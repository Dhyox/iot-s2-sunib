# program utama: serial ke ESP32 + dashboard flask (localhost:5000)
# NOTE: tutup serial monitor arduino dulu, kalo ga port COM-nya kepake
import logging
import threading
import time
from collections import Counter, defaultdict

import serial
from flask import Flask, jsonify, render_template, request

import database as db
import config
from config import (BAUD_RATE, DASHBOARD_HOST, DASHBOARD_PORT, RFID_CARDS,
                    SCAN_WINDOW_SEC, SERIAL_PORT)
from face_engine import FaceEngine, open_camera

# gate kebuka kalo minimal 3 dari 5 frame nebak orang yg sama
VOTE_FRAMES = getattr(config, "VOTE_FRAMES", 5)
VOTES_NEEDED = getattr(config, "VOTES_NEEDED", 3)
FRAME_INTERVAL_SEC = getattr(config, "FRAME_INTERVAL_SEC", 0.15)


class GateBridge:
    def __init__(self):
        self.engine = FaceEngine()
        if not self.engine.known:
            print("PERINGATAN: belum ada wajah terdaftar. Jalankan enroll.py dulu.")
        self.cap = open_camera()
        self.ser = None
        self.write_lock = threading.Lock()
        self.connected = False
        self.cancel_scan = threading.Event()
        self.scan_thread = None

    def _open_serial(self):
        s = serial.Serial()
        s.port = SERIAL_PORT
        s.baudrate = BAUD_RATE
        s.timeout = 0.2
        s.dtr = False   # kalo ga di-set, ESP32 ke-reset tiap port dibuka
        s.rts = False
        s.open()
        return s

    def run(self):
        while True:
            try:
                self.ser = self._open_serial()
                self.connected = True
                print(f"Terhubung ke ESP32 di {SERIAL_PORT}")
                self._read_loop()
            except (serial.SerialException, OSError) as e:
                self.connected = False
                print(f"Serial error: {e}. Mencoba lagi dalam 3 detik...")
                self._close_serial()   # port lama harus ditutup, kalo ga COM-nya ke-lock
                time.sleep(3)

    def _close_serial(self):
        with self.write_lock:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            self.ser = None

    def _read_loop(self):
        while True:
            raw = self.ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore").strip()
            if line:
                self._handle(line)

    def send(self, msg):
        with self.write_lock:
            if not (self.ser and self.ser.is_open):
                print(f"  gagal kirim {msg}: ESP32 ga konek")
                return False
            try:
                self.ser.write((msg + "\n").encode())
            except (serial.SerialException, OSError) as e:
                print(f"  gagal kirim {msg}: {e}")
                return False
        print(f"  -> {msg}")
        return True

    def _handle(self, line):
        if line.startswith("#"):
            print(f"[ESP32] {line[1:].strip()}")
            return
        print(f"<- {line}")

        if line == "READY":
            return
        if line == "SCAN":
            self._start_face_scan()
        elif line == "CANCEL":
            self.cancel_scan.set()
        elif line.startswith("RFID,"):
            self._check_card(line.split(",", 1)[1].strip().upper())
        elif line == "DOOR,OPEN":
            self.cancel_scan.set()   # udh kebuka (kartu/dashboard), stop scan
            db.log_door("open")
        elif line == "DOOR,CLOSED":
            db.log_door("closed")

    def _check_card(self, uid):
        name = RFID_CARDS.get(uid)
        if name:
            self.send(f"RFID,OK,{name}")
            db.log_access("rfid", "granted", identity=name, uid=uid)
        else:
            self.send("RFID,FAIL")
            db.log_access("rfid", "denied", uid=uid, note="kartu tidak terdaftar")

    def _start_face_scan(self):
        # thread sendiri biar RFID tetep bisa dijawab pas lagi scan
        if self.scan_thread and self.scan_thread.is_alive():
            self.cancel_scan.set()
            self.scan_thread.join(timeout=2)
        self.cancel_scan.clear()
        self.scan_thread = threading.Thread(target=self._face_scan, daemon=True)
        self.scan_thread.start()

    def _face_scan(self):
        if not self.cap.isOpened():
            self.cap = open_camera()
        for _ in range(5):          # buang frame lama di buffer
            self.cap.read()

        deadline = time.time() + SCAN_WINDOW_SEC
        votes, vote_scores = Counter(), defaultdict(list)
        outcomes = Counter()
        judged, last_judged = 0, 0.0
        closest_name, closest_score = None, None

        while time.time() < deadline and judged < VOTE_FRAMES:
            if self.cancel_scan.is_set():
                print("  (scan wajah dihentikan, akses sudah selesai)")
                return
            ok, frame = self.cap.read()
            if not ok or time.time() - last_judged < FRAME_INTERVAL_SEC:
                continue

            r = self.engine.identify(frame)
            if r.status == "no_face":
                continue

            last_judged = time.time()
            judged += 1
            outcomes[r.status] += 1
            print(f"  frame {judged}: {r.status:<7} {r.name} {r.score:.1f}")
            if r.name and (closest_score is None or r.score > closest_score):
                closest_name, closest_score = r.name, r.score

            if r.status == "match":
                votes[r.name] += 1
                vote_scores[r.name].append(r.score)
                if votes[r.name] >= VOTES_NEEDED:
                    break
            leader = max(votes.values(), default=0)
            if leader + (VOTE_FRAMES - judged) < VOTES_NEEDED:
                break               # udh ga mungkin menang, gausah lanjut

        if self.cancel_scan.is_set():
            return

        winner, n = votes.most_common(1)[0] if votes else (None, 0)
        if winner and n >= VOTES_NEEDED:
            score = sum(vote_scores[winner]) / n
            self.send(f"FACE,OK,{winner}")
            db.log_access("face", "granted", identity=winner, score=round(score, 1),
                          note=f"{n}/{judged} frame sepakat")
            return

        self.send("FACE,FAIL")
        if judged == 0:
            note = "tidak ada wajah terdeteksi"
        elif outcomes["unknown"]:
            note = "wajah tidak dikenal"
        else:
            note = "frame tidak sepakat"
        if closest_name:
            note += f" (terdekat {closest_name}, {votes[closest_name]}/{judged} frame)"
        db.log_access("face", "denied",
                      score=round(closest_score, 1) if closest_score is not None else None,
                      note=note)

    def manual_open(self):
        if not self.send("OPEN"):
            return False
        db.log_access("manual", "granted", identity="Dashboard",
                      note="dibuka dari dashboard")
        return True


# dashboard
app = Flask(__name__)
bridge: GateBridge = None


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(door=db.door_status(),
                   esp32_connected=bridge.connected,
                   today=db.today_summary())


@app.route("/api/logs")
def api_logs():
    limit = min(request.args.get("limit", 50, type=int), 500)
    return jsonify(db.recent_logs(limit))


@app.route("/api/stats")
def api_stats():
    days = min(request.args.get("days", 14, type=int), 90)
    return jsonify(daily=db.daily_stats(days),
                   methods=db.method_stats(days),
                   hourly=db.hourly_stats(days))


@app.route("/api/unlock", methods=["POST"])
def api_unlock():
    if not bridge.connected:
        return jsonify(ok=False, error="ESP32 tidak terhubung"), 503
    if not bridge.manual_open():
        return jsonify(ok=False, error="Gagal kirim ke ESP32"), 503
    return jsonify(ok=True)


def main():
    global bridge
    db.init_db()
    bridge = GateBridge()
    threading.Thread(target=bridge.run, daemon=True).start()

    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # biar terminal ga spam log polling
    print(f"Dashboard: http://localhost:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT,
            debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()

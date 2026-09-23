"""
Smart Gate - aplikasi laptop.

Satu program menjalankan dua hal sekaligus:
  1. Bridge serial ke ESP32 (thread terpisah): menjawab SCAN dengan face
     recognition, mengecek UID RFID, dan mencatat semuanya ke database.
  2. Server HTTP (Flask) untuk dashboard di http://localhost:5000

Jalankan: python main.py
(Tutup Serial Monitor Arduino IDE dulu, port COM tidak bisa dipakai bersamaan.)
"""
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

# Voting multi-frame (bisa ditimpa dari config.py)
VOTE_FRAMES = getattr(config, "VOTE_FRAMES", 5)          # frame berkualitas yang dinilai
VOTES_NEEDED = getattr(config, "VOTES_NEEDED", 3)        # minimal frame yang sepakat
FRAME_INTERVAL_SEC = getattr(config, "FRAME_INTERVAL_SEC", 0.15)  # jeda antar frame dinilai


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

    # ---------- koneksi serial ----------
    def _open_serial(self):
        s = serial.Serial()
        s.port = SERIAL_PORT
        s.baudrate = BAUD_RATE
        s.timeout = 0.2
        s.dtr = False   # cegah ESP32 ter-reset saat port dibuka
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
            except serial.SerialException as e:
                self.connected = False
                print(f"Serial error: {e}. Mencoba lagi dalam 3 detik...")
                time.sleep(3)

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
            if self.ser and self.ser.is_open:
                self.ser.write((msg + "\n").encode())
                print(f"  -> {msg}")

    # ---------- pesan dari ESP32 ----------
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
            self.cancel_scan.set()   # gate sudah terbuka (kartu/dashboard), hentikan scan wajah
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
        # Face scan jalan di thread sendiri, supaya RFID tetap dijawab saat scan
        if self.scan_thread and self.scan_thread.is_alive():
            self.cancel_scan.set()
            self.scan_thread.join(timeout=2)
        self.cancel_scan.clear()
        self.scan_thread = threading.Thread(target=self._face_scan, daemon=True)
        self.scan_thread.start()

    def _face_scan(self):
        """
        Voting multi-frame: nilai hingga VOTE_FRAMES frame berkualitas bagus.
        Gate dibuka hanya kalau minimal VOTES_NEEDED frame sepakat pada orang yang sama.
        """
        if not self.cap.isOpened():
            self.cap = open_camera()
        for _ in range(5):          # buang frame lama di buffer webcam
            self.cap.read()

        deadline = time.time() + SCAN_WINDOW_SEC
        votes, vote_scores = Counter(), defaultdict(list)
        outcomes = Counter()
        judged, last_judged = 0, 0.0
        skipped = Counter()         # alasan frame dilewati (kualitas)
        closest_name, closest_score = None, 0.0

        while time.time() < deadline and judged < VOTE_FRAMES:
            if self.cancel_scan.is_set():
                print("  (scan wajah dihentikan, akses sudah selesai)")
                return
            ok, frame = self.cap.read()
            if not ok or time.time() - last_judged < FRAME_INTERVAL_SEC:
                continue

            r = self.engine.identify(frame)
            if r.status in ("no_face", "low_quality"):
                if r.status == "low_quality":   # wajah ada tapi tidak layak
                    skipped[r.reason.split(" (")[0]] += 1
                continue

            last_judged = time.time()
            judged += 1
            outcomes[r.status] += 1
            second = f", ke-2 {r.second_name} {r.second_score:.2f}" if r.second_name else ""
            print(f"  frame {judged}: {r.status:<9} {r.name} {r.score:.2f}{second}")
            if r.score > closest_score:
                closest_name, closest_score = r.name, r.score

            if r.status == "match":
                votes[r.name] += 1
                vote_scores[r.name].append(r.score)
                if votes[r.name] >= VOTES_NEEDED:
                    break
            leader = max(votes.values(), default=0)
            if leader + (VOTE_FRAMES - judged) < VOTES_NEEDED:
                break               # sudah tidak mungkin mencapai VOTES_NEEDED

        if self.cancel_scan.is_set():
            return

        winner, n = votes.most_common(1)[0] if votes else (None, 0)
        if winner and n >= VOTES_NEEDED:
            score = sum(vote_scores[winner]) / n
            self.send(f"FACE,OK,{winner}")
            db.log_access("face", "granted", identity=winner, score=round(score, 3),
                          note=f"{n}/{judged} frame sepakat")
            return

        self.send("FACE,FAIL")
        if judged == 0:
            reason = skipped.most_common(1)[0][0] if skipped else "tidak ada wajah terdeteksi"
            note = f"tidak ada frame layak: {reason}"
        elif outcomes["ambiguous"] and outcomes["ambiguous"] >= outcomes["unknown"]:
            note = "ragu: skor mirip beberapa orang"
        elif outcomes["unknown"]:
            note = "wajah tidak dikenal"
        else:
            note = "frame tidak sepakat"
        if closest_name and judged:
            note += f" (terdekat {closest_name}, {votes[closest_name]}/{judged} frame)"
        db.log_access("face", "denied",
                      score=round(closest_score, 3) if judged else None, note=note)

    # ---------- dari dashboard ----------
    def manual_open(self):
        self.send("OPEN")
        db.log_access("manual", "granted", identity="Dashboard",
                      note="dibuka dari dashboard")


# ================= HTTP / dashboard =================
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
    bridge.manual_open()
    return jsonify(ok=True)


def main():
    global bridge
    db.init_db()
    bridge = GateBridge()
    threading.Thread(target=bridge.run, daemon=True).start()

    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # sembunyikan log polling
    print(f"Dashboard: http://localhost:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT,
            debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()

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

import cv2
import serial
from flask import Flask, jsonify, render_template, request

import database as db
from config import (BAUD_RATE, CAMERA_INDEX, DASHBOARD_HOST, DASHBOARD_PORT,
                    RFID_CARDS, SCAN_WINDOW_SEC, SERIAL_PORT)
from face_engine import FaceEngine


class GateBridge:
    def __init__(self):
        self.engine = FaceEngine()
        if not self.engine.known:
            print("PERINGATAN: belum ada wajah terdaftar. Jalankan enroll.py dulu.")
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        self.ser = None
        self.write_lock = threading.Lock()
        self.connected = False

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
            self._face_scan()
        elif line.startswith("RFID,"):
            self._check_card(line.split(",", 1)[1].strip().upper())
        elif line == "DOOR,OPEN":
            db.log_door("open")
        elif line == "DOOR,CLOSED":
            db.log_door("closed")

    def _check_card(self, uid):
        name = RFID_CARDS.get(uid)
        if name:
            self.send(f"OK,{name}")
            db.log_access("rfid", "granted", identity=name, uid=uid)
        else:
            self.send("FAIL")
            db.log_access("rfid", "denied", uid=uid, note="kartu tidak terdaftar")

    def _face_scan(self):
        if not self.cap.isOpened():
            self.cap.open(CAMERA_INDEX)
        for _ in range(5):          # buang frame lama di buffer webcam
            self.cap.read()

        deadline = time.time() + SCAN_WINDOW_SEC
        saw_face, best_unknown = False, 0.0
        while time.time() < deadline:
            ok, frame = self.cap.read()
            if not ok:
                continue
            status, name, score = self.engine.identify(frame)
            if status == "match":
                self.send(f"OK,{name}")
                db.log_access("face", "granted", identity=name,
                              score=round(score, 3))
                return
            if status == "unknown":
                saw_face = True
                best_unknown = max(best_unknown, score)

        self.send("FAIL")
        if saw_face:
            db.log_access("face", "denied", score=round(best_unknown, 3),
                          note="wajah tidak dikenal")
        else:
            db.log_access("face", "denied", note="tidak ada wajah terdeteksi")

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

"""Pengaturan utama. Ubah bagian ini sesuai laptopmu."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --- Serial ke ESP32 ---
# Windows: "COM3", "COM5", ...   Linux: "/dev/ttyUSB0"   macOS: "/dev/cu.usbserial-xxxx"
# Cek port dengan: python -m serial.tools.list_ports
SERIAL_PORT = "COM8"
BAUD_RATE = 115200

# --- Webcam ---
CAMERA_INDEX = 0          # 0 = webcam bawaan laptop, 1 = webcam eksternal
SCAN_WINDOW_SEC = 5.0     # lama mencoba mengenali wajah setelah SCAN
                          # (harus < SESSION_MS di ESP32, yaitu 12 detik)

# --- Face recognition (Haar cascade + LBPH) ---
HAAR_CASCADE = BASE_DIR / "models" / "haarcascade_frontalface_default.xml"
FACE_DATA_DIR = BASE_DIR / "data"          # foto wajah: data/<nama>/<n>.jpg
LBPH_MODEL_FILE = BASE_DIR / "trainer.yml"
LBPH_LABELS_FILE = BASE_DIR / "labels.json"  # id LBPH -> nama
# Jarak LBPH maksimum agar dianggap cocok (0 = sama persis, makin kecil makin mirip).
# Turunkan (mis. 60) kalau orang lain ikut dikenali.
LBPH_THRESHOLD = 70

# --- RFID: UID kartu -> nama pemilik ---
# Disimpan di rfid_cards.json (tidak di-commit, repo publik). Buat dari contoh:
#   copy rfid_cards.example.json rfid_cards.json
# UID yang belum terdaftar akan muncul di log dashboard sebagai "Tidak dikenal",
# salin UID-nya ke rfid_cards.json lalu restart app.
RFID_CARDS_FILE = BASE_DIR / "rfid_cards.json"


def _load_rfid_cards():
    if not RFID_CARDS_FILE.exists():
        print(f"PERINGATAN: {RFID_CARDS_FILE.name} tidak ada, semua kartu akan ditolak.")
        return {}
    with open(RFID_CARDS_FILE, encoding="utf-8") as f:
        return {uid.upper(): name for uid, name in json.load(f).items()}


RFID_CARDS = _load_rfid_cards()

# --- Database & dashboard ---
DB_FILE = BASE_DIR / "gate.db"
DASHBOARD_HOST = "0.0.0.0"   # 0.0.0.0 = bisa dibuka dari HP di WiFi yang sama
DASHBOARD_PORT = 5000

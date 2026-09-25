# setting utama, sesuaiin sama laptop masing2
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# serial ESP32
# cek port: python -m serial.tools.list_ports  (windows COMx, linux /dev/ttyUSB0)
SERIAL_PORT = "COM8"
BAUD_RATE = 115200

# webcam
CAMERA_INDEX = 0          # 0 = webcam laptop, 1 = webcam external
SCAN_WINDOW_SEC = 5.0     # jangan lebih dari SESSION_MS di ESP32 (12 detik)

# face recognition
HAAR_CASCADE = BASE_DIR / "models" / "haarcascade_frontalface_default.xml"
FACE_DATA_DIR = BASE_DIR / "data"
LBPH_MODEL_FILE = BASE_DIR / "trainer.yml"
LBPH_LABELS_FILE = BASE_DIR / "labels.json"
# makin kecil makin ketat. turunin kalo orang lain ikut kebuka
LBPH_THRESHOLD = 70

# kartu RFID ada di rfid_cards.json (ga di-commit soalnya repo publik)
# copy dari rfid_cards.example.json terus isi UID kartunya
RFID_CARDS_FILE = BASE_DIR / "rfid_cards.json"


def _load_rfid_cards():
    if not RFID_CARDS_FILE.exists():
        print(f"PERINGATAN: {RFID_CARDS_FILE.name} tidak ada, semua kartu akan ditolak.")
        return {}
    with open(RFID_CARDS_FILE, encoding="utf-8") as f:
        return {uid.upper(): name for uid, name in json.load(f).items()}


RFID_CARDS = _load_rfid_cards()

# database & dashboard
DB_FILE = BASE_DIR / "gate.db"
DASHBOARD_HOST = "0.0.0.0"   # biar bisa dibuka dari HP (1 wifi)
DASHBOARD_PORT = 5000

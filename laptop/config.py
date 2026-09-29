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

# face recognition (insightface / ArcFace)
# model kedownload otomatis ke models/ pas pertama kali jalan
FACE_MODEL = "buffalo_l"  # ganti "buffalo_s" kalo laptopnya kelemotan
EMBEDDINGS_FILE = BASE_DIR / "embeddings.pkl"
# skor = cosine similarity (0-1), makin tinggi makin mirip
# naikin kalo orang lain ikut kebuka, turunin kalo muka sendiri sering ditolak
# nilai pastinya cek pake evaluate.py
MATCH_THRESHOLD = 0.40
MATCH_MARGIN = 0.08       # skor harus beda segini sama orang ke-2, biar ga ketuker

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

# dashboard online (vercel). isi di cloud.json (ga di-commit, ada key rahasia):
#   {"url": "https://nama-project.vercel.app", "key": "INGEST_KEY yg sama kayak di vercel"}
# kalo file-nya ga ada, upload ke online dimatiin aja, dashboard lokal tetep jalan
CLOUD_FILE = BASE_DIR / "cloud.json"


def _load_cloud():
    if not CLOUD_FILE.exists():
        return None
    with open(CLOUD_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("url") or not cfg.get("key"):
        print(f"PERINGATAN: {CLOUD_FILE.name} harus ada url & key, upload online dimatiin.")
        return None
    return cfg


CLOUD = _load_cloud()

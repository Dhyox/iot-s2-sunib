# """Pengaturan utama. Ubah bagian ini sesuai laptopmu."""
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
                          # (harus < FACE_TIMEOUT_MS di ESP32, yaitu 10 detik)

# --- Face recognition (OpenCV YuNet + SFace) ---
MODEL_DIR = BASE_DIR / "models"
DETECTOR_MODEL = MODEL_DIR / "face_detection_yunet_2023mar.onnx"
RECOGNIZER_MODEL = MODEL_DIR / "face_recognition_sface_2021dec.onnx"
EMBEDDINGS_FILE = BASE_DIR / "embeddings.pkl"
# Cosine similarity minimum agar dianggap cocok.
# 0.363 = nilai rekomendasi OpenCV. Naikkan (mis. 0.45) kalau sering salah kenal.
MATCH_THRESHOLD = 0.363

# --- RFID: UID kartu -> nama pemilik ---
# UID yang belum terdaftar akan muncul di log dashboard sebagai "Tidak dikenal",
# salin UID-nya ke sini lalu restart app.
RFID_CARDS = {
    "BFADA3D0": "Miyano",
    "FFFD9ED0": "DhyoxB",
    "10942060": "MasterCard",
}

# --- Database & dashboard ---
DB_FILE = BASE_DIR / "gate.db"
DASHBOARD_HOST = "0.0.0.0"   # 0.0.0.0 = bisa dibuka dari HP di WiFi yang sama
DASHBOARD_PORT = 5000

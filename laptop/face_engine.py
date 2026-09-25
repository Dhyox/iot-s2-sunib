"""
Deteksi & pengenalan wajah dengan Haar cascade + LBPH (OpenCV contrib).

Alur per frame:
  Haar cascade (deteksi) -> ambil wajah terbesar -> grayscale 200x200
  -> LBPH predict -> jarak < LBPH_THRESHOLD = cocok

Butuh paket opencv-contrib-python (untuk cv2.face).
Data wajah & model dibuat oleh: python enroll.py <nama>
"""
import json
import os
from dataclasses import dataclass

import cv2

import config

FACE_SIZE = (200, 200)
LBPH_THRESHOLD = getattr(config, "LBPH_THRESHOLD", 70)
CAMERA_INDEX = getattr(config, "CAMERA_INDEX", 0)
CAMERA_WIDTH = getattr(config, "CAMERA_WIDTH", 1280)
CAMERA_HEIGHT = getattr(config, "CAMERA_HEIGHT", 720)


@dataclass
class Result:
    status: str               # no_face | unknown | match
    name: str = None          # kandidat terbaik
    score: float = 0.0        # 100 - jarak LBPH (makin tinggi makin mirip)
    reason: str = ""


def open_camera(index=None):
    """Buka webcam dengan resolusi lebih tinggi (default OpenCV sering 640x480)."""
    index = CAMERA_INDEX if index is None else index
    if os.name == "nt":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)   # lebih cepat di Windows
    else:
        cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    return cap


def load_detector():
    path = config.HAAR_CASCADE
    if not path.exists():   # cadangan: file bawaan OpenCV
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(path))
    if detector.empty():
        raise SystemExit(f"Haar cascade tidak bisa dibaca: {path}")
    return detector


def create_recognizer():
    if not hasattr(cv2, "face"):
        raise SystemExit("cv2.face tidak ada. Jalankan: pip uninstall opencv-python "
                         "lalu pip install opencv-contrib-python")
    return cv2.face.LBPHFaceRecognizer_create()


def detect_faces(detector, gray):
    faces = detector.detectMultiScale(gray, scaleFactor=1.3, minNeighbors=5)
    return list(faces) if len(faces) else []


def largest(faces):
    return max(faces, key=lambda f: f[2] * f[3]) if faces else None


def crop(gray, face):
    x, y, w, h = face
    return cv2.resize(gray[y:y + h, x:x + w], FACE_SIZE)


class FaceEngine:
    def __init__(self):
        self.detector = load_detector()
        self.recognizer = create_recognizer()
        self.labels = {}      # id LBPH -> nama
        if config.LBPH_MODEL_FILE.exists() and config.LBPH_LABELS_FILE.exists():
            self.recognizer.read(str(config.LBPH_MODEL_FILE))
            with open(config.LBPH_LABELS_FILE, encoding="utf-8") as f:
                self.labels = {int(k): v for k, v in json.load(f).items()}

    @property
    def known(self):
        return self.labels

    def predict(self, face_img):
        """(nama, jarak) untuk crop wajah grayscale 200x200."""
        label, distance = self.recognizer.predict(face_img)
        return self.labels.get(label), float(distance)

    def identify(self, frame):
        if not self.labels:
            return Result("unknown", reason="belum ada wajah terdaftar")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face = largest(detect_faces(self.detector, gray))
        if face is None:
            return Result("no_face", reason="tidak ada wajah terdeteksi")

        name, distance = self.predict(crop(gray, face))
        # skor = 100 - jarak (makin tinggi makin mirip), sama seperti "Match %"
        score = 100.0 - distance
        if name is None or distance >= LBPH_THRESHOLD:
            return Result("unknown", name, score,
                          reason=f"jarak {distance:.0f} di atas ambang {LBPH_THRESHOLD}")
        return Result("match", name, score)

"""
Deteksi, filter kualitas, dan pengenalan wajah (OpenCV YuNet + SFace).

Alur per frame:
  YuNet (deteksi + 5 landmark) -> filter kualitas (ukuran, arah wajah, ketajaman)
  -> alignCrop 112x112 -> SFace (embedding 128-d, dinormalisasi)
  -> skor per orang = rata-rata TOP_K kemiripan tertinggi dengan sampel orang itu
  -> keputusan: ambang (MATCH_THRESHOLD) + selisih dengan kandidat kedua (MATCH_MARGIN)

Semua pengaturan baru punya nilai default di bawah. Untuk mengubahnya, cukup
tambahkan baris dengan nama yang sama di config.py (tidak perlu mengedit file ini).
"""
import os
import pickle
from dataclasses import dataclass

import cv2
import numpy as np

import config


def _cfg(name, default):
    return getattr(config, name, default)


# ---------- Pengaturan (bisa ditimpa dari config.py) ----------
MATCH_THRESHOLD = _cfg("MATCH_THRESHOLD", 0.45)   # skor minimum agar dianggap cocok
MATCH_MARGIN = _cfg("MATCH_MARGIN", 0.08)         # selisih minimum dgn kandidat kedua
TOP_K = _cfg("TOP_K", 3)                          # jumlah sampel terbaik yg dirata-rata
MIN_FACE_PX = _cfg("MIN_FACE_PX", 90)             # lebar wajah minimum (piksel)
MIN_SHARPNESS = _cfg("MIN_SHARPNESS", 40.0)       # variance of Laplacian minimum
MAX_YAW = _cfg("MAX_YAW", 0.35)                   # batas wajah menyamping (0 = lurus)
CAMERA_INDEX = _cfg("CAMERA_INDEX", 0)
CAMERA_WIDTH = _cfg("CAMERA_WIDTH", 1280)
CAMERA_HEIGHT = _cfg("CAMERA_HEIGHT", 720)


@dataclass
class Result:
    status: str               # no_face | low_quality | unknown | ambiguous | match
    name: str = None          # kandidat terbaik
    score: float = 0.0
    second_name: str = None   # kandidat kedua
    second_score: float = 0.0
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


def normalize(v):
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


class FaceEngine:
    def __init__(self):
        for path in (config.DETECTOR_MODEL, config.RECOGNIZER_MODEL):
            if not path.exists():
                raise SystemExit(f"Model {path.name} tidak ada. "
                                 "Jalankan dulu: python download_models.py")
        self.detector = cv2.FaceDetectorYN.create(
            str(config.DETECTOR_MODEL), "", (320, 320), 0.9, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(
            str(config.RECOGNIZER_MODEL), "")
        self.known = self.load_embeddings()
        self.build_gallery()

    # ---------- database wajah ----------
    @staticmethod
    def load_embeddings():
        if config.EMBEDDINGS_FILE.exists():
            with open(config.EMBEDDINGS_FILE, "rb") as f:
                return pickle.load(f)
        return {}

    def save_embeddings(self):
        with open(config.EMBEDDINGS_FILE, "wb") as f:
            pickle.dump(self.known, f)
        self.build_gallery()

    def build_gallery(self):
        """Matriks sampel ternormalisasi per orang, untuk pencocokan cepat."""
        self.gallery = {name: np.stack([normalize(s) for s in samples])
                        for name, samples in self.known.items() if samples}

    # ---------- deteksi & kualitas ----------
    def detect_all(self, frame):
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        return [] if faces is None else list(faces)

    @staticmethod
    def largest(faces):
        return max(faces, key=lambda f: f[2] * f[3]) if faces else None

    def quality(self, frame, face):
        """
        Cek kualitas wajah. Return (ok, alasan, aligned_crop, metrik).
        Metrik: lebar wajah, yaw (arah menyamping), ketajaman.
        """
        metrics = {"width": float(face[2]), "yaw": 0.0, "sharpness": 0.0}
        if face[2] < MIN_FACE_PX:
            return False, f"wajah terlalu jauh/kecil ({int(face[2])} px)", None, metrics

        right_eye, left_eye, nose = face[4:6], face[6:8], face[8:10]
        eye_vec = left_eye - right_eye
        eye_dist = float(np.linalg.norm(eye_vec))
        if eye_dist < 1:
            return False, "landmark tidak valid", None, metrics
        eye_mid = (right_eye + left_eye) / 2
        # posisi hidung di sepanjang sumbu mata: ~0 kalau menghadap lurus
        yaw = float(np.dot(nose - eye_mid, eye_vec / eye_dist) / eye_dist)
        metrics["yaw"] = yaw
        if abs(yaw) > MAX_YAW:
            return False, "wajah terlalu menyamping", None, metrics

        aligned = self.recognizer.alignCrop(frame, face)
        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        metrics["sharpness"] = sharpness
        if sharpness < MIN_SHARPNESS:
            return False, f"gambar buram ({sharpness:.0f})", None, metrics
        return True, "", aligned, metrics

    # ---------- embedding & pencocokan ----------
    def embed_aligned(self, aligned):
        return normalize(self.recognizer.feature(aligned))

    def scores(self, feat):
        """[(nama, skor)] urut dari tertinggi. Skor = rata-rata TOP_K kemiripan terbaik."""
        ranked = []
        for name, samples in self.gallery.items():
            sims = samples @ feat                       # cosine similarity
            k = min(TOP_K, len(sims))
            ranked.append((name, float(np.sort(sims)[-k:].mean())))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

    @staticmethod
    def decide(ranked):
        if not ranked:
            return Result("unknown", reason="belum ada wajah terdaftar")
        best_name, best = ranked[0]
        second_name, second = ranked[1] if len(ranked) > 1 else (None, 0.0)
        r = Result("match", best_name, best, second_name, second)
        if best < MATCH_THRESHOLD:
            r.status, r.reason = "unknown", "skor di bawah ambang"
        elif second_name is not None and best - second < MATCH_MARGIN:
            r.status, r.reason = "ambiguous", "skor terlalu dekat dengan orang lain"
        return r

    def identify(self, frame):
        face = self.largest(self.detect_all(frame))
        if face is None:
            return Result("no_face", reason="tidak ada wajah terdeteksi")
        ok, reason, aligned, _ = self.quality(frame, face)
        if not ok:
            return Result("low_quality", reason=reason)
        return self.decide(self.scores(self.embed_aligned(aligned)))

    @staticmethod
    def draw_face(frame, face, color=(0, 200, 0)):
        x, y, w, h = face[:4].astype(np.int32)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

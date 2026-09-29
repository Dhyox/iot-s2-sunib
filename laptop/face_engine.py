# face recognition pake insightface (deteksi SCRFD + ArcFace)
# ArcFace udh di-train sama pembuatnya, jadi kita ga training apa2.
# enroll cuma nyimpen embedding (512 angka) tiap orang, terus dibandingin pake cosine similarity
import os
import pickle
from dataclasses import dataclass

import cv2
import numpy as np

import config

FACE_MODEL = getattr(config, "FACE_MODEL", "buffalo_l")
MATCH_THRESHOLD = getattr(config, "MATCH_THRESHOLD", 0.40)
MATCH_MARGIN = getattr(config, "MATCH_MARGIN", 0.08)
TOP_K = getattr(config, "TOP_K", 3)                  # skor = rata2 3 sampel paling mirip
MIN_FACE_PX = getattr(config, "MIN_FACE_PX", 60)     # lebar muka minimal
MIN_DET_SCORE = getattr(config, "MIN_DET_SCORE", 0.6)
CAMERA_INDEX = getattr(config, "CAMERA_INDEX", 0)
CAMERA_WIDTH = getattr(config, "CAMERA_WIDTH", 1280)
CAMERA_HEIGHT = getattr(config, "CAMERA_HEIGHT", 720)
EMBEDDING_DIM = 512


@dataclass
class Result:
    status: str               # no_face / low_quality / unknown / ambiguous / match
    name: str = None
    score: float = 0.0
    second_name: str = None
    second_score: float = 0.0
    reason: str = ""


def open_camera(index=None):
    index = CAMERA_INDEX if index is None else index
    if os.name == "nt":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)   # di windows lebih cepet kebuka
    else:
        cap = cv2.VideoCapture(index)
    # default opencv cuma 640x480
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # biar ga dapet frame basi pas prosesnya lama
    return cap


class FaceEngine:
    def __init__(self):
        try:
            from insightface.app import FaceAnalysis
        except ImportError:
            raise SystemExit("insightface belum ke-install. Jalankan: pip install -r requirements.txt")
        # root=BASE_DIR -> modelnya disimpen di models/<FACE_MODEL>
        self.app = FaceAnalysis(name=FACE_MODEL, root=str(config.BASE_DIR),
                                providers=["CPUExecutionProvider"],
                                allowed_modules=["detection", "recognition"])
        self.app.prepare(ctx_id=-1, det_size=(640, 640))
        self.app.get(np.zeros((480, 640, 3), np.uint8))   # pemanasan, panggilan pertama suka lama
        self.known = self.load_embeddings()
        self.build_gallery()

    @staticmethod
    def load_embeddings():
        if not config.EMBEDDINGS_FILE.exists():
            return {}
        with open(config.EMBEDDINGS_FILE, "rb") as f:
            known = pickle.load(f)
        # embeddings.pkl dari engine lama (SFace, 128 angka) ga kepake
        bad = [n for n, s in known.items() if any(np.shape(e) != (EMBEDDING_DIM,) for e in s)]
        for n in bad:
            print(f"PERINGATAN: data wajah {n} formatnya lama, enroll ulang ya.")
            del known[n]
        return known

    def save_embeddings(self):
        with open(config.EMBEDDINGS_FILE, "wb") as f:
            pickle.dump(self.known, f)
        self.build_gallery()

    def build_gallery(self):
        self.gallery = {name: np.stack(samples).astype(np.float32)
                        for name, samples in self.known.items() if samples}

    def detect(self, frame):
        return self.app.get(frame)

    @staticmethod
    def largest(faces):
        if not faces:
            return None
        return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

    @staticmethod
    def quality(face):
        width = face.bbox[2] - face.bbox[0]
        if width < MIN_FACE_PX:
            return False, f"wajah terlalu jauh ({int(width)} px)"
        if face.det_score < MIN_DET_SCORE:
            return False, "wajah kurang jelas"
        return True, ""

    def scores(self, emb):
        # [(nama, skor)] urut dari paling mirip
        ranked = []
        for name, samples in self.gallery.items():
            sims = samples @ emb
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
            r.status, r.reason = "ambiguous", "skornya deket sama orang lain"
        return r

    def identify(self, frame):
        face = self.largest(self.detect(frame))
        if face is None:
            return Result("no_face", reason="tidak ada wajah terdeteksi")
        ok, reason = self.quality(face)
        if not ok:
            return Result("low_quality", reason=reason)
        return self.decide(self.scores(face.normed_embedding))

    @staticmethod
    def draw_face(frame, face, color=(0, 200, 0)):
        x1, y1, x2, y2 = face.bbox.astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

"""Deteksi + pengenalan wajah dengan OpenCV YuNet dan SFace."""
import pickle

import cv2
import numpy as np

from config import (DETECTOR_MODEL, EMBEDDINGS_FILE, MATCH_THRESHOLD,
                    RECOGNIZER_MODEL)


class FaceEngine:
    def __init__(self):
        for path in (DETECTOR_MODEL, RECOGNIZER_MODEL):
            if not path.exists():
                raise SystemExit(f"Model {path.name} tidak ada. "
                                 "Jalankan dulu: python download_models.py")
        self.detector = cv2.FaceDetectorYN.create(
            str(DETECTOR_MODEL), "", (320, 320), 0.9, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(RECOGNIZER_MODEL), "")
        self.known = self.load_embeddings()

    # ---------- database wajah ----------
    @staticmethod
    def load_embeddings():
        if EMBEDDINGS_FILE.exists():
            with open(EMBEDDINGS_FILE, "rb") as f:
                return pickle.load(f)
        return {}

    def save_embeddings(self):
        with open(EMBEDDINGS_FILE, "wb") as f:
            pickle.dump(self.known, f)

    # ---------- deteksi & embedding ----------
    def largest_face(self, frame):
        """Kembalikan baris deteksi wajah terbesar, atau None."""
        h, w = frame.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return None
        return max(faces, key=lambda f: f[2] * f[3])

    def embed(self, frame, face):
        aligned = self.recognizer.alignCrop(frame, face)
        return self.recognizer.feature(aligned).copy()

    # ---------- pencocokan ----------
    def identify(self, frame):
        """
        Return (status, nama, skor):
          status = "no_face" | "unknown" | "match"
        """
        face = self.largest_face(frame)
        if face is None:
            return "no_face", None, 0.0

        feat = self.embed(frame, face)
        best_name, best_score = None, -1.0
        for name, samples in self.known.items():
            for sample in samples:
                score = self.recognizer.match(
                    feat, sample, cv2.FaceRecognizerSF_FR_COSINE)
                if score > best_score:
                    best_name, best_score = name, score

        if best_name is not None and best_score >= MATCH_THRESHOLD:
            return "match", best_name, float(best_score)
        return "unknown", None, float(max(best_score, 0.0))

    @staticmethod
    def draw_face(frame, face, color=(0, 200, 0)):
        x, y, w, h = face[:4].astype(np.int32)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

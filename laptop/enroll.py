"""
Daftarkan wajah (Haar cascade + LBPH).
Gabungan dari script collecting data + training.

  python enroll.py Carlson             # ambil 100 foto, GANTI foto lama Carlson, lalu training
  python enroll.py Carlson --append    # tambah foto tanpa menghapus yang lama
  python enroll.py Carlson --samples 150
  python enroll.py --train             # training ulang dari folder data/ saja
  python enroll.py --list              # daftar orang & jumlah foto
  python enroll.py --remove Carlson

Foto tersimpan di data/<nama>/<n>.jpg (grayscale 200x200), model di trainer.yml,
nama tiap id di labels.json. Tekan Q atau Enter untuk batal.

Tips: ambil foto di lokasi gate, dengan cahaya yang sama seperti saat dipakai.
"""
import argparse
import json
import shutil
import time

import cv2
import numpy as np

import config
from face_engine import (FACE_SIZE, create_recognizer, crop, detect_faces, largest,
                         load_detector, open_camera)

DATA_DIR = config.FACE_DATA_DIR
DEFAULT_SAMPLES = getattr(config, "ENROLL_SAMPLES", 100)


def person_dirs():
    if not DATA_DIR.exists():
        return []
    return sorted(d for d in DATA_DIR.iterdir() if d.is_dir() and any(d.glob("*.jpg")))


def capture(name, n, interval=0.0, title="Enroll wajah"):
    """Ambil n crop wajah dari webcam, minimal `interval` detik antar foto.
    Return list kosong kalau dibatalkan."""
    detector = load_detector()
    cap = open_camera()
    if not cap.isOpened():
        raise SystemExit("Webcam tidak bisa dibuka. Cek CAMERA_INDEX di config.py")

    print(f"Mengambil {n} foto untuk {name}. Lihat ke kamera, gerakkan kepala sedikit.")
    faces_taken, last = [], 0.0
    while len(faces_taken) < n:
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face = largest(detect_faces(detector, gray))
        if face is not None and time.time() - last >= interval:
            faces_taken.append(crop(gray, face))
            last = time.time()
        if face is not None:
            x, y, w, h = face
            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 200, 0), 2)
        cv2.putText(frame, f"{name}: {len(faces_taken)}/{n}", (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
        cv2.imshow(title, frame)
        if cv2.waitKey(1) & 0xFF in (ord("q"), 13):
            print("Dibatalkan.")
            faces_taken = []
            break

    cap.release()
    cv2.destroyAllWindows()
    return faces_taken


def save_faces(name, faces, append):
    folder = DATA_DIR / name
    if folder.exists() and not append:
        shutil.rmtree(folder)
    folder.mkdir(parents=True, exist_ok=True)
    start = len(list(folder.glob("*.jpg")))
    for i, face in enumerate(faces, start + 1):
        cv2.imwrite(str(folder / f"{i}.jpg"), face)


def train():
    """Latih LBPH dari semua foto di data/ lalu simpan trainer.yml + labels.json."""
    faces, ids, labels = [], [], {}
    for label, folder in enumerate(person_dirs(), 1):
        labels[label] = folder.name
        for path in sorted(folder.glob("*.jpg")):
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                print(f"  lewati {path.name}: tidak bisa dibaca")
                continue
            faces.append(cv2.resize(img, FACE_SIZE))
            ids.append(label)

    if not faces:
        config.LBPH_MODEL_FILE.unlink(missing_ok=True)
        config.LBPH_LABELS_FILE.unlink(missing_ok=True)
        print("Tidak ada foto di data/. Model dihapus.")
        return

    print(f"Training LBPH dengan {len(faces)} foto...")
    recognizer = create_recognizer()
    recognizer.train(faces, np.array(ids))
    recognizer.write(str(config.LBPH_MODEL_FILE))
    with open(config.LBPH_LABELS_FILE, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2)
    print(f"Selesai. {len(labels)} orang: {', '.join(labels.values())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove")
    args = ap.parse_args()

    if args.list:
        dirs = person_dirs()
        if not dirs:
            print("Belum ada wajah terdaftar.")
        for d in dirs:
            print(f"{d.name}: {len(list(d.glob('*.jpg')))} foto")
        return

    if args.remove:
        folder = DATA_DIR / args.remove
        if not folder.exists():
            raise SystemExit(f"{args.remove} tidak terdaftar.")
        shutil.rmtree(folder)
        print(f"{args.remove} dihapus.")
        train()
        return

    if args.train:
        train()
        return

    if not args.name:
        ap.error("isi nama, contoh: python enroll.py Carlson")

    faces = capture(args.name, args.samples)
    if len(faces) < args.samples:
        print("Enroll tidak selesai, data lama tidak diubah.")
        return
    save_faces(args.name, faces, args.append)
    train()


if __name__ == "__main__":
    main()

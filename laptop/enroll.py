"""
Daftarkan wajah seseorang.

  python enroll.py Miyano            # ambil 5 sampel (default)
  python enroll.py Budi --samples 8
  python enroll.py --list            # lihat siapa saja yang terdaftar
  python enroll.py --remove Budi

Di jendela kamera: tekan SPASI untuk ambil sampel, Q untuk batal.
Tips: ambil sampel dengan sedikit variasi sudut/ekspresi dan pencahayaan
yang mirip dengan lokasi gate.
"""
import argparse

import cv2

from config import CAMERA_INDEX
from face_engine import FaceEngine


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove")
    args = ap.parse_args()

    engine = FaceEngine()

    if args.list:
        for name, samples in engine.known.items():
            print(f"{name}: {len(samples)} sampel")
        if not engine.known:
            print("Belum ada wajah terdaftar.")
        return

    if args.remove:
        engine.known.pop(args.remove, None)
        engine.save_embeddings()
        print(f"{args.remove} dihapus.")
        return

    if not args.name:
        ap.error("isi nama, contoh: python enroll.py Miyano")

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        raise SystemExit("Webcam tidak bisa dibuka. Cek CAMERA_INDEX di config.py")

    collected = []
    print(f"Mendaftarkan {args.name}. SPASI = ambil sampel, Q = batal.")
    while len(collected) < args.samples:
        ok, frame = cap.read()
        if not ok:
            continue
        face = engine.largest_face(frame)
        preview = frame.copy()
        if face is not None:
            engine.draw_face(preview, face)
        cv2.putText(preview, f"{args.name}: {len(collected)}/{args.samples}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 0), 2)
        cv2.imshow("Enroll wajah", preview)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            print("Dibatalkan.")
            break
        if key == ord(" "):
            if face is None:
                print("  Wajah tidak terdeteksi, coba lagi.")
                continue
            collected.append(engine.embed(frame, face))
            print(f"  Sampel {len(collected)} tersimpan.")

    cap.release()
    cv2.destroyAllWindows()

    if len(collected) == args.samples:
        engine.known.setdefault(args.name, []).extend(collected)
        engine.save_embeddings()
        print(f"Selesai. {args.name} sekarang punya "
              f"{len(engine.known[args.name])} sampel.")


if __name__ == "__main__":
    main()

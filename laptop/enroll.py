# daftarin wajah
# python enroll.py Carlson            -> 20 sampel, ikutin instruksi di layar (sampel lama ditimpa)
# python enroll.py Carlson --append   -> nambah sampel
# python enroll.py --list             -> daftar orang + seberapa mirip sama orang lain
# python enroll.py --remove Carlson
# enroll di tempat gate ya, kamera & cahayanya sama kayak pas dipake
import argparse
import time

import cv2
import numpy as np

import config
from face_engine import MATCH_THRESHOLD, TOP_K, FaceEngine, open_camera

DEFAULT_SAMPLES = getattr(config, "ENROLL_SAMPLES", 20)
CAPTURE_INTERVAL = 0.5    # jeda antar sampel biar posenya beda2
PROMPTS = [
    "Lihat lurus ke kamera",
    "Toleh sedikit ke kiri",
    "Toleh sedikit ke kanan",
    "Angkat dagu sedikit",
    "Turunkan dagu sedikit",
    "Ganti ekspresi (senyum/netral)",
]
GREEN, ORANGE, RED = (0, 200, 0), (0, 165, 255), (0, 0, 255)


def put(img, text, y, color=(255, 255, 255)):
    cv2.putText(img, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
    cv2.putText(img, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)


# return list embedding, [] kalo dicancel (Q / enter)
def capture(engine, name, n, interval=CAPTURE_INTERVAL, prompts=True, title="Enroll wajah"):
    cap = open_camera()
    if not cap.isOpened():
        raise SystemExit("Webcam tidak bisa dibuka. Cek CAMERA_INDEX di config.py")

    samples, last, start = [], 0.0, time.time()
    while len(samples) < n:
        ok, frame = cap.read()
        if not ok:
            continue
        preview = frame.copy()
        faces = engine.detect(frame)
        status, color = "", ORANGE

        if not faces:
            status = "Wajah tidak terdeteksi"
        elif len(faces) > 1:
            status, color = "Hanya boleh 1 wajah di kamera", RED
            for f in faces:
                engine.draw_face(preview, f, RED)
        else:
            face = faces[0]
            good, reason = engine.quality(face)
            engine.draw_face(preview, face, GREEN if good else ORANGE)
            if not good:
                status = reason
            elif time.time() - start < 2:
                status = "Bersiap..."
            elif time.time() - last >= interval:
                samples.append(face.normed_embedding.astype(np.float32))
                last = time.time()
                status, color = "Sampel tersimpan", GREEN

        put(preview, f"{name}: {len(samples)}/{n}", 30, GREEN)
        if prompts:
            put(preview, PROMPTS[min(len(samples) * len(PROMPTS) // n, len(PROMPTS) - 1)], 60)
        if status:
            put(preview, status, 90, color)
        cv2.imshow(title, preview)
        if cv2.waitKey(1) & 0xFF in (ord("q"), 13):
            print("Dibatalkan.")
            samples = []
            break

    cap.release()
    cv2.destroyAllWindows()
    return samples


def consistency(samples):
    # rata2 kemiripan tiap sampel sama sampel lain punya orang yg sama
    S = np.stack(samples)
    sim = S @ S.T
    np.fill_diagonal(sim, np.nan)
    return np.nanmean(sim, axis=1)


def cross_check(engine, name):
    # seberapa mirip orang ini sama orang lain yg terdaftar (makin kecil makin bagus)
    own = engine.gallery.get(name)
    if own is None:
        return
    for other, others in engine.gallery.items():
        if other == name:
            continue
        k = min(TOP_K, len(others))
        scores = [float(np.sort(others @ f)[-k:].mean()) for f in own]
        worst = max(scores)
        flag = "  <-- RAWAN KETUKER" if worst >= MATCH_THRESHOLD else ""
        print(f"    vs {other:<12} rata-rata {np.mean(scores):.2f}, "
              f"tertinggi {worst:.2f}{flag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove")
    args = ap.parse_args()

    engine = FaceEngine()

    if args.list:
        if not engine.known:
            print("Belum ada wajah terdaftar.")
        for name, samples in engine.known.items():
            c = consistency(samples).mean() if len(samples) > 1 else float("nan")
            print(f"{name}: {len(samples)} sampel, konsistensi {c:.2f}")
            cross_check(engine, name)
        return

    if args.remove:
        if args.remove not in engine.known:
            raise SystemExit(f"{args.remove} tidak terdaftar.")
        del engine.known[args.remove]
        engine.save_embeddings()
        print(f"{args.remove} dihapus.")
        return

    if not args.name:
        ap.error("isi nama, contoh: python enroll.py Carlson")

    print(f"Mendaftarkan {args.name} ({args.samples} sampel). Ikuti instruksi di layar.")
    new = capture(engine, args.name, args.samples)
    if len(new) < args.samples:
        print("Enroll tidak selesai, data lama tidak diubah.")
        return

    if args.append:
        engine.known.setdefault(args.name, []).extend(new)
    else:
        engine.known[args.name] = new
    engine.save_embeddings()

    samples = engine.known[args.name]
    c = consistency(samples).mean() if len(samples) > 1 else float("nan")
    print(f"Selesai. {args.name}: {len(samples)} sampel, konsistensi {c:.2f}")
    print("  Kemiripan dengan orang lain:")
    cross_check(engine, args.name)


if __name__ == "__main__":
    main()

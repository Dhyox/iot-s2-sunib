"""
Daftarkan wajah dengan capture otomatis + filter kualitas.

  python enroll.py Miyano              # GANTI sampel lama Miyano dengan sampel baru
  python enroll.py Miyano --append     # tambah sampel tanpa menghapus yang lama
  python enroll.py Miyano --samples 30
  python enroll.py --list              # daftar orang, konsistensi, dan kemiripan antar orang
  python enroll.py --remove Miyano

Ikuti instruksi di layar (lihat lurus, toleh sedikit, dst). Sampel hanya diambil
kalau hanya ada 1 wajah, cukup dekat, tidak buram, dan tidak terlalu menyamping.
Tekan Q untuk batal.

Tips: lakukan enroll di lokasi gate, dengan webcam, jarak, dan cahaya yang sama
seperti saat dipakai.
"""
import argparse
import time

import cv2
import numpy as np

import config
from face_engine import TOP_K, MATCH_THRESHOLD, FaceEngine, normalize, open_camera

DEFAULT_SAMPLES = getattr(config, "ENROLL_SAMPLES", 20)
CAPTURE_INTERVAL = 0.5    # detik antar sampel
DUPLICATE_SIM = 0.92      # sampel yang lebih mirip dari ini dianggap duplikat
OUTLIER_DROP = 0.10       # buang sampel yang jauh di bawah konsistensi median
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


def capture(engine, name, n):
    cap = open_camera()
    if not cap.isOpened():
        raise SystemExit("Webcam tidak bisa dibuka. Cek CAMERA_INDEX di config.py")

    samples, last_capture, start = [], 0.0, time.time()
    while len(samples) < n:
        ok, frame = cap.read()
        if not ok:
            continue
        preview = frame.copy()
        prompt = PROMPTS[min(len(samples) * len(PROMPTS) // n, len(PROMPTS) - 1)]
        faces = engine.detect_all(frame)
        status, status_color = "", ORANGE

        if not faces:
            status = "Wajah tidak terdeteksi"
        elif len(faces) > 1:
            status, status_color = "Hanya boleh 1 wajah di kamera", RED
            for f in faces:
                engine.draw_face(preview, f, RED)
        else:
            face = faces[0]
            good, reason, aligned, m = engine.quality(frame, face)
            engine.draw_face(preview, face, GREEN if good else ORANGE)
            put(preview, f"lebar {m['width']:.0f}px  yaw {m['yaw']:+.2f}  "
                         f"tajam {m['sharpness']:.0f}", preview.shape[0] - 15)
            if not good:
                status = reason
            elif time.time() - start < 2:
                status = "Bersiap..."
            elif time.time() - last_capture >= CAPTURE_INTERVAL:
                feat = engine.embed_aligned(aligned)
                if samples and max(float(s @ feat) for s in samples) > DUPLICATE_SIM:
                    status = "Mirip sampel sebelumnya, ubah posisi sedikit"
                else:
                    samples.append(feat)
                    last_capture = time.time()
                    status, status_color = "Sampel tersimpan", GREEN

        put(preview, f"{name}: {len(samples)}/{n}", 30, GREEN)
        put(preview, prompt, 60)
        if status:
            put(preview, status, 90, status_color)
        cv2.imshow("Enroll wajah", preview)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("Dibatalkan.")
            samples = []
            break

    cap.release()
    cv2.destroyAllWindows()
    return samples


def consistency(samples):
    """Rata-rata kemiripan tiap sampel terhadap sampel lain milik orang yang sama."""
    S = np.stack([normalize(s) for s in samples])
    sim = S @ S.T
    np.fill_diagonal(sim, np.nan)
    return np.nanmean(sim, axis=1)


def remove_outliers(samples):
    if len(samples) < 5:
        return samples, 0
    mean_sim = consistency(samples)
    keep = mean_sim >= np.median(mean_sim) - OUTLIER_DROP
    return [s for s, k in zip(samples, keep) if k], int((~keep).sum())


def cross_check(engine, name):
    """Seberapa mirip orang ini dengan orang lain yang terdaftar (makin rendah makin baik)."""
    own = engine.gallery.get(name)
    if own is None:
        return
    for other, others in engine.gallery.items():
        if other == name:
            continue
        k = min(TOP_K, len(others))
        scores = [float(np.sort(others @ f)[-k:].mean()) for f in own]
        worst = max(scores)
        flag = "  <-- RAWAN TERTUKAR" if worst >= MATCH_THRESHOLD else ""
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
        engine.known.pop(args.remove, None)
        engine.save_embeddings()
        print(f"{args.remove} dihapus.")
        return

    if not args.name:
        ap.error("isi nama, contoh: python enroll.py Miyano")

    print(f"Mendaftarkan {args.name} ({args.samples} sampel). Ikuti instruksi di layar.")
    new = capture(engine, args.name, args.samples)
    if len(new) < args.samples:
        print("Enroll tidak selesai, data lama tidak diubah.")
        return

    new, dropped = remove_outliers(new)
    if dropped:
        print(f"  {dropped} sampel dibuang karena tidak konsisten dengan sampel lain.")

    if args.append:
        engine.known.setdefault(args.name, []).extend(new)
    else:
        engine.known[args.name] = new
    engine.save_embeddings()

    samples = engine.known[args.name]
    print(f"Selesai. {args.name}: {len(samples)} sampel, "
          f"konsistensi {consistency(samples).mean():.2f}")
    print("  Kemiripan dengan orang lain:")
    cross_check(engine, args.name)


if __name__ == "__main__":
    main()

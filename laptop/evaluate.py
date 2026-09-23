"""
Evaluasi akurasi & kalibrasi threshold face recognition.

1) Kumpulkan data uji. Lakukan di SESI BERBEDA dari enroll (jam/hari lain),
   supaya hasilnya jujur:
     python evaluate.py collect Miyano      # orang yang terdaftar
     python evaluate.py collect tamu1       # orang yang TIDAK terdaftar (uji false accept)
   Tiap orang ~40 frame, tersimpan di folder eval_data/.

2) Buat laporan:
     python evaluate.py report
   -> ringkasan di terminal + grafik eval_report.png

Istilah:
  genuine  = skor wajah terhadap dirinya sendiri (harus tinggi)
  impostor = skor wajah terhadap orang lain (harus rendah)
  FAR      = False Accept Rate, orang salah diterima
  FRR      = False Reject Rate, orang benar ditolak
  EER      = titik saat FAR = FRR
"""
import argparse
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

import face_engine as fe
from config import BASE_DIR
from face_engine import FaceEngine, open_camera

EVAL_DIR = BASE_DIR / "eval_data"


# ---------------- collect ----------------
def collect(name, n):
    engine = FaceEngine()
    cap = open_camera()
    if not cap.isOpened():
        raise SystemExit("Webcam tidak bisa dibuka.")
    feats, last = [], 0.0
    print(f"Merekam {n} frame untuk '{name}'. Bergerak natural seperti saat lewat gate. Q = batal.")
    while len(feats) < n:
        ok, frame = cap.read()
        if not ok:
            continue
        preview = frame.copy()
        faces = engine.detect_all(frame)
        msg = "Wajah tidak terdeteksi" if not faces else ""
        if len(faces) > 1:
            msg = "Hanya boleh 1 wajah"
        elif len(faces) == 1:
            good, reason, aligned, _ = engine.quality(frame, faces[0])
            engine.draw_face(preview, faces[0], (0, 200, 0) if good else (0, 165, 255))
            msg = reason
            if good and time.time() - last > 0.25:
                feats.append(engine.embed_aligned(aligned))
                last = time.time()
        cv2.putText(preview, f"{name}: {len(feats)}/{n}  {msg}", (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 0), 2)
        cv2.imshow("Kumpulkan data uji", preview)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            print("Dibatalkan.")
            cap.release()
            cv2.destroyAllWindows()
            return
    cap.release()
    cv2.destroyAllWindows()
    EVAL_DIR.mkdir(exist_ok=True)
    np.save(EVAL_DIR / f"{name}.npy", np.stack(feats))
    print(f"Tersimpan: eval_data/{name}.npy")


# ---------------- report ----------------
def rates(genuine, impostor, t):
    far = float(np.mean(impostor >= t)) if len(impostor) else 0.0
    frr = float(np.mean(genuine < t)) if len(genuine) else 0.0
    return far, frr


def analyse(engine, probes):
    """Hitung skor genuine/impostor, keputusan per frame, dan margin."""
    genuine, impostor = [], []
    confusion = defaultdict(Counter)
    wrong_margins, right_margins = [], []
    for true_name, feats in probes.items():
        for f in feats:
            ranked = engine.scores(fe.normalize(f))
            for name, s in ranked:
                (genuine if name == true_name else impostor).append(s)
            r = engine.decide(ranked)
            if r.status == "match":
                pred = r.name
            elif r.status == "ambiguous":
                pred = "(ditolak: ragu)"
            else:
                pred = "(ditolak)"
            confusion[true_name][pred] += 1
            if true_name in engine.gallery and len(ranked) > 1:
                margin = ranked[0][1] - ranked[1][1]
                (right_margins if ranked[0][0] == true_name else wrong_margins).append(margin)
    return (np.array(genuine), np.array(impostor), confusion,
            np.array(right_margins), np.array(wrong_margins))


def report():
    engine = FaceEngine()
    if not engine.gallery:
        raise SystemExit("Belum ada wajah terdaftar. Jalankan enroll.py dulu.")
    files = sorted(EVAL_DIR.glob("*.npy")) if EVAL_DIR.exists() else []
    if not files:
        raise SystemExit("Belum ada data uji. Jalankan: python evaluate.py collect <nama>")
    probes = {f.stem: np.load(f) for f in files}

    genuine, impostor, confusion, right_m, wrong_m = analyse(engine, probes)
    enrolled = [n for n in probes if n in engine.gallery]
    strangers = [n for n in probes if n not in engine.gallery]

    print("=" * 64)
    print(f"Terdaftar di galeri : {', '.join(engine.gallery)}")
    print(f"Data uji terdaftar  : {', '.join(enrolled) or '-'}")
    print(f"Data uji asing      : {', '.join(strangers) or '- (disarankan ada, untuk uji false accept)'}")
    print(f"Skor genuine  : n={len(genuine)}, rata-rata {genuine.mean() if len(genuine) else 0:.3f}")
    print(f"Skor impostor : n={len(impostor)}, rata-rata {impostor.mean():.3f}, "
          f"tertinggi {impostor.max():.3f}")

    # --- sweep threshold ---
    ts = np.linspace(0, 1, 1001)
    curve = np.array([rates(genuine, impostor, t) for t in ts])
    far, frr = curve[:, 0], curve[:, 1]
    rec = {}
    if len(genuine):
        i = int(np.argmin(np.abs(far - frr)))
        print(f"\nEER ≈ {(far[i] + frr[i]) / 2:.1%} pada threshold {ts[i]:.3f}")
    for target in (0.01, 0.001):
        idx = np.where(far <= target)[0]
        if len(idx):
            t = ts[idx[0]]
            rec[target] = t
            print(f"Threshold untuk FAR ≤ {target:.1%}: {t:.3f}  (FRR {rates(genuine, impostor, t)[1]:.1%})")
    cur_far, cur_frr = rates(genuine, impostor, fe.MATCH_THRESHOLD)
    print(f"Threshold sekarang {fe.MATCH_THRESHOLD:.3f}: FAR {cur_far:.1%}, FRR {cur_frr:.1%}"
          "  (per frame, sebelum voting)")

    # --- margin ---
    if len(wrong_m):
        suggest = float(np.percentile(wrong_m, 95))
        lost = float(np.mean(right_m < suggest)) if len(right_m) else 0.0
        print(f"\nTop-1 salah orang: {len(wrong_m)} frame, margin 95% di bawah {suggest:.3f}")
        print(f"  MATCH_MARGIN {suggest:.3f} akan menolak ~95% kasus salah orang, "
              f"dan {lost:.1%} frame yang sebenarnya benar")
    else:
        print("\nTidak ada frame dengan top-1 salah orang. MATCH_MARGIN sekarang sudah cukup.")

    # --- tabel keputusan ---
    print(f"\nKeputusan per frame (threshold {fe.MATCH_THRESHOLD}, margin {fe.MATCH_MARGIN}):")
    for true_name in probes:
        total = sum(confusion[true_name].values())
        parts = ", ".join(f"{p} {c / total:.0%}"
                          for p, c in confusion[true_name].most_common())
        tag = "" if true_name in engine.gallery else " [asing]"
        print(f"  {true_name + tag:<20} -> {parts}")
    print("Catatan: voting multi-frame di main.py menekan error lebih jauh dari angka per frame ini.")

    plot(genuine, impostor, ts, far, frr, rec)


def plot(genuine, impostor, ts, far, frr, rec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    bins = np.linspace(-0.2, 1, 61)
    a1.hist(impostor, bins=bins, alpha=0.6, label="impostor (orang lain)", color="#C23A2B")
    if len(genuine):
        a1.hist(genuine, bins=bins, alpha=0.6, label="genuine (diri sendiri)", color="#1E8C4E")
    a1.axvline(fe.MATCH_THRESHOLD, color="black", ls="--",
               label=f"threshold sekarang {fe.MATCH_THRESHOLD:.2f}")
    if 0.01 in rec:
        a1.axvline(rec[0.01], color="#2C6FB7", ls=":", label=f"FAR ≤ 1%: {rec[0.01]:.2f}")
    a1.set_xlabel("skor kemiripan")
    a1.set_ylabel("jumlah frame")
    a1.set_title("Distribusi skor")
    a1.legend()

    a2.plot(ts, far, label="FAR", color="#C23A2B")
    a2.plot(ts, frr, label="FRR", color="#1E8C4E")
    a2.axvline(fe.MATCH_THRESHOLD, color="black", ls="--")
    a2.set_xlabel("threshold")
    a2.set_ylabel("rate")
    a2.set_title("FAR / FRR terhadap threshold")
    a2.legend()

    fig.tight_layout()
    out = BASE_DIR / "eval_report.png"
    fig.savefig(out, dpi=130)
    print(f"\nGrafik tersimpan: {out.name}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect")
    c.add_argument("name")
    c.add_argument("--frames", type=int, default=40)
    sub.add_parser("report")
    args = ap.parse_args()
    if args.cmd == "collect":
        collect(args.name, args.frames)
    else:
        report()


if __name__ == "__main__":
    main()

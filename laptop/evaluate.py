# buat ngetes akurasi + nyari LBPH_THRESHOLD yg pas (buat laporan juga)
#   python evaluate.py collect Carlson   (yg udh di-enroll)
#   python evaluate.py collect tamu1     (orang luar, buat cek false accept)
#   python evaluate.py report
# collect-nya jangan barengan sama enroll, beda hari/jam biar hasilnya jujur
#
# FAR = gate kebuka buat orang yg salah, FRR = orangnya bener tapi ditolak
import argparse
from collections import Counter, defaultdict

import numpy as np

import face_engine as fe
from config import BASE_DIR
from enroll import capture
from face_engine import FaceEngine

EVAL_DIR = BASE_DIR / "eval_data"


def collect(name, n):
    faces = capture(name, n, interval=0.25, title="Kumpulkan data uji")
    if len(faces) < n:
        return
    EVAL_DIR.mkdir(exist_ok=True)
    np.save(EVAL_DIR / f"{name}.npy", np.stack(faces))
    print(f"Tersimpan: eval_data/{name}.npy")


def load_probes():
    probes = {}
    for f in (sorted(EVAL_DIR.glob("*.npy")) if EVAL_DIR.exists() else []):
        data = np.load(f)
        if data.ndim != 3 or data.shape[1:] != fe.FACE_SIZE[::-1]:   # file versi SFace dulu
            print(f"Lewati {f.name}: format lama/tidak cocok, kumpulkan ulang.")
            continue
        probes[f.stem] = data
    return probes


def rates(dist, correct, enrolled, t):
    accepted = dist < t
    far = float(np.mean(accepted & ~correct))
    frr = float(np.mean(~(accepted & correct)[enrolled])) if enrolled.any() else 0.0
    return far, frr


def report():
    engine = FaceEngine()
    if not engine.known:
        raise SystemExit("Belum ada wajah terdaftar. Jalankan enroll.py dulu.")
    probes = load_probes()
    if not probes:
        raise SystemExit("Belum ada data uji. Jalankan: python evaluate.py collect <nama>")

    registered = set(engine.known.values())
    true_names, pred_names, dists = [], [], []
    for true_name, faces in probes.items():
        for face in faces:
            name, dist = engine.predict(face)
            true_names.append(true_name)
            pred_names.append(name)
            dists.append(dist)
    dist = np.array(dists)
    correct = np.array([t == p for t, p in zip(true_names, pred_names)])
    enrolled = np.array([t in registered for t in true_names])

    enrolled_names = [n for n in probes if n in registered]
    strangers = [n for n in probes if n not in registered]
    print("=" * 64)
    print(f"Terdaftar di model  : {', '.join(sorted(registered))}")
    print(f"Data uji terdaftar  : {', '.join(enrolled_names) or '-'}")
    print(f"Data uji asing      : {', '.join(strangers) or '- (disarankan ada, untuk uji false accept)'}")
    if correct.any():
        print(f"Jarak saat tebakan BENAR : n={correct.sum()}, rata-rata {dist[correct].mean():.1f}, "
              f"terjauh {dist[correct].max():.1f}")
    if (~correct).any():
        print(f"Jarak saat tebakan SALAH : n={(~correct).sum()}, rata-rata {dist[~correct].mean():.1f}, "
              f"terdekat {dist[~correct].min():.1f}")

    ts = np.arange(0, 150.5, 0.5)
    curve = np.array([rates(dist, correct, enrolled, t) for t in ts])
    far, frr = curve[:, 0], curve[:, 1]
    rec = {}
    if enrolled.any() and (~correct).any():
        i = int(np.argmin(np.abs(far - frr)))
        print(f"\nEER ≈ {(far[i] + frr[i]) / 2:.1%} pada threshold {ts[i]:.1f}")
    for target in (0.01, 0.001):
        idx = np.where(far <= target)[0]
        if len(idx):
            t = ts[idx[-1]]       # ambil yg paling longgar tapi FAR masih aman
            rec[target] = t
            print(f"Threshold untuk FAR ≤ {target:.1%}: {t:.1f}  "
                  f"(FRR {rates(dist, correct, enrolled, t)[1]:.1%})")
    cur_far, cur_frr = rates(dist, correct, enrolled, fe.LBPH_THRESHOLD)
    print(f"Threshold sekarang {fe.LBPH_THRESHOLD}: FAR {cur_far:.1%}, FRR {cur_frr:.1%}"
          "  (per frame, sebelum voting)")

    confusion = defaultdict(Counter)
    for t, p, d in zip(true_names, pred_names, dist):
        confusion[t][p if d < fe.LBPH_THRESHOLD else "(ditolak)"] += 1
    print(f"\nKeputusan per frame (threshold {fe.LBPH_THRESHOLD}):")
    for true_name in probes:
        total = sum(confusion[true_name].values())
        parts = ", ".join(f"{p} {c / total:.0%}"
                          for p, c in confusion[true_name].most_common())
        tag = "" if true_name in registered else " [asing]"
        print(f"  {true_name + tag:<20} -> {parts}")
    print("Catatan: voting multi-frame di main.py menekan error lebih jauh dari angka per frame ini.")

    plot(dist, correct, ts, far, frr, rec)


def plot(dist, correct, ts, far, frr, rec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.5))
    bins = np.linspace(0, max(150, float(dist.max()) + 5), 61)
    if (~correct).any():
        a1.hist(dist[~correct], bins=bins, alpha=0.6,
                label="tebakan salah (orang lain/asing)", color="#C23A2B")
    if correct.any():
        a1.hist(dist[correct], bins=bins, alpha=0.6, label="tebakan benar", color="#1E8C4E")
    a1.axvline(fe.LBPH_THRESHOLD, color="black", ls="--",
               label=f"threshold sekarang {fe.LBPH_THRESHOLD}")
    if 0.01 in rec:
        a1.axvline(rec[0.01], color="#2C6FB7", ls=":", label=f"FAR ≤ 1%: {rec[0.01]:.1f}")
    a1.set_xlabel("jarak LBPH (makin kecil makin mirip)")
    a1.set_ylabel("jumlah frame")
    a1.set_title("Distribusi jarak")
    a1.legend()

    a2.plot(ts, far, label="FAR", color="#C23A2B")
    a2.plot(ts, frr, label="FRR", color="#1E8C4E")
    a2.axvline(fe.LBPH_THRESHOLD, color="black", ls="--")
    a2.set_xlabel("threshold (jarak)")
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

# Smart Gate: Face Recognition + RFID

ESP32 DevKit V1 mengendalikan gate (RFID RC522, HC-SR04, servo, buzzer, LED merah & hijau).
Laptop menjalankan face recognition lewat webcam (InsightFace / ArcFace), mencatat log
ke SQLite, dan menyajikan dashboard HTTP. Keduanya terhubung lewat kabel USB (serial).

```
iot-s2-sunib/
├── esp32_gate/esp32_gate.ino   firmware ESP32
└── laptop/
    ├── config.py               port COM, kamera, threshold
    ├── rfid_cards.example.json contoh daftar kartu RFID (salin ke rfid_cards.json)
    ├── face_engine.py          deteksi + pengenalan wajah (InsightFace / ArcFace)
    ├── enroll.py               daftarkan wajah
    ├── evaluate.py             uji akurasi & kalibrasi threshold
    ├── database.py             SQLite: log akses & status pintu
    ├── main.py                 bridge serial + server dashboard
    ├── templates/dashboard.html
    └── static/chart.umd.min.js Chart.js lokal (dashboard jalan tanpa internet)
```

File yang dibuat saat dipakai (tidak di-commit): `rfid_cards.json` (kartu RFID),
`models/` (model InsightFace, diunduh otomatis), `embeddings.pkl` (data wajah),
`gate.db` (log), `eval_data/` dan `eval_report.png` (evaluasi).

## Cara kerja

1. Tidak ada orang → semua LED mati.
2. Orang mendekat ≤ 60 cm (3 pembacaan berturut-turut) → **LED merah nyala**, sesi 12 detik dimulai.
3. Selama sesi, **wajah dan kartu aktif bersamaan**. Mana yang berhasil duluan, gate terbuka.
   - Wajah: laptop menilai hingga 5 frame berisi wajah, gate dibuka kalau minimal 3 frame
     sepakat pada orang yang sama (skor ≥ `MATCH_THRESHOLD` dan cukup beda dari orang ke-2).
     Gagal → **merah kedip 3x** + bunyi 3x, lalu masih ada 2 detik untuk tempel kartu.
   - Kartu: UID dicek laptop ke `rfid_cards.json`. Kalau laptop tidak menjawab dalam 1,5 detik,
     ESP32 memakai daftar cadangan `LOCAL_CARDS`. Kartu salah → **merah kedip 3x** + bip pendek, sesi lanjut.
   - Sesi habis tanpa berhasil → bip panjang, LED mati, jeda 2 detik. Kalau orangnya masih
     di depan sensor, sesi baru langsung mulai lagi.
4. Akses diterima → **LED hijau nyala**, servo terbuka 5 detik, lalu tertutup (LED mati) + jeda 2 detik.
   Orang harus lewat/menjauh dulu sebelum sesi baru.

### Face recognition

ArcFace sudah di-train oleh pembuatnya dengan jutaan wajah, jadi tidak ada training di sini.
Setiap wajah diubah jadi *embedding* (512 angka). Enroll = menyimpan ~20 embedding per orang
dari pose yang berbeda-beda. Saat scan, embedding wajah dibandingkan (cosine similarity)
dengan semua orang terdaftar. Skor tiap orang = rata-rata 3 sampel paling mirip.

## Wiring

| Komponen | Pin ESP32 |
|---|---|
| RC522 | SS 5, RST 4, SCK 18, MISO 19, MOSI 23, 3.3V |
| HC-SR04 | TRIG 26, ECHO 27 (pakai voltage divider) |
| Servo | 13 |
| Buzzer | 21 |
| LED merah | 32 (pakai resistor) |
| LED hijau | 33 (pakai resistor) |

## 1. ESP32

1. Arduino IDE → Boards Manager: install **esp32** (Espressif). Pilih board **DOIT ESP32 DEVKIT V1**.
2. Library Manager: install **MFRC522** dan **ESP32Servo**.
3. Buka `esp32_gate/esp32_gate.ino`, cek bagian setting (buzzer pasif?), lalu upload.
4. Tes cepat lewat Serial Monitor (115200, line ending "Newline"): harus muncul `READY`.
   Ketik `OPEN` untuk tes servo, atau dekatkan tangan ke sensor lalu ketik `FACE,OK,Tes`.
5. **Tutup Serial Monitor** sebelum menjalankan program Python.

## 2. Laptop (Python 3.9+)

```bash
cd laptop
pip uninstall -y opencv-contrib-python   # sisa versi LBPH, bentrok sama opencv-python
pip install -r requirements.txt
python -m serial.tools.list_ports        # cari port ESP32, isi SERIAL_PORT di config.py
copy rfid_cards.example.json rfid_cards.json   # lalu isi UID kartu asli (Linux/macOS: cp)
python enroll.py Carlson                 # pertama kali jalan: unduh model (~300 MB)
python enroll.py Vincent
python main.py
```

Buka dashboard di http://localhost:5000. Dari HP di WiFi yang sama: `http://<IP-laptop>:5000`.

UID kartu yang belum terdaftar muncul di log dashboard sebagai "Tidak dikenal".
Salin UID-nya ke `rfid_cards.json`, lalu restart `main.py`.

### Data yang tidak di-commit

Repo ini publik, jadi data berikut hanya disimpan di laptop gate (sudah ada di `.gitignore`):
`rfid_cards.json` (UID kartu asli), `embeddings.pkl` (data wajah), `gate.db` (log akses),
`models/`, `eval_data/`. Setiap laptop harus enroll wajah dan mengisi `rfid_cards.json` sendiri.

### Mengelola wajah

```bash
python enroll.py Carlson             # GANTI data lama Carlson, 20 sampel
python enroll.py Carlson --append    # tambah sampel tanpa menghapus yang lama
python enroll.py Carlson --samples 30
python enroll.py --list              # daftar orang + kemiripan dengan orang lain
python enroll.py --remove Carlson
```

Ikuti instruksi di layar (lihat lurus, toleh sedikit, angkat dagu, ganti ekspresi).
Yang penting **variasi pose**, bukan jumlah foto. Enroll di lokasi gate, dengan webcam,
jarak, dan cahaya yang sama seperti saat dipakai. Tekan Q atau Enter untuk batal.

`--list` menampilkan seberapa mirip tiap orang dengan orang lain. Kalau muncul
`RAWAN KETUKER`, enroll ulang orang tersebut atau naikkan `MATCH_THRESHOLD`.

### Evaluasi akurasi

Kumpulkan data uji di **sesi berbeda** dari enroll (jam/hari lain), termasuk orang yang
**tidak terdaftar** untuk menguji false accept:

```bash
python evaluate.py collect Carlson   # orang terdaftar, 40 frame
python evaluate.py collect tamu1     # orang asing
python evaluate.py report            # FAR, FRR, EER, saran threshold & margin + eval_report.png
```

## Protokol serial (115200 baud, satu baris per pesan)

| Arah | Pesan | Arti |
|---|---|---|
| ESP32 → laptop | `READY` | ESP32 baru menyala |
| ESP32 → laptop | `SCAN` | ada orang di depan sensor, mulai face recognition |
| ESP32 → laptop | `CANCEL` | sesi selesai (gate terbuka / waktu habis), hentikan scan |
| ESP32 → laptop | `RFID,<uid>` | kartu ditempel, minta verifikasi |
| ESP32 → laptop | `DOOR,OPEN` / `DOOR,CLOSED` | status gate berubah |
| ESP32 → laptop | `# ...` | pesan debug |
| laptop → ESP32 | `FACE,OK,<nama>` / `FACE,FAIL` | hasil face recognition |
| laptop → ESP32 | `RFID,OK,<nama>` / `RFID,FAIL` | hasil verifikasi kartu |
| laptop → ESP32 | `OPEN` | buka manual dari dashboard |

Pesan lain yang diterima laptop (misalnya data serial yang terpotong) diabaikan dan
ditampilkan sebagai `<- ?? ...`.

## API dashboard

| Endpoint | Isi |
|---|---|
| `GET /api/status` | status pintu, koneksi ESP32, ringkasan hari ini |
| `GET /api/logs?limit=50` | log akses terbaru |
| `GET /api/stats?days=14` | akses per hari, per metode, per jam |
| `POST /api/unlock` | buka gate dari dashboard |

## Troubleshooting

- **`could not open port` / `Access is denied`**: Serial Monitor Arduino masih terbuka, atau `SERIAL_PORT` salah.
- **`pip install insightface` gagal di Windows** (`Microsoft Visual C++ 14.0 or greater is required`):
  install "Microsoft C++ Build Tools" (centang *Desktop development with C++*), lalu ulangi.
- **`cv2.imshow ... The function is not implemented`**: ada `opencv-python-headless` yang ikut
  ter-install. Jalankan `pip uninstall -y opencv-python-headless opencv-contrib-python` lalu
  `pip install --force-reinstall opencv-python`.
- **Scan wajah terasa lambat**: ganti `FACE_MODEL = "buffalo_s"` di `config.py` (lebih ringan), lalu enroll ulang.
- **Wajah sendiri sering ditolak**: enroll ulang di lokasi gate, atau tambah sampel
  (`python enroll.py Carlson --append`). Bisa juga turunkan `MATCH_THRESHOLD` sedikit.
- **Orang lain dikenali sebagai kamu**: naikkan `MATCH_THRESHOLD` / `MATCH_MARGIN`.
  Gunakan `python evaluate.py report` untuk memilih nilai yang tepat.
- **Face recog terpicu terus / tidak pernah**: atur `TRIGGER_DISTANCE_CM` di `.ino`, cek voltage divider Echo.
- **ESP32 reset saat servo bergerak** (`Brownout detector was triggered`): pasang kapasitor di rail 5V, atau pindah ke supply 5V eksternal.

## Limitasi (untuk laporan)

- Belum ada liveness detection, jadi foto wajah di HP bisa menipu sistem.
- Akurasi tetap bergantung pada kondisi enroll (cahaya, jarak, pose). Enroll sebaiknya di lokasi gate.
- Endpoint `/api/unlock` tidak memakai autentikasi. Siapa pun di jaringan yang sama bisa membuka gate.
- Face recognition bergantung pada laptop. Kalau laptop mati, hanya kartu di `LOCAL_CARDS` yang bisa membuka gate.
- Model InsightFace (buffalo_l / buffalo_s) hanya untuk penggunaan non-komersial.

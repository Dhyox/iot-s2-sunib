# Smart Gate: Face Recognition + RFID

ESP32 DevKit V1 mengendalikan gate (RFID RC522, HC-SR04, servo, buzzer, LED RGB).
Laptop menjalankan face recognition lewat webcam (Haar cascade + LBPH), mencatat log
ke SQLite, dan menyajikan dashboard HTTP. Keduanya terhubung lewat kabel USB (serial).

```
iot-s2-sunib/
├── esp32_gate/esp32_gate.ino   firmware ESP32
└── laptop/
    ├── config.py               port COM, kamera, threshold
    ├── rfid_cards.example.json contoh daftar kartu RFID (salin ke rfid_cards.json)
    ├── face_engine.py          deteksi (Haar cascade) + pengenalan wajah (LBPH)
    ├── enroll.py               ambil foto wajah + training model
    ├── evaluate.py             uji akurasi & kalibrasi threshold
    ├── database.py             SQLite: log akses & status pintu
    ├── main.py                 bridge serial + server dashboard
    ├── models/haarcascade_frontalface_default.xml
    ├── templates/dashboard.html
    └── static/chart.umd.min.js Chart.js lokal (dashboard jalan tanpa internet)
```

File yang dibuat saat dipakai (tidak di-commit): `rfid_cards.json` (kartu RFID),
`data/<nama>/*.jpg` (foto wajah), `trainer.yml` (model LBPH), `labels.json` (id -> nama),
`gate.db` (log), `eval_data/` dan `eval_report.png` (evaluasi).

## Cara kerja

1. Orang mendekat ≤ 30 cm (3 pembacaan berturut-turut) → LED biru, sesi 12 detik dimulai.
2. Selama sesi, **wajah dan kartu aktif bersamaan**. Mana yang berhasil duluan, gate terbuka.
   - Wajah: laptop menilai hingga 5 frame berisi wajah, gate dibuka kalau minimal 3 frame
     sepakat pada orang yang sama (jarak LBPH < `LBPH_THRESHOLD`).
     Gagal → alarm 3x + merah sebentar, kartu masih bisa dipakai.
   - Kartu: UID dicek laptop ke `RFID_CARDS`. Kalau laptop tidak menjawab dalam 1,5 detik,
     ESP32 memakai daftar cadangan `LOCAL_CARDS`. Kartu salah → bip pendek, sesi lanjut.
   - Sesi habis tanpa berhasil → bip panjang.
3. Akses diterima → LED hijau, servo terbuka 5 detik, lalu tertutup + jeda 4 detik.
   Orang harus menjauh dulu sebelum sesi baru.

## 1. ESP32

1. Arduino IDE → Boards Manager: install **esp32** (Espressif). Pilih board **DOIT ESP32 DEVKIT V1**.
2. Library Manager: install **MFRC522** dan **ESP32Servo**.
3. Buka `esp32_gate/esp32_gate.ino`, cek bagian *Pengaturan* (LED common anode? buzzer pasif?), lalu upload.
4. Tes cepat lewat Serial Monitor (115200, line ending "Newline"): harus muncul `READY`.
   Ketik `OPEN` untuk tes servo, atau dekatkan tangan ke sensor lalu ketik `FACE,OK,Tes`.
5. **Tutup Serial Monitor** sebelum menjalankan program Python.

## 2. Laptop (Python 3.9+)

```bash
cd laptop
pip uninstall opencv-python          # bentrok dengan versi contrib (cv2.face hilang)
pip install -r requirements.txt
python -m serial.tools.list_ports    # cari port ESP32, isi SERIAL_PORT di config.py
copy rfid_cards.example.json rfid_cards.json   # lalu isi UID kartu asli (Linux/macOS: cp)
python enroll.py Carlson             # ambil 100 foto wajah + training otomatis
python enroll.py Vincent
python main.py
```

Buka dashboard di http://localhost:5000. Dari HP di WiFi yang sama: `http://<IP-laptop>:5000`.

UID kartu yang belum terdaftar muncul di log dashboard sebagai "Tidak dikenal".
Salin UID-nya ke `rfid_cards.json`, lalu restart `main.py`.

### Data yang tidak di-commit

Repo ini publik, jadi data berikut hanya disimpan di laptop gate (sudah ada di `.gitignore`):
`rfid_cards.json` (UID kartu asli), `data/` (foto wajah), `trainer.yml` + `labels.json`
(model wajah), `gate.db` (log akses), `eval_data/`. Setiap laptop harus enroll wajah
dan mengisi `rfid_cards.json` sendiri.

### Mengelola wajah

```bash
python enroll.py Carlson             # GANTI foto lama Carlson dengan 100 foto baru
python enroll.py Carlson --append    # tambah foto tanpa menghapus yang lama
python enroll.py Carlson --samples 150
python enroll.py --list              # daftar orang & jumlah foto
python enroll.py --remove Carlson    # hapus orang lalu training ulang
python enroll.py --train             # training ulang dari folder data/
```

Tekan Q atau Enter untuk membatalkan pengambilan foto (data lama tidak berubah).

### Evaluasi akurasi

Kumpulkan data uji di **sesi berbeda** dari enroll (jam/hari lain), termasuk orang yang
**tidak terdaftar** untuk menguji false accept:

```bash
python evaluate.py collect Carlson   # orang terdaftar, 40 foto
python evaluate.py collect tamu1     # orang asing
python evaluate.py report            # FAR, FRR, EER, saran threshold + eval_report.png
```

## Protokol serial (115200 baud, satu baris per pesan)

| Arah | Pesan | Arti |
|---|---|---|
| ESP32 → laptop | `READY` | ESP32 baru menyala |
| ESP32 → laptop | `SCAN` | ada orang ≤ 30 cm, mulai face recognition |
| ESP32 → laptop | `CANCEL` | sesi selesai (gate terbuka / waktu habis), hentikan scan |
| ESP32 → laptop | `RFID,<uid>` | kartu ditempel, minta verifikasi |
| ESP32 → laptop | `DOOR,OPEN` / `DOOR,CLOSED` | status gate berubah |
| ESP32 → laptop | `# ...` | pesan debug |
| laptop → ESP32 | `FACE,OK,<nama>` / `FACE,FAIL` | hasil face recognition |
| laptop → ESP32 | `RFID,OK,<nama>` / `RFID,FAIL` | hasil verifikasi kartu |
| laptop → ESP32 | `OPEN` | buka manual dari dashboard |

## API dashboard

| Endpoint | Isi |
|---|---|
| `GET /api/status` | status pintu, koneksi ESP32, ringkasan hari ini |
| `GET /api/logs?limit=50` | log akses terbaru |
| `GET /api/stats?days=14` | akses per hari, per metode, per jam |
| `POST /api/unlock` | buka gate dari dashboard |

## Troubleshooting

- **`could not open port` / `Access is denied`**: Serial Monitor Arduino masih terbuka, atau `SERIAL_PORT` salah.
- **`cv2.face tidak ada`**: `pip uninstall opencv-python opencv-contrib-python`, lalu `pip install opencv-contrib-python`.
- **Wajah sering tidak dikenali**: enroll ulang di lokasi gate dengan pencahayaan yang sama,
  atau tambah foto (`python enroll.py Carlson --append`). Bisa juga naikkan `LBPH_THRESHOLD` sedikit.
- **Orang lain/asing dikenali sebagai kamu**: turunkan `LBPH_THRESHOLD` (misal 60).
  Gunakan `python evaluate.py report` untuk memilih nilai yang tepat.
- **Face recog terpicu terus / tidak pernah**: atur `TRIGGER_DISTANCE_CM` di `.ino`, cek voltage divider Echo.
- **ESP32 reset saat servo bergerak** (`Brownout detector was triggered`): pasang kapasitor di rail 5V, atau pindah ke supply 5V eksternal.

## Limitasi (untuk laporan)

- Belum ada liveness detection, jadi foto wajah di HP bisa menipu sistem.
- LBPH sensitif terhadap perubahan cahaya dan sudut wajah. Enroll sebaiknya dilakukan di lokasi gate.
- LBPH selalu mengembalikan orang terdaftar yang paling mirip; penolakan orang asing hanya
  bergantung pada `LBPH_THRESHOLD`, jadi threshold perlu dikalibrasi dengan `evaluate.py`.
- Endpoint `/api/unlock` tidak memakai autentikasi. Siapa pun di jaringan yang sama bisa membuka gate.
- Face recognition bergantung pada laptop. Kalau laptop mati, hanya kartu di `LOCAL_CARDS` yang bisa membuka gate.

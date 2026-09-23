# Smart Gate: Face Recognition + RFID

ESP32 DevKit V1 mengendalikan gate (RFID, HC-SR04, servo, buzzer, LED).
Laptop menjalankan face recognition lewat webcam, mencatat log ke SQLite,
dan menyajikan dashboard HTTP. Keduanya terhubung lewat kabel USB (serial).

```
smart-gate/
├── esp32_gate/esp32_gate.ino   firmware ESP32
└── laptop/
    ├── config.py               port COM, kamera, threshold, daftar kartu RFID
    ├── download_models.py      unduh model wajah (sekali saja)
    ├── enroll.py               daftarkan wajah
    ├── face_engine.py          deteksi + pengenalan wajah (OpenCV YuNet + SFace)
    ├── database.py             SQLite: log akses & status pintu
    ├── main.py                 bridge serial + server dashboard
    ├── templates/dashboard.html
    └── static/chart.umd.min.js Chart.js lokal (dashboard jalan tanpa internet)
```

## 1. ESP32

1. Arduino IDE → Boards Manager: install **esp32** (Espressif). Pilih board **DOIT ESP32 DEVKIT V1**.
2. Library Manager: install **MFRC522** dan **ESP32Servo**.
3. Buka `esp32_gate/esp32_gate.ino`, cek bagian *Pengaturan* (LED common anode? buzzer pasif?), lalu upload.
4. Tes cepat lewat Serial Monitor (115200): harus muncul `READY`. Tempel kartu → muncul `RFID,<UID>`.
   Karena laptop belum menjawab, gate memakai daftar `LOCAL_CARDS`.
5. **Tutup Serial Monitor** sebelum menjalankan program Python.

## 2. Laptop (Python 3.9+)

```bash
cd laptop
pip install -r requirements.txt
python download_models.py          # sekali saja
python -m serial.tools.list_ports  # cari port ESP32, isi SERIAL_PORT di config.py
python enroll.py Miyano            # SPASI = ambil sampel, 5x
python main.py
```

Buka dashboard di http://localhost:5000. Dari HP di WiFi yang sama: `http://<IP-laptop>:5000`.

UID kartu yang belum terdaftar muncul di log dashboard sebagai "Tidak dikenal".
Salin UID-nya ke `RFID_CARDS` di `config.py`, lalu restart `main.py`.

## Protokol serial

| Arah | Pesan | Arti |
|---|---|---|
| ESP32 → laptop | `READY` | ESP32 baru menyala |
| ESP32 → laptop | `SCAN` | ada orang ≤ 30 cm, minta face recognition |
| ESP32 → laptop | `RFID,<uid>` | kartu ditempel, minta verifikasi |
| ESP32 → laptop | `DOOR,OPEN` / `DOOR,CLOSED` | status gate berubah |
| ESP32 → laptop | `# ...` | pesan debug |
| laptop → ESP32 | `OK,<nama>` / `FAIL` | hasil verifikasi |
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
- **Wajah sering tidak dikenali**: tambah sampel (`python enroll.py Miyano --samples 5` menambah, bukan mengganti) dengan pencahayaan yang sama seperti lokasi demo.
- **Orang lain dikenali sebagai kamu**: naikkan `MATCH_THRESHOLD` (misal 0.45).
- **Face recog terpicu terus / tidak pernah**: atur `TRIGGER_DISTANCE_CM` di `.ino`, cek voltage divider Echo.
- **ESP32 reset saat servo bergerak** (`Brownout detector was triggered`): pasang kapasitor di rail 5V, atau pindah ke supply 5V eksternal.

## Limitasi (untuk laporan)

- Belum ada liveness detection, jadi foto wajah di HP bisa menipu sistem.
- Endpoint `/api/unlock` tidak memakai autentikasi. Siapa pun di jaringan yang sama bisa membuka gate.
- Face recognition bergantung pada laptop. Kalau laptop mati, hanya kartu di `LOCAL_CARDS` yang bisa membuka gate.

# upload log ke dashboard online (vercel), jalan di thread sendiri
# event diambil dari tabel outbox di gate.db. kalo internet mati, ga ilang,
# nunggu aja di outbox terus dikirim pas udh online lagi
import json
import threading
import time
import urllib.error
import urllib.request

import database as db
from config import CLOUD

SEND_EVERY_SEC = 2
HEARTBEAT_EVERY_SEC = 10     # dashboard nganggep offline kalo >30 detik ga ada heartbeat
BATCH = 50


def _post(events):
    req = urllib.request.Request(
        CLOUD["url"].rstrip("/") + "/api/ingest",
        data=json.dumps({"events": events}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {CLOUD['key']}"},
        method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        r.read()


class Uploader:
    def __init__(self, get_status):
        self.get_status = get_status
        self.last_hb = 0.0
        self.failing = False

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as e:   # jangan sampe thread-nya mati diem2
                print(f"cloud: error {e!r}")
            time.sleep(SEND_EVERY_SEC)

    def tick(self):
        rows = db.outbox_peek(BATCH)
        events = [e for _, e in rows]
        send_hb = time.time() - self.last_hb >= HEARTBEAT_EVERY_SEC
        if send_hb:
            connected, door = self.get_status()
            events.append({"type": "heartbeat", "esp32_connected": connected, "door": door})
        if not events:
            return

        try:
            _post(events)
        except urllib.error.HTTPError as e:
            hint = " (key di cloud.json beda sama INGEST_KEY di vercel?)" if e.code == 401 else ""
            self._fail(f"server nolak, HTTP {e.code}{hint}")
            return
        except (urllib.error.URLError, OSError) as e:
            self._fail(f"gagal upload ({e}), nyoba lagi terus di background")
            return

        db.outbox_delete([i for i, _ in rows])
        if send_hb:
            self.last_hb = time.time()
        if self.failing:
            print("cloud: nyambung lagi ke dashboard online")
            self.failing = False

    def _fail(self, msg):
        if not self.failing:   # print sekali aja, biar terminal ga spam
            print(f"cloud: {msg}")
            self.failing = True


def start(get_status):
    """get_status() -> (esp32_connected, door_state)"""
    if not CLOUD:
        print("cloud.json ga ada, upload ke dashboard online dimatiin.")
        return
    print(f"Upload ke dashboard online: {CLOUD['url']}")
    threading.Thread(target=Uploader(get_status).run, daemon=True).start()

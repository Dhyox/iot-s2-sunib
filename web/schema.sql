-- jalanin sekali aja di Neon (SQL Editor), buat bikin tabel dashboard online

CREATE TABLE IF NOT EXISTS access_log (
    id        BIGSERIAL PRIMARY KEY,
    event_id  TEXT UNIQUE NOT NULL,     -- id dari laptop, biar ga dobel kalo upload diulang
    ts        TIMESTAMPTZ NOT NULL,
    method    TEXT NOT NULL,            -- face / rfid / manual
    identity  TEXT,
    result    TEXT NOT NULL,            -- granted / denied
    score     REAL,
    note      TEXT
);

CREATE TABLE IF NOT EXISTS door_event (
    id        BIGSERIAL PRIMARY KEY,
    event_id  TEXT UNIQUE NOT NULL,
    ts        TIMESTAMPTZ NOT NULL,
    state     TEXT NOT NULL             -- open / closed
);

-- cuma 1 baris, di-update laptop tiap 10 detik (buat tau gate online/offline)
CREATE TABLE IF NOT EXISTS gate_status (
    id               INT PRIMARY KEY DEFAULT 1,
    last_seen        TIMESTAMPTZ NOT NULL,
    esp32_connected  BOOLEAN NOT NULL,
    door_state       TEXT
);

CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log(ts);
CREATE INDEX IF NOT EXISTS idx_door_ts ON door_event(ts);

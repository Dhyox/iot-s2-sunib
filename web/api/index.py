# API dashboard online, jalan di vercel
# laptop ngirim event ke POST /api/ingest (pake INGEST_KEY)
# dashboard baca dari /api/status, /api/logs, /api/stats
# env di vercel: DATABASE_URL (otomatis dari Neon), INGEST_KEY (bikin sendiri)
import hmac
import os
from datetime import datetime, timedelta

import psycopg
from flask import Flask, jsonify, request
from psycopg.rows import dict_row
from werkzeug.exceptions import HTTPException

app = Flask(__name__)

TZ = os.environ.get("GATE_TZ", "Asia/Jakarta")   # server vercel pake UTC, jadi semua dihitung pake WIB
OFFLINE_AFTER_SEC = 30                           # laptop kirim heartbeat tiap 10 detik
MAX_EVENTS = 200
METHODS = {"face", "rfid", "manual"}
RESULTS = {"granted", "denied"}
DOOR_STATES = {"open", "closed"}


def db():
    url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not url:
        raise RuntimeError("DATABASE_URL belum di-set di Vercel")
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


def local_ts(col):
    # timestamp -> string jam WIB, formatnya sama kayak dashboard lokal
    return f"to_char({col} AT TIME ZONE %(tz)s, 'YYYY-MM-DD HH24:MI:SS')"


def today(cur):
    cur.execute("SELECT (now() AT TIME ZONE %(tz)s)::date AS d", {"tz": TZ})
    return cur.fetchone()["d"]


@app.errorhandler(Exception)
def on_error(e):
    if isinstance(e, HTTPException):   # 404/405 dll biarin normal
        return e
    print(f"error: {e!r}")
    return jsonify(ok=False, error=str(e)), 500


# dari laptop

def _parse_ts(value):
    ts = datetime.fromisoformat(str(value))
    if ts.tzinfo is None:
        raise ValueError("ts harus ada timezone-nya")
    return ts


def _text(value, limit):
    return None if value is None else str(value)[:limit]


@app.post("/api/ingest")
def ingest():
    key = os.environ.get("INGEST_KEY", "")
    auth = request.headers.get("Authorization", "")
    if not key or not hmac.compare_digest(auth.encode(), f"Bearer {key}".encode()):
        return jsonify(ok=False, error="unauthorized"), 401

    body = request.get_json(silent=True)
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        return jsonify(ok=False, error="format salah"), 400

    saved, skipped = 0, 0
    with db() as conn, conn.cursor() as cur:
        for e in events:
            try:
                with conn.transaction():   # per event, biar 1 event rusak ga ngegagalin semua
                    _save_event(cur, e)
                saved += 1
            except (KeyError, ValueError, TypeError, AttributeError, psycopg.DataError) as err:
                # event rusak di-skip aja, kalo ga laptop bakal ngirim ulang terus
                print(f"skip event: {err!r}")
                skipped += 1
    return jsonify(ok=True, saved=saved, skipped=skipped)


def _save_event(cur, e):
    kind = e.get("type")
    if kind == "access":
        if e["method"] not in METHODS or e["result"] not in RESULTS:
            raise ValueError("method/result ga valid")
        score = e.get("score")
        cur.execute(
            "INSERT INTO access_log (event_id, ts, method, identity, result, score, note)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING",
            (_text(e["event_id"], 64), _parse_ts(e["ts"]), e["method"],
             _text(e.get("identity"), 60), e["result"],
             None if score is None else float(score), _text(e.get("note"), 200)))
    elif kind == "door":
        if e["state"] not in DOOR_STATES:
            raise ValueError("state ga valid")
        cur.execute(
            "INSERT INTO door_event (event_id, ts, state) VALUES (%s, %s, %s)"
            " ON CONFLICT (event_id) DO NOTHING",
            (_text(e["event_id"], 64), _parse_ts(e["ts"]), e["state"]))
    elif kind == "heartbeat":
        door = e.get("door") if e.get("door") in DOOR_STATES else None
        cur.execute(
            "INSERT INTO gate_status (id, last_seen, esp32_connected, door_state)"
            " VALUES (1, now(), %s, %s) ON CONFLICT (id) DO UPDATE SET"
            " last_seen = now(), esp32_connected = EXCLUDED.esp32_connected,"
            " door_state = EXCLUDED.door_state",
            (bool(e.get("esp32_connected")), door))
    else:
        raise ValueError("type ga dikenal")


# buat dashboard

@app.get("/api/status")
def api_status():
    p = {"tz": TZ}
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {local_ts('ts')} AS ts, state FROM door_event"
                    " ORDER BY door_event.ts DESC, id DESC LIMIT 1", p)
        door = cur.fetchone() or {"ts": None, "state": "closed"}

        cur.execute(f"SELECT {local_ts('last_seen')} AS last_seen, esp32_connected,"
                    " EXTRACT(EPOCH FROM now() - last_seen) AS age FROM gate_status WHERE id = 1", p)
        hb = cur.fetchone()
        online = bool(hb) and hb["age"] < OFFLINE_AFTER_SEC

        p["today"] = today(cur)
        cur.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE result = 'granted') AS granted,
                   COUNT(*) FILTER (WHERE result = 'denied')  AS denied,
                   COUNT(DISTINCT identity) FILTER (WHERE result = 'granted') AS people
            FROM access_log WHERE (ts AT TIME ZONE %(tz)s)::date = %(today)s
        """, p)
        summary = cur.fetchone()

    return jsonify(door=door, online=online,
                   esp32_connected=online and hb["esp32_connected"],
                   last_seen=hb["last_seen"] if hb else None,
                   today=summary)


@app.get("/api/logs")
def api_logs():
    limit = max(1, min(request.args.get("limit", 50, type=int), 500))
    with db() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT id, {local_ts('ts')} AS ts, method, identity, result, score, note"
                    " FROM access_log ORDER BY access_log.ts DESC, id DESC LIMIT %(limit)s",
                    {"tz": TZ, "limit": limit})
        return jsonify(cur.fetchall())


@app.get("/api/stats")
def api_stats():
    days = max(1, min(request.args.get("days", 14, type=int), 90))
    with db() as conn, conn.cursor() as cur:
        start = today(cur) - timedelta(days=days - 1)
        p = {"tz": TZ, "start": start}
        local_day = "(ts AT TIME ZONE %(tz)s)::date"

        cur.execute(f"""
            SELECT {local_day} AS day,
                   COUNT(*) FILTER (WHERE result = 'granted') AS granted,
                   COUNT(*) FILTER (WHERE result = 'denied')  AS denied
            FROM access_log WHERE {local_day} >= %(start)s GROUP BY day
        """, p)
        by_day = {r["day"]: r for r in cur.fetchall()}

        cur.execute(f"""
            SELECT method,
                   COUNT(*) FILTER (WHERE result = 'granted') AS granted,
                   COUNT(*) FILTER (WHERE result = 'denied')  AS denied
            FROM access_log WHERE {local_day} >= %(start)s GROUP BY method
        """, p)
        methods = {r["method"]: {"granted": r["granted"], "denied": r["denied"]}
                   for r in cur.fetchall()}

        cur.execute(f"""
            SELECT EXTRACT(HOUR FROM ts AT TIME ZONE %(tz)s)::int AS hour, COUNT(*) AS n
            FROM access_log WHERE {local_day} >= %(start)s AND result = 'granted'
            GROUP BY hour
        """, p)
        hourly = [0] * 24
        for r in cur.fetchall():
            hourly[r["hour"]] = r["n"]

    daily = []
    for i in range(days):
        d = start + timedelta(days=i)
        r = by_day.get(d)
        daily.append({"day": d.isoformat(),
                      "granted": r["granted"] if r else 0,
                      "denied": r["denied"] if r else 0})
    return jsonify(daily=daily, methods=methods, hourly=hourly)

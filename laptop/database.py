"""Penyimpanan log akses & status pintu di SQLite."""
import sqlite3
import threading
from datetime import date, datetime, timedelta

from config import DB_FILE

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


_conn = _connect()


def init_db():
    with _lock:
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS access_log (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        TEXT NOT NULL,          -- 'YYYY-MM-DD HH:MM:SS'
            method    TEXT NOT NULL,          -- face | rfid | manual
            identity  TEXT,                   -- nama, NULL kalau tidak dikenal
            uid       TEXT,                   -- UID kartu (khusus rfid)
            result    TEXT NOT NULL,          -- granted | denied
            score     REAL,                   -- skor kemiripan wajah
            note      TEXT
        );
        CREATE TABLE IF NOT EXISTS door_event (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            ts    TEXT NOT NULL,
            state TEXT NOT NULL               -- open | closed
        );
        CREATE INDEX IF NOT EXISTS idx_access_ts ON access_log(ts);
        """)
        _conn.commit()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_access(method, result, identity=None, uid=None, score=None, note=None):
    with _lock:
        _conn.execute(
            "INSERT INTO access_log (ts, method, identity, uid, result, score, note)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_now(), method, identity, uid, result, score, note))
        _conn.commit()


def log_door(state):
    with _lock:
        last = _conn.execute(
            "SELECT state FROM door_event ORDER BY id DESC LIMIT 1").fetchone()
        if last and last["state"] == state:
            return  # tidak ada perubahan
        _conn.execute("INSERT INTO door_event (ts, state) VALUES (?, ?)",
                      (_now(), state))
        _conn.commit()


def door_status():
    with _lock:
        row = _conn.execute(
            "SELECT ts, state FROM door_event ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else {"ts": None, "state": "closed"}


def recent_logs(limit=50):
    with _lock:
        rows = _conn.execute(
            "SELECT * FROM access_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def daily_stats(days=14):
    start = date.today() - timedelta(days=days - 1)
    with _lock:
        rows = _conn.execute("""
            SELECT date(ts) AS day,
                   SUM(result = 'granted') AS granted,
                   SUM(result = 'denied')  AS denied
            FROM access_log
            WHERE date(ts) >= ?
            GROUP BY day
        """, (start.isoformat(),)).fetchall()
    by_day = {r["day"]: r for r in rows}
    out = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        r = by_day.get(d)
        out.append({"day": d,
                    "granted": r["granted"] if r else 0,
                    "denied": r["denied"] if r else 0})
    return out


def method_stats(days=14):
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    with _lock:
        rows = _conn.execute("""
            SELECT method,
                   SUM(result = 'granted') AS granted,
                   SUM(result = 'denied')  AS denied
            FROM access_log WHERE date(ts) >= ?
            GROUP BY method
        """, (start,)).fetchall()
    return {r["method"]: {"granted": r["granted"], "denied": r["denied"]}
            for r in rows}


def hourly_stats(days=14):
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    with _lock:
        rows = _conn.execute("""
            SELECT CAST(strftime('%H', ts) AS INTEGER) AS hour, COUNT(*) AS n
            FROM access_log WHERE date(ts) >= ? AND result = 'granted'
            GROUP BY hour
        """, (start,)).fetchall()
    counts = [0] * 24
    for r in rows:
        counts[r["hour"]] = r["n"]
    return counts


def today_summary():
    today = date.today().isoformat()
    with _lock:
        r = _conn.execute("""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(result = 'granted'), 0) AS granted,
                   COALESCE(SUM(result = 'denied'), 0)  AS denied,
                   COUNT(DISTINCT CASE WHEN result = 'granted'
                                       THEN identity END) AS people
            FROM access_log WHERE date(ts) = ?
        """, (today,)).fetchone()
    return dict(r)

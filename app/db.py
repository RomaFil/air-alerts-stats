"""SQLite-сховище тривог. Спільне для веб-сервісу і збирача."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("DB_PATH", "/data/alerts.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY,   -- id тривоги з API
    location_uid    INTEGER NOT NULL,
    location_title  TEXT,
    location_type   TEXT,
    alert_type      TEXT,
    alert_level     TEXT,                  -- 'red' | 'yellow' | NULL = джерело рівня не дає
    started_at      TEXT NOT NULL,         -- ISO 8601 UTC
    finished_at     TEXT,                  -- ISO 8601 UTC або NULL = триває
    finished_source TEXT,                  -- 'api' (підтверджено API) | 'poller' (оцінка збирача)
    last_seen_at    TEXT,                  -- коли востаннє бачили активною
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_loc_start ON alerts(location_uid, started_at);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts(finished_at) WHERE finished_at IS NULL;

CREATE TABLE IF NOT EXISTS regions (
    uid        INTEGER PRIMARY KEY,
    title      TEXT NOT NULL,
    type       TEXT,          -- oblast | raion | hromada | city
    parent_uid INTEGER        -- NULL для верхнього рівня
);

CREATE INDEX IF NOT EXISTS idx_regions_parent ON regions(parent_uid);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Доливає колонки, яких немає в старій базі.

    `CREATE TABLE IF NOT EXISTS` існуючу таблицю не чіпає, тому нові поля
    треба додавати окремо — інакше база, створена до появи колонки, лишиться
    без неї назавжди.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
    if "alert_level" not in have:
        conn.execute("ALTER TABLE alerts ADD COLUMN alert_level TEXT")


def init() -> None:
    from . import regions
    with connect() as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
        # статичний каталог як стартове наповнення; провайдер його потім уточнить
        if not conn.execute("SELECT 1 FROM regions LIMIT 1").fetchone():
            upsert_regions(conn, regions.seed_rows())


def upsert_regions(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Оновлює каталог регіонів. Порожній список нічого не чіпає."""
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO regions (uid, title, type, parent_uid)
        VALUES (:uid, :title, :type, :parent_uid)
        ON CONFLICT(uid) DO UPDATE SET
            title      = excluded.title,
            type       = excluded.type,
            parent_uid = COALESCE(excluded.parent_uid, regions.parent_uid)
        """,
        rows,
    )
    return len(rows)


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def upsert_alert(conn: sqlite3.Connection, a: dict, *, seen_now: bool) -> None:
    """Записує тривогу.

    Ключове правило: finished_at, підтверджений API, ніколи не перетирається
    оцінкою збирача. Навпаки — так, бо API точніший.
    """
    now = utcnow()
    finished = a.get("finished_at")
    src = "api" if finished else None
    last_seen = now if seen_now else None

    conn.execute(
        """
        INSERT INTO alerts (id, location_uid, location_title, location_type, alert_type,
                            alert_level, started_at, finished_at, finished_source,
                            last_seen_at, updated_at)
        VALUES (:id, :uid, :title, :ltype, :atype, :alevel, :start, :fin, :src, :seen, :now)
        ON CONFLICT(id) DO UPDATE SET
            location_title  = excluded.location_title,
            location_type   = excluded.location_type,
            alert_type      = excluded.alert_type,
            -- рівень тримаємо останній відомий: тривога може перетекти
            -- з жовтої в червону, а COALESCE не дав би її оновити
            alert_level     = COALESCE(excluded.alert_level, alerts.alert_level),
            started_at      = excluded.started_at,
            finished_at     = COALESCE(excluded.finished_at, alerts.finished_at),
            finished_source = CASE
                                WHEN excluded.finished_at IS NOT NULL THEN 'api'
                                ELSE alerts.finished_source
                              END,
            last_seen_at    = COALESCE(excluded.last_seen_at, alerts.last_seen_at),
            updated_at      = excluded.updated_at
        """,
        {
            "id": a["id"], "uid": a["location_uid"], "title": a.get("location_title"),
            "ltype": a.get("location_type"), "atype": a.get("alert_type"),
            "alevel": a.get("alert_level"),
            "start": a["started_at"], "fin": finished, "src": src,
            "seen": last_seen, "now": now,
        },
    )


def close_stale(conn: sqlite3.Connection, active_ids: set[int]) -> int:
    """Тривоги, яких більше немає в активному списку, закриваємо часом last_seen_at.

    Джерело позначається як 'poller' — потім backfill з API уточнить.
    """
    rows = conn.execute(
        "SELECT id, last_seen_at FROM alerts WHERE finished_at IS NULL"
    ).fetchall()
    now = utcnow()
    n = 0
    for row in rows:
        if row["id"] in active_ids:
            continue
        conn.execute(
            "UPDATE alerts SET finished_at=?, finished_source='poller', updated_at=? WHERE id=?",
            (row["last_seen_at"] or now, now, row["id"]),
        )
        n += 1
    return n

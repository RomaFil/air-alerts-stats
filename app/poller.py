"""Фоновий збирач: live-опитування + (якщо джерело вміє) backfill історії.

Запускається окремим контейнером. Пише в ту саму SQLite, що читає веб.
"""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from . import db
from .providers import ProviderError, get_provider
from .regions import OBLASTS

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "45"))
BACKFILL_INTERVAL_HOURS = float(os.environ.get("BACKFILL_INTERVAL_HOURS", "12"))
BACKFILL_SPACING = float(os.environ.get("BACKFILL_SPACING", "35"))
REGIONS_REFRESH_HOURS = float(os.environ.get("REGIONS_REFRESH_HOURS", "24"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s poller: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("poller")

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True
    log.info("отримано сигнал %s, зупиняюсь", signum)


def sleep_interruptible(seconds: float) -> None:
    end = time.monotonic() + seconds
    while not _stop and time.monotonic() < end:
        time.sleep(min(1.0, end - time.monotonic()))


def refresh_regions(provider) -> None:
    """Підтягує каталог регіонів із джерела, якщо воно його віддає."""
    try:
        rows = provider.fetch_regions()
    except Exception as e:  # noqa: BLE001
        log.warning("каталог регіонів: %s", e)
        return
    if not rows:
        return
    with db.connect() as conn:
        conn.execute("BEGIN")
        n = db.upsert_regions(conn, rows)
        db.set_meta(conn, "last_regions_refresh_at", db.utcnow())
        conn.execute("COMMIT")
    log.info("каталог регіонів оновлено: %d записів", n)


def poll_once(provider) -> None:
    try:
        alerts = provider.fetch_active()
    except ProviderError as e:
        log.warning("live: %s", e)
        return

    with db.connect() as conn:
        if alerts is None:
            db.set_meta(conn, "last_poll_at", db.utcnow())
            return  # 304 — нічого не змінилось

        conn.execute("BEGIN")
        for a in alerts:
            db.upsert_alert(conn, a, seen_now=True)
        closed = db.close_stale(conn, {a["id"] for a in alerts})
        db.set_meta(conn, "last_poll_at", db.utcnow())
        db.set_meta(conn, "provider", provider.name)
        conn.execute("COMMIT")
        if closed:
            log.info("активних %d, закрито %d", len(alerts), closed)


def backfill(provider) -> None:
    """Тягне історію по кожній області. Повільно — у alerts.in.ua ліміт 2 запити/хв."""
    log.info("backfill: старт, %d областей", len(OBLASTS))
    total = 0
    for uid in OBLASTS:
        if _stop:
            return
        try:
            alerts = provider.fetch_history(uid)
        except Exception as e:  # noqa: BLE001 — не валимо цикл через один регіон
            log.warning("backfill uid=%s: %s", uid, e)
            sleep_interruptible(BACKFILL_SPACING)
            continue
        with db.connect() as conn:
            conn.execute("BEGIN")
            for a in alerts:
                db.upsert_alert(conn, a, seen_now=False)
            conn.execute("COMMIT")
        total += len(alerts)
        sleep_interruptible(BACKFILL_SPACING)
    with db.connect() as conn:
        db.set_meta(conn, "last_backfill_at", db.utcnow())
        # backfill приніс місяць історії — зсуваємо початок покриття назад
        earliest = (datetime.now(timezone.utc) - timedelta(days=30)).replace(
            microsecond=0).isoformat().replace("+00:00", "Z")
        current = db.get_meta(conn, "coverage_start")
        if not current or earliest < current:
            db.set_meta(conn, "coverage_start", earliest)
    log.info("backfill: готово, оброблено %d записів", total)


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    db.init()
    # Справжній початок збору. Виводити його з MIN(started_at) не можна:
    # у фіді є тривоги, що тривають з 2022 року, і тоді будь-яка минула дата
    # виглядала б покритою, хоча даних за неї немає.
    with db.connect() as conn:
        if not db.get_meta(conn, "coverage_start"):
            db.set_meta(conn, "coverage_start", db.utcnow())
            log.info("початок збору зафіксовано: %s", db.get_meta(conn, "coverage_start"))

    try:
        provider = get_provider()
    except ProviderError as e:
        log.error("%s", e)
        return 1

    log.info(
        "старт: джерело=%s, live кожні %ss, історія=%s",
        provider.name, POLL_INTERVAL,
        f"backfill кожні {BACKFILL_INTERVAL_HOURS}г" if provider.supports_history
        else "тільки власне накопичення",
    )

    next_backfill = 0.0
    next_regions = 0.0

    while not _stop:
        if time.monotonic() >= next_regions:
            refresh_regions(provider)
            next_regions = time.monotonic() + REGIONS_REFRESH_HOURS * 3600
        if provider.supports_history and time.monotonic() >= next_backfill:
            backfill(provider)
            next_backfill = time.monotonic() + BACKFILL_INTERVAL_HOURS * 3600
        try:
            poll_once(provider)
        except Exception as e:  # noqa: BLE001
            log.exception("live poll впав: %s", e)
        sleep_interruptible(POLL_INTERVAL)

    provider.close()
    log.info("зупинено")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Веб-сервіс: API статистики + статичний фронтенд."""
from __future__ import annotations

import os
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import db, regions

TZ = ZoneInfo(os.environ.get("TZ", "Europe/Kyiv"))
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Air Alerts Stats", docs_url="/api/docs", redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    db.init()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def day_bounds(day: date_cls) -> tuple[datetime, datetime]:
    """Межі доби в локальному поясі, повернуті в UTC."""
    start = datetime.combine(day, datetime.min.time(), tzinfo=TZ)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def merge_intervals(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Об'єднує перекривні відрізки — щоб область і її райони не рахувались двічі."""
    if not spans:
        return []
    spans = sorted(spans)
    out = [spans[0]]
    for s, e in spans[1:]:
        last_s, last_e = out[-1]
        if s <= last_e:
            out[-1] = (last_s, max(last_e, e))
        else:
            out.append((s, e))
    return out


@app.get("/api/regions")
def api_regions():
    return {"regions": regions.tree()}


@app.get("/api/status")
def api_status():
    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c, MIN(started_at) first, MAX(started_at) last FROM alerts"
        ).fetchone()
        regions_stored = conn.execute("SELECT COUNT(*) c FROM regions").fetchone()["c"]
        return {
            "provider": db.get_meta(conn, "provider"),
            "alerts_stored": row["c"],
            "regions_stored": regions_stored,
            "earliest_alert": row["first"],
            "latest_alert": row["last"],
            "last_poll_at": db.get_meta(conn, "last_poll_at"),
            "last_backfill_at": db.get_meta(conn, "last_backfill_at"),
            "last_regions_refresh_at": db.get_meta(conn, "last_regions_refresh_at"),
            "coverage_start": db.get_meta(conn, "coverage_start"),
            "timezone": str(TZ),
        }


@app.get("/api/stats")
def api_stats(
    uid: int = Query(..., description="location_uid регіону"),
    date: str = Query(..., description="Дата YYYY-MM-DD у локальному поясі"),
    alert_type: str = Query("air_raid", description="air_raid | all"),
    scope: str = Query("with_children", description="with_children | exact"),
):
    try:
        day = date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(400, "date має бути у форматі YYYY-MM-DD")

    uids = regions.family(uid) if scope == "with_children" else {uid}
    start_utc, end_utc = day_bounds(day)
    now = datetime.now(timezone.utc)

    placeholders = ",".join("?" * len(uids))
    sql = f"""
        SELECT id, location_uid, location_title, location_type, alert_type,
               started_at, finished_at, finished_source
        FROM alerts
        WHERE location_uid IN ({placeholders})
          AND started_at < ?
          AND (finished_at IS NULL OR finished_at > ?)
    """
    params: list = [*uids, end_utc.isoformat(), start_utc.isoformat()]
    if alert_type != "all":
        sql += " AND alert_type = ?"
        params.append(alert_type)
    sql += " ORDER BY started_at"

    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        coverage_start = db.get_meta(conn, "coverage_start") or conn.execute(
            "SELECT MIN(started_at) m FROM alerts"
        ).fetchone()["m"]

    items = []
    spans: list[tuple[datetime, datetime]] = []
    for r in rows:
        s = parse_iso(r["started_at"])
        f = parse_iso(r["finished_at"])
        ongoing = f is None
        eff_end = f or now
        cs = max(s, start_utc)
        ce = min(eff_end, end_utc)
        if ce <= cs:
            continue
        spans.append((cs, ce))
        items.append({
            "id": r["id"],
            "location_uid": r["location_uid"],
            "location_title": r["location_title"] or regions.title(r["location_uid"]),
            "location_type": r["location_type"],
            "alert_type": r["alert_type"],
            "started_at": s.astimezone(TZ).isoformat(),
            "finished_at": f.astimezone(TZ).isoformat() if f else None,
            "ongoing": ongoing,
            "estimated_end": ongoing is False and r["finished_source"] == "poller",
            # відрізок, обрізаний межами доби — саме він іде в графік
            "clip_start": cs.astimezone(TZ).isoformat(),
            "clip_end": ce.astimezone(TZ).isoformat(),
            "clipped": cs > s or ce < eff_end,
            "duration_seconds": int((ce - cs).total_seconds()),
        })

    merged = merge_intervals(spans)
    union_seconds = int(sum((e - s).total_seconds() for s, e in merged))
    raw_seconds = sum(i["duration_seconds"] for i in items)

    return {
        "uid": uid,
        "region_title": regions.title(uid),
        "date": day.isoformat(),
        "scope": scope,
        "alert_type": alert_type,
        "count": len(items),
        "total_seconds": union_seconds,      # об'єднаний час під тривогою
        "sum_seconds": raw_seconds,          # сума окремих тривог (може двоїтись обл./район)
        "longest_seconds": max((i["duration_seconds"] for i in items), default=0),
        "coverage_start": coverage_start,
        # full   — доба цілком у межах збору
        # partial— збір почався всередині доби (тривоги, що вже тривали, порахуються
        #          правильно: джерело віддає їхній справжній початок; бракує лише тих,
        #          що встигли початись і завершитись до старту збору)
        # none   — доба цілком до початку збору
        "coverage": (
            "full" if not coverage_start or start_utc.isoformat() >= coverage_start
            else "none" if end_utc.isoformat() <= coverage_start
            else "partial"
        ),
        "incomplete": bool(coverage_start and start_utc.isoformat() < coverage_start),
        "alerts": items,
        "merged": [
            {"start": s.astimezone(TZ).isoformat(), "end": e.astimezone(TZ).isoformat()}
            for s, e in merged
        ],
    }


@app.get("/api/range")
def api_range(
    uid: int = Query(..., description="location_uid регіону"),
    date_from: str = Query(..., alias="from", description="Перша доба, YYYY-MM-DD"),
    date_to: str = Query(..., alias="to", description="Остання доба включно, YYYY-MM-DD"),
    alert_type: str = Query("air_raid"),
    scope: str = Query("with_children"),
):
    """Подобові підсумки за період — для порівняння днів між собою.

    Одним запитом до БД, далі розкладка по добах у пам'яті: 30 окремих
    запитів через тунель з мобільного вантажились би помітно довше.
    """
    try:
        first = date_cls.fromisoformat(date_from)
        last = date_cls.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "дати мають бути у форматі YYYY-MM-DD")
    if last < first:
        first, last = last, first
    span_days = (last - first).days + 1
    if span_days > 92:
        raise HTTPException(400, "період не більший за 92 доби")

    uids = regions.family(uid) if scope == "with_children" else {uid}
    win_start, _ = day_bounds(first)
    _, win_end = day_bounds(last)
    now = datetime.now(timezone.utc)

    placeholders = ",".join("?" * len(uids))
    sql = f"""
        SELECT started_at, finished_at FROM alerts
        WHERE location_uid IN ({placeholders})
          AND started_at < ?
          AND (finished_at IS NULL OR finished_at > ?)
    """
    params: list = [*uids, win_end.isoformat(), win_start.isoformat()]
    if alert_type != "all":
        sql += " AND alert_type = ?"
        params.append(alert_type)

    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        coverage_start = db.get_meta(conn, "coverage_start")

    parsed = []
    for r in rows:
        s = parse_iso(r["started_at"])
        e = parse_iso(r["finished_at"]) or now
        if s and e > s:
            parsed.append((s, e))
    parsed.sort()

    days = []
    for i in range(span_days):
        day = first + timedelta(days=i)
        d_start, d_end = day_bounds(day)
        spans = []
        for s, e in parsed:
            if s >= d_end:
                break          # відсортовано за початком — далі тільки пізніші
            if e <= d_start:
                continue
            spans.append((max(s, d_start), min(e, d_end)))
        merged = merge_intervals(spans)
        days.append({
            "date": day.isoformat(),
            "count": len(spans),
            "total_seconds": int(sum((e - s).total_seconds() for s, e in merged)),
            "covered": not (coverage_start and d_start.isoformat() < coverage_start),
        })

    covered = [d for d in days if d["covered"]]
    return {
        "uid": uid,
        "region_title": regions.title(uid),
        "from": first.isoformat(),
        "to": last.isoformat(),
        "scope": scope,
        "alert_type": alert_type,
        "coverage_start": coverage_start,
        "days": days,
        "max_seconds": max((d["total_seconds"] for d in days), default=0),
        "max_count": max((d["count"] for d in days), default=0),
        # середні рахуємо лише по покритих добах, інакше порожні дні до початку
        # збору тягнули б середнє вниз і показували б неправду
        "avg_seconds": int(sum(d["total_seconds"] for d in covered) / len(covered)) if covered else 0,
        "avg_count": round(sum(d["count"] for d in covered) / len(covered), 1) if covered else 0,
        "covered_days": len(covered),
    }


class NoCacheStatic(StaticFiles):
    """Статика з обов'язковою ревалідацією.

    Без цього браузер лишає в кеші стару app.js після оновлення застосунку,
    і на телефоні видно вчорашню версію, поки вручну не почистиш кеш.
    `no-cache` не забороняє кешування — він лише змушує щоразу перепитати,
    тож незмінені файли й далі приїжджають як дешеві 304.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", NoCacheStatic(directory=STATIC_DIR), name="static")


def asset_version() -> str:
    """Мітка версії статики = час останньої зміни app.js/style.css.

    Підставляється в URL скрипта й стилів. Без цього браузер, який один раз
    закешував app.js (тим паче до появи no-cache), продовжує віддавати стару
    версію — саме так на телефоні лишається вчорашній застосунок.
    Зміна файлу змінює URL, тож оновлення доїжджає завжди й без ручного бампу.
    """
    stamps = []
    for name in ("app.js", "style.css"):
        try:
            stamps.append(int((STATIC_DIR / name).stat().st_mtime))
        except OSError:
            pass
    return str(max(stamps)) if stamps else "0"


@app.get("/", response_class=HTMLResponse)
def index():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html.replace("{{v}}", asset_version()),
        headers={"Cache-Control": "no-cache"},
    )

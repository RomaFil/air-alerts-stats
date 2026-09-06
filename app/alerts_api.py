"""Тонкий клієнт alerts.in.ua."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx

BASE = "https://api.alerts.in.ua"
TOKEN = os.environ.get("ALERTS_TOKEN", "").strip()
UA = "air-alerts-stats/1.0 (self-hosted)"


class AlertsApiError(RuntimeError):
    pass


def to_utc_iso(value: str | None) -> str | None:
    """API віддає ISO 8601 у різних формах ('...Z', '+03:00', без зони).

    Зводимо все до UTC-рядка 'YYYY-MM-DDTHH:MM:SSZ'. Без зони -> вважаємо Київ,
    бо саме так API позначає локальний час.
    """
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        from zoneinfo import ZoneInfo
        dt = dt.replace(tzinfo=ZoneInfo("Europe/Kyiv"))
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize(raw: dict) -> dict | None:
    """Сира тривога з API -> запис для БД. None, якщо не вистачає ключів."""
    if raw.get("id") is None or raw.get("location_uid") is None:
        return None
    started = to_utc_iso(raw.get("started_at"))
    if not started:
        return None
    try:
        uid = int(raw["location_uid"])
    except (TypeError, ValueError):
        return None
    return {
        "id": int(raw["id"]),
        "location_uid": uid,
        "location_title": raw.get("location_title"),
        "location_type": raw.get("location_type"),
        "alert_type": raw.get("alert_type"),
        "started_at": started,
        "finished_at": to_utc_iso(raw.get("finished_at")),
    }


class AlertsClient:
    def __init__(self, token: str | None = None, timeout: float = 20.0):
        self.token = (token or TOKEN).strip()
        if not self.token:
            raise AlertsApiError("ALERTS_TOKEN не заданий — див. .env.example")
        self._client = httpx.Client(
            base_url=BASE,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.token}",
                "User-Agent": UA,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, *, if_modified_since: str | None = None) -> tuple[int, dict | None, str | None]:
        headers = {}
        if if_modified_since:
            headers["If-Modified-Since"] = if_modified_since
        r = self._client.get(path, headers=headers)
        if r.status_code == 304:
            return 304, None, if_modified_since
        if r.status_code == 429:
            raise AlertsApiError("429: перевищено ліміт запитів")
        if r.status_code in (401, 403):
            raise AlertsApiError(f"{r.status_code}: токен відхилено")
        r.raise_for_status()
        return r.status_code, r.json(), r.headers.get("Last-Modified")

    def active(self, if_modified_since: str | None = None):
        """Активні тривоги. Повертає (список|None, last_modified). None = 304."""
        status, data, lm = self._get("/v1/alerts/active.json", if_modified_since=if_modified_since)
        if status == 304:
            return None, lm
        items = (data or {}).get("alerts", [])
        return [n for n in (normalize(x) for x in items) if n], lm

    def history(self, uid: int, period: str = "month_ago") -> list[dict]:
        """Історія по регіону. Наразі API підтримує лише period='month_ago'."""
        _, data, _ = self._get(f"/v1/regions/{uid}/alerts/{period}.json")
        items = (data or {}).get("alerts", [])
        return [n for n in (normalize(x) for x in items) if n]

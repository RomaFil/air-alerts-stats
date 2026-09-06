"""siren.pp.ua — вільне дзеркало офіційного ukrainealarm v3 (ДСНС).

Ключа не потребує. Дає гранулярність до громад і повне дерево регіонів.
UID-и збігаються з нумерацією alerts.in.ua (обидва з каталогу ДСНС),
крім Криму: там 9999 замість 29.
"""
from __future__ import annotations

import httpx

from .base import Provider, ProviderError, synthetic_id, to_utc_iso

BASE = "https://siren.pp.ua/api/v3"

# siren -> наша нумерація
UID_FIXUP = {9999: 29}

TYPE_MAP = {
    "AIR": "air_raid",
    "ARTILLERY": "artillery_shelling",
    "URBAN_FIGHTS": "urban_fights",
    "CHEMICAL": "chemical",
    "NUCLEAR": "nuclear",
    "INFO": "info",
}

REGION_TYPE_MAP = {
    "State": "oblast",
    "District": "raion",
    "Community": "hromada",
    "City": "city",
}


def _uid(raw) -> int | None:
    try:
        uid = int(raw)
    except (TypeError, ValueError):
        return None
    return UID_FIXUP.get(uid, uid)


class SirenProvider(Provider):
    name = "siren"
    supports_history = False  # історичного ендпоінта немає — її веде наш збирач

    def __init__(self, timeout: float = 25.0):
        self._client = httpx.Client(
            base_url=BASE,
            timeout=timeout,
            headers={"User-Agent": "air-alerts-stats/1.0", "Accept": "application/json"},
            follow_redirects=True,
        )
        self._last_modified: str | None = None

    def close(self) -> None:
        self._client.close()

    def fetch_active(self) -> list[dict] | None:
        headers = {}
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified
        r = self._client.get("/alerts", headers=headers)
        if r.status_code == 304:
            return None
        if r.status_code == 429:
            raise ProviderError("429: перевищено ліміт запитів")
        r.raise_for_status()
        self._last_modified = r.headers.get("Last-Modified")

        out: list[dict] = []
        seen: set[int] = set()
        for region in r.json():
            uid = _uid(region.get("regionId"))
            if uid is None:
                continue
            title = region.get("regionName")
            rtype = REGION_TYPE_MAP.get(region.get("regionType"), "unknown")
            for alert in region.get("activeAlerts") or []:
                atype = TYPE_MAP.get(alert.get("type"), "unknown")
                started = to_utc_iso(alert.get("lastUpdate"))
                if not started:
                    continue
                aid = synthetic_id(self.name, uid, atype, started)
                if aid in seen:
                    continue  # у фіді трапляються дублі того самого типу
                seen.add(aid)
                out.append({
                    "id": aid,
                    "location_uid": uid,
                    "location_title": title,
                    "location_type": rtype,
                    "alert_type": atype,
                    "started_at": started,
                    "finished_at": None,  # активна; кінець проставить збирач
                })
        return out

    def fetch_regions(self) -> list[dict]:
        r = self._client.get("/regions")
        r.raise_for_status()
        out: list[dict] = []

        def walk(node: dict, parent: int | None) -> None:
            uid = _uid(node.get("regionId"))
            if uid is None:
                return
            out.append({
                "uid": uid,
                "title": node.get("regionName") or f"UID {uid}",
                "type": REGION_TYPE_MAP.get(node.get("regionType"), "unknown"),
                "parent_uid": parent,
            })
            for child in node.get("regionChildIds") or []:
                walk(child, uid)

        for state in r.json().get("states", []):
            walk(state, None)
        return out

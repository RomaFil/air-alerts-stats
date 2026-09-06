"""ubilling.net.ua/aerialalerts — вільний агрегатор рівня областей.

Ключа не потребує. Віддає для кожної області alertnow + changed (момент зміни
стану), тобто початок тривоги точний, а не з точністю до інтервалу опитування.
Районів не має.
"""
from __future__ import annotations

import httpx

from .base import Provider, ProviderError, synthetic_id, to_utc_iso
from ..regions import STATIC_TITLES

BASE = "https://ubilling.net.ua/aerialalerts/"

# у фіді назви — рядки; зводимо до наших uid
TITLE_TO_UID = {title: uid for uid, title in STATIC_TITLES.items()}
ALIASES = {
    "м. Київ": "м. Київ",
    "Київ": "м. Київ",
    "АР Крим": "Автономна Республіка Крим",
}


class UbillingProvider(Provider):
    name = "ubilling"
    supports_history = False

    def __init__(self, timeout: float = 25.0):
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "air-alerts-stats/1.0", "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_active(self) -> list[dict] | None:
        r = self._client.get(BASE)
        if r.status_code == 429:
            raise ProviderError("429: перевищено ліміт запитів")
        r.raise_for_status()
        states = (r.json() or {}).get("states") or {}

        out: list[dict] = []
        for name, state in states.items():
            if not state.get("alertnow"):
                continue
            title = ALIASES.get(name, name)
            uid = TITLE_TO_UID.get(title)
            if uid is None:
                continue
            started = to_utc_iso(state.get("changed"))
            if not started:
                continue
            out.append({
                "id": synthetic_id(self.name, uid, "air_raid", started),
                "location_uid": uid,
                "location_title": title,
                "location_type": "oblast",
                "alert_type": "air_raid",
                "started_at": started,
                "finished_at": None,
            })
        return out

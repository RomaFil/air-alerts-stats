"""Спільний інтерфейс джерел даних про тривоги."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")


class ProviderError(RuntimeError):
    pass


def to_utc_iso(value: str | None, *, naive_tz=KYIV) -> str | None:
    """ISO 8601 у будь-якій формі -> 'YYYY-MM-DDTHH:MM:SSZ'.

    Рядок без зони трактуємо як київський час — саме так його віддають
    ubilling і alerts.in.ua.
    """
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00").replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def synthetic_id(provider: str, uid: int, alert_type: str, started_at: str) -> int:
    """Стабільний id для джерел, які своїх id не дають.

    Той самий (регіон, тип, початок) завжди дає те саме число, тому повторні
    опитування оновлюють один рядок, а не плодять дублі. 62 біти — влазить
    у SQLite INTEGER і не конфліктує з id від alerts.in.ua (вони малі).

    Рівень тривоги (red/yellow) у ключ навмисно не входить: він може
    змінитись посеред тривоги, і тоді той самий інцидент отримав би другий
    id — тобто дублікат замість оновлення рядка.

    Хеш тут потрібен лише як детермінований ідентифікатор публічних даних,
    а не як криптографічний захист. SHA-256 узято замість SHA-1 просто тому,
    що він не гірший, а статичні аналізатори на SHA-1 справедливо лаються.
    """
    key = f"{provider}:{uid}:{alert_type}:{started_at}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") >> 2 | (1 << 61)


class Provider:
    """Джерело даних. Мінімум — вміти сказати, хто зараз під тривогою."""

    name = "base"
    supports_history = False

    def fetch_active(self) -> list[dict] | None:
        """Активні тривоги. None = 'нічого не змінилось' (304)."""
        raise NotImplementedError

    def fetch_history(self, uid: int) -> list[dict]:
        raise NotImplementedError

    def fetch_regions(self) -> list[dict]:
        """Дерево регіонів: [{uid, title, type, parent_uid}]. [] якщо не вміє."""
        return []

    def close(self) -> None:
        pass

"""Вибір джерела даних через змінну ALERTS_PROVIDER.

Історію веде наша власна БД, тому джерело можна міняти будь-коли —
уже накопичене нікуди не дінеться.
"""
from __future__ import annotations

import os

from .base import Provider, ProviderError

PROVIDERS = ("siren", "ubilling", "alerts_in_ua")


def get_provider(name: str | None = None) -> Provider:
    name = (name or os.environ.get("ALERTS_PROVIDER") or "siren").strip().lower()
    if name == "siren":
        from .siren import SirenProvider
        return SirenProvider()
    if name == "ubilling":
        from .ubilling import UbillingProvider
        return UbillingProvider()
    if name in ("alerts_in_ua", "alerts.in.ua", "alertsinua"):
        from .alerts_in_ua import AlertsInUaProvider
        return AlertsInUaProvider()
    raise ProviderError(f"невідомий ALERTS_PROVIDER={name!r}, доступні: {', '.join(PROVIDERS)}")


__all__ = ["Provider", "ProviderError", "get_provider", "PROVIDERS"]

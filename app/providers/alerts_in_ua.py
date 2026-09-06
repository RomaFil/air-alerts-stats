"""alerts.in.ua — потребує токена, зате має історію за останній місяць."""
from __future__ import annotations

from ..alerts_api import AlertsApiError, AlertsClient
from .base import Provider, ProviderError


class AlertsInUaProvider(Provider):
    name = "alerts_in_ua"
    supports_history = True

    def __init__(self, token: str | None = None):
        try:
            self._client = AlertsClient(token)
        except AlertsApiError as e:
            raise ProviderError(str(e)) from e
        self._last_modified: str | None = None

    def close(self) -> None:
        self._client.close()

    def fetch_active(self) -> list[dict] | None:
        try:
            alerts, lm = self._client.active(if_modified_since=self._last_modified)
        except AlertsApiError as e:
            raise ProviderError(str(e)) from e
        if lm:
            self._last_modified = lm
        return alerts

    def fetch_history(self, uid: int) -> list[dict]:
        try:
            return self._client.history(uid)
        except AlertsApiError as e:
            raise ProviderError(str(e)) from e

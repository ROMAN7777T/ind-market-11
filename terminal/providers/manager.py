"""Holds provider instances for this process. Always starts DISCONNECTED."""
from __future__ import annotations

from .base import ProviderStatus
from .kotak_neo import KotakNeoProvider


class ProviderManager:
    def __init__(self) -> None:
        self.kotak = KotakNeoProvider()

    def live_data_ok(self) -> bool:
        return self.kotak.live_data_ok()

    def status(self) -> ProviderStatus:
        return self.kotak.info.status


_manager: ProviderManager | None = None


def provider_manager() -> ProviderManager:
    global _manager
    if _manager is None:
        _manager = ProviderManager()
    return _manager

"""Provider interface for market data (quotes, candles, streams, instrument master).

There is deliberately no order-placement method in this interface. A test asserts that no
provider class exposes anything that looks like order placement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ProviderStatus(str, Enum):
    DISCONNECTED = "DISCONNECTED"
    SETUP_REQUIRED = "SETUP REQUIRED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    ERROR = "ERROR"


@dataclass
class ProviderInfo:
    name: str
    status: ProviderStatus = ProviderStatus.DISCONNECTED
    sdk: str | None = None
    sdk_version: str | None = None
    capabilities: dict = field(default_factory=dict)
    last_connected: str | None = None
    message: str = ""
    live_data: bool = False


class MarketDataProvider(ABC):
    info: ProviderInfo

    @abstractmethod
    def connect(self, user_initiated: bool) -> ProviderInfo:
        """Open a session. Must refuse unless `user_initiated` is True."""

    @abstractmethod
    def disconnect(self) -> ProviderInfo:
        """Close the session and clear any locally held session credentials."""

    @abstractmethod
    def test_connection(self) -> dict:
        """A safe read-only check. Must not place, modify or cancel anything."""

    def live_data_ok(self) -> bool:
        return self.info.status == ProviderStatus.CONNECTED and self.info.live_data

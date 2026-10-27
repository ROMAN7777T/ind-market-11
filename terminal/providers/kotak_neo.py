"""Kotak Neo provider - DISCONNECTED by default and NOT YET INTEGRATED.

What this class does today:
- starts DISCONNECTED and never connects on import, on app start or in the background;
- `connect()` refuses unless the user clicked Connect (user_initiated=True);
- checks only that the expected local environment variables exist (values are never read
  into logs, the database or the UI) and whether a Kotak SDK module is installed;
- then stops with SETUP REQUIRED, because the authentication flow, SDK methods, feed
  protocol and account permissions have not been verified against current official Kotak
  Neo documentation. No endpoint, SDK method or protocol is guessed here.

Implementing the real session belongs to a future, explicitly requested integration session
(see docs/KOTAK_INTEGRATION.md). Order placement must never be added: the terminal is paper-only.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util

from .. import db
from ..secure import secret_present
from .base import MarketDataProvider, ProviderInfo, ProviderStatus

# Placeholder names. The exact credentials the current Kotak Neo flow needs must be confirmed
# from the official documentation during integration.
REQUIRED_ENV = ("KOTAK_CONSUMER_KEY", "KOTAK_CONSUMER_SECRET", "KOTAK_MOBILE_NUMBER", "KOTAK_UCC")
# Candidate module name for the Kotak Neo Python SDK; to be confirmed during integration.
CANDIDATE_SDK_MODULES = ("neo_api_client",)


class KotakNeoProvider(MarketDataProvider):
    def __init__(self) -> None:
        self.info = ProviderInfo(name="Kotak Neo", capabilities={
            "quotes": "not verified", "historical candles": "not verified", "websocket stream": "not verified",
            "instrument master": "not verified", "order placement": "DISABLED (paper-only terminal)"})
        self._session = None

    def detect_sdk(self) -> tuple[str | None, str | None]:
        for mod in CANDIDATE_SDK_MODULES:
            if importlib.util.find_spec(mod) is not None:
                try:
                    ver = importlib.metadata.version(mod.replace("_", "-"))
                except importlib.metadata.PackageNotFoundError:
                    ver = "unknown"
                return mod, ver
        return None, None

    def missing_credentials(self) -> list[str]:
        return [name for name in REQUIRED_ENV if not secret_present(name)]

    def connect(self, user_initiated: bool) -> ProviderInfo:
        if not user_initiated:
            raise PermissionError("Kotak connection can only be started by the user from Settings.")
        db.log_connection("kotak", "connect_requested", "User clicked Connect Kotak")
        missing = self.missing_credentials()
        sdk, ver = self.detect_sdk()
        self.info.sdk, self.info.sdk_version = sdk, ver
        if missing:
            self.info.status = ProviderStatus.SETUP_REQUIRED
            self.info.message = ("Credentials not configured locally. Add these variables to your .env file "
                                 f"(never paste them into chat): {', '.join(missing)}.")
        elif sdk is None:
            self.info.status = ProviderStatus.SETUP_REQUIRED
            self.info.message = "No Kotak Neo SDK is installed. It will be selected from the official documentation during integration."
        else:
            self.info.status = ProviderStatus.SETUP_REQUIRED
            self.info.message = ("Credentials and an SDK were found, but the integration adapter is not implemented yet: "
                                 "the authentication flow and data features must first be verified against the current "
                                 "official Kotak Neo documentation. Nothing was sent to Kotak.")
        self.info.live_data = False
        db.log_connection("kotak", "connect_result", f"{self.info.status.value}: {self.info.message}")
        return self.info

    def disconnect(self) -> ProviderInfo:
        self._session = None
        self.info.status = ProviderStatus.DISCONNECTED
        self.info.live_data = False
        self.info.message = "Disconnected. No session credentials are held."
        db.log_connection("kotak", "disconnect", "Session cleared")
        return self.info

    def test_connection(self) -> dict:
        sdk, ver = self.detect_sdk()
        return {
            "network_calls_made": 0,
            "credentials_configured": not self.missing_credentials(),
            "missing_variables": self.missing_credentials(),
            "sdk_module": sdk, "sdk_version": ver,
            "status": self.info.status.value,
            "note": "Local checks only. A real connection test will be added after the integration is verified.",
        }

import inspect
import re
from pathlib import Path

import pytest

from terminal.providers.base import MarketDataProvider, ProviderStatus
from terminal.providers.kotak_neo import KotakNeoProvider
from terminal.providers.manager import provider_manager

ROOT = Path(__file__).resolve().parent.parent


def test_default_state_is_disconnected():
    m = provider_manager()
    assert m.status() == ProviderStatus.DISCONNECTED
    assert not m.live_data_ok()


def test_no_automatic_login_on_import_or_page_load(no_network, monkeypatch):
    calls = []
    monkeypatch.setattr(KotakNeoProvider, "connect", lambda self, user_initiated: calls.append(1))
    import importlib

    importlib.import_module("terminal.ui.common")
    for mod in ("overview", "chart_terminal", "market_watch", "scanner_page", "news_intel", "fno_analytics",
                "backtest_lab", "paper_trading", "journal", "data_manager", "settings_page"):
        importlib.import_module(f"terminal.ui.pages.{mod}")
    from terminal import clock
    clock.now()
    assert calls == []
    assert provider_manager().status() == ProviderStatus.DISCONNECTED


def test_connect_requires_user_action():
    with pytest.raises(PermissionError):
        KotakNeoProvider().connect(user_initiated=False)


def test_missing_credentials_keeps_app_usable(no_network):
    p = KotakNeoProvider()
    info = p.connect(user_initiated=True)
    assert info.status == ProviderStatus.SETUP_REQUIRED
    assert "KOTAK_CONSUMER_KEY" in info.message and not info.live_data
    assert p.test_connection()["network_calls_made"] == 0


def test_credentials_present_still_no_network_and_no_session(no_network, monkeypatch):
    for n in ("KOTAK_CONSUMER_KEY", "KOTAK_CONSUMER_SECRET", "KOTAK_MOBILE_NUMBER", "KOTAK_UCC"):
        monkeypatch.setenv(n, "dummy-value-1234")
    p = KotakNeoProvider()
    info = p.connect(user_initiated=True)
    assert info.status == ProviderStatus.SETUP_REQUIRED and not info.live_data
    assert "dummy-value-1234" not in info.message
    assert p.disconnect().status == ProviderStatus.DISCONNECTED


def test_authentication_failure_is_reported_safely(no_network, monkeypatch):
    """A failure inside the provider must surface as a status, never as a crash or a secret leak."""
    from terminal import db

    monkeypatch.setenv("KOTAK_CONSUMER_SECRET", "super-secret-value")
    db.log_connection("kotak", "auth_failed", "login failed for secret=super-secret-value token=abc123")
    log = db.rows("SELECT detail FROM connection_log")[-1]["detail"]
    assert "super-secret-value" not in log and "abc123" not in log


ORDER_WORDS = re.compile(r"\b(place_order|modify_order|cancel_order|place_stock_order|submit_order|order_place)\b")


def test_no_provider_exposes_order_methods():
    for cls in (MarketDataProvider, KotakNeoProvider):
        names = [n for n, _ in inspect.getmembers(cls)]
        assert not [n for n in names if "order" in n.lower()], names


def test_no_real_order_code_anywhere():
    hits = []
    for p in (ROOT / "terminal").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for m in ORDER_WORDS.finditer(text):
            before = text[max(0, m.start() - 6):m.start()]
            if m.group(1) == "cancel_order" and (p.name == "paper.py" or before.endswith("paper.")):
                continue  # local paper-order cancel (a database update), no network
            hits.append(f"{p.name}: {m.group(1)}")
    assert hits == []


def test_local_start_is_bound_to_localhost():
    assert "--server.address localhost" in (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert "start.ps1" in (ROOT / "Start IndQuant Terminal.bat").read_text(encoding="utf-8")
    cfg = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "gatherUsageStats = false" in cfg and "showErrorDetails = false" in cfg


def test_secrets_and_data_never_committed():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for p in (".env", ".streamlit/secrets.toml", ".venv/", "data/", "logs/", "exports/"):
        assert p in ignored


def test_env_example_has_placeholders_only():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            assert line.split("=", 1)[1].strip() in ("", "<your-value>") or line.split("=", 1)[1].strip().startswith("<")

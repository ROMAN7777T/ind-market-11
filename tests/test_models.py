from terminal.config import DEFAULT_PAPER, DEFAULT_RISK, DEFAULT_SESSION
from terminal.models import validate_section


def test_defaults_are_valid():
    for name, d in (("session", DEFAULT_SESSION), ("risk", DEFAULT_RISK), ("paper", DEFAULT_PAPER)):
        clean, errs = validate_section(name, dict(d))
        assert errs == [] and clean


def test_bad_session_times_rejected():
    _, errs = validate_section("session", dict(DEFAULT_SESSION, flat_by="16:00"))
    assert errs
    _, errs = validate_section("session", dict(DEFAULT_SESSION, market_open="9:15"))
    assert errs


def test_bad_risk_rejected():
    assert validate_section("risk", dict(DEFAULT_RISK, risk_per_trade_pct=-1))[1]
    assert validate_section("risk", dict(DEFAULT_RISK, risk_per_trade_pct=3.0, max_open_risk_pct=1.0))[1]

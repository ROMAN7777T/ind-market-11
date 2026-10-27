import logging

import pytest

from terminal import db
from terminal.providers.stream import ReconnectingStream, StreamState
from terminal.secure import REDACTED, RedactingFilter, get_secret, redact


def test_redacts_env_values_and_patterns(monkeypatch):
    monkeypatch.setenv("KOTAK_MPIN", "482916")
    s = redact("mpin 482916 password=hunter2 Authorization: Bearer abc.def token: 'xyz' key sk-ant-api03-ABCDEFGHIJKLMN")
    for leaked in ("482916", "hunter2", "abc.def", "sk-ant-api03-ABCDEFGHIJKLMN"):
        assert leaked not in s
    assert REDACTED in s


def test_placeholder_values_are_not_secrets(monkeypatch):
    monkeypatch.setenv("KOTAK_UCC", "<your-value>")
    assert get_secret("KOTAK_UCC") is None


def test_unknown_secret_name_rejected():
    with pytest.raises(KeyError):
        get_secret("HOME")


def test_settings_refuse_secret_like_keys():
    for k in ("kotak_password", "api_key", "session_token", "mpin", "totp_secret"):
        with pytest.raises(ValueError):
            db.set_setting(k, "x")
    with pytest.raises(ValueError):
        db.set_setting("broker", {"access_token": "x"})


def test_logging_filter_redacts(caplog, monkeypatch):
    monkeypatch.setenv("KOTAK_PASSWORD", "pa55word!")
    log = logging.getLogger("t_redact")
    log.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO):
        log.info("login with pa55word! failed")
    assert "pa55word!" not in caplog.text


class FakeWS:
    def __init__(self, script):
        self.script = list(script)
        self.closed = False

    def recv(self):
        item = self.script.pop(0) if self.script else ""
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def test_stream_recovers_after_interruption():
    sockets = [FakeWS(["tick1", ConnectionResetError()]), FakeWS(["tick2", "tick3"])]
    got, sleeps = [], []
    s = ReconnectingStream("wss://example.invalid/feed", factory=lambda url: sockets.pop(0), on_message=got.append,
                           sleep=sleeps.append)
    state = s.run(max_messages=3)
    assert got == ["tick1", "tick2", "tick3"]
    assert state == StreamState.CLOSED and sleeps == [1.0]


def test_stream_marks_stale_then_failed():
    def boom(url):
        raise OSError("down")

    s = ReconnectingStream("wss://example.invalid/feed", factory=boom, max_retries=3, sleep=lambda x: None)
    assert s.run() == StreamState.FAILED
    assert len(s.errors) == 4


def test_stream_requires_tls():
    with pytest.raises(ValueError):
        ReconnectingStream("ws://insecure")

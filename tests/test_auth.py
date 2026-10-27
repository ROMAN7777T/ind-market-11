from terminal import auth


def test_local_hosts_are_local():
    for h in ("localhost:8501", "127.0.0.1:8501", "[::1]:8501", "LOCALHOST"):
        assert not auth.is_remote({"host": h})


def test_remote_hosts_and_proxies_are_remote():
    assert auth.is_remote({"host": "indquant.streamlit.app"})
    assert auth.is_remote({"host": "192.168.1.20:8501"})
    assert auth.is_remote({})  # unknown host: fail closed
    # a spoofed Host header behind a proxy is still remote
    assert auth.is_remote({"host": "localhost", "x-forwarded-for": "203.0.113.9"})


def test_password_sources_and_placeholders(monkeypatch):
    monkeypatch.delenv("TERMINAL_PASSWORD", raising=False)
    assert auth.configured_password() is None
    monkeypatch.setenv("TERMINAL_PASSWORD", "<choose-a-long-unique-password>")
    assert auth.configured_password() is None  # placeholder never counts
    monkeypatch.setenv("TERMINAL_PASSWORD", "correct horse battery staple")
    assert auth.configured_password() == "correct horse battery staple"


def test_password_check_is_exact():
    assert auth.check_password("s3cret-pass", "s3cret-pass")
    assert not auth.check_password("s3cret-pas", "s3cret-pass")
    assert not auth.check_password("", "s3cret-pass")

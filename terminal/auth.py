"""Access control for hosted deployments.

Local use (the browser and server on the same computer) needs no password. Anywhere else the
app fails closed: it opens only when `app_password` is configured (Streamlit secrets or the
TERMINAL_PASSWORD environment variable) and the visitor enters it.
"""
from __future__ import annotations

import hmac
import os

LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def configured_password() -> str | None:
    pw = os.environ.get("TERMINAL_PASSWORD")
    if not pw:
        try:
            import streamlit as st

            pw = st.secrets.get("app_password")
        except Exception:  # no secrets file locally
            pw = None
    if not pw or str(pw).strip().startswith("<"):
        return None
    return str(pw)


def host_of(host_header: str | None) -> str:
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        return h.split("]")[0] + "]"
    return h.split(":")[0]


def is_local(host_header: str | None) -> bool:
    return host_of(host_header) in LOCAL_HOSTS


def check_password(entered: str, expected: str) -> bool:
    return hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def request_headers() -> dict:
    try:
        import streamlit as st

        return {k.lower(): v for k, v in st.context.headers.items()}
    except Exception:
        return {}


def is_remote(headers: dict) -> bool:
    """Remote if the Host is not this computer, or if any reverse proxy forwarded the request."""
    if any(h in headers for h in ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")):
        return True
    return not is_local(headers.get("host"))


def hosted() -> bool:
    return is_remote(request_headers())

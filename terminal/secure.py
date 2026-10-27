"""Secret handling: read from the local environment only, redact everywhere else.

Secrets are never stored in SQLite, never logged, never sent to an AI provider.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

# Names of environment variables that hold secrets. `.env.example` lists them with placeholders.
SECRET_ENV_VARS = (
    "KOTAK_CONSUMER_KEY",
    "KOTAK_CONSUMER_SECRET",
    "KOTAK_MOBILE_NUMBER",
    "KOTAK_UCC",
    "KOTAK_MPIN",
    "KOTAK_PASSWORD",
    "KOTAK_TOTP_SECRET",
    "KOTAK_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY",
)

_SECRET_KEY_HINTS = ("password", "secret", "token", "mpin", "otp", "totp", "api_key", "apikey", "consumer_key")

_PATTERNS = [
    re.compile(r"(?i)(password|secret|token|mpin|otp|totp|api[_-]?key|authorization)(\s*[=:]\s*|\"\s*:\s*\")([^\s\"',;]+)"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{10,}"),
]

REDACTED = "***REDACTED***"


def load_env() -> None:
    """Load the local .env file if present. Never prints its contents."""
    try:
        from dotenv import load_dotenv

        from .config import PROJECT_ROOT

        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass


def get_secret(name: str) -> str | None:
    if name not in SECRET_ENV_VARS:
        raise KeyError(f"{name} is not a registered secret variable")
    value = os.environ.get(name)
    if value is None or value.strip() == "" or value.strip().startswith("<"):
        return None
    return value


def secret_present(name: str) -> bool:
    return get_secret(name) is not None


def redact(text: Any) -> str:
    s = str(text)
    for name in SECRET_ENV_VARS:
        v = os.environ.get(name)
        if v and len(v) >= 4 and not v.startswith("<"):
            s = s.replace(v, REDACTED)
    s = _PATTERNS[1].sub(f"Bearer {REDACTED}", s)
    s = _PATTERNS[0].sub(lambda m: m.group(0) if m.group(3).startswith(REDACTED[:3]) or m.group(3) == "Bearer"
                         else f"{m.group(1)}{m.group(2)}{REDACTED}", s)
    s = _PATTERNS[2].sub(REDACTED, s)
    return s


def assert_not_secret(key: str, value: Any) -> None:
    """Refuse to persist anything that looks like a credential."""
    k = key.lower()
    if any(h in k for h in _SECRET_KEY_HINTS):
        raise ValueError(f"Refusing to store '{key}': secrets belong in the local .env file, not the database.")
    if isinstance(value, dict):
        for sub_k, sub_v in value.items():
            assert_not_secret(str(sub_k), sub_v)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging() -> logging.Logger:
    from .config import ensure_dirs, log_dir

    ensure_dirs()
    logger = logging.getLogger("terminal")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_dir() / "terminal.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        fh.addFilter(RedactingFilter())
        logger.addHandler(fh)
    return logger

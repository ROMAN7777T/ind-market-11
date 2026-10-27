"""Reconnecting WebSocket wrapper for future live streaming.

Transport-agnostic: the socket factory is injected (websocket-client's `create_connection`
in production, a fake in tests). On interruption the stream marks itself STALE, backs off
and retries a bounded number of times. It never fabricates ticks.
"""
from __future__ import annotations

import time
from typing import Callable


class StreamState:
    IDLE = "IDLE"
    CONNECTED = "CONNECTED"
    STALE = "STALE"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


class ReconnectingStream:
    def __init__(self, url: str, factory: Callable | None = None, on_message: Callable[[str], None] | None = None,
                 max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 30.0, sleep: Callable = time.sleep):
        if not url.startswith("wss://"):
            raise ValueError("Only secure wss:// streams are allowed")
        self.url = url
        self.factory = factory or self._default_factory
        self.on_message = on_message or (lambda m: None)
        self.max_retries, self.base_delay, self.max_delay, self.sleep = max_retries, base_delay, max_delay, sleep
        self.state = StreamState.IDLE
        self.retries = 0
        self.messages = 0
        self.errors: list[str] = []
        self._ws = None
        self._stop = False

    @staticmethod
    def _default_factory(url: str):
        from websocket import create_connection

        return create_connection(url, timeout=10)

    def _connect(self) -> bool:
        try:
            self._ws = self.factory(self.url)
            self.state = StreamState.CONNECTED
            self.retries = 0
            return True
        except Exception as e:
            self.errors.append(f"connect: {type(e).__name__}")
            return False

    def run(self, max_messages: int | None = None) -> str:
        while not self._stop:
            if self._ws is None and not self._connect():
                if not self._backoff():
                    return self.state
                continue
            try:
                msg = self._ws.recv()
                if msg is None or msg == "":
                    raise ConnectionError("empty frame / closed by server")
                self.messages += 1
                self.on_message(msg)
                if max_messages and self.messages >= max_messages:
                    self.close()
            except Exception as e:
                self.errors.append(f"recv: {type(e).__name__}")
                self.state = StreamState.STALE  # data is now stale; consumers must not show it as live
                self._safe_close()
                if not self._backoff():
                    return self.state
        return self.state

    def _backoff(self) -> bool:
        self.retries += 1
        if self.retries > self.max_retries:
            self.state = StreamState.FAILED
            return False
        self.state = StreamState.STALE
        self.sleep(min(self.max_delay, self.base_delay * 2 ** (self.retries - 1)))
        return True

    def _safe_close(self) -> None:
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None

    def close(self) -> None:
        self._stop = True
        self._safe_close()
        self.state = StreamState.CLOSED

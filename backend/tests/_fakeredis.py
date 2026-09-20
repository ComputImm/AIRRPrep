"""
A minimal in-memory stand-in for the Redis client, for tests only.

Only the handful of operations the modules under test actually use is
implemented -- get/set (with `ex` and `nx`)/delete/ttl/expire/exists -- with
an injectable clock so expiry can be tested without sleeping.
"""

from __future__ import annotations


class FakeRedis:
    def __init__(self, now: float = 1_000_000.0):
        self._data: dict[str, str] = {}
        self._expiry: dict[str, float] = {}
        self.now = now

    # -- clock ------------------------------------------------------------
    def advance(self, seconds: float) -> None:
        self.now += seconds

    def _expired(self, key: str) -> bool:
        deadline = self._expiry.get(key)
        return deadline is not None and deadline <= self.now

    def _sweep(self, key: str) -> None:
        if self._expired(key):
            self._data.pop(key, None)
            self._expiry.pop(key, None)

    # -- commands ---------------------------------------------------------
    def get(self, key: str):
        self._sweep(key)
        return self._data.get(key)

    def set(self, key: str, value, ex: int | None = None, nx: bool = False):
        self._sweep(key)
        if nx and key in self._data:
            return None
        self._data[key] = value if isinstance(value, str) else str(value)
        if ex is not None:
            self._expiry[key] = self.now + ex
        else:
            self._expiry.pop(key, None)
        return True

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            self._expiry.pop(key, None)
            removed += 1 if self._data.pop(key, None) is not None else 0
        return removed

    def exists(self, key: str) -> int:
        self._sweep(key)
        return 1 if key in self._data else 0

    def ttl(self, key: str) -> int:
        self._sweep(key)
        if key not in self._data:
            return -2
        deadline = self._expiry.get(key)
        return -1 if deadline is None else int(deadline - self.now)

    def expire(self, key: str, seconds: int) -> bool:
        self._sweep(key)
        if key not in self._data:
            return False
        self._expiry[key] = self.now + seconds
        return True

    def keys(self, pattern: str = "*") -> list[str]:
        for key in list(self._data):
            self._sweep(key)
        if pattern == "*":
            return list(self._data)
        prefix = pattern.rstrip("*")
        return [k for k in self._data if k.startswith(prefix)]

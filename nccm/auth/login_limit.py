"""In-memory login rate limiting by username + client IP."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

_MAX_FAILURES = int(os.environ.get("NCCM_LOGIN_MAX_FAILURES", "8"))
_WINDOW_SECONDS = int(os.environ.get("NCCM_LOGIN_WINDOW_SECONDS", "900"))
_LOCKOUT_SECONDS = int(os.environ.get("NCCM_LOGIN_LOCKOUT_SECONDS", "300"))

_state: dict[tuple[str, str], tuple[int, float, float]] = {}


class LoginRateLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"login temporarily locked; retry after {retry_after}s")


@dataclass(frozen=True)
class LoginAttemptKey:
    username: str
    ip: str


def _key(username: str, ip: str) -> tuple[str, str]:
    return ((username or "").strip().lower()[:128], (ip or "unknown")[:64])


def _purge(now: float) -> None:
    expired: list[tuple[str, str]] = []
    for k, (_failures, last, locked_until) in _state.items():
        if locked_until > now:
            continue
        if last < now - _WINDOW_SECONDS:
            expired.append(k)
    for k in expired:
        _state.pop(k, None)


def check_login_allowed(*, username: str, ip: str) -> None:
    now = time.time()
    _purge(now)
    k = _key(username, ip)
    entry = _state.get(k)
    if not entry:
        return
    _failures, _last, locked_until = entry
    if locked_until > now:
        raise LoginRateLimited(max(1, int(locked_until - now)))


def record_login_failure(*, username: str, ip: str) -> None:
    now = time.time()
    _purge(now)
    k = _key(username, ip)
    failures, _last, locked_until = _state.get(k, (0, now, 0.0))
    failures += 1
    if failures >= _MAX_FAILURES:
        locked_until = now + _LOCKOUT_SECONDS
    _state[k] = (failures, now, locked_until)


def record_login_success(*, username: str, ip: str) -> None:
    _state.pop(_key(username, ip), None)

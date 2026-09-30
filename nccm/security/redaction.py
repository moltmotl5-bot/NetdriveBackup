"""Redact sensitive values from log/audit text."""
from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(password\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(enable_password\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(authorization\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(x-api-key\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(csrf_token\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(token\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(cookie\s*[=:]\s*)(\S+)"), r"\1***"),
]


def redact_text(text: str) -> str:
    out = text or ""
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out

"""CSRF token helpers and POST validation middleware."""
from __future__ import annotations

import re
import secrets
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"

_CSRF_EXEMPT_PATHS = {"/health"}
_CSRF_EXEMPT_PREFIXES = ("/api/v1",)


def get_or_create_csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return str(token)


def rotate_csrf_token(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(CSRF_SESSION_KEY)
    if not expected or not submitted:
        return False
    return secrets.compare_digest(str(expected), str(submitted))


def csrf_required(path: str) -> bool:
    if path in _CSRF_EXEMPT_PATHS:
        return False
    return not any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES)


async def _read_body(receive: Receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    return body


def _extract_csrf_from_body(content_type: str, body: bytes) -> str | None:
    ct = (content_type or "").lower()
    if "application/x-www-form-urlencoded" in ct:
        values = parse_qs(body.decode("utf-8", errors="replace"))
        raw = values.get(CSRF_FORM_FIELD, [None])[0]
        return str(raw) if raw is not None else None
    if "multipart/form-data" in ct:
        # Match csrf field whether it appears before or after file parts.
        patterns = [
            rb'name="' + re.escape(CSRF_FORM_FIELD.encode()) + rb'"\r\n\r\n([^\r\n]+)',
            rb'name="' + re.escape(CSRF_FORM_FIELD.encode()) + rb'"\s*\r\n\r\n([^\r\n]+)',
        ]
        for pat in patterns:
            match = re.search(pat, body)
            if match:
                return match.group(1).decode("utf-8", errors="replace")
    return None


class CsrfMiddleware:
    """Validate CSRF token on POST; replay request body for downstream handlers."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "")
        if method != "POST" or not csrf_required(path):
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        token = _extract_csrf_from_body(headers.get("content-type", ""), body)
        session = scope.get("session") or {}
        expected = session.get(CSRF_SESSION_KEY)
        if not expected or not token or not secrets.compare_digest(str(expected), str(token)):
            response = PlainTextResponse("CSRF validation failed", status_code=403)
            await response(scope, receive, send)
            return

        sent = False

        async def replay_receive() -> dict:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from web.security import security_headers

        extra = security_headers()

        async def send_with_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                for key, value in extra.items():
                    if key.lower() not in existing:
                        headers.append([key.encode(), value.encode()])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)

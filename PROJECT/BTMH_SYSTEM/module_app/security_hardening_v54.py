"""BTMH Security V5.4 customer-release HTTP hardening.

This module is intentionally dependency-light and can be disabled in development
with BTMH_ENV=development. It never logs or returns credentials.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_URI_CREDENTIAL_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<userinfo>[^/@\s]+)@", re.I)
_SENSITIVE_KEYS = {
    "password", "passwd", "pwd", "secret", "token", "access_token", "refresh_token",
    "authorization", "cookie", "mfa_secret", "totp_secret",
    "private_key", "face_template_key", "database_url", "dsn",
}
_SOURCE_KEYS = {"source", "camera_source", "rtsp", "rtsp_url", "stream_url", "url"}


def redact_uri(value: str) -> str:
    """Redact URI user-info while preserving the host/path for diagnostics."""
    if not isinstance(value, str):
        return value
    try:
        parts = urlsplit(value)
        if parts.scheme and parts.netloc and "@" in parts.netloc:
            host = parts.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parts.scheme, f"***:***@{host}", parts.path, parts.query, parts.fragment))
    except Exception:
        pass
    return _URI_CREDENTIAL_RE.sub(lambda m: f"{m.group('scheme')}***:***@", value)


def sanitize_payload(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_KEYS or normalized.endswith("_password") or normalized.endswith("_secret") or normalized.endswith("_token"):
                clean[key] = "***"
            elif normalized in _SOURCE_KEYS:
                clean[key] = redact_uri(item) if isinstance(item, str) else sanitize_payload(item, parent_key=normalized)
            else:
                clean[key] = sanitize_payload(item, parent_key=normalized)
        return clean
    if isinstance(value, list):
        return [sanitize_payload(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_payload(item, parent_key=parent_key) for item in value)
    if isinstance(value, str):
        return redact_uri(value)
    return value


class V54SecretRedactionFilter(logging.Filter):
    """Best-effort guard preventing URI credentials from entering support logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact_uri(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(redact_uri(v) if isinstance(v, str) else v for v in record.args)
            elif isinstance(record.args, dict):
                record.args = sanitize_payload(record.args)
        except Exception:
            pass
        return True


def install_log_redaction() -> None:
    root_logger = logging.getLogger()
    if getattr(root_logger, "_btmh_v54_redaction", False):
        return
    redactor = V54SecretRedactionFilter()
    for handler in root_logger.handlers:
        handler.addFilter(redactor)
    root_logger.addFilter(redactor)
    root_logger._btmh_v54_redaction = True


def protect_status_provider(provider: Any) -> None:
    """Wrap an in-process status provider so credentials never leave it."""
    if provider is None or getattr(provider, "_btmh_v54_status_protected", False):
        return
    original = getattr(provider, "status", None)
    if not callable(original):
        return
    def safe_status(*args: Any, **kwargs: Any) -> Any:
        return sanitize_payload(original(*args, **kwargs))
    try:
        setattr(provider, "status", safe_status)
        setattr(provider, "_btmh_v54_status_protected", True)
    except Exception:
        # Some providers use slots/read-only attributes; JSON response redaction
        # remains active as a second, independent protection layer.
        return


class V54SecurityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        env = os.getenv("BTMH_ENV", "production").strip().lower()
        production = env not in {"dev", "development", "test", "testing"}
        if production and path in {"/docs", "/redoc", "/openapi.json"}:
            response = JSONResponse({"detail": "Not found"}, status_code=404)
            await response(scope, receive, send)
            return

        start_message: Message | None = None
        body_parts: list[bytes] = []
        is_json = False

        async def guarded_send(message: Message) -> None:
            nonlocal start_message, is_json
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                header_map = {k.lower(): v for k, v in headers}
                content_type = header_map.get(b"content-type", b"").decode("latin-1").lower()
                is_json = "application/json" in content_type or content_type.endswith("+json")
                # Security headers suitable for an internal customer release.
                additions = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"no-referrer",
                    b"permissions-policy": b"camera=(self), microphone=(), geolocation=()",
                    b"cross-origin-resource-policy": b"same-origin",
                }
                existing = {k.lower() for k, _ in headers}
                for key, value in additions.items():
                    if key not in existing:
                        headers.append((key, value))
                message = {**message, "headers": headers}
                start_message = message
                if not is_json:
                    await send(message)
                return

            if message["type"] == "http.response.body" and is_json:
                body_parts.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                raw = b"".join(body_parts)
                clean_body = raw
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    payload = sanitize_payload(payload)
                    clean_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                except Exception:
                    # Never make a valid application response fail only because it was not JSON-decodable.
                    clean_body = raw
                start = start_message or {"type": "http.response.start", "status": 200, "headers": []}
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(clean_body)).encode("ascii")))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": clean_body, "more_body": False})
                return

            await send(message)

        await self.app(scope, receive, guarded_send)


def install_v54_hardening(app: Any) -> None:
    if getattr(getattr(app, "state", object()), "v54_hardening_installed", False):
        return
    install_log_redaction()
    app.add_middleware(V54SecurityMiddleware)
    app.state.v54_hardening_installed = True

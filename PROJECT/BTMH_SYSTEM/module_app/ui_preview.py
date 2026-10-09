"""Opt-in, isolated UI preview policy. No product imports or hardware effects."""
from __future__ import annotations

import ipaddress
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

BASE = Path(__file__).resolve().parent.parent
PREVIEW_DIRECTORY = BASE / ".btmh-ui-preview"
DEFAULT_PORT = 8810
NOTICE = (
    "UI PREVIEW · Dữ liệu kiểm thử riêng, không phải dữ liệu vận hành. "
    "Camera, nhận diện AI và ghi hình không khả dụng. "
    "QR: quản lý lời mời; thu mẫu khuôn mặt cần HTTPS và phần cứng thật."
)


def _validate_existing_tree(root: Path) -> None:
    # Imports create keys/directories, so inspect existing children first.
    # Do not follow a junction, symlink or multiply-linked file into real data.
    pending = [root] if root.exists() else []
    while pending:
        path = pending.pop()
        info = path.lstat()
        redirected = (path.is_symlink() or
                      bool(getattr(info, "st_file_attributes", 0) &
                           getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or
                      (stat.S_ISREG(info.st_mode) and info.st_nlink > 1))
        if redirected or not path.resolve().is_relative_to(root):
            raise RuntimeError("UI Preview profile must not contain redirected data")
        if stat.S_ISDIR(info.st_mode):
            pending.extend(path.iterdir())


def validated_preview() -> bool:
    if os.getenv("BTMH_UI_PREVIEW", "0") != "1":
        return False
    root = Path(os.environ.get("CAMPUSFACE_DATA_ROOT", "")).absolute()
    # Do not accept a junction/symlink redirecting the private profile elsewhere.
    container = PREVIEW_DIRECTORY.absolute()
    if container.resolve() != container or root.resolve() != root:
        raise RuntimeError("UI Preview data directory must not be redirected")
    relative = root.relative_to(container) if root.is_relative_to(container) else None
    permitted = relative is not None and (
        relative.parts == ("default",) or
        (len(relative.parts) == 2 and relative.parts[0] == "tests")
    )
    if not permitted or os.getenv("CAMPUSFACE_DB_MODE") != "sqlite":
        raise RuntimeError("UI Preview requires its private SQLite profile")
    if os.getenv("BTMH_ENV") != "development" or os.getenv("MODULE_HOST") != "127.0.0.1":
        raise RuntimeError("UI Preview requires development mode and 127.0.0.1")
    _validate_existing_tree(root)
    return True


def prepare_environment(*, profile: str = "default", port: int = DEFAULT_PORT) -> Path:
    """Called by the separate runner BEFORE any application import."""
    relative = Path(profile)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid preview profile")
    if not 1 <= int(port) <= 65535:
        raise ValueError("Invalid preview port")
    # Do not inherit customer credentials, camera profiles or integration settings.
    for key in list(os.environ):
        if key.startswith(("BTMH_", "CAMPUSFACE_", "MODULE_")) or key in {
            "FACE_DEMO_KEY", "OPENCV_FFMPEG_CAPTURE_OPTIONS",
        }:
            del os.environ[key]
    root = (PREVIEW_DIRECTORY / relative).absolute()
    os.environ.update({
        "BTMH_UI_PREVIEW": "1", "BTMH_ENV": "development",
        "CAMPUSFACE_DATA_ROOT": str(root), "CAMPUSFACE_DB_MODE": "sqlite",
        "MODULE_HOST": "127.0.0.1", "MODULE_PORT": str(port),
    })
    validated_preview()
    return root


def hardware_unavailable(path: str, method: str) -> bool:
    """Allow only known independent UI APIs; future integrations fail closed here.

    This policy runs after the existing HTTP authentication/RBAC guards.
    It never authorizes a request or changes an existing permission.
    """
    if not path.startswith("/api/v1/"):
        return path.rstrip("/") in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
    reading = method.upper() in {"GET", "HEAD"}
    if path == "/api/v1/health":
        return False
    if path.startswith("/api/v1/auth/"):
        return not (
            path in {
                "/api/v1/auth/status", "/api/v1/auth/bootstrap-local",
                "/api/v1/auth/login", "/api/v1/auth/logout",
                "/api/v1/auth/profile", "/api/v1/auth/password",
                "/api/v1/auth/mfa/verify",
            } or (reading and path in {"/api/v1/auth/admin-security", "/api/v1/auth/sms/security"})
        )
    if path.startswith("/api/v1/admin/face-enrollment/"):
        return path.endswith(("/approve", "/frame", "/finalize"))
    if path.startswith(("/api/v1/admin/users", "/api/v1/admin/roles")):
        return False
    if path.startswith("/api/v1/mobile/"):
        return not (path.startswith("/api/v1/mobile/auth/") or
                    (reading and path in {"/api/v1/mobile/summary", "/api/v1/mobile/presence",
                                          "/api/v1/mobile/history/recognition", "/api/v1/mobile/history/hr"}))
    if path.startswith(("/api/v1/students", "/api/v1/stores", "/api/v1/work-shifts", "/api/v1/zones")):
        return False
    if path.startswith("/api/v1/employees/"):
        return not (path.endswith("/shift") or (reading and path.endswith("/face-validation")))
    if reading and path.startswith((
        "/api/v1/history/", "/api/v1/dashboard/", "/api/v1/hr-report/",
        "/api/v1/presence/", "/api/v1/visitors", "/api/v1/attendance/",
        "/api/v1/events", "/api/v1/exports/", "/api/v1/exceptions",
    )):
        return False
    return not (reading and path in {
        "/api/v1/recognition/cameras", "/api/v1/recognition/recent",
        "/api/v1/cameras/devices", "/api/v1/system/audit",
        "/api/v1/operations/rules",
        "/api/v1/module/contract", "/api/v1/backups",
    })


class LocalPreviewMiddleware:
    """Enforce loopback/Host boundaries and reject all realtime transports."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        client = (scope.get("client") or ("", 0))[0]
        try:
            local_client = ipaddress.ip_address(client).is_loopback
        except ValueError:
            local_client = False
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        try:
            authority = urlsplit("//" + headers.get(b"host", b"").decode("latin1"))
            port = authority.port  # Validate malformed/out-of-range ports as well.
            local_host = (authority.hostname in {"localhost", "127.0.0.1", "::1"} and
                          authority.username is None and authority.password is None and
                          not authority.path and not authority.query and not authority.fragment)
        except ValueError:
            local_host = False
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008,
                        "reason": "Realtime unavailable in UI Preview"})
            return
        if not local_client or not local_host:
            from starlette.responses import JSONResponse
            response = JSONResponse({"detail": "UI Preview chỉ khả dụng trên localhost"}, status_code=403)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


def preview_html(path: Path) -> str:
    """Keep every existing frontend script and the real authentication gate."""
    source = path.read_text(encoding="utf-8")
    banner = (
        '<aside role="status" id="btmh-ui-preview-notice" '
        'style="position:fixed;bottom:0;left:0;right:0;z-index:2147483647;'
        'padding:10px 18px;background:#6f2435;color:#fffdf9;'
        'font:13px/1.5 system-ui,sans-serif;text-align:center">' + NOTICE + '</aside>'
        '<style>body{padding-bottom:64px!important}</style>'
    )
    return source.replace("</body>", banner + "</body>")

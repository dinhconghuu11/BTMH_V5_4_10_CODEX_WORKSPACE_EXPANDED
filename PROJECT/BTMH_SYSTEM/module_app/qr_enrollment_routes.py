"""HTTP adapters for the two-table reviewed enrollment workflow.

No schema or biometric publication lives here. QR capability is separate from
management authentication and the existing read-only Mobile Viewer.
"""
from __future__ import annotations

import os
import base64
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from . import qr_enrollment as service
from .enrollment_capture import CAPTURE
from .config import UI_PREVIEW
from .ui_preview import preview_html

QR_COOKIE = "btmh_enrollment_capture"
QR_PREFIX = "/api/v1/qr-enrollment"
ADMIN_PREFIX = "/api/v1/admin/face-enrollment"
_RATE_LOCK = threading.Lock()
_RATE: OrderedDict = OrderedDict()


class EnrollmentBodyLimitMiddleware:
    """Bound streamed/chunked JSON before the route's body parser buffers it."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        protected = path.startswith((QR_PREFIX + "/", ADMIN_PREFIX + "/", "/api/v1/enrollment/"))
        if scope.get("type") != "http" or scope.get("method") not in {"POST", "PUT", "PATCH"} or not protected:
            return await self.app(scope, receive, send)
        limit = 3 * 1024 * 1024 if path.endswith("/frame") or path.startswith("/api/v1/enrollment/") else 16 * 1024
        size = 0
        started = False

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message.get("type") == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise HTTPException(413, {"code": "PAYLOAD_TOO_LARGE", "message": "Dữ liệu đăng ký vượt giới hạn."})
            return message

        async def tracked_send(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except HTTPException as exc:
            if exc.status_code != 413 or started:
                raise
            response = JSONResponse({"detail": exc.detail}, status_code=413, headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)


def enrollment_enabled() -> bool:
    return os.getenv("BTMH_QR_ENROLLMENT_ENABLED", "1").strip() == "1"


def _error(exc):
    if isinstance(exc, service.EnrollmentError):
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc),
                                        "field": getattr(exc, "field", None)},
                            headers={"Cache-Control": "no-store"}) from None
    if isinstance(exc, (ValueError, PermissionError)):
        raise HTTPException(400, {"code": "CAPTURE_RETRY", "message": "Chưa thể hoàn tất. Kiểm tra hướng dẫn và thử lại."},
                            headers={"Cache-Control": "no-store"}) from None
    raise HTTPException(503, {"code": "ENROLLMENT_UNAVAILABLE", "message": "Đăng ký FaceID tạm thời chưa sẵn sàng."},
                        headers={"Cache-Control": "no-store"}) from None


def _rate(request, action, *, maximum=30, seconds=60):
    # Bounded in-memory limiter. Store no token, body, employee or password.
    now = time.monotonic()
    key = (request.client.host if request.client else "unknown", action)
    with _RATE_LOCK:
        entry = _RATE.pop(key, None)
        start, count = entry if entry and now - entry[0] < seconds else (now, 0)
        _RATE[key] = (start, count + 1)
        while len(_RATE) > 1024:
            _RATE.popitem(last=False)
    if count >= maximum:
        raise HTTPException(429, {"code": "RATE_LIMITED", "message": "Vui lòng chờ một chút rồi thử lại."},
                            headers={"Retry-After": str(seconds), "Cache-Control": "no-store"})


def capability_http_guard(request):
    """Only QR routes bypass portal login; each handler validates its capability."""
    path = request.url.path
    if not (path.startswith(QR_PREFIX + "/") or path.startswith(ADMIN_PREFIX) or path.startswith("/api/v1/enrollment/")):
        return None
    if not enrollment_enabled():
        return JSONResponse({"detail": "Đăng ký FaceID mới đang tạm dừng.", "code": "ENROLLMENT_DISABLED"}, status_code=503)
    if not path.startswith(QR_PREFIX + "/"):
        return None
    if request.url.scheme != "https":
        return JSONResponse({"detail": "Đăng ký bằng điện thoại cần kết nối HTTPS được thiết bị tin cậy.", "code": "HTTPS_REQUIRED"}, status_code=403)
    if request.method not in {"GET", "HEAD"}:
        origin = request.headers.get("origin", "").lower().rstrip("/")
        expected = str(request.base_url).lower().rstrip("/")
        if not origin or origin != expected or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Yêu cầu khác nguồn bị từ chối.", "code": "ORIGIN_REJECTED"}, status_code=403)
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
            return JSONResponse({"detail": "Yêu cầu cần dữ liệu JSON.", "code": "JSON_REQUIRED"}, status_code=415)
        raw_size = request.headers.get("content-length")
        if raw_size:
            try:
                if not 0 <= int(raw_size) <= 3 * 1024 * 1024:
                    return JSONResponse({"detail": "Ảnh camera vượt giới hạn.", "code": "IMAGE_TOO_LARGE"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Dữ liệu yêu cầu không hợp lệ.", "code": "INVALID_REQUEST"}, status_code=400)
        action = path.rsplit("/", 1)[-1]
        limits = {"redeem": (10, 60), "consent": (10, 60), "frame": (30, 5), "submit": (10, 60), "reset": (10, 60)}
        if action in limits:
            try:
                maximum, seconds = limits[action]
                _rate(request, action, maximum=maximum, seconds=seconds)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers={"Cache-Control": "no-store", "Retry-After": str(seconds)})
    return None


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartPayload(StrictPayload):
    student_id: int = Field(gt=0)
    store_id: int = Field(gt=0)
    invitation_minutes: int = Field(default=15, ge=5, le=60)


class DecisionPayload(StrictPayload):
    expected_revision: int = Field(ge=0)
    reason: str = Field(default="", max_length=1000)
    duplicate_override: bool = False


class RedeemPayload(StrictPayload):
    invite_secret: str = Field(min_length=40, max_length=128)


class ConsentPayload(StrictPayload):
    granted: bool


class UploadPayload(StrictPayload):
    image: str = Field(min_length=1, max_length=2796247)


class EmptyPayload(StrictPayload):
    pass


def _secret(request):
    return str(request.cookies.get(QR_COOKIE) or "")


def _safe_json(result, response):
    response.headers["Cache-Control"] = "no-store"
    return result


def _invitation_result(result, request):
    """Encode locally with installed OpenCV; never send secrets to a QR service."""
    result = dict(result)
    result.pop("invite_secret", None)
    path = str(result.get("qr_path") or "")
    if not path.startswith("/enroll#invite="):
        return result
    url = str(request.base_url).rstrip("/") + path
    result["qr_url"] = url
    result["capture_https_ready"] = request.url.scheme == "https" and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
    try:
        import cv2
        code = cv2.QRCodeEncoder_create().encode(url)
        code = cv2.copyMakeBorder(code, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
        code = cv2.resize(code, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
        ok, raw = cv2.imencode(".png", code)
        if ok:
            result["qr_data_url"] = "data:image/png;base64," + base64.b64encode(raw.tobytes()).decode("ascii")
    except Exception:
        # The real copyable invitation remains usable; never display a fake QR.
        result["qr_available"] = False
    return result


def desktop_frame(payload, request, actor):
    try:
        if not getattr(payload, "request_id", None):
            raise service.EnrollmentError("Mở phiên đăng ký mới trước khi quét.", code="REQUEST_REQUIRED", status=409)
        with service.desktop_capture_lease(actor, payload.request_id, payload.student_id) as binding:
            if payload.image:
                return CAPTURE.frame_upload(binding["id"], binding["student_id"], payload.image)
            # Preserve desktop's existing camera fallback without changing the
            # dedicated phone route into a camera selection/AI control API.
            from .camera import CAMERA
            CAMERA.hold_enrollment_mode(0.75)
            image = CAMERA.latest_frame()
            if image is None:
                raise ValueError("Camera chưa sẵn sàng")
            return CAPTURE.frame(binding["id"], binding["student_id"], image)
    except Exception as exc:
        _error(exc)


def desktop_finalize(payload, request, actor):
    try:
        if not getattr(payload, "request_id", None):
            raise service.EnrollmentError("Mở phiên đăng ký mới trước khi quét.", code="REQUEST_REQUIRED", status=409)
        if payload.confirm_duplicate:
            raise service.EnrollmentError("Quyết định trùng khuôn mặt phải được duyệt riêng.", code="APPROVAL_REQUIRED", status=403)
        existing = service.get_request(actor, payload.request_id)
        row = existing.get("request", existing)
        if row.get("source_kind") != "DESKTOP" or row.get("created_by_user_id") != actor.get("id") or (payload.student_id is not None and int(payload.student_id) != int(row["student_id"])):
            raise service.EnrollmentError("Phiên đăng ký không khớp nhân viên.", code="REQUEST_BINDING_DENIED", status=403)
        if row.get("status") in {"PENDING_REVIEW", "NEEDS_DUPLICATE_REVIEW"}:
            return existing
        # Binding and capture lease are revalidated before preparation. The
        # durable staging service checks them again under its transaction.
        with service.desktop_capture_lease(actor, payload.request_id, payload.student_id) as binding:
            draft = CAPTURE.prepare(binding["id"], binding["student_id"])
        return service.stage_prepared_request(binding["id"], draft, actor=actor, expected_revision=binding["revision"])
    except Exception as exc:
        _error(exc)


def desktop_reset(payload, request, actor):
    try:
        if not getattr(payload, "request_id", None):
            raise service.EnrollmentError("Mở phiên đăng ký mới trước khi quét.", code="REQUEST_REQUIRED", status=409)
        return service.reset_capture(actor=actor, request_id=payload.request_id)
    except Exception as exc:
        _error(exc)


def install_qr_routes(app, frontend: Path, auth_permission):
    app.add_middleware(EnrollmentBodyLimitMiddleware)
    # Preserve the existing SMS/auth validation handler, while ensuring invalid
    # QR/admin payloads never echo their secret/image input in a 422 response.
    previous_validation = app.exception_handlers.get(RequestValidationError, request_validation_exception_handler)

    @app.exception_handler(RequestValidationError)
    async def safe_validation(request, exc):
        if request.url.path.startswith((QR_PREFIX, ADMIN_PREFIX, "/api/v1/enrollment/")):
            return JSONResponse({"detail": "Dữ liệu yêu cầu không hợp lệ.", "code": "INVALID_REQUEST"},
                                status_code=422, headers={"Cache-Control": "no-store"})
        return await previous_validation(request, exc)

    def admin(request):
        actor = auth_permission(request, "employee.enroll")
        if str(actor.get("role") or "").upper() not in {"SUPER_ADMIN", "ADMIN"}:
            raise HTTPException(403, {"code": "OWNER_ADMIN_REQUIRED", "message": "Chỉ Chủ sở hữu hoặc Quản trị viên được quản lý duyệt FaceID."})
        return actor

    @app.get("/enroll")
    def capture_page():
        if UI_PREVIEW:
            return HTMLResponse(preview_html(frontend / "enroll.html"),
                                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        return FileResponse(frontend / "enroll.html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @app.post(ADMIN_PREFIX + "/invitations")
    def invitation(payload: StartPayload, request: Request, response: Response):
        actor = admin(request)
        try:
            result = service.issue_invitation(actor, payload.student_id, payload.store_id,
                                              invitation_minutes=payload.invitation_minutes)
            return _safe_json(_invitation_result(result, request), response)
        except Exception as exc:
            _error(exc)

    @app.post(ADMIN_PREFIX + "/requests")
    def desktop_start(payload: StartPayload, request: Request, response: Response):
        actor = admin(request)
        try:
            return _safe_json(service.start_desktop_request(actor, payload.student_id, payload.store_id), response)
        except Exception as exc:
            _error(exc)

    @app.get(ADMIN_PREFIX + "/requests")
    def requests(request: Request, response: Response, store_id: int | None = None, student_id: int | None = None, status: str = "", limit: int = 100, offset: int = 0):
        actor = admin(request)
        try:
            return _safe_json(service.list_requests(actor, store_id=store_id, student_id=student_id, status=status, limit=limit, offset=offset), response)
        except Exception as exc:
            _error(exc)

    @app.get(ADMIN_PREFIX + "/requests/{request_id}")
    def detail(request_id: str, request: Request, response: Response):
        actor = admin(request)
        try:
            return _safe_json(service.get_request(actor, request_id), response)
        except Exception as exc:
            _error(exc)

    @app.get(ADMIN_PREFIX + "/requests/{request_id}/preview.jpg")
    def preview(request_id: str, request: Request):
        actor = admin(request)
        try:
            return Response(service.get_preview(actor, request_id), media_type="image/jpeg", headers={"Cache-Control": "no-store"})
        except Exception as exc:
            _error(exc)

    def decide(action, request_id, payload, request, response):
        actor = admin(request)
        try:
            common = {"expected_revision": payload.expected_revision, "reason": payload.reason}
            if action == "approve":
                result = service.approve_request(actor, request_id, duplicate_override=payload.duplicate_override, **common)
            else:
                if payload.duplicate_override:
                    raise service.EnrollmentError("Dữ liệu quyết định không hợp lệ.", code="INVALID_REQUEST", status=400)
                function = {"reject": service.reject_request, "cancel": service.cancel_request, "reenroll": service.request_reenrollment}[action]
                result = function(actor, request_id, **common)
                if action == "reenroll":
                    result = _invitation_result(result, request)
            return _safe_json(result, response)
        except Exception as exc:
            _error(exc)

    @app.post(ADMIN_PREFIX + "/requests/{request_id}/approve")
    def approve(request_id: str, payload: DecisionPayload, request: Request, response: Response):
        return decide("approve", request_id, payload, request, response)

    @app.post(ADMIN_PREFIX + "/requests/{request_id}/reject")
    def reject(request_id: str, payload: DecisionPayload, request: Request, response: Response):
        return decide("reject", request_id, payload, request, response)

    @app.post(ADMIN_PREFIX + "/requests/{request_id}/cancel")
    def cancel(request_id: str, payload: DecisionPayload, request: Request, response: Response):
        return decide("cancel", request_id, payload, request, response)

    @app.post(ADMIN_PREFIX + "/requests/{request_id}/reenroll")
    def reenroll(request_id: str, payload: DecisionPayload, request: Request, response: Response):
        return decide("reenroll", request_id, payload, request, response)

    @app.post(QR_PREFIX + "/redeem")
    def redeem(payload: RedeemPayload, request: Request):
        try:
            result = dict(service.redeem_invitation(payload.invite_secret))
            secret = result.pop("capture_secret")
            response = JSONResponse(result, headers={"Cache-Control": "no-store"})
            response.set_cookie(QR_COOKIE, secret, max_age=1800, httponly=True,
                                secure=True, samesite="strict", path=QR_PREFIX)
            return response
        except Exception as exc:
            _error(exc)

    @app.get(QR_PREFIX + "/status")
    def status(request: Request, response: Response):
        _rate(request, "status", maximum=120)
        try:
            return _safe_json(service.capture_status(_secret(request)), response)
        except Exception as exc:
            _error(exc)

    @app.post(QR_PREFIX + "/consent")
    def consent(payload: ConsentPayload, request: Request, response: Response):
        try:
            return _safe_json(service.accept_capture_consent(_secret(request), granted=payload.granted), response)
        except Exception as exc:
            _error(exc)

    @app.post(QR_PREFIX + "/frame")
    def frame(payload: UploadPayload, request: Request, response: Response):
        try:
            with service.capture_frame_lease(_secret(request)) as binding:
                return _safe_json(CAPTURE.frame_upload(binding["id"], binding["student_id"], payload.image), response)
        except Exception as exc:
            _error(exc)

    @app.post(QR_PREFIX + "/submit")
    def submit(payload: EmptyPayload, request: Request, response: Response):
        try:
            binding = service.capture_status(_secret(request))
            row = binding.get("request", binding)
            if row.get("status") in {"PENDING_REVIEW", "NEEDS_DUPLICATE_REVIEW"}:
                return _safe_json(binding, response)
            with service.capture_frame_lease(_secret(request)) as binding:
                draft = CAPTURE.prepare(binding["id"], binding["student_id"])
            return _safe_json(service.stage_prepared_request(binding["id"], draft, session_secret=_secret(request),
                                                           expected_revision=binding["revision"]), response)
        except Exception as exc:
            _error(exc)

    @app.post(QR_PREFIX + "/reset")
    def reset(payload: EmptyPayload, request: Request, response: Response):
        try:
            return _safe_json(service.reset_capture(_secret(request)), response)
        except Exception as exc:
            _error(exc)

from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import os
import re
import time
import zipfile
import socket
import secrets
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .camera_catalog_v543 import build_source_catalog
from .capture_session_v544 import display_source
from .camera_connection_v544 import connection_view, update_connection_source
from .camera_registry_v546 import persisted_connection_matches, startup_source_tracks_previous
from .camera_registry_v547 import legacy_hikvision_repair_plan
from .security_hardening_v54 import sanitize_payload
from pydantic import BaseModel, Field

from .camera import CAMERA
from .office_engine import OFFICE
from .media_webrtc import MEDIA
from .media_gateway_v5410 import MEDIA_GATEWAY, NativeGatewayError
from .mediamtx_runtime import require_mediamtx
from .gpu_manager import gpu_status
from .production_pilot import PILOT
from .performance_diagnostics_v550 import collect_performance_diagnostics, safe_camera_status
from .hr_reporting import build_hr_report, report_print_html, report_xlsx_bytes, save_shift_policy, shift_policy
from .config import APP_NAME, APP_VERSION, BASE_DIR, CAMERA_MODE, DATA_ROOT, PROFILE, PORT, UI_PREVIEW
from .ui_preview import LocalPreviewMiddleware, hardware_unavailable, preview_html, NOTICE
from . import config as runtime_config
from .db import (
    add_audit_event, audit_events, close_all_open_presence_sessions, db_status, execute, fetchall, fetchone, init_db, utc_now,
    hr_current_presence, hr_event_history, hr_presence_history,
)
from .face_core import CORE
from .registry import ENROLLMENT, INDEX
from .student_media import delete_student_media, photo_path, student_photos
from .walkby import WALKBY
from .passive_pad import PAD
from .production_ops import (
    ensure_production_schema, create_session, list_sessions, get_session, session_ledger,
    close_session, session_csv, camera_settings, save_camera_settings, create_backup,
    list_backups, backup_path, import_backup, restore_backup, storage_status,
    operations_rules, save_operations_rules, list_camera_devices, save_camera_device, delete_camera_device,
    exception_queue, review_exception, operations_summary, adjust_attendance_record, recognition_evidence_path,
    hr_event_evidence_path,
)
from .camera_profiles import normalize_camera_source, redact_camera_source
from .auth import (
    user_count, bootstrap_admin, create_user, register_public_user, approve_user, change_password_by_verified_phone,
    list_users, update_user, reset_user_password, role_catalog, login as auth_login, logout as auth_logout,
    complete_mfa_challenge, reset_user_mfa,
    user_for_token, token_from_authorization, require_role,
    require_permission, has_permission, login_lock_status, enforce_admin_only, mobile_viewer_status, configure_mobile_viewer,
    mobile_login, mobile_logout, mobile_user_for_token, mobile_login_lock_status,
    provision_release_owner_account, privileged_security_status, verify_privileged_security_contact,
    privileged_login_otp_destination, complete_privileged_login_challenge,
)
from .visitor import (
    ensure_visitor_schema, list_sessions as visitor_sessions, get_session as visitor_session,
    review_session as review_visitor_session, shot_path as visitor_shot_path,
)
from .recording import ensure_recording_schema, archive_status as recording_archive_status, list_segments as recording_segments, resolve_event_video
from .camera_fleet_v4 import FLEET_V4, FleetUnavailable
from .ai_camera_runtime import CameraAIRuntime
from .recording_runtime_v4 import RECORDER_V4
from .otp_service import (
    ensure_otp_schema, request_otp as otp_request, request_otp_delivery as otp_request_delivery,
    verify_otp as otp_verify, delivery_status as otp_delivery_status,
    delivery_config_public as otp_delivery_config_public, save_delivery_config as otp_save_delivery_config,
)
from .platform_v5 import (
    ensure_platform_v5_schema, list_stores, create_store, list_shifts, save_shift as save_shift_v5,
    assign_employee_shift, employee_shift, create_attendance_correction, list_attendance_corrections,
    create_incident, list_incidents, get_incident, add_incident_evidence, lock_incident_evidence,
    create_video_clip, list_video_clips, set_face_enrollment_validation_pending,
    mark_face_enrollment_validated, face_enrollment_validation,
)
from .demo_context import (
    ensure_demo_schema, camera_context, source_context, list_camera_contexts,
    save_camera_configuration, scoped_store_ids, enforce_store_scope, _safe_name,
)
from .shift_attendance import ensure_shift_attendance_schema, build_shift_attendance_report
from .camera_appearances import ensure_appearance_schema
from .entrance_visits import ENTRY_VISITS, ensure_entrance_visits_schema
from .recognition_history import query_recognition_history, recognition_filter_options
from .account_service import AccountError, get_self_profile, update_self_profile, change_self_password, provision_account
from .visit_reports import query_visits_report, query_management_summary
from .qr_enrollment_routes import (
    capability_http_guard, enrollment_enabled, install_qr_routes,
    desktop_frame, desktop_finalize, desktop_reset,
)
from . import qr_enrollment
from .sync_v5 import (
    EdgeAuthError, EDGE_SYNC_WORKER, authenticate_edge_request, ensure_sync_v5_schema,
    list_edge_nodes, register_edge_node, revoke_edge_node, pending_sync_batch, mark_sync_result,
    receive_sync_batch, sync_status, update_edge_heartbeat,
)

AI_RUNTIME = CameraAIRuntime(CAMERA, retire_reader=lambda camera_id: FLEET_V4.stop(camera_id),
                            reader_reservation=FLEET_V4.reserve, retire_business=ENTRY_VISITS.reset_camera)

_OTP_LOCK = threading.RLock()
_OTP_CHALLENGES: dict[str, dict] = {}

def _otp_cleanup():
    now = time.time()
    with _OTP_LOCK:
        for key in [k for k,v in _OTP_CHALLENGES.items() if float(v.get("expires_at") or 0) <= now]:
            item = _OTP_CHALLENGES.pop(key, None)
            if item and item.get("token"):
                auth_logout(str(item.get("token")))

app = FastAPI(title=APP_NAME, version=APP_VERSION,
              docs_url=None if UI_PREVIEW else "/docs", redoc_url=None,
              openapi_url=None if UI_PREVIEW else "/openapi.json")
FRONTEND = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


from . import sms_auth_v542 as sms_security
from .sms_routes_v542 import (
    browser_guard, sensitive_action_guard, secure_transport, set_pending,
    set_auth_result, install_sms_routes,
)

AUTH_COOKIE = "campusface_session"
MOBILE_COOKIE = "campusface_mobile_viewer"
PUBLIC_API_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/bootstrap",
    "/api/v1/auth/bootstrap-local",
    "/api/v1/auth/login",
    "/api/v1/auth/sms/send",
    "/api/v1/auth/sms/verify",
    "/api/v1/auth/sms/cancel",
    "/api/v1/auth/mfa/verify",
    "/api/v1/auth/2fa/request-otp",
    "/api/v1/auth/2fa/verify",
    "/api/v1/auth/register",
    "/api/v1/auth/bootstrap/request-otp",
    "/api/v1/auth/bootstrap/verify-otp",
    "/api/v1/auth/register/request-otp",
    "/api/v1/auth/register/verify-otp",
    "/api/v1/auth/forgot/request-otp",
    "/api/v1/auth/forgot/verify-otp",
    # Device-authenticated Edge transport bypasses browser session auth, then
    # verifies its Ed25519 signature + timestamp + nonce inside the route.
    "/api/v1/sync/receive",
    "/api/v1/sync/heartbeat",
}
MOBILE_PUBLIC_API_PATHS = {
    "/api/v1/mobile/auth/status",
    "/api/v1/mobile/auth/login",
}

LEGACY_OTP_API_PATHS = {
    "/api/v1/auth/bootstrap/request-otp",
    "/api/v1/auth/bootstrap/verify-otp",
    "/api/v1/auth/register/request-otp",
    "/api/v1/auth/register/verify-otp",
    "/api/v1/auth/forgot/request-otp",
    "/api/v1/auth/forgot/verify-otp",
    "/api/v1/auth/2fa/request-otp",
    "/api/v1/auth/2fa/verify",
    "/api/v1/auth/admin-security/otp-provider",
    "/api/v1/auth/admin-security/otp-provider/test",
    "/api/v1/auth/admin-security/request-otp",
    "/api/v1/auth/admin-security/verify-otp",
}

_AUTHENTICATED_ONLY = "__authenticated__"


def _api_permission_for(path: str, method: str) -> str | None:
    """Return the permission required by an authenticated browser API request.

    Public authentication/bootstrap and signed Edge routes are skipped before this
    function is called. Returning ``None`` is fail-closed in the middleware so a
    newly added API must declare its permission before it becomes reachable.
    """
    p = str(path or "").split("?", 1)[0]
    m = str(method or "GET").upper()

    if p.startswith("/api/v1/auth/sms/"):
        return _AUTHENTICATED_ONLY
    if p in {"/api/v1/auth/logout", "/api/v1/auth/profile", "/api/v1/auth/password"}:
        return _AUTHENTICATED_ONLY
    if p.startswith("/api/v1/auth/admin-security"):
        return "system.manage"
    if p.startswith("/api/v1/admin/mobile-access"):
        return "system.manage"
    if p.startswith("/api/v1/admin/face-enrollment/"):
        return "employee.enroll"
    if p.startswith("/api/v1/admin/"):
        return "account.approve"

    if p.startswith("/api/v1/employees/") and p.endswith("/shift"):
        return "attendance.view" if m in {"GET", "HEAD"} else "attendance.manage"
    if p.startswith("/api/v1/employees/") and "/face-validation" in p:
        return "employee.view" if m in {"GET", "HEAD"} else "employee.enroll"
    if p.startswith("/api/v1/students") or p.startswith("/api/v1/employees"):
        if "/consent" in p:
            return "employee.enroll"
        return "employee.view" if m in {"GET", "HEAD"} else "employee.manage"
    if p.startswith("/api/v1/enrollment/"):
        return "employee.enroll"

    if p.startswith("/api/v1/events/") and p.endswith("/evidence.jpg"):
        return "evidence.view"
    if p.startswith("/api/v1/history/") and p.endswith("/evidence.jpg"):
        return "evidence.view"
    if p.startswith("/api/v1/events/") and p.endswith("/video"):
        return "camera.playback"
    if p == "/api/v1/events" or p.startswith("/api/v1/history/"):
        return "history.view"

    if p.startswith("/api/v1/recognition/"):
        return "camera.live"
    if p in {"/api/v1/camera/select", "/api/v1/camera/control", "/api/v1/camera/test-source"}:
        return "camera.switch"
    if p in {"/api/v1/camera/reconnect"}:
        return "camera.configure"
    if p.startswith("/api/v1/settings/camera"):
        return "camera.live" if m in {"GET", "HEAD"} else "camera.configure"
    if p.startswith("/api/v1/cameras/devices/") and p.endswith("/connection"):
        return "camera.configure"
    if p.startswith("/api/v1/cameras/devices"):
        return "camera.live" if m in {"GET", "HEAD"} else "camera.configure"
    if p.startswith("/api/v1/camera/") or p.startswith("/api/v1/cameras/"):
        return "camera.live"
    if p == "/api/v1/media/gateway/restart":
        return "camera.configure"
    if p.startswith("/api/v1/media/"):
        return "camera.live"
    if p.startswith("/api/v1/office/gate/"):
        return "camera.configure"
    if p.startswith("/api/v1/office/config"):
        return "camera.live" if m in {"GET", "HEAD"} else "camera.configure"
    if p.startswith("/api/v1/office/start") or p.startswith("/api/v1/office/stop"):
        return "camera.switch"
    if p.startswith("/api/v1/office/"):
        return "camera.live"

    if p.startswith("/api/v1/visitors/"):
        return "visitor.review" if m not in {"GET", "HEAD"} else "visitor.view"
    if p == "/api/v1/visitors":
        return "visitor.view"
    if p.startswith("/api/v1/exceptions"):
        return "visitor.review" if m not in {"GET", "HEAD"} else "visitor.view"

    if p.startswith("/api/v1/recordings"):
        return "camera.playback"
    if p.startswith("/api/v1/video/clips"):
        return "camera.playback" if m in {"GET", "HEAD"} else "video.clip"

    if p.startswith("/api/v1/hr-report"):
        return "hr.report"
    if p.startswith("/api/v1/operations"):
        return "operations.view" if m in {"GET", "HEAD"} else "attendance.manage"
    if p.startswith("/api/v1/presence/"):
        return "attendance.view"
    if p.startswith("/api/v1/attendance/corrections"):
        return "attendance.view" if m in {"GET", "HEAD"} else "attendance.adjust"
    if p.startswith("/api/v1/attendance/"):
        if m in {"GET", "HEAD"}:
            return "attendance.view"
        return "attendance.manage"
    if p.startswith("/api/v1/work-shifts"):
        return "attendance.view" if m in {"GET", "HEAD"} else "attendance.manage"

    if p.startswith("/api/v1/incidents"):
        return "incident.view" if m in {"GET", "HEAD"} else "incident.manage"
    if p.startswith("/api/v1/dashboard/"):
        return "dashboard.view"
    if p == "/api/v1/stores":
        return "dashboard.view" if m in {"GET", "HEAD"} else "system.manage"
    if p.startswith("/api/v1/exports/student-template"):
        return "employee.manage"
    if p.startswith("/api/v1/exports/"):
        return "employee.view"

    if p == "/api/v1/system/audit":
        return "audit.view"
    if p.startswith("/api/v1/system/diagnostics") or p.startswith("/api/v1/system/self-test"):
        return "system.diagnostics"
    if p.startswith("/api/v1/performance/"):
        return "system.health"
    if p.startswith("/api/v1/production/") or p.startswith("/api/v1/backups"):
        return "system.manage"
    if p.startswith("/api/v1/sync/"):
        return "system.manage"
    if p == "/api/v1/module/contract":
        return "system.health"

    return None


def _request_token(request: Request) -> str:
    token = token_from_authorization(request.headers.get("Authorization", ""))
    if token:
        return token
    return str(request.cookies.get(AUTH_COOKIE) or "").strip()


def _request_user(request: Request) -> dict | None:
    return user_for_token(_request_token(request))


def _request_mobile_token(request: Request) -> str:
    return str(request.cookies.get(MOBILE_COOKIE) or "").strip()


def _request_mobile_user(request: Request) -> dict | None:
    return mobile_user_for_token(_request_mobile_token(request))


def _websocket_user(websocket: WebSocket) -> dict | None:
    token = str(websocket.cookies.get(AUTH_COOKIE) or "").strip()
    if not token:
        raw = str(websocket.query_params.get("access_token") or "").strip()
        token = raw
    user = user_for_token(token)
    permission = _api_permission_for(websocket.url.path, "GET")
    return user if user and permission and has_permission(user, permission) else None


def _camera_scope_context(user: dict, camera_id: int | None = None) -> dict:
    context = camera_context(camera_id) if camera_id is not None else source_context(CAMERA.current_source_identity())
    if not context:
        if camera_id is None and scoped_store_ids(user) is None:
            return {}
        raise HTTPException(404, "Không tìm thấy camera")
    try:
        enforce_store_scope(user, context.get("store_id"))
    except PermissionError:
        raise HTTPException(403, "Camera không thuộc cửa hàng được cấp quyền") from None
    return context


def _require_store_scope(user: dict, store_id: int | None) -> None:
    try:
        enforce_store_scope(user, store_id)
    except PermissionError:
        raise HTTPException(403, "Cửa hàng không thuộc phạm vi được cấp quyền") from None


def _require_employee_scope(user: dict, student_id: int) -> None:
    allowed = scoped_store_ids(user)
    if allowed is None:
        return
    stores = fetchall("SELECT store_id FROM employee_store_assignments WHERE student_id=?", (student_id,))
    if not any(int(row["store_id"]) in allowed for row in stores):
        raise HTTPException(403, "Nhân viên không thuộc cửa hàng được cấp quyền")


def _enforce_camera_request_scope(request: Request, user: dict) -> None:
    """Apply store scope to existing camera transports as well as new views."""
    path = request.url.path
    match = re.match(r"^/api/v1/cameras/(?:devices/)?(\d+)(?:/|$)", path)
    raw_id = request.query_params.get("camera_id")
    if match:
        _camera_scope_context(user, int(match.group(1)))
    elif path.startswith("/api/v1/media/") or path.startswith("/api/v1/camera/"):
        try:
            camera_id = int(raw_id) if raw_id is not None else None
        except ValueError:
            raise HTTPException(400, "Camera không hợp lệ") from None
        # Global gateway controls retain their existing permission and primary scope.
        _camera_scope_context(user, camera_id)


@app.middleware("http")
async def _campusface_security_headers(request: Request, call_next):
    blocked = browser_guard(request)
    if blocked is not None:
        return blocked
    path = request.url.path
    blocked = capability_http_guard(request)
    if blocked is not None:
        return blocked
    if path in LEGACY_OTP_API_PATHS and str(os.getenv("BTMH_LEGACY_OTP_ENABLED", "0")).strip() != "1":
        return JSONResponse(
            {"detail": "Kênh OTP SMS/Email không được kích hoạt trên hệ thống này"},
            status_code=404,
            headers={"Cache-Control": "no-store"},
        )
    if path.startswith("/api/v1/qr-enrollment/"):
        # Dedicated enrollment capability; no portal/Viewer permission granted.
        # Each route validates its own expiring employee-bound capability.
        pass
    elif path.startswith("/api/v1/mobile/"):
        if path not in MOBILE_PUBLIC_API_PATHS:
            if await run_in_threadpool(_request_mobile_user, request) is None:
                return JSONResponse({"detail": "Cần đăng nhập Mobile Viewer"}, status_code=401, headers={"Cache-Control": "no-store"})
            # Mobile Viewer is server-enforced read-only. Logout is the only POST.
            if request.method.upper() not in {"GET", "HEAD"} and path != "/api/v1/mobile/auth/logout":
                return JSONResponse({"detail": "Mobile Viewer chỉ có quyền xem"}, status_code=405, headers={"Cache-Control": "no-store"})
    elif path.startswith("/api/v1/") and path not in PUBLIC_API_PATHS:
        if await run_in_threadpool(user_count) == 0:
            return JSONResponse(
                {"detail": "Hệ thống chưa được thiết lập Chủ sở hữu"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        user = await run_in_threadpool(_request_user, request)
        if user is None:
            return JSONResponse(
                {"detail": "Cần đăng nhập để truy cập hệ thống"},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )
        required_permission = _api_permission_for(path, request.method)
        if required_permission is None:
            return JSONResponse(
                {"detail": "API chưa được khai báo quyền truy cập"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        if required_permission != _AUTHENTICATED_ONLY and not has_permission(user, required_permission):
            return JSONResponse(
                {"detail": "Tài khoản không có quyền thực hiện thao tác này"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        try:
            await run_in_threadpool(_enforce_camera_request_scope, request, user)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers={"Cache-Control": "no-store"})
        blocked = await run_in_threadpool(sensitive_action_guard, request, user, _request_token(request))
        if blocked is not None:
            return blocked
    if UI_PREVIEW and hardware_unavailable(path, request.method):
        return JSONResponse(
            {"detail": "Chức năng phần cứng hoặc kết nối ngoài không khả dụng trong UI Preview.",
             "code": "UI_PREVIEW_UNAVAILABLE"},
            status_code=503, headers={"Cache-Control": "no-store"},
        )
    response = await call_next(request)
    if path.startswith(("/api/v1/auth/", "/api/v1/qr-enrollment/", "/api/v1/admin/face-enrollment/", "/api/v1/enrollment/")):
        response.headers["Cache-Control"] = "no-store"
    # Professional pilot: browser hardening without external dependencies.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer" if path == "/enroll" else "same-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if request.url.path in {"/", "/mobile", "/enroll"} or request.url.path.startswith("/static/") or request.url.path.startswith("/mobile/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-BTMH-UI"] = "v5-production"
    return response


class StudentCreate(BaseModel):
    student_code: str
    full_name: str
    class_name: str = ""
    faculty: str = ""
    email: str = ""
    phone: str = ""
    consent: bool = False


class StudentUpdate(BaseModel):
    full_name: str | None = None
    class_name: str | None = None
    faculty: str | None = None
    email: str | None = None
    phone: str | None = None


class ConsentPayload(BaseModel):
    granted: bool = True


class FramePayload(BaseModel):
    image: str = Field(default="", max_length=2796247)
    session_id: str = "browser-recognition"
    student_id: int | None = None
    confirm_duplicate: bool = False
    request_id: str | None = Field(default=None, min_length=1, max_length=128)


class AttendanceSessionCreate(BaseModel):
    name: str = "Hiện diện"
    class_name: str = ""
    room_name: str = ""
    start_at: str
    end_at: str
    grace_minutes: int = 5


class EdgeNodeRegisterPayload(BaseModel):
    node_id: str
    node_name: str
    store_id: int | None = None
    public_key_b64: str = ""


class SyncAckPayload(BaseModel):
    event_ids: list[str]
    success: bool = True
    error: str = ""


class SyncReceivePayload(BaseModel):
    source_node_id: str
    events: list[dict] = []


class EdgeHeartbeatPayload(BaseModel):
    source_node_id: str
    store_id: int | None = None
    app_version: str = ""
    pending_count: int = 0
    retry_count: int = 0
    conflict_count: int = 0
    worker_running: bool = False
    worker_last_success_at: str = ""
    worker_last_error: str = ""
    last_sync_at: str = ""


class CameraSettingsPayload(BaseModel):
    source: str = "0"
    backend: str = "auto"
    width: int = 1920
    height: int = 1080
    fps: int = 30
    fourcc: str = "auto"
    preview_fps: int = 25
    observation_preview_fps: int = 25
    observation_preview_width: int = 1920
    observation_jpeg_quality: int = 92
    # Read-only migration aliases for older V4/V5.0 clients.
    classroom_preview_fps: int | None = None
    classroom_preview_width: int | None = None
    classroom_jpeg_quality: int | None = None


class CameraControlPayload(BaseModel):
    action: str
    speed: float = 0.5


class CameraSelectPayload(BaseModel):
    source: str = "0"


class CameraDevicePayload(BaseModel):
    name: str = "Camera"
    source: str = "0"
    camera_type: str = "USB"
    zone_name: str = ""
    resolution: str = "1920x1080"
    target_fps: int = 30
    ptz_enabled: bool = False
    enabled: bool = True
    notes: str = ""


class CameraConfigurationPayload(BaseModel):
    camera_name: str | None = None
    store_id: int | None = None
    zone_name: str = ""
    ai_enabled: bool = False
    attendance_enabled: bool = True
    visitor_counting_enabled: bool = False
    entrance_config: dict = {}


class OperationsRulesPayload(BaseModel):
    duplicate_window_seconds: int = 45
    reentry_gap_minutes: int = 10
    exception_low_confidence: float = 0.72
    evidence_retention_days: int = 30



class HrShiftPolicyPayload(BaseModel):
    enabled: bool = False
    name: str = "Ca hành chính"
    start_time: str = "08:00"
    end_time: str = "17:30"
    break_start: str = "12:00"
    break_end: str = "13:30"
    late_grace_minutes: int = 10
    early_leave_grace_minutes: int = 10
    workdays: list[int] = [0, 1, 2, 3, 4]

class ExceptionReviewPayload(BaseModel):
    decision: str
    resolved_student_id: int | None = None
    note: str = ""


class AttendanceAdjustmentPayload(BaseModel):
    status: str
    reason: str


class AuthBootstrapPayload(BaseModel):
    username: str
    display_name: str = "Quản trị viên"
    phone: str = ""
    password: str


class AuthLoginPayload(BaseModel):
    username: str
    password: str


class AuthMfaVerifyPayload(BaseModel):
    trust_browser: bool = False
    challenge_id: str
    code: str


class AuthSecondFactorRequestPayload(BaseModel):
    login_challenge_id: str
    method: str


class AuthSecondFactorVerifyPayload(BaseModel):
    login_challenge_id: str
    otp_challenge_id: str
    otp: str


class AdminSecurityOtpRequestPayload(BaseModel):
    method: str
    destination: str
    display_name: str = ""


class AdminSecurityOtpVerifyPayload(BaseModel):
    challenge_id: str
    otp: str


class OtpDeliveryConfigPayload(BaseModel):
    sms: dict
    email: dict


class OtpDeliveryTestPayload(BaseModel):
    method: str
    destination: str


class AuthRegisterPayload(BaseModel):
    username: str
    display_name: str = ""
    phone: str
    password: str

class AuthOtpRequestPayload(BaseModel):
    username: str
    password: str
    destination: str

class AuthOtpVerifyPayload(BaseModel):
    challenge_id: str
    otp: str


class AuthBootstrapOtpRequestPayload(BaseModel):
    username: str
    display_name: str = "Quản trị viên"
    phone: str
    email: str


class AuthRegisterOtpRequestPayload(BaseModel):
    username: str
    display_name: str
    phone: str
    email: str


class AuthOtpPasswordVerifyPayload(BaseModel):
    challenge_id: str
    otp: str
    password: str


class AuthForgotRequestPayload(BaseModel):
    identifier: str


class AuthForgotVerifyPayload(BaseModel):
    challenge_id: str
    otp: str
    password: str


class AccountApprovalPayload(BaseModel):
    role: str = "EMPLOYEE"
    store_id: int | None = None


class StoreCreatePayload(BaseModel):
    store_code: str
    store_name: str
    timezone_name: str = "Asia/Ho_Chi_Minh"


class ShiftV5Payload(BaseModel):
    id: int | None = None
    store_id: int | None = None
    shift_code: str
    shift_name: str
    start_time: str = "08:00"
    end_time: str = "17:30"
    late_grace_minutes: int = 5
    early_leave_grace_minutes: int = 5
    workdays: list[int] = [0,1,2,3,4,5]
    active: bool = True


class ShiftAssignPayload(BaseModel):
    shift_id: int
    effective_from: str = ""


class AttendanceCorrectionV5Payload(BaseModel):
    student_id: int
    work_date: str
    original_checkin_at: str | None = None
    original_checkout_at: str | None = None
    effective_checkin_at: str | None = None
    effective_checkout_at: str | None = None
    correction_type: str = "MANUAL_ADJUSTMENT"
    reason: str


class IncidentCreatePayload(BaseModel):
    store_id: int | None = None
    title: str
    severity: str = "NORMAL"
    visitor_session_code: str = ""
    employee_id: int | None = None
    occurred_at: str = ""
    note: str = ""


class IncidentEvidencePayload(BaseModel):
    evidence_type: str
    evidence_ref: str
    camera_source: str = ""
    captured_at: str = ""
    note: str = ""


class VideoClipCreatePayload(BaseModel):
    segment_id: str
    start_at: str
    end_at: str


class MobileViewerLoginPayload(BaseModel):
    password: str


class MobileViewerConfigPayload(BaseModel):
    enabled: bool = False
    password: str = ""


class UserCreatePayload(BaseModel):
    username: str
    display_name: str = ""
    role: str = "VIEWER"
    password: str
    confirm_password: str | None = None
    phone: str = ""
    email: str = ""
    store_id: int | None = None


class SelfProfilePayload(BaseModel):
    model_config = {"extra": "forbid"}
    display_name: str


class SelfPasswordPayload(BaseModel):
    model_config = {"extra": "forbid"}
    current_password: str
    new_password: str
    confirm_password: str


class UserUpdatePayload(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None


class UserPasswordPayload(BaseModel):
    password: str


class VisitorReviewPayload(BaseModel):
    visitor_type: str = "UNKNOWN"
    label: str = ""
    note: str = ""


class OfficeLinePayload(BaseModel):
    configured: bool = False
    enabled: bool = False
    name: str = "Cửa văn phòng"
    x1: float = 0.15
    y1: float = 0.55
    x2: float = 0.85
    y2: float = 0.55
    inside_side: str = "positive"
    deadband: float = 0.025
    cooldown_sec: float = 2.5
    anchor: str = "person_center"
    camera_id: int | None = None
    camera_name: str = ""
    zone_name: str = ""
    camera_source_fingerprint: str = ""


class OfficeConfigPayload(BaseModel):
    monitoring_enabled: bool = True
    line: OfficeLinePayload


class WebRTCOfferPayload(BaseModel):
    sdp: str
    type: str = "offer"


class WebRTCClosePayload(BaseModel):
    session_id: str

class ProductionPilotConfigPayload(BaseModel):
    watchdog_enabled: bool = True
    camera_auto_recovery: bool = True
    camera_stale_sec: float = 8.0
    camera_bad_confirm_sec: float = 4.0
    recovery_cooldown_sec: float = 45.0
    auto_backup_enabled: bool = True
    auto_backup_interval_hours: float = 24.0
    auto_backup_retention: int = 14
    health_interval_sec: float = 2.0
    disk_warn_free_gb: float = 8.0
    ram_warn_percent: float = 88.0
    cpu_warn_percent: float = 92.0
    gpu_warn_percent: float = 94.0



def _camera_label_for_source(source: str) -> str:
    value = normalize_camera_source(str(source or "0").strip() or "0")
    try:
        for item in list_camera_devices():
            if normalize_camera_source(str(item.get("source") or "")) == value:
                return str(item.get("name") or value)
    except Exception:
        pass
    if value == "0":
        return "Camera laptop"
    if value == "1":
        return "Camera USB/PTZ #1"
    if value.lower().startswith("rtsp://"):
        return "Hikvision Camera"
    return value


def _hikvision_device() -> dict | None:
    try:
        items = [x for x in list_camera_devices() if bool(x.get("enabled", True))]
    except Exception:
        return None
    network = [x for x in items if str(x.get("source") or "").lower().startswith("rtsp://")]
    if not network:
        return None
    return next((x for x in network if "hikvision" in str(x.get("name") or "").lower()), network[0])


def _configure_ai_registry_source() -> None:
    """Enable a derived AI stream only for the active enabled DB record."""
    current = normalize_camera_source(CAMERA.current_source_identity())
    registered = None
    try:
        registered = next((str(row.get("source") or "") for row in list_camera_devices()
                           if bool(row.get("enabled", True))
                           and normalize_camera_source(str(row.get("source") or "")) == current), None)
    except Exception:
        pass  # Registry lookup failure leaves the private lane on main fallback.
    CAMERA.configure_ai_source(registered)
    if registered is None:
        MEDIA_GATEWAY.sync_small_source("", fallback_reason="SMALL_NOT_VALIDATED")


def _resolve_camera_selection(requested: str) -> tuple[str, str]:
    """Resolve UI aliases without exposing RTSP credentials to the browser.

    V5.3.3 exposed safe aliases such as CAM02 in the browser but the backend only
    accepted a raw RTSP URL or USB index. Resolve CAMxx server-side so switching
    recognition cameras works without ever sending camera credentials to JS.
    """
    raw = str(requested or "0").strip() or "0"
    key = raw.lower()
    if key.startswith("cam") and key[3:].isdigit():
        cid = int(key[3:])
        device = fetchone("SELECT * FROM camera_devices WHERE id=?", (cid,))
        if not device or not bool(device.get("enabled", 1)):
            raise ValueError("Camera không tồn tại hoặc đã bị tắt")
        source = normalize_camera_source(str(device.get("source") or ""))
        if not source:
            raise ValueError("Camera chưa có nguồn video")
        return source, str(device.get("name") or f"CAM{cid:02d}")
    if key in {"laptop", "camera-laptop"}:
        raw = "0"
    elif key in {"hikvision", "ptz", "camera-ptz", "network"}:
        device = _hikvision_device()
        if device is not None:
            source = normalize_camera_source(str(device.get("source") or ""))
            return source, str(device.get("name") or "Hikvision Camera")
        if key != "1" and raw != "1":
            raise ValueError("Chưa có cấu hình Hikvision RTSP")
    source = normalize_camera_source(raw)
    valid = source.isdigit() or source.lower().startswith(("rtsp://", "http://", "https://"))
    if not valid:
        raise ValueError("Nguồn camera không hợp lệ")
    return source, _camera_label_for_source(source)


def _camera_id_for_source(source: str) -> int | None:
    canonical = normalize_camera_source(str(source or ""))
    try:
        for item in list_camera_devices():
            if normalize_camera_source(str(item.get("source") or "")) == canonical:
                return int(item.get("id") or 0) or None
    except Exception:
        pass
    return None


@app.on_event("startup")
def startup() -> None:
    if UI_PREVIEW:
        # Existing schemas only, in the validated private SQLite profile. No
        # camera seeding, model load, LAN repair, gateway or background workers.
        init_db()
        ensure_production_schema(seed_cameras=False)
        enforce_admin_only()
        ensure_otp_schema()
        ensure_platform_v5_schema()
        ensure_demo_schema()
        ensure_shift_attendance_schema()
        ensure_appearance_schema()
        ensure_entrance_visits_schema()
        if enrollment_enabled():
            qr_enrollment.ensure_qr_enrollment_schema()
            qr_enrollment.recover_incomplete_captures()
        ensure_sync_v5_schema()
        ensure_visitor_schema()
        ensure_recording_schema()
        return
    # Enforce the same policy for direct uvicorn/VS Code launches as the batch
    # launcher, before database/camera workers start. Only explicit development
    # permits an unavailable native gateway.
    require_mediamtx(DATA_ROOT)
    init_db()
    # A previous process may have been terminated while people were present. Close
    # stale sessions before camera tracking starts so "currently present" is rebuilt
    # from fresh observations instead of inherited database state.
    close_all_open_presence_sessions(end_reason="SYSTEM_RESTART")
    ensure_production_schema()
    # 5.4.7: conservatively repair the exact legacy Hikvision sample endpoint
    # when the PC has moved to a different private /24 and exactly one matching
    # host answers on the saved RTSP port. Credentials/path are preserved and
    # the active FaceID reader is not switched here.
    try:
        for _camera_row in list_camera_devices():
            _plan = legacy_hikvision_repair_plan(_camera_row)
            if not _plan:
                continue
            _values = dict(_camera_row)
            _values["source"] = _plan["new_source"]
            _updated = save_camera_device(_values, device_id=int(_plan["device_id"]))
            if persisted_connection_matches(_plan["new_source"], _updated):
                _settings = camera_settings()
                if startup_source_tracks_previous(_settings.get("source"), _plan["previous_source"]):
                    _settings["source"] = _plan["new_source"]
                    save_camera_settings(_settings)
                try:
                    FLEET_V4.stop(int(_plan["device_id"]), wait=False)
                except Exception:
                    pass
                try:
                    RECORDER_V4.invalidate_camera(int(_plan["device_id"]))
                except Exception:
                    pass
                try:
                    add_audit_event(
                        "SYSTEM", "CAMERA_LEGACY_ENDPOINT_REPAIRED", "SUCCESS",
                        camera_source=str(_camera_row.get("name") or "Camera"),
                        detail={
                            "device_id": int(_plan["device_id"]),
                            "previous_host": _plan["previous_host"],
                            "new_host": _plan["new_host"],
                            "reason": _plan["reason"],
                        },
                    )
                except Exception:
                    pass
    except Exception:
        # Repair is opportunistic and must never prevent application startup.
        pass
    enforce_admin_only()
    provision_release_owner_account()
    ensure_otp_schema()
    ensure_platform_v5_schema()
    ensure_demo_schema()
    ensure_shift_attendance_schema()
    ensure_appearance_schema()
    ensure_entrance_visits_schema()
    if enrollment_enabled():
        qr_enrollment.ensure_qr_enrollment_schema()
        qr_enrollment.recover_incomplete_captures()
    ensure_sync_v5_schema()
    EDGE_SYNC_WORKER.start()
    ensure_visitor_schema()
    ensure_recording_schema()
    try:
        INDEX.load(force=True)
    except Exception:
        # The module still starts so the UI can explain whether a model/key/template
        # is missing. Registration can then create the first template.
        pass
    try:
        settings = camera_settings()
        configured_source = str(settings.get("source") or "0")
        resolved_source, resolved_label = _resolve_camera_selection(configured_source)
        # Migrate legacy PTZ index 1 / raw unescaped RTSP to the canonical source.
        if normalize_camera_source(configured_source) != resolved_source:
            settings["source"] = resolved_source
            save_camera_settings(settings)
        CAMERA.configure_source(resolved_source, resolved_label)
    except Exception:
        configured_source = "0"
        resolved_source = "0"
        resolved_label = "Camera laptop"
        CAMERA.configure_source(resolved_source, resolved_label)
    _configure_ai_registry_source()
    # The legacy primary service captures video immediately, but AI starts only
    # after the supervisor admits a configured registry camera into capacity.
    CAMERA.configure_ai_pipeline({}, enabled=False)
    CAMERA.start()
    AI_RUNTIME.start()
    # V5.4.10 native browser video is isolated from Python FaceID/PAD.
    # MediaMTX receives the current RTSP source through process environment only;
    # credentials are never returned to the browser or written into gateway YAML.
    try:
        MEDIA_GATEWAY.start(resolved_source, resolved_label)
    except Exception:
        pass
    # Start the recorder after the gateway so the active camera can share its
    # compressed upstream instead of opening a redundant camera connection.
    RECORDER_V4.start()
    # V5.2 production workload: identity, entry/exit, attendance, recording and evidence.
    # No pose or behaviour/action analysis worker exists in the runtime package.
    OFFICE.start()
    PILOT.start()
    # OFFICE consumes the shared FaceID result for presence/Virtual Gate only.
    try:
        add_audit_event("SYSTEM", "SYSTEM_START", "SUCCESS", camera_source=CAMERA.event_camera_source(), detail={"version": APP_VERSION, "profile": PROFILE, "identity_monitoring": True, "action_ai": False})
    except Exception:
        pass


@app.on_event("shutdown")
async def shutdown() -> None:
    if UI_PREVIEW:
        return
    AI_RUNTIME.stop()
    try:
        RECORDER_V4.stop()
        FLEET_V4.shutdown()
        add_audit_event("SYSTEM", "SYSTEM_STOP", "SUCCESS", camera_source=CAMERA.event_camera_source(), detail={"version": APP_VERSION})
    except Exception:
        pass
    try:
        close_all_open_presence_sessions(end_reason="SYSTEM_STOP")
    except Exception:
        pass
    try:
        await MEDIA.close_all()
    except Exception:
        pass
    try:
        MEDIA_GATEWAY.shutdown()
    except Exception:
        pass
    EDGE_SYNC_WORKER.stop()
    PILOT.stop()
    OFFICE.stop()
    CAMERA.stop()


@app.get("/")
def root():
    if UI_PREVIEW:
        return HTMLResponse(preview_html(FRONTEND / "index.html"), headers={"Cache-Control": "no-store"})
    return FileResponse(FRONTEND / "index.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "X-CampusFace-UI": "professional-v2.4-admin"})


@app.get("/mobile")
def mobile_root():
    if UI_PREVIEW:
        return HTMLResponse(preview_html(FRONTEND / "mobile" / "index.html"), headers={"Cache-Control": "no-store"})
    return FileResponse(FRONTEND / "mobile" / "index.html", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0", "X-CampusFace-UI": "mobile-viewer-v2.4"})


@app.get("/mobile/manifest.webmanifest")
def mobile_manifest():
    return FileResponse(FRONTEND / "mobile" / "manifest.webmanifest", media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@app.get("/mobile/sw.js")
def mobile_service_worker():
    return FileResponse(FRONTEND / "mobile" / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/mobile"})


@app.get("/api/v1/health")
def health():
    if UI_PREVIEW:
        return {
            "ok": True, "name": APP_NAME, "version": APP_VERSION,
            "mode": "UI_PREVIEW", "ui_preview": True, "notice": NOTICE,
            "offline_runtime": True, "internet_required_at_runtime": False,
            "local_ai_pipeline": False, "models_ready": False,
            "faceid_models_ready": False, "pad_ready": False,
            "database": db_status(), "templates": {"ready": False, "students": 0, "template_vectors": 0},
            "camera": {"opened": False, "state": "unavailable", "ai_active": False,
                       "reason": "UI_PREVIEW"},
            "anti_spoof": {"enabled": runtime_config.PAD_ENABLED, "checkin_requires_pass": True},
        }
    try:
        template_status = INDEX.status()
    except Exception as exc:
        template_status = {"ready": False, "error": str(exc), "template_vectors": 0, "students": 0}
    try:
        database = db_status()
    except Exception as exc:
        database = {"mode": "error", "error": str(exc)}
    return {
        "ok": True,
        "name": APP_NAME,
        "version": APP_VERSION,
        "profile": PROFILE,
        "offline_runtime": True,
        "internet_required_at_runtime": False,
        "cloud_ai_used": False,
        "local_ai_pipeline": True,
        "recognition_dedup": "track + same-camera + cross-camera + attendance",
        "identity_engine": "YuNet + SFace + passive PAD + latest-frame tracking",
        "ptz_control": False,
        "fixed_camera_mode": True,
        "virtual_gate": True,
        "presence_monitor": OFFICE.status(),
        "gpu": gpu_status(),
        "camera_mode": CAMERA_MODE,
        "models_ready": bool(CORE.ready),
        "faceid_models_ready": CORE.ready,
        "pad_ready": PAD.ready,
        "custom_detector_ready": CORE.custom_detector_ready,
        "anti_spoof": {
            "enabled": True,
            "mode": "pad+context" if PAD.ready else "context-multiframe-fallback",
            "checkin_requires_pass": True,
            "active_challenge_required": False,
            "geometry_hard_block": False,
            "pad": PAD.status(),
        },
        "database": database,
        "templates": template_status,
        "camera": CAMERA.status(),
    }


@app.get("/api/v1/students")
def students(request: Request):
    _auth_permission(request, "employee.view")
    # V6 returns operational FaceID/recognition metadata with every student so the
    # management screen can show real readiness instead of placeholder columns.
    # Correlated subqueries keep the query portable across SQLite maintenance mode
    # and PostgreSQL production mode without adding new schema dependencies.
    return fetchall(
        """SELECT s.id,s.student_code,s.full_name,s.class_name,s.faculty,s.email,s.phone,
        s.biometric_consent_status,s.created_at,s.updated_at,
        CASE WHEN EXISTS(SELECT 1 FROM face_templates f WHERE f.student_id=s.id) THEN 1 ELSE 0 END AS enrolled,
        COALESCE((SELECT MAX(f.pose_count) FROM face_templates f WHERE f.student_id=s.id),0) AS face_pose_count,
        (SELECT MAX(f.updated_at) FROM face_templates f WHERE f.student_id=s.id) AS face_updated_at,
        CASE WHEN EXISTS(SELECT 1 FROM student_photos p WHERE p.student_id=s.id AND p.photo_type='PROFILE') THEN 1 ELSE 0 END AS has_photo,
        COALESCE((SELECT COUNT(*) FROM recognition_events r WHERE r.student_id=s.id AND r.status='RECOGNIZED'),0) AS recognition_count,
        (SELECT MAX(r.event_at) FROM recognition_events r WHERE r.student_id=s.id AND r.status='RECOGNIZED') AS last_seen_at,
        COALESCE((SELECT r2.confidence FROM recognition_events r2 WHERE r2.student_id=s.id AND r2.status='RECOGNIZED' ORDER BY r2.id DESC LIMIT 1),0) AS last_confidence,
        CASE WHEN EXISTS(SELECT 1 FROM face_templates f2 WHERE f2.student_id=s.id)
             THEN COALESCE((SELECT v.status FROM face_enrollment_validations v WHERE v.student_id=s.id),'PENDING_STORE_VALIDATION')
             ELSE 'NOT_ENROLLED' END AS face_validation_status,
        COALESCE((SELECT v.camera_source FROM face_enrollment_validations v WHERE v.student_id=s.id),'') AS face_validation_camera,
        COALESCE((SELECT v.score FROM face_enrollment_validations v WHERE v.student_id=s.id),0) AS face_validation_score
        FROM students s
        ORDER BY s.id DESC"""
    )


@app.get("/api/v1/students/{student_id}")
def get_student(student_id: int, request: Request):
    _auth_permission(request, "employee.view")
    row = fetchone("SELECT * FROM students WHERE id=?", (student_id,))
    if not row:
        raise HTTPException(404, "Không tìm thấy nhân viên")
    template = fetchone("SELECT id,pose_count,created_at,updated_at FROM face_templates WHERE student_id=?", (student_id,))
    photos = student_photos(student_id)
    recognition = fetchone(
        """SELECT COUNT(*) AS recognition_count,MAX(event_at) AS last_seen_at
        FROM recognition_events WHERE student_id=? AND status='RECOGNIZED'""",
        (student_id,),
    ) or {}
    latest = fetchone(
        """SELECT confidence,liveness_score,anti_spoof_passed,event_at,status
        FROM recognition_events WHERE student_id=? ORDER BY id DESC LIMIT 1""",
        (student_id,),
    ) or {}
    row["enrolled"] = 1 if template else 0
    row["face_pose_count"] = int((template or {}).get("pose_count") or 0)
    row["face_updated_at"] = (template or {}).get("updated_at")
    row["has_photo"] = 1 if any(str(x.get("photo_type") or "").upper() == "PROFILE" for x in photos) else 0
    row["photos"] = photos
    row["recognition_count"] = int(recognition.get("recognition_count") or 0)
    row["last_seen_at"] = recognition.get("last_seen_at")
    row["last_confidence"] = float(latest.get("confidence") or 0.0)
    row["last_liveness_score"] = float(latest.get("liveness_score") or 0.0)
    row["last_anti_spoof_passed"] = bool(latest.get("anti_spoof_passed") or 0)
    row["last_event_status"] = latest.get("status")
    validation = face_enrollment_validation(student_id)
    row["face_validation_status"] = (validation or {}).get("status") or ("PENDING_STORE_VALIDATION" if template else "NOT_ENROLLED")
    row["face_validation"] = validation
    return row


@app.get("/api/v1/students/{student_id}/timeline")
def student_timeline(student_id: int, request: Request, limit: int = 60):
    _auth_permission(request, "employee.view")
    if not fetchone("SELECT id FROM students WHERE id=?", (student_id,)):
        raise HTTPException(404, "Không tìm thấy nhân viên")
    limit = max(5, min(200, int(limit)))
    rec = fetchall(
        """SELECT id,event_at,status,confidence,liveness_score,anti_spoof_passed,track_id,camera_source,detail_json
        FROM recognition_events WHERE student_id=? ORDER BY id DESC LIMIT ?""",
        (student_id, limit),
    )
    audit = fetchall(
        """SELECT id,event_at,event_type AS status,category,detail_json
        FROM audit_events WHERE student_id=? ORDER BY id DESC LIMIT ?""",
        (student_id, limit),
    )
    items = []
    for x in rec:
        items.append({**x, "kind": "RECOGNITION", "label": str(x.get("status") or "FACEID")})
    for x in audit:
        items.append({**x, "kind": "AUDIT", "label": str(x.get("status") or "SYSTEM")})
    items.sort(key=lambda x: str(x.get("event_at") or ""), reverse=True)
    return {"student_id": student_id, "items": items[:limit]}


@app.get("/api/v1/students/{student_id}/photo")
def get_student_photo(request: Request, student_id: int, photo_type: str = "PROFILE"):
    _auth_permission(request, "employee.view")
    if not fetchone("SELECT id FROM students WHERE id=?", (student_id,)):
        raise HTTPException(404, "Không tìm thấy nhân viên")
    path = photo_path(student_id, photo_type)
    if not path:
        raise HTTPException(404, "Nhân viên chưa có ảnh hồ sơ")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.put("/api/v1/students/{student_id}")
def update_student(student_id: int, payload: StudentUpdate, request: Request):
    _auth_permission(request, "employee.manage")
    current = fetchone("SELECT * FROM students WHERE id=?", (student_id,))
    if not current:
        raise HTTPException(404, "Không tìm thấy nhân viên")
    values = payload.model_dump(exclude_none=True)
    if not values:
        return current
    allowed = {"full_name", "class_name", "faculty", "email", "phone"}
    values = {k: v for k, v in values.items() if k in allowed}
    values["updated_at"] = utc_now()
    sets = ",".join(f"{k}=?" for k in values)
    execute(f"UPDATE students SET {sets} WHERE id=?", (*values.values(), student_id))
    try:
        add_audit_event("STUDENT", "STUDENT_UPDATED", "SUCCESS", student_id=student_id, detail={"fields": sorted(k for k in values if k != "updated_at")})
    except Exception:
        pass
    return get_student(student_id, request)


@app.put("/api/v1/students/{student_id}/consent")
def update_student_consent(student_id: int, payload: ConsentPayload, request: Request):
    actor = _auth_permission(request, "employee.enroll")
    if not fetchone("SELECT id FROM students WHERE id=?", (student_id,)):
        raise HTTPException(404, "Không tìm thấy nhân viên")
    now = utc_now()
    retired = []
    # Preserve existing consent withdrawal semantics, serialized with approval.
    # These are explicit runtime decisions, not migration/backfill operations.
    with qr_enrollment.publication_transaction() as conn:
        if payload.granted:
            conn.execute(
                "UPDATE students SET biometric_consent_status=?,biometric_consent_at=?,consent_at=?,updated_at=? WHERE id=?",
                ("GRANTED", now, now, now, student_id),
            )
            event_type = "BIOMETRIC_CONSENT_GRANTED"
        else:
            conn.execute(
                "UPDATE students SET biometric_consent_status=?,biometric_consent_at=?,updated_at=? WHERE id=?",
                ("WITHDRAWN", now, now, student_id),
            )
            conn.execute("DELETE FROM face_templates WHERE student_id=?", (student_id,))
            retired = qr_enrollment.cancel_employee_requests(student_id, reason="CONSENT_WITHDRAWN", actor=actor, conn=conn)
            event_type = "BIOMETRIC_CONSENT_WITHDRAWN"
    qr_enrollment.retire_requests(retired)
    if not payload.granted:
        delete_student_media(student_id)
        INDEX.invalidate()
    try:
        add_audit_event("STUDENT", event_type, "SUCCESS", student_id=student_id, detail={"actor": "admin"})
    except Exception:
        pass
    return get_student(student_id, request)


@app.post("/api/v1/students")
def create_student(payload: StudentCreate, request: Request):
    _auth_permission(request, "employee.manage")
    if not payload.student_code.strip() or not payload.full_name.strip():
        raise HTTPException(400, "Mã nhân viên và họ tên là bắt buộc")
    now = utc_now()
    status = "GRANTED" if payload.consent else "NOT_GRANTED"
    try:
        sid = execute(
            """INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,
            biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                payload.student_code.strip(),
                payload.full_name.strip(),
                payload.class_name.strip(),
                payload.faculty.strip(),
                payload.email.strip(),
                payload.phone.strip(),
                now if payload.consent else "",
                status,
                now if payload.consent else None,
                now,
                now,
            ),
        )
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(409, "Mã nhân viên đã tồn tại")
        raise
    try:
        add_audit_event("STUDENT", "STUDENT_CREATED", "SUCCESS", student_id=int(sid), detail={"student_code": payload.student_code.strip(), "full_name": payload.full_name.strip()})
    except Exception:
        pass
    return get_student(int(sid), request)


@app.delete("/api/v1/students/{student_id}")
def delete_student(student_id: int, request: Request):
    actor = _auth_permission(request, "employee.manage")
    if not fetchone("SELECT id FROM students WHERE id=?", (student_id,)):
        raise HTTPException(404, "Không tìm thấy nhân viên")
    snapshot = fetchone("SELECT student_code,full_name,class_name FROM students WHERE id=?", (student_id,)) or {}
    try:
        add_audit_event("STUDENT", "STUDENT_DELETED", "SUCCESS", student_id=student_id, detail=snapshot)
    except Exception:
        pass
    with qr_enrollment.publication_transaction() as conn:
        retired = qr_enrollment.cancel_employee_requests(student_id, reason="EMPLOYEE_DELETED", actor=actor, conn=conn)
        conn.execute("DELETE FROM students WHERE id=?", (student_id,))
    qr_enrollment.retire_requests(retired)
    delete_student_media(student_id)
    INDEX.invalidate()
    WALKBY.purge_student(student_id)
    CAMERA.purge_student(student_id)
    AI_RUNTIME.purge_student(student_id)
    return {"ok": True, "student_id": student_id, "faceid_revoked": True}


def _payload_image(payload: FramePayload):
    if payload.image:
        return CORE.decode_data_url(payload.image)
    if CAMERA_MODE == "service":
        frame = CAMERA.latest_frame()
        if frame is not None:
            return frame
    raise HTTPException(400, "Không có frame camera")


@app.post("/api/v1/enrollment/frame")
def enrollment_frame(payload: FramePayload, request: Request):
    actor = _auth_permission(request, "employee.enroll")
    return desktop_frame(payload, request, actor)


@app.post("/api/v1/enrollment/finalize")
def enrollment_finalize(payload: FramePayload, request: Request):
    actor = _auth_permission(request, "employee.enroll")
    return desktop_finalize(payload, request, actor)


@app.post("/api/v1/enrollment/reset")
def enrollment_reset(payload: FramePayload, request: Request):
    actor = _auth_permission(request, "employee.enroll")
    return desktop_reset(payload, request, actor)


@app.get("/api/v1/employees/{student_id}/face-validation")
def employee_face_validation_status(student_id: int, request: Request):
    _auth_permission(request, "employee.view")
    row = face_enrollment_validation(student_id)
    if row is None:
        enrolled = fetchone("SELECT student_id FROM face_templates WHERE student_id=?", (int(student_id),))
        return {"student_id": int(student_id), "status": "PENDING_STORE_VALIDATION" if enrolled else "NOT_ENROLLED"}
    return row


@app.post("/api/v1/employees/{student_id}/face-validation")
def employee_face_validation_run(student_id: int, payload: FramePayload, request: Request):
    actor = _auth_permission(request, "employee.enroll")
    if not fetchone("SELECT id FROM students WHERE id=?", (int(student_id),)):
        raise HTTPException(404, "Không tìm thấy nhân viên")
    if not fetchone("SELECT student_id FROM face_templates WHERE student_id=?", (int(student_id),)):
        raise HTTPException(409, "Nhân viên chưa có FaceID để xác minh")
    try:
        image = _payload_image(payload)
        faces = CORE.detect(image, long_range=False)
        if len(faces) != 1:
            return {"ok": False, "status": "RETRY", "message": "Cần đúng một khuôn mặt rõ trong khung camera.", "face_count": len(faces)}
        obs = CORE.observe(image, faces[0])
        quality = obs.quality or {}
        if int(quality.get("face_px") or 0) < 55 or float(quality.get("score") or 0.0) < 0.40:
            return {"ok": False, "status": "RETRY", "message": "Khuôn mặt chưa đủ rõ để xác minh. Hãy đứng gần camera hơn.", "quality": quality}
        ranked = INDEX.rank(obs.embedding, top_k=2)
        if not ranked:
            return {"ok": False, "status": "RETRY", "message": "Chưa có kết quả FaceID đủ tin cậy.", "quality": quality}
        sid, score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else -1.0
        margin = float(score - second)
        verified = int(sid) == int(student_id) and float(score) >= 0.56 and margin >= 0.045
        if not verified:
            candidate = fetchone("SELECT student_code,full_name FROM students WHERE id=?", (int(sid),)) or {}
            add_audit_event(
                "FACEID", "STORE_CAMERA_VALIDATION_FAILED", "REVIEW", student_id=int(student_id),
                camera_source=CAMERA.event_camera_source(), detail={
                    "actor": actor.get("username"), "top_student_id": int(sid), "top_name": candidate.get("full_name"),
                    "score": round(float(score),4), "margin": round(float(margin),4),
                },
            )
            return {
                "ok": False, "status": "RETRY",
                "message": "Camera cửa hàng chưa xác minh chắc chắn đúng nhân viên. Hãy thử lại ở vị trí/góc nhìn tự nhiên hơn.",
                "score": round(float(score),4), "margin": round(float(margin),4),
                "top_candidate": {"student_id": int(sid), "student_code": candidate.get("student_code") or "", "full_name": candidate.get("full_name") or ""},
                "quality": quality,
            }
        validation = mark_face_enrollment_validated(
            int(student_id), camera_source=CAMERA.event_camera_source(), score=float(score), margin=float(margin),
            actor=str(actor.get("username") or ""), note="Đã xác minh FaceID trên camera cửa hàng",
        )
        add_audit_event(
            "FACEID", "STORE_CAMERA_VALIDATION_SUCCESS", "SUCCESS", student_id=int(student_id),
            camera_source=CAMERA.event_camera_source(), detail={
                "actor": actor.get("username"), "score": round(float(score),4), "margin": round(float(margin),4),
            },
        )
        return {"ok": True, "status": "VERIFIED", "validation": validation, "score": round(float(score),4), "margin": round(float(margin),4), "quality": quality}
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/recognition/frame")
def recognition_frame(payload: FramePayload, request: Request):
    _auth_user(request, {"ADMIN", "OPERATOR"})
    """Browser-camera fallback.

    In the default service mode, recognition already runs continuously in the AI
    worker and the browser does not need to upload JPEG frames.
    """
    t0 = time.perf_counter()
    try:
        result = WALKBY.process(payload.session_id, _payload_image(payload), camera_source=CAMERA.event_camera_source())
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    result["ai_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return result


@app.post("/api/v1/recognition/reset")
def recognition_reset(payload: FramePayload, request: Request):
    _auth_user(request, {"ADMIN", "OPERATOR"})
    WALKBY.reset(payload.session_id)
    if CAMERA_MODE == "service":
        WALKBY.reset("service-camera")
    return {"ok": True}


@app.get("/api/v1/events")
def events(request: Request, limit: int = 30):
    _auth_permission(request, "history.view")
    limit = max(1, min(1000, int(limit)))
    rows = fetchall(
        """SELECT re.id,re.student_id,re.track_id,re.camera_source,re.direction,re.confidence,re.liveness_score,
        re.anti_spoof_passed,re.event_at,re.status,re.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM recognition_events re LEFT JOIN students s ON s.id=re.student_id
        ORDER BY re.id DESC LIMIT ?""",
        (limit,),
    )
    for row in rows:
        try:
            detail = json.loads(row.get("detail_json") or "{}")
        except Exception:
            detail = {}
        row["detail"] = detail
        row["reason"] = str(detail.get("reason") or (detail.get("liveness") or {}).get("reason") or "")
        row["checkin_result"] = str(detail.get("checkin_result") or ("SUCCESS" if row.get("anti_spoof_passed") else "FAILED" if str(row.get("status") or "").upper()=="SPOOF_BLOCKED" else ""))
        row["best_snapshot"] = str(detail.get("best_snapshot") or "")
    return rows


def _parse_history_time(value: str):
    try:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _history_spoof_method(reason: str) -> str:
    text = str(reason or "").lower()
    if any(token in text for token in ("màn hình", "screen", "điện thoại", "phone")):
        return "PHONE_SCREEN"
    if any(token in text for token in ("ảnh", "photo", "printed", "phẳng")):
        return "PHOTO"
    if any(token in text for token in ("liveness", "người thật", "chớp", "quay đầu")):
        return "LIVENESS_FAILED"
    return "ANTI_SPOOF"


def _history_spatial_bucket(detail: dict) -> str:
    """Coarse legacy-only bucket used when older events lack episode aggregation.

    New V2.7 rows already represent one physical episode, so they are keyed by DB
    event id.  For old rows this bucket prevents two simultaneous unknown faces on
    opposite sides of one camera from being compacted into the same UI item.
    """
    try:
        box = (detail or {}).get("bbox") or (detail or {}).get("face_bbox")
        if not isinstance(box, (list, tuple)) or len(box) < 4:
            return "NOBOX"
        x, y, w, h = [float(v) for v in box[:4]]
        fw = float((detail or {}).get("frame_width") or 0.0)
        fh = float((detail or {}).get("frame_height") or 0.0)
        if max(abs(x), abs(y), abs(w), abs(h)) > 1.5:
            if fw <= 1.0 or fh <= 1.0:
                return "NOBOX"
            x, y, w, h = x/fw, y/fh, w/fw, h/fh
        cx = max(0.0, min(0.999, x + w*0.5))
        cy = max(0.0, min(0.999, y + h*0.5))
        return f"{int(cx*4)}:{int(cy*3)}"
    except Exception:
        return "NOBOX"


@app.get("/api/v1/history/feed")
def history_feed(request: Request, limit: int = 800):
    """Unified enterprise history feed for attendance, FaceID and security.

    Recognition and anti-spoof keep their own authoritative tables; this endpoint only
    normalizes them for the customer-facing dashboard, so a spoof can retain the matched
    student's name while still being unambiguously marked CHECK-IN FAILED.
    """
    _auth_permission(request, "history.view")
    limit = max(50, min(2000, int(limit)))
    out: list[dict] = []
    recs = fetchall(
        """SELECT re.id,re.student_id,re.track_id,re.camera_source,re.confidence,re.liveness_score,
        re.anti_spoof_passed,re.event_at,re.status,re.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM recognition_events re LEFT JOIN students s ON s.id=re.student_id
        ORDER BY re.id DESC LIMIT ?""", (limit,),
    )
    for r in recs:
        try: detail = json.loads(r.get("detail_json") or "{}")
        except Exception: detail = {}
        status = str(r.get("status") or "").upper()
        reason = str(detail.get("reason") or (detail.get("liveness") or {}).get("reason") or "")
        if status == "RECOGNIZED" and bool(r.get("anti_spoof_passed")):
            event_type, ui_status = "CHECKIN_SUCCESS", "SUCCESS"
        elif status == "SPOOF_BLOCKED":
            event_type, ui_status = "CHECKIN_FAILED", "FAILED"
        elif status == "UNREGISTERED":
            event_type, ui_status = "UNKNOWN_PERSON", "WARNING"
        else:
            event_type, ui_status = "CHECKIN_REVIEW", "WARNING"
        out.append({
            "source": "recognition", "source_id": r.get("id"), "category": "CHECKIN",
            "event_type": event_type, "status": ui_status, "event_at": r.get("event_at"),
            "student_id": r.get("student_id"), "student_code": r.get("student_code") or "",
            "full_name": r.get("full_name") or ("Chưa đăng ký" if event_type=="UNKNOWN_PERSON" else ""),
            "class_name": r.get("class_name") or "", "faculty": r.get("faculty") or "",
            "camera_source": r.get("camera_source") or "static-camera",
            "confidence": float(r.get("confidence") or 0.0), "liveness_score": float(r.get("liveness_score") or 0.0),
            "anti_spoof_passed": bool(r.get("anti_spoof_passed")), "reason": reason,
            "spoof_method": _history_spoof_method(reason) if status=="SPOOF_BLOCKED" else "",
            "snapshot_url": f"/api/v1/events/{int(r.get('id') or 0)}/evidence.jpg" if detail.get("snapshot_path") else str(detail.get("best_snapshot") or ""),
            "repeat_count": int((detail.get("aggregation") or {}).get("repeat_count") or 1),
            "episode_first_seen": str((detail.get("aggregation") or {}).get("first_seen") or r.get("event_at") or ""),
            "episode_last_seen": str((detail.get("aggregation") or {}).get("last_seen") or r.get("event_at") or ""),
            "detail": detail,
        })


    for r in audit_events(limit):
        try: detail = json.loads(r.get("detail_json") or "{}")
        except Exception: detail = {}
        out.append({
            "source": "audit", "source_id": r.get("id"), "category": str(r.get("category") or "SYSTEM").upper(),
            "event_type": str(r.get("event_type") or ""), "status": str(r.get("status") or "INFO").upper(),
            "event_at": r.get("event_at"), "student_id": r.get("student_id"),
            "student_code": r.get("student_code") or "", "full_name": r.get("full_name") or "",
            "class_name": r.get("class_name") or "", "faculty": r.get("faculty") or "",
            "camera_source": r.get("camera_source") or "", "reason": str(detail.get("reason") or ""), "detail": detail,
        })

    out.sort(key=lambda x: str(x.get("event_at") or ""), reverse=True)
    return {"items": out[:limit], "generated_at": utc_now()}


def _legacy_recognition_history_feed(request: Request, limit: int = 800):
    """Low-volume FaceID/security history, separate from HR tracking."""
    _auth_permission(request, "history.view")
    limit = max(20, min(2000, int(limit)))
    items: list[dict] = []
    rows = fetchall(
        """SELECT re.id,re.student_id,re.track_id,re.camera_source,re.confidence,re.liveness_score,
        re.anti_spoof_passed,re.event_at,re.status,re.detail_json,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM recognition_events re LEFT JOIN students s ON s.id=re.student_id
        ORDER BY re.id DESC LIMIT ?""",
        (limit,),
    )
    for r in rows:
        try:
            detail = json.loads(r.get("detail_json") or "{}") or {}
        except Exception:
            detail = {}
        status = str(r.get("status") or "").upper()
        reason = str(detail.get("reason") or (detail.get("liveness") or {}).get("reason") or "")
        if status == "RECOGNIZED" and bool(r.get("anti_spoof_passed")):
            event_type, ui_status = "RECOGNIZED", "SUCCESS"
        elif status == "SPOOF_BLOCKED":
            event_type, ui_status = "SPOOF_BLOCKED", "FAILED"
        elif status == "UNREGISTERED":
            event_type, ui_status = "UNREGISTERED", "WARNING"
        else:
            event_type, ui_status = "RECOGNITION_REVIEW", "WARNING"
        items.append({
            "source": "recognition", "source_id": r.get("id"), "category": "RECOGNITION",
            "event_type": event_type, "status": ui_status, "event_at": r.get("event_at"),
            "student_id": r.get("student_id"), "student_code": r.get("student_code") or "",
            "full_name": r.get("full_name") or ("Chưa đăng ký" if event_type == "UNREGISTERED" else ""),
            "class_name": r.get("class_name") or "", "faculty": r.get("faculty") or "",
            "track_id": r.get("track_id") or "", "camera_source": r.get("camera_source") or "",
            "confidence": float(r.get("confidence") or 0.0), "liveness_score": float(r.get("liveness_score") or 0.0),
            "anti_spoof_passed": bool(r.get("anti_spoof_passed")), "reason": reason,
            "spoof_method": _history_spoof_method(reason) if status == "SPOOF_BLOCKED" else "",
            "snapshot_url": f"/api/v1/events/{int(r.get('id') or 0)}/evidence.jpg" if detail.get("snapshot_path") else str(detail.get("best_snapshot") or ""),
            "repeat_count": int((detail.get("aggregation") or {}).get("repeat_count") or 1),
            "episode_first_seen": str((detail.get("aggregation") or {}).get("first_seen") or r.get("event_at") or ""),
            "episode_last_seen": str((detail.get("aggregation") or {}).get("last_seen") or r.get("event_at") or ""),
            "detail": detail,
        })
    # FaceID registration changes are useful in recognition audit but unrelated HR
    # posture/action events are intentionally excluded.
    for r in audit_events(limit):
        cat = str(r.get("category") or "").upper()
        etype = str(r.get("event_type") or "").upper()
        # Recognition History is biometric/security evidence only. Generic SECURITY
        # audit rows such as LOGIN_SUCCESS/LOGIN_FAILED belong to System > Audit Log.
        biometric_audit = (cat == "FACEID") or etype.startswith("FACE_") or etype in {
            "FACEID_ENROLL", "FACEID_UPDATE", "FACEID_DELETE", "BIOMETRIC_TEMPLATE_CHANGE"
        }
        if not biometric_audit:
            continue
        try:
            detail = json.loads(r.get("detail_json") or "{}") or {}
        except Exception:
            detail = {}
        items.append({
            "source": "audit", "source_id": r.get("id"), "category": "RECOGNITION",
            "event_type": etype, "status": str(r.get("status") or "INFO").upper(),
            "event_at": r.get("event_at"), "student_id": r.get("student_id"),
            "student_code": r.get("student_code") or "", "full_name": r.get("full_name") or "",
            "class_name": r.get("class_name") or "", "faculty": r.get("faculty") or "",
            "camera_source": r.get("camera_source") or "", "reason": str(detail.get("reason") or ""), "detail": detail,
        })
    items.sort(key=lambda x: str(x.get("event_at") or ""), reverse=True)

    # Collapse repetitive recognition/security rows for 24/7 operation. This also
    # cleans up old databases that were created before DB-side cooldown existed.
    collapsed: list[dict] = []
    recent: dict[str, tuple[datetime | None, int]] = {}
    for item in items:
        etype = str(item.get("event_type") or "").upper()
        if etype in {"RECOGNIZED", "CHECKIN_SUCCESS"}:
            identity = str(item.get("student_id") or item.get("student_code") or item.get("full_name") or "unknown")
            key = f"REC:{identity}:{item.get('camera_source') or ''}"
            window = 600.0
        elif etype in {"SPOOF_BLOCKED", "CHECKIN_FAILED"}:
            detail = item.get("detail") or {}
            agg = detail.get("aggregation") or {}
            if str(agg.get("policy") or "") == "TRACK_IDENTITY_EPISODE_V27":
                # One V2.7 DB row already equals one physical security episode.
                # Never collapse it with another simultaneous face on the same camera.
                key = f"SPOOF_EP:{item.get('source_id')}"
                window = 0.0
            else:
                identity = str(item.get("student_id") or "camera-episode")
                spatial = _history_spatial_bucket(detail)
                key = f"SPOOF_LEGACY:{identity}:{item.get('spoof_method') or ''}:{item.get('camera_source') or ''}:{spatial}"
                window = 180.0
        elif etype in {"UNREGISTERED", "UNKNOWN_PERSON"}:
            detail = item.get("detail") or {}
            agg = detail.get("aggregation") or {}
            if str(agg.get("policy") or "") == "TRACK_IDENTITY_EPISODE_V27":
                # Runtime DB aggregation already resolved tracker churn using bbox
                # continuity; preserve separate simultaneous unknown people here.
                key = f"UNK_EP:{item.get('source_id')}"
                window = 0.0
            else:
                spatial = _history_spatial_bucket(detail)
                key = f"UNK_LEGACY:{item.get('camera_source') or ''}:{spatial}"
                window = 180.0
        else:
            collapsed.append(item)
            continue
        cur = _parse_history_time(str(item.get("event_at") or ""))
        prev = recent.get(key)
        if prev and cur and prev[0]:
            gap = abs((prev[0] - cur).total_seconds())
            if gap <= window:
                target = collapsed[prev[1]]
                target["repeat_count"] = int(target.get("repeat_count") or 1) + 1
                target.setdefault("detail", {})["collapsed_repeats"] = int(target["repeat_count"])
                continue
        item["repeat_count"] = int(item.get("repeat_count") or 1)
        collapsed.append(item)
        recent[key] = (cur, len(collapsed)-1)
    return {"items": collapsed[:limit], "generated_at": utc_now()}


def _hr_daily_summary(items: list[dict], sessions: list[dict]) -> list[dict]:
    """Aggregate manager-facing presence metrics without creating extra DB rows."""
    now_utc = datetime.now(timezone.utc)
    grouped: dict[tuple[str, int], dict] = {}

    def key_for(student_id, stamp):
        dt = _parse_history_time(str(stamp or ""))
        if not dt or student_id is None:
            return None, None
        local_dt = dt.astimezone()
        return (local_dt.date().isoformat(), int(student_id)), local_dt

    for row in sessions:
        key, started = key_for(row.get("student_id"), row.get("started_at"))
        if not key or not started:
            continue
        bucket = grouped.setdefault(key, {
            "date": key[0], "student_id": key[1], "student_code": row.get("student_code") or "",
            "full_name": row.get("full_name") or "Chưa xác định", "class_name": row.get("class_name") or "",
            "faculty": row.get("faculty") or "", "presence_sec": 0.0, "outside_sec": 0.0,
            "session_count": 0, "exit_count": 0, "first_seen": row.get("started_at"), "last_seen": row.get("ended_at") or row.get("last_seen_at"),
        })
        duration = float(row.get("duration_sec") or 0.0)
        if str(row.get("status") or "").upper() == "OPEN":
            start_utc = _parse_history_time(str(row.get("started_at") or ""))
            if start_utc:
                duration = max(duration, (now_utc - start_utc).total_seconds())
        bucket["presence_sec"] += max(0.0, duration)
        bucket["session_count"] += 1
        if str(row.get("started_at") or "") < str(bucket.get("first_seen") or row.get("started_at") or ""):
            bucket["first_seen"] = row.get("started_at")
        tail = row.get("ended_at") or row.get("last_seen_at")
        if str(tail or "") > str(bucket.get("last_seen") or ""):
            bucket["last_seen"] = tail

    # Pair OUT -> next ENTRY/RETURN on the same local day to estimate time outside.
    events_by_person: dict[tuple[str, int], list[dict]] = {}
    for item in items:
        key, _ = key_for(item.get("student_id"), item.get("event_at"))
        if not key:
            continue
        events_by_person.setdefault(key, []).append(item)
        if str(item.get("event_type") or "").upper() == "EXIT":
            bucket = grouped.setdefault(key, {
                "date": key[0], "student_id": key[1], "student_code": item.get("student_code") or "",
                "full_name": item.get("full_name") or "Chưa xác định", "class_name": item.get("class_name") or "",
                "faculty": item.get("faculty") or "", "presence_sec": 0.0, "outside_sec": 0.0,
                "session_count": 0, "exit_count": 0, "first_seen": "", "last_seen": "",
            })
            bucket["exit_count"] += 1

    for key, rows in events_by_person.items():
        rows.sort(key=lambda x: str(x.get("event_at") or ""))
        out_at = None
        for item in rows:
            etype = str(item.get("event_type") or "").upper()
            dt = _parse_history_time(str(item.get("event_at") or ""))
            if not dt:
                continue
            if etype == "EXIT":
                out_at = dt
            elif etype in {"ENTRY", "RETURN"} and out_at is not None and dt >= out_at:
                grouped[key]["outside_sec"] += max(0.0, (dt - out_at).total_seconds())
                out_at = None

    rows = list(grouped.values())
    for row in rows:
        row["presence_sec"] = round(float(row.get("presence_sec") or 0.0), 1)
        row["outside_sec"] = round(float(row.get("outside_sec") or 0.0), 1)
    rows.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("full_name") or "")), reverse=True)
    return rows


@app.get("/api/v1/history/hr")
def hr_history_feed(request: Request, limit: int = 800):
    """Manager-facing HR history: business events + sessions, never tracker churn."""
    _auth_permission(request, "history.view")
    limit = max(20, min(2000, int(limit)))
    raw_events = hr_event_history(limit)
    sessions = hr_presence_history(min(limit, 1000))
    current = hr_current_presence()
    realtime = OFFICE.realtime_state()
    items: list[dict] = []
    business_types = {"PRESENCE_START", "PRESENCE_END", "ENTRY", "RETURN", "EXIT"}
    for r in raw_events:
        detail = dict(r.get("detail") or {})
        etype = str(r.get("event_type") or "").upper()
        if etype not in business_types:
            continue
        # Old V2.5 rows caused by temporary camera loss are diagnostic evidence,
        # not a business conclusion that the employee left. Keep them out of HR.
        if etype == "PRESENCE_END" and str(detail.get("reason") or "").upper() == "CAMERA_NOT_VISIBLE":
            continue
        items.append({
            "source": "hr", "source_id": r.get("id"), "category": "HR",
            "event_type": etype, "status": str(r.get("status") or "INFO"),
            "event_at": r.get("event_at"), "student_id": r.get("student_id"),
            "student_code": r.get("student_code") or "", "full_name": r.get("full_name") or "Chưa xác định",
            "class_name": r.get("class_name") or "", "faculty": r.get("faculty") or "",
            "track_id": r.get("track_id") or "", "camera_source": r.get("camera_source") or "",
            "action": str(detail.get("status") or ""),
            "reason": str(detail.get("reason") or ""), "detail": detail,
            # The evidence route serves a V2.9 HR snapshot. For legacy rows it can
            # safely reuse the nearest FaceID evidence for the same employee/time.
            "snapshot_url": f"/api/v1/history/hr/{int(r.get('id') or 0)}/evidence.jpg",
        })
    # Defensive cleanup for older databases: a business event belongs once to one
    # presence session. Keep the newest row if a legacy worker wrote duplicates.
    collapsed: list[dict] = []
    seen_session_events: set[tuple] = set()
    for item in items:
        session_id = (item.get("detail") or {}).get("session_id")
        if session_id and str(item.get("event_type") or "").upper() in {"PRESENCE_START", "PRESENCE_END", "ENTRY", "RETURN", "EXIT"}:
            key = (int(item.get("student_id") or 0), str(item.get("event_type") or "").upper(), str(session_id))
            if key in seen_session_events:
                continue
            seen_session_events.add(key)
        collapsed.append(item)
    items = collapsed
    daily = _hr_daily_summary(items, sessions)
    office_cfg = OFFICE.config()
    line_cfg = dict(office_cfg.get("line") or {})
    gate_authoritative = bool(line_cfg.get("configured") and line_cfg.get("enabled"))
    visible_now = sum(1 for x in realtime if bool(x.get("visible")))
    temporarily_lost = sum(1 for x in realtime if not bool(x.get("visible")))
    return {
        "items": items[:limit],
        "sessions": sessions,
        "current": current,
        "realtime": realtime,
        "daily_summary": daily,
        "policy": {
            "virtual_gate_configured": bool(line_cfg.get("configured")),
            "virtual_gate_enabled": bool(line_cfg.get("enabled")),
            "session_authority": "VIRTUAL_GATE" if gate_authoritative else "CAMERA_OBSERVATION",
            "camera_loss_means_out": False,
        },
        "summary": {
            "currently_present": visible_now,
            "temporarily_lost": temporarily_lost,
            "open_sessions": len(current),
            "events_loaded": len(items),
            "sessions_loaded": len(sessions),
        },
        "generated_at": utc_now(),
    }


@app.get("/api/v1/history/technical")
def technical_history_feed(request: Request, limit: int = 400):
    """Diagnostics kept separate from HR decisions and manager-facing history."""
    _auth_permission(request, "history.view")
    limit = max(20, min(1500, int(limit)))
    items: list[dict] = []
    for r in audit_events(min(2000, limit * 3)):
        category = str(r.get("category") or "").upper()
        if category != "TECHNICAL":
            continue
        try:
            detail = json.loads(str(r.get("detail_json") or "{}")) or {}
        except Exception:
            detail = {}
        items.append({
            "source": "audit", "source_id": r.get("id"), "category": "TECHNICAL",
            "event_type": str(r.get("event_type") or ""), "status": str(r.get("status") or "INFO"),
            "event_at": r.get("event_at"), "student_id": r.get("student_id"),
            "student_code": r.get("student_code") or "", "full_name": r.get("full_name") or "",
            "camera_source": r.get("camera_source") or "", "detail": detail,
        })
    # Surface legacy V2.5 visibility rows here instead of silently losing them.
    for r in hr_event_history(min(1000, limit * 2)):
        etype = str(r.get("event_type") or "").upper()
        if etype not in {"NOT_VISIBLE", "BACK_IN_VIEW", "STATUS_CHANGE"}:
            continue
        detail = dict(r.get("detail") or {})
        items.append({
            "source": "legacy_hr", "source_id": r.get("id"), "category": "TECHNICAL",
            "event_type": etype, "status": str(r.get("status") or "INFO"),
            "event_at": r.get("event_at"), "student_id": r.get("student_id"),
            "student_code": r.get("student_code") or "", "full_name": r.get("full_name") or "",
            "camera_source": r.get("camera_source") or "", "detail": detail,
        })
    items.sort(key=lambda x: str(x.get("event_at") or ""), reverse=True)
    return {
        "items": items[:limit],
        "realtime": OFFICE.realtime_state(),
        "performance": CAMERA.performance_status(),
        "generated_at": utc_now(),
    }


@app.get("/api/v1/camera/sources")
def camera_sources(request: Request):
    _auth_permission(request, "camera.live")
    rows = fetchall("SELECT * FROM camera_devices ORDER BY id")
    catalog = build_source_catalog(rows, CAMERA.current_source_identity(), CAMERA.status())
    return JSONResponse(catalog, headers={"Cache-Control": "no-store"})


@app.get("/api/v1/camera/status")
def camera_status(request: Request, ):
    _auth_permission(request, "camera.view")
    return {"mode": CAMERA_MODE, **CAMERA.status(), "ptz": CAMERA.ptz_status()}


@app.get("/api/v1/performance/status")
def performance_status():
    """Realtime telemetry for adaptive latest-frame AI scheduling."""
    return {"camera": CAMERA.status(), "performance": CAMERA.performance_status(), "media": MEDIA.status(), "native_gateway": MEDIA_GATEWAY.status(), "generated_at": utc_now()}


@app.get("/api/v1/camera/control/status")
def camera_control_status():
    return CAMERA.ptz_status()


def _perform_camera_selection(source: str, label: str, actor: dict, target_id: int | None):
    before = CAMERA.status()
    def audit(action, outcome, detail):
        try:
            add_audit_event("SYSTEM", action, outcome, camera_source=label,
                detail=sanitize_payload({"actor":actor.get("username"),"camera_id":target_id, **detail}))
        except Exception:
            pass
    audit("CAMERA_HANDOVER_STARTED", "INFO", {"from":before.get("source_label"),"target":display_source(source)})
    # A live-grid refresh cannot reopen the candidate source during preflight.
    try:
        with AI_RUNTIME.reserve_camera(target_id), FLEET_V4.reserve(target_id):
            result = CAMERA.safe_select_source(source, source_label=label)
    except (FleetUnavailable, RuntimeError):
        result = {"ok": False, "code": "FLEET_RETIRE_FAILED", "kept_previous": True,
                  "message": "Camera reader is still stopping; retry shortly"}
    if not result.get("ok"):
        audit("CAMERA_HANDOVER_FAILED", "FAILED", {"code":result.get("code"),"kept_previous":result.get("kept_previous")})
        return JSONResponse(status_code=409 if result.get("busy") else 503,
            content=sanitize_payload({"detail":result.get("message") or "Camera unavailable", **result}),
            headers={"Cache-Control":"no-store"})
    _configure_ai_registry_source()
    AI_RUNTIME.reconcile()
    persisted=True
    try:
        current=camera_settings();current["source"]=source;save_camera_settings(current)
    except Exception:
        persisted=False
    gateway_status = {}
    try:
        gateway_status = MEDIA_GATEWAY.sync_source(source, label)
    except Exception:
        gateway_status = {"available": False}
    audit("CAMERA_HANDOVER_COMPLETED", "SUCCESS", {"source":display_source(source),"persisted":persisted,"native_gateway":bool(gateway_status.get("available"))})
    return {"ok":True, **result,"persisted":persisted,
            "native_gateway": sanitize_payload(gateway_status),
            "persistence_warning":"" if persisted else "Camera da doi, nhung chua luu duoc cau hinh cho lan khoi dong sau."}


@app.post("/api/v1/camera/select")
def camera_select(payload: CameraSelectPayload, request: Request):
    actor = _auth_permission(request, "camera.switch")
    try:
        source,label = _resolve_camera_selection(payload.source)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    return _perform_camera_selection(source,label,actor,_camera_id_for_source(source))


@app.post("/api/v1/camera/test-source")
def camera_test_source(payload: CameraSelectPayload, request: Request):
    actor = _auth_permission(request, "camera.switch")
    try:
        source,label = _resolve_camera_selection(payload.source)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    try:
        with FLEET_V4.reserve(_camera_id_for_source(source)):
            result=CAMERA.test_source(source,source_label=label)
    except FleetUnavailable:
        raise HTTPException(503, "FLEET_RETIRE_FAILED") from None
    try:
        add_audit_event("SYSTEM","CAMERA_PREFLIGHT","SUCCESS" if result.get("ok") else "FAILED",
            camera_source=label,detail={"actor":actor.get("username"),"code":result.get("code", "READY")})
    except Exception: pass
    return JSONResponse(sanitize_payload(result), headers={"Cache-Control":"no-store"})


@app.post("/api/v1/camera/control")
def camera_control(payload: CameraControlPayload, request: Request):
    _auth_user(request, {"ADMIN", "OPERATOR"})
    try:
        result = CAMERA.control_ptz(payload.action, payload.speed)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    try:
        add_audit_event("SYSTEM", "CAMERA_CONTROL", "SUCCESS", camera_source=str(result.get("camera_source") or "static-camera"), detail={"action": payload.action, "speed": payload.speed, "mode": result.get("mode")})
    except Exception:
        pass
    return {"ok": True, **result}


@app.get("/api/v1/camera/latest-event")
def camera_latest_event():
    return {"event": CAMERA.latest_event()}


@app.get("/api/v1/camera/recent-events")
def camera_recent_events(limit: int = 12):
    return {"events": CAMERA.recent_events(limit)}


@app.get("/api/v1/camera/latest-result")
def camera_latest_result():
    return CAMERA.latest_result()


def _preview_response(raw: bool = False, *, packet=None):
    jpeg, seq, age = CAMERA.preview_packet(raw) if packet is None else packet
    if not jpeg:
        raise HTTPException(503, "Camera chua co khung hinh; dang ket noi lai")
    return Response(jpeg, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Camera-Seq": str(seq),
        "X-Frame-Age-Ms": str(age if age is not None else 999999),
    })


@app.get("/api/v1/camera/frame.jpg")
def camera_frame(request: Request):
    _auth_permission(request, "camera.view")
    return _preview_response(False)


@app.get("/api/v1/camera/frame_raw.jpg")
def camera_frame_raw(request: Request):
    _auth_permission(request, "camera.view")
    return _preview_response(True)


@app.get("/api/v1/events/{event_id}/evidence.jpg")
def recognition_event_evidence(request: Request, event_id: int):
    actor = _auth_permission(request, "evidence.view")
    event = fetchone("SELECT store_id FROM recognition_events WHERE id=?", (event_id,))
    if not event:
        raise HTTPException(404, "Không tìm thấy sự kiện")
    _require_store_scope(actor, event.get("store_id"))
    path = recognition_evidence_path(event_id)
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(404, "Sự kiện chưa có ảnh bằng chứng")
    return FileResponse(path, media_type="image/jpeg", filename=f"recognition_{int(event_id)}.jpg", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/history/hr/{event_id}/evidence.jpg")
def hr_history_event_evidence(event_id: int, request: Request):
    actor = _auth_permission(request, "evidence.view")
    if scoped_store_ids(actor) is not None:
        raise HTTPException(403, "Bằng chứng cũ chưa có attribution cửa hàng để xác minh quyền")
    path = hr_event_evidence_path(event_id)
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(404, "Sự kiện nhân sự chưa có ảnh bằng chứng")
    return FileResponse(path, media_type="image/jpeg", filename=f"hr_event_{int(event_id)}.jpg", headers={"Cache-Control": "no-store"})


@app.websocket("/api/v1/operations/live/ws")
async def operations_live_ws(websocket: WebSocket):
    """Low-rate operational telemetry push for Dashboard/Live Monitor.

    Video remains on the dedicated preview pipeline. This channel pushes only
    lightweight status/event JSON, eliminating rapid REST polling on operations
    pages while keeping realtime UI feedback.
    """
    if await run_in_threadpool(_websocket_user, websocket) is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    last_event_id = None
    try:
        while True:
            camera = CAMERA.status()
            perf = CAMERA.performance_status()
            latest = CAMERA.latest_event()
            event_id = (latest or {}).get("id")
            payload = {
                "camera": camera,
                "performance": perf,
                "latest_event": latest if event_id != last_event_id else None,
                "generated_at": utc_now(),
            }
            await websocket.send_json(sanitize_payload(payload))
            if event_id is not None:
                last_event_id = event_id
            await asyncio.sleep(0.8)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/v1/camera/stream.mjpg")
def camera_stream(request: Request):
    _auth_permission(request, "camera.view")
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            jpeg = CAMERA.latest_jpeg()
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.035)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","X-Accel-Buffering":"no"})


@app.get("/api/v1/camera/stream_raw.mjpg")
def camera_stream_raw(request: Request):
    _auth_permission(request, "camera.view")
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            jpeg = CAMERA.latest_raw_jpeg()
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.035)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","X-Accel-Buffering":"no"})


def _media_tracking_payload(camera_id: int | None = None) -> dict:
    context = (AI_RUNTIME.context(camera_id) or camera_context(camera_id)) if camera_id is not None else source_context(CAMERA.current_source_identity())
    cid = (context or {}).get("camera_id")
    service = AI_RUNTIME.service(cid) if cid is not None else None
    ai_state = AI_RUNTIME.camera_state(cid) if cid is not None else {"ai_state": "DISABLED"}
    # A live video frame is not proof that inference succeeded. Do not publish
    # old identity/boxes while this source is disabled, paused, starting or failed.
    observer = service.latest_result() if service is not None and ai_state.get("ai_state") == "ACTIVE" else {}
    camera = service.status() if service is not None else {}
    performance = service.performance_status() if service is not None else {}
    tracks = []
    for raw in list(observer.get("tracks") or []):
        bbox = list(raw.get("bbox") or [0, 0, 0, 0])[:4]
        face_bbox = list(raw.get("face_bbox") or [0, 0, 0, 0])[:4]
        verified = bool(raw.get("recognized")) and not raw.get("spoof_blocked")
        candidate = raw.get("candidate_student") or {}
        candidate_matches = verified and candidate.get("id") == raw.get("student_id")
        tracks.append({
            "track_id": str(raw.get("track_id") or ""),
            "appearance_id": raw.get("appearance_id"),
            "daily_sequence": raw.get("daily_sequence"),
            "business_date": raw.get("business_date"),
            "event_id": raw.get("event_id"),
            "student_id": raw.get("student_id"),
            "student_code": str(raw.get("student_code") or (candidate.get("student_code") if candidate_matches else "") or ""),
            "full_name": str(raw.get("full_name") or (candidate.get("full_name") if candidate_matches else "") or "") if verified else "",
            "recognized": verified,
            "identity_verified": bool(raw.get("identity_verified")),
            "unregistered": bool(raw.get("unregistered")),
            "spoof_blocked": bool(raw.get("spoof_blocked")),
            "confidence": round(float(raw.get("confidence") or 0.0), 4),
            "bbox": [int(float(v or 0)) for v in bbox],
            "face_bbox": [int(float(v or 0)) for v in face_bbox],
            "status": str(raw.get("status") or "ANALYZING"),
            "pad_status": str((raw.get("liveness") or {}).get("status") or "PENDING"),
            "tracking_grace": bool(raw.get("tracking_grace")),
            "observation_age_ms": int(raw.get("observation_age_ms") or 0),
            **_public_verification_diagnostics(raw),
        })
    return {
        "type": "tracking",
        "bbox_format": "xywh",
        "camera_id": cid,
        "store_id": (context or {}).get("store_id"),
        "store_name": (context or {}).get("store_name"),
        "zone_name": (context or {}).get("zone_name"),
        "camera_name": (context or {}).get("camera_name"),
        **_public_ai_status(ai_state),
        "source_epoch": observer.get("source_epoch"),
        "sent_at": time.time(),
        "updated_at": float(observer.get("updated_at") or 0.0),
        "frame_width": int(observer.get("frame_width") or camera.get("actual_width") or 0),
        "frame_height": int(observer.get("frame_height") or camera.get("actual_height") or 0),
        "camera_seq": int(camera.get("latest_seq") or 0),
        "tracking_age_ms": performance.get("tracking_result_age_ms"),
        "source_age_ms": camera.get("last_frame_age_ms"),
        "ai_performance": _public_ai_performance(camera, performance) if ai_state.get("ai_state") == "ACTIVE" else _public_ai_performance({}, {}),
        "ai_detection": _public_ai_detection(observer, camera, performance) if ai_state.get("ai_state") == "ACTIVE" else None,
        "tracks": tracks,
    }


def _public_ai_number(value):
    return round(value, 4) if type(value) in {int, float} and math.isfinite(value) and value >= 0 else None


def _public_verification_diagnostics(track):
    quality = track.get("quality_gate") if isinstance(track.get("quality_gate"), dict) else {}
    live = track.get("liveness") if isinstance(track.get("liveness"), dict) else {}
    signals = live.get("signals") if isinstance(live.get("signals"), dict) else {}
    pad = signals.get("pad") if isinstance(signals.get("pad"), dict) else {}
    face_quality = track.get("quality") if isinstance(track.get("quality"), dict) else {}
    reason = ""
    if track.get("spoof_blocked") or live.get("status") in {"BLOCKED", "FAIL"}:
        reason = "PAD_BLOCKED"
    elif quality.get("ok") is False:
        text = str(quality.get("reason") or "").lower()
        reason = next((code for marker, code in (("nhỏ", "FACE_TOO_SMALL"), ("nghiêng", "FACE_POSE"),
                      ("dọc", "FACE_PITCH"), ("nét", "FACE_BLUR"), ("ánh sáng", "FACE_LIGHTING")) if marker in text), "FACE_QUALITY_WAIT")
    elif live.get("reason") == "PAD_INFERENCE_FAILED":
        reason = "PAD_INFERENCE_FAILED"
    elif live.get("status") != "PASS":
        reason = "PAD_CHECKING"
    return {"verification_reason_code": reason,
            "pad_live_score": _public_ai_number(pad.get("live_score")),
            "pad_spoof_score": _public_ai_number(pad.get("spoof_score")),
            "face_quality": {key: _public_ai_number(face_quality.get(key)) for key in
                             ("face_px", "score", "sharpness", "brightness", "contrast")}}


def _public_ai_detection(observer, camera, performance):
    detection = observer.get("detection") if isinstance(observer.get("detection"), dict) else {}
    capture = performance.get("ai_capture") if isinstance(performance.get("ai_capture"), dict) else {}
    mode = camera.get("ai_input_mode")
    return {"input_mode": mode if mode in {"HIKVISION_SUBSTREAM", "MAIN_FALLBACK"} else "",
            "input_seq": _public_ai_number(camera.get("ai_seq")),
            "input_width": _public_ai_number(observer.get("frame_width")),
            "input_height": _public_ai_number(observer.get("frame_height")),
            "substream_capture_fps": _public_ai_number(capture.get("capture_fps")),
            "substream_age_ms": _public_ai_number(capture.get("frame_age_ms")),
            **{key: _public_ai_number(detection.get(key)) for key in
               ("detected_faces", "observed_faces", "observation_errors", "no_face_streak")},
            "recovery_attempted": detection.get("recovery_attempted") if type(detection.get("recovery_attempted")) is bool else None}


def _public_ai_performance(camera, performance):
    metrics = camera.get("ai_metrics") if isinstance(camera.get("ai_metrics"), dict) else {}
    stages = camera.get("ai_stage_times") if isinstance(camera.get("ai_stage_times"), dict) else {}
    lanes = {}
    for name in ("pad", "faceid"):
        raw = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
        lanes[name] = {key: _public_ai_number(raw.get(key)) for key in
                       ("fps", "completed", "dropped", "errors", "last_ms", "last_latency_ms", "last_queue_wait_ms", "pending")}
        lanes[name]["stalled"] = raw.get("stalled") if type(raw.get("stalled")) is bool else None
        lanes[name]["busy"] = raw.get("busy") if type(raw.get("busy")) is bool else None
    return {**{key: _public_ai_number(performance.get(key)) for key in
               ("actual_ai_fps", "capture_fps", "avg_ai_ms", "p95_ai_ms", "effective_target_fps")}, **lanes,
            "stage_times": {key: _public_ai_number(stages.get(key)) for key in
                            ("work_lock_wait_ms", "acquisition_ms", "preprocessing_ms", "detection_ms", "observation_ms",
                             "tracking_ms", "verification_dispatch_ms", "sample_total_ms", "capture_to_result_ms")}}


@app.get("/api/v1/media/metadata")
def media_metadata(request: Request, camera_id: int):
    actor = _auth_permission(request, "camera.live")
    _camera_scope_context(actor, camera_id)
    payload = _media_tracking_payload(camera_id)
    _require_store_scope(actor, payload.get("store_id"))
    return payload


@app.get("/api/v1/media/capabilities")
def media_capabilities(camera_id: int | None = None):
    """Describe browser media transports without exposing camera credentials."""
    payload = dict(MEDIA.status())
    _sync_adaptive_gateway_quality()
    payload["native_gateway"] = MEDIA_GATEWAY.status()
    payload["camera_matches_active"] = True
    if camera_id is not None:
        _row, _source, active = _fleet_camera_source(camera_id)
        payload["camera_matches_active"] = bool(active)
        if not active:
            payload["native_gateway"] = {
                **payload["native_gateway"], "available": False, "native_webrtc": False,
                "transport": "NONE", "state": "BLOCKED", "reason": "NON_PRIMARY_CAMERA",
                "reason_code": "NON_PRIMARY_CAMERA",
                "last_error": "Camera này chưa có gateway native riêng; dùng transport dự phòng của đúng camera.",
                "whep_url": "",
                "small_available": False,
                "small_fallback_reason": "NON_PRIMARY_CAMERA",
            }
            payload["webrtc"] = {**payload.get("webrtc", {}), "available": False}
    payload["policy"] = "NATIVE_GATEWAY_FIRST"
    payload["fallback_chain"] = ["MEDIAMTX_WHEP_WEBRTC", "PYTHON_WEBRTC", "WEBSOCKET_ACK_BITMAP", "MJPEG", "HTTP_SNAPSHOT"]
    return sanitize_payload(payload)


def _sync_adaptive_gateway_quality() -> None:
    """A fresh registered decoder proof permits auxiliary native small views."""
    _configure_ai_registry_source()
    source = CAMERA.validated_ai_substream_source() if runtime_config.ADAPTIVE_VIDEO_QUALITY else ""
    reason = "SMALL_NOT_VALIDATED" if runtime_config.ADAPTIVE_VIDEO_QUALITY else "ADAPTIVE_DISABLED"
    MEDIA_GATEWAY.sync_small_source(source, fallback_reason=reason)


@app.get("/api/v1/media/gateway/status")
def media_gateway_status(request: Request):
    _auth_permission(request, "camera.live")
    return sanitize_payload({"ok": True, **MEDIA_GATEWAY.status()})


@app.post("/api/v1/media/gateway/restart")
def media_gateway_restart(request: Request):
    actor = _auth_permission(request, "camera.configure")
    result = MEDIA_GATEWAY.restart()
    try:
        add_audit_event("SYSTEM", "MEDIA_GATEWAY_RESTART", "SUCCESS" if result.get("available") else "FAILED", camera_source=CAMERA.event_camera_source(), detail={"actor": actor.get("username"), "available": bool(result.get("available")), "error": str(result.get("last_error") or "")[:200]})
    except Exception:
        pass
    return sanitize_payload({"ok": bool(result.get("process_alive")), **result})


def _require_active_media_camera(camera_id: int | None) -> str | None:
    if camera_id is None:
        return None
    _row, source, active = _fleet_camera_source(camera_id)
    if not active:
        raise HTTPException(409, "Camera đã thay đổi; kết nối lại transport của đúng camera")
    return source


@app.post("/api/v1/media/gateway/whep")
async def media_gateway_whep(request: Request, camera_id: int | None = None, quality: str = "main"):
    """Authenticate signaling while H.264 media travels directly over WebRTC."""
    actor = _auth_permission(request, "camera.live")
    if quality not in {"main", "small"}:
        raise HTTPException(400, "Unsupported media quality")
    source = _require_active_media_camera(camera_id)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/sdp":
        raise HTTPException(415, "WHEP yêu cầu application/sdp")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            raise HTTPException(413, "SDP vượt giới hạn 64 KiB")
    try:
        sdp = body.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "SDP không hợp lệ")
    owner = str(actor["id"])
    current_source, source_epoch = CAMERA.media_source_context()
    source = current_source if source is None else source
    try:
        await run_in_threadpool(_sync_adaptive_gateway_quality)
        result = await run_in_threadpool(MEDIA_GATEWAY.create_whep_session, sdp, owner,
                                        expected_source=source, quality=quality)
        if CAMERA.media_source_context() != (current_source, source_epoch):
            raise HTTPException(409, "Camera changed during video negotiation")
        if camera_id is not None and _require_active_media_camera(camera_id) != source:
            raise HTTPException(409, "Camera đã thay đổi trong lúc khởi tạo video")
        if result.get("quality") == "small" and not CAMERA.validated_ai_substream_source():
            raise HTTPException(409, "Small stream validation expired during video negotiation")
        if await request.is_disconnected():
            await run_in_threadpool(MEDIA_GATEWAY.delete_whep_session, result["session_id"], owner)
            return Response(status_code=499)
    except HTTPException:
        if 'result' in locals():
            await run_in_threadpool(MEDIA_GATEWAY.delete_whep_session, result["session_id"], owner)
        raise
    except NativeGatewayError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "code": exc.code})
    return Response(
        content=result["sdp"], status_code=201, media_type="application/sdp",
        headers={"Location": f"/api/v1/media/gateway/whep/session/{result['session_id']}", "Cache-Control": "no-store",
                 "X-BTMH-Quality": result.get("quality", "main"),
                 "X-BTMH-Quality-Fallback": result.get("quality_fallback_reason", "")},
    )


@app.delete("/api/v1/media/gateway/whep/session/{session_id}")
async def media_gateway_whep_close(session_id: str, request: Request):
    actor = _auth_permission(request, "camera.live")
    try:
        await run_in_threadpool(MEDIA_GATEWAY.delete_whep_session, session_id, str(actor["id"]))
    except NativeGatewayError as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc), "code": exc.code})
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@app.post("/api/v1/media/webrtc/offer")
async def media_webrtc_offer(payload: WebRTCOfferPayload, request: Request, camera_id: int | None = None):
    # V5.4.10 fallback Python WebRTC follows the same camera.live permission as the camera UI.
    # It is no longer restricted to ADMIN, while credentials remain server-side.
    actor = _auth_permission(request, "camera.live")
    source = _require_active_media_camera(camera_id)
    try:
        result = await asyncio.wait_for(MEDIA.create_answer(sdp=payload.sdp, offer_type=payload.type, owner=str(actor["id"]), source_identity=source), timeout=12.0)
        if camera_id is not None and _require_active_media_camera(camera_id) != source:
            raise HTTPException(409, "Camera đã thay đổi trong lúc khởi tạo video")
        if await request.is_disconnected():
            await MEDIA.close(result["session_id"], owner=str(actor["id"]))
            return Response(status_code=499)
        return result
    except HTTPException:
        if 'result' in locals():
            await MEDIA.close(result["session_id"], owner=str(actor["id"]))
        raise
    except asyncio.TimeoutError:
        raise HTTPException(504, "Python WebRTC negotiation quá thời gian")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Không thể khởi tạo WebRTC: {exc}")


@app.post("/api/v1/media/webrtc/close")
async def media_webrtc_close(payload: WebRTCClosePayload, request: Request):
    actor = _auth_permission(request, "camera.live")
    try:
        return {"ok": True, "closed": await MEDIA.close(payload.session_id, owner=str(actor["id"]))}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.websocket("/api/v1/media/preview/ws")
async def media_preview_ws(websocket: WebSocket):
    """V5.4.10 compatibility fallback preview with strict one-frame backpressure.

    A frame is sent only after the browser ACKs the previous one.  The next packet
    is always CAMERA.latest_observation_packet(), so slow rendering drops old
    frames instead of creating delayed playback.  This path avoids a second video
    encode on the local management PC and is independent from FaceID/PAD cadence.
    """
    actor = await run_in_threadpool(_websocket_user, websocket)
    if actor is None:
        await websocket.close(code=4401)
        return
    raw_id = (getattr(websocket, "query_params", {}) or {}).get("camera_id")
    try:
        camera_id = int(raw_id) if raw_id is not None else None
        await run_in_threadpool(_camera_scope_context, actor, camera_id)
        if camera_id is not None:
            scoped_source = await run_in_threadpool(_require_active_media_camera, int(camera_id))
        else:
            scoped_source = normalize_camera_source(CAMERA.current_source_identity())
    except (HTTPException, ValueError):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    last_seq = -1
    check_at = 0.0
    try:
        while True:
            if time.monotonic() >= check_at:
                actor = await run_in_threadpool(_websocket_user, websocket)
                if actor is None:
                    await websocket.close(code=4401)
                    return
                await run_in_threadpool(_camera_scope_context, actor, camera_id)
                check_at = time.monotonic() + 1.0
            if normalize_camera_source(CAMERA.current_source_identity()) != scoped_source:
                await websocket.close(code=4409)
                break
            jpeg, seq, _encoded_at = CAMERA.latest_observation_packet()
            if jpeg and seq > 0 and seq != last_seq:
                await websocket.send_bytes(jpeg)
                last_seq = int(seq)
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=3.0)
                except asyncio.TimeoutError:
                    # Do not build a socket/browser playback queue for a stalled tab.
                    break
                if str(message).strip().lower() in {"close", "stop"}:
                    break
                continue
            await asyncio.sleep(0.004)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/api/v1/media/metadata/ws")
async def media_metadata_ws(websocket: WebSocket):
    """ACK-paced tracking metadata for browser-side Canvas overlay.

    Video and AI metadata are deliberately separate. The browser may render video at
    25 FPS while tracking arrives at its own cadence, and neither stream queues stale
    application frames.
    """
    actor = await run_in_threadpool(_websocket_user, websocket)
    if actor is None:
        await websocket.close(code=4401)
        return
    try:
        raw_id = websocket.query_params.get("camera_id")
        camera_id = int(raw_id) if raw_id is not None else None
        scope = await run_in_threadpool(_camera_scope_context, actor, camera_id)
        camera_id = scope.get("camera_id")
    except (ValueError, HTTPException):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    last_signature = None
    check_at = 0.0
    try:
        while True:
            if time.monotonic() >= check_at:
                actor = await run_in_threadpool(_websocket_user, websocket)
                if actor is None:
                    await websocket.close(code=4401)
                    return
                await run_in_threadpool(_camera_scope_context, actor, camera_id)
                check_at = time.monotonic() + 2.0
            payload = await run_in_threadpool(_media_tracking_payload, camera_id)
            enforce_store_scope(actor, payload.get("store_id"))
            signature = (
                round(float(payload.get("updated_at") or 0.0), 4),
                payload.get("camera_id"), payload.get("ai_state"), payload.get("source_epoch"),
                tuple((str(x.get("track_id") or ""), tuple(x.get("bbox") or []), str(x.get("full_name") or "")) for x in payload.get("tracks") or []),
            )
            if signature != last_signature:
                await websocket.send_json(sanitize_payload(payload))
                last_signature = signature
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                except asyncio.TimeoutError:
                    # If a backgrounded browser stops ACKing, do not queue metadata.
                    continue
                if str(message).strip().lower() in {"close", "stop"}:
                    break
                await asyncio.sleep(.1)
                continue
            await asyncio.sleep(.1)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/api/v1/office/status")
def office_status():
    return {**OFFICE.status(), "gpu": gpu_status()}


@app.get("/api/v1/office/latest")
def office_latest():
    return {**OFFICE.latest(), "gpu": gpu_status()}


@app.get("/api/v1/office/config")
def office_config():
    return {"ok": True, "config": OFFICE.config()}


@app.put("/api/v1/office/config")
def office_config_save(payload: OfficeConfigPayload, request: Request):
    actor = _auth_user(request, {"ADMIN", "OPERATOR"})
    values = payload.model_dump()
    line = dict(values.get("line") or {})
    # Bind a production Virtual Gate to the active camera without persisting or
    # exposing the RTSP credential. Switching cameras therefore cannot silently
    # apply an old door line to a different field of view.
    try:
        import hashlib
        runtime = CAMERA.status()
        current_source = normalize_camera_source(str(runtime.get("source") or ""))
        fingerprint = hashlib.sha256(current_source.encode("utf-8", errors="ignore")).hexdigest()[:16] if current_source else ""
        active = None
        for item in list_camera_devices():
            if normalize_camera_source(str(item.get("source") or "")) == current_source:
                active = item
                break
        line["camera_source_fingerprint"] = fingerprint
        line["camera_id"] = int(active.get("id")) if active and active.get("id") is not None else None
        line["camera_name"] = str((active or {}).get("name") or runtime.get("source_label") or "Camera")[:120]
        line["zone_name"] = str((active or {}).get("zone_name") or "")[:120]
        values["line"] = line
    except Exception:
        pass
    cfg = OFFICE.save_config(values)
    try:
        add_audit_event(
            "OFFICE", "VIRTUAL_GATE_CONFIG", "SUCCESS",
            camera_source=CAMERA.event_camera_source(),
            detail={"line": cfg.get("line"), "monitoring_enabled": cfg.get("monitoring_enabled")},
        )
    except Exception:
        pass
    return {"ok": True, "config": cfg}


@app.post("/api/v1/office/start")
def office_start(request: Request):
    _auth_user(request, {"ADMIN", "OPERATOR"})
    OFFICE.set_monitoring(True)
    try:
        add_audit_event("OFFICE", "OFFICE_MONITOR_START", "SUCCESS", camera_source=CAMERA.event_camera_source())
    except Exception:
        pass
    return {"ok": True, "office": OFFICE.status(), "observer": "IDENTITY_ONLY"}


@app.post("/api/v1/office/stop")
def office_stop(request: Request):
    _auth_user(request, {"ADMIN", "OPERATOR"})
    OFFICE.set_monitoring(False)
    try:
        add_audit_event("OFFICE", "OFFICE_MONITOR_STOP", "SUCCESS", camera_source=CAMERA.event_camera_source())
    except Exception:
        pass
    return {"ok": True, "office": OFFICE.status(), "observer": "IDENTITY_ONLY"}


@app.get("/api/v1/office/events")
def office_events(limit: int = 50):
    return {"ok": True, "events": OFFICE.events(limit)}


@app.websocket("/api/v1/office/preview/ws")
async def office_preview_ws(websocket: WebSocket):
    """Newest-frame, ACK-paced office preview with no playback queue.

    This is intentionally separate from AI inference. The browser can render at its
    own pace while the next packet always comes from the newest camera frame.
    """
    if await run_in_threadpool(_websocket_user, websocket) is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    last_seq = -1
    try:
        while True:
            jpeg, seq, _encoded_at = CAMERA.latest_observation_packet()
            if jpeg and seq > 0 and seq != last_seq:
                await websocket.send_bytes(jpeg)
                last_seq = seq
                message = await websocket.receive_text()
                if str(message).strip().lower() in {"close", "stop"}:
                    break
                continue
            await asyncio.sleep(0.006)
    except WebSocketDisconnect:
        pass
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


def _auth_user(request: Request, roles: set[str]) -> dict:
    try:
        token = _request_token(request)
        auth_header = f"Bearer {token}" if token else ""
        return require_role(auth_header, roles)
    except PermissionError as exc:
        raise HTTPException(401 if "đăng nhập" in str(exc).lower() else 403, str(exc))


def _auth_permission(request: Request, permission: str) -> dict:
    try:
        token = _request_token(request)
        auth_header = f"Bearer {token}" if token else ""
        return require_permission(auth_header, permission)
    except PermissionError as exc:
        raise HTTPException(401 if "đăng nhập" in str(exc).lower() else 403, str(exc))


@app.get("/api/v1/auth/status")
def auth_status(request: Request):
    user = _request_user(request)
    return {"setup_required": user_count() == 0, "authenticated": bool(user), "user": user}


@app.post("/api/v1/auth/bootstrap")
def auth_bootstrap_legacy(payload: AuthBootstrapPayload, request: Request, response: Response):
    if str(os.getenv("BTMH_ALLOW_LEGACY_BOOTSTRAP", "0")).strip() != "1":
        raise HTTPException(409, "Hãy dùng quy trình thiết lập Chủ sở hữu lần đầu trên PC quản lý trung tâm.")
    try:
        user = bootstrap_admin(payload.username, payload.display_name, payload.password, payload.phone, "", phone_verified=False)
        result = auth_login(payload.username, payload.password)
        response.set_cookie(AUTH_COOKIE, result["token"], max_age=int(result.get("expires_in") or 28800), httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/")
        add_audit_event("SYSTEM", "SUPER_ADMIN_BOOTSTRAP_LEGACY", "SUCCESS", detail={"username": payload.username})
        return {**result, "created": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/auth/bootstrap-local")
def auth_bootstrap_local(payload: AuthBootstrapPayload, request: Request, response: Response):
    """Create the first owner from loopback without mandatory MFA enrollment."""
    host = str(request.client.host if request.client else "").strip().lower()
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "Thiết lập Chủ sở hữu chỉ được thực hiện trực tiếp trên PC quản lý trung tâm")
    if user_count() > 0:
        raise HTTPException(409, "Hệ thống đã có tài khoản Chủ sở hữu")
    try:
        user = bootstrap_admin(payload.username, payload.display_name, payload.password, "", "", phone_verified=False)
        result = auth_login(payload.username, payload.password)
        add_audit_event(
            "SYSTEM", "OWNER_BOOTSTRAP_LOCAL", "SUCCESS",
            detail={"username": user.get("username"), "client_ip": host, "mfa_setup_required": bool(result.get("mfa_setup_required"))},
        )
        return set_auth_result(response, request, {**result, "created": user, "message": "Da tao Chu so huu."}, AUTH_COOKIE)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/auth/bootstrap/request-otp")
def auth_bootstrap_request_otp(payload: AuthBootstrapOtpRequestPayload):
    if user_count() > 0:
        raise HTTPException(409, "Hệ thống đã có tài khoản quản trị gốc")
    if len(str(payload.username or "").strip()) < 3:
        raise HTTPException(400, "Tên đăng nhập phải có ít nhất 3 ký tự")
    try:
        result = otp_request(purpose="BOOTSTRAP", phone=payload.phone, payload={
            "username": str(payload.username).strip().lower(),
            "display_name": str(payload.display_name or "Quản trị viên").strip(),
            "phone": str(payload.phone).strip(),
            "email": str(payload.email).strip().lower(),
        })
        add_audit_event("SECURITY", "BOOTSTRAP_OTP_REQUESTED", "SUCCESS", detail={"username": str(payload.username)[:120], "phone_tail": str(payload.phone)[-4:]})
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/v1/auth/bootstrap/verify-otp")
def auth_bootstrap_verify_otp(payload: AuthOtpPasswordVerifyPayload, request: Request, response: Response):
    if user_count() > 0:
        raise HTTPException(409, "Hệ thống đã có tài khoản quản trị gốc")
    try:
        verified = otp_verify(challenge_id=payload.challenge_id, otp=payload.otp, purpose="BOOTSTRAP")
        data = verified.get("payload") or {}
        user = bootstrap_admin(data.get("username",""), data.get("display_name","Quản trị viên"), payload.password, data.get("phone",""), data.get("email",""), phone_verified=True)
        result = auth_login(data.get("username",""), payload.password)
        if result.get("token"):
            response.set_cookie(AUTH_COOKIE, result["token"], max_age=int(result.get("expires_in") or 28800), httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/")
        add_audit_event("SYSTEM", "SUPER_ADMIN_BOOTSTRAP", "SUCCESS", detail={"username": user.get("username"), "phone_verified": True, "mfa_required": bool(result.get("mfa_required"))})
        return {**result, "created": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/auth/register")
def auth_register_legacy(payload: AuthRegisterPayload):
    raise HTTPException(409, "Đăng ký V5 yêu cầu xác minh OTP số điện thoại trước khi tạo tài khoản")


@app.post("/api/v1/auth/register/request-otp")
def auth_register_request_otp(payload: AuthRegisterOtpRequestPayload):
    if str(os.getenv("BTMH_PUBLIC_REGISTRATION", "0")).strip() != "1":
        raise HTTPException(403, "Hệ thống không cho phép đăng ký công khai. Tài khoản do Chủ sở hữu hoặc Quản trị viên tạo.")
    if user_count() == 0:
        raise HTTPException(409, "Hãy khởi tạo SUPER_ADMIN trước")
    username = str(payload.username or "").strip().lower()
    email = str(payload.email or "").strip().lower()
    phone = str(payload.phone or "").strip()
    if len(username) < 3 or not str(payload.display_name or "").strip():
        raise HTTPException(400, "Tên đăng nhập và họ tên là bắt buộc")
    if fetchone("SELECT id FROM system_users WHERE username=?", (username,)):
        raise HTTPException(409, "Tên đăng nhập đã tồn tại")
    if email and fetchone("SELECT user_id FROM account_profiles WHERE LOWER(email)=?", (email,)):
        raise HTTPException(409, "Email đã được đăng ký")
    phone_cmp = phone.replace(" ","").replace("-","").replace(".","")
    if phone_cmp.startswith("+84"):
        phone_cmp = "0" + phone_cmp[3:]
    if fetchone("SELECT user_id FROM account_profiles WHERE phone=?", (phone_cmp,)):
        raise HTTPException(409, "Số điện thoại đã được đăng ký")
    try:
        result = otp_request(purpose="REGISTER", phone=phone, payload={
            "username": username, "display_name": str(payload.display_name).strip(), "phone": phone, "email": email,
        })
        add_audit_event("SECURITY", "REGISTER_OTP_REQUESTED", "SUCCESS", detail={"username": username, "phone_tail": phone[-4:]})
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/v1/auth/register/verify-otp")
def auth_register_verify_otp(payload: AuthOtpPasswordVerifyPayload):
    if str(os.getenv("BTMH_PUBLIC_REGISTRATION", "0")).strip() != "1":
        raise HTTPException(403, "Hệ thống không cho phép đăng ký công khai. Tài khoản do Chủ sở hữu hoặc Quản trị viên tạo.")
    if user_count() == 0:
        raise HTTPException(409, "Hãy khởi tạo SUPER_ADMIN trước")
    try:
        verified = otp_verify(challenge_id=payload.challenge_id, otp=payload.otp, purpose="REGISTER")
        data = verified.get("payload") or {}
        user = register_public_user(data.get("username",""), data.get("display_name",""), data.get("phone",""), payload.password, data.get("email",""))
        add_audit_event("SECURITY", "SELF_REGISTER_PENDING", "SUCCESS", detail={"username": user.get("username"), "role": user.get("role"), "status": "PENDING"})
        return {"ok": True, "status": "PENDING", "message": "Đăng ký thành công. Tài khoản đang chờ quản trị viên phê duyệt.", "user": user}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/auth/forgot/request-otp")
def auth_forgot_request_otp(payload: AuthForgotRequestPayload):
    ident = str(payload.identifier or "").strip().lower()
    phone_cmp = ident.replace(" ","").replace("-","").replace(".","")
    if phone_cmp.startswith("+84"):
        phone_cmp = "0" + phone_cmp[3:]
    row = fetchone(
        """SELECT u.id,u.username,u.active,p.phone,p.email,p.account_status,p.phone_verified
           FROM system_users u LEFT JOIN account_profiles p ON p.user_id=u.id
           WHERE LOWER(u.username)=? OR LOWER(COALESCE(p.email,''))=? OR COALESCE(p.phone,'')=? LIMIT 1""",
        (ident, ident, phone_cmp),
    )
    # Avoid exposing whether an arbitrary username/email exists. The UI receives a
    # generic message when lookup cannot be completed.
    if not row or not row.get("phone") or not bool(row.get("phone_verified",0)):
        return {"ok": True, "message": "Nếu tài khoản hợp lệ, mã OTP sẽ được gửi tới số điện thoại đã xác minh."}
    try:
        result = otp_request(purpose="PASSWORD_RESET", phone=str(row.get("phone")), payload={"user_id": int(row.get("id")), "username": str(row.get("username"))})
        add_audit_event("SECURITY", "PASSWORD_RESET_OTP_REQUESTED", "SUCCESS", detail={"username": row.get("username"), "phone_tail": str(row.get("phone"))[-4:]})
        return {**result, "ok": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/v1/auth/forgot/verify-otp")
def auth_forgot_verify_otp(payload: AuthForgotVerifyPayload):
    try:
        verified = otp_verify(challenge_id=payload.challenge_id, otp=payload.otp, purpose="PASSWORD_RESET")
        data = verified.get("payload") or {}
        user = change_password_by_verified_phone(str(data.get("username") or ""), payload.password)
        add_audit_event("SECURITY", "PASSWORD_RESET", "SUCCESS", detail={"username": user.get("username"), "sessions_revoked": True})
        return {"ok": True, "message": "Mật khẩu đã được thay đổi. Các phiên đăng nhập cũ đã bị thu hồi."}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/auth/login")
def auth_login_endpoint(payload: AuthLoginPayload, request: Request, response: Response):
    client_ip = str(request.client.host if request.client else "local")
    binding = secrets.token_urlsafe(32)
    try:
        result = auth_login(payload.username, payload.password,
            trusted_cookie=request.cookies.get(sms_security.TRUST_COOKIE, ""),
            binding=binding, allow_trust=secure_transport(request))
        if result.get("token"):
            add_audit_event("SECURITY", "LOGIN_SUCCESS", "SUCCESS", detail={"user_id": result["user"]["id"], "trusted_browser": bool(result.get("trusted_browser"))})
            return set_auth_result(response, request, result, AUTH_COOKIE)
        auth_logout(_request_token(request))
        response.delete_cookie(AUTH_COOKIE, path="/")
        set_pending(response, binding, request)
        add_audit_event("SECURITY", "LOGIN_SECOND_FACTOR_REQUIRED", "SUCCESS", detail={"method": result.get("mfa_method")})
        return result
    except ValueError as exc:
        lock = login_lock_status(payload.username)
        add_audit_event("SECURITY", "LOGIN_FAILED", "FAILED", detail={"client_ip": client_ip})
        raise HTTPException(429 if lock.get("locked") else 401, str(exc))


@app.post("/api/v1/auth/2fa/request-otp")
def auth_second_factor_request(payload: AuthSecondFactorRequestPayload):
    try:
        destination = privileged_login_otp_destination(payload.login_challenge_id, payload.method)
        result = otp_request_delivery(
            purpose="ADMIN_LOGIN",
            channel=str(destination.get("method") or payload.method),
            destination=str(destination.get("destination") or ""),
            payload={
                "user_id": int(destination.get("user_id") or 0),
                "login_challenge_id": str(payload.login_challenge_id or ""),
                "method": str(destination.get("method") or payload.method).upper(),
            },
        )
        add_audit_event(
            "SECURITY", "ADMIN_LOGIN_OTP_REQUESTED", "SUCCESS",
            detail={"username": (destination.get("user") or {}).get("username"), "method": destination.get("method"), "destination": result.get("destination_hint")},
        )
        return {**result, "otp_challenge_id": result.get("challenge_id")}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/v1/auth/2fa/verify")
def auth_second_factor_verify(payload: AuthSecondFactorVerifyPayload, request: Request, response: Response):
    client_ip = str(request.client.host if request.client else "local")
    try:
        verified = otp_verify(challenge_id=payload.otp_challenge_id, otp=payload.otp, purpose="ADMIN_LOGIN")
        data = verified.get("payload") or {}
        if str(data.get("login_challenge_id") or "") != str(payload.login_challenge_id or ""):
            raise ValueError("OTP không thuộc phiên đăng nhập hiện tại")
        user_id = int(data.get("user_id") or 0)
        result = complete_privileged_login_challenge(payload.login_challenge_id, user_id)
        response.set_cookie(AUTH_COOKIE, result["token"], max_age=int(result.get("expires_in") or 28800), httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/")
        add_audit_event("SECURITY", "LOGIN_2FA_VERIFIED", "SUCCESS", detail={"username": result.get("user", {}).get("username"), "client_ip": client_ip, "method": verified.get("channel")})
        add_audit_event("SECURITY", "LOGIN_SUCCESS", "SUCCESS", detail={"username": result.get("user", {}).get("username"), "client_ip": client_ip, "mfa": True, "method": verified.get("channel")})
        return result
    except ValueError as exc:
        add_audit_event("SECURITY", "LOGIN_2FA_VERIFY_FAILED", "FAILED", detail={"client_ip": client_ip})
        raise HTTPException(401, str(exc))


@app.get("/api/v1/auth/admin-security")
def auth_admin_security_status(request: Request):
    actor = _auth_user(request, {"ADMIN"})
    role = str(actor.get("role") or "").upper()
    if role not in {"SUPER_ADMIN", "ADMIN"}:
        raise HTTPException(403, "Chỉ ADMIN/SUPER_ADMIN có hồ sơ bảo mật quản trị")
    out = {
        "ok": True,
        "security": privileged_security_status(int(actor.get("id") or 0), role),
        "user": actor,
        "delivery": otp_delivery_status(),
    }
    if role == "SUPER_ADMIN":
        out["provider_config"] = otp_delivery_config_public()
    return out


@app.put("/api/v1/auth/admin-security/otp-provider")
def auth_admin_security_save_otp_provider(payload: OtpDeliveryConfigPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    if str(actor.get("role") or "").upper() != "SUPER_ADMIN":
        raise HTTPException(403, "Chỉ SUPER_ADMIN được thay đổi nhà cung cấp OTP toàn hệ thống")
    try:
        config = otp_save_delivery_config({"sms": payload.sms, "email": payload.email})
        status = otp_delivery_status()
        add_audit_event(
            "SECURITY", "OTP_PROVIDER_CONFIG_UPDATED", "SUCCESS",
            detail={
                "actor": actor.get("username"),
                "sms_provider": config.get("sms", {}).get("provider"),
                "email_provider": config.get("email", {}).get("provider"),
                "sms_real": status.get("sms", {}).get("real_delivery"),
                "email_real": status.get("email", {}).get("real_delivery"),
            },
        )
        return {"ok": True, "provider_config": config, "delivery": status}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        add_audit_event("SECURITY", "OTP_PROVIDER_CONFIG_UPDATED", "FAILED", detail={"actor": actor.get("username"), "error": str(exc)[:180]})
        raise HTTPException(500, f"Không lưu được cấu hình OTP: {exc}")


@app.post("/api/v1/auth/admin-security/otp-provider/test")
def auth_admin_security_test_otp_provider(payload: OtpDeliveryTestPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    if str(actor.get("role") or "").upper() != "SUPER_ADMIN":
        raise HTTPException(403, "Chỉ SUPER_ADMIN được test nhà cung cấp OTP")
    method = str(payload.method or "").strip().upper()
    if method not in {"SMS", "EMAIL"}:
        raise HTTPException(400, "Chỉ hỗ trợ test SMS hoặc Email")
    try:
        result = otp_request_delivery(
            purpose="OTP_PROVIDER_TEST",
            channel=method,
            destination=payload.destination,
            payload={"actor_user_id": int(actor.get("id") or 0), "provider_test": True},
        )
        add_audit_event("SECURITY", "OTP_PROVIDER_TEST", "SUCCESS", detail={"actor": actor.get("username"), "method": method, "destination": result.get("destination_hint"), "provider": result.get("provider")})
        return {**result, "ok": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        add_audit_event("SECURITY", "OTP_PROVIDER_TEST", "FAILED", detail={"actor": actor.get("username"), "method": method, "error": str(exc)[:180]})
        raise HTTPException(503, str(exc))
    except Exception as exc:
        add_audit_event("SECURITY", "OTP_PROVIDER_TEST", "FAILED", detail={"actor": actor.get("username"), "method": method, "error": str(exc)[:180]})
        raise HTTPException(502, f"Nhà cung cấp OTP không phản hồi: {exc}")


@app.post("/api/v1/auth/admin-security/request-otp")
def auth_admin_security_request_otp(payload: AdminSecurityOtpRequestPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    role = str(actor.get("role") or "").upper()
    if role not in {"SUPER_ADMIN", "ADMIN"}:
        raise HTTPException(403, "Chỉ ADMIN/SUPER_ADMIN được thiết lập xác thực hai lớp")
    method = str(payload.method or "").strip().upper()
    if method not in {"SMS", "EMAIL"}:
        raise HTTPException(400, "Chỉ hỗ trợ OTP qua SMS hoặc Email")
    try:
        result = otp_request_delivery(
            purpose="ADMIN_SECURITY_SETUP",
            channel=method,
            destination=payload.destination,
            payload={
                "user_id": int(actor.get("id") or 0),
                "method": method,
                "destination": str(payload.destination or "").strip(),
                "display_name": str(payload.display_name or actor.get("display_name") or "").strip(),
            },
        )
        add_audit_event("SECURITY", "ADMIN_SECURITY_CONTACT_OTP_REQUESTED", "SUCCESS", detail={"actor": actor.get("username"), "method": method, "destination": result.get("destination_hint")})
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@app.post("/api/v1/auth/admin-security/verify-otp")
def auth_admin_security_verify_otp(payload: AdminSecurityOtpVerifyPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    role = str(actor.get("role") or "").upper()
    if role not in {"SUPER_ADMIN", "ADMIN"}:
        raise HTTPException(403, "Chỉ ADMIN/SUPER_ADMIN được thiết lập xác thực hai lớp")
    try:
        verified = otp_verify(challenge_id=payload.challenge_id, otp=payload.otp, purpose="ADMIN_SECURITY_SETUP")
        data = verified.get("payload") or {}
        if int(data.get("user_id") or 0) != int(actor.get("id") or 0):
            raise ValueError("OTP không thuộc tài khoản đang đăng nhập")
        security = verify_privileged_security_contact(
            int(actor.get("id") or 0),
            method=str(data.get("method") or verified.get("channel") or ""),
            destination=str(data.get("destination") or ""),
            display_name=str(data.get("display_name") or ""),
        )
        fresh_user = next((u for u in list_users() if int(u.get("id") or 0) == int(actor.get("id") or 0)), actor)
        add_audit_event("SECURITY", "ADMIN_SECURITY_CONTACT_VERIFIED", "SUCCESS", detail={"actor": actor.get("username"), "method": data.get("method"), "destination": verified.get("destination_hint"), "two_factor_enabled": bool(security.get("setup_completed"))})
        return {"ok": True, "security": security, "user": fresh_user, "message": "Đã xác minh. Từ lần đăng nhập tiếp theo tài khoản quản trị sẽ yêu cầu OTP bước 2."}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/v1/auth/mfa/verify")
def auth_mfa_verify(payload: AuthMfaVerifyPayload, request: Request, response: Response):
    try:
        result = complete_mfa_challenge(payload.challenge_id, payload.code,
            binding=request.cookies.get(sms_security.PENDING_COOKIE, ""))
        add_audit_event("SECURITY", "MFA_VERIFIED", "SUCCESS", detail={"user_id": result["user"]["id"]})
        return set_auth_result(response, request, result, AUTH_COOKIE, payload.trust_browser)
    except ValueError as exc:
        add_audit_event("SECURITY", "MFA_VERIFY_FAILED", "FAILED", detail={})
        raise HTTPException(401, str(exc))


@app.post("/api/v1/auth/logout")
def auth_logout_endpoint(request: Request, response: Response):
    token = _request_token(request)
    user = user_for_token(token)
    auth_logout(token)
    response.delete_cookie(AUTH_COOKIE, path="/")
    if user:
        add_audit_event("SECURITY", "LOGOUT", "SUCCESS", detail={"username": user.get("username"), "client_ip": str(request.client.host if request.client else "local")})
    return {"ok": True}


def _account_http_error(exc: AccountError):
    return HTTPException(exc.status, {"message": str(exc), "code": exc.code, "field": exc.field})


@app.get("/api/v1/auth/profile")
def auth_profile_get(request: Request):
    try:
        return get_self_profile(_request_token(request))
    except AccountError as exc:
        raise _account_http_error(exc) from None


@app.put("/api/v1/auth/profile")
def auth_profile_update(payload: SelfProfilePayload, request: Request):
    try:
        out = update_self_profile(_request_token(request), display_name=payload.display_name)
    except AccountError as exc:
        raise _account_http_error(exc) from None
    add_audit_event("SECURITY", "SELF_PROFILE_UPDATED", "SUCCESS", detail={"user_id": out["user"]["id"], "fields": ["display_name"]})
    return out


@app.put("/api/v1/auth/password")
def auth_password_update(payload: SelfPasswordPayload, request: Request, response: Response):
    try:
        out = change_self_password(_request_token(request), current_password=payload.current_password,
                                   new_password=payload.new_password, confirm_password=payload.confirm_password)
    except AccountError as exc:
        raise _account_http_error(exc) from None
    for cookie in (AUTH_COOKIE, sms_security.TRUST_COOKIE, sms_security.PENDING_COOKIE):
        response.delete_cookie(cookie, path="/")
    add_audit_event("SECURITY", "SELF_PASSWORD_CHANGED", "SUCCESS", detail={"sessions_revoked": True})
    return out


def _mobile_lan_urls() -> list[str]:
    candidates: list[str] = []
    preferred = ""
    # Prefer the interface Windows/Linux would route general LAN/Internet traffic over.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.1)
        sock.connect(("8.8.8.8", 80))
        preferred = str(sock.getsockname()[0] or "")
        sock.close()
    except Exception:
        preferred = ""
    try:
        candidates.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    ordered: list[str] = []
    for ip in ([preferred] if preferred else []) + candidates:
        ip = str(ip or "").strip()
        if not ip or ip.startswith(("127.", "169.254.")) or ":" in ip or ip in ordered:
            continue
        ordered.append(ip)
    return [f"http://{ip}:{int(PORT)}/mobile" for ip in ordered]


@app.get("/api/v1/admin/mobile-access")
def admin_mobile_access(request: Request):
    _auth_user(request, {"ADMIN"})
    urls = _mobile_lan_urls()
    return {**mobile_viewer_status(), "url": "/mobile", "lan_urls": urls, "preferred_url": (urls[0] if urls else f"http://IP-MAY-CHU:{int(PORT)}/mobile")}


@app.put("/api/v1/admin/mobile-access")
def admin_mobile_access_update(payload: MobileViewerConfigPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    try:
        status = configure_mobile_viewer(enabled=bool(payload.enabled), password=str(payload.password or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "MOBILE_VIEWER_CONFIG_UPDATED", "SUCCESS", detail={"actor": actor.get("username"), "enabled": status.get("enabled"), "password_changed": bool(payload.password)})
    urls = _mobile_lan_urls()
    return {**status, "url": "/mobile", "lan_urls": urls, "preferred_url": (urls[0] if urls else f"http://IP-MAY-CHU:{int(PORT)}/mobile")}


@app.get("/api/v1/mobile/auth/status")
def mobile_auth_status(request: Request):
    status = mobile_viewer_status()
    viewer = _request_mobile_user(request)
    return {**status, "authenticated": bool(viewer), "viewer": viewer}


@app.post("/api/v1/mobile/auth/login")
def mobile_auth_login(payload: MobileViewerLoginPayload, request: Request, response: Response):
    client_ip = str(request.client.host if request.client else "local")
    try:
        result = mobile_login(payload.password)
        response.set_cookie(MOBILE_COOKIE, result["token"], max_age=int(result.get("expires_in") or 86400), httponly=True, samesite="strict", secure=False, path="/")
        add_audit_event("SECURITY", "MOBILE_VIEWER_LOGIN", "SUCCESS", detail={"client_ip": client_ip})
        return {"ok": True, "expires_in": result.get("expires_in"), "viewer": result.get("viewer")}
    except ValueError as exc:
        lock = mobile_login_lock_status()
        add_audit_event("SECURITY", "MOBILE_VIEWER_LOGIN_FAILED", "FAILED", detail={"client_ip": client_ip, "locked": bool(lock.get("locked")), "retry_after": int(lock.get("retry_after") or 0)})
        raise HTTPException(429 if lock.get("locked") else 401, str(exc))


@app.post("/api/v1/mobile/auth/logout")
def mobile_auth_logout(request: Request, response: Response):
    mobile_logout(_request_mobile_token(request))
    response.delete_cookie(MOBILE_COOKIE, path="/")
    return {"ok": True}


def _mobile_summary_payload() -> dict:
    base = _legacy_dashboard_summary()
    hr = hr_history_feed(60)
    cam = base.get("camera") or {}
    return {
        "employees": int((base.get("students") or {}).get("total") or 0),
        "faceid_enrolled": int((base.get("students") or {}).get("faceid") or 0),
        "present": int((hr.get("summary") or {}).get("currently_present") or 0),
        "camera": {
            "online": bool(cam.get("opened")) and str(cam.get("state") or "").lower() == "online",
            "label": str(cam.get("source_label") or "Camera văn phòng"),
        },
        "pending_review": int((base.get("operations") or {}).get("pending_exceptions") or 0),
        "generated_at": utc_now(),
    }


@app.get("/api/v1/mobile/summary")
def mobile_summary():
    return _mobile_summary_payload()


@app.get("/api/v1/mobile/presence")
def mobile_presence():
    rows = hr_current_presence()
    return {"items": [{
        "student_id": r.get("student_id"), "employee_code": r.get("student_code") or "",
        "full_name": r.get("full_name") or "Chưa xác định", "department": r.get("faculty") or "",
        "group": r.get("class_name") or "", "started_at": r.get("started_at"),
        "last_seen_at": r.get("last_seen_at"), "status": "PRESENT",
    } for r in rows], "generated_at": utc_now()}


@app.get("/api/v1/mobile/history/recognition")
def mobile_recognition_history(request: Request, limit: int = 80):
    if not _request_mobile_user(request):
        raise HTTPException(401, "Cần đăng nhập Mobile Viewer")
    # Keep the existing Viewer read scope; never grant it portal/approval rights.
    # The desktop route now has portal auth and cannot be called as a builder.
    end = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    data = query_recognition_history(end - timedelta(days=365), end, limit=max(20, min(200, int(limit))))
    items = []
    for x in data.get("items") or []:
        public = _recognition_public_row(x)
        result = public.get("result") or public.get("status") or ""
        items.append({
            "event_at": public.get("event_at"), "full_name": public.get("full_name") or "Chưa xác định",
            "employee_code": public.get("student_code") or "", "event_type": result,
            "status": {"RECOGNIZED": "SUCCESS", "SPOOF_BLOCKED": "FAILED", "UNREGISTERED": "WARNING"}.get(result, "WARNING"),
            "confidence": float(x.get("confidence") or 0), "repeat_count": 1,
        })
    return {"items": items, "generated_at": data.get("generated_at") or utc_now()}


@app.get("/api/v1/mobile/history/hr")
def mobile_hr_history(request: Request, limit: int = 80):
    if not _request_mobile_user(request):
        raise HTTPException(401, "Cần đăng nhập Mobile Viewer")
    items = []
    for x in hr_event_history(max(20, min(200, int(limit)))):
        event_type = str(x.get("event_type") or "").upper()
        if event_type not in {"PRESENCE_START", "PRESENCE_END", "ENTRY", "RETURN", "EXIT"}:
            continue
        if event_type == "PRESENCE_END" and str((x.get("detail") or {}).get("reason") or "").upper() == "CAMERA_NOT_VISIBLE":
            continue
        items.append({
            "event_at": x.get("event_at"), "full_name": _safe_name(x.get("full_name")) or "Chưa xác định",
            "employee_code": _safe_name(x.get("student_code")), "event_type": event_type,
            "status": x.get("status") or "", "action": x.get("action") or "", "reason": "",
        })
    return {"items": items, "generated_at": utc_now()}


@app.get("/api/v1/mobile/cameras")
def mobile_cameras():
    runtime = CAMERA.status()
    active = normalize_camera_source(str(runtime.get("source") or "0"))
    items = []
    for row in list_camera_devices():
        source = normalize_camera_source(str(row.get("source") or ""))
        is_active = source == active
        items.append({
            "id": row.get("id"), "name": row.get("name") or "Camera", "zone": row.get("zone_name") or "",
            "active": is_active, "status": ("ONLINE" if is_active and runtime.get("opened") and str(runtime.get("state") or "").lower()=="online" else "STANDBY"),
        })
    return {"items": items, "generated_at": utc_now()}


@app.get("/api/v1/mobile/camera/stream.mjpg")
def mobile_camera_stream(request: Request):
    async def gen():
        while True:
            if await request.is_disconnected():
                break
            jpeg = CAMERA.latest_observation_jpeg() or CAMERA.latest_jpeg()
            if jpeg:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            # Mobile view is deliberately capped near 10 FPS to keep the UI responsive
            # and avoid consuming workstation/phone bandwidth needed by AI processing.
            await asyncio.sleep(0.10)
    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache","X-Accel-Buffering":"no"})


@app.get("/api/v1/admin/roles")
def admin_roles(request: Request):
    _auth_permission(request, "account.approve")
    return {"items": role_catalog(), "mode": "RBAC"}


@app.get("/api/v1/admin/users")
def admin_users(request: Request):
    _auth_permission(request, "account.approve")
    return {"items": list_users(), "mode": "RBAC"}


@app.post("/api/v1/admin/users")
def admin_create_user(payload: UserCreatePayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    try:
        user = provision_account(actor, _request_token(request), username=payload.username, display_name=payload.display_name,
            role=payload.role, password=payload.password, confirm_password=payload.confirm_password,
            phone=payload.phone, email=payload.email, store_id=payload.store_id)
    except AccountError as exc:
        raise _account_http_error(exc) from None
    add_audit_event("SECURITY", "USER_CREATED", "SUCCESS", detail={"actor": actor.get("username"), "username": user.get("username"), "role": user.get("role")})
    return {"ok": True, "user": user}


@app.put("/api/v1/admin/users/{user_id}")
def admin_update_user(user_id: int, payload: UserUpdatePayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    try:
        user = update_user(user_id, role=payload.role, active=payload.active, display_name=payload.display_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "USER_UPDATED", "SUCCESS", detail={"actor": actor.get("username"), "user_id": int(user_id), "role": user.get("role"), "active": user.get("active")})
    return {"ok": True, "user": user}


@app.post("/api/v1/admin/users/{user_id}/approve")
def admin_approve_user(user_id: int, payload: AccountApprovalPayload, request: Request):
    actor = _auth_permission(request, "account.approve")
    actor_role = str(actor.get("role") or "").upper()
    requested = str(payload.role or "EMPLOYEE").upper()
    if actor_role == "MANAGER" and requested != "EMPLOYEE":
        raise HTTPException(403, "Quản lý cửa hàng chỉ được duyệt tài khoản nhân viên")
    if actor_role not in {"SUPER_ADMIN", "ADMIN", "MANAGER"}:
        raise HTTPException(403, "Tài khoản không có quyền phê duyệt")
    try:
        user = approve_user(user_id, role=requested, store_id=payload.store_id, actor=str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "ACCOUNT_APPROVED", "SUCCESS", detail={"actor": actor.get("username"), "user_id": int(user_id), "role": requested, "store_id": payload.store_id})
    return {"ok": True, "user": user}


@app.post("/api/v1/admin/users/{user_id}/mfa/reset")
def admin_reset_user_mfa(user_id: int, request: Request):
    actor = _auth_permission(request, "system.manage")
    target = next((item for item in list_users() if int(item.get("id") or 0) == int(user_id)), None)
    if not target:
        raise HTTPException(404, "Không tìm thấy tài khoản")
    if str(target.get("role") or "").upper() == "SUPER_ADMIN" and str(actor.get("role") or "").upper() != "SUPER_ADMIN":
        raise HTTPException(403, "Chỉ SUPER_ADMIN được đặt lại MFA của SUPER_ADMIN")
    try:
        user = reset_user_mfa(user_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "MFA_RESET", "SUCCESS", detail={"actor": actor.get("username"), "user_id": int(user_id), "username": user.get("username")})
    return {"ok": True, "user": user, "message": "Đã đặt lại ứng dụng xác thực. Tài khoản quản trị sẽ thiết lập lại Authenticator ở lần đăng nhập kế tiếp."}


@app.put("/api/v1/admin/users/{user_id}/password")
def admin_reset_user_password(user_id: int, payload: UserPasswordPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    try:
        user = reset_user_password(user_id, payload.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "USER_PASSWORD_RESET", "SUCCESS", detail={"actor": actor.get("username"), "user_id": int(user_id), "username": user.get("username")})
    return {"ok": True}


@app.get("/api/v1/visitors")
def visitors_list(request: Request, status: str = "", limit: int = 100):
    actor = _auth_permission(request, "visitor.view")
    # Legacy observations have no immutable store attribution. Never guess it
    # from today's camera mapping or expose global rows to a scoped account.
    if scoped_store_ids(actor) is not None:
        return {"items": [], "coverage": "LEGACY_UNATTRIBUTED"}
    return {"items": [_public_visitor_observation(row) for row in visitor_sessions(status=status, limit=limit)],
            "coverage": "OBSERVATIONS_ONLY"}


def _public_visitor_observation(row):
    fields = ("session_code", "status", "visitor_type", "entry_at", "last_seen_at", "exit_at", "duration_sec")
    result = {key: row.get(key) for key in fields}
    result["label"] = _safe_name(row.get("label"))
    source = str(row.get("camera_source") or "")
    result["camera_name"] = _safe_name(source) if not re.search(r"(?i)(?:rtsps?|https?)://|\b(?:\d{1,3}\.){3}\d{1,3}\b", source) else ""
    result["measure"] = "OBSERVATION_SESSION"
    result["best_shots"] = []
    code = str(row.get("session_code") or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,96}", code):
        for shot in (row.get("best_shots") or [])[:3]:
            rank = int(shot.get("rank") or 0)
            if 1 <= rank <= 3:
                result["best_shots"].append({"snapshot_url": f"/api/v1/visitors/{code}/shots/{rank}.jpg",
                                             "captured_at": shot.get("captured_at"), "quality": shot.get("quality")})
    return result


def _legacy_visitor_scope(request, permission):
    actor = _auth_permission(request, permission)
    if scoped_store_ids(actor) is not None:
        raise HTTPException(403, "Quan sát cũ chưa có nguồn cửa hàng để xác nhận phạm vi truy cập.")
    return actor


@app.get("/api/v1/visitors/{session_code}")
def visitors_detail(session_code: str, request: Request):
    _legacy_visitor_scope(request, "visitor.view")
    item = visitor_session(session_code)
    if not item:
        raise HTTPException(404, "Không tìm thấy lượt khách")
    return _public_visitor_observation(item)


@app.put("/api/v1/visitors/{session_code}/review")
def visitors_review(session_code: str, payload: VisitorReviewPayload, request: Request):
    actor = _legacy_visitor_scope(request, "visitor.review")
    try:
        item = review_visitor_session(session_code, visitor_type=payload.visitor_type, label=payload.label, note=payload.note, actor=str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("VISITOR", "VISITOR_REVIEWED", "SUCCESS", detail={"actor": actor.get("username"), "session_code": session_code, "visitor_type": item.get("visitor_type")})
    return {"ok": True, "item": _public_visitor_observation(item)}


@app.get("/api/v1/visitors/{session_code}/shots/{rank}.jpg")
def visitors_shot(session_code: str, rank: int, request: Request):
    _legacy_visitor_scope(request, "visitor.view")
    path = visitor_shot_path(session_code, rank)
    if path is None:
        raise HTTPException(404, "Không tìm thấy ảnh")
    return FileResponse(path, media_type="image/jpeg", filename=f"{session_code}_{int(rank)}.jpg")



@app.get("/api/v1/recordings/status")
def recordings_status(request: Request):
    try:
        token = _request_token(request)
        require_permission(f"Bearer {token}" if token else "", "camera.playback")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    out = recording_archive_status()
    out["runtime"] = RECORDER_V4.status()
    out["mode"] = "LOCAL_FFMPEG_OR_NVR_INDEX"
    out["note"] = "V4 records Hikvision/IP RTSP into 5-minute MP4 segments when the local FFmpeg runtime is available; NVR indexing remains supported."
    return out


@app.get("/api/v1/recordings/segments")
def recordings_segments_endpoint(request: Request, camera_source: str = "", start_at: str = "", end_at: str = "", limit: int = 200):
    try:
        token = _request_token(request)
        require_permission(f"Bearer {token}" if token else "", "camera.playback")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"items": recording_segments(camera_source=camera_source, start_at=start_at, end_at=end_at, limit=limit)}


@app.get("/api/v1/events/{event_id}/video")
def event_video_window(event_id: int, request: Request, pre_seconds: int = 10, post_seconds: int = 10):
    try:
        token = _request_token(request)
        require_permission(f"Bearer {token}" if token else "", "camera.playback")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    row = fetchone("SELECT id,camera_source,event_at FROM recognition_events WHERE id=?", (int(event_id),))
    if not row:
        raise HTTPException(404, "Không tìm thấy sự kiện nhận diện")
    return resolve_event_video(camera_source=str(row.get("camera_source") or ""), event_at=str(row.get("event_at") or ""), pre_seconds=pre_seconds, post_seconds=post_seconds)


@app.get("/api/v1/hr-report/shift")
def hr_report_shift_get(request: Request):
    _auth_permission(request, "hr.report")
    return shift_policy()


@app.put("/api/v1/hr-report/shift")
def hr_report_shift_update(payload: HrShiftPolicyPayload, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    result = save_shift_policy(payload.model_dump())
    add_audit_event("HR", "SHIFT_POLICY_UPDATED", "SUCCESS", detail={"actor": actor.get("username"), **result})
    return {"ok": True, "policy": result}


def _history_date_range(start_date: str = "", end_date: str = "") -> tuple[date, date]:
    today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    try:
        start = date.fromisoformat(start_date) if start_date else today
        end = date.fromisoformat(end_date) if end_date else start
    except ValueError:
        raise HTTPException(400, "Ngày cần có định dạng YYYY-MM-DD") from None
    if end < start or (end - start).days > 365:
        raise HTTPException(400, "Chọn khoảng ngày hợp lệ, tối đa 366 ngày mỗi truy vấn")
    return start, end


def _recognition_history_page(actor: dict, start_date: str = "", end_date: str = "", *,
                              store_id: int | None = None, zone_name: str = "", camera_id: int | None = None,
                              employee_id: int | None = None, subject_type: str = "", result: str = "",
                              search: str = "", limit: int = 100, offset: int = 0, before_id: int | None = None):
    start, end = _history_date_range(start_date, end_date)
    try:
        page = query_recognition_history(start, end, allowed_store_ids=scoped_store_ids(actor),
            store_id=store_id, zone_name=zone_name, camera_id=camera_id, employee_id=employee_id,
            subject_type=subject_type, result=result, search=search, limit=limit, offset=offset, before_id=before_id)
    except PermissionError:
        raise HTTPException(403, "Cửa hàng không thuộc phạm vi được cấp quyền") from None
    except ValueError as exc:
        raise HTTPException(400, "Bộ lọc chưa hợp lệ. Kiểm tra ngày, camera, đối tượng và kết quả rồi thử lại.") from None
    evidence = has_permission(actor, "evidence.view")
    return {**page, "items": [_recognition_public_row(row, evidence_allowed=evidence) for row in page["items"]],
            "start_date": start.isoformat(), "end_date": end.isoformat()}


@app.get("/api/v1/history/recognition")
def recognition_history_feed(request: Request, start_date: str = "", end_date: str = "", store_id: int | None = None,
                             zone_name: str = "", camera_id: int | None = None, employee_id: int | None = None,
                             subject_type: str = "", result: str = "", search: str = "", limit: int = 100, offset: int = 0):
    actor = _auth_permission(request, "history.view")
    return _recognition_history_page(actor, start_date, end_date, store_id=store_id, zone_name=zone_name,
        camera_id=camera_id, employee_id=employee_id, subject_type=subject_type, result=result,
        search=search, limit=limit, offset=offset)


@app.get("/api/v1/history/filters")
def history_filter_options(request: Request):
    actor = _auth_permission(request, "history.view")
    return recognition_filter_options(actor)


def _csv_response(rows, columns, filename: str):
    def safe(value):
        value = "" if value is None else str(value)
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    def generate():
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        yield "\ufeff"
        writer.writerow([label for _key, label in columns])
        yield buffer.getvalue()
        buffer.seek(0); buffer.truncate(0)
        for row in rows:
            writer.writerow([safe(row.get(key)) for key, _label in columns])
            yield buffer.getvalue()
            buffer.seek(0); buffer.truncate(0)
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.get("/api/v1/history/recognition/export.csv")
def recognition_history_csv(request: Request, start_date: str = "", end_date: str = "", store_id: int | None = None,
                             zone_name: str = "", camera_id: int | None = None, employee_id: int | None = None,
                             subject_type: str = "", result: str = "", search: str = ""):
    actor = _auth_permission(request, "history.view")
    filters = dict(store_id=store_id, zone_name=zone_name, camera_id=camera_id, employee_id=employee_id,
                   subject_type=subject_type, result=result, search=search)
    first = _recognition_history_page(actor, start_date, end_date, limit=200, **filters)
    def rows():
        page = first
        while page["items"]:
            yield from page["items"]
            if len(page["items"]) < 200:
                break
            page = _recognition_history_page(actor, start_date, end_date,
                before_id=min(row["event_id"] for row in page["items"]), limit=200, **filters)
    return _csv_response(rows(), [("event_id", "Event ID"), ("business_date", "Ngày camera"),
        ("daily_sequence", "Sequence"), ("occurred_at", "Thời gian UTC"), ("store_name", "Cửa hàng"),
        ("zone_name", "Khu vực"), ("camera_name", "Camera"), ("subject_type", "Đối tượng"),
        ("full_name", "Tên"), ("faceid_status", "FaceID"), ("pad_status", "PAD"), ("status", "Trạng thái")],
        "BTMH_Recognition.csv")


def _attendance_filtered_report(actor: dict, start_date: str = "", end_date: str = "", *,
                                store_id: int | None = None, employee_id: int | None = None,
                                department: str = "", result: str = ""):
    if store_id is not None:
        _require_store_scope(actor, store_id)
    start, end = _history_date_range(start_date, end_date)
    report = build_shift_attendance_report(start, end, allowed_store_ids=scoped_store_ids(actor), store_id=store_id)
    rows = report.get("rows") or []
    if employee_id is not None:
        rows = [row for row in rows if int(row.get("employee_id") or row.get("student_id") or 0) == employee_id]
    if department:
        rows = [row for row in rows if str(row.get("department") or "") == department]
    if result:
        rows = [row for row in rows if str(row.get("status") or "").upper() == result.upper()]
    totals = {"scheduled_shifts": len(rows), "present_shifts": sum(bool(row.get("checkin_at")) for row in rows),
              "late_cases": sum(row.get("late") is True for row in rows), "absent_days": sum(row.get("status") == "ABSENT" for row in rows),
              "pending_shifts": sum(row.get("status") == "NOT_YET_DUE" for row in rows), "missing_out": sum(row.get("status") == "MISSING_OUT" for row in rows)}
    return {**report, "rows": rows, "totals": totals, "start_date": start.isoformat(), "end_date": end.isoformat()}


@app.get("/api/v1/history/attendance")
def shift_attendance_history(request: Request, start_date: str = "", end_date: str = "",
                             store_id: int | None = None, employee_id: int | None = None,
                             result: str = "", department: str = "", limit: int = 100, offset: int = 0):
    actor = _auth_permission(request, "hr.report")
    report = _attendance_filtered_report(actor, start_date, end_date, store_id=store_id, employee_id=employee_id,
                                         department=department, result=result)
    rows = report["rows"]
    page_size, page_offset = max(1, min(200, limit)), max(0, offset)
    return {**{key: value for key, value in report.items() if key != "rows"},
            "items": rows[page_offset:page_offset + page_size], "total": len(rows),
            "limit": page_size, "offset": page_offset}


@app.get("/api/v1/history/attendance/export.csv")
def shift_attendance_csv(request: Request, start_date: str = "", end_date: str = "", store_id: int | None = None,
                         employee_id: int | None = None, department: str = "", result: str = ""):
    actor = _auth_permission(request, "hr.report")
    report = _attendance_filtered_report(actor, start_date, end_date, store_id=store_id, employee_id=employee_id,
                                         department=department, result=result)
    return _csv_response(report["rows"], [("business_date", "Ngày làm việc"), ("employee_code", "Mã nhân viên"),
        ("full_name", "Nhân viên"), ("department", "Bộ phận"), ("store_name", "Cửa hàng"), ("shift_name", "Ca"),
        ("checkin_at", "Giờ vào UTC"), ("checkout_at", "Giờ ra / điều chỉnh đã duyệt UTC"),
        ("checkout_source", "Nguồn giờ ra"), ("last_seen_at", "Lần ghi nhận cuối UTC"), ("status", "Trạng thái")],
        "BTMH_Attendance.csv")


@app.get("/api/v1/history/attendance/timeline")
def shift_attendance_timeline(request: Request, employee_id: int, business_date: str, store_id: int | None = None):
    actor = _auth_permission(request, "hr.report")
    if employee_id <= 0:
        raise HTTPException(400, "Nhân viên không hợp lệ")
    start, _end = _history_date_range(business_date, business_date)
    report = _attendance_filtered_report(actor, business_date, business_date, store_id=store_id, employee_id=employee_id)
    items = []
    window_start = datetime.combine(start, datetime.min.time(), ZoneInfo("Asia/Ho_Chi_Minh")).astimezone(timezone.utc)
    window_end = window_start + timedelta(days=1) - timedelta(microseconds=1)
    def timestamp(value):
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo is not None else None
    for row in report["rows"]:
        for key in ("expected_start_at", "checkin_at"):
            if row.get(key):
                window_start = min(window_start, timestamp(row[key]) or window_start)
        for key in ("expected_end_at", "checkout_at", "last_seen_at"):
            if row.get(key):
                window_end = max(window_end, timestamp(row[key]) or window_end)
        if row.get("checkin_at"):
            correction = row.get("correction") or {}
            items.append({"source": "ATTENDANCE", "event_type": "APPROVED_CHECKIN_CORRECTION" if correction.get("effective_checkin_at") else "VALID_IN",
                "label": "Giờ vào được duyệt" if correction.get("effective_checkin_at") else "Ghi nhận vào hợp lệ",
                "occurred_at": row["checkin_at"], "store_id": row["store_id"], "store_name": row.get("store_name"),
                "camera_name": row.get("camera_name") if not correction.get("effective_checkin_at") else None,
                "event_id": None if correction.get("effective_checkin_at") else row.get("first_event_id"),
                "full_name": row.get("full_name"), "subject_type": "EMPLOYEE"})
        if row.get("checkout_at"):
            items.append({"source": "ATTENDANCE", "event_type": "APPROVED_CHECKOUT_CORRECTION" if row.get("checkout_source") == "APPROVED_CORRECTION" else "VALID_OUT",
                "label": "Giờ ra được duyệt" if row.get("checkout_source") == "APPROVED_CORRECTION" else "Ghi nhận ra thực tế",
                "occurred_at": row["checkout_at"], "store_id": row["store_id"], "store_name": row.get("store_name"),
                "camera_name": None, "event_id": None if row.get("checkout_source") == "APPROVED_CORRECTION" else row.get("last_out_event_id"),
                "full_name": row.get("full_name"), "subject_type": "EMPLOYEE"})
        if row.get("last_seen_at"):
            items.append({"source": "ATTENDANCE", "event_type": "LAST_OBSERVATION", "occurred_at": row["last_seen_at"],
                "label": "Lần ghi nhận cuối",
                "store_id": row["store_id"], "store_name": row.get("store_name"), "camera_name": None,
                "full_name": row.get("full_name"), "subject_type": "EMPLOYEE"})
    clauses, params = ["r.student_id=?", "r.event_at>=?", "r.event_at<=?"], [employee_id, window_start.isoformat(), window_end.isoformat()]
    allowed = scoped_store_ids(actor)
    if store_id is not None:
        clauses.append("r.store_id=?"); params.append(store_id)
    elif allowed is not None:
        if not allowed:
            return {"items": [], "schedule_state": "UNCONFIGURED", "business_date": business_date}
        clauses.append("r.store_id IN (" + ",".join("?" for _ in allowed) + ")"); params.extend(sorted(allowed))
    rows = fetchall("SELECT r.*,s.full_name,s.student_code,s.faculty FROM recognition_events r "
                    "LEFT JOIN students s ON s.id=r.student_id WHERE " + " AND ".join(clauses) + " ORDER BY r.id LIMIT 200", params)
    for row in rows:
        items.append({**_recognition_public_row(row, evidence_allowed=has_permission(actor, "evidence.view")),
                      "source": "RECOGNITION", "event_type": "RECOGNITION", "label": "Nhận diện"})
    items.sort(key=lambda row: timestamp(row.get("occurred_at")) or window_start)
    return {"items": items, "business_date": business_date, "schedule_state": "ASSIGNED" if report["rows"] else "UNCONFIGURED",
            "recognition_limit": 200, "recognition_limit_reached": len(rows) >= 200, "generated_at": utc_now()}


@app.get("/api/v1/hr-report/summary")
def hr_report_summary(request: Request, period: str = "day", anchor: str = "", store_id: int | None = None):
    actor = _auth_permission(request, "hr.report")
    if store_id is not None:
        _require_store_scope(actor, store_id)
    return build_hr_report(period, anchor or None, allowed_store_ids=scoped_store_ids(actor), store_id=store_id)


@app.get("/api/v1/hr-report/export.xlsx")
def hr_report_export_xlsx(request: Request, period: str = "day", anchor: str = "", store_id: int | None = None):
    actor = _auth_permission(request, "hr.report")
    if store_id is not None:
        _require_store_scope(actor, store_id)
    report = build_hr_report(period, anchor or None, allowed_store_ids=scoped_store_ids(actor), store_id=store_id)
    data = report_xlsx_bytes(report)
    safe_anchor = str(report.get("anchor") or datetime.now().date().isoformat())
    filename = f"CampusFace_HR_{str(period or 'day').lower()}_{safe_anchor}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})


@app.get("/api/v1/hr-report/print")
def hr_report_print(request: Request, period: str = "day", anchor: str = "", store_id: int | None = None):
    actor = _auth_permission(request, "hr.report")
    if store_id is not None:
        _require_store_scope(actor, store_id)
    report = build_hr_report(period, anchor or None, allowed_store_ids=scoped_store_ids(actor), store_id=store_id)
    return Response(report_print_html(report), media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/operations/summary")
def operations_summary_api(request: Request, ):
    _auth_permission(request, "operations.view")
    return operations_summary()


@app.get("/api/v1/operations/rules")
def operations_rules_api(request: Request, ):
    _auth_permission(request, "operations.view")
    return operations_rules()


@app.put("/api/v1/operations/rules")
def operations_rules_update(payload: OperationsRulesPayload, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    result = save_operations_rules(payload.model_dump())
    add_audit_event("OPERATIONS", "ATTENDANCE_RULES_UPDATED", "SUCCESS", detail={"actor": actor.get("username"), **result})
    return {"ok": True, "rules": result}




@app.get("/api/v1/cameras/fleet/v4")
def camera_fleet_v4(request: Request):
    actor = _auth_permission(request, "camera.live")
    allowed = {c["camera_id"] for c in list_camera_contexts(actor)}
    rows = [row for row in list_camera_devices() if int(row["id"]) in allowed]
    items = []
    surveillance_rank = 0
    primary_runtime = CAMERA.status()
    primary_source = normalize_camera_source(CAMERA.current_source_identity())
    for row in rows:
        source = normalize_camera_source(str(row.get("source") or ""))
        ctype = str(row.get("camera_type") or "").upper()
        is_enrollment = source in {"0", "laptop"} or ctype in {"USB", "WEBCAM", "LAPTOP"}
        if is_enrollment:
            continue
        surveillance_rank += 1
        cid = int(row.get("id") or 0)
        if not bool(row.get("enabled", True)):
            FLEET_V4.stop(cid, wait=False)
            st = {"online": False, "state": "disabled", "error": ""}
        elif AI_RUNTIME.service(cid) is not None:
            ai_status = AI_RUNTIME.service(cid).status()
            st = {"online": bool(ai_status.get("opened")) and ai_status.get("state") == "online",
                  "shared_with_faceid": True, "error": ""}
        elif source == primary_source:
            # The FaceID service already owns this RTSP source. Reuse its real
            # frame/health state instead of opening a second Live Grid session.
            FLEET_V4.stop(cid, wait=False)
            age_ms = primary_runtime.get("last_frame_age_ms")
            online = bool(primary_runtime.get("opened")) and str(primary_runtime.get("state") or "") == "online"
            st = {
                "online": online,
                "last_frame_age_sec": round(float(age_ms) / 1000.0, 2) if age_ms is not None else None,
                "error": str(primary_runtime.get("error") or ""),
                "reconnects": int(primary_runtime.get("reconnect_count") or 0),
                "shared_with_faceid": True,
            }
        else:
            worker = FLEET_V4.get(cid)
            st = {**(worker.status() if worker else {"online": False, "state": "idle", "error": ""}),
                  "shared_with_faceid": False}
        rec = RECORDER_V4.camera_status(cid)
        items.append({
            "id": cid,
            "enabled": bool(row.get("enabled", True)),
            "name": str(row.get("name") or f"CAM{row.get('id')}"),
            "zone_name": str(row.get("zone_name") or row.get("location") or ""),
            "camera_type": ctype or "IP",
            "role": "SURVEILLANCE_PRIMARY" if surveillance_rank == 1 else "SURVEILLANCE",
            "source_key": f"CAM{cid:02d}",
            "source_display": redact_camera_source(source),
            "recording_enabled": bool(row.get("recording_enabled", True)),
            "recording_active": bool(rec.get("active")),
            "recording_error": str(rec.get("last_error") or ""),
            "recording_restart_count": int(rec.get("restart_count") or 0),
            "ai_enabled": bool(row.get("ai_enabled", False)),
            "face_recognition_enabled": bool(row.get("ai_enabled", False)),
            **AI_RUNTIME.camera_state(cid),
            **st,
        })
    return {"items": items, "enrollment_camera": {"name": "Laptop Camera", "source": "browser:getUserMedia", "role": "ENROLLMENT"}, "recording": RECORDER_V4.status(), "generated_at": utc_now()}


def _fleet_camera_source(camera_id: int) -> tuple[dict, str, bool]:
    row = fetchone("SELECT * FROM camera_devices WHERE id=?", (int(camera_id),))
    if not row:
        FLEET_V4.stop(int(camera_id), wait=False)
        raise HTTPException(404, "Không tìm thấy camera")
    if not bool(row.get("enabled", True)):
        FLEET_V4.stop(int(camera_id), wait=False)
        raise HTTPException(409, "Camera da bi tat")
    source = normalize_camera_source(str(row.get("source") or ""))
    active = normalize_camera_source(CAMERA.current_source_identity()) == source
    return row, source, active


@app.get("/api/v1/cameras/{camera_id}/frame.jpg")
def camera_fleet_frame(camera_id: int):
    row, source, active = _fleet_camera_source(camera_id)
    ai_service = AI_RUNTIME.service(camera_id)
    if ai_service is not None:
        context = ai_service.media_source_context()
        if context[0] != source:
            raise HTTPException(409, "CAMERA_SOURCE_CHANGED")
        return _preview_response(True, packet=ai_service.scoped_preview_packet(*context))
    if active:
        FLEET_V4.stop(int(camera_id))
        context = CAMERA.media_source_context()
        if context[0] != source:
            raise HTTPException(409, "CAMERA_SOURCE_CHANGED")
        return _preview_response(True, packet=CAMERA.scoped_preview_packet(*context))
    else:
        try:
            worker = FLEET_V4.ensure(int(camera_id), source, str(row.get("name") or "Camera"))
        except FleetUnavailable:
            raise HTTPException(503, "FLEET_RETIRE_FAILED") from None
        data = worker.jpeg()
    if not data:
        raise HTTPException(503, "Camera chưa có frame")
    state = worker.status()
    age = state.get("last_frame_age_sec")
    return Response(content=data, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Camera-Seq": str(state.get("frame_seq", 0)),
        "X-Frame-Age-Ms": str(float(age) * 1000.0 if age is not None else 999999),
    })


@app.get("/api/v1/cameras/{camera_id}/stream.mjpg")
def camera_fleet_stream(camera_id: int, request: Request):
    row, source, active = _fleet_camera_source(camera_id)
    ai_service = AI_RUNTIME.service(camera_id)
    lease = None
    if ai_service is not None:
        context = ai_service.media_source_context()
        if context[0] != source:
            raise HTTPException(409, "CAMERA_SOURCE_CHANGED")
        def get_frame():
            return ai_service.scoped_preview_packet(*context)[0]
    elif active:
        FLEET_V4.stop(int(camera_id))
        context = CAMERA.media_source_context()
        if context[0] != source:
            raise HTTPException(409, "CAMERA_SOURCE_CHANGED")
        def get_frame():
            return CAMERA.scoped_preview_packet(*context)[0]
    else:
        try:
            worker, lease = FLEET_V4.acquire(int(camera_id), source, str(row.get("name") or "Camera"))
        except FleetUnavailable:
            raise HTTPException(503, "FLEET_RETIRE_FAILED") from None
        def get_frame():
            return worker.jpeg()
    async def generate():
        last = None
        check_at = 0.0
        try:
            while not await request.is_disconnected():
                if time.monotonic() >= check_at:
                    try:
                        actor = await run_in_threadpool(_auth_permission, request, "camera.live")
                        await run_in_threadpool(_camera_scope_context, actor, camera_id)
                        _, current, current_active = await run_in_threadpool(_fleet_camera_source, camera_id)
                    except HTTPException:
                        break
                    if current != source or current_active != active:
                        break
                    check_at = time.monotonic() + 1.0
                if ai_service is not None and (AI_RUNTIME.service(camera_id) is not ai_service
                        or ai_service.media_source_context() != context):
                    break
                if active and ai_service is None and CAMERA.media_source_context() != context:
                    break
                if lease is not None and not await run_in_threadpool(FLEET_V4.renew, int(camera_id), lease):
                    break
                data = get_frame()
                if data and data != last:
                    last = data
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nCache-Control: no-store\r\n\r\n" + data + b"\r\n"
                await asyncio.sleep(0.1)
        finally:
            if lease is not None:
                await run_in_threadpool(FLEET_V4.release, int(camera_id), lease)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/api/v1/presence/current")
def presence_current_v4(request: Request):
    _auth_permission(request, "attendance.view")
    rows = hr_current_presence()
    total_row = fetchone("SELECT COUNT(*) n FROM students") or {"n": 0}
    visitor_row = fetchone("SELECT COUNT(*) n FROM visitor_sessions WHERE status='ACTIVE'") or {"n": 0}
    return {
        "items": [{
            "student_id": r.get("student_id"), "employee_code": r.get("student_code") or "",
            "full_name": r.get("full_name") or "Chưa xác định", "department": r.get("faculty") or "",
            "group": r.get("class_name") or "", "started_at": r.get("started_at"),
            "last_seen_at": r.get("last_seen_at"), "status": "PRESENT",
        } for r in rows],
        "employee_total": int(total_row.get("n") or 0),
        "active_visitors": int(visitor_row.get("n") or 0),
        "generated_at": utc_now(),
    }


@app.get("/api/v1/recordings/media")
def recording_media_v4(path: str, request: Request):
    _auth_permission(request, "camera.playback")
    raw = str(path or "").strip()
    root = Path(DATA_ROOT).resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve()
        candidate.relative_to(root)
    except Exception:
        raise HTTPException(403, "Đường dẫn video không hợp lệ")
    if not candidate.is_file():
        raise HTTPException(404, "Không tìm thấy video")
    return FileResponse(candidate, media_type="video/mp4", filename=candidate.name)


@app.get("/api/v1/cameras/fleet")
def camera_fleet_status(request: Request):
    actor = _auth_permission(request, "camera.live")
    public_items = []
    for context in list_camera_contexts(actor):
        state = AI_RUNTIME.camera_state(context["camera_id"])
        public_items.append({**context, **state, "active_ai_pipeline": bool(state["ai_admitted"])})
    return {
        "runtime_mode": "BACKGROUND_AI_CAMERA_PIPELINES",
        "multi_camera_schema_ready": True,
        "simultaneous_ai_workers": True,
        "capacity": AI_RUNTIME.capacity,
        "background_owned": True,
        "items": public_items,
    }


@app.get("/api/v1/cameras/devices")
def camera_devices_list(request: Request):
    actor = _auth_permission(request, "camera.live")
    items = list_camera_devices()
    allowed_ids = {int(item["camera_id"]) for item in list_camera_contexts(actor)}
    items = [item for item in items if int(item.get("id") or 0) in allowed_ids]
    runtime = CAMERA.status()
    online = bool(runtime.get("opened")) and str(runtime.get("state") or "").lower() == "online"
    active_source = CAMERA.current_source_identity()
    for item in items:
        item_source = normalize_camera_source(str(item.get("source") or ""))
        is_active = item_source == normalize_camera_source(active_source)
        item["active"] = is_active
        item["source_display"] = redact_camera_source(item_source)
        # Never return raw RTSP credentials to the browser. Activation uses device_id.
        item["source"] = item_source if str(item_source).isdigit() else "hikvision"
        handover = runtime.get("handover") or {}
        in_handover = bool(runtime.get("handover_active") or handover.get("active"))
        item["health_status"] = "HANDOVER" if is_active and in_handover else ("ONLINE" if is_active and online else "OFFLINE" if is_active else "STANDBY")
        item["actual_resolution"] = f"{runtime.get('actual_width',0)}x{runtime.get('actual_height',0)}" if is_active else ""
        item["capture_fps"] = runtime.get("capture_fps", 0) if is_active else 0
    return {"items": items, "runtime": runtime}


@app.get("/api/v1/cameras/devices/{device_id}/configuration")
def camera_configuration_get(device_id: int, request: Request):
    actor = _auth_permission(request, "camera.configure")
    return {"item": _camera_scope_context(actor, device_id)}


@app.put("/api/v1/cameras/devices/{device_id}/configuration")
def camera_configuration_save(device_id: int, payload: CameraConfigurationPayload, request: Request):
    actor = _auth_permission(request, "camera.configure")
    _camera_scope_context(actor, device_id)
    try:
        enforce_store_scope(actor, payload.store_id)
        with AI_RUNTIME.reserve_camera(device_id):
            item = save_camera_configuration(device_id, **payload.model_dump())
    except PermissionError:
        raise HTTPException(403, "Cửa hàng không thuộc phạm vi được cấp quyền") from None
    except ValueError as exc:
        messages = {"INVALID_CAMERA_NAME": "Tên camera cần có từ 1 đến 120 ký tự và không chứa địa chỉ kết nối.",
                    "CAMERA_ZONE_REQUIRED": "Đặt khu vực trước khi bật AI hoặc đếm lượt ghé.",
                    "CAMERA_STORE_REQUIRED": "Chọn cửa hàng trước khi bật AI hoặc đếm lượt ghé.",
                    "ENTRANCE_CONFIG_REQUIRED": "Thiết lập đường vào trước khi bật đếm lượt ghé.",
                    "STORE_NOT_FOUND": "Cửa hàng đã chọn không còn tồn tại.", "CAMERA_NOT_FOUND": "Camera không còn tồn tại."}
        raise HTTPException(400, messages.get(str(exc), "Kiểm tra cửa hàng, khu vực và vị trí đường vào rồi lưu lại.")) from None
    except RuntimeError:
        raise HTTPException(409, "Camera đang dừng worker cũ; vui lòng thử lại") from None
    add_audit_event("SYSTEM", "CAMERA_CONFIGURATION_SAVED", "SUCCESS", detail={
        "actor": actor.get("username"), "camera_id": device_id,
        "store_id": item.get("store_id"), "zone_name": item.get("zone_name"),
        "ai_enabled": item.get("ai_enabled"), "visitor_counting_enabled": item.get("visitor_counting_enabled"),
    })
    AI_RUNTIME.reconcile()
    return {"ok": True, "item": item}


@app.get("/api/v1/recognition/cameras")
def recognition_cameras(request: Request):
    actor = _auth_permission(request, "camera.live")
    return {"items": _public_camera_states(actor), "capacity": AI_RUNTIME.capacity, "generated_at": utc_now()}


def _public_camera_states(actor: dict):
    """Read current owners only. Never open a decoder or initialize a model."""
    items = []
    primary_context = source_context(CAMERA.current_source_identity()) or {}
    primary = CAMERA.status()
    pad_state = "DISABLED" if not runtime_config.PAD_ENABLED else "ENABLED" if getattr(PAD, "_net", None) is not None else "UNAVAILABLE" if getattr(PAD, "_attempted", False) else "PENDING"
    for context in list_camera_contexts(actor):
        cid = int(context["camera_id"])
        state = AI_RUNTIME.camera_state(cid)
        online = state.get("online")
        if not context.get("enabled"):
            online = False
        elif online is None and cid == primary_context.get("camera_id"):
            online = bool(primary.get("opened")) and primary.get("state") == "online"
        elif online is None:
            worker = FLEET_V4.get(cid)
            status = worker.status() if worker is not None else None
            online = bool(status.get("online")) if status is not None else None
        recording = RECORDER_V4.camera_status(cid)
        items.append({**context, **_public_ai_status(state),
                      "ai_admitted": bool(state.get("ai_admitted")), "online": online,
                      "connection_state": "ONLINE" if online is True else "OFFLINE" if online is False else "UNKNOWN",
                      "recording_active": bool(recording.get("active")), "pad_state": pad_state})
    return items


def _public_ai_status(state: dict) -> dict:
    """Keep diagnostics source-free and limited to known availability codes."""
    reasons = {"CAMERA_NOT_READY", "AI_WORKER_START_FAILED", "RETIREMENT_PENDING",
               "READER_RETIRE_PENDING", "CAPACITY_WAIT", "AI_PROCESS_FAILED", "AI_PAUSED", "AI_STARTING"}
    count = state.get("ai_successful_results_current_source")
    return {"ai_state": state.get("ai_state", "DISABLED"),
            "reason_code": state.get("reason_code") if state.get("reason_code") in reasons else "",
            "ai_error_code": "AI_PROCESS_FAILED" if state.get("ai_error_code") == "AI_PROCESS_FAILED" else "",
            "ai_successful_results_current_source": count if type(count) is int and count >= 0 else None}


def _visit_runtime_readiness(report: dict, cameras: list):
    states = {row["camera_id"]: row for row in cameras}
    for row in report["stores"]:
        configured = row.get("configured_camera_ids") or []
        ready = bool(configured) and all(states.get(cid, {}).get("ai_state") == "ACTIVE" and
            states.get(cid, {}).get("online") is True and states.get(cid, {}).get("store_id") == row["store_id"] for cid in configured)
        if configured and not ready:
            row["configuration_state"] = "PARTIAL"
            row["comparison_eligible"] = False
    statuses = [row["configuration_state"] for row in report["stores"]]
    report["configuration_state"] = "READY" if statuses and all(item == "READY" for item in statuses) else "UNCONFIGURED" if not statuses or all(item == "UNCONFIGURED" for item in statuses) else "PARTIAL"
    for name, direction in (("max_rise", 1), ("max_fall", -1)):
        eligible = [row for row in report["stores"] if row.get("comparison_eligible") and row["delta"] * direction > 0]
        winner = max(eligible, key=lambda row: (row["delta"] * direction, -row["store_id"])) if eligible else None
        report[name] = {key: winner[key] for key in ("store_id", "store_name", "selected", "previous", "delta", "percent", "change_state")} if winner else None
    return report


@app.get("/api/v1/history/visits")
def entrance_visits_report(request: Request, date: str = "", store_id: int | None = None):
    actor = _auth_permission(request, "visitor.view")
    try:
        report = query_visits_report(date or None, allowed_store_ids=scoped_store_ids(actor), store_id=store_id)
    except PermissionError:
        raise HTTPException(403, "Cửa hàng không thuộc phạm vi được cấp quyền") from None
    except ValueError:
        raise HTTPException(400, "Chọn ngày và cửa hàng hợp lệ") from None
    return _visit_runtime_readiness(report, _public_camera_states(actor))


@app.get("/api/v1/dashboard/summary")
def dashboard_summary(request: Request, store_id: int | None = None):
    actor = _auth_permission(request, "dashboard.view")
    try:
        out = query_management_summary(allowed_store_ids=scoped_store_ids(actor), store_id=store_id)
    except PermissionError:
        raise HTTPException(403, "Cửa hàng không thuộc phạm vi được cấp quyền") from None
    except ValueError:
        raise HTTPException(400, "Chọn cửa hàng hợp lệ") from None
    cameras = [row for row in _public_camera_states(actor) if store_id is None or row["store_id"] == store_id]
    out["cameras"] = {"total": len(cameras), "online": sum(row["online"] is True for row in cameras),
                      "unknown": sum(row["online"] is None for row in cameras)}
    out["latest"] = [_recognition_public_row(row, evidence_allowed=has_permission(actor, "evidence.view")) for row in out["latest"]]
    out["visits"] = _visit_runtime_readiness(out["visits"], cameras)
    return out


def _recognition_public_row(row: dict, *, evidence_allowed: bool = False) -> dict:
    try:
        detail = json.loads(row.get("detail_json") or "{}")
    except (ValueError, TypeError):
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    status = str(row.get("status") or "ANALYZING").upper()
    verified = status == "RECOGNIZED" and bool(row.get("anti_spoof_passed"))
    blocked = status == "SPOOF_BLOCKED"
    live = detail.get("liveness") or {}
    if not isinstance(live, dict):
        live = {}
    pad = str(live.get("status") or ("PASS" if verified else "FAIL" if blocked else "PENDING")).upper()
    if pad not in {"PASS", "FAIL", "PENDING", "BLOCKED", "ERROR"}:
        pad = "PENDING"
    timezone_name = str(detail.get("appearance_timezone") or "Asia/Ho_Chi_Minh")
    try:
        ZoneInfo(timezone_name)
    except (ValueError, KeyError):
        timezone_name = "Asia/Ho_Chi_Minh"
    event_id = int(row["id"])
    return {"id": event_id, "event_id": event_id, "source_id": event_id, "source": "recognition",
            "appearance_id": row.get("appearance_id"), "daily_sequence": row.get("daily_sequence"),
            "business_date": row.get("business_date"), "event_at": row.get("event_at"), "occurred_at": row.get("event_at"),
            "timezone_name": timezone_name,
            "camera_id": row.get("camera_id"), "camera_name": _safe_name(row.get("camera_name")) or None,
            "store_id": row.get("store_id"), "store_name": _safe_name(row.get("store_name")) or None, "zone_name": _safe_name(row.get("zone_name")) or None,
            "subject_type": "EMPLOYEE" if verified else "VISITOR" if status == "UNREGISTERED" else "UNKNOWN",
            "person_id": row.get("student_id") if verified else None, "student_id": row.get("student_id") if verified else None,
            "full_name": _safe_name(row.get("full_name")) if verified else "Khách" if status == "UNREGISTERED" else "Chưa xác định",
            "student_code": _safe_name(row.get("student_code")) if verified else "", "department": _safe_name(row.get("faculty")) if verified else "",
            "status": status, "faceid_status": "VERIFIED" if verified else "REJECTED" if blocked else "UNKNOWN" if status == "UNREGISTERED" else "CHECKING",
            "pad_status": pad, "recognized": verified, "anti_spoof_passed": bool(row.get("anti_spoof_passed")),
            "snapshot_url": f"/api/v1/events/{event_id}/evidence.jpg" if evidence_allowed and detail.get("snapshot_path") else ""}


@app.get("/api/v1/recognition/recent")
def recognition_recent(request: Request, camera_id: int | None = None, limit: int = 20):
    actor = _auth_permission(request, "camera.live")
    clauses, params = ["r.appearance_id IS NOT NULL"], []
    if camera_id is not None:
        _camera_scope_context(actor, camera_id)
        clauses.append("r.camera_id=?")
        params.append(camera_id)
    allowed = scoped_store_ids(actor)
    if allowed is not None:
        if not allowed:
            return {"items": [], "generated_at": utc_now()}
        clauses.append("r.store_id IN (" + ",".join("?" for _ in allowed) + ")")
        params.extend(sorted(allowed))
    rows = fetchall("SELECT r.*,s.student_code,s.full_name,s.faculty FROM recognition_events r "
                    "LEFT JOIN students s ON s.id=r.student_id WHERE " + " AND ".join(clauses) +
                    " ORDER BY r.id DESC LIMIT ?", (*params, max(1, min(50, limit))))
    evidence = has_permission(actor, "evidence.view")
    return {"items": [_recognition_public_row(row, evidence_allowed=evidence) for row in rows], "generated_at": utc_now()}


@app.post("/api/v1/cameras/devices")
def camera_devices_create(payload: CameraDevicePayload, request: Request):
    actor = _auth_permission(request, "camera.configure")
    try:
        item = save_camera_device(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _configure_ai_registry_source()
    add_audit_event("SYSTEM", "CAMERA_DEVICE_CREATED", "SUCCESS", camera_source=str(item.get("source") or ""), detail={"actor": actor.get("username"), "name": item.get("name"), "zone": item.get("zone_name")})
    return {"ok": True, "item": item}


@app.put("/api/v1/cameras/devices/{device_id}")
def camera_devices_update(device_id: int, payload: CameraDevicePayload, request: Request):
    actor = _auth_permission(request, "camera.configure")
    try:
        item = save_camera_device(payload.model_dump(), device_id=device_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _configure_ai_registry_source()
    FLEET_V4.stop(int(device_id), wait=False)
    RECORDER_V4.invalidate_camera(int(device_id))
    add_audit_event("SYSTEM", "CAMERA_DEVICE_UPDATED", "SUCCESS", camera_source=str(item.get("source") or ""), detail={"actor": actor.get("username"), "device_id": device_id, "name": item.get("name")})
    return {"ok": True, "item": item}


@app.delete("/api/v1/cameras/devices/{device_id}")
def camera_devices_delete(device_id: int, request: Request):
    actor = _auth_permission(request, "camera.configure")
    try:
        delete_camera_device(device_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _configure_ai_registry_source()
    FLEET_V4.stop(int(device_id), wait=False)
    RECORDER_V4.invalidate_camera(int(device_id))
    add_audit_event("SYSTEM", "CAMERA_DEVICE_DELETED", "SUCCESS", detail={"actor": actor.get("username"), "device_id": device_id})
    return {"ok": True}


@app.post("/api/v1/cameras/devices/{device_id}/activate")
def camera_devices_activate(device_id: int, request: Request):
    actor = _auth_permission(request, "camera.configure")
    try:
        source,label=_resolve_camera_selection(f"CAM{int(device_id):02d}")
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    result = _perform_camera_selection(source,label,actor,int(device_id))
    if isinstance(result,JSONResponse):return result
    return {"ok":True,"device":{"id":device_id,"name":label},"runtime":result,"restart_required":False}


class CameraConnectionUpdate(BaseModel):
    host: str
    port: int = 554
    path: str = "/Streaming/Channels/101"
    username: str | None = None
    password: str | None = None


@app.get("/api/v1/cameras/devices/{device_id}/connection")
def camera_connection_get(device_id: int, request: Request):
    _auth_permission(request,"camera.configure")
    row=fetchone("SELECT * FROM camera_devices WHERE id=?",(device_id,))
    if not row:raise HTTPException(404,"Camera not found")
    return JSONResponse(connection_view(row),headers={"Cache-Control":"no-store"})


@app.put("/api/v1/cameras/devices/{device_id}/connection")
def camera_connection_update(device_id: int, payload: CameraConnectionUpdate, request: Request):
    """Persist a camera connection by immutable device id and verify the read-back.

    V5.4.7 keeps the V5.4.6 persistence guard and repairs the legacy failure mode where an operator edited a Hikvision
    address but another runtime component continued to use the pre-edit URI.
    Saving a connection never switches the active FaceID source; it only updates
    the registry, invalidates stale auxiliary readers and verifies persistence.
    """
    actor=_auth_permission(request,"camera.configure")
    if not CAMERA._handover_lock.acquire(blocking=False):
        raise HTTPException(409,"Camera đang được kiểm tra/chuyển nguồn. Vui lòng chờ.")
    row=None
    previous_source=""
    try:
        row=fetchone("SELECT * FROM camera_devices WHERE id=?",(device_id,))
        if not row:raise HTTPException(404,"Camera not found")
        previous_source=normalize_camera_source(str(row.get("source") or ""))
        try:
            source=update_connection_source(str(row["source"]),**payload.model_dump())
        except ValueError:
            raise HTTPException(400,"IP, cổng, đường dẫn hoặc thông tin đăng nhập camera chưa hợp lệ.") from None
        source=normalize_camera_source(source)
        values=dict(row);values["source"]=source
        try:
            save_camera_device(values,device_id=device_id)
        except ValueError as exc:
            raise HTTPException(400,str(exc))

        # Read back from the database, rather than trusting the value just written.
        # A successful response therefore guarantees that reload/restart will see
        # the same RTSP endpoint.
        updated=fetchone("SELECT * FROM camera_devices WHERE id=?",(device_id,))
        if not persisted_connection_matches(source, updated):
            raise HTTPException(500,"Không xác nhận được cấu hình camera vừa lưu. Dữ liệu cũ vẫn được giữ an toàn.")

        _configure_ai_registry_source()

        # Any live-grid or recorder worker keyed by this camera id may still own
        # the previous URI. Stop only those auxiliary readers so their next use
        # reopens from the verified registry record. The primary FaceID camera is
        # deliberately not touched until the operator presses Chuyển nguồn.
        try:
            FLEET_V4.stop(int(device_id),wait=False)
        except Exception:
            pass
        try:
            RECORDER_V4.invalidate_camera(int(device_id))
        except Exception:
            pass

        # If the edited camera was the persisted startup source, carry the edit
        # into startup settings without disturbing the currently running reader.
        try:
            settings=camera_settings()
            if startup_source_tracks_previous(settings.get("source"), previous_source):
                settings["source"]=source
                save_camera_settings(settings)
        except Exception:
            pass
    finally:
        CAMERA._handover_lock.release()
    add_audit_event("SYSTEM","CAMERA_CONNECTION_UPDATED","SUCCESS",camera_source=str((row or {}).get("name") or "Camera"),
                    detail={"actor":actor.get("username"),"device_id":device_id,"credential_changed":bool(payload.password),
                            "persisted":True,"source":redact_camera_source(source)})
    result=connection_view(updated)
    result.update({"ok":True,"persisted":True,"requires_switch":True})
    return JSONResponse(result,headers={"Cache-Control":"no-store"})


@app.get("/api/v1/exceptions")
def exceptions_list(limit: int = 80, decision: str = "PENDING"):
    return {"items": exception_queue(limit=limit, decision=decision), "rules": operations_rules()}


@app.put("/api/v1/exceptions/{event_id}")
def exceptions_review(event_id: int, payload: ExceptionReviewPayload, request: Request):
    actor = _auth_permission(request, "visitor.review")
    try:
        review = review_exception(event_id, payload.decision, payload.resolved_student_id, str(actor.get("username") or "operator"), payload.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("OPERATIONS", "EXCEPTION_REVIEWED", "SUCCESS", student_id=payload.resolved_student_id, detail={"event_id": event_id, "decision": payload.decision, "actor": actor.get("username"), "note": payload.note[:200]})
    return {"ok": True, "review": review}


@app.put("/api/v1/attendance/sessions/{session_id}/records/{student_id}")
def attendance_adjust(session_id: int, student_id: int, payload: AttendanceAdjustmentPayload, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    try:
        result = adjust_attendance_record(session_id, student_id, payload.status, payload.reason, str(actor.get("username") or "operator"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("ATTENDANCE", "ATTENDANCE_MANUAL_ADJUSTMENT", "SUCCESS", student_id=student_id, detail={"session_id": session_id, **result})
    return {"ok": True, "adjustment": result}


@app.get("/api/v1/attendance/sessions")
def attendance_sessions(limit: int = 100):
    return {"items": list_sessions(limit)}


@app.post("/api/v1/attendance/sessions")
def attendance_create_session(payload: AttendanceSessionCreate, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    try:
        result = create_session(payload.name, payload.class_name, payload.room_name, payload.start_at, payload.end_at, payload.grace_minutes, actor.get("username", "operator"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("ATTENDANCE", "SESSION_CREATED", "SUCCESS", detail={"session_id": result["id"], "name": result["name"], "class_name": result["class_name"]})
    return result


@app.get("/api/v1/attendance/sessions/{session_id}")
def attendance_get_session(session_id: int):
    try:
        return get_session(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/v1/attendance/sessions/{session_id}/ledger")
def attendance_ledger(session_id: int):
    try:
        return {"session": get_session(session_id), "items": session_ledger(session_id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/v1/attendance/sessions/{session_id}/close")
def attendance_close(session_id: int, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    try:
        result = close_session(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    add_audit_event("ATTENDANCE", "SESSION_CLOSED", "SUCCESS", detail={"session_id": session_id, "actor": actor.get("username")})
    return result


@app.get("/api/v1/attendance/sessions/{session_id}/export.csv")
def attendance_export(session_id: int):
    try:
        payload = session_csv(session_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return Response(payload, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="CampusFace-Session-{session_id}.csv"'})


def _legacy_dashboard_summary():
    # "Hôm nay" follows the Windows/server local timezone while event timestamps
    # stay canonical UTC in storage. This avoids losing the first hours after local
    # midnight on deployments such as UTC+7.
    local_now = datetime.now().astimezone()
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    start_utc = local_start.astimezone(timezone.utc).isoformat()
    end_utc = local_end.astimezone(timezone.utc).isoformat()
    total = int((fetchone("SELECT COUNT(*) AS n FROM students") or {}).get("n") or 0)
    enrolled = int((fetchone("SELECT COUNT(*) AS n FROM face_templates") or {}).get("n") or 0)
    recognized = int((fetchone("SELECT COUNT(*) AS n FROM recognition_events WHERE status='RECOGNIZED' AND event_at>=? AND event_at<?", (start_utc, end_utc)) or {}).get("n") or 0)
    unique_today = int((fetchone("SELECT COUNT(DISTINCT student_id) AS n FROM recognition_events WHERE student_id IS NOT NULL AND status='RECOGNIZED' AND event_at>=? AND event_at<?", (start_utc, end_utc)) or {}).get("n") or 0)
    unknown = int((fetchone("SELECT COUNT(*) AS n FROM recognition_events WHERE status='UNREGISTERED' AND event_at>=? AND event_at<?", (start_utc, end_utc)) or {}).get("n") or 0)
    spoof = int((fetchone("SELECT COUNT(*) AS n FROM recognition_events WHERE status='SPOOF_BLOCKED' AND event_at>=? AND event_at<?", (start_utc, end_utc)) or {}).get("n") or 0)
    classes = int((fetchone("SELECT COUNT(*) AS n FROM attendance_sessions WHERE start_at>=? AND start_at<?", (start_utc, end_utc)) or {}).get("n") or 0)
    active_classes = int((fetchone("SELECT COUNT(*) AS n FROM attendance_sessions WHERE status='ACTIVE'") or {}).get("n") or 0)
    try:
        visitor_today = int((fetchone("SELECT COUNT(*) AS n FROM visitor_sessions WHERE entry_at>=? AND entry_at<?", (start_utc, end_utc)) or {}).get("n") or 0)
        active_visitors = int((fetchone("SELECT COUNT(*) AS n FROM visitor_sessions WHERE status='ACTIVE'") or {}).get("n") or 0)
    except Exception:
        visitor_today = 0
        active_visitors = 0
    try:
        open_incidents = int((fetchone("SELECT COUNT(*) AS n FROM incidents WHERE UPPER(status) NOT IN ('CLOSED','RESOLVED')") or {}).get("n") or 0)
    except Exception:
        open_incidents = 0
    try:
        employee_present_now = len(hr_current_presence())
    except Exception:
        employee_present_now = 0
    latest = fetchall(
        """SELECT r.id,r.student_id,r.status,r.confidence,r.liveness_score,r.anti_spoof_passed,r.event_at,
        s.student_code,s.full_name,s.class_name,s.faculty
        FROM recognition_events r LEFT JOIN students s ON s.id=r.student_id
        ORDER BY r.id DESC LIMIT 8"""
    )
    try:
        templates = INDEX.status()
    except Exception as exc:
        templates = {"ready": False, "error": str(exc), "template_vectors": 0, "students": enrolled}
    try:
        camera_devices = list_camera_devices()
    except Exception:
        camera_devices = []
    try:
        pending_exceptions = int((fetchone("SELECT COUNT(*) AS n FROM exception_reviews WHERE decision='PENDING'") or {}).get("n") or 0)
    except Exception:
        pending_exceptions = 0
    cam_runtime = CAMERA.status()
    perf = CAMERA.performance_status()
    active_source = str(cam_runtime.get("source") or "")
    registered_cameras = len(camera_devices)
    online_cameras = 1 if cam_runtime.get("opened") and str(cam_runtime.get("state") or "").lower() == "online" else 0
    return {
        "students": {
            "total": total,
            "faceid": enrolled,
            "faceid_coverage": round((enrolled / total * 100.0), 1) if total else 0.0,
        },
        "today": {
            "recognized_events": recognized,
            "unique_students": unique_today,
            "unknown": unknown,
            "spoof_blocked": spoof,
            "attendance_sessions": classes,
            "active_sessions": active_classes,
            "visitor_sessions": visitor_today,
            "active_visitors": active_visitors,
            "employee_present_now": employee_present_now,
        },
        "camera": cam_runtime,
        "performance": perf,
        "operations": {
            "registered_cameras": registered_cameras,
            "online_cameras": online_cameras,
            "active_source": active_source,
            "pending_exceptions": pending_exceptions,
            "open_incidents": open_incidents,
        },
        "database": db_status(),
        "storage": storage_status(),
        "templates": templates,
        "latest": latest,
        "generated_at": utc_now(),
    }


@app.get("/api/v1/system/audit")
def system_audit(request: Request, limit: int = 80):
    _auth_permission(request, "audit.view")
    return {"items": audit_events(max(5, min(250, int(limit))))}


@app.post("/api/v1/camera/reconnect")
def camera_reconnect(request: Request):
    # Recovery is safe before initial account bootstrap; once accounts exist it is
    # restricted to authenticated operators/admins like other operational controls.
    actor = {"username": "local-bootstrap"}
    if user_count() > 0:
        actor = _auth_permission(request, "camera.configure")
    CAMERA.restart()
    try:
        gateway = MEDIA_GATEWAY.restart()
    except Exception:
        gateway = {"available": False}
    add_audit_event("SYSTEM", "CAMERA_RECONNECT", "SUCCESS", camera_source=CAMERA.event_camera_source(), detail={"actor": actor.get("username"), "native_gateway": bool(gateway.get("available"))})
    return {"ok": True, "camera": CAMERA.status(), "native_gateway": sanitize_payload(gateway)}


@app.get("/api/v1/exports/students.csv")
def export_students_csv(request: Request):
    import csv
    import io
    rows = students(request)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Mã nhân viên", "Ho ten", "Lop", "Phòng ban", "Email", "Dien thoai", "FaceID", "So goc FaceID", "Lan nhan dien", "Nhan dien gan nhat"])
    for r in rows:
        writer.writerow([
            r.get("student_code", ""), r.get("full_name", ""), r.get("class_name", ""), r.get("faculty", ""),
            r.get("email", ""), r.get("phone", ""), "YES" if r.get("enrolled") else "NO",
            r.get("face_pose_count", 0), r.get("recognition_count", 0), r.get("last_seen_at", "") or "",
        ])
    data = ('\ufeff' + out.getvalue()).encode('utf-8')
    return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="CampusFace-Students.csv"'})


@app.get("/api/v1/exports/student-template.csv")
def export_student_template_csv():
    data = "\ufeffMã nhân viên,Ho ten,Lop,Phòng ban,Email,Dien thoai\r\nSV001,Nguyen Van A,8B1,Cong nghe thong tin,a@example.com,0900000000\r\n".encode("utf-8")
    return Response(data, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="CampusFace-Student-Template.csv"'})


@app.get("/api/v1/settings/camera")
def get_camera_settings(request: Request):
    _auth_permission(request, "camera.live")
    settings = dict(camera_settings())
    raw_source = normalize_camera_source(str(settings.get("source") or "0"))
    settings["source"] = raw_source if raw_source.isdigit() else "hikvision"
    return {"settings": settings, "runtime": CAMERA.status(), "restart_required_after_change": True}


@app.put("/api/v1/settings/camera")
def put_camera_settings(payload: CameraSettingsPayload, request: Request):
    actor = _auth_permission(request, "camera.configure")
    values = payload.model_dump()
    if values.get("classroom_preview_fps") is not None:
        values["observation_preview_fps"] = values["classroom_preview_fps"]
    if values.get("classroom_preview_width") is not None:
        values["observation_preview_width"] = values["classroom_preview_width"]
    if values.get("classroom_jpeg_quality") is not None:
        values["observation_jpeg_quality"] = values["classroom_jpeg_quality"]
    try:
        source, _label = _resolve_camera_selection(str(values.get("source") or "0"))
        values["source"] = source
        result = save_camera_settings(values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "CAMERA_SETTINGS_CHANGED", "SUCCESS", detail={"actor": actor.get("username"), **result})
    return result


@app.post("/api/v1/camera/test-current")
def camera_test_current(request: Request):
    actor = _auth_permission(request, "camera.live")
    status = CAMERA.status()
    online = bool(status.get("opened")) and str(status.get("state") or "").lower() == "online"
    frame_age = float(status.get("last_frame_age_ms") or 0.0)
    result = {
        "ok": bool(online and (frame_age <= 1500 or frame_age <= 0)),
        "online": online,
        "source_label": status.get("source_label") or "Camera",
        "resolution": f"{int(status.get('actual_width') or 0)}x{int(status.get('actual_height') or 0)}",
        "capture_fps": float(status.get("capture_fps") or 0.0),
        "frame_age_ms": frame_age,
        "backend": status.get("backend") or "—",
        "error": status.get("error") or "",
    }
    add_audit_event("SYSTEM", "CAMERA_CONNECTION_TEST", "SUCCESS" if result["ok"] else "WARNING", camera_source=str(result["source_label"]), detail={"actor": actor.get("username"), **result})
    return result


@app.get("/api/v1/system/diagnostics")
def system_diagnostics(request: Request, ):
    _auth_permission(request, "system.diagnostics")
    import shutil
    raw_storage = storage_status()
    storage = {}
    for key in ("db_size", "free_bytes", "total_bytes", "photos_size", "backup_count"):
        value = raw_storage.get(key)
        storage[key] = value if type(value) in (int, float) and 0 <= value <= 10**16 and math.isfinite(value) else None
    storage["data_root"] = str(DATA_ROOT)
    try:
        storage["last_backup_at"] = datetime.fromisoformat(str(raw_storage.get("last_backup_at") or "")).isoformat()
    except ValueError:
        storage["last_backup_at"] = None
    cam = safe_camera_status(CAMERA.status())
    identity = CAMERA.latest_result()
    try:
        templates = INDEX.status()
    except Exception as exc:
        templates = {"ready": False, "error": str(exc)}
    checks = [
        {"key": "camera", "label": "Camera", "ok": bool(cam.get("opened")) and str(cam.get("state") or "").lower() == "online", "detail": cam.get("error") or f"{cam.get('actual_width',0)}x{cam.get('actual_height',0)} @ {cam.get('capture_fps',0)} FPS"},
        {"key": "camera_quality", "label": "Chất lượng camera", "ok": str(cam.get("camera_quality") or "UNKNOWN").upper() != "POOR", "detail": cam.get("quality_warning") or f"{cam.get('camera_quality','UNKNOWN')} · nét {cam.get('sharpness_score',0)} · sáng {cam.get('brightness',0)}"},
        {"key": "face_detector", "label": "Face Detector", "ok": bool(CORE.ready), "detail": "YuNet + SFace cục bộ sẵn sàng" if CORE.ready else "Thiếu model FaceID hoặc model chưa tải"},
        {"key": "passive_pad", "label": "Passive PAD", "ok": True, "detail": "MiniFASNet V2 cục bộ sẵn sàng" if PAD.ready else "PAD tăng cường chưa có · Context anti-spoof đa khung đang hoạt động"},
        {"key": "templates", "label": "FaceID Templates", "ok": bool(templates.get("ready", True)), "detail": f"{templates.get('students',0)} nhân viên / {templates.get('template_vectors',0)} vector"},
        {"key": "database", "label": "Database", "ok": bool(raw_storage.get("db_path")), "detail": "PostgreSQL" if runtime_config.DB_MODE == "postgres" else "SQLite"},
        {"key": "storage", "label": "Dung lượng", "ok": int(storage.get("free_bytes") or 0) > 512 * 1024 * 1024, "detail": f"Còn {round(int(storage.get('free_bytes') or 0)/1024/1024/1024,1)} GB"},
        {"key": "identity", "label": "Identity Engine", "ok": True, "detail": f"Tracks {len(identity.get('tracks') or [])} · FaceID only"},
        {"key": "backup", "label": "Backup", "ok": bool(storage.get("backup_count")), "detail": storage.get("last_backup_at") or "Chưa có bản sao lưu"},
    ]
    return {
        "ok": all(c["ok"] for c in checks if c["key"] != "backup"),
        "checks": checks,
        "camera": cam,
        "identity": {"mode": "IDENTITY_ONLY", "tracks": len(identity.get("tracks") or []), "frame_width": identity.get("frame_width", 0), "frame_height": identity.get("frame_height", 0)},
        "storage": storage,
        "auth": {"configured": user_count() > 0},
        "generated_at": utc_now(),
    }


@app.post("/api/v1/system/self-test")
def system_self_test(request: Request, ):
    # The self-test is non-destructive: it checks actual runtime state rather than
    # taking over the camera or writing fake attendance data.
    _auth_permission(request, "system.diagnostics")
    result = system_diagnostics(request)
    allowed_checks = {"camera", "camera_quality", "face_detector", "passive_pad", "templates", "database", "storage", "identity", "backup"}
    safe_checks = [{"key": check["key"], "ok": check["ok"]} for check in result.get("checks", [])
                   if isinstance(check, dict) and check.get("key") in allowed_checks and type(check.get("ok")) is bool]
    add_audit_event("SYSTEM", "SELF_TEST", "SUCCESS" if result.get("ok") else "WARNING", detail={"checks": safe_checks})
    return result


@app.get("/api/v1/system/diagnostics/performance")
def system_performance_diagnostics(request: Request):
    _auth_permission(request, "system.diagnostics")
    result = collect_performance_diagnostics(CAMERA, MEDIA_GATEWAY, RECORDER_V4, FLEET_V4, PILOT)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/api/v1/production/status")
def production_status(request: Request):
    _auth_user(request, {"ADMIN"})
    return PILOT.status()


@app.get("/api/v1/production/config")
def production_config(request: Request):
    _auth_user(request, {"ADMIN"})
    return {"config": PILOT.config(), "status": PILOT.status()}


@app.put("/api/v1/production/config")
def production_config_update(payload: ProductionPilotConfigPayload, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    config = PILOT.save_config(payload.model_dump())
    add_audit_event("SYSTEM", "PRODUCTION_CONFIG_CHANGED", "SUCCESS", detail={"actor": actor.get("username"), "config": config})
    return {"ok": True, "config": config, "status": PILOT.force_check()}


@app.post("/api/v1/production/check")
def production_check(request: Request):
    _auth_user(request, {"ADMIN"})
    return PILOT.force_check()


@app.post("/api/v1/production/recover-camera")
def production_recover_camera(request: Request):
    actor = _auth_user(request, {"ADMIN"})
    try:
        result = PILOT.recover_camera_now()
    except Exception as exc:
        add_audit_event("SYSTEM", "PRODUCTION_CAMERA_RECOVERY", "FAILED", camera_source=CAMERA.event_camera_source(), detail={"actor": actor.get("username"), "error": str(exc)})
        raise HTTPException(500, f"Không thể phục hồi camera: {exc}")
    add_audit_event("SYSTEM", "PRODUCTION_CAMERA_RECOVERY", "SUCCESS", camera_source=CAMERA.event_camera_source(), detail={"actor": actor.get("username")})
    return result


@app.get("/api/v1/office/gate/test")
def office_gate_test(request: Request):
    _auth_user(request, {"ADMIN"})
    cfg = OFFICE.config()
    line = dict(cfg.get("line") or {})
    office = OFFICE.status()
    cam = CAMERA.status()
    identity = CAMERA.latest_result()
    configured = bool(line.get("configured"))
    enabled = bool(line.get("enabled"))
    camera_binding = str(line.get("camera_source_fingerprint") or "")
    current_source = normalize_camera_source(str(cam.get("source") or ""))
    import hashlib
    current_fp = hashlib.sha256(current_source.encode("utf-8", errors="ignore")).hexdigest()[:16] if current_source else ""
    camera_match = (not camera_binding) or camera_binding == current_fp
    reasons = []
    if not configured: reasons.append("Chưa vẽ đường ảo")
    if not enabled: reasons.append("Đường ảo chưa bật")
    if not bool(cam.get("opened")): reasons.append("Camera chưa online")
    if not camera_match: reasons.append("Virtual Gate thuộc camera khác")
    tracks = list(identity.get("tracks") or [])
    result = {
        "ok": bool(configured and enabled and cam.get("opened") and camera_match),
        "configured": configured,
        "enabled": enabled,
        "camera_match": camera_match,
        "camera": cam.get("source_label") or "Camera",
        "camera_id": line.get("camera_id"),
        "camera_name": line.get("camera_name") or "",
        "zone_name": line.get("zone_name") or "",
        "visible_tracks": len(tracks),
        "active_track_states": int(office.get("active_track_states") or 0),
        "crossing_total_runtime": int(office.get("crossing_total_runtime") or 0),
        "reasons": reasons,
        "line": line,
    }
    return result


@app.get("/api/v1/backups")
def backups_list(request: Request):
    _auth_user(request, {"ADMIN"})
    return {"items": list_backups(), "storage": storage_status()}


@app.post("/api/v1/backups")
def backups_create(request: Request):
    actor = _auth_user(request, {"ADMIN"})
    result = create_backup("manual")
    add_audit_event("SYSTEM", "BACKUP_CREATED", "SUCCESS", detail={"actor": actor.get("username"), "name": result["name"]})
    return result


@app.get("/api/v1/backups/{name}")
def backups_download(name: str, request: Request):
    _auth_user(request, {"ADMIN"})
    try:
        path = backup_path(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(path, filename=path.name, media_type="application/zip")


@app.post("/api/v1/backups/import/{name}")
async def backups_import(name: str, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    data = await request.body()
    try:
        result = import_backup(name, data)
    except (ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "BACKUP_IMPORTED", "SUCCESS", detail={"actor": actor.get("username"), "name": result["name"]})
    return result


@app.post("/api/v1/backups/{name}/restore")
def backups_restore(name: str, request: Request):
    actor = _auth_user(request, {"ADMIN"})
    try:
        result = restore_backup(name)
        INDEX.invalidate()
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "BACKUP_RESTORED", "SUCCESS", detail={"actor": actor.get("username"), "name": name, "restart_required": True})
    return result


# --------------------------- BTMH V5 production domain ---------------------------

@app.get("/api/v1/stores")
def stores_v5(request: Request):
    actor = _auth_permission(request, "dashboard.view")
    allowed = scoped_store_ids(actor)
    return {"items": [store for store in list_stores() if allowed is None or int(store["id"]) in allowed]}


@app.post("/api/v1/stores")
def create_store_v5(payload: StoreCreatePayload, request: Request):
    actor = _auth_permission(request, "system.manage")
    try:
        row = create_store(payload.store_code, payload.store_name, payload.timezone_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "STORE_CREATED", "SUCCESS", detail={"actor": actor.get("username"), "store_code": row.get("store_code")})
    return {"ok": True, "store": row}


@app.get("/api/v1/work-shifts")
def work_shifts_v5(request: Request, store_id: int | None = None):
    actor = _auth_permission(request, "attendance.view")
    if store_id is not None:
        _require_store_scope(actor, store_id)
    allowed = scoped_store_ids(actor)
    return {"items": [row for row in list_shifts(store_id)
                      if allowed is None or row.get("store_id") in allowed]}


@app.put("/api/v1/work-shifts")
def save_work_shift_v5(payload: ShiftV5Payload, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    _require_store_scope(actor, payload.store_id)
    if payload.id is not None:
        existing = fetchone("SELECT store_id FROM work_shifts WHERE id=?", (payload.id,))
        if existing:
            _require_store_scope(actor, existing.get("store_id"))
    try:
        row = save_shift_v5(payload.model_dump(), str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("HR", "WORK_SHIFT_SAVED", "SUCCESS", detail={"actor": actor.get("username"), "shift_id": row.get("id"), "shift_code": row.get("shift_code")})
    return {"ok": True, "shift": row}


@app.put("/api/v1/employees/{student_id}/shift")
def assign_employee_shift_v5(student_id: int, payload: ShiftAssignPayload, request: Request):
    actor = _auth_permission(request, "attendance.manage")
    _require_employee_scope(actor, student_id)
    shift = fetchone("SELECT store_id FROM work_shifts WHERE id=?", (payload.shift_id,))
    if shift:
        _require_store_scope(actor, shift.get("store_id"))
    try:
        row = assign_employee_shift(student_id, payload.shift_id, str(actor.get("username") or ""), payload.effective_from)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("HR", "EMPLOYEE_SHIFT_ASSIGNED", "SUCCESS", student_id=int(student_id), detail={"actor": actor.get("username"), "shift_id": payload.shift_id})
    return {"ok": True, "assignment": row}


@app.get("/api/v1/employees/{student_id}/shift")
def employee_shift_v5(student_id: int, request: Request):
    actor = _auth_permission(request, "attendance.view")
    _require_employee_scope(actor, student_id)
    return {"assignment": employee_shift(student_id)}


@app.get("/api/v1/attendance/corrections")
def attendance_corrections_v5(request: Request, student_id: int | None = None, limit: int = 200):
    actor = _auth_permission(request, "attendance.view")
    if student_id is not None:
        _require_employee_scope(actor, student_id)
    rows = list_attendance_corrections(student_id, limit)
    allowed = scoped_store_ids(actor)
    if allowed is not None:
        employee_ids = {int(row["student_id"]) for row in
                        fetchall("SELECT student_id,store_id FROM employee_store_assignments")
                        if int(row["store_id"]) in allowed}
        rows = [row for row in rows if int(row["student_id"]) in employee_ids]
    return {"items": rows}


@app.post("/api/v1/attendance/corrections")
def attendance_correction_create_v5(payload: AttendanceCorrectionV5Payload, request: Request):
    actor = _auth_permission(request, "attendance.adjust")
    _require_employee_scope(actor, payload.student_id)
    try:
        row = create_attendance_correction(payload.model_dump(), str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("HR", "ATTENDANCE_CORRECTION_CREATED", "SUCCESS", student_id=int(payload.student_id), detail={
        "actor": actor.get("username"), "work_date": payload.work_date, "reason": payload.reason,
        "effective_checkin_at": payload.effective_checkin_at, "effective_checkout_at": payload.effective_checkout_at,
    })
    return {"ok": True, "correction": row}


@app.get("/api/v1/incidents")
def incidents_v5(request: Request, status: str = "", limit: int = 200):
    _auth_permission(request, "incident.view")
    return {"items": list_incidents(status, limit)}


@app.post("/api/v1/incidents")
def incidents_create_v5(payload: IncidentCreatePayload, request: Request):
    actor = _auth_permission(request, "incident.manage")
    data = payload.model_dump()
    if not data.get("occurred_at"):
        data["occurred_at"] = utc_now()
    try:
        row = create_incident(data, str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "INCIDENT_CREATED", "SUCCESS", detail={"actor": actor.get("username"), "incident_id": row.get("incident_id"), "title": row.get("title")})
    return {"ok": True, "incident": row}


@app.get("/api/v1/incidents/{incident_id}")
def incident_get_v5(incident_id: str, request: Request):
    _auth_permission(request, "incident.view")
    row = get_incident(incident_id)
    if not row:
        raise HTTPException(404, "Không tìm thấy sự cố")
    return row


@app.post("/api/v1/incidents/{incident_id}/evidence")
def incident_add_evidence_v5(incident_id: str, payload: IncidentEvidencePayload, request: Request):
    actor = _auth_permission(request, "incident.manage")
    try:
        row = add_incident_evidence(incident_id, payload.evidence_type, payload.evidence_ref, str(actor.get("username") or ""), payload.camera_source, payload.captured_at, payload.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "INCIDENT_EVIDENCE_ADDED", "SUCCESS", detail={"actor": actor.get("username"), "incident_id": incident_id, "evidence_type": payload.evidence_type})
    return {"ok": True, "evidence": row}


@app.post("/api/v1/incidents/{incident_id}/lock")
def incident_lock_v5(incident_id: str, request: Request):
    actor = _auth_permission(request, "incident.manage")
    try:
        row = lock_incident_evidence(incident_id, str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "INCIDENT_EVIDENCE_LOCKED", "SUCCESS", detail={"actor": actor.get("username"), "incident_id": incident_id})
    return {"ok": True, "incident": row}


@app.get("/api/v1/video/clips")
def video_clips_v5(request: Request, limit: int = 200):
    _auth_permission(request, "camera.playback")
    return {"items": list_video_clips(limit)}


@app.post("/api/v1/video/clips")
def video_clip_create_v5(payload: VideoClipCreatePayload, request: Request):
    actor = _auth_permission(request, "video.clip")
    try:
        row = create_video_clip(payload.segment_id, payload.start_at, payload.end_at, str(actor.get("username") or ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SECURITY", "VIDEO_CLIP_CREATED", "SUCCESS", camera_source=str(row.get("camera_source") or ""), detail={"actor": actor.get("username"), "clip_id": row.get("clip_id"), "status": row.get("status")})
    return {"ok": True, "clip": row}


@app.get("/api/v1/sync/status")
def sync_status_v5(request: Request):
    _auth_permission(request, "system.manage")
    return {**sync_status(), "worker": EDGE_SYNC_WORKER.status()}


@app.get("/api/v1/sync/nodes")
def sync_nodes_v5(request: Request):
    _auth_permission(request, "system.manage")
    stores = {int(x.get("id") or 0): x for x in list_stores()}
    items = list_edge_nodes()
    for item in items:
        store = stores.get(int(item.get("store_id") or 0)) or {}
        item["store_code"] = store.get("store_code") or ""
        item["store_name"] = store.get("store_name") or ""
    return {"items": items, "stores": list(stores.values()), "generated_at": utc_now()}


@app.post("/api/v1/sync/nodes")
def sync_register_node_v5(payload: EdgeNodeRegisterPayload, request: Request):
    actor = _auth_permission(request, "system.manage")
    try:
        node = register_edge_node(payload.node_id, payload.node_name, payload.store_id, payload.public_key_b64)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "EDGE_NODE_REGISTERED", "SUCCESS", detail={"actor": actor.get("username"), "node_id": node.get("node_id"), "store_id": node.get("store_id"), "key_fingerprint": node.get("key_fingerprint")})
    return {"ok": True, "node": node}


@app.post("/api/v1/sync/nodes/{node_id}/revoke")
def sync_revoke_node_v5(node_id: str, request: Request):
    actor = _auth_permission(request, "system.manage")
    try:
        node = revoke_edge_node(node_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "EDGE_NODE_REVOKED", "SUCCESS", detail={"actor": actor.get("username"), "node_id": node_id})
    return {"ok": True, "node": node}


@app.get("/api/v1/sync/outbox")
def sync_outbox_v5(request: Request, limit: int = 100, store_id: int | None = None):
    _auth_permission(request, "system.manage")
    return {"items": pending_sync_batch(limit, store_id)}


@app.post("/api/v1/sync/outbox/ack")
def sync_outbox_ack_v5(payload: SyncAckPayload, request: Request):
    actor = _auth_permission(request, "system.manage")
    updated = mark_sync_result(payload.event_ids, success=payload.success, error=payload.error)
    add_audit_event("SYSTEM", "SYNC_OUTBOX_ACK", "SUCCESS" if payload.success else "RETRY", detail={"actor": actor.get("username"), "count": updated})
    return {"ok": True, "updated": updated}


@app.post("/api/v1/sync/receive")
async def sync_receive_v5(payload: SyncReceivePayload, request: Request):
    # This route intentionally does not use a browser/admin session. Edge nodes
    # authenticate using their registered Ed25519 public key. Central never stores
    # the Edge private key. Timestamp + nonce protection blocks captured replay.
    body = await request.body()
    node_id = str(request.headers.get("X-BTMH-Edge-Node") or "").strip()
    try:
        edge = authenticate_edge_request(
            node_id=node_id,
            timestamp=str(request.headers.get("X-BTMH-Edge-Timestamp") or ""),
            nonce=str(request.headers.get("X-BTMH-Edge-Nonce") or ""),
            signature=str(request.headers.get("X-BTMH-Edge-Signature") or ""),
            method=request.method,
            path=request.url.path,
            body=body,
        )
    except EdgeAuthError as exc:
        raise HTTPException(401, str(exc))
    if str(payload.source_node_id or "").strip() != node_id:
        raise HTTPException(400, "source_node_id không khớp Edge identity")
    try:
        result = receive_sync_batch(node_id, payload.events)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    add_audit_event("SYSTEM", "SYNC_BATCH_RECEIVED", "SUCCESS", detail={"source_node_id": node_id, "store_id": edge.get("store_id"), "received": result.get("received"), "duplicates": len(result.get("duplicates") or []), "conflicts": len(result.get("conflicts") or []), "rejected": len(result.get("rejected") or [])})
    return result


@app.post("/api/v1/sync/heartbeat")
async def sync_heartbeat_v5(payload: EdgeHeartbeatPayload, request: Request):
    # Same device-authenticated trust boundary as /sync/receive. The browser never
    # calls this route; Edge nodes sign the raw request with their local private key.
    body = await request.body()
    node_id = str(request.headers.get("X-BTMH-Edge-Node") or "").strip()
    try:
        edge = authenticate_edge_request(
            node_id=node_id,
            timestamp=str(request.headers.get("X-BTMH-Edge-Timestamp") or ""),
            nonce=str(request.headers.get("X-BTMH-Edge-Nonce") or ""),
            signature=str(request.headers.get("X-BTMH-Edge-Signature") or ""),
            method=request.method,
            path=request.url.path,
            body=body,
        )
    except EdgeAuthError as exc:
        raise HTTPException(401, str(exc))
    if str(payload.source_node_id or "").strip() != node_id:
        raise HTTPException(400, "source_node_id không khớp Edge identity")
    try:
        health = update_edge_heartbeat(node_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "node_id": node_id, "store_id": edge.get("store_id"), "heartbeat": health, "server_time": utc_now()}


@app.get("/api/v1/module/contract")
def module_contract():
    return {
        "module": "btmh-security-v5-production",
        "version": APP_VERSION,
        "offline_edge_runtime": True,
        "architecture": "edge-ai + central management / store_id-ready / local-first; durable outbox + signed Edge push worker + idempotent Central receipt implemented; production transport requires HTTPS; mTLS remains optional deployment hardening",
        "camera": "multi-source / laptop + rtsp / safe handover / multi-camera fleet / recording separated from ai",
        "recognition": "identity-first / employee-name-or-customer / multi-frame consensus / passive anti-spoof / best-face evidence",
        "enrollment": "guided multi-angle / quality filtering / multi-template / duplicate guard with human confirmation / store-camera validation",
        "attendance": "shift-driven / automatic camera events / auditable human corrections without overwriting originals",
        "video": "local-or-nvr index / event-linked playback / clip creation / incident evidence lock",
        "auth": "first-run super-admin / phone OTP registration / pending approval / RBAC permissions / password recovery OTP",
        "action_ai": False,
        "legacy_action_ai_runtime": False,
    }


# BTMH Security V5.4 customer-release hardening.
install_sms_routes(app, _request_user, _request_token, AUTH_COOKIE)
install_qr_routes(app, FRONTEND, _auth_permission)
if UI_PREVIEW:
    app.add_middleware(LocalPreviewMiddleware)

try:
    from .security_hardening_v54 import install_v54_hardening, protect_status_provider
except ImportError:  # Support direct module execution used by legacy launchers.
    from module_app.security_hardening_v54 import install_v54_hardening, protect_status_provider

install_v54_hardening(app)
try:
    protect_status_provider(CAMERA)
except NameError:
    pass

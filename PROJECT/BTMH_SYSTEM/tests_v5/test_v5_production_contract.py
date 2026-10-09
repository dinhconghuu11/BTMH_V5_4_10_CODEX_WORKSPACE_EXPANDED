from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APPJS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
V4JS = (ROOT / "frontend" / "js" / "btmh_v4.js").read_text(encoding="utf-8")
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
AUTH = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")
OTP = (ROOT / "module_app" / "otp_service.py").read_text(encoding="utf-8")
PLATFORM = (ROOT / "module_app" / "platform_v5.py").read_text(encoding="utf-8")
REGISTRY = (ROOT / "module_app" / "registry.py").read_text(encoding="utf-8")
VISITOR = (ROOT / "module_app" / "visitor.py").read_text(encoding="utf-8")
WALKBY = (ROOT / "module_app" / "walkby.py").read_text(encoding="utf-8")
REQ = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")
CONFIG = (ROOT / "module_app" / "config.py").read_text(encoding="utf-8")


def test_version_consistent_v5_preview():
    root_version = (PROJECT / "VERSION.txt").read_text(encoding="utf-8").strip()
    core_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert root_version == core_version == "5.4.1-customer-ui-hardening"
    assert 'APP_VERSION = "5.4.1-customer-ui-hardening"' in CONFIG


def test_seven_primary_navigation_items_are_business_focused():
    nav = re.search(r'<nav[^>]+v5-primary-nav[\s\S]*?</nav>', HTML)
    assert nav
    block = nav.group(0)
    expected = [
        "Tổng quan", "Nhân sự", "Quan sát cửa hàng", "Nhận diện &amp; Ra/Vào",
        "Xem lại camera", "Lịch sử &amp; Báo cáo", "Sự cố &amp; Bằng chứng",
    ]
    assert block.count('class="nav-item') == 7
    for label in expected:
        assert label in block
    for legacy in ("Theo dõi AI", "Giơ tay", "Cúi đầu", "Nghi điện thoại", "Classroom"):
        assert legacy not in block


def test_camera_source_manager_supports_laptop_and_store_sources():
    assert 'id="v5ActiveCameraSelect"' in HTML
    assert 'id="v5EnrollmentCameraSelect"' in HTML
    assert "Laptop Camera" in HTML
    assert "switchCameraSource" in V4JS
    assert "/api/v1/camera/select" in V4JS
    assert "safe handover" in MAIN.lower() or "safe handover" in V4JS.lower() or "handover" in V4JS.lower()


def test_enrollment_is_guided_quality_filtered_and_multi_angle():
    for label in ("Chính diện", "Nghiêng trái", "Nghiêng phải", "Hơi cúi", "Hơi ngẩng"):
        assert label in HTML
    assert "8–12" in HTML
    assert "quality" in REGISTRY.lower()
    assert "pose" in REGISTRY.lower()


def test_duplicate_face_guard_requires_human_confirmation():
    assert "DUPLICATE_WARN_SCORE" in REGISTRY
    assert "requires_duplicate_confirmation" in REGISTRY
    assert "confirm_duplicate" in REGISTRY
    assert "requires_duplicate_confirmation" in APPJS
    assert 'id="v5DuplicateFaceModal"' in HTML
    assert "vẫn lưu" in HTML


def test_store_camera_faceid_validation_is_implemented():
    assert "CREATE TABLE IF NOT EXISTS face_enrollment_validations" in PLATFORM
    assert '@app.post("/api/v1/employees/{student_id}/face-validation")' in MAIN
    assert "STORE_CAMERA_VALIDATION_SUCCESS" in MAIN
    assert 'id="v5ValidateStoreCameraBtn"' in HTML
    assert "validateEnrollmentOnStoreCamera" in APPJS
    assert "PENDING_STORE_VALIDATION" in MAIN


def test_employee_ui_exposes_validation_state_not_false_ready_state():
    assert "faceValidationMeta" in APPJS
    assert "Chờ xác minh camera" in APPJS
    assert "Đã xác minh camera" in APPJS


def test_best_face_evidence_keeps_multiple_quality_shots_and_video_linkage():
    # Visitor session/evidence contract: multiple best shots and video references.
    assert "best" in VISITOR.lower()
    assert "video" in VISITOR.lower() or "segment" in VISITOR.lower()
    assert "sharp" in WALKBY.lower() or "quality" in WALKBY.lower()
    assert "best_shots" in WALKBY or "best shots" in WALKBY.lower() or "best_shot" in WALKBY
    assert "resolve_event_video" in MAIN


def test_shift_and_attendance_correction_preserve_original_values():
    assert "CREATE TABLE IF NOT EXISTS work_shifts" in PLATFORM
    assert "CREATE TABLE IF NOT EXISTS attendance_corrections_v5" in PLATFORM
    for field in ("original_checkin_at", "original_checkout_at", "effective_checkin_at", "effective_checkout_at", "reason", "approved_by"):
        assert field in PLATFORM
    assert "Điều chỉnh chấm công có audit" in HTML


def test_playback_clip_and_incident_evidence_lock_exist():
    assert 'id="v5CreateClipBtn"' in HTML
    assert "CREATE TABLE IF NOT EXISTS video_clips" in PLATFORM
    assert "CREATE TABLE IF NOT EXISTS incidents" in PLATFORM
    assert "CREATE TABLE IF NOT EXISTS incident_evidence" in PLATFORM
    assert "VIDEO_CLIP" in PLATFORM and "VIDEO_SEGMENT" in PLATFORM
    assert "protected=1" in PLATFORM
    assert "Evidence Lock" in HTML


def test_auth_registration_requires_phone_email_otp_and_pending_approval():
    for element_id in ("gateRegisterUsername", "gateRegisterDisplay", "gateRegisterPhone", "gateRegisterEmail", "gateRegisterPassword", "gateRegisterPassword2", "gateRegisterOtp"):
        assert f'id="{element_id}"' in HTML
    assert '@app.post("/api/v1/auth/register/request-otp")' in MAIN
    assert '@app.post("/api/v1/auth/register/verify-otp")' in MAIN
    assert 'status="PENDING"' in AUTH or 'status="PENDING"' in MAIN or '"PENDING"' in AUTH
    assert "approve_user" in MAIN


def test_first_run_super_admin_is_otp_bootstrapped_and_not_default_password():
    assert "Tạo SUPER ADMIN" in HTML
    assert '@app.post("/api/v1/auth/bootstrap/request-otp")' in MAIN
    assert '@app.post("/api/v1/auth/bootstrap/verify-otp")' in MAIN
    assert '"SUPER_ADMIN"' in AUTH
    assert "admin123" not in AUTH.lower()
    assert "admin123" not in MAIN.lower()


def test_forgot_password_uses_verified_phone_otp_and_revokes_sessions():
    assert "Quên mật khẩu" in HTML
    assert '@app.post("/api/v1/auth/forgot/request-otp")' in MAIN
    assert '@app.post("/api/v1/auth/forgot/verify-otp")' in MAIN
    assert "PASSWORD_RESET" in MAIN
    assert "_sessions.pop" in AUTH


def test_otp_security_limits_and_hashing():
    assert "OTP_TTL_SECONDS = 300" in OTP
    assert "OTP_RESEND_SECONDS = 60" in OTP
    assert "OTP_MAX_ATTEMPTS = 5" in OTP
    assert "OTP_MAX_PER_HOUR = 6" in OTP
    assert "pbkdf2_hmac" in OTP
    assert "otp_hash" in OTP
    assert "consumed" in OTP


def test_passwords_use_argon2id_for_new_credentials_and_minimum_10_for_primary_flows():
    assert "argon2-cffi==25.1.0" in REQ
    assert 'return "ARGON2ID"' in AUTH
    assert "_new_password(password, 10)" in AUTH
    assert 'minlength="10"' in HTML


def test_browser_auth_is_http_only_cookie_first():
    assert "httponly=True" in MAIN
    assert 'samesite="strict"' in MAIN
    assert 'secure=request.url.scheme == "https"' in MAIN
    assert "do not persist bearer tokens in localStorage" in APPJS


def test_rbac_has_store_security_hr_and_admin_roles_with_granular_permissions():
    for role in ("SUPER_ADMIN", "ADMIN", "MANAGER", "HR", "SECURITY", "TECHNICIAN", "EMPLOYEE"):
        assert f'"{role}"' in AUTH
    for permission in ("employee.manage", "employee.enroll", "attendance.adjust", "camera.live", "camera.playback", "video.clip", "incident.manage", "account.approve"):
        assert permission in AUTH
    assert ".permission-locked" in (ROOT / "frontend" / "css" / "btmh_v5_production.css").read_text(encoding="utf-8")


def test_multi_store_schema_and_central_transport_are_present():
    assert "CREATE TABLE IF NOT EXISTS stores" in PLATFORM
    assert "employee_store_assignments" in PLATFORM
    assert "camera_store_assignments" in PLATFORM
    assert "store_id" in AUTH
    assert "signed Edge push worker" in MAIN
    assert "production transport requires HTTPS" in MAIN


def test_internal_api_has_default_auth_gate_and_websockets_require_session():
    assert "path.startswith(\"/api/v1/\")" in MAIN
    assert "PUBLIC_API_PATHS" in MAIN
    assert "_request_user(request) is None" in MAIN
    assert MAIN.count("_websocket_user(websocket) is None") == MAIN.count("@app.websocket")
    assert MAIN.count("@app.websocket") >= 3


def test_html_ids_are_unique():
    ids = re.findall(r'\bid="([^"]+)"', HTML)
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    assert dupes == []

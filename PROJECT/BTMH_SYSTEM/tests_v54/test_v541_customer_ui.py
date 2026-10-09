from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
AUTH = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")


def test_customer_brand_and_auth_assets_present():
    assert "Bảo Tín Mạnh Hải" in HTML
    assert "/static/img/btmh_official_logo.png" in HTML
    assert "/static/img/btmh_emblem.png" in HTML
    assert (ROOT / "frontend" / "css" / "btmh_customer_v541.css").exists()
    assert (ROOT / "frontend" / "js" / "btmh_customer_v541.js").exists()


def test_customer_ui_hides_build_and_development_labels():
    forbidden = [
        "BTMH Security V5.4",
        "Identity · Camera · Evidence",
        "OPERATIONS PROFESSIONAL",
        "OTP DELIVERY",
        "Gửi OTP SMS",
        "Gửi OTP Email",
        "SUPER_ADMIN -",
    ]
    for value in forbidden:
        assert value not in HTML


def test_public_registration_removed_from_visible_auth_flow():
    assert 'id="gateRegisterView"' not in HTML
    assert 'id="gateRegisterForm"' not in HTML
    assert 'id="openRegisterBtn"' not in HTML
    assert "gateRegister(" not in APP_JS
    assert "BTMH_PUBLIC_REGISTRATION=0" in (ROOT / ".env.customer.example").read_text(encoding="utf-8")


def test_first_run_owner_is_local_and_no_longer_forces_totp_setup():
    assert '@app.post("/api/v1/auth/bootstrap-local")' in MAIN
    assert 'host not in {"127.0.0.1", "::1", "localhost"}' in MAIN
    assert "_new_mfa_challenge(row, setup=False)" in AUTH
    assert "sms.begin_login(row, binding)" in AUTH
    assert "/api/v1/auth/bootstrap-local" in APP_JS
    assert "/api/v1/auth/mfa/verify" in APP_JS


def test_sms_email_otp_is_not_part_of_visible_login():
    assert 'id="gateMfaMethodBox"' not in HTML
    assert 'id="gateMfaOtpBox"' not in HTML
    assert 'id="otpProviderPanel"' not in HTML
    assert 'id="adminSecurityVerifyPhone"' not in HTML
    assert 'id="adminSecurityVerifyEmail"' not in HTML


def test_customer_navigation_is_simplified():
    assert "Camera &amp; giám sát" in HTML
    assert 'data-nav-cluster="camera"' in HTML
    assert "Tài khoản &amp; phân quyền" in HTML
    assert "Cài đặt hệ thống" in HTML


def test_customer_roles_are_defined():
    for role, label in [
        ("SUPER_ADMIN", "Chủ sở hữu"),
        ("ADMIN", "Quản trị viên"),
        ("MANAGER", "Quản lý cửa hàng"),
        ("HR", "Nhân sự"),
        ("SECURITY", "Giám sát / Bảo vệ"),
        ("EMPLOYEE", "Nhân viên"),
    ]:
        assert f'"{role}": {{"label": "{label}"' in AUTH


def test_backend_enforces_strong_customer_passwords():
    assert "def _validate_password_strength" in AUTH
    assert "_validate_password_strength(password, 12)" in AUTH


def test_hr_does_not_receive_camera_control_permission():
    hr_start = AUTH.index('"HR": {')
    hr_end = AUTH.index('},', hr_start)
    assert '"camera.switch"' not in AUTH[hr_start:hr_end]


def test_management_portal_denies_employee_role():
    assert "role==='EMPLOYEE'" in APP_JS
    assert "Tài khoản Nhân viên không có quyền vào trang quản lý" in APP_JS
    employee_start = AUTH.index('"EMPLOYEE": {')
    employee_end = AUTH.index('},', employee_start)
    assert '"dashboard.view"' not in AUTH[employee_start:employee_end]


def test_manager_cannot_manage_system_accounts():
    manager_start = AUTH.index('"MANAGER": {')
    manager_end = AUTH.index('},', manager_start)
    assert '"account.approve"' not in AUTH[manager_start:manager_end]


def test_all_private_browser_routes_are_permission_mapped():
    from module_app.main import app, _api_permission_for, PUBLIC_API_PATHS, MOBILE_PUBLIC_API_PATHS

    missing = []
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", None) or {"GET"}) - {"OPTIONS"}
        if not path.startswith("/api/v1/"):
            continue
        if path in PUBLIC_API_PATHS or path in MOBILE_PUBLIC_API_PATHS or path.startswith("/api/v1/mobile/"):
            continue
        for method in methods:
            if _api_permission_for(path, method) is None:
                missing.append(f"{method} {path}")
    assert missing == []


def test_setup_state_is_fail_closed_for_private_api():
    assert "Hệ thống chưa được thiết lập Chủ sở hữu" in MAIN
    assert "API chưa được khai báo quyền truy cập" in MAIN
    assert "has_permission(user, required_permission)" in MAIN


def test_legacy_sms_email_otp_api_is_disabled_by_default():
    env = (ROOT / ".env.customer.example").read_text(encoding="utf-8")
    assert "BTMH_LEGACY_OTP_ENABLED=0" in env
    assert "LEGACY_OTP_API_PATHS" in MAIN
    assert "Kênh OTP SMS/Email không được kích hoạt" in MAIN

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APPJS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
OTP = (ROOT / "module_app" / "otp_service.py").read_text(encoding="utf-8")


def test_admin_security_is_dedicated_module_not_system_panel():
    assert 'id="page-admin-security"' in HTML
    assert 'id="adminSecurityNav"' in HTML
    assert 'Quản trị &amp; bảo mật' in HTML
    system = re.search(r'<section class="page" id="page-system">([\s\S]*?)</section>', HTML)
    assert system
    assert 'id="adminSecurityPanel"' not in system.group(1)
    admin = re.search(r'<section class="page v537-admin-security-page" id="page-admin-security">([\s\S]*?)<section class="page" id="page-system">', HTML)
    assert admin and 'id="adminSecurityPanel"' in admin.group(1)


def test_admin_navigation_and_first_login_route_target_dedicated_module():
    assert "'admin-security': ['Quản trị & bảo mật'" in APPJS
    assert "if(page==='admin-security'){loadAdminSecurityModule();}" in APPJS
    assert "navigate('admin-security')" in APPJS
    assert "window.openCurrentAccountModule=openCurrentAccountModule" in APPJS


def test_real_otp_provider_ui_and_backend_contract_exist():
    for element_id in (
        'otpProviderPanel','otpSmsProvider','otpSmsWebhookUrl','otpSmsAccountSid','otpSmsSecret',
        'otpEmailProvider','otpSmtpHost','otpSmtpPort','otpSmtpUsername','otpSmtpFrom','otpSmtpPassword',
        'otpSmsTestBtn','otpEmailTestBtn','otpProviderSave',
    ):
        assert f'id="{element_id}"' in HTML
    assert '@app.put("/api/v1/auth/admin-security/otp-provider")' in MAIN
    assert '@app.post("/api/v1/auth/admin-security/otp-provider/test")' in MAIN
    assert 'Chỉ SUPER_ADMIN được thay đổi nhà cung cấp OTP toàn hệ thống' in MAIN


def test_email_smtp_and_sms_webhook_twilio_delivery_are_implemented():
    assert 'smtplib.SMTP' in OTP
    assert 'smtplib.SMTP_SSL' in OTP
    assert 'provider == "WEBHOOK"' in OTP
    assert 'provider == "TWILIO"' in OTP
    assert 'api.twilio.com/2010-04-01/Accounts/' in OTP
    assert 'Authorization"] = "Bearer " + token' in OTP


def test_provider_secrets_use_dpapi_and_are_not_returned_plaintext():
    assert 'save_secret(SMS_SECRET_PATH, sms_secret, machine_scope=True)' in OTP
    assert 'save_secret(SMTP_SECRET_PATH, smtp_password, machine_scope=True)' in OTP
    public_fn = OTP.split('def delivery_config_public()',1)[1].split('def save_delivery_config',1)[0]
    assert '"secret_configured"' in public_fn
    assert '"password_configured"' in public_fn
    assert '"password":' not in public_fn
    assert '"secret":' not in public_fn


def test_demo_is_explicit_and_real_delivery_status_is_channel_specific():
    assert '"real_delivery": sms_real' in OTP
    assert '"real_delivery": email_real' in OTP
    assert '"demo": not sms_real and not email_real' in OTP
    assert 'DEMO — chưa gửi ra ngoài' in APPJS

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
AUTH = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")
OTP = (ROOT / "module_app" / "otp_service.py").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")


def test_privileged_admin_uses_verified_sms_or_email_otp_after_first_login():
    assert 'CREATE TABLE IF NOT EXISTS privileged_security_profiles' in AUTH
    assert 'second_factor_required' in AUTH
    assert '@app.post("/api/v1/auth/2fa/request-otp")' in MAIN
    assert '@app.post("/api/v1/auth/2fa/verify")' in MAIN
    assert '@app.post("/api/v1/auth/admin-security/request-otp")' in MAIN
    assert '@app.post("/api/v1/auth/admin-security/verify-otp")' in MAIN
    assert 'BTMH_SMS_PROVIDER' in OTP and 'BTMH_EMAIL_PROVIDER' in OTP
    assert 'BTMH_SMTP_HOST' in OTP


def test_admin_security_ui_has_inside_setup_and_login_otp_choices():
    for marker in (
        "adminSecurityPanel", "adminSecurityPhone", "adminSecurityEmail",
        "adminSecurityVerifyPhone", "adminSecurityVerifyEmail", "gateMfaMethodBox",
        "gateMfaOtpBox", "gateMfaCode",
    ):
        assert f'id="{marker}"' in HTML
    assert "/api/v1/auth/admin-security/request-otp" in JS
    assert "/api/v1/auth/2fa/request-otp" in JS
    assert "/api/v1/auth/2fa/verify" in JS
    assert "Authenticator" not in HTML[HTML.find('id="gateMfaView"'):HTML.find('v23-auth-foot')]


def test_sqlite_admin_first_login_setup_then_second_login_otp_smoke(tmp_path):
    import os, subprocess, sys, textwrap
    script = textwrap.dedent(r'''
        from module_app.db import init_db
        from module_app.production_ops import ensure_production_schema
        from module_app.auth import (
            ensure_rbac_schema, bootstrap_admin, login, logout,
            verify_privileged_security_contact, privileged_login_otp_destination,
            complete_privileged_login_challenge,
        )
        from module_app.otp_service import ensure_otp_schema, request_otp_delivery, verify_otp

        init_db(); ensure_production_schema(); ensure_rbac_schema(); ensure_otp_schema()
        root=bootstrap_admin('roototp','Root OTP','VeryStrong!2026')
        first=login('roototp','VeryStrong!2026')
        assert first['token'] and first['security_setup_required'] is True
        assert first['user']['security_setup_required'] is True
        uid=root['id']

        setup=request_otp_delivery(
            purpose='ADMIN_SECURITY_SETUP', channel='SMS', destination='0900000201',
            payload={'user_id':uid,'method':'SMS','destination':'0900000201','display_name':'Root Owner'},
        )
        verified=verify_otp(challenge_id=setup['challenge_id'],otp=setup['demo_otp'],purpose='ADMIN_SECURITY_SETUP')
        security=verify_privileged_security_contact(
            uid, method=verified['payload']['method'], destination=verified['payload']['destination'],
            display_name=verified['payload']['display_name'],
        )
        assert security['setup_completed'] is True and security['phone_verified'] is True
        logout(first['token'])

        second=login('roototp','VeryStrong!2026')
        assert second['second_factor_required'] is True and 'token' not in second
        assert second['methods'][0]['method']=='SMS'
        dest=privileged_login_otp_destination(second['challenge_id'],'SMS')
        otp=request_otp_delivery(
            purpose='ADMIN_LOGIN', channel='SMS', destination=dest['destination'],
            payload={'user_id':uid,'login_challenge_id':second['challenge_id'],'method':'SMS'},
        )
        checked=verify_otp(challenge_id=otp['challenge_id'],otp=otp['demo_otp'],purpose='ADMIN_LOGIN')
        final=complete_privileged_login_challenge(second['challenge_id'],checked['payload']['user_id'])
        assert final['token'] and final['second_factor_verified'] is True
    ''')
    env = os.environ.copy()
    env.update({
        'CAMPUSFACE_DB_MODE': 'sqlite',
        'CAMPUSFACE_DATA_ROOT': str(tmp_path / 'runtime'),
        'PYTHONPATH': str(ROOT),
        'BTMH_SMS_PROVIDER': 'DEMO',
        'BTMH_EMAIL_PROVIDER': 'DEMO',
    })
    subprocess.run([sys.executable, '-c', script], env=env, check=True, timeout=30)


def test_email_otp_delivery_demo_smoke(tmp_path):
    import os, subprocess, sys, textwrap
    script = textwrap.dedent(r'''
        from module_app.db import init_db
        from module_app.otp_service import ensure_otp_schema, request_otp_delivery, verify_otp
        init_db(); ensure_otp_schema()
        out=request_otp_delivery(purpose='EMAIL_TEST',channel='EMAIL',destination='owner@example.test',payload={'x':1})
        assert out['channel']=='EMAIL' and out['demo_otp']
        result=verify_otp(challenge_id=out['challenge_id'],otp=out['demo_otp'],purpose='EMAIL_TEST')
        assert result['ok'] and result['channel']=='EMAIL'
    ''')
    env=os.environ.copy()
    env.update({'CAMPUSFACE_DB_MODE':'sqlite','CAMPUSFACE_DATA_ROOT':str(tmp_path/'runtime'),'PYTHONPATH':str(ROOT),'BTMH_EMAIL_PROVIDER':'DEMO'})
    subprocess.run([sys.executable,'-c',script],env=env,check=True,timeout=30)

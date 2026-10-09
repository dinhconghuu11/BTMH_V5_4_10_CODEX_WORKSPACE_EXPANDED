"""Real FastAPI parser/middleware/cookies on private SQLite, no worker startup.

Requires installed application dependencies. These are ASGI/TestClient tests,
not evidence of a production camera/GPU/PostgreSQL/phone deployment.
"""
import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from module_app import auth, db, qr_enrollment
from module_app.main import app
from module_app.production_ops import ensure_production_schema

PW = "OnlyForAuthRoutingTests!550"


@pytest.fixture
def private_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "SQLITE_PATH", tmp_path / "private-auth-routing.db")
    monkeypatch.setattr(auth, "_ARGON2", PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
    monkeypatch.setenv("BTMH_PUBLIC_REGISTRATION", "0")
    monkeypatch.setenv("BTMH_QR_ENROLLMENT_ENABLED", "1")
    auth._sessions.clear()
    auth._mfa_challenges.clear()
    auth._failed_logins.clear()
    auth._session_factor_times.clear()
    auth._session_credential_tags.clear()
    db.init_db()
    ensure_production_schema()
    auth.ensure_rbac_schema()
    qr_enrollment.ensure_qr_enrollment_schema()


def client(remote=False):
    return TestClient(app, base_url="https://btmh.test", headers={"Origin": "https://btmh.test"}, client=("192.0.2.60" if remote else "127.0.0.1", 12345))


def bootstrap(browser, username="testowner"):
    return browser.post("/api/v1/auth/bootstrap-local", json={"username": username, "display_name": "Test Owner", "password": PW, "phone": ""})


def login(browser, username="testowner", password=PW):
    return browser.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_first_owner_real_cookie_logout_and_existing_owner_login(private_auth):
    browser = client()
    assert browser.get("/api/v1/auth/status").json() == {"setup_required": True, "authenticated": False, "user": None}
    response = bootstrap(browser)
    assert response.status_code == 200, response.text
    assert response.json()["created"]["role"] == "SUPER_ADMIN"
    assert response.json()["authenticated"] is True
    assert "token" not in response.json()
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    status = browser.get("/api/v1/auth/status").json()
    assert status["authenticated"] is True and status["setup_required"] is False
    assert browser.post("/api/v1/auth/logout", json={}).status_code == 200
    status = browser.get("/api/v1/auth/status").json()
    assert status["authenticated"] is False and status["setup_required"] is False
    assert login(browser).status_code == 200
    assert browser.get("/api/v1/auth/status").json()["authenticated"] is True


def test_wrong_credentials_preserve_signed_out_state_and_validation(private_auth):
    bootstrap(client())
    browser = client()
    assert login(browser, password="wrong").status_code == 401
    assert browser.get("/api/v1/auth/status").json()["authenticated"] is False
    assert browser.get("/api/v1/admin/users").status_code == 401
    assert browser.post("/api/v1/auth/login", json={"username": "testowner"}).status_code == 422


def test_remote_first_owner_setup_is_rejected(private_auth):
    response = bootstrap(client(remote=True))
    assert response.status_code == 403
    assert auth.user_count() == 0


def test_duplicate_owner_and_disabled_owner_cannot_reopen_setup(private_auth):
    browser = client()
    assert bootstrap(browser).status_code == 200
    assert bootstrap(browser, "secondowner").status_code == 409
    browser.post("/api/v1/auth/logout", json={})
    db.execute("UPDATE system_users SET active=0 WHERE username=?", ("testowner",))
    status = client().get("/api/v1/auth/status").json()
    assert status["authenticated"] is False and status["setup_required"] is False
    assert bootstrap(client(), "thirdowner").status_code == 409
    assert db.fetchone("SELECT COUNT(*) n FROM system_users")["n"] == 1


def test_public_registration_never_grants_accounts_or_privileged_roles(private_auth):
    assert bootstrap(client()).status_code == 200
    response = client().post("/api/v1/auth/register/request-otp", json={
        "username": "publicowner", "display_name": "Public Owner", "phone": "0912345678", "email": "test@example.invalid"})
    assert response.status_code == 404  # Legacy public registration routes are removed.
    response = client().post("/api/v1/auth/register/verify-otp", json={"challenge_id": "missing", "otp": "000000", "password": PW})
    assert response.status_code == 404
    assert db.fetchone("SELECT COUNT(*) n FROM system_users")["n"] == 1


def test_mfa_password_does_not_issue_session_and_existing_totp_remains_required(private_auth):
    browser = client()
    assert bootstrap(browser).status_code == 200
    uid = db.fetchone("SELECT id FROM system_users WHERE username='testowner'")["id"]
    secret = auth._totp_secret()
    auth._persist_mfa_setup(uid, secret, auth._totp_step() - 1)
    browser.post("/api/v1/auth/logout", json={})
    browser = client()
    response = login(browser)
    assert response.status_code == 200, response.text
    challenge = response.json()
    assert challenge["mfa_required"] is True and challenge["mfa_method"] == "TOTP"
    assert "token" not in challenge
    assert browser.get("/api/v1/auth/status").json()["authenticated"] is False
    assert browser.get("/api/v1/admin/users").status_code == 401
    wrong = browser.post("/api/v1/auth/mfa/verify", json={"challenge_id": challenge["challenge_id"], "code": "not-valid"})
    assert wrong.status_code in {400, 401}
    verified = browser.post("/api/v1/auth/mfa/verify", json={"challenge_id": challenge["challenge_id"], "code": auth._totp_code(secret)})
    assert verified.status_code == 200, verified.text
    assert verified.json()["authenticated"] is True
    assert browser.get("/api/v1/auth/status").json()["authenticated"] is True


def test_registration_page_and_qr_are_separate_from_management_authority(private_auth):
    assert bootstrap(client()).status_code == 200
    browser = client()
    response = browser.get("/")
    assert response.status_code == 200
    for element in ("gateLoginForm", "gateOpenRegistrationBtn", "gateEnrollmentForm", "gateOpenSetupBtn"):
        assert 'id="' + element + '"' in response.text
    response = browser.get("/enroll")
    assert response.status_code == 200
    assert "mobileEnrollmentRoot" in response.text
    assert response.headers["referrer-policy"] == "no-referrer"
    assert browser.post("/api/v1/qr-enrollment/redeem", json={"invite_secret": secrets.token_urlsafe(32)}).status_code == 410
    assert browser.get("/api/v1/auth/status").json()["authenticated"] is False
    assert browser.post("/api/v1/admin/face-enrollment/invitations", json={"student_id": 1, "store_id": 1}).status_code == 401


def test_rbac_restricts_enrollment_to_authorized_role(private_auth):
    assert bootstrap(client()).status_code == 200
    auth.create_user("testviewer", "Test Viewer", "VIEWER", PW)
    browser = client()
    assert login(browser, "testviewer").status_code == 200
    assert browser.post("/api/v1/admin/face-enrollment/invitations", json={"student_id": 1, "store_id": 1}).status_code == 403
    assert browser.get("/api/v1/admin/users").status_code == 403
    assert browser.get("/api/v1/auth/status").json()["user"]["role"] == "VIEWER"


def test_issued_qr_invitation_keeps_employee_store_binding_and_never_grants_portal_session(private_auth):
    from module_app.platform_v5 import ensure_platform_v5_schema
    ensure_platform_v5_schema()
    owner_browser = client()
    assert bootstrap(owner_browser).status_code == 200
    store = db.fetchone("SELECT id FROM stores ORDER BY id LIMIT 1")["id"]
    now = db.utc_now()
    other_store = db.execute("INSERT INTO stores(store_code,store_name,created_at,updated_at) VALUES(?,?,?,?)", ("TEST-B", "Test Store B", now, now))
    employee = db.execute("INSERT INTO students(student_code,full_name,consent_at,created_at,updated_at) VALUES(?,?,?,?,?)", ("TEST-E1", "Test Employee", now, now, now))
    db.execute("INSERT INTO employee_store_assignments(student_id,store_id,created_at) VALUES(?,?,?)", (employee, store, now))
    wrong_store = owner_browser.post("/api/v1/admin/face-enrollment/invitations", json={"student_id": employee, "store_id": other_store})
    assert wrong_store.status_code == 403
    assert wrong_store.json()["detail"]["code"] == "STORE_ASSIGNMENT_MISMATCH"
    issued = owner_browser.post("/api/v1/admin/face-enrollment/invitations", json={"student_id": employee, "store_id": store, "invitation_minutes": 5})
    assert issued.status_code == 200, issued.text
    invitation = issued.json()
    assert invitation["qr_url"].startswith("https://btmh.test/enroll#invite=")
    invitation_secret = parse_qs(urlsplit(invitation["qr_url"]).fragment)["invite"][0]
    phone = client(remote=True)
    redeemed = phone.post("/api/v1/qr-enrollment/redeem", json={"invite_secret": invitation_secret})
    assert redeemed.status_code == 200, redeemed.text
    assert "capture_secret" not in redeemed.json()
    status = phone.get("/api/v1/qr-enrollment/status")
    assert status.status_code == 200, status.text
    assert status.json()["request"]["store_id"] == store
    assert status.json()["request"]["student_id"] == employee
    assert phone.post("/api/v1/qr-enrollment/consent", json={"granted": True}).status_code == 200
    assert phone.get("/api/v1/auth/status").json()["authenticated"] is False
    assert phone.get("/api/v1/admin/face-enrollment/requests").status_code == 401
    assert phone.post("/api/v1/qr-enrollment/redeem", json={"invite_secret": invitation_secret}).status_code == 410
    assert db.fetchone("SELECT COUNT(*) n FROM face_templates")["n"] == 0

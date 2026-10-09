"""Diagnostics RBAC and self-test request contracts; no hardware access."""
from __future__ import annotations

from argon2 import PasswordHasher
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from module_app import auth, db, main
from module_app.production_ops import ensure_production_schema


PASSWORD = "LocalDiagnosticsRegressionOnly!550"
PERFORMANCE_PATH = "/api/v1/system/diagnostics/performance"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_MODE", "sqlite")
    monkeypatch.setattr(db, "SQLITE_PATH", tmp_path / "diagnostics.db")
    monkeypatch.setattr(auth, "_ARGON2", PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
    auth._sessions.clear()
    auth._mfa_challenges.clear()
    auth._failed_logins.clear()
    auth._session_factor_times.clear()
    auth._session_credential_tags.clear()
    db.init_db()
    ensure_production_schema()
    auth.ensure_rbac_schema()
    auth.bootstrap_admin("diag_owner", "QA Owner", PASSWORD, phone_verified=False)
    auth.create_user("diag_employee", "QA Employee", "EMPLOYEE", PASSWORD)
    auth.create_user("diag_technician", "QA Technician", "TECHNICIAN", PASSWORD)
    # Constructing a client without its lifespan context does not start cameras,
    # gateway, recorder or production-monitor threads.
    result = TestClient(main.app, base_url="http://127.0.0.1", client=("127.0.0.1", 12345))
    yield result
    result.close()
    auth._sessions.clear()
    auth._session_factor_times.clear()
    auth._session_credential_tags.clear()


def _login(client, username):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("method,path", [
    ("GET", PERFORMANCE_PATH),
    ("GET", "/api/v1/system/diagnostics"),
    ("POST", "/api/v1/system/self-test"),
])
def test_anonymous_diagnostics_never_reads_components(client, monkeypatch, method, path):
    def unexpected(*args, **kwargs):
        pytest.fail("anonymous diagnostics request reached runtime collection")

    monkeypatch.setattr(main, "collect_performance_diagnostics", unexpected)
    monkeypatch.setattr(main, "storage_status", unexpected)
    monkeypatch.setattr(main, "add_audit_event", unexpected)
    response = client.request(method, path)
    assert response.status_code == 401


@pytest.mark.parametrize("method,path", [
    ("GET", PERFORMANCE_PATH),
    ("GET", "/api/v1/system/diagnostics"),
    ("POST", "/api/v1/system/self-test"),
])
def test_employee_without_diagnostics_permission_never_reads_components(client, monkeypatch, method, path):
    _login(client, "diag_employee")

    def unexpected(*args, **kwargs):
        pytest.fail("unauthorized employee reached runtime collection")

    monkeypatch.setattr(main, "collect_performance_diagnostics", unexpected)
    monkeypatch.setattr(main, "storage_status", unexpected)
    monkeypatch.setattr(main, "add_audit_event", unexpected)
    response = client.request(method, path)
    assert response.status_code == 403


@pytest.mark.parametrize("username", ["diag_owner", "diag_technician"])
def test_authorized_performance_diagnostics_collects_expected_components_and_is_not_cached(client, monkeypatch, username):
    _login(client, username)
    calls = []
    payload = {"schema_version": "test", "camera": {"capture_fps": 25}, "resources": {"cpu_percent": None}}

    def collect(*components):
        calls.append(components)
        return payload

    monkeypatch.setattr(main, "collect_performance_diagnostics", collect)
    response = client.get(PERFORMANCE_PATH)
    assert response.status_code == 200, response.text
    assert response.json() == payload
    assert "no-store" in response.headers.get("cache-control", "")
    assert len(calls) == 1
    assert len(calls[0]) == 5
    assert all(actual is expected for actual, expected in zip(
        calls[0], (main.CAMERA, main.MEDIA_GATEWAY, main.RECORDER_V4, main.FLEET_V4, main.PILOT)
    ))


@pytest.mark.parametrize("passed,outcome", [(True, "SUCCESS"), (False, "WARNING")])
def test_self_test_forwards_same_request_and_audits_only_safe_check_fields(monkeypatch, passed, outcome):
    request = Request({"type": "http", "method": "POST", "path": "/api/v1/system/self-test", "headers": []})
    forwarded, authorized, audited = [], [], []
    secret = "rtsp://operator:private-test-password@camera.invalid/stream"
    payload = {"ok": passed, "checks": [{"key": "camera", "ok": passed, "detail": secret,
                                          "label": secret, "extra": {"source": secret}}]}

    def authorize(actual_request, permission):
        authorized.append((actual_request, permission))
        return {"id": 7, "username": "qa_owner"}

    def diagnostics(actual_request):
        forwarded.append(actual_request)
        return payload

    monkeypatch.setattr(main, "_auth_permission", authorize)
    monkeypatch.setattr(main, "system_diagnostics", diagnostics)
    monkeypatch.setattr(main, "add_audit_event", lambda *args, **kwargs: audited.append((args, kwargs)))

    assert main.system_self_test(request) == payload
    assert forwarded == [request]
    assert authorized == [(request, "system.diagnostics")]
    assert len(audited) == 1 and audited[0][0] == ("SYSTEM", "SELF_TEST", outcome)
    assert audited[0][1]["detail"] == {"checks": [{"key": "camera", "ok": passed}]}


def test_authenticated_self_test_uses_real_permission_route_and_request(client, monkeypatch):
    _login(client, "diag_owner")
    forwarded = []

    def diagnostics(request):
        assert isinstance(request, Request)
        assert request.url.path == "/api/v1/system/self-test"
        forwarded.append(request)
        return {"ok": True, "checks": [{"key": "camera", "ok": True}]}

    monkeypatch.setattr(main, "system_diagnostics", diagnostics)
    monkeypatch.setattr(main, "add_audit_event", lambda *args, **kwargs: None)
    response = client.post("/api/v1/system/self-test")
    assert response.status_code == 200, response.text
    assert response.json()["ok"] and len(forwarded) == 1

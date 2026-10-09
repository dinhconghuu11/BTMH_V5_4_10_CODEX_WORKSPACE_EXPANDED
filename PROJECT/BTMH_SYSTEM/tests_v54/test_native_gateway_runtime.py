from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    from module_app import media_gateway_v5410 as module

    gw = module.NativeMediaGateway()
    gw._config_dir = tmp_path / "config"
    gw._config_path = gw._config_dir / "mediamtx.yml"
    gw._log_path = tmp_path / "logs" / "gateway.log"
    gw._runtime_dir = tmp_path / "runtime"
    gw._source = "rtsp://camera_user:FakeCameraSecret@camera.invalid/Streaming/Channels/101"
    gw._source_label = "Test camera"
    gw._desired = True
    gw._process = SimpleNamespace(poll=lambda: None, pid=1234)
    monkeypatch.setattr(gw, "_port_open", lambda *args, **kwargs: True)
    state = {"sessions": {}, "deletes": [], "offers": [], "location": None, "error": None,
             "source_ready": True, "content_type": "application/sdp"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, headers=None):
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authenticated(self):
            expected = "Basic " + base64.b64encode(f"{gw._internal_user}:{gw._internal_password}".encode()).decode()
            if self.headers.get("Authorization") != expected:
                self.send(401, b'{"error":"authentication error"}')
                return False
            return True

        def do_POST(self):
            if not self.authenticated():
                return
            state["offers"].append(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if state["error"]:
                self.send(503, json.dumps({"error": state["error"]}).encode())
                return
            sid = str(uuid4())
            secret = str(uuid4())
            state["sessions"][sid] = {"id": sid, "path": module.GATEWAY_PATH,
                                      "peerConnectionEstablished": True, "secret": secret}
            # MediaMTX v1.21.1 returns the public session UUID in ID and a
            # distinct secret UUID in Location; diagnostics uses the former.
            location = state["location"] or f"/{module.GATEWAY_PATH}/whep/{secret}"
            self.send(201, b"v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n", {
                "Location": location, "ID": sid, "Content-Type": state["content_type"]})

        def do_DELETE(self):
            if not self.authenticated():
                return
            state["deletes"].append(self.path)
            secret = self.path.rsplit("/", 1)[-1]
            for sid, session in list(state["sessions"].items()):
                if session["secret"] == secret:
                    state["sessions"].pop(sid)
            self.send(200, b"{}")

        def do_GET(self):
            if not self.authenticated():
                return
            if self.path.startswith("/v3/paths/get/"):
                payload = {"online": True, "available": state["source_ready"],
                           "ready": state["source_ready"], "source": {"url": gw._source},
                           "readers": list(state["sessions"].values()), "inboundBytes": 9999,
                           "inboundFramesInError": 2,
                           "tracks2": [{"codec": "H264", "codecProps": {
                               "width": 1920, "height": 1080, "profile": "Baseline", "level": "4.0"}}]}
            else:
                payload = {"items": list(state["sessions"].values())}
            self.send(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(module, "GATEWAY_HTTP_PORT", server.server_port)
    monkeypatch.setattr(module, "GATEWAY_API_PORT", server.server_port)
    yield gw, state, module
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


OFFER = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"


def test_whep_uses_internal_auth_and_owner_bound_app_session(gateway):
    gw, state, module = gateway
    answer = gw.create_whep_session(OFFER, "user-a")
    assert answer["sdp"].startswith("v=0")
    assert answer["session_id"] not in state["sessions"]
    assert gw._internal_password not in repr(answer)
    assert gw._source not in repr(answer)
    with pytest.raises(module.NativeGatewayError) as err:
        gw.delete_whep_session(answer["session_id"], "user-b")
    assert err.value.status_code == 403
    assert state["deletes"] == []
    assert gw.delete_whep_session(answer["session_id"], "user-a")
    assert not gw.delete_whep_session(answer["session_id"], "user-a")
    assert state["sessions"] == {}


@pytest.mark.parametrize("location", [
    "http://outside.invalid/btmhmain/whep/00000000-0000-0000-0000-000000000000",
    "//outside.invalid/btmhmain/whep/00000000-0000-0000-0000-000000000000",
    "/v3/config/global/get", "/btmhmain/whep/not-a-uuid",
    "/btmhmain/whep/00000000-0000-0000-0000-000000000000?token=secret",
])
def test_untrusted_location_never_becomes_delete_target(gateway, location):
    gw, state, module = gateway
    state["location"] = location
    with pytest.raises(module.NativeGatewayError) as err:
        gw.create_whep_session(OFFER, "viewer")
    assert err.value.code == "GATEWAY_INVALID_LOCATION"
    assert state["deletes"] == []
    assert gw._sessions == {} and gw._pending_sessions == {}


def test_negotiation_after_handover_is_deleted_instead_of_attached(gateway, monkeypatch):
    gw, state, module = gateway
    original = gw._http_request

    def request(method, *args, **kwargs):
        result = original(method, *args, **kwargs)
        if method == "POST":
            gw._generation += 1
        return result

    monkeypatch.setattr(gw, "_http_request", request)
    with pytest.raises(module.NativeGatewayError) as err:
        gw.create_whep_session(OFFER, "viewer")
    assert err.value.code == "GATEWAY_SOURCE_CHANGED"
    assert len(state["deletes"]) == 1
    assert gw._sessions == {} and gw._pending_sessions == {}


def test_invalid_answer_cleans_created_upstream_session(gateway):
    gw, state, module = gateway
    state["content_type"] = "application/json"
    with pytest.raises(module.NativeGatewayError) as err:
        gw.create_whep_session(OFFER, "viewer")
    assert err.value.code == "GATEWAY_INVALID_SDP"
    assert len(state["deletes"]) == 1


def test_sdp_and_session_quota_are_bounded_before_upstream_request(gateway):
    gw, state, module = gateway
    with pytest.raises(module.NativeGatewayError) as err:
        gw.create_whep_session("v=0" + "x" * module.WHEP_MAX_BODY, "viewer")
    assert err.value.status_code == 413
    gw._pending_sessions = {str(i): "viewer" for i in range(module.WHEP_MAX_OWNER_SESSIONS)}
    with pytest.raises(module.NativeGatewayError) as err:
        gw.create_whep_session(OFFER, "viewer")
    assert err.value.status_code == 429
    assert not state["offers"]


def test_diagnostics_allowlist_actual_source_and_peer_health(gateway):
    gw, state, _ = gateway
    gw.create_whep_session(OFFER, "viewer")
    status = gw.status()
    assert status["source_healthy"] is True
    assert status["source_state"] == "READY"
    assert status["source_reader_count"] == 1
    assert status["webrtc_connected_count"] == 1
    assert status["source_codecs"][0]["width"] == 1920
    assert status["source_inbound_bytes"] == 9999
    assert status["source_frames_in_error"] == 2
    assert status["whep_url"] == "/api/v1/media/gateway/whep"
    assert gw._source not in repr(status)
    assert gw._internal_password not in repr(status)
    state["source_ready"] = False
    state["sessions"].clear()
    gw._diagnostics_at = 0
    assert gw.status()["source_state"] == "IDLE"
    assert gw.status()["source_healthy"] is None


def test_gateway_rejection_preserves_precise_reason_without_secrets(gateway):
    gw, state, module = gateway
    state["error"] = f"H264 B-frames unsupported: {gw._source}; auth={gw._internal_password}"
    with pytest.raises(module.NativeGatewayError) as err:
        gw.create_whep_session(OFFER, "viewer")
    assert "H264 B-frames unsupported" in str(err.value)
    assert "FakeCameraSecret" not in str(err.value)
    assert gw._internal_password not in str(err.value)
    assert gw._pending_sessions == {}


def test_recovered_source_can_return_to_on_demand_idle(gateway):
    gw, state, _ = gateway
    gw._source_error = "RTSP source: connection timeout"
    assert gw.status()["source_state"] == "READY"
    assert gw._source_error == ""
    state["source_ready"] = False
    gw._diagnostics_at = 0
    status = gw.status()
    assert status["source_state"] == "IDLE"
    assert status["source_healthy"] is None
    assert status["source_error"] == ""


def test_static_source_online_without_available_stream_is_not_healthy(gateway):
    gw, state, _ = gateway
    state["source_ready"] = False
    gw._pending_sessions["negotiating"] = "viewer"
    status = gw.status()
    assert status["api_ready"] is True
    assert status["source_state"] == "CONNECTING"
    assert status["source_healthy"] is False


def test_reaping_uses_session_id_not_whep_location_secret(gateway):
    gw, state, _ = gateway
    answer = gw.create_whep_session(OFFER, "viewer")
    session = gw._sessions[answer["session_id"]]
    assert session["upstream_id"] in state["sessions"]
    assert session["upstream_id"] != session["url"].rsplit("/", 1)[-1]
    session["created"] = time.monotonic() - 40
    assert gw.status()["app_session_count"] == 1
    state["sessions"].clear()
    gw._diagnostics_at = 0
    assert gw.status()["app_session_count"] == 0


def test_config_and_indexed_env_separate_ice_from_private_listeners(gateway, monkeypatch):
    gw, _, module = gateway
    monkeypatch.setenv("MODULE_HOST", "0.0.0.0")
    monkeypatch.setenv("BTMH_MEDIA_GATEWAY_ICE_HOSTS", "gateway.local,invalid/@secret")
    monkeypatch.setenv("MTX_AUTHMETHOD", "http")
    gw._write_config()
    config = gw._config_path.read_text(encoding="utf-8")
    assert f"webrtcAddress: 127.0.0.1:{module.GATEWAY_HTTP_PORT}" in config
    assert f"webrtcLocalUDPAddress: 0.0.0.0:{module.GATEWAY_ICE_PORT}" in config
    assert "webrtcIPsFromInterfaces: true" in config
    assert "gateway.local" in config
    assert "invalid/@secret" not in config
    assert gw._source not in config and gw._internal_password not in config
    env = gw._child_environment(gw._source)
    assert "MTX_AUTHMETHOD" not in env
    assert env["MTX_AUTHINTERNALUSERS_0_PASS"] == gw._internal_password
    assert env["MTX_AUTHINTERNALUSERS_0_PERMISSIONS_0_ACTION"] == "read"
    assert env["MTX_AUTHINTERNALUSERS_0_PERMISSIONS_0_PATH"] == module.GATEWAY_PATH
    assert env["MTX_PATHS_BTMHMAIN_SOURCE"] == gw._source


def test_recorder_relay_requires_matching_source_and_listener(gateway, monkeypatch):
    gw, _, _ = gateway
    assert gw.relay_source(gw._source).startswith("rtsp://btmh-internal:")
    assert gw.relay_source("rtsp://different.invalid/101") == ""
    monkeypatch.setattr(gw, "_port_open", lambda *args, **kwargs: False)
    assert gw.relay_source(gw._source) == ""


def test_missing_binary_restarts_back_off_instead_of_busy_loop(gateway, monkeypatch, tmp_path):
    gw, _, _ = gateway
    gw._process = None  # This case starts without an owned gateway child.
    monkeypatch.setattr(gw, "binary_path", lambda: tmp_path / "missing.exe")
    for _ in range(8):
        assert not gw._spawn_locked()
    assert gw._failure_count == 8
    assert 29000 <= gw.status()["restart_backoff_ms"] <= 30000


def test_spawn_rotates_recorder_auth_without_credentials_in_argv(gateway, monkeypatch, tmp_path):
    gw, _, module = gateway
    gw._process = None  # Auth rotation is tested only after the prior owner exited.
    binary = tmp_path / "mediamtx.exe"
    binary.touch()
    calls = []
    monkeypatch.setattr(gw, "binary_path", lambda: binary)
    monkeypatch.setattr(gw, "_port_open", lambda *args, **kwargs: bool(calls))
    monkeypatch.setattr(gw, "_start_log_pump", lambda *args: None)

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(poll=lambda: None, pid=100)

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    old_password = gw._internal_password
    assert gw._spawn_locked()
    assert gw._internal_password != old_password
    argv, kwargs = calls[0]
    assert gw._internal_password not in repr(argv)
    assert "FakeCameraSecret" not in repr(argv)
    assert kwargs["env"]["MTX_AUTHINTERNALUSERS_0_PASS"] == gw._internal_password


def test_immediate_child_error_is_not_cleared_after_log_pump(gateway, monkeypatch, tmp_path):
    gw, _, module = gateway
    gw._process = None  # Model a fresh child, not an already-running gateway.
    binary = tmp_path / "mediamtx.exe"
    binary.touch()
    monkeypatch.setattr(gw, "binary_path", lambda: binary)
    monkeypatch.setattr(gw, "_port_open", lambda *args, **kwargs: False)
    proc = SimpleNamespace(poll=lambda: 1, returncode=1, pid=100)
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: proc)
    def pump(*args):
        gw._last_error = "ERR: gateway listener could not bind"
    monkeypatch.setattr(gw, "_start_log_pump", pump)
    assert not gw._spawn_locked()
    assert gw._last_error == "ERR: gateway listener could not bind"

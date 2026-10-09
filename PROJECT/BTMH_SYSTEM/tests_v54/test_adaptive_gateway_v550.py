"""Adaptive native path contracts against a private authenticated loopback fake."""
import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pytest

from module_app import media_gateway_v5410 as module
from module_app.camera_profiles import hikvision_ai_substream


OFFER = "v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n"


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    gw = module.NativeMediaGateway()
    gw._config_dir = tmp_path / "config"
    gw._config_path = gw._config_dir / "mediamtx.yml"
    gw._log_path = tmp_path / "logs" / "gateway.log"
    gw._source = "rtsp://test:FakeAdaptiveSecret@camera.invalid:554/Streaming/Channels/101?transport=tcp"
    gw._desired = True
    gw._process = SimpleNamespace(poll=lambda: None, pid=1234)
    monkeypatch.setattr(gw, "_port_open", lambda *a, **kw: True)
    state = {"posts": [], "patches": [], "deletes": [], "sessions": {}, "location": None,
             "small_error": False, "main_error": False, "small_bad_sdp": False, "config_error": False, "after_post": None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body=b"{}", headers=None):
            self.send_response(code)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def auth(self):
            expected = "Basic " + base64.b64encode(f"{gw._internal_user}:{gw._internal_password}".encode()).decode()
            if self.headers.get("Authorization") != expected:
                self.send(401)
                return False
            return True

        def do_POST(self):
            if not self.auth():
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["posts"].append((self.path, body))
            path = self.path.split("/")[1]
            if (path == module.GATEWAY_SMALL_PATH and state["small_error"]
                    or path == module.GATEWAY_PATH and state["main_error"]):
                self.send(503, json.dumps({"error": "small camera rejected: " + gw._small_source}).encode())
                return
            secret, public_id = str(uuid4()), str(uuid4())
            state["sessions"][secret] = {"id": public_id, "path": path, "peerConnectionEstablished": True}
            location = state["location"] or f"/{path}/whep/{secret}"
            content_type = "application/json" if path == module.GATEWAY_SMALL_PATH and state["small_bad_sdp"] else "application/sdp"
            if state["after_post"]:
                state["after_post"]()
            self.send(201, OFFER.encode(), {"Location": location, "ID": public_id, "Content-Type": content_type})

        def do_PATCH(self):
            if not self.auth():
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["patches"].append((self.path, self.headers.get("Content-Type"), body))
            if self.path.startswith("/v3/config/paths/patch/"):
                if state["config_error"]:
                    self.send(500, json.dumps({"error": gw._source + " " + gw._small_source}).encode())
                else:
                    self.send(200)
            else:
                self.send(204, b"")

        def do_DELETE(self):
            if not self.auth():
                return
            state["deletes"].append(self.path)
            state["sessions"].pop(self.path.rsplit("/", 1)[-1], None)
            self.send(200)

        def do_GET(self):
            if not self.auth():
                return
            if self.path.startswith("/v3/paths/get/"):
                payload = {"online": True, "available": True, "source": {"url": gw._source},
                           "tracks2": [{"codec": "H264", "codecProps": {"width": 1920, "height": 1080}}]}
            else:
                payload = {"items": list(state["sessions"].values())}
            self.send(200, json.dumps(payload).encode(), {"Content-Type": "application/json"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(module, "GATEWAY_HTTP_PORT", server.server_port)
    monkeypatch.setattr(module, "GATEWAY_API_PORT", server.server_port)
    try:
        yield gw, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def enable_small(gw):
    result = gw.sync_small_source(hikvision_ai_substream(gw._source))
    assert result["small_available"]


def test_auxiliary_patch_preserves_main_reader_process_relay_and_credentials(gateway):
    gw, state = gateway
    main = gw.create_whep_session(OFFER, "viewer")
    relay, process, generation, password = gw.relay_source(gw._source), gw._process, gw._generation, gw._internal_password
    enable_small(gw)
    assert gw._process is process and gw._generation == generation and gw._internal_password == password
    assert main["session_id"] in gw._sessions and gw.relay_source(gw._source) == relay
    assert relay.endswith("/" + module.GATEWAY_PATH)
    path, content_type, body = state["patches"][0]
    assert path == "/v3/config/paths/patch/" + module.GATEWAY_SMALL_PATH
    assert content_type == "application/json"
    assert json.loads(body)["source"] == hikvision_ai_substream(gw._source)
    enable_small(gw)
    assert len(state["patches"]) == 1


def test_small_configuration_stays_in_private_environment_and_memory(gateway):
    gw, _ = gateway
    enable_small(gw)
    gw._write_config()
    config = gw._config_path.read_text(encoding="utf-8")
    assert gw._source not in config and gw._small_source not in config and "FakeAdaptiveSecret" not in config
    env = gw._child_environment(gw._source)
    assert env["MTX_PATHS_BTMHMAIN_SOURCE"] == gw._source
    assert env["MTX_PATHS_BTMHSMALL_SOURCE"] == gw._small_source
    assert env["MTX_AUTHINTERNALUSERS_0_PERMISSIONS_0_PATH"] == module.GATEWAY_PATH
    assert env["MTX_AUTHINTERNALUSERS_0_PERMISSIONS_3_PATH"] == module.GATEWAY_SMALL_PATH
    status = gw.status()
    assert status["small_path"] == module.GATEWAY_SMALL_PATH
    assert status["small_available"]
    assert "rtsp://" not in repr(status) and "FakeAdaptiveSecret" not in repr(status)


@pytest.mark.parametrize("source", [
    "rtsp://test:FakeAdaptiveSecret@other.invalid/Streaming/Channels/102",
    "rtsp://changed:OtherSecret@camera.invalid/Streaming/Channels/102",
    "rtsp://test:FakeAdaptiveSecret@camera.invalid/Streaming/Channels/201",
    "http://camera.invalid/Streaming/Channels/102",
    "rtsp://test:FakeAdaptiveSecret@camera.invalid/Streaming/Channels/102?changed=1",
])
def test_arbitrary_auxiliary_source_is_rejected_without_touching_main(gateway, source):
    gw, state = gateway
    original = gw._source
    result = gw.sync_small_source(source)
    assert not result["small_available"] and result["small_fallback_reason"] == "SMALL_SOURCE_REJECTED"
    assert gw._source == original and not state["patches"]


def test_unproven_small_falls_back_explicitly_to_main(gateway):
    gw, state = gateway
    gw.sync_small_source("", fallback_reason="ADAPTIVE_DISABLED")
    result = gw.create_whep_session(OFFER, "viewer", quality="small")
    assert result["quality"] == "main" and result["requested_quality"] == "small"
    assert result["quality_fallback_reason"] == "ADAPTIVE_DISABLED"
    assert state["posts"][0][0] == "/" + module.GATEWAY_PATH + "/whep"


@pytest.mark.parametrize("quality", ["", "btmhsmall", "../btmhmain", "rtsp://secret@camera.invalid"])
def test_quality_is_allowlisted_before_any_upstream_request(gateway, quality):
    gw, state = gateway
    with pytest.raises(module.NativeGatewayError) as exc:
        gw.create_whep_session(OFFER, "viewer", quality=quality)
    assert exc.value.code == "GATEWAY_INVALID_QUALITY" and not state["posts"]


def test_small_session_is_path_bound_and_owner_bound_for_patch_and_delete(gateway):
    gw, state = gateway
    enable_small(gw)
    result = gw.create_whep_session(OFFER, "viewer", quality="small")
    session = gw._sessions[result["session_id"]]
    assert result["quality"] == "small" and result["quality_fallback_reason"] == ""
    assert session["path"] == module.GATEWAY_SMALL_PATH
    assert session["url"].split("/")[3] == module.GATEWAY_SMALL_PATH
    assert "FakeAdaptiveSecret" not in repr(result) and "http://" not in repr(result)
    for action in (lambda: gw.patch_whep_session(result["session_id"], "other", "a=ice-ufrag:test"),
                   lambda: gw.delete_whep_session(result["session_id"], "other")):
        with pytest.raises(module.NativeGatewayError) as exc:
            action()
        assert exc.value.status_code == 403
    assert not state["deletes"] and len(state["patches"]) == 1
    assert gw.patch_whep_session(result["session_id"], "viewer", "a=ice-ufrag:test")
    assert state["patches"][-1][0] == session["url"].split(str(module.GATEWAY_HTTP_PORT), 1)[1]
    assert state["patches"][-1][1] == "application/trickle-ice-sdpfrag"
    assert gw.delete_whep_session(result["session_id"], "viewer")


def test_cross_path_location_is_rejected_without_deleting_untrusted_target(gateway):
    gw, state = gateway
    enable_small(gw)
    state["location"] = f"/{module.GATEWAY_PATH}/whep/{uuid4()}"
    with pytest.raises(module.NativeGatewayError) as exc:
        gw.create_whep_session(OFFER, "viewer", quality="small")
    assert exc.value.code == "GATEWAY_INVALID_LOCATION"
    assert not state["deletes"] and not gw._sessions


@pytest.mark.parametrize("failure", ["small_error", "small_bad_sdp"])
def test_small_negotiation_failure_cleans_allocated_peer_then_retries_main_once(gateway, failure):
    gw, state = gateway
    enable_small(gw)
    state[failure] = True
    result = gw.create_whep_session(OFFER, "viewer", quality="small")
    assert result["quality"] == "main" and result["quality_fallback_reason"] == "SMALL_NEGOTIATION_FAILED"
    assert [path for path, _ in state["posts"]] == ["/btmhsmall/whep", "/btmhmain/whep"]
    assert len(gw._sessions) == 1 and not gw._pending_sessions
    assert all(item["path"] == module.GATEWAY_PATH for item in state["sessions"].values())
    if failure == "small_bad_sdp":
        assert len(state["deletes"]) == 1 and state["deletes"][0].startswith("/btmhsmall/whep/")
    assert "FakeAdaptiveSecret" not in repr(gw.status())


def test_auxiliary_revocation_closes_small_only_and_invalidates_pending_negotiation(gateway):
    gw, state = gateway
    main = gw.create_whep_session(OFFER, "viewer")
    enable_small(gw)
    small = gw.create_whep_session(OFFER, "viewer", quality="small")
    process = gw._process
    status = gw.sync_small_source("", fallback_reason="SUBSTREAM_STALE")
    assert not status["small_available"] and status["small_fallback_reason"] == "SUBSTREAM_STALE"
    assert main["session_id"] in gw._sessions and small["session_id"] not in gw._sessions
    assert gw._process is process
    assert state["deletes"][0].startswith("/btmhsmall/whep/")
    assert json.loads(state["patches"][-1][2])["source"] == "publisher"
    enable_small(gw)
    state["after_post"] = lambda: setattr(gw, "_small_generation", gw._small_generation + 1)
    with pytest.raises(module.NativeGatewayError) as exc:
        gw.create_whep_session(OFFER, "viewer", quality="small")
    assert exc.value.code == "GATEWAY_SOURCE_CHANGED"
    assert len(state["deletes"]) == 2 and main["session_id"] in gw._sessions


def test_diagnostics_reaping_retains_live_small_sessions(gateway):
    gw, state = gateway
    enable_small(gw)
    result = gw.create_whep_session(OFFER, "viewer", quality="small")
    gw._sessions[result["session_id"]]["created"] = time.monotonic() - 40
    gw._diagnostics_at = 0
    assert gw.status()["app_session_count"] == 1
    state["sessions"].clear()
    gw._diagnostics_at = 0
    assert gw.status()["app_session_count"] == 0


def test_config_failure_has_only_fixed_reason_and_main_remains_available(gateway):
    gw, state = gateway
    state["config_error"] = True
    result = gw.sync_small_source(hikvision_ai_substream(gw._source))
    assert result["small_fallback_reason"] == "SMALL_CONFIG_FAILED" and not result["small_available"]
    status = gw.status()
    assert status["available"] and "FakeAdaptiveSecret" not in repr(status)
    assert gw.create_whep_session(OFFER, "viewer", quality="small")["quality"] == "main"


def test_untrusted_fallback_reason_is_not_exposed(gateway):
    gw, _ = gateway
    result = gw.sync_small_source("", fallback_reason="FakeAdaptiveSecret")
    assert result["small_fallback_reason"] == "SMALL_NOT_VALIDATED"


def test_exhausted_backend_retry_reports_safe_code_without_another_native_attempt(gateway):
    gw, state = gateway
    enable_small(gw)
    state["small_error"] = state["main_error"] = True
    with pytest.raises(module.NativeGatewayError) as exc:
        gw.create_whep_session(OFFER, "viewer", quality="small")
    assert exc.value.code == "SMALL_AND_MAIN_UNAVAILABLE"
    assert len(state["posts"]) == 2 and not gw._sessions and not gw._pending_sessions
    assert "FakeAdaptiveSecret" not in str(exc.value)


def test_small_log_error_does_not_change_main_health_or_relay(gateway):
    gw, _ = gateway
    enable_small(gw)
    before = gw.relay_source(gw._source)
    line = "ERR [path btmhsmall] [RTSP source] connection failed: " + gw._small_source
    gw._record_log_error(gw._process, gw._safe_message(line), line, gw._source)
    status = gw.status()
    assert status["source_healthy"] is True and status["source_state"] == "READY"
    assert status["last_error"] == "" and status["source_error"] == ""
    assert not status["small_available"] and status["small_fallback_reason"] == "SMALL_UNAVAILABLE"
    assert gw.relay_source(gw._source) == before
    assert "FakeAdaptiveSecret" not in repr(status)


def test_captured_small_url_redaction_survives_revocation_and_source_handover(gateway):
    gw, _ = gateway
    old_source = gw._source + "&token=PrivateQuerySecret"
    old_small = hikvision_ai_substream(old_source)
    gw._source = "rtsp://different:NewSecret@other.invalid/Streaming/Channels/101"
    gw._small_source = ""
    safe = gw._safe_message("ERR old auxiliary source: " + old_small, source=old_source)
    assert "PrivateQuerySecret" not in safe and "FakeAdaptiveSecret" not in safe
    assert "[RTSP_SOURCE_REDACTED]" in safe


def test_main_control_and_relay_progress_while_auxiliary_api_is_blocked(gateway, monkeypatch):
    gw, state = gateway
    entered, release = threading.Event(), threading.Event()
    original = gw._http_request
    result = []

    def request(method, url, *args, **kwargs):
        if method == "PATCH" and "/v3/config/paths/patch/" in url:
            entered.set()
            assert release.wait(2)
        return original(method, url, *args, **kwargs)

    monkeypatch.setattr(gw, "_http_request", request)
    thread = threading.Thread(target=lambda: result.append(gw.sync_small_source(hikvision_ai_substream(gw._source))))
    thread.start()
    try:
        assert entered.wait(1)
        assert gw.relay_source(gw._source).endswith("/btmhmain")
        assert gw.status()["available"]
        assert gw.create_whep_session(OFFER, "viewer")["quality"] == "main"
        # A revocation must invalidate the blocked earlier PATCH immediately.
        revoked = gw.sync_small_source("", fallback_reason="SUBSTREAM_STALE")
        assert not revoked["small_available"]
        release.set()
        thread.join(2)
        assert not thread.is_alive() and not result[0]["small_available"]
        gw.sync_small_source("", fallback_reason="SUBSTREAM_STALE")
        assert json.loads(state["patches"][-1][2])["source"] == "publisher"
    finally:
        release.set()
        thread.join(2)


def test_failed_auxiliary_cleanup_is_bounded_retained_and_counted_in_quota(gateway, monkeypatch):
    gw, _ = gateway
    enable_small(gw)
    small = [gw.create_whep_session(OFFER, "viewer", quality="small") for _ in range(6)]
    original = gw._http_request
    attempts = []

    def fail_delete(method, url, *args, **kwargs):
        if method == "DELETE":
            attempts.append(kwargs["timeout"])
            raise module.NativeGatewayError(503, "GATEWAY_UNREACHABLE", "fake timeout")
        return original(method, url, *args, **kwargs)

    monkeypatch.setattr(gw, "_http_request", fail_delete)
    began = time.monotonic()
    gw.sync_small_source("", fallback_reason="SUBSTREAM_STALE")
    assert time.monotonic() - began < 1
    assert attempts == [.25, .25]
    assert len(gw._small_retired_sessions) == 6
    assert all(item["session_id"] not in gw._sessions for item in small)
    gw.create_whep_session(OFFER, "viewer")
    gw.create_whep_session(OFFER, "viewer")
    with pytest.raises(module.NativeGatewayError) as exc:
        gw.create_whep_session(OFFER, "viewer")
    assert exc.value.code == "GATEWAY_SESSION_LIMIT"
    monkeypatch.setattr(gw, "_http_request", original)
    gw.sync_small_source("", fallback_reason="SUBSTREAM_STALE")
    assert len(gw._small_retired_sessions) == 4

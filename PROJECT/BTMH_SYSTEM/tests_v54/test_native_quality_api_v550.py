"""Adaptive quality signaling keeps camera generations and existing RBAC."""
import asyncio
import time

import numpy as np
import pytest
from fastapi import HTTPException

from module_app import main
from module_app.ai_capture_v550 import AIFramePacket
from module_app.camera import StaticCameraService
from test_whep_proxy_lifecycle import Request


@pytest.fixture
def camera(monkeypatch):
    camera = StaticCameraService()
    camera.configure_source("rtsp://camera.example.test/Streaming/Channels/101")
    monkeypatch.setattr(main, "CAMERA", camera)
    monkeypatch.setattr(main, "_auth_permission", lambda *args: {"id": 7})
    monkeypatch.setattr(main, "_sync_adaptive_gateway_quality", lambda: None)
    return camera


def test_unknown_quality_rejected_before_upstream(camera, monkeypatch):
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", lambda *a, **kw: pytest.fail("upstream called"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.media_gateway_whep(Request(), quality="arbitrary-path"))
    assert exc.value.status_code == 400


def test_small_fallback_headers_are_explicit_and_no_source_is_exposed(camera, monkeypatch):
    observed = []
    def create(sdp, owner, **kwargs):
        observed.append(kwargs)
        return {"sdp": "v=0\r\nanswer", "session_id": "quality-session", "quality": "main",
                "requested_quality": "small", "quality_fallback_reason": "SMALL_NOT_VALIDATED"}
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", create)
    response = asyncio.run(main.media_gateway_whep(Request(), quality="small"))
    assert response.status_code == 201
    assert observed[0] == {"expected_source": camera.current_source_identity(), "quality": "small"}
    assert response.headers["X-BTMH-Quality"] == "main"
    assert response.headers["X-BTMH-Quality-Fallback"] == "SMALL_NOT_VALIDATED"
    assert "rtsp://" not in repr(dict(response.headers))


def test_unscoped_same_uri_new_epoch_closes_negotiated_session(camera, monkeypatch):
    deleted = []
    def create(*args, **kwargs):
        # A -> B -> A has the same URI but a different physical generation.
        camera._source_epoch += 2
        return {"sdp": "v=0\r\nanswer", "session_id": "old-generation", "quality": "main"}
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", create)
    monkeypatch.setattr(main.MEDIA_GATEWAY, "delete_whep_session", lambda sid, owner: deleted.append((sid, owner)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.media_gateway_whep(Request()))
    assert exc.value.status_code == 409 and deleted == [("old-generation", "7")]


def test_small_proof_revoked_during_negotiation_closes_session(camera, monkeypatch):
    proof = {"valid": True}
    deleted = []
    monkeypatch.setattr(camera, "validated_ai_substream_source", lambda: "internal-source" if proof["valid"] else "")
    def create(*args, **kwargs):
        proof["valid"] = False
        return {"sdp": "v=0\r\nanswer", "session_id": "old-small", "quality": "small"}
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", create)
    monkeypatch.setattr(main.MEDIA_GATEWAY, "delete_whep_session", lambda sid, owner: deleted.append((sid, owner)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.media_gateway_whep(Request(), quality="small"))
    assert exc.value.status_code == 409 and deleted == [("old-small", "7")]


def test_small_proof_requires_current_registered_epoch_and_fresh_packet(camera):
    source = camera.current_source_identity()
    camera.configure_ai_source(source)
    lane = camera._ai_capture
    lane._state = "READY"
    lane._latest = AIFramePacket(np.zeros((20, 20, 3), np.uint8), 1, time.perf_counter(), camera._source_epoch)
    assert camera.validated_ai_substream_source().endswith("/102")
    camera._source_epoch += 1
    assert camera.validated_ai_substream_source() == ""
    camera._source_epoch -= 1
    lane._latest = AIFramePacket(lane._latest.frame, 1, time.perf_counter() - 2, camera._source_epoch)
    assert camera.validated_ai_substream_source() == ""
    camera.configure_ai_source(None)
    assert camera.validated_ai_substream_source() == ""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from module_app import main
from module_app.media_gateway_v5410 import NativeGatewayError
from module_app import media_webrtc


class Request:
    def __init__(self, body=b"v=0\r\n", content_type="application/sdp", disconnected=False):
        self.headers = {"content-type": content_type}
        self.body = body
        self.disconnected = disconnected

    async def stream(self):
        yield self.body

    async def is_disconnected(self):
        return self.disconnected


@pytest.fixture
def actor(monkeypatch):
    monkeypatch.setattr(main, "_auth_permission", lambda request, permission: {"id": 7})


def test_whep_signaling_is_owned_same_origin_and_keeps_sdp(actor, monkeypatch):
    created, deleted = [], []
    def create(sdp, owner, **kwargs):
        created.append((sdp, owner))
        return {"sdp": "v=0\r\nanswer", "session_id": "session-123"}
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", create)
    monkeypatch.setattr(main.MEDIA_GATEWAY, "delete_whep_session", lambda sid, owner: deleted.append((sid, owner)))
    result = asyncio.run(main.media_gateway_whep(Request()))
    assert result.status_code == 201
    assert result.body == b"v=0\r\nanswer"
    assert result.headers["location"] == "/api/v1/media/gateway/whep/session/session-123"
    assert created == [("v=0\r\n", "7")]
    asyncio.run(main.media_gateway_whep_close("session-123", Request()))
    assert deleted == [("session-123", "7")]
    assert main._api_permission_for(result.headers["location"], "DELETE") == "camera.live"


def test_whep_aborted_request_deletes_allocated_session(actor, monkeypatch):
    deleted = []
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", lambda *args, **kwargs: {"sdp": "answer", "session_id": "pending"})
    monkeypatch.setattr(main.MEDIA_GATEWAY, "delete_whep_session", lambda sid, owner: deleted.append((sid, owner)))
    result = asyncio.run(main.media_gateway_whep(Request(disconnected=True)))
    assert result.status_code == 499
    assert deleted == [("pending", "7")]


@pytest.mark.parametrize("sample_request,code", [(Request(content_type="application/json"), 415), (Request(b"x" * 65537), 413), (Request(b"\xff"), 400)])
def test_whep_rejects_invalid_or_unbounded_payload_before_gateway(actor, monkeypatch, sample_request, code):
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", lambda *args: pytest.fail("gateway called"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.media_gateway_whep(sample_request))
    assert exc.value.status_code == code


def test_whep_propagates_actionable_error_code(actor, monkeypatch):
    def fail(*args, **kwargs):
        raise NativeGatewayError(503, "SOURCE_NOT_READY", "Camera has no ready media")
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", fail)
    result = asyncio.run(main.media_gateway_whep(Request()))
    assert result.status_code == 503
    assert b"SOURCE_NOT_READY" in result.body


def test_other_camera_cannot_use_primary_video(monkeypatch):
    monkeypatch.setattr(main, "_fleet_camera_source", lambda camera_id: ({}, "internal", False))
    caps = main.media_capabilities(camera_id=2)
    assert caps["camera_matches_active"] is False
    assert caps["native_gateway"]["available"] is False
    assert caps["native_gateway"]["whep_url"] == ""
    assert caps["native_gateway"]["reason_code"] == "NON_PRIMARY_CAMERA"
    assert caps["webrtc"]["available"] is False


def test_camera_switch_during_whep_creation_closes_old_session(actor, monkeypatch):
    active = {"value": True}
    deleted = []
    monkeypatch.setattr(main, "_fleet_camera_source", lambda camera_id: ({}, "original", active["value"]))
    def create(sdp, owner, **kwargs):
        assert kwargs["expected_source"] == "original"
        active["value"] = False
        return {"sdp": "answer", "session_id": "old-camera-session"}
    monkeypatch.setattr(main.MEDIA_GATEWAY, "create_whep_session", create)
    monkeypatch.setattr(main.MEDIA_GATEWAY, "delete_whep_session", lambda sid, owner: deleted.append((sid, owner)))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.media_gateway_whep(Request(), camera_id=1))
    assert exc.value.status_code == 409
    assert deleted == [("old-camera-session", "7")]


def test_python_negotiation_cancellation_closes_peer_and_track(monkeypatch):
    peers, tracks = [], []
    class Track:
        def __init__(self, *args, **kwargs):
            self.stopped = False
            tracks.append(self)
        def stop(self):
            self.stopped = True
    class Peer:
        connectionState = "new"
        def __init__(self):
            self.closed = False
            peers.append(self)
        def addTrack(self, track):
            return object()
        def getTransceivers(self):
            return []
        def on(self, event):
            return lambda function: function
        async def setRemoteDescription(self, description):
            await asyncio.Event().wait()
        async def close(self):
            self.closed = True
    monkeypatch.setattr(media_webrtc, "AIORTC_AVAILABLE", True)
    monkeypatch.setattr(media_webrtc, "RTCPeerConnection", Peer)
    monkeypatch.setattr(media_webrtc, "RTCSessionDescription", lambda **kwargs: kwargs)
    monkeypatch.setattr(media_webrtc, "LatestCameraVideoTrack", Track)
    service = media_webrtc.WebRTCMediaService()
    async def run():
        task = asyncio.create_task(service.create_answer(sdp="v=0", owner="7"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service._peers
        assert peers[0].closed and tracks[0].stopped
        await service.close_all()
    asyncio.run(run())


def test_python_close_cannot_close_another_users_peer():
    service = media_webrtc.WebRTCMediaService()
    class Peer:
        closed = False
        async def close(self):
            self.closed = True
    peer = Peer()
    service._peers["owned"] = peer
    service._owners["owned"] = "7"
    with pytest.raises(PermissionError):
        asyncio.run(service.close("owned", owner="8"))
    assert not peer.closed
    assert asyncio.run(service.close("owned", owner="7"))
    assert peer.closed


def test_scoped_python_track_never_emits_other_cameras_frame(monkeypatch):
    import numpy as np
    track = object.__new__(media_webrtc.LatestCameraVideoTrack)
    track._source_identity = "rtsp://camera-a.invalid/main"
    track._next_due = 0
    track._fps = 20
    track_stopped = []
    monkeypatch.setattr(track, "stop", lambda: track_stopped.append(True))
    # Handover commits in the middle of sampling the latest packet.
    sources = iter(["rtsp://camera-a.invalid/main", "rtsp://camera-b.invalid/main"])
    monkeypatch.setattr(media_webrtc.CAMERA, "current_source_identity", lambda: next(sources))
    monkeypatch.setattr(media_webrtc.CAMERA, "latest_media_packet", lambda: (np.zeros((10, 10, 3)), 7, 0))
    with pytest.raises(RuntimeError, match="MEDIA_CAMERA_SOURCE_CHANGED"):
        asyncio.run(track.recv())
    assert track_stopped == [True]

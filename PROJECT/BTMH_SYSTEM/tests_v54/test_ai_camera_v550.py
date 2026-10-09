"""Source and evidence contracts for the private AI stream; no hardware access."""
import time
from types import SimpleNamespace

import numpy as np
import pytest

from module_app import main
from module_app.camera import StaticCameraService
from module_app.face_core import CORE
from test_camera_v544 import FakeSession


def test_registry_binding_requires_enabled_exact_active_source(monkeypatch):
    camera = StaticCameraService()
    source = "rtsp://example.test/Streaming/Channels/101"
    camera.configure_source(source)
    monkeypatch.setattr(main, "CAMERA", camera)
    monkeypatch.setattr(main, "list_camera_devices", lambda: [
        {"source": source, "enabled": False},
        {"source": "rtsp://other.test/Streaming/Channels/101", "enabled": True},
    ])
    main._configure_ai_registry_source()
    assert camera._ai_registered_source == ""
    monkeypatch.setattr(main, "list_camera_devices", lambda: [{"source": source, "enabled": True}])
    main._configure_ai_registry_source()
    assert camera._ai_registered_source == source
    assert camera.current_source_identity() == source
    assert "example.test" not in str(camera._ai_capture.status())


def test_handover_configures_ai_after_new_source_is_committed(monkeypatch):
    camera = StaticCameraService()
    camera.configure_source("0")
    old = FakeSession("0")
    camera._active_session = old
    camera._cap = old
    camera._status["running"] = True
    target = FakeSession("rtsp://example.test/Streaming/Channels/101")
    monkeypatch.setattr(camera, "_new_session", lambda source: target)
    monkeypatch.setattr(camera, "_clear_transient_recognition", lambda **kwargs: None)
    observed = []
    monkeypatch.setattr(camera, "_sync_ai_capture_epoch", lambda: observed.append(
        (camera.current_source_identity(), camera._source_epoch)))
    try:
        result = camera.safe_select_source(target.source)
        assert result["ok"]
        assert observed == [(target.source, 1)]
    finally:
        camera.stop()


@pytest.mark.parametrize("mismatch", ["epoch", "time", "geometry", "future"])
def test_main_evidence_rejects_unverifiable_substream_proposal(monkeypatch, mismatch):
    camera = StaticCameraService()
    captured = time.perf_counter()
    camera._frame = np.zeros((480, 640, 3), np.uint8)
    camera._frame_at = captured
    camera._source_epoch = 7
    image = np.zeros((240, 320, 3), np.uint8)
    epoch = 6 if mismatch == "epoch" else 7
    if mismatch == "time":
        captured -= 1
    if mismatch == "geometry":
        image = np.zeros((200, 320, 3), np.uint8)
    if mismatch == "future":
        captured += 1
        camera._frame_at = captured
    monkeypatch.setattr(CORE, "detect", lambda *args, **kwargs: pytest.fail("unverified evidence reached detector"))
    assert camera._ai_evidence_provider(source_epoch=epoch, capture_at=captured,
        image=image, observation=SimpleNamespace(bbox=(30, 30, 40, 40))) is None


def test_handover_during_main_evidence_confirmation_discards_result(monkeypatch):
    camera = StaticCameraService()
    captured = time.perf_counter()
    camera._frame = np.zeros((480, 640, 3), np.uint8)
    camera._frame_at = captured
    camera._source_epoch = 7
    image = np.zeros((240, 320, 3), np.uint8)
    observation = SimpleNamespace(bbox=(30, 30, 40, 40))
    def detect(*args, **kwargs):
        camera._source_epoch += 1
        return [object()]
    monkeypatch.setattr(CORE, "detect", detect)
    monkeypatch.setattr(CORE, "_translate_face", lambda face, x, y: face)
    monkeypatch.setattr(CORE, "observe", lambda *args, **kwargs: SimpleNamespace(bbox=(60, 60, 80, 80)))
    assert camera._ai_evidence_provider(source_epoch=7, capture_at=captured,
        image=image, observation=observation) is None


@pytest.mark.parametrize("age", [2.0, -1.0])
def test_ai_main_fallback_rejects_stale_or_future_frames(age):
    camera = StaticCameraService()
    camera._frame = np.zeros((240, 320, 3), np.uint8)
    camera._frame_at = time.perf_counter() - age
    camera._status["state"] = "online"
    frame, _, _, _, mode = camera._ai_input_packet()
    assert frame is None and mode == "MAIN_FALLBACK"


@pytest.mark.parametrize("write", ["create", "update", "delete"])
def test_registry_write_revokes_auxiliary_ai_without_switching_primary(monkeypatch, write):
    camera = StaticCameraService()
    source = "rtsp://example.test/Streaming/Channels/101"
    camera.configure_source(source)
    primary = object()
    camera._active_session = primary
    rows = [{"source": source, "enabled": True}]
    monkeypatch.setattr(main, "CAMERA", camera)
    monkeypatch.setattr(main, "list_camera_devices", lambda: rows)
    monkeypatch.setattr(main, "_auth_permission", lambda *args: {"username": "test"})
    monkeypatch.setattr(main, "add_audit_event", lambda *args, **kwargs: None)
    main._configure_ai_registry_source()
    assert camera._ai_registered_source == source
    def save(*args, **kwargs):
        rows[0]["enabled"] = False
        return rows[0]
    def delete(*args):
        rows.clear()
    monkeypatch.setattr(main, "save_camera_device", save)
    monkeypatch.setattr(main, "delete_camera_device", delete)
    payload = SimpleNamespace(model_dump=lambda: {})
    if write == "create":
        result = main.camera_devices_create(payload, object())
    elif write == "update":
        result = main.camera_devices_update(1, payload, object())
    else:
        result = main.camera_devices_delete(1, object())
    assert result["ok"] and camera._ai_registered_source == ""
    assert camera._ai_capture._source == ""
    assert camera.current_source_identity() == source and camera._active_session is primary


def test_failed_registry_write_keeps_valid_ai_binding(monkeypatch):
    from fastapi import HTTPException
    camera = StaticCameraService()
    source = "rtsp://example.test/Streaming/Channels/101"
    camera.configure_source(source)
    monkeypatch.setattr(main, "CAMERA", camera)
    monkeypatch.setattr(main, "list_camera_devices", lambda: [{"source": source, "enabled": True}])
    monkeypatch.setattr(main, "_auth_permission", lambda *args: {"username": "test"})
    main._configure_ai_registry_source()
    def save(*args, **kwargs):
        raise ValueError("test write rejected")
    monkeypatch.setattr(main, "save_camera_device", save)
    with pytest.raises(HTTPException):
        main.camera_devices_update(1, SimpleNamespace(model_dump=lambda: {}), object())
    assert camera._ai_registered_source == source and camera.current_source_identity() == source

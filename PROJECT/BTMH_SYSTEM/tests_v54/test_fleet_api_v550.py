"""Reader demand and physical camera scope; no hardware or customer data."""
import asyncio
import time
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from module_app import main
from module_app.camera import StaticCameraService


def test_fleet_status_does_not_open_auxiliary_readers(monkeypatch):
    monkeypatch.setattr(main, "_auth_permission", lambda *a: {})
    monkeypatch.setattr(main, "list_camera_devices", lambda: [{"id": 42, "source": "rtsp://camera.example.test/stream", "enabled": True}])
    monkeypatch.setattr(main.FLEET_V4, "ensure", lambda *a: pytest.fail("status opened reader"))
    monkeypatch.setattr(main.FLEET_V4, "get", lambda *a: None)
    monkeypatch.setattr(main.RECORDER_V4, "camera_status", lambda *a: {})
    monkeypatch.setattr(main.RECORDER_V4, "status", lambda: {})
    result = main.camera_fleet_v4(None)
    assert result["items"][0]["state"] == "idle"


def primary(monkeypatch):
    camera = StaticCameraService()
    camera.configure_source("rtsp://camera.example.test/stream")
    camera._raw_jpeg, camera._raw_jpeg_seq, camera._raw_jpeg_at = b"camera-A", 7, time.perf_counter()
    monkeypatch.setattr(main, "CAMERA", camera)
    monkeypatch.setattr(main, "_fleet_camera_source", lambda cid: ({}, camera.current_source_identity(), True))
    monkeypatch.setattr(main.FLEET_V4, "stop", lambda *a, **kw: True)
    return camera


def test_primary_stream_ends_on_epoch_change_even_same_uri(monkeypatch):
    camera = primary(monkeypatch)
    class Reader:
        async def is_disconnected(self): return False
    async def collect():
        response = main.camera_fleet_stream(42, Reader())
        iterator = response.body_iterator
        assert b"camera-A" in await anext(iterator)
        camera._source_epoch += 2
        camera._raw_jpeg = b"camera-B"
        with pytest.raises(StopAsyncIteration): await anext(iterator)
    asyncio.run(collect())


@pytest.mark.parametrize("age", [5.0, -1.0])
def test_scoped_primary_packet_rejects_stale_and_future_frame(monkeypatch, age):
    camera = primary(monkeypatch)
    camera._raw_jpeg_at = time.perf_counter() - age
    with pytest.raises(HTTPException) as error: main.camera_fleet_frame(42)
    assert error.value.status_code == 503


def test_scoped_primary_packet_refuses_another_camera_epoch(monkeypatch):
    camera = primary(monkeypatch)
    context = camera.media_source_context()
    camera._source_epoch += 1
    camera._raw_jpeg = b"camera-B"
    assert camera.scoped_preview_packet(*context) == (b"", 0, None)


@pytest.mark.parametrize("disconnect", [True, False])
def test_aux_stream_releases_lease_on_disconnect_or_iterator_close(monkeypatch, disconnect):
    released = []
    worker = SimpleNamespace(jpeg=lambda: b"aux-frame")
    monkeypatch.setattr(main, "_fleet_camera_source", lambda cid: ({}, "rtsp://camera.example.test/aux", False))
    monkeypatch.setattr(main.FLEET_V4, "acquire", lambda *a: (worker, "lease"))
    monkeypatch.setattr(main.FLEET_V4, "renew", lambda *a: True)
    monkeypatch.setattr(main.FLEET_V4, "release", lambda *a: released.append(a))
    class Reader:
        async def is_disconnected(self): return disconnect
    async def collect():
        iterator = main.camera_fleet_stream(42, Reader()).body_iterator
        if disconnect:
            assert [part async for part in iterator] == []
        else:
            assert b"aux-frame" in await anext(iterator)
            await iterator.aclose()
    asyncio.run(collect())
    assert released == [(42, "lease")]


def test_aux_stream_lost_lease_never_sends_cached_frame(monkeypatch):
    released = []
    worker = SimpleNamespace(jpeg=lambda: pytest.fail("read after revoked lease"))
    monkeypatch.setattr(main, "_fleet_camera_source", lambda cid: ({}, "rtsp://camera.example.test/aux", False))
    monkeypatch.setattr(main.FLEET_V4, "acquire", lambda *a: (worker, "revoked"))
    monkeypatch.setattr(main.FLEET_V4, "renew", lambda *a: False)
    monkeypatch.setattr(main.FLEET_V4, "release", lambda *a: released.append(a))
    class Reader:
        async def is_disconnected(self): return False
    async def collect(): return [part async for part in main.camera_fleet_stream(42, Reader()).body_iterator]
    assert asyncio.run(collect()) == []
    assert released == [(42, "revoked")]


def test_busy_auxiliary_lifecycle_does_not_block_event_loop(monkeypatch):
    entered, resumed = threading.Event(), threading.Event()
    worker = SimpleNamespace(jpeg=lambda: b"aux-frame")
    def renew(*args):
        entered.set()
        return resumed.wait(1.0)
    monkeypatch.setattr(main, "_fleet_camera_source", lambda cid: ({}, "rtsp://camera.example.test/aux", False))
    monkeypatch.setattr(main.FLEET_V4, "acquire", lambda *a: (worker, "lease"))
    monkeypatch.setattr(main.FLEET_V4, "renew", renew)
    monkeypatch.setattr(main.FLEET_V4, "release", lambda *a: True)
    class Reader:
        async def is_disconnected(self): return False
    async def collect():
        iterator = main.camera_fleet_stream(42, Reader()).body_iterator
        task = asyncio.create_task(anext(iterator))
        async def another_client():
            while not entered.is_set(): await asyncio.sleep(.001)
            resumed.set()
        await asyncio.wait_for(another_client(), timeout=2.0)
        assert b"aux-frame" in await task
        await iterator.aclose()
    asyncio.run(collect())


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_registry_write_invalidates_auxiliary_owner(monkeypatch, operation):
    stopped, invalidated = [], []
    monkeypatch.setattr(main, "_auth_permission", lambda *a: {})
    monkeypatch.setattr(main, "save_camera_device", lambda *a, **kw: {})
    monkeypatch.setattr(main, "delete_camera_device", lambda *a: None)
    monkeypatch.setattr(main, "_configure_ai_registry_source", lambda: None)
    monkeypatch.setattr(main, "add_audit_event", lambda *a, **kw: None)
    monkeypatch.setattr(main.FLEET_V4, "stop", lambda cid, **kw: stopped.append(cid))
    monkeypatch.setattr(main.RECORDER_V4, "invalidate_camera", lambda cid: invalidated.append(cid))
    if operation == "update":
        main.camera_devices_update(42, SimpleNamespace(model_dump=lambda: {}), None)
    else:
        main.camera_devices_delete(42, None)
    assert stopped == invalidated == [42]

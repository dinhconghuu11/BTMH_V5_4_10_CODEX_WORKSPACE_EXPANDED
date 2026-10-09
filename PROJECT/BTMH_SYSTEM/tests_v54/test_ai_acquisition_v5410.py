"""Real acquisition method with inert arrays; no app startup or decoder."""
import time
from types import SimpleNamespace

import numpy as np
import pytest

from module_app.camera import StaticCameraService


@pytest.mark.parametrize("substream_ready", [True, False])
def test_ai_acquisition_does_not_copy_unused_main_or_stale_frame(monkeypatch, substream_ready):
    class UnusedMain(np.ndarray):
        def copy(self, *args, **kwargs):
            raise AssertionError("unused main frame was copied")
    camera = StaticCameraService()
    camera._frame = np.zeros((1080, 1920, 3), np.uint8).view(UnusedMain)
    camera._frame_at = time.perf_counter() - (0 if substream_ready else 5)
    camera._status["state"] = "online"
    packet = SimpleNamespace(frame=np.zeros((360, 640, 3), np.uint8), seq=8, at=time.perf_counter())
    monkeypatch.setattr(camera._ai_capture, "snapshot", lambda _: packet if substream_ready else None)
    frame, seq, _, _, mode = camera._ai_input_packet()
    if substream_ready:
        assert frame.shape == (360, 640, 3) and seq == 8 and mode == "HIKVISION_SUBSTREAM"
    else:
        assert frame is None and mode == "MAIN_FALLBACK"


def test_main_fallback_owns_its_copy_and_preserves_source_epoch():
    camera = StaticCameraService()
    camera._frame = np.zeros((120, 160, 3), np.uint8)
    camera._frame_at = time.perf_counter()
    camera._frame_seq, camera._source_epoch = 9, 4
    camera._status["state"] = "online"
    frame, seq, _, epoch, mode = camera._ai_input_packet()
    assert (seq, epoch, mode) == (9, 4, "MAIN_FALLBACK")
    frame[:] = 255
    assert not camera._frame.any()

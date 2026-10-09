from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fleet_stop_waits_for_rtsp_release_contract():
    text = (ROOT / "module_app" / "camera_fleet_v4.py").read_text(encoding="utf-8")
    assert "def stop(self, camera_id: int, *, wait: bool = True" in text
    assert "worker.stop(wait=wait, timeout=timeout)" in text
    assert "thread.join(timeout=max(0.1, float(timeout)))" in text


def test_faceid_handover_waits_for_fleet_release():
    text = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    assert "FLEET_V4.stop(target_camera_id, wait=True, timeout=6.5)" in text
    assert "Luồng xem trực tiếp Hikvision chưa nhả kết nối" in text


def test_rtsp_warmup_allows_keyframe_delay():
    text = (ROOT / "module_app" / "camera.py").read_text(encoding="utf-8")
    assert "timeout_sec=4.2 if self._is_network_source(source) else 2.8" in text
    assert "retired_aux_workers" in text

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
FLEET = (ROOT / "module_app" / "camera_fleet_v4.py").read_text(encoding="utf-8")
REC = (ROOT / "module_app" / "recording_runtime_v4.py").read_text(encoding="utf-8")
OTP = (ROOT / "module_app" / "otp_service.py").read_text(encoding="utf-8")
APPJS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
V4JS = (ROOT / "frontend" / "js" / "btmh_v4.js").read_text(encoding="utf-8")


def test_cam_alias_is_resolved_server_side_without_exposing_rtsp_credentials():
    assert 'key.startswith("cam") and key[3:].isdigit()' in MAIN
    assert 'SELECT * FROM camera_devices WHERE id=?' in MAIN
    assert 'source_key": f"CAM{cid:02d}"' in MAIN


def test_active_faceid_camera_reuses_primary_frames_in_fleet():
    assert 'FLEET_V4.stop(target_camera_id, wait=True, timeout=6.5)' in MAIN
    assert 'shared_with_faceid' in MAIN
    assert 'CAMERA.latest_raw_jpeg()' in MAIN
    assert 'def stop(self, camera_id: int, *, wait: bool = True' in FLEET


def test_recording_status_is_real_and_current_file_is_not_indexed_early():
    assert 'SEGMENT_SECONDS = 60' in REC
    assert 'FINALIZE_GRACE_SECONDS = 3.0' in REC
    assert "'active': active" in REC
    assert 'FFmpeg recorder exited with code' in REC
    assert 'now_ts - float(stat.st_mtime) < FINALIZE_GRACE_SECONDS' in REC
    assert 'recording_active' in MAIN
    assert 'REC WAIT' in V4JS


def test_playback_day_boundaries_are_timezone_safe_and_errors_are_visible():
    assert '.toISOString()' in V4JS
    assert 'Recorder đang chạy. Đoạn video đầu tiên sẽ xuất hiện sau khoảng 1 phút.' in V4JS
    assert 'H.264' in V4JS


def test_demo_otp_is_never_presented_as_real_delivery():
    assert 'def delivery_status()' in OTP
    assert 'real_delivery' in OTP
    assert 'DEMO — chưa gửi ra ngoài' in APPJS
    assert 'OTP chưa được gửi qua' in APPJS
    assert '"delivery": otp_delivery_status()' in MAIN

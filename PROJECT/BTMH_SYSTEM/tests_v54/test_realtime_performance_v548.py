from module_app import config as cfg
from module_app.rtsp_native_v545 import command
from module_app.camera import StaticCameraService


def test_balanced_rtsp_defaults_are_bounded():
    assert cfg.RTSP_REALTIME_PROFILE in {"light","balanced","quality"}
    assert 5 <= cfg.RTSP_CAPTURE_FPS <= 30
    assert 640 <= cfg.RTSP_CAPTURE_MAX_WIDTH <= 1920
    assert 2 <= cfg.RTSP_AI_TARGET_FPS <= 12
    assert 640 <= cfg.RTSP_AI_WIDTH <= 1600
    assert 8 <= cfg.RTSP_PREVIEW_FPS <= 24
    assert 720 <= cfg.RTSP_PREVIEW_WIDTH <= 1920


def test_native_ffmpeg_can_bound_rate_and_width_without_uri():
    cmd=command('ffmpeg',18,1280)
    assert '-vf' in cmd
    vf=cmd[cmd.index('-vf')+1]
    assert 'fps=18' in vf and '1280' in vf and 'scale=' in vf
    assert not any('rtsp://' in item for item in cmd)


def test_native_ffmpeg_legacy_mode_keeps_passthrough():
    cmd=command('ffmpeg')
    assert '-vf' not in cmd and cmd[cmd.index('-fps_mode')+1]=='passthrough'


def test_rtsp_session_receives_realtime_policy(monkeypatch):
    from module_app import camera_handover_v544 as hand
    captured={}
    class Dummy:
        def __init__(self, source, **kwargs):
            captured['source']=source;captured.update(kwargs)
    monkeypatch.setattr(hand,'CaptureSession',Dummy)
    obj=StaticCameraService()
    obj._capture_plan_cache={}
    obj._new_session('rtsp://example.test/stream')
    assert captured['output_fps']==cfg.RTSP_CAPTURE_FPS
    assert captured['output_max_width']==cfg.RTSP_CAPTURE_MAX_WIDTH


def test_usb_session_keeps_unbounded_decoder(monkeypatch):
    from module_app import camera_handover_v544 as hand
    captured={}
    class Dummy:
        def __init__(self, source, **kwargs):
            captured['source']=source;captured.update(kwargs)
    monkeypatch.setattr(hand,'CaptureSession',Dummy)
    obj=StaticCameraService();obj._capture_plan_cache={}
    obj._new_session('0')
    assert captured['output_fps']==0.0 and captured['output_max_width']==0


def test_performance_status_exposes_zero_backlog_contract():
    obj=StaticCameraService()
    d=obj.performance_status()
    assert d['frame_policy']=='LATEST_FRAME_DROP_STALE'
    assert d['queue_depth']==0

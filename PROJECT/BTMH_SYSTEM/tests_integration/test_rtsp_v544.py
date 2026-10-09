import os
import shutil
import time
import threading
from pathlib import Path
import pytest
from module_app.capture_session_v544 import CaptureSession
from module_app.camera import StaticCameraService
from .rtsp_fixture import TestRTSPServer as LoopbackRTSP

pytestmark=pytest.mark.skipif(not shutil.which('ffmpeg'),reason='FFmpeg executable required to generate local test video')

@pytest.fixture
def rtsp(tmp_path):
    server=LoopbackRTSP(tmp_path/'test.h264')
    yield server
    server.close()


def test_real_h264_rtsp_tcp_and_encoded_credentials(rtsp):
    s=CaptureSession(rtsp.url())
    try:
        s.start();r=s.wait_ready(5,12.)
        assert r['ok'],r
        assert r['width']==320 and r['height']==240 and rtsp.tcp_setups>0
        a=s.snapshot();time.sleep(.4);b=s.snapshot();assert b.seq>a.seq
        assert 'Test@' not in str(r) and 'camera:' not in str(r)
    finally:s.close()
    assert s.process.poll() is not None


def test_wrong_rtsp_password_reports_auth_failed(rtsp):
    s=CaptureSession(rtsp.url(password='incorrect'))
    try:
        s.start();r=s.wait_ready(5,12.)
        assert not r['ok'] and r['code']=='AUTH_FAILED',r
    finally:s.close()


def test_wrong_rtsp_path_reports_not_found(rtsp):
    s=CaptureSession(rtsp.url(path='/invalid-stream'))
    try:
        s.start();r=s.wait_ready(5,12.)
        assert not r['ok'] and r['code']=='PATH_NOT_FOUND',r
    finally:s.close()


def test_stalled_rtsp_has_outer_deadline_and_terminates(tmp_path):
    server=LoopbackRTSP(tmp_path/'hang.h264',hang=True)
    s=CaptureSession(server.url())
    try:
        started=time.monotonic();s.start();r=s.wait_ready(5,.8)
        assert not r['ok'] and r['code']=='TIMEOUT',r
        s.close()
        assert time.monotonic()-started<3.0 and s.process.poll() is not None
    finally:s.close();server.close()


def test_live_switch_repeats_and_auth_failure_keeps_source(rtsp,tmp_path,monkeypatch):
    other=LoopbackRTSP(tmp_path/'second.h264')
    cam=StaticCameraService()
    # Real decoder processes and publisher. AI is stubbed only to avoid model/DB dependencies.
    monkeypatch.setattr(cam,'_ai_loop',lambda gen:cam._stop.wait(60))
    monkeypatch.setattr(cam,'_preview_loop',lambda gen:cam._stop.wait(60))
    monkeypatch.setattr(cam,'_clear_transient_recognition',lambda **kwargs:None)
    cam.configure_source(rtsp.url(),'First')
    try:
        cam.start()
        end=time.monotonic()+12
        while time.monotonic()<end and not cam.status()['opened']:time.sleep(.05)
        assert cam.status()['opened'],cam.status()
        for n in range(4):
            url=other.url() if n%2==0 else rtsp.url()
            r=cam.safe_select_source(url,source_label='Next')
            assert r['ok'],r
            assert cam.status()['opened'] and not cam._recognition_paused
        old=cam._active_session;seq=old.snapshot().seq
        fail=cam.safe_select_source(other.url(password='incorrect'),source_label='Wrong password')
        assert not fail['ok'] and fail['code']=='AUTH_FAILED' and fail['kept_previous'],fail
        time.sleep(.5)
        assert cam._active_session is old and old.alive() and old.snapshot().seq>seq
        assert not cam._recognition_paused
    finally:
        cam.stop();other.close()

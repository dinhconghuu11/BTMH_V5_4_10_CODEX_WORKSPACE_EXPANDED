from pathlib import Path
import time
import pytest
from module_app.capture_session_v544 import CaptureSession
from module_app.rtsp_native_v545 import resolve_ffmpeg
from .rtsp_fixture import TestRTSPServer as LoopbackRTSP

pytestmark=pytest.mark.skipif(not resolve_ffmpeg(),reason="Native FFmpeg unavailable")

@pytest.mark.parametrize('decoder',['ffmpeg','opencv'])
def test_digest_auth_reserved_characters_end_to_end(tmp_path,decoder):
    server=LoopbackRTSP(tmp_path/'digest.h264',password="Only@%40:# /?'Test",digest=True)
    session=CaptureSession(server.url(),decoder=decoder)
    try:
        session.start();r=session.wait_ready(5,16)
        assert r['ok'],r
        assert server.auth_successes>=3 and server.tcp_setups>0
        assert session.snapshot().frame.shape==(240,320,3)
        seq=session.snapshot().seq;time.sleep(.3);assert session.snapshot().seq>seq
        assert "Only" not in str(r)
    finally:session.close();server.close()


def test_native_h264_full_hd_25fps_fresh_frames(tmp_path):
    server=LoopbackRTSP(tmp_path/'fullhd.h264',size='1920x1080',fps=25,digest=True)
    session=CaptureSession(server.url(),decoder='ffmpeg')
    try:
        session.start();r=session.wait_ready(5,18)
        assert r['ok'] and (r['width'],r['height'])==(1920,1080),r
        assert r['backend']=='ffmpeg-native'
        seq=session.snapshot().seq
        time.sleep(1.0)
        assert session.snapshot().seq>seq+5
        assert session.healthy() and session.snapshot().frame.shape==(1080,1920,3)
        assert session.process.args.count('-i')==1
        assert server.url() not in str(session.process.args)
    finally:session.close();server.close()
    assert session.process.poll() is not None


def test_native_wrong_digest_password_is_not_auto_retried(tmp_path):
    server=LoopbackRTSP(tmp_path/'auth.h264',digest=True)
    session=CaptureSession(server.url(password='incorrect'),decoder='ffmpeg')
    try:
        session.start();r=session.wait_ready(5,12)
        assert not r['ok'] and r['code']=='AUTH_FAILED',r
        assert server.auth_successes==0
        assert server.auth_denials<=3  # initial challenge, rejected response; no retry loop
    finally:session.close();server.close()


def test_native_stopped_rtsp_does_not_report_old_frame_as_live(tmp_path):
    server=LoopbackRTSP(tmp_path/'stop.h264')
    session=CaptureSession(server.url(),decoder='ffmpeg')
    try:
        session.start();assert session.wait_ready(5,12)['ok']
        server.close()
        deadline=time.monotonic()+6
        while time.monotonic()<deadline and session.healthy():time.sleep(.05)
        assert not session.healthy()
    finally:session.close()

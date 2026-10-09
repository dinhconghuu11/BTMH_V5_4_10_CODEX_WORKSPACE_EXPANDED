"""Narrow camera-layer regression tests. Never contacts a customer IP."""
from io import BytesIO
import json
from pathlib import Path
import os
import threading
import time
from urllib.parse import quote
import pytest
import numpy as np
from module_app.rtsp_native_v545 import input_manifest, command, read_ppm, resolve_ffmpeg
from module_app.capture_session_v544 import CaptureSession, classify_diagnostic, display_source
from module_app.camera_connection_v544 import update_connection_source


def test_manifest_keeps_secret_outside_argv():
    password="A@:#%40 /?'Test"
    source="rtsp://operator:"+quote(password,safe="")+"@192.0.2.1:554/Streaming/Channels/101"
    args=command('/not/executed/ffmpeg')
    assert source not in str(args) and password not in str(args)
    text=input_manifest(source,8000).decode()
    assert text.count("\nfile ")==1 and "rtsp_transport tcp" in text
    assert source in text and 'option timeout 8000000' in text
    assert 'operator' not in display_source(source)


@pytest.mark.parametrize('source',['file:///tmp/private','http://example.test/x','rtsp://example.test/x\nfile /etc/passwd','rtsp://x/\rfile /etc/passwd','rtsp://x/'+('a'*4096)])
def test_manifest_injection_and_wrong_protocol_rejected(source):
    with pytest.raises(ValueError):input_manifest(source,8000)


def test_command_retains_native_resolution_and_frame_rate():
    cmd=command('ffmpeg')
    assert '-vf' not in cmd and '-r' not in cmd and '-re' not in cmd and '-s' not in cmd
    assert cmd[cmd.index('-fps_mode')+1]=='passthrough'
    assert cmd[cmd.index('-protocol_whitelist')+1]=='pipe,rtsp,tcp,rtp'
    assert '-an' in cmd and '-sn' in cmd and '-dn' in cmd


def test_ppm_frame_preserves_first_whitespace_pixel():
    data=b'\n\t '+bytes(16*16*3-3)
    w,h,p=read_ppm(BytesIO(b'P6\n16 16\n255\n'+data),CaptureSession._read_exact)
    assert (w,h)==(16,16) and p==data


@pytest.mark.parametrize('header',[b'P5\n16 16\n255\n',b'P6\n100000 20000\n255\n',b'P6\n16 16\n65535\n',b'P6\n0 16\n255\n',b'P6\n16 16 3\n255\n'])
def test_invalid_ppm_rejected_before_allocation(header):
    with pytest.raises(ValueError):read_ppm(BytesIO(header),CaptureSession._read_exact)


def test_truncated_ppm_rejected():
    with pytest.raises(EOFError):read_ppm(BytesIO(b'P6\n16 16\n255\nabc'),CaptureSession._read_exact)


def test_localhost_usb_keeps_existing_worker(monkeypatch):
    # resolve_ffmpeg must never run for a USB source.
    from module_app import capture_session_v544 as mod
    monkeypatch.setattr(mod,'resolve_ffmpeg',lambda:pytest.fail('USB tried RTSP resolver'))
    class Process:
        def __init__(self,args,**kwargs):
            assert 'capture_worker_v544.py' in args[-1]
            self.stdin=BytesIO();self.stdout=BytesIO();self.stderr=BytesIO()
        def poll(self):return 0
    monkeypatch.setattr(mod.subprocess,'Popen',Process)
    s=CaptureSession('0');s.start();s.close()
    assert not s._native


def test_force_native_missing_has_actionable_error(monkeypatch):
    from module_app import capture_session_v544 as mod
    monkeypatch.setattr(mod,'resolve_ffmpeg',lambda:None)
    s=CaptureSession('rtsp://192.0.2.1/x',decoder='ffmpeg')
    s.start();r=s.wait_ready(timeout=.1);s.close()
    assert not r['ok'] and r['code']=='DECODER_UNAVAILABLE'


@pytest.mark.parametrize('text,code',[
('method DESCRIBE failed: 401 Unauthorized','AUTH_FAILED'),
('method SETUP failed: 403 Forbidden','AUTH_FAILED'),
('method DESCRIBE failed: 404 Not Found','PATH_NOT_FOUND'),
('Connection timed out','TIMEOUT'),
('Unrecognized option fps_mode','DECODER_OPTIONS'),
('Protocol not found','DECODER_UNAVAILABLE'),
('Stream map 0:v:0 matches no streams','NO_VIDEO_STREAM'),
('method SETUP failed: 453 Not Enough Bandwidth','CAMERA_BUSY'),
('method DESCRIBE failed: 503 Service Unavailable','CAMERA_BUSY')])
def test_native_errors_classified(text,code):
    assert classify_diagnostic(text)==code


def test_editor_keeps_original_password_when_changing_only_host():
    raw="rtsp://operator:"+quote('Secret@%40:/?#+',safe='')+"@192.0.2.1:554/Streaming/Channels/101"
    changed=update_connection_source(raw,'192.0.2.2',554,'/Streaming/Channels/101')
    assert changed==raw.replace('192.0.2.1','192.0.2.2')


def test_force_opencv_does_not_lookup_native(monkeypatch):
    from module_app import capture_session_v544 as mod
    monkeypatch.setattr(mod,'resolve_ffmpeg',lambda:pytest.fail('OpenCV looked up FFmpeg'))
    class Process:
        def __init__(self,args,**kwargs):
            assert 'capture_worker_v544.py' in args[-1]
            self.stdin=BytesIO();self.stdout=BytesIO();self.stderr=BytesIO()
        def poll(self):return 0
    monkeypatch.setattr(mod.subprocess,'Popen',Process)
    s=CaptureSession('rtsp://192.0.2.1/x',decoder='opencv');s.start();s.close()
    assert not s._native


def test_native_launch_failure_falls_back_without_network_retry(monkeypatch):
    from module_app import capture_session_v544 as mod
    monkeypatch.setattr(mod,'resolve_ffmpeg',lambda:'/broken/ffmpeg')
    calls=[]
    class Process:
        def __init__(self,args,**kwargs):
            calls.append(args)
            if args[0]=='/broken/ffmpeg':raise OSError('Cannot start')
            self.stdin=BytesIO();self.stdout=BytesIO();self.stderr=BytesIO()
        def poll(self):return 0
    monkeypatch.setattr(mod.subprocess,'Popen',Process)
    s=CaptureSession('rtsp://192.0.2.1/x',decoder='auto');s.start();s.close()
    assert len(calls)==2 and 'capture_worker_v544.py' in calls[-1][-1] and not s._native

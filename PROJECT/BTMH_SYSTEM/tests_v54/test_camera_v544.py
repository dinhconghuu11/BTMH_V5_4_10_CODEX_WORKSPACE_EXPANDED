"""Deterministic camera contracts: no customer data or physical camera access."""
import contextlib
import json
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit,unquote

import numpy as np
import pytest
from fastapi.testclient import TestClient
from argon2 import PasswordHasher
from module_app import auth,db,main,production_ops
from module_app.camera import StaticCameraService
from module_app.capture_session_v544 import CaptureSession,FramePacket,ERRORS,valid_source,display_source,classify_diagnostic
from module_app.camera_connection_v544 import connection_view,update_connection_source
from module_app.camera_profiles import hikvision,build_rtsp_url
from module_app.camera_fleet_v4 import CameraFleetV4,FleetWorker


class FakeSession:
    def __init__(self, source, ok=True, code="AUTH_FAILED", entered=None, release=None):
        self.source=source;self.ok=ok;self.code=code;self.closed=False;self.seq=10
        self.entered=entered;self.release_wait=release;self.started_at=time.perf_counter()
        self.image=np.zeros((240,320,3),np.uint8)
    def start(self):pass
    def close(self):self.closed=True
    def healthy(self,**kw):return self.ok and not self.closed
    def alive(self):return not self.closed
    def snapshot(self):self.seq+=1;return FramePacket(self.image,self.seq,time.perf_counter())
    def metadata(self):return {"backend":"fake","transport":"tcp"}
    def get(self,p):return 25 if p==5 else 0
    def diagnostics(self,code=None):return {"code":code or self.code,"message":"test diagnostic","width":320,"height":240,"observed_fps":25,"transport":"tcp","stable_frames":5}
    def wait_ready(self,*args,**kwargs):
        if self.entered:self.entered.set()
        if self.release_wait:self.release_wait.wait(2.)
        return {"ok":self.ok,**self.diagnostics("READY" if self.ok else self.code)}


@pytest.fixture
def camera(monkeypatch):
    obj=StaticCameraService()
    old=FakeSession('0')
    obj.configure_source('0','Laptop')
    obj._active_session=old;obj._cap=old
    obj._publish_frame(old.image,time.perf_counter())
    obj._status['running']=True
    monkeypatch.setattr(obj,'_clear_transient_recognition',lambda **kw:None)
    yield obj,old
    obj.stop()


def test_bad_target_keeps_active_camera_and_faceid(camera,monkeypatch):
    cam,old=camera;target=FakeSession('rtsp://192.0.2.1/x',False)
    monkeypatch.setattr(cam,'_new_session',lambda src:target)
    r=cam.safe_select_source(target.source,source_label='IP')
    assert not r['ok'] and r['kept_previous'] and r['code']=='AUTH_FAILED'
    assert cam._active_session is old and not old.closed and target.closed
    assert not cam._recognition_paused and not cam._handover['active']
    assert cam.current_source_identity()=='0'


def test_success_commits_after_frames_and_retires_only_previous(camera,monkeypatch):
    cam,old=camera;target=FakeSession('rtsp://192.0.2.1/x')
    monkeypatch.setattr(cam,'_new_session',lambda src:target)
    r=cam.safe_select_source(target.source,source_label='IP')
    assert r['ok'] and old.closed and not target.closed
    assert cam._active_session is target and cam._cap is target
    assert cam._source_epoch==1 and cam.current_source_identity()==target.source
    assert not cam._recognition_paused and not cam._handover['active']


def test_preflight_does_not_pause_old_faceid(camera,monkeypatch):
    cam,old=camera;entered=threading.Event();release=threading.Event()
    target=FakeSession('rtsp://192.0.2.1/x',True,entered=entered,release=release)
    monkeypatch.setattr(cam,'_new_session',lambda src:target)
    result={}
    t=threading.Thread(target=lambda:result.update(cam.safe_select_source(target.source)));t.start()
    assert entered.wait(1.)
    assert cam._active_session is old and not old.closed
    assert cam._handover['state']=='CHECKING' and not cam._recognition_paused
    # A duplicate switch is rejected rather than starting a second decoder.
    r=cam.safe_select_source('rtsp://192.0.2.2/x')
    assert r['busy'] and r['code']=='BUSY'
    release.set();t.join(3.)
    assert not t.is_alive() and result['ok']


def test_test_only_never_swaps(camera,monkeypatch):
    cam,old=camera;target=FakeSession('rtsp://192.0.2.1/x')
    monkeypatch.setattr(cam,'_new_session',lambda src:target)
    r=cam.test_source(target.source)
    assert r['ok'] and r['test_only'] and target.closed
    assert cam._active_session is old and not old.closed and cam.current_source_identity()=='0'


def test_same_source_noop_never_opens_second_usb_handle(camera,monkeypatch):
    cam,old=camera
    monkeypatch.setattr(cam,'_new_session',lambda src:pytest.fail('opened active USB twice'))
    assert cam.safe_select_source('0')['noop'] and not old.closed


def test_start_exception_does_not_touch_old(camera,monkeypatch):
    cam,old=camera
    def fail(src):raise OSError('secret should not leak')
    monkeypatch.setattr(cam,'_new_session',fail)
    r=cam.safe_select_source('rtsp://user:SECRET@192.0.2.1/x')
    assert r['code']=='START_FAILED' and r['kept_previous'] and 'SECRET' not in json.dumps(r)
    assert not old.closed and not cam._handover['active']


def test_shutdown_during_preflight_never_commits_late(camera,monkeypatch):
    cam,old=camera;entered=threading.Event();release=threading.Event()
    target=FakeSession('rtsp://192.0.2.1/x',True,entered=entered,release=release)
    monkeypatch.setattr(cam,'_new_session',lambda src:target)
    result={};t=threading.Thread(target=lambda:result.update(cam.safe_select_source(target.source)));t.start()
    assert entered.wait(1.)
    cam.stop();release.set();t.join(3.)
    assert not result['ok'] and cam._active_session is None and target.closed


@pytest.mark.parametrize('source',['rtsp://***:***@192.0.2.1/x','rtsp://u:%2A%2A%2A@192.0.2.1/x','file:///etc/passwd','/tmp/file.avi','rtsp://localhost:99999/x','http://'])
def test_invalid_or_masked_source_rejected_before_open(source):
    with pytest.raises(ValueError):valid_source(source)


def test_literal_percent_password_is_preserved_roundtrip():
    u=build_rtsp_url('192.0.2.1','cam','Literal%40@:#123')
    assert unquote(urlsplit(u).password)=='Literal%40@:#123'
    out=update_connection_source(u,'192.0.2.2',554,'/Streaming/Channels/101',None,None)
    assert unquote(urlsplit(out).password)=='Literal%40@:#123'
    assert 'Literal' not in display_source(out)


@pytest.mark.parametrize('text,expected',[
    ('method DESCRIBE failed: 401 Unauthorized rtsp://u:SECRET@x','AUTH_FAILED'),
    ('method DESCRIBE failed: 404 Not Found','PATH_NOT_FOUND'),
    ('Connection refused','CONNECTION_REFUSED'),
    ('No route to host','UNREACHABLE'),
    ('Could not find decoder','CODEC_UNSUPPORTED'),
    ('random warning',None)])
def test_native_errors_classified_without_leaking_raw_text(text,expected):
    assert classify_diagnostic(text)==expected


def test_fleet_reservation_blocks_reopening_candidate(monkeypatch):
    fleet=CameraFleetV4();starts=[]
    monkeypatch.setattr(FleetWorker,'start',lambda self:starts.append(self.camera_id))
    with fleet.reserve(9):
        w=fleet.ensure(9,'rtsp://192.0.2.1/x','IP')
        assert not starts and w.error=='HANDOVER_RESERVED'
    fleet.ensure(9,'rtsp://192.0.2.1/x','IP')
    assert starts==[9]


PW='UnitTestOnly!544'
@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_MODE','sqlite');monkeypatch.setattr(db,'SQLITE_PATH',tmp_path/'test.db')
    monkeypatch.setattr(auth,'_ARGON2',PasswordHasher(time_cost=1,memory_cost=8192,parallelism=1))
    auth._sessions.clear();auth._mfa_challenges.clear();auth._failed_logins.clear()
    auth._session_factor_times.clear();auth._session_credential_tags.clear()
    db.init_db();production_ops.ensure_production_schema();auth.ensure_rbac_schema()
    auth.bootstrap_admin('camera_owner','Owner',PW,phone_verified=False)
    obj=StaticCameraService();old=FakeSession('0');obj.configure_source('0','Laptop')
    obj._active_session=old;obj._cap=old;obj._publish_frame(old.image,time.perf_counter())
    monkeypatch.setattr(obj,'_clear_transient_recognition',lambda **kw:None)
    monkeypatch.setattr(main,'CAMERA',obj)
    monkeypatch.setattr(main,'save_camera_settings',lambda cfg:None)
    with contextlib.nullcontext(TestClient(main.app,base_url='http://127.0.0.1',client=('127.0.0.1',12345))) as c:
        yield c,obj,old
    obj.stop()


def login(c,user='camera_owner'):
    r=c.post('/api/v1/auth/login',json={'username':user,'password':PW});assert r.status_code==200,r.text


def add():
    return production_ops.save_camera_device({'name':'Hikvision Manual','source':'rtsp://operator:unit-secret@192.0.2.2:554/Streaming/Channels/101','camera_type':'RTSP'})['id']


def test_read_and_reseed_never_overwrite_operator_camera(client,monkeypatch):
    c,cam,old=client;cid=add()
    monkeypatch.setattr(production_ops,'load_hikvision_profile',lambda:hikvision('192.0.2.99','old','old-secret'))
    production_ops.list_camera_devices();production_ops.seed_default_camera_devices()
    row=db.fetchone('SELECT * FROM camera_devices WHERE id=?',(cid,))
    assert '192.0.2.2' in row['source'] and 'unit-secret' in row['source']
    assert not db.fetchone("SELECT id FROM camera_devices WHERE source LIKE '%192.0.2.99%'")


def test_connection_edit_hides_secret_and_preserves_blank(client):
    c,cam,old=client;cid=add();login(c)
    r=c.get(f'/api/v1/cameras/devices/{cid}/connection');assert r.status_code==200
    assert 'unit-secret' not in r.text and r.json()['credential_saved']
    r=c.put(f'/api/v1/cameras/devices/{cid}/connection',json={'host':'192.0.2.3','port':554,'path':'/Streaming/Channels/101'})
    assert r.status_code==200 and 'unit-secret' not in r.text
    row=db.fetchone('SELECT * FROM camera_devices WHERE id=?',(cid,));assert '192.0.2.3' in row['source'] and 'unit-secret' in row['source']
    assert cam._active_session is old and not old.closed


def test_select_failure_has_actionable_error_and_keeps_source(client,monkeypatch):
    c,cam,old=client;cid=add();login(c)
    monkeypatch.setattr(cam,'_new_session',lambda src:FakeSession(src,False))
    r=c.post('/api/v1/camera/select',json={'source':f'CAM{cid:02d}'})
    assert r.status_code==503 and r.json()['code']=='AUTH_FAILED' and r.json()['kept_previous']
    assert 'unit-secret' not in r.text and not old.closed


def test_diagnostic_does_not_require_switch(client,monkeypatch):
    c,cam,old=client;cid=add();login(c)
    monkeypatch.setattr(cam,'_new_session',lambda src:FakeSession(src))
    r=c.post('/api/v1/camera/test-source',json={'source':f'CAM{cid:02d}'})
    assert r.status_code==200 and r.json()['ok'] and r.json()['test_only']
    assert not old.closed and cam.current_source_identity()=='0'


def test_failed_switch_not_persisted(client,monkeypatch):
    c,cam,old=client;cid=add();login(c)
    monkeypatch.setattr(cam,'_new_session',lambda src:FakeSession(src,False))
    monkeypatch.setattr(main,'save_camera_settings',lambda cfg:pytest.fail('Failed source persisted'))
    assert c.post('/api/v1/cameras/devices/'+str(cid)+'/activate').status_code==503


def test_employee_denied_test_edit_and_switch(client):
    c,cam,old=client;cid=add();auth.create_user('camera_employee','Employee','EMPLOYEE',PW);login(c,'camera_employee')
    assert c.post('/api/v1/camera/test-source',json={'source':'0'}).status_code==403
    assert c.get(f'/api/v1/cameras/devices/{cid}/connection').status_code==403
    assert c.put(f'/api/v1/cameras/devices/{cid}/connection',json={'host':'192.0.2.5'}).status_code==403
    assert c.post('/api/v1/camera/select',json={'source':'0'}).status_code==403


def test_anonymous_denied_camera_tools(client):
    c,cam,old=client
    assert c.post('/api/v1/camera/test-source',json={'source':'0'}).status_code==401
    assert c.get('/api/v1/cameras/devices/1/connection').status_code==401


def test_uri_path_at_sign_not_confused_with_credentials():
    from module_app.camera_profiles import normalize_camera_source,redact_camera_source
    source='rtsp://operator:test%40only@192.0.2.9/path@camera'
    assert normalize_camera_source(source)==source
    assert redact_camera_source(source)=='rtsp://***:***@192.0.2.9/path@camera'


def test_watchdog_restart_cannot_retire_active_during_preflight(camera):
    cam,old=camera
    cam._handover_lock.acquire()
    try:
        cam.restart()
        assert cam._active_session is old and not old.closed
    finally:cam._handover_lock.release()


def test_long_encoded_camera_secret_is_not_silently_truncated(client):
    c,cam,old=client
    source=build_rtsp_url('192.0.2.5','operator','@'*250+'Word')
    assert len(source)>500
    row=production_ops.save_camera_device({'name':'Long credential','source':source,'camera_type':'RTSP'})
    assert row['source']==source


@pytest.mark.parametrize("method",["_clear_transient_recognition","_publish_frame"])
def test_exception_during_commit_restores_open_previous_source(camera,monkeypatch,method):
    cam,old=camera;target=FakeSession('rtsp://192.0.2.1/x')
    monkeypatch.setattr(cam,'_new_session',lambda src:target)
    def fail(*args,**kwargs):raise RuntimeError('diagnostic must not include SECRET')
    monkeypatch.setattr(cam,method,fail)
    r=cam.safe_select_source(target.source)
    assert not r['ok'] and r['code']=='COMMIT_FAILED' and r['kept_previous']
    assert cam._active_session is old and cam._cap is old and not old.closed and target.closed
    assert not cam._recognition_paused and cam.current_source_identity()=='0'
    assert 'SECRET' not in json.dumps(r)


def test_shipped_profile_cannot_override_local_camera(monkeypatch,tmp_path):
    from module_app import camera_profiles as cp
    sample=tmp_path/'template.json'
    sample.write_text(json.dumps({'example_only':True,'ip':'192.0.2.99','username':'sample'}))
    monkeypatch.setattr(cp,'_profile_candidates',lambda:[sample])
    monkeypatch.setattr(cp,'_stored_camera_password',lambda:'SyntheticSecret!544')
    monkeypatch.delenv('CAMPUSFACE_HIKVISION_IP',raising=False)
    monkeypatch.delenv('CAMPUSFACE_HIKVISION_USERNAME',raising=False)
    assert cp.load_hikvision_profile() is None


def test_fleet_polling_does_not_retry_rejected_credentials():
    worker=FleetWorker(2,'rtsp://192.0.2.1/x','IP')
    worker.error='AUTH_FAILED'
    for _ in range(10):worker.start()
    assert not worker.running and worker.thread is None

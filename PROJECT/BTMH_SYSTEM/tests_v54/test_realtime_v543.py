"""No physical cameras/SMS used. API tests use isolated SQLite + synthetic frames."""
import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from module_app import auth, db, main
from module_app.camera_catalog_v543 import build_source_catalog
from module_app.camera import StaticCameraService
from module_app.production_ops import ensure_production_schema
from argon2 import PasswordHasher

PW = 'LocalRegressionOnly!543'
ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_MODE', 'sqlite')
    monkeypatch.setattr(db, 'SQLITE_PATH', tmp_path / 'rt.db')
    monkeypatch.setattr(auth, '_ARGON2', PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
    auth._sessions.clear(); auth._mfa_challenges.clear(); auth._failed_logins.clear()
    auth._session_factor_times.clear(); auth._session_credential_tags.clear()
    db.init_db(); ensure_production_schema(); auth.ensure_rbac_schema()
    auth.bootstrap_admin('qa_owner', 'QA Owner', PW, phone_verified=False)
    monkeypatch.setattr(main, 'CAMERA', SimpleNamespace(
        current_source_identity=lambda: 'rtsp://operator:test-only@192.0.2.9/stream1',
        status=lambda: {'source': 'rtsp://***:***@192.0.2.9/stream1', 'opened': True, 'state': 'online'},
        preview_packet=lambda raw=False: (b'\xff\xd8QA\xff\xd9', 123, 12.5),
        media_source_context=lambda: ('rtsp://operator:test-only@192.0.2.9/stream1', 0),
        scoped_preview_packet=lambda *args: (b'\xff\xd8QA\xff\xd9', 123, 12.5),
        latest_raw_jpeg=lambda: b'\xff\xd8QA\xff\xd9',
    ))
    # A source-list read must never open a capture or invoke fleet discovery.
    monkeypatch.setattr(main.FLEET_V4, 'ensure', lambda *a, **kw: pytest.fail('Unexpected camera open'))
    return TestClient(main.app, base_url='http://127.0.0.1', client=('127.0.0.1', 12345))

def signed_in(c, username='qa_owner'):
    r=c.post('/api/v1/auth/login', json={'username':username,'password':PW})
    assert r.status_code==200,r.text
    return c

def add_camera(name='Door', source='rtsp://operator:test-only@192.0.2.9/stream1', enabled=1, kind='RTSP'):
    db.execute('INSERT INTO camera_devices(name,source,camera_type,zone_name,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
               (name,source,kind,'QA',enabled,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z'))
    return int(db.fetchone('SELECT id FROM camera_devices WHERE name=?',(name,))['id'])

def test_catalog_includes_usb_rtsp_offline_disabled_without_credentials():
    rows=[{'id':1,'source':'0','enabled':1}, {'id':2,'source':'1','enabled':1,'camera_type':'USB'},
          {'id':3,'source':'rtsp://a:secret@192.0.2.1/stream','enabled':1},
          {'id':4,'source':'rtsp://192.0.2.2/stream','enabled':0}]
    out=build_source_catalog(rows,rows[2]['source'],{'state':'reconnecting','opened':False})
    assert len(out['items'])==4
    assert [i['source_key'] for i in out['items']]==['0','CAM02','CAM03','CAM04']
    assert out['items'][2]['health_status']=='OFFLINE' and out['items'][2]['selectable']
    assert out['items'][3]['health_status']=='DISABLED' and not out['items'][3]['selectable']
    assert not any(s in json.dumps(out) for s in ['secret','rtsp://','192.0.2.'])

def test_catalog_missing_ip_config_does_not_invent_cameras():
    out=build_source_catalog([], '0', {})
    assert len(out['items'])==1 and out['items'][0]['source_key']=='0'

def test_catalog_invalid_source_visible_but_not_selectable():
    out=build_source_catalog([{'id':2,'source':'','name':'Needs setup'}], '0', {})
    item=next(x for x in out['items'] if x['id']==2)
    assert item['health_status']=='INVALID' and not item['selectable']

def test_catalog_deduplicates_builtin_camera():
    out=build_source_catalog([{'id':1,'source':'0'},{'id':2,'source':'0'}], '0', {})
    assert len(out['items'])==1

def test_sources_api_anonymous_denied(isolated):
    assert isolated.get('/api/v1/camera/sources').status_code==401

def test_sources_api_owner_sees_all_registered_no_capture(isolated):
    a=add_camera();b=add_camera('Disabled','rtsp://192.0.2.10/x',0);c=add_camera('USB','2',1,'USB')
    r=signed_in(isolated).get('/api/v1/camera/sources')
    assert r.status_code==200,r.text
    items={x['id']:x for x in r.json()['items']}
    assert all(x in items for x in (a,b,c)) and items[a]['active']
    assert not items[b]['selectable'] and items[c]['selectable']
    assert 'test-only' not in r.text and 'rtsp://' not in r.text
    assert r.headers['cache-control']=='no-store'

def test_sources_api_employee_cannot_read(isolated):
    auth.create_user('qa_employee','Employee','EMPLOYEE',PW)
    r=signed_in(isolated,'qa_employee').get('/api/v1/camera/sources')
    assert r.status_code==403,r.text

def test_alias_resolves_server_side_and_disabled_is_rejected(isolated):
    cid=add_camera();disabled=add_camera('Disabled','rtsp://192.0.2.10/x',0)
    source,label=main._resolve_camera_selection(f'CAM{cid:02d}')
    assert source.startswith('rtsp://operator:test-only@') and label=='Door'
    with pytest.raises(ValueError):main._resolve_camera_selection(f'CAM{disabled:02d}')

def test_usb_one_is_not_network_alias(isolated):
    add_camera()
    assert main._resolve_camera_selection('1')[0]=='1'

def test_active_source_comparison_uses_internal_not_redacted_value(isolated):
    cid=add_camera()
    row,source,active=main._fleet_camera_source(cid)
    assert active and 'test-only' in source

def test_disabled_fleet_source_never_opens(isolated):
    cid=add_camera(enabled=0)
    with pytest.raises(HTTPException) as error:main._fleet_camera_source(cid)
    assert error.value.status_code==409

@pytest.mark.parametrize('path',['frame.jpg','frame_raw.jpg'])
def test_finite_frames_send_age_and_sequence(isolated,path):
    r=signed_in(isolated).get('/api/v1/camera/'+path)
    assert r.status_code==200 and r.headers['content-type']=='image/jpeg'
    assert r.headers['x-camera-seq']=='123' and float(r.headers['x-frame-age-ms'])==12.5

def test_missing_frame_is_explicit_503(isolated,monkeypatch):
    monkeypatch.setattr(main.CAMERA,'preview_packet',lambda raw=False:(b'',0,None))
    assert signed_in(isolated).get('/api/v1/camera/frame.jpg').status_code==503

def test_preview_packet_marks_raw_and_preserves_encoded_sequence():
    obj=object.__new__(StaticCameraService)
    obj._lock=threading.RLock()
    obj._raw_jpeg=b'raw';obj._raw_jpeg_seq=7;obj._raw_jpeg_at=0
    obj._jpeg=b'view';obj._jpeg_seq=8;obj._jpeg_at=0
    assert obj.preview_packet(True)==(b'raw',7,None)
    assert obj._raw_requested_at>0
    assert obj.preview_packet(False)==(b'view',8,None)
    assert obj._preview_requested_at>0

def test_stream_disconnect_stops_async_iterator(isolated,monkeypatch):
    cid=add_camera()
    monkeypatch.setattr(main.FLEET_V4,'stop',lambda *a,**kw:True)
    class Gone:
        async def is_disconnected(self):return True
    response=main.camera_fleet_stream(cid,Gone())
    async def collect():return [part async for part in response.body_iterator]
    assert asyncio.run(collect())==[]

def test_operations_websocket_rejects_anonymous(isolated):
    with pytest.raises(WebSocketDisconnect):
        with isolated.websocket_connect('/api/v1/operations/live/ws') as ws:ws.receive_json()

def test_operations_websocket_rejects_employee(isolated):
    auth.create_user('qa_employee','Employee','EMPLOYEE',PW);signed_in(isolated,'qa_employee')
    with pytest.raises(WebSocketDisconnect):
        with isolated.websocket_connect('/api/v1/operations/live/ws') as ws:ws.receive_json()

def test_navigation_presentation_has_no_mutation_observer_feedback_loop():
    js=(ROOT/'frontend/js/btmh_customer_v541.js').read_text()
    assert 'new MutationObserver' not in js
    assert "'btmh:navigate'" in js and 'aria-current' in js

def test_runtime_has_bounded_single_flight_and_cancellation():
    js=(ROOT/'frontend/js/btmh_runtime_v543.js').read_text()
    assert 'networkInFlight<3' in js and 'new AbortController()' in js
    assert 'jobs.has(key)' in js and 'URL.revokeObjectURL' in js
    assert "document.addEventListener('visibilitychange'" in js

def test_login_uses_preserved_logo_and_left_brand_right_light_form():
    html=(ROOT/'frontend/index.html').read_text(encoding='utf-8');css=(ROOT/'frontend/css/btmh_ui_v543.css').read_text(encoding='utf-8')
    assert 'gold-jewelry-v543.svg' in html and 'btmh_official_logo.png' in html
    assert html.index('class="btmh-store-story btmh-gold-story"')<html.index('class="btmh-auth-card"')
    assert 'prefers-reduced-motion' in css and '#fffdf9' in css

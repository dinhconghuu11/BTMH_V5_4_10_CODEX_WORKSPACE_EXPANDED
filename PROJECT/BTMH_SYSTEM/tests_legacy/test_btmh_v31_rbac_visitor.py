from pathlib import Path
import os, subprocess, sys, textwrap

CORE = Path(__file__).resolve().parents[1]


def test_btmh_v31_static_contract():
    auth = (CORE / 'module_app/auth.py').read_text(encoding='utf-8')
    main = (CORE / 'module_app/main.py').read_text(encoding='utf-8')
    walkby = (CORE / 'module_app/walkby.py').read_text(encoding='utf-8')
    html = (CORE / 'frontend/index.html').read_text(encoding='utf-8')
    css = (CORE / 'frontend/css/professional_v25_btmh_security.css').read_text(encoding='utf-8')
    assert 'ROLE_DEFINITIONS' in auth and 'require_permission' in auth
    assert 'SECURITY' in auth and 'TECHNICIAN' in auth and 'MANAGER' in auth
    assert '/api/v1/visitors' in main and '/api/v1/admin/roles' in main
    assert 'best_shots_revision' in walkby and 'touch_visitor_unknown' in walkby
    assert 'id="page-visitors"' in html and 'Tài khoản &amp; phân quyền' in html
    assert 'btmh-visitor-card' in css and 'btmh-rbac-panel' in css


def test_btmh_v31_runtime_rbac_and_visitor(tmp_path: Path):
    code = r'''
import base64
from module_app.db import init_db
from module_app.production_ops import ensure_production_schema
from module_app.auth import enforce_admin_only, bootstrap_admin, create_user, login, require_role, require_permission, update_user
from module_app.visitor import ensure_visitor_schema, touch_unknown, close_track, list_sessions
from module_app.recording import ensure_recording_schema, archive_status
init_db(); ensure_production_schema(); enforce_admin_only(); ensure_visitor_schema(); ensure_recording_schema()
bootstrap_admin('admin','Admin','Password123!')
create_user('security01','Security','SECURITY','Password123!')
create_user('hr01','HR','HR','Password123!')
sec=login('security01','Password123!'); hr=login('hr01','Password123!')
assert require_permission('Bearer '+sec['token'],'visitor.review')['role']=='SECURITY'
assert require_permission('Bearer '+hr['token'],'employee.manage')['role']=='HR'
try:
    require_permission('Bearer '+sec['token'],'employee.manage')
    raise AssertionError('SECURITY must not manage employees')
except PermissionError: pass
try:
    require_role('Bearer '+sec['token'], {'ADMIN'})
    raise AssertionError('SECURITY must not be ADMIN')
except PermissionError: pass
jpg=base64.b64encode(b'jpeg-demo').decode()
v=touch_unknown(track_ref='walkby:7',camera_source='CAM01',event_id=10,best_shots=[
    {'data_url':'data:image/jpeg;base64,'+jpg,'quality':.91,'pose':'center'},
    {'data_url':'data:image/jpeg;base64,'+jpg,'quality':.87,'pose':'left'},
])
assert v['status']=='ACTIVE' and len(v['best_shots'])==2
assert close_track(track_ref='walkby:7',camera_source='CAM01')['status']=='CLOSED'
assert list_sessions(limit=5)[0]['camera_source']=='CAM01'
assert archive_status()['mode']=='NVR_OR_LOCAL_INDEX'
print('OK')
'''
    env = os.environ.copy()
    env['CAMPUSFACE_DB_MODE'] = 'sqlite'
    env['CAMPUSFACE_DATA_ROOT'] = str(tmp_path / 'data')
    env['PYTHONPATH'] = str(CORE)
    cp = subprocess.run([sys.executable, '-c', textwrap.dedent(code)], env=env, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert 'OK' in cp.stdout

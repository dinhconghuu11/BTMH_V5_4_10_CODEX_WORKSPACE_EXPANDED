from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
ROOT = CORE.parents[1]


def test_admin_only_and_mobile_read_only_static_contract():
    main = (CORE / 'module_app/main.py').read_text(encoding='utf-8')
    auth = (CORE / 'module_app/auth.py').read_text(encoding='utf-8')
    html = (CORE / 'frontend/index.html').read_text(encoding='utf-8')
    mobile = (CORE / 'frontend/mobile/index.html').read_text(encoding='utf-8')
    mobile_js = (CORE / 'frontend/mobile/mobile.js').read_text(encoding='utf-8')
    assert 'V2.4 chỉ sử dụng một quyền quản trị ADMIN' in auth
    assert 'UPPER(role)=\'ADMIN\'' in auth
    assert 'Mobile Viewer chỉ có quyền xem' in main
    assert 'request.method.upper() not in {"GET", "HEAD"}' in main
    assert '@app.get("/mobile")' in main
    assert '/api/v1/mobile/summary' in main
    assert '/api/v1/mobile/presence' in main
    assert '/api/v1/mobile/history/recognition' in main
    assert '/api/v1/mobile/history/hr' in main
    assert '/api/v1/mobile/camera/stream.mjpg' in main
    assert 'id="mobileViewerForm"' in html
    assert 'READ ONLY' in mobile
    assert '/api/v1/mobile/auth/login' in mobile_js
    assert '/api/v1/mobile/camera/stream.mjpg' in mobile_js
    # No secondary-role creation controls remain in the current admin page.
    assert 'id="newUserRole"' not in html
    assert '<option value="OPERATOR">' not in html
    assert '<option value="VIEWER">' not in html


def test_mobile_auth_roundtrip_and_secondary_user_blocked(tmp_path: Path):
    code = r'''
from module_app.db import init_db
from module_app.production_ops import ensure_production_schema
init_db(); ensure_production_schema()
from module_app.auth import bootstrap_admin, login, create_user, configure_mobile_viewer, mobile_login, mobile_user_for_token
bootstrap_admin('admin','Admin','Password123!')
assert login('admin','Password123!')['user']['role']=='ADMIN'
try:
    create_user('operator','Operator','OPERATOR','Password123!')
    raise AssertionError('secondary user created')
except ValueError:
    pass
st=configure_mobile_viewer(enabled=True,password='Viewer123!')
assert st['enabled'] is True and st['mode']=='READ_ONLY'
r=mobile_login('Viewer123!')
assert mobile_user_for_token(r['token'])['mode']=='READ_ONLY'
print('PASS')
'''
    env = os.environ.copy()
    env.update({'PYTHONPATH': str(CORE), 'CAMPUSFACE_DB_MODE': 'sqlite', 'CAMPUSFACE_DATA_ROOT': str(tmp_path/'data')})
    proc = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + '\n' + proc.stderr
    assert 'PASS' in proc.stdout


def test_camera_handover_contract_preserved():
    # Camera performance/media internals evolve after V2.4, but the two source
    # handover methods must remain byte-for-byte equivalent to the stable V2.7
    # contract. camera_profiles.py also remains unchanged from the V2.4 baseline.
    camera_path = CORE / 'module_app' / 'camera.py'
    source = camera_path.read_text(encoding='utf-8')
    tree = ast.parse(source)
    expected_methods = {
        'safe_select_source': '9318e9a97ed23ae89332540438f34bdfa145bfea373f3b3ff7c96905e240fa4c',
        'select_source': '7a1006e76b37ea5dcf0668387ded5ef5b3d4c7078830c035eb297b52c16b539c',
    }
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in expected_methods:
            segment = ast.get_source_segment(source, node) or ''
            found[node.name] = hashlib.sha256(segment.encode('utf-8')).hexdigest()
    assert found == expected_methods
    profile_digest = hashlib.sha256((CORE/'module_app'/'camera_profiles.py').read_bytes()).hexdigest()
    assert profile_digest == '9ae23d1833bc8f9e25c84da4a6489398e7f92a7bbfa23e68dc05a287ef4bfefd'


def test_mobile_packaging_contract():
    assert (ROOT/'tools/install/ENABLE_MOBILE_LAN_ACCESS.bat').exists()
    assert (ROOT/'tools/install/DISABLE_MOBILE_LAN_ACCESS.bat').exists()
    for name in ['index.html','mobile.css','mobile.js','manifest.webmanifest','sw.js','icon-192.png','icon-512.png']:
        assert (CORE/'frontend/mobile'/name).exists(), name


if __name__ == '__main__':
    import tempfile
    test_admin_only_and_mobile_read_only_static_contract()
    with tempfile.TemporaryDirectory(prefix='cf-v24-') as td:
        test_mobile_auth_roundtrip_and_secondary_user_blocked(Path(td))
    test_camera_handover_contract_preserved()
    test_mobile_packaging_contract()
    print('[OK] CampusFace V2.4 Admin + Mobile Viewer contract passed')

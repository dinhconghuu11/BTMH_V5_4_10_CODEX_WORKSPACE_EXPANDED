from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def _run(script: str, data_root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DB_MODE": "sqlite",
        "CAMPUSFACE_DATA_ROOT": str(data_root),
    })
    return subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=45)


def test_v210_static_contracts():
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    pilot = (CORE / "module_app" / "production_pilot.py").read_text(encoding="utf-8")
    office = (CORE / "module_app" / "office_engine.py").read_text(encoding="utf-8")
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/production/status" in main
    assert "/api/v1/production/recover-camera" in main
    assert "/api/v1/office/gate/test" in main
    assert '"virtual_gate": True' in main
    assert "CAPTURE_THREAD_ONLY" in (CORE / "module_app" / "camera.py").read_text(encoding="utf-8")
    assert "CAMERA.restart()" in pilot
    assert "create_backup(\"auto\")" in pilot
    assert "camera_source_fingerprint" in office
    assert "Virtual Gate tạm dừng" in office
    assert "v210ProductionForm" in html
    assert "officeGateTestBtn" in html
    assert "loadProductionStatus" in js
    assert "testOfficeGate" in js


def test_v210_supervisor_config_and_health_snapshot(tmp_path: Path):
    script = r'''
from module_app.db import init_db
from module_app.production_ops import ensure_production_schema
from module_app.production_pilot import PILOT
init_db(); ensure_production_schema()
cfg=PILOT.save_config({"camera_stale_sec":1,"auto_backup_interval_hours":1,"auto_backup_retention":1,"watchdog_enabled":True})
assert cfg["camera_stale_sec"] >= 4.0
assert cfg["auto_backup_interval_hours"] >= 6.0
assert cfg["auto_backup_retention"] >= 3
st=PILOT.force_check()
assert "resources" in st and "database" in st and "watchdog" in st and "backup" in st
assert st["database"]["ok"] is True
print("PASS")
'''
    proc = _run(script, tmp_path / "pilot")
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v210_gate_binding_fields_survive_sanitize(tmp_path: Path):
    script = r'''
from module_app.db import init_db
from module_app.production_ops import ensure_production_schema
from module_app.office_engine import OFFICE
init_db(); ensure_production_schema()
cfg=OFFICE.save_config({"line":{"configured":True,"enabled":True,"x1":.1,"y1":.5,"x2":.9,"y2":.5,"camera_id":7,"camera_name":"Camera 07","zone_name":"Cua vao","camera_source_fingerprint":"abcdef1234567890"}})
line=cfg["line"]
assert line["camera_id"]==7
assert line["camera_name"]=="Camera 07"
assert line["zone_name"]=="Cua vao"
assert line["camera_source_fingerprint"]=="abcdef1234567890"
print("PASS")
'''
    proc = _run(script, tmp_path / "gate")
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v210_production_installer_and_version():
    root = CORE.parents[1]
    assert (root / "tools" / "install" / "CAMPUSFACE_PRODUCTION_PILOT_SETUP.bat").exists()
    assert (root / "tools" / "diagnostics" / "VERIFY_V2_10_PRODUCTION_PILOT.bat").exists()
    assert "V2.10" in (root / "VERSION.txt").read_text(encoding="utf-8")
    config = (CORE / "module_app" / "config.py").read_text(encoding="utf-8")
    assert 'APP_VERSION = "2.10.0-production-pilot"' in config


def test_v210_backup_includes_operational_json_config(tmp_path: Path):
    script = r'''
import json, zipfile
from pathlib import Path
from module_app.db import init_db
from module_app.production_ops import ensure_production_schema, create_backup
from module_app.config import CONFIG_DIR
init_db(); ensure_production_schema()
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
(CONFIG_DIR/'office_ai.json').write_text(json.dumps({'line':{'configured':True}}),encoding='utf-8')
(CONFIG_DIR/'production_pilot.json').write_text(json.dumps({'watchdog_enabled':True}),encoding='utf-8')
r=create_backup('test-v210')
with zipfile.ZipFile(r['path'],'r') as zf:
    names=set(zf.namelist())
    assert 'Config/office_ai.json' in names, names
    assert 'Config/production_pilot.json' in names, names
print('PASS')
'''
    proc = _run(script, tmp_path / "backup")
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout

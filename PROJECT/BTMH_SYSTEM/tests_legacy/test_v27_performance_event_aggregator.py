from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def test_v27_preview_performance_contract():
    config = (CORE / "module_app" / "config.py").read_text(encoding="utf-8")
    camera = (CORE / "module_app" / "camera.py").read_text(encoding="utf-8")
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    start = (CORE / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
    assert 'MODULE_CLASSROOM_PREVIEW_FPS", "25"' in config
    assert 'MODULE_CLASSROOM_JPEG_QUALITY", "92"' in config
    assert 'MODULE_QUICK_REARM_SEC", "2.60"' in config
    assert 'fflags;nobuffer' in camera
    assert 'CAP_PROP_HW_ACCELERATION' in camera
    assert 'classroom_encode_ms' in camera
    assert 'cv2.filter2D' in camera
    assert 'id="officePreviewCanvas"' in html
    assert 'createImageBitmap' in js
    assert "desynchronized:true" in js
    assert 'apply_v27_performance_config.py' in start


def test_v27_recognition_history_excludes_login_audit():
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    assert 'LOGIN_SUCCESS/LOGIN_FAILED belong to System > Audit Log' in main
    assert 'biometric_audit = (cat == "FACEID")' in main
    assert 'key = f"UNK_EP:{item.get(\'source_id\')}"' in main
    assert 'def _history_spatial_bucket' in main


def test_v27_unknown_and_spoof_episode_aggregation(tmp_path: Path):
    data_root = tmp_path / "data"
    script = r'''
from module_app.db import init_db, add_unknown_event, add_spoof_event, fetchall
init_db()
base={"bbox":[100,100,160,180],"frame_width":1280,"frame_height":720,"reason":"no-match"}
a=add_unknown_event("sess:1",base,camera_source="hikvision")
b=add_unknown_event("sess:9",{"bbox":[112,105,158,178],"frame_width":1280,"frame_height":720,"reason":"no-match"},camera_source="hikvision")
assert a["id"] == b["id"], (a,b)
assert b.get("deduplicated") is True
rows=fetchall("SELECT id,status,detail_json FROM recognition_events ORDER BY id")
assert len(rows)==1, rows
# PAD later confirms the same physical face is a spoof: promote, do not insert row 2.
c=add_spoof_event("sess:10",{"bbox":[118,110,155,175],"frame_width":1280,"frame_height":720,"reason":"phone-screen"},camera_source="hikvision",liveness_score=.9)
assert c["id"] == a["id"], (a,c)
assert c.get("promoted_from_unknown") is True
rows=fetchall("SELECT id,status,detail_json FROM recognition_events ORDER BY id")
assert len(rows)==1 and rows[0]["status"]=="SPOOF_BLOCKED", rows
# A second person far away must remain a separate episode when bbox metadata exists.
d=add_unknown_event("sess:20",{"bbox":[900,100,150,180],"frame_width":1280,"frame_height":720,"reason":"no-match"},camera_source="hikvision")
rows=fetchall("SELECT id,status FROM recognition_events ORDER BY id")
assert len(rows)==2, rows
assert d["id"] != a["id"]
print("PASS")
'''
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(CORE),
        "CAMPUSFACE_DB_MODE": "sqlite",
        "CAMPUSFACE_DATA_ROOT": str(data_root),
        "CAMPUSFACE_UNKNOWN_EVENT_DEDUP_SEC": "180",
        "CAMPUSFACE_SPOOF_EVENT_DEDUP_SEC": "180",
        "CAMPUSFACE_SPOOF_PROMOTE_UNKNOWN_SEC": "90",
        "CAMPUSFACE_UNKNOWN_AFTER_SPOOF_HOLD_SEC": "60",
    })
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "PASS" in proc.stdout


def test_v27_clean_ui_contract():
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (CORE / "frontend" / "css" / "professional_v20_clean_ui.css").read_text(encoding="utf-8")
    assert "professional_v20_clean_ui.css?v=2.7.0" in html
    assert "history-storage-policy" not in html
    assert "office-gate-help" not in html
    assert "Business Event + Session" not in html
    assert "Nhật ký kỹ thuật / xác minh" not in html
    assert "grid-template-columns:minmax(190px,.45fr)" in css
    assert "flex-wrap:wrap!important" in css
    assert "position:relative!important" in css
    assert ".faceid-v13-simple-help" in css

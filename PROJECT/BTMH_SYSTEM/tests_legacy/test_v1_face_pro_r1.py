from __future__ import annotations

import sys
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np

_STANDALONE_ROOT = tempfile.TemporaryDirectory(prefix="cf-pro-r1-test-")
os.environ.setdefault("CAMPUSFACE_DB_MODE", "sqlite")
os.environ.setdefault("CAMPUSFACE_DATA_ROOT", _STANDALONE_ROOT.name)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.anti_spoof as anti
from module_app.anti_spoof import AntiSpoofEngine
from module_app.device_context import DeviceEvidence
from module_app.passive_pad import PadResult
from module_app.db import execute, init_db, utc_now
from module_app.production_ops import ensure_production_schema, create_backup
from module_app.student_media import save_enrollment_photo, photo_path, student_photos
from module_app.action_engine import vietnamese_posture_label, vietnamese_activity_label


FRAME = np.zeros((480, 640, 3), np.uint8)
OBS = SimpleNamespace(bbox=(120, 100, 130, 170), yaw=0.0, pitch=0.0)


class MissingPad:
    def predict(self, image, bbox):
        return PadResult(False, reason="optional PAD absent")


class SwitchDevice:
    def __init__(self, mode="clean"):
        self.mode = mode

    def evaluate_face(self, image, bbox, now=None):
        if self.mode == "phone":
            return DeviceEvidence(
                risk=.97, hard=True, reason="FACE_INSIDE_PHONE_OR_PHOTO",
                source="geometry_carrier", device="phone/photo-carrier",
                confidence=.97, inside_ratio=.98,
            )
        return DeviceEvidence(risk=.08, hard=False, source="none")


def test_blocked_track_recovers_after_phone_leaves():
    old_pad, old_device = anti.PAD, anti.DEVICE_CONTEXT
    device = SwitchDevice("phone")
    try:
        anti.PAD, anti.DEVICE_CONTEXT = MissingPad(), device
        eng = AntiSpoofEngine(); eng._face_mesh_attempted = True; eng._face_mesh = False
        assert eng.update("track", FRAME, OBS, now=10.0).status == "CHECKING"
        blocked = eng.update("track", FRAME, OBS, now=10.2)
        assert blocked.status == "BLOCKED", blocked.public()

        device.mode = "clean"
        d = eng.update("track", FRAME, OBS, now=10.4)
        assert d.status == "BLOCKED" and d.signals.get("recovery_stage") == "CLEANING", d.public()
        eng.update("track", FRAME, OBS, now=10.7)
        checking = eng.update("track", FRAME, OBS, now=11.0)
        assert checking.status == "CHECKING", checking.public()
        assert checking.spoof_method == "", checking.public()

        eng.update("track", FRAME, OBS, now=11.2)
        eng.update("track", FRAME, OBS, now=11.4)
        passed = eng.update("track", FRAME, OBS, now=11.6)
        assert passed.status == "PASS", passed.public()
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = old_pad, old_device


def test_phone_return_during_recovery_reblocks_clean_counter():
    old_pad, old_device = anti.PAD, anti.DEVICE_CONTEXT
    device = SwitchDevice("phone")
    try:
        anti.PAD, anti.DEVICE_CONTEXT = MissingPad(), device
        eng = AntiSpoofEngine(); eng._face_mesh_attempted = True; eng._face_mesh = False
        eng.update("track2", FRAME, OBS, now=20.0)
        assert eng.update("track2", FRAME, OBS, now=20.2).status == "BLOCKED"
        device.mode = "clean"
        eng.update("track2", FRAME, OBS, now=20.4)
        device.mode = "phone"
        d = eng.update("track2", FRAME, OBS, now=20.6)
        assert d.status == "BLOCKED", d.public()
        assert int(d.signals.get("recovery_clean_streak", -1)) == 0, d.public()
    finally:
        anti.PAD, anti.DEVICE_CONTEXT = old_pad, old_device


def test_student_portrait_is_stored_outside_database_and_backed_up():
    init_db(); ensure_production_schema()
    now = utc_now()
    sid = execute(
        """INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,
        biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        ("PRO-R1-001", "Sinh vien test", "A1", "CNTT", "", "", now, "GRANTED", now, now, now),
    )
    image = np.full((180, 150, 3), 165, dtype=np.uint8)
    saved = save_enrollment_photo(int(sid), image)
    assert saved and saved.get("photo_type") == "PROFILE"
    path = photo_path(int(sid))
    assert path is not None and path.exists() and "Photos" in str(path)
    rows = student_photos(int(sid))
    assert {x["photo_type"] for x in rows} == {"ENROLLMENT_BEST", "PROFILE"}

    backup = create_backup("pro-r1-media-test")
    with zipfile.ZipFile(backup["path"], "r") as zf:
        names = set(zf.namelist())
        assert any(name.startswith("Photos/Students/") and name.endswith("profile.jpg") for name in names)


def test_action_labels_are_split_into_posture_and_activity():
    track = {"posture": "SEATED", "moving": True, "hand_raised": False, "using_phone": False}
    assert vietnamese_posture_label(track) == "Đang ngồi"
    assert vietnamese_activity_label(track) == "Di chuyển"


def test_release_contract_has_stable_data_root_and_native_camera():
    cfg = (ROOT / "module_app" / "config.py").read_text(encoding="utf-8")
    cam = (ROOT / "module_app" / "camera.py").read_text(encoding="utf-8")
    walk = (ROOT / "module_app" / "walkby.py").read_text(encoding="utf-8")
    resolver = (ROOT / "scripts" / "resolve_data_root.bat").read_text(encoding="utf-8")
    migration = (ROOT / "scripts" / "apply_pro_r1_config.py").read_text(encoding="utf-8")
    starter = (ROOT / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
    runner = (ROOT / "run_module.py").read_text(encoding="utf-8")
    main = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    assert 'stable = local / "CampusFace"' in cfg and 'legacy = local / "CampusFaceV1142"' in cfg
    assert "CF_STABLE_ROOT=%LOCALAPPDATA%\\CampusFace" in resolver
    assert r"CF_LEGACY_ROOT=%LOCALAPPDATA%\CampusFaceV1142" in resolver
    assert "CAMPUSFACE_CONFIG_REV" in migration and "1920" in migration and "1080" in migration
    assert ("apply_pro_r1_config.py" in starter) or ("apply_pro_r2_config.py" in starter)
    assert "vendor_py" in runner and (ROOT / "vendor_py" / "websockets" / "__init__.py").exists()
    assert 'MODULE_CAMERA_WIDTH", "1920"' in cfg and 'MODULE_CAMERA_HEIGHT", "1080"' in cfg
    assert "AI_NATIVE_FRAME" in cam and "ai_input_width" in cam
    assert "if tr.spoof_blocked and not live.blocked" in walk
    assert 'students/{student_id}/photo' in main and "student_photos" in main


if __name__ == "__main__":
    tests = [
        test_blocked_track_recovers_after_phone_leaves,
        test_phone_return_during_recovery_reblocks_clean_counter,
        test_student_portrait_is_stored_outside_database_and_backed_up,
        test_action_labels_are_split_into_posture_and_activity,
        test_release_contract_has_stable_data_root_and_native_camera,
    ]
    for fn in tests:
        fn(); print("[PASS]", fn.__name__)
    print("[OK] V1 FACE PRO R1 regression passed")

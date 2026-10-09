"""Shared capture with actual registry geometry/readiness and isolated fake models."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sqlite3
import struct
import sys
import threading
import types
import unittest
import uuid

import cv2
import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


class FakeCore:
    def __init__(self):
        self.yaw = self.pitch = 0.0
        self.faces = 1
        self.detect_calls = self.observe_calls = 0
        self.sharpness = 80.0
        self.face = np.array([240, 120, 160, 240, 280, 180, 360, 180, 320, 220, 290, 270, 350, 270, .99], dtype=np.float32)

    def detect(self, image, **kwargs):
        self.detect_calls += 1
        return [self.face] * self.faces

    def bbox(self, face, shape):
        return (240, 120, 160, 240)

    def observe(self, image, face):
        self.observe_calls += 1
        embedding = np.array([1., self.yaw, self.pitch, .2], dtype=np.float32)
        embedding /= np.linalg.norm(embedding)
        return types.SimpleNamespace(embedding=embedding, pose="center", yaw=self.yaw, pitch=self.pitch,
                                     bbox=self.bbox(face, image.shape),
                                     quality={"face_px": 160, "sharpness": self.sharpness, "brightness": 120., "score": .82})

    def face_crop(self, image, bbox, **kwargs):
        return image[120:360, 240:400].copy()


class FakePad:
    def __init__(self):
        self.status = "PASS"
        self.calls = []
        self.states = {}
        self.entered = self.release = None

    def update(self, key, image, obs):
        self.calls.append(key)
        self.states[key] = self.states.get(key, 0) + 1
        if self.entered is not None:
            self.entered.set()
            if not self.release.wait(3):
                raise AssertionError("test worker was not released")
        public = {"status": self.status, "score": .99, "reason": "test", "observations": self.states[key],
                  "decision_version": "existing-engine", "signals": {"internal": True}}
        return types.SimpleNamespace(status=self.status, public=lambda: public)

    def purge_prefix(self, key):
        self.states = {k: value for k, value in self.states.items() if not k.startswith(key)}


@dataclass(frozen=True)
class PreparedDraft:
    template_blob: bytes
    preview_blob: bytes | None
    pose_count: int
    quality: dict
    pad: dict
    duplicate: dict | None


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.package = "_enrollment_capture_test_" + uuid.uuid4().hex
        package = types.ModuleType(self.package)
        package.__path__ = [str(SOURCE)]
        sys.modules[self.package] = package
        self.addCleanup(lambda: [sys.modules.pop(key, None) for key in list(sys.modules) if key.startswith(self.package)])
        self.raw = sqlite3.connect(":memory:", check_same_thread=False)
        self.raw.row_factory = sqlite3.Row
        self.addCleanup(self.raw.close)
        self.raw.executescript("CREATE TABLE students(id INTEGER PRIMARY KEY,student_code TEXT,full_name TEXT,biometric_consent_status TEXT);"
                               "CREATE TABLE face_templates(id INTEGER PRIMARY KEY,student_id INTEGER UNIQUE,embedding_blob BLOB,pose_count INTEGER);"
                               "INSERT INTO students VALUES(1,'E1','Employee 1','GRANTED'),(2,'E2','Employee 2','GRANTED');")
        self.now = 100.0
        self.core = FakeCore()
        self.pad = FakePad()
        # Model-free test environment omits cryptography. This reversible fake
        # exercises the existing encryption boundary without claiming crypto QA.
        self.fernet = types.SimpleNamespace(encrypt=lambda raw: b"test-encrypted:" + raw[::-1],
                                            decrypt=lambda blob: blob[len(b"test-encrypted:"):][::-1]
                                            if blob.startswith(b"test-encrypted:") else (_ for _ in ()).throw(ValueError("invalid test ciphertext")))
        self.photos = []

        def stub(name, **values):
            module = types.ModuleType(self.package + "." + name)
            module.__dict__.update(values)
            sys.modules[module.__name__] = module

        def fetchall(sql, args=()):
            return [dict(row) for row in self.raw.execute(sql, args).fetchall()]

        def fetchone(sql, args=()):
            row = self.raw.execute(sql, args).fetchone()
            return dict(row) if row else None

        stub("config", ENROLL_MIN_FACE_PX=100, ENROLL_MIN_SHARPNESS=20., ENROLL_MIN_TOTAL=10,
             ENROLL_SAMPLE_GAP_SEC=.4, ENROLL_TARGET=10)
        stub("db", fetchall=fetchall, fetchone=fetchone)
        stub("crypto", encrypt_bytes=self.fernet.encrypt, decrypt_bytes=self.fernet.decrypt)
        stub("face_core", CORE=self.core)
        stub("anti_spoof", ANTI_SPOOF=self.pad)
        stub("student_media", save_enrollment_photo=lambda *args, **kwargs: self.photos.append(args) or True)
        stub("qr_enrollment", PreparedDraft=PreparedDraft)

        def load(name):
            spec = importlib.util.spec_from_file_location(self.package + "." + name, SOURCE / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module

        self.registry = load("registry")
        self.registry.time = types.SimpleNamespace(time=lambda: self.now)
        self.module = load("enrollment_capture")
        self.capture = self.module.EnrollmentCapture(clock=lambda: self.now,
                                                    utc_clock=lambda: datetime(2026, 10, 8, 12, tzinfo=timezone.utc))
        self.image = np.full((480, 640, 3), 100, dtype=np.uint8)

    def frame(self, yaw=0., pitch=0., request="request-1", student=1):
        self.now += 1
        self.core.yaw, self.core.pitch = yaw, pitch
        return self.capture.frame(request, student, self.image)

    def finish(self):
        for _ in range(4):
            response = self.frame()
        for yaw, pitch in ((-.09, 0), (-.04, .06), (.09, 0), (.03, -.06), (0, 0),
                           (-.09, 0), (-.04, .06), (.09, 0), (.03, -.06), (0, 0)):
            response = self.frame(yaw, pitch)
        self.assertTrue(response["capture_ready"], response)
        return response

    def test_actual_two_pass_preparation_encrypted_no_publication(self):
        response = self.finish()
        draft = self.capture.prepare("request-1", 1)
        self.assertIsInstance(draft, PreparedDraft)
        self.assertEqual(draft.quality["scan_passes"], 2)
        self.assertEqual(draft.pose_count, 10)
        self.assertEqual(draft.pad["status"], "PASS")
        self.assertTrue(draft.pad["verified_at"].endswith("+00:00"))
        self.assertNotIn("signals", draft.pad)
        self.assertEqual(self.registry.decode_template(draft.template_blob).shape, (10, 4))
        self.assertTrue(self.fernet.decrypt(draft.preview_blob).startswith(b"\xff\xd8"))
        self.assertEqual(self.raw.execute("SELECT COUNT(*) FROM face_templates").fetchone()[0], 0)
        self.assertFalse(self.photos)
        self.assertEqual(self.core.detect_calls, self.core.observe_calls)
        self.assertEqual(self.core.observe_calls, len(self.pad.calls))
        self.assertEqual(response["guidance_phases"], ["CENTER", "LEFT", "RIGHT", "CENTER", "LIVENESS"])
        self.assertEqual(response["capture_phase"], "LIVENESS")

    def test_pad_nonpass_never_seeds_calibration_or_accepts_samples(self):
        for status in ("CHECKING", "BLOCKED", "MODEL_UNAVAILABLE"):
            self.pad.status = status
            for _ in range(5):
                response = self.frame()
                self.assertFalse(response["accepted"])
            self.assertFalse(self.registry.ENROLLMENT.sessions)
        self.pad.status = "PASS"
        for _ in range(4):
            response = self.frame()
        self.assertTrue(response["accepted"])
        self.assertEqual(response["captured"], 1)

    def test_quality_and_vertical_coverage_cannot_be_skipped(self):
        self.core.sharpness = 0.
        for _ in range(4):
            self.assertFalse(self.frame()["accepted"])
        self.core.sharpness = 80.
        for _ in range(4):
            self.frame()
        for _ in range(4):
            self.frame(-.09, 0)
            response = self.frame(.09, 0)
            self.frame()
        self.assertFalse(response["ready_to_finalize"])
        with self.assertRaises(ValueError):
            self.capture.prepare("request-1", 1)

    def test_current_pass_invalidated_by_missing_face_and_bad_upload(self):
        self.finish()
        self.core.faces = 0
        self.assertFalse(self.frame()["capture_ready"])
        self.assertFalse(self.pad.states)
        with self.assertRaises(ValueError):
            self.capture.prepare("request-1", 1)
        self.core.faces = 1
        self.assertTrue(self.frame()["capture_ready"])
        with self.assertRaises(ValueError):
            self.capture.frame_upload("request-1", 1, "not-an-image")
        self.assertFalse(self.pad.states)
        with self.assertRaises(ValueError):
            self.capture.prepare("request-1", 1)

    def test_submit_needs_recent_pass_and_current_consent(self):
        self.finish()
        self.now += self.module.PAD_FRESH_SECONDS + 1
        with self.assertRaises(ValueError):
            self.capture.prepare("request-1", 1)
        self.frame()
        self.raw.execute("UPDATE students SET biometric_consent_status='REVOKED' WHERE id=1")
        with self.assertRaises(PermissionError):
            self.capture.prepare("request-1", 1)
        with self.assertRaises(PermissionError):
            self.frame()

    def test_isolated_pad_keys_reset_and_retirement_clear_evidence(self):
        self.frame(request="A")
        self.frame(request="B", student=2)
        keys = set(self.pad.calls)
        self.assertEqual(len(keys), 2)
        old = self.capture._captures["A"]
        self.capture.reset_capture("A")
        new = self.capture._captures["A"]
        self.assertNotEqual(old.key, new.key)
        self.assertEqual(old.created_at, new.created_at)
        self.assertNotIn(old.key, self.pad.states)
        self.assertNotIn(old.key, self.registry.ENROLLMENT.sessions)
        with self.assertRaises(ValueError):
            self.capture.prepare("A", 1)
        self.frame(request="A")
        self.capture.retire_capture("A")
        with self.assertRaises(PermissionError):
            self.frame(request="A")
        self.assertEqual(len(self.pad.states), 1)  # Other capture untouched.
        fresh_process = self.module.EnrollmentCapture(clock=lambda: self.now)
        with self.assertRaises(ValueError):
            fresh_process.prepare("B", 2)

    def test_capture_subject_fixed_and_capacity_bounded(self):
        self.frame()
        with self.assertRaises(PermissionError):
            self.frame(student=2)
        for i in range(self.module.MAX_ACTIVE_CAPTURES - 1):
            self.frame(request=f"R{i}")
        with self.assertRaises(ValueError):
            self.frame(request="overflow")
        self.now += self.module.CAPTURE_TTL_SECONDS + 1
        self.frame(request="new")
        self.assertEqual(len(self.capture._captures), 1)
        self.assertEqual(len(self.pad.states), 1)
        with self.assertRaises(PermissionError):
            self.frame(request="request-1")

    def test_second_frame_and_prepare_busy_before_decode_model(self):
        self.pad.entered, self.pad.release = threading.Event(), threading.Event()
        errors = []
        def worker():
            try:
                self.capture.frame("A", 1, self.image)
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(self.pad.entered.wait(2))
        try:
            calls = self.core.detect_calls
            response = self.capture.frame_upload("A", 1, "invalid-even-before-decode")
            self.assertTrue(response["busy"])
            self.assertEqual(self.core.detect_calls, calls)
            with self.assertRaises(ValueError):
                self.capture.prepare("A", 1)
        finally:
            self.pad.release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(errors)

    def test_jpeg_limits_checked_before_decode_or_inference(self):
        payload = self.module.MAX_IMAGE_BYTES + 1
        oversized = "data:image/jpeg;base64," + base64.b64encode(b"x" * payload).decode()
        with self.assertRaises(ValueError):
            self.capture.frame_upload("R", 1, oversized)
        # Valid SOF framing with malicious oversized dimensions; no decode call.
        sof = b"\xff\xd8\xff\xc0" + struct.pack(">HBHHB", 8, 8, 4000, 4000, 1) + b"\xff\xd9"
        with self.assertRaises(ValueError):
            self.capture.frame_upload("R", 1, "data:image/jpeg;base64," + base64.b64encode(sof).decode())
        self.assertEqual(self.core.detect_calls, 0)
        self.assertFalse(self.pad.calls)
        ok, raw = cv2.imencode(".jpg", self.image)
        self.assertTrue(ok)
        data_url = "data:image/jpeg;base64," + base64.b64encode(raw).decode()
        image = self.module.decode_uploaded_frame(data_url)
        self.assertEqual(image.shape, self.image.shape)
        response = self.capture.frame_upload("R", 1, data_url)
        self.assertEqual(self.core.detect_calls, 1)
        self.assertFalse(response["accepted"])  # Neutral calibration is not skipped.

    def test_duplicate_recheck_uses_current_transaction_and_same_algorithm(self):
        self.finish()
        draft = self.capture.prepare("request-1", 1)
        self.assertIsNone(draft.duplicate)
        self.raw.execute("INSERT INTO face_templates(student_id,embedding_blob,pose_count) VALUES(?,?,?)",
                         (2, draft.template_blob, draft.pose_count))
        expected = self.registry.ENROLLMENT._duplicate_candidate(
            [{"embedding": row} for row in self.registry.decode_template(draft.template_blob)], 1)
        # Global DB reads would miss this transaction in production. Force the
        # callback to use only the caller's approval connection for both queries.
        self.registry.fetchall = self.registry.fetchone = lambda *args: (_ for _ in ()).throw(AssertionError("out-of-transaction DB read"))
        actual = self.registry.recheck_prepared_duplicate(draft.template_blob, 1, self.raw)
        self.assertEqual(actual, expected)
        self.assertEqual(actual["student_id"], 2)
        self.assertTrue(actual["strong"])
        self.assertEqual(self.registry.recheck_prepared_duplicate(draft.template_blob, 2, self.raw), None)
        with self.assertRaises(Exception):
            self.registry.recheck_prepared_duplicate(b"not-encrypted", 1, self.raw)

    def test_legacy_finalize_is_preparation_only_and_no_override_bypass(self):
        self.finish()
        state = self.capture._captures["request-1"]
        material = self.registry.ENROLLMENT.finalize(state.key, 1, confirm_duplicate=True)
        self.assertIn("template_blob", material)
        self.assertEqual(self.raw.execute("SELECT COUNT(*) FROM face_templates").fetchone()[0], 0)
        self.assertFalse(self.photos)
        self.assertIn(state.key, self.registry.ENROLLMENT.sessions)

    def test_preview_and_index_side_effects_only_explicit_after_commit_helpers(self):
        self.finish()
        draft = self.capture.prepare("request-1", 1)
        self.assertTrue(self.module.save_approved_preview(1, draft.preview_blob))
        self.assertEqual(len(self.photos), 1)
        calls = []
        self.module.INDEX = types.SimpleNamespace(invalidate=lambda: calls.append("invalidate"), load=lambda **kw: calls.append(kw))
        self.module.refresh_active_index()
        self.assertEqual(calls, ["invalidate", {"force": True}])


if __name__ == "__main__":
    unittest.main()

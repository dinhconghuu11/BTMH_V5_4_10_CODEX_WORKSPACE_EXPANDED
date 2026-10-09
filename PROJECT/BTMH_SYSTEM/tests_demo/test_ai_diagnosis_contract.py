"""Readonly diagnosis/public AI availability; no cameras, app startup or models."""
from __future__ import annotations

import ast
import importlib.util
import math
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("btmh_readonly_diagnosis", ROOT / "scripts/diagnose_camera_ai.py")
diagnosis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnosis)


def public_functions():
    tree = ast.parse((ROOT / "module_app/main.py").read_text(encoding="utf-8"))
    names = {"_public_ai_status", "_media_tracking_payload", "_public_verification_diagnostics", "_public_ai_number", "_public_ai_performance", "_public_ai_detection"}
    scope = {"time": SimpleNamespace(time=lambda: 10.), "math": math}
    code = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
    exec(compile(code, "main.py isolated public functions", "exec"), scope)
    return scope


class PublicAIStatusTests(unittest.TestCase):
    def payload(self, state):
        scope = public_functions()
        context = {"camera_id": 7, "store_id": 2, "zone_name": "Entry"}
        service = SimpleNamespace(
            latest_result=lambda: {"tracks": [{"track_id": "cached", "recognized": True, "full_name": "stale identity", "student_id": 99}]},
            status=lambda: {"actual_width": 800, "actual_height": 600}, performance_status=lambda: {})
        scope.update(AI_RUNTIME=SimpleNamespace(context=lambda _: context, service=lambda _: service,
                                               camera_state=lambda _: {"ai_state": state, "reason_code": "AI_PROCESS_FAILED"}),
                     camera_context=lambda _: context)
        return scope["_media_tracking_payload"](7)

    def test_unavailable_ai_suppresses_cached_identity_and_boxes(self):
        for state in ("ERROR", "PAUSED", "STARTING", "DISABLED", "OFFLINE", "WAITING_FOR_CAPACITY", "STOPPING"):
            with self.subTest(state=state):
                payload = self.payload(state)
                self.assertEqual(payload["tracks"], [])
                self.assertNotIn("stale identity", str(payload))
                self.assertEqual(payload["updated_at"], 0.)
                self.assertIsNone(payload["ai_detection"])

    def test_active_ai_keeps_existing_verified_track_contract(self):
        payload = self.payload("ACTIVE")
        self.assertEqual(payload["tracks"][0]["full_name"], "stale identity")
        self.assertEqual(payload["bbox_format"], "xywh")
        self.assertEqual(payload["camera_id"], 7)

    def test_public_failure_fields_never_return_raw_errors(self):
        scope = public_functions()
        result = scope["_public_ai_status"]({"ai_state": "ERROR", "reason_code": "rtsp://private:secret@host", "ai_error_code": "private exception", "ai_successful_results_current_source": -1})
        self.assertEqual(result["reason_code"], "")
        self.assertEqual(result["ai_error_code"], "")
        self.assertIsNone(result["ai_successful_results_current_source"])

    def test_verification_diagnostics_identify_pad_or_quality_wait_without_private_reason(self):
        scope = public_functions()
        diagnose = scope["_public_verification_diagnostics"]
        blocked = diagnose({"spoof_blocked": True, "liveness": {"status": "BLOCKED", "reason": "private text",
                            "signals": {"pad": {"live_score": .1577, "spoof_score": .8423, "source": "private source"}}}})
        self.assertEqual(blocked["verification_reason_code"], "PAD_BLOCKED")
        self.assertEqual(blocked["pad_spoof_score"], .8423)
        self.assertNotIn("private", str(blocked))
        for marker, code in (("nhỏ", "FACE_TOO_SMALL"), ("nghiêng", "FACE_POSE"), ("dọc", "FACE_PITCH"),
                             ("nét", "FACE_BLUR"), ("ánh sáng", "FACE_LIGHTING"), ("private reason", "FACE_QUALITY_WAIT")):
            self.assertEqual(diagnose({"quality_gate": {"ok": False, "reason": marker}})["verification_reason_code"], code)
        self.assertEqual(diagnose({"liveness": {"status": "CHECKING", "reason": "PAD_INFERENCE_FAILED"}})["verification_reason_code"], "PAD_INFERENCE_FAILED")
        self.assertEqual(diagnose({"liveness": {"status": "PASS"}})["verification_reason_code"], "")

    def test_ai_performance_allowlists_finite_metrics_for_the_selected_service(self):
        scope = public_functions()
        result = scope["_public_ai_performance"]({"ai_metrics": {"pad": {"errors": 4, "stalled": True, "source": "private", "last_queue_wait_ms": 12., "pending": 1},
                 "faceid": {"fps": float("nan"), "last_ms": "private", "errors": -1}},
                 "ai_stage_times": {"detection_ms": 8.5, "source": "private", "tracking_ms": float("inf")}}, {"actual_ai_fps": 3.2, "reason": "private"})
        self.assertEqual(result["actual_ai_fps"], 3.2)
        self.assertEqual(result["pad"]["errors"], 4)
        self.assertTrue(result["pad"]["stalled"])
        self.assertIsNone(result["faceid"]["fps"])
        self.assertIsNone(result["faceid"]["last_ms"])
        self.assertIsNone(result["faceid"]["errors"])
        self.assertNotIn("private", str(result))
        self.assertEqual(result["pad"]["last_queue_wait_ms"], 12.)
        self.assertEqual(result["pad"]["pending"], 1)
        self.assertEqual(result["stage_times"]["detection_ms"], 8.5)
        self.assertIsNone(result["stage_times"]["tracking_ms"])

    def test_detection_diagnostics_distinguish_detector_miss_from_observation_failure(self):
        scope = public_functions()
        diagnose = scope["_public_ai_detection"]
        camera = {"ai_input_mode": "HIKVISION_SUBSTREAM", "ai_seq": 42, "source": "private"}
        performance = {"ai_capture": {"capture_fps": 12., "frame_age_ms": 20., "source": "private"}}
        observer = {"frame_width": 640, "frame_height": 360, "detection": {"detected_faces": 2,
                    "observed_faces": 0, "observation_errors": 2, "no_face_streak": 0, "recovery_attempted": False,
                    "error": "private"}}
        result = diagnose(observer, camera, performance)
        self.assertEqual(result["input_mode"], "HIKVISION_SUBSTREAM")
        self.assertEqual(result["detected_faces"], 2)
        self.assertEqual(result["observed_faces"], 0)
        self.assertEqual(result["observation_errors"], 2)
        self.assertEqual(result["substream_age_ms"], 20.)
        self.assertNotIn("private", str(result))
        observer["detection"] = {"detected_faces": 0, "observed_faces": 0, "observation_errors": 0,
                                 "no_face_streak": 10, "recovery_attempted": True}
        result = diagnose(observer, {"ai_input_mode": "private"}, {})
        self.assertEqual(result["no_face_streak"], 10)
        self.assertTrue(result["recovery_attempted"])
        self.assertEqual(result["input_mode"], "")
        self.assertIsNone(result["substream_age_ms"])

    def test_face_quality_diagnostics_exclude_raw_images_and_identity(self):
        diagnose = public_functions()["_public_verification_diagnostics"]
        result = diagnose({"quality": {"face_px": 48, "score": .52, "sharpness": 16.2,
                           "brightness": float("nan"), "contrast": -1, "embedding": "private", "snapshot": "private"}})
        self.assertEqual(result["face_quality"]["face_px"], 48)
        self.assertEqual(result["face_quality"]["score"], .52)
        self.assertIsNone(result["face_quality"]["brightness"])
        self.assertIsNone(result["face_quality"]["contrast"])
        self.assertNotIn("private", str(result))


class ReadonlyDiagnosisTests(unittest.TestCase):
    def fixture(self, query):
        if "FROM camera_devices" in query:
            return [{"id": 4, "name": "Laptop Camera", "zone_name": "Entry", "enabled": 1, "ai_enabled": 0, "attendance_enabled": 1}]
        if "FROM camera_store_assignments" in query:
            return []
        if "FROM stores" in query:
            return []
        if "FROM role_permissions" in query:
            return [{"role": "ADMIN", "permission": "*"}]
        self.fail("unexpected diagnostic query")

    def test_configuration_disabled_and_unassigned_are_explicit_without_sources(self):
        seen = []
        def query(sql):
            seen.append(sql)
            return self.fixture(sql)
        result = diagnosis.registry_snapshot(query)
        item = result["cameras"][0]
        self.assertFalse(item["eligible_configuration"])
        self.assertEqual(item["blocking_reasons"], ["AI_DISABLED", "STORE_ASSIGNMENT_MISSING_OR_INVALID"])
        self.assertTrue(all(sql.startswith("SELECT ") for sql in seen))
        self.assertTrue(all("source" not in sql and "password" not in sql for sql in seen))

    def test_diagnostic_does_not_import_or_initialize_product(self):
        tree = ast.parse((ROOT / "scripts/diagnose_camera_ai.py").read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node, (ast.Import, ast.ImportFrom)) and "module_app" in ast.unparse(node) for node in ast.walk(tree)))
        self.assertNotIn("init_db(", ast.unparse(tree))

    def test_sqlite_connection_is_readonly_and_query_only(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE camera_devices(id INTEGER)")
        connection.commit()
        connection.execute("PRAGMA query_only=ON")
        calls = []
        class Reader:
            row_factory = None
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql):
                calls.append(sql)
                if sql == "PRAGMA query_only=ON":
                    return connection.execute(sql)
                with self_test.assertRaises(sqlite3.OperationalError):
                    connection.execute("INSERT INTO camera_devices VALUES(1)")
                return SimpleNamespace(fetchall=lambda: [])
        self_test = self
        def connect(filename, **kwargs):
            self.assertTrue(filename.endswith("?mode=ro"))
            self.assertEqual(kwargs, {"uri": True})
            return Reader()
        try:
            with patch.object(diagnosis.sqlite3, "connect", side_effect=connect):
                result = diagnosis.inspect_database(ROOT, {"CAMPUSFACE_DB_MODE": "sqlite"})
            self.assertEqual(result["status"], "READ_ONLY_OK", str(result))
            self.assertEqual(calls[0], "PRAGMA query_only=ON")
        finally:
            connection.close()

    def test_names_redact_sources_and_network_addresses(self):
        result = diagnosis.safe_name("Camera rtsp://user:password@10.1.2.3/101 10.1.2.3")
        self.assertNotIn("password", result)
        self.assertNotIn("10.1.2.3", result)

    def test_postgresql_requires_readonly_session_and_transaction(self):
        calls = []
        class Reader:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql):
                calls.append(sql)
                self_test.assertTrue(sql == "SET TRANSACTION READ ONLY" or sql.startswith("SELECT "))
                return SimpleNamespace(fetchall=lambda: [])
            def rollback(self): calls.append("ROLLBACK")
        self_test = self
        def connect(**kwargs):
            self.assertIn("default_transaction_read_only=on", kwargs["options"])
            self.assertIn("statement_timeout=5000", kwargs["options"])
            self.assertLessEqual(kwargs["connect_timeout"], 5)
            return Reader()
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _: None))
        with patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect), "psycopg.rows": SimpleNamespace(dict_row=object())}), \
             patch.object(diagnosis.importlib.util, "spec_from_file_location", return_value=spec), \
             patch.object(diagnosis.importlib.util, "module_from_spec", return_value=SimpleNamespace(load_secret=lambda *a: "fixture-not-printed")):
            result = diagnosis.inspect_database(ROOT, {"CAMPUSFACE_DB_MODE": "postgres"})
        self.assertEqual(result["status"], "READ_ONLY_OK", str(result))
        self.assertEqual(calls[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(calls[-1], "ROLLBACK")
        self.assertNotIn("fixture-not-printed", str(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)

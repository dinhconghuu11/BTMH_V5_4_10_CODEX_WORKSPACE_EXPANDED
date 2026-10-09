"""Deterministic Phase D tests. In-memory SQLite; no models/customer DB/pytest."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import sqlite3
import sys
import threading
import types
import unittest
import zipfile
from zoneinfo import ZoneInfo

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"
TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=TZ).astimezone(timezone.utc)


class ShiftAttendanceTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        package_name = self.db.__package__
        sys.modules[package_name + ".config"].DATA_ROOT = Path(__file__).resolve().parent
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        self.addCleanup(connection.close)
        lock = threading.RLock()

        @contextmanager
        def memory_connection():
            with lock:
                try:
                    yield self.db._CompatConnection(connection, "sqlite")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

        self.db.connection = memory_connection
        self.db.init_db()
        self.db.execute("CREATE TABLE runtime_settings(setting_key TEXT PRIMARY KEY,setting_value TEXT,updated_at TEXT)")
        for name in ("shift_attendance", "platform_v5", "hr_reporting"):
            spec = importlib.util.spec_from_file_location(package_name + "." + name, SOURCE / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(self, name, module)
        # Clip directory creation is unrelated to assignment/attendance migration;
        # keep this fixture entirely in memory under the sandbox filesystem policy.
        self.platform_v5.CLIP_ROOT = types.SimpleNamespace(mkdir=lambda **kwargs: None)
        self.platform_v5.ensure_platform_v5_schema()
        self.platform_v5._sync_event = lambda *args: None
        self.db.execute("INSERT INTO stores(id,store_code,store_name,timezone_name,created_at,updated_at) VALUES(2,'S2','Store B','Asia/Ho_Chi_Minh','2026','2026')")
        for employee, store in ((1, 1), (2, 2)):
            self.db.execute("INSERT INTO students(id,student_code,full_name,class_name,faculty,consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            (employee, f"E{employee}", f"Employee {employee}", "Team", "Department", "2026", "2026", "2026"))
            self.db.execute("INSERT INTO employee_store_assignments VALUES(?,?,1,'2026')", (employee, store))
        self.camera = {"camera_id": 11, "store_id": 1, "timezone_name": "Asia/Ho_Chi_Minh", "store_name": "Store A",
                       "camera_name": "Entrance", "zone_name": "Door", "attendance_enabled": True, "entrance_config": {"enabled": False}}

    def shift(self, start="08:00", end="17:30", store=1, grace=5, code="DAY"):
        return self.platform_v5.save_shift({"shift_code": code, "shift_name": code, "start_time": start, "end_time": end,
                                           "store_id": store, "late_grace_minutes": grace, "early_leave_grace_minutes": grace,
                                           "workdays": list(range(7)), "active": True}, "owner")

    def assign(self, shift, employee=1, day="2026-10-01"):
        return self.platform_v5.assign_employee_shift(employee, shift["id"], "owner", day)

    def report(self, start="2026-10-08", end="2026-10-08", now="2026-10-08T18:00:00", **kwargs):
        return self.shift_attendance.build_shift_attendance_report(start, end, now=at(now), **kwargs)

    def inbound(self, stamp="2026-10-08T08:00:00", employee=1, context=None, **kwargs):
        return self.shift_attendance.register_attendance_in(employee, context or self.camera, at(stamp), **kwargs)

    def outbound(self, stamp="2026-10-08T17:30:00", employee=1, context=None, **kwargs):
        return self.shift_attendance.register_attendance_out(employee, context or self.camera, at(stamp), **kwargs)

    def test_migration_idempotence_does_not_assign_seed_and_seeds_only_known_interval(self):
        self.shift_attendance.ensure_shift_attendance_schema()
        self.shift_attendance.ensure_shift_attendance_schema()
        self.assertEqual(self.db.fetchall("SELECT * FROM employee_shift_assignment_history"), [])
        self.assertEqual(self.report()["rows"], [])
        shift = self.shift()
        self.db.execute("INSERT INTO employee_shift_assignments VALUES(?,?,?,?,?,?,?)", (1, shift["id"], "2026-10-05", "2026-10-10", "owner", "2026", "2026"))
        self.shift_attendance.ensure_shift_attendance_schema()
        self.shift_attendance.ensure_shift_attendance_schema()
        history = self.db.fetchall("SELECT * FROM employee_shift_assignment_history")
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["effective_from"], history[0]["effective_to"]), ("2026-10-05", "2026-10-10"))

    def test_tomorrows_assignment_and_shift_edits_preserve_yesterday(self):
        day, night = self.shift(), self.shift("22:00", "06:00", code="NIGHT")
        self.assign(day)
        self.inbound()
        self.assign(night, day="2026-10-09")
        self.db.execute("UPDATE work_shifts SET start_time='09:00' WHERE id=?", (day["id"],))
        old = self.report()["rows"][0]
        self.assertEqual(old["shift_id"], day["id"])
        self.assertEqual(old["expected_start_at"], at("2026-10-08T08:00:00").isoformat())
        self.assertEqual(self.platform_v5.employee_shift(1, "2026-10-09")["id"], night["id"])
        self.assertIsNone(self.platform_v5.employee_shift(1, "2026-09-30"))

    def test_absence_only_after_shift_end_and_report_is_read_only(self):
        self.assign(self.shift())
        self.assertEqual(self.report(now="2026-10-08T07:00:00")["rows"][0]["status"], "NOT_YET_DUE")
        self.assertEqual(self.report(now="2026-10-08T17:30:00")["totals"]["absent_days"], 0)
        self.assertEqual(self.report(now="2026-10-08T17:30:01")["totals"]["absent_days"], 1)
        self.assertEqual(self.db.fetchall("SELECT * FROM shift_attendance_records"), [])

    def test_first_valid_in_configured_grace_latest_seen_is_not_checkout(self):
        self.assign(self.shift(grace=0))
        self.inbound("2026-10-08T08:00:01")
        self.inbound("2026-10-08T09:00:00", context={**self.camera, "camera_id": 12})
        row = self.report()["rows"][0]
        self.assertTrue(row["late"])
        self.assertEqual(row["checkin_at"], at("2026-10-08T08:00:01").isoformat())
        self.assertIsNone(row["checkout_at"])
        self.assertEqual(row["status"], "MISSING_OUT")
        self.assertIsNone(row["early_leave"])
        self.assertEqual(len(self.db.fetchall("SELECT * FROM shift_attendance_records")), 1)

    def test_overnight_business_date_and_late_out_after_end(self):
        self.assign(self.shift("22:00", "06:00", grace=7))
        first = self.inbound("2026-10-08T22:07:00")
        self.assertFalse(first["late"])
        self.inbound("2026-10-09T02:00:00")
        result = self.outbound("2026-10-09T06:30:00")
        self.assertEqual(result["business_date"], "2026-10-08")
        row = self.report(now="2026-10-09T07:00:00")["rows"][0]
        self.assertEqual(row["expected_end_at"], at("2026-10-09T06:00:00").isoformat())
        self.assertEqual(row["checkout_at"], at("2026-10-09T06:30:00").isoformat())
        self.assertFalse(row["early_leave"])

    def test_real_out_repeat_out_and_reentry_state(self):
        self.assign(self.shift())
        self.assertFalse(self.outbound()["accepted"])
        self.inbound()
        self.outbound("2026-10-08T12:00:00", event_id=1)
        self.assertFalse(self.outbound("2026-10-08T16:00:00", event_id=2)["accepted"])
        self.assertEqual(self.report()["rows"][0]["checkout_at"], at("2026-10-08T12:00:00").isoformat())
        self.inbound("2026-10-08T13:00:00")
        reopened = self.report()["rows"][0]
        self.assertIsNone(reopened["checkout_at"])
        self.assertEqual(reopened["status"], "MISSING_OUT")
        self.outbound()
        self.assertEqual(self.report()["rows"][0]["checkin_at"], at("2026-10-08T08:00:00").isoformat())

    def test_out_replay_or_visibility_cannot_reopen_or_manufacture_out(self):
        self.assign(self.shift())
        self.inbound()
        self.outbound()
        self.inbound(event_id=1)
        self.assertIsNotNone(self.report()["rows"][0]["checkout_at"])
        self.assertFalse(self.outbound(source_type="TRACK_LOST")["accepted"])
        self.assertIsNone(self.shift_attendance.touch_attendance_seen(1, self.camera, at("2026-10-08T18:00:00")))

    def test_two_camera_concurrent_dedup_and_earlier_event(self):
        self.assign(self.shift())
        failures = []
        barrier = threading.Barrier(2)
        def admit(camera, stamp):
            try:
                barrier.wait()
                self.inbound(stamp, context={**self.camera, "camera_id": camera})
            except Exception as error:
                failures.append(error)
        threads = [threading.Thread(target=admit, args=(11, "2026-10-08T08:04:00")),
                   threading.Thread(target=admit, args=(12, "2026-10-08T08:00:00"))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5)
        self.assertEqual(failures, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        rows = self.db.fetchall("SELECT * FROM shift_attendance_records")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["first_in_at"], at("2026-10-08T08:00:00").isoformat())

    def test_global_shift_resolves_unique_primary_store_and_ambiguous_stays_unknown(self):
        global_shift = self.shift(store=None)
        self.assertEqual(self.assign(global_shift)["store_id"], 1)
        self.db.execute("INSERT INTO employee_store_assignments VALUES(1,2,1,'2026')")
        self.assign(global_shift, day="2026-10-09")
        self.assertIsNone(self.shift_attendance.assignment_for_date(1, "2026-10-09")["store_id"])
        self.assertFalse(self.inbound("2026-10-09T08:00:00")["accepted"])
        self.assertFalse(self.inbound(context={**self.camera, "store_id": None})["accepted"])

    def test_scope_is_applied_in_sql_to_history_records_and_corrections(self):
        self.assign(self.shift())
        self.assign(self.shift(store=2, code="OTHER"), employee=2)
        self.inbound()
        self.inbound(employee=2, context={**self.camera, "store_id": 2})
        statements = []
        original = self.db.fetchall
        def capture(sql, args=()):
            statements.append((sql, args)); return original(sql, args)
        self.db.fetchall = capture
        result = self.report(allowed_store_ids={1})
        self.assertEqual({row["store_id"] for row in result["rows"]}, {1})
        for sql, args in statements:
            if "shift_attendance_records" in sql or "attendance_corrections_v5" in sql:
                self.assertIn("store_id IN", sql)
                self.assertEqual(args[-1], 1)
        self.assertEqual(self.report(allowed_store_ids=set())["rows"], [])
        with self.assertRaises(PermissionError): self.report(allowed_store_ids={1}, store_id=2)

    def test_approved_corrections_preserve_raw_evidence_and_export(self):
        self.assign(self.shift())
        self.inbound("2026-10-08T08:10:00")
        self.platform_v5.create_attendance_correction({"student_id": 1, "work_date": "2026-10-08", "reason": "Approved correction",
                                                     "effective_checkin_at": at("2026-10-08T08:00:00").isoformat()}, "owner")
        row = self.report()["rows"][0]
        self.assertFalse(row["late"])
        self.assertEqual(row["raw_checkin_at"], at("2026-10-08T08:10:00").isoformat())
        self.assertTrue(row["attendance_adjusted"])
        self.assertEqual(row["correction"]["approved_by"], "owner")
        self.assertIsNone(row["checkout_at"])
        hr = self.hr_reporting.build_hr_report("day", "2026-10-08", allowed_store_ids={1}, now=at("2026-10-08T18:00:00"))
        self.assertFalse(hr["observation_available"])
        self.assertEqual(hr["totals"]["late_cases"], 0)
        self.assertIsNone(hr["rows"][0]["compliance_percent"])
        with zipfile.ZipFile(BytesIO(self.hr_reporting.report_xlsx_bytes(hr))) as output:
            self.assertIn("xl/worksheets/sheet1.xml", output.namelist())
        self.assertIn("Chưa ghi nhận ra", self.hr_reporting.report_print_html(hr))

    def test_cached_tracks_validity_gate_and_throttle(self):
        self.assign(self.shift())
        valid = {"recognized": True, "student_id": 1, "liveness": {"status": "PASS"}, "observation_age_ms": 0}
        for change in ({"stale": True}, {"tracking_grace": True}, {"spoof_blocked": True}, {"observation_age_ms": 50}, {"liveness": {"status": "CHECKING"}}):
            self.assertEqual(self.shift_attendance.consume_camera_result(self.camera, {"tracks": [{**valid, **change}]}, at("2026-10-08T08:00:00")), [])
        self.shift_attendance.consume_camera_result(self.camera, {"tracks": [valid]}, at("2026-10-08T08:00:00"))
        self.assertEqual(self.shift_attendance.consume_camera_result(self.camera, {"tracks": [valid]}, at("2026-10-08T08:00:00.2")), [])
        self.assertIsNotNone(self.report()["rows"][0]["checkin_at"])
        self.assertIsNone(self.report()["rows"][0]["checkout_at"])
        gated = {**self.camera, "entrance_config": {"enabled": True}}
        self.shift_attendance.consume_camera_result(gated, {"tracks": [valid]}, at("2026-10-09T08:00:00"))
        self.assertIsNone(self.report("2026-10-09", "2026-10-09")["rows"][0]["checkin_at"])

    def test_cached_identity_admits_new_business_date_under_one_second(self):
        self.assign(self.shift("00:00", "23:59", code="ALLDAY"))
        track = {"recognized": True, "student_id": 1, "liveness": {"status": "PASS"}}
        self.shift_attendance.consume_camera_result(self.camera, {"tracks": [track]}, at("2026-10-08T23:59:59.7"))
        self.shift_attendance.consume_camera_result(self.camera, {"tracks": [track]}, at("2026-10-09T00:00:00.2"))
        self.assertEqual(len(self.db.fetchall("SELECT * FROM shift_attendance_records")), 2)

    def test_manual_checkout_is_explicit_adjustment_and_bad_dates_rejected(self):
        self.assign(self.shift())
        self.inbound()
        self.platform_v5.create_attendance_correction({"student_id": 1, "work_date": "2026-10-08", "reason": "Verified manual exit",
                                                     "effective_checkout_at": at("2026-10-08T17:30:00").isoformat()}, "owner")
        row = self.report()["rows"][0]
        self.assertEqual(row["checkout_source"], "APPROVED_CORRECTION")
        self.assertIsNone(row["raw_checkout_at"])
        with self.assertRaises(ValueError):
            self.platform_v5.create_attendance_correction({"student_id": 1, "work_date": "2026-99-99", "reason": "Bad date"}, "owner")
        with self.assertRaises(ValueError): self.assign(self.shift(code="BAD"), day="2026-99-99")

    def test_hr_unassigned_and_absence_never_uses_global_seed_policy(self):
        report = self.hr_reporting.build_hr_report("day", "2026-10-08", now=at("2026-10-08T18:00:00"))
        self.assertEqual(report["totals"]["absent_days"], 0)
        self.assertTrue(all(row["late_days"] is None and row["status"] == "Chưa có ca được gán" for row in report["rows"]))
        self.assertEqual(report["totals"]["unassigned_employees"], 2)

    def test_cache_has_hard_capacity_even_all_entries_are_recent(self):
        self.assign(self.shift())
        now = at("2026-10-08T08:00:00")
        for employee in range(100, 4196):
            self.shift_attendance._SEEN[(employee, 1)] = (now, None, now.astimezone(TZ).date())
        track = {"recognized": True, "student_id": 1, "liveness": {"status": "PASS"}}
        self.shift_attendance.consume_camera_result(self.camera, {"tracks": [track]}, now)
        self.assertEqual(len(self.shift_attendance._SEEN), 4096)
        self.assertIn((1, 1), self.shift_attendance._SEEN)

    def test_invalid_legacy_correction_and_replayed_event_do_not_fake_latest_seen(self):
        self.assign(self.shift())
        self.db.execute("INSERT INTO attendance_corrections_v5(student_id,work_date,reason,approved_by,effective_checkin_at,created_at,updated_at) "
                        "VALUES(1,'2026-10-08','Legacy invalid','owner','invalid','2026','2026')")
        event = {"status": "RECOGNIZED", "anti_spoof_passed": True, "student_id": 1, "store_id": 1, "camera_id": 11,
                 "event_at": at("2026-10-08T08:00:00").isoformat(), "id": 20}
        self.shift_attendance.consume_camera_result(self.camera, {"events": [event]}, at("2026-10-08T18:00:00"))
        row = self.report()["rows"][0]
        self.assertEqual(row["last_seen_at"], event["event_at"])
        self.assertEqual(row["checkin_at"], event["event_at"])
        self.assertIsNone(row["checkout_at"])


    def test_appearance_verification_admits_in_without_backdating_to_analyzing(self):
        self.assign(self.shift(grace=0))
        event = {"id": 77, "student_id": 1, "status": "RECOGNIZED", "anti_spoof_passed": True,
                 **self.camera, "event_at": at("2026-10-08T07:59:00").isoformat(),
                 "recognized_at": at("2026-10-08T08:01:00").isoformat()}
        self.shift_attendance.consume_camera_result(self.camera, {"events": [event], "tracks": []}, at("2026-10-08T08:01:00"))
        row = self.report()["rows"][0]
        self.assertEqual(row["first_in_at"], event["recognized_at"])
        self.assertTrue(row["late"])
        # Replaying the same daily appearance never shifts last_seen to consumption time.
        self.shift_attendance.consume_camera_result(self.camera, {"events": [event], "tracks": []}, at("2026-10-08T11:00:00"))
        self.assertEqual(self.report()["rows"][0]["last_seen_at"], event["recognized_at"])


if __name__ == "__main__":
    unittest.main()

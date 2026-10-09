"""Real in-memory SQL and crossing contracts; no models, cameras or pytest."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import unittest

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


class EntranceVisitTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
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
        self.module = self.load("entrance_visits")
        self.module.ensure_entrance_visits_schema()
        self.hooks = []

        def hook(direction):
            def record(employee, context, occurred_at, **kwargs):
                self.hooks.append({"direction": direction, "employee": employee, "context": context,
                                   "occurred_at": occurred_at, **kwargs})
                return {"accepted": True}
            return record

        self.consumer = self.module.EntranceVisits(in_hook=hook("IN"), out_hook=hook("OUT"))
        self.camera = {"camera_id": 11, "store_id": 1, "camera_name": "Entrance A", "store_name": "Store A",
                       "zone_name": "Front", "timezone_name": "Asia/Ho_Chi_Minh", "attendance_enabled": True,
                       "visitor_counting_enabled": True, "entrance_config": {"enabled": True, "name": "Front door",
                       "x1": .2, "y1": .5, "x2": .8, "y2": .5, "deadband": .02, "cooldown_sec": .1,
                       "reacquire_sec": 2., "max_distance": .12, "anchor": "face_center"}}
        self.start = datetime(2026, 10, 8, 3, tzinfo=timezone.utc)

    def load(self, name):
        spec = importlib.util.spec_from_file_location(self.db.__package__ + "." + name, SOURCE / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def track(self, y, *, x=.5, tid=1, kind="VISITOR", appearance="appearance-A", **changes):
        track = {"track_id": tid, "bbox": [(x - .025) * 1000, (y - .025) * 1000, 50, 50],
                 "status": "UNREGISTERED", "unknown": True, "recognized": False, "liveness": {"status": "PASS"},
                 "stale": False, "observation_age_ms": 0, "appearance_id": appearance}
        if kind == "EMPLOYEE":
            track.update(status="RECOGNIZED", unknown=False, recognized=True, student_id=7)
        elif kind == "PENDING":
            track.update(status="ANALYZING", unknown=False)
        elif kind == "SPOOF":
            track.update(status="SPOOF_BLOCKED", spoof_blocked=True)
        track.update(changes)
        return track

    def consume(self, tracks, seconds, *, context=None, **changes):
        result = {"ok": True, "camera_id": 11, "source_epoch": 1, "worker_instance_id": "worker-A",
                  "frame_width": 1000, "frame_height": 1000, "tracks": tracks, "events": []}
        result.update(changes)
        return self.consumer.consume(context or self.camera, result, self.start + timedelta(seconds=seconds))

    def rows(self, status=None):
        return self.db.fetchall("SELECT * FROM entrance_visits " + ("WHERE visit_status=? " if status else "") +
                               "ORDER BY entered_at,visit_id", (status,) if status else ())

    def inbound(self, tid=1, x=.5, kind="VISITOR", start=0, **kwargs):
        self.consume([self.track(.4, tid=tid, x=x, kind=kind, **kwargs)], start)
        return self.consume([self.track(.6, tid=tid, x=x, kind=kind, **kwargs)], start + 1)

    def test_migration_idempotent_and_does_not_backfill_observation_sessions(self):
        self.db.execute("CREATE TABLE old_observation_sessions(id INTEGER PRIMARY KEY)")
        self.db.execute("INSERT INTO old_observation_sessions VALUES(1)")
        self.module.ensure_entrance_visits_schema()
        self.module.ensure_entrance_visits_schema()
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM old_observation_sessions")["n"], 1)

    def test_in_out_next_in_is_another_visit_even_same_appearance(self):
        first = self.inbound()["actions"][0]
        self.assertTrue(first["accepted"])
        self.consume([self.track(.4)], 2)
        self.consume([self.track(.6)], 3)
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]["visit_id"], rows[1]["visit_id"])
        self.assertEqual(rows[0]["appearance_id"], rows[1]["appearance_id"])
        self.assertEqual(rows[0]["exited_at"], (self.start + timedelta(seconds=2)).isoformat())
        self.assertIsNone(rows[1]["exited_at"])
        self.assertEqual(rows[0]["anchor_basis"], "FACE")

    def test_initial_inside_and_unpaired_out_never_invent_visit(self):
        self.consume([self.track(.6)], 0)
        result = self.consume([self.track(.4)], 1)
        self.assertEqual(self.rows(), [])
        self.assertEqual(result["actions"][0]["reason"], "OUT_WITHOUT_VISIT")

    def test_repeat_in_while_open_and_cooldown_jitter_do_not_increment(self):
        self.inbound()
        self.consume([self.track(.4)], 1.05)  # cooldown suppresses jitter OUT
        result = self.consume([self.track(.6)], 1.3)
        self.assertEqual(len(self.rows()), 1)
        self.assertIsNone(self.rows()[0]["exited_at"])
        self.assertEqual(result["actions"][0]["reason"], "VISIT_ALREADY_OPEN")

    def test_crossing_infinite_extension_is_not_crossing_finite_segment(self):
        self.inbound(x=.95)
        self.assertEqual(self.rows(), [])
        self.consumer.reset_camera(11)
        self.inbound(x=.8, start=3)
        self.assertEqual(len(self.rows()), 1)  # endpoint is part of segment

    def test_inside_direction_and_reversed_line(self):
        self.camera["entrance_config"]["inside_side"] = "negative"
        self.consume([self.track(.6)], 0)
        self.consume([self.track(.4)], 1)
        self.assertEqual(len(self.rows()), 1)
        self.consumer.reset_camera(11)
        self.camera["entrance_config"].update(x1=.8, x2=.2, inside_side="positive")
        self.consume([self.track(.6, tid=2)], 3)
        self.consume([self.track(.4, tid=2)], 4)
        self.assertEqual(len(self.rows()), 2)

    def test_roi_breaks_baseline_and_deadband_needs_stable_sides(self):
        self.camera["entrance_config"]["roi"] = {"x1": .2, "y1": .2, "x2": .8, "y2": .8}
        self.consume([self.track(.4, x=.9)], 0)
        self.consume([self.track(.6)], 1)
        self.assertEqual(self.rows(), [])
        self.consume([self.track(.51)], 1.3)
        self.consume([self.track(.49)], 1.6)
        self.assertEqual(self.rows(), [])
        self.consume([self.track(.4)], 2)
        self.consume([self.track(.6)], 3)
        self.assertEqual(len(self.rows()), 1)

    def test_pending_crossing_waits_for_employee_pad_pass_and_uses_crossing_time(self):
        self.inbound(kind="PENDING")
        result = self.consume([self.track(.6, kind="EMPLOYEE", liveness={"status": "VERIFYING"})], 1.5)
        self.assertEqual(result["pending"], 1)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.hooks, [])
        self.consume([self.track(.6, kind="EMPLOYEE")], 2)
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.hooks), 1)
        self.assertEqual(self.hooks[0]["employee"], 7)
        self.assertEqual(self.hooks[0]["source_type"], "GATE_IN")
        self.assertEqual(self.hooks[0]["occurred_at"], self.start + timedelta(seconds=1))
        self.assertEqual(self.hooks[0]["observed_at"], self.start + timedelta(seconds=2))

    def test_candidate_unknown_and_pending_in_out_do_not_count_employee_early(self):
        self.inbound(candidate_student_id=7)
        self.assertEqual(self.rows(), [])
        self.consume([self.track(.4, kind="PENDING")], 2)
        self.consume([self.track(.4, kind="EMPLOYEE")], 3)
        self.assertEqual(self.rows(), [])
        self.assertEqual([item["direction"] for item in self.hooks], ["IN", "OUT"])

    def test_confirmed_unknown_releases_pending_crossings_and_spoof_rejects(self):
        self.inbound(kind="PENDING")
        self.consume([self.track(.4, kind="PENDING")], 2)
        self.consume([self.track(.4)], 3)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["entered_at"], (self.start + timedelta(seconds=1)).isoformat())
        self.assertEqual(self.rows()[0]["exited_at"], (self.start + timedelta(seconds=2)).isoformat())
        self.consumer.reset_camera(11)
        self.inbound(kind="PENDING", start=5)
        self.consume([self.track(.6, kind="SPOOF")], 7)
        self.consume([self.track(.4)], 8)
        self.consume([self.track(.6)], 9)
        self.assertEqual(len(self.rows()), 1)

    def test_employee_only_camera_still_gets_in_out_and_no_visitors(self):
        self.camera["visitor_counting_enabled"] = False
        self.inbound(kind="EMPLOYEE")
        self.consume([self.track(.4, kind="EMPLOYEE")], 2)
        self.assertEqual([item["direction"] for item in self.hooks], ["IN", "OUT"])
        self.assertEqual(self.rows(), [])
        self.consumer.reset_camera(11)
        self.inbound(start=4)
        self.assertEqual(self.rows(), [])

    def test_disabled_ordinary_camera_and_unassigned_context_are_fail_closed(self):
        original = json.loads(json.dumps(self.camera))
        for changed in ({"entrance_config": {"enabled": False}}, {"store_id": None}, {"zone_name": ""},
                        {"attendance_enabled": False, "visitor_counting_enabled": False},
                        {"entrance_config": {"enabled": True, "x1": float("nan")}}):
            with self.subTest(changed=changed):
                self.camera = json.loads(json.dumps(original))
                self.camera.update(changed)
                self.inbound()
                self.assertEqual(self.rows(), [])
                self.assertEqual(self.hooks, [])

    def test_visitor_only_camera_counts_visitors_without_attendance_hooks(self):
        self.camera["attendance_enabled"] = False
        self.inbound(kind="EMPLOYEE")
        self.consume([self.track(.4, kind="EMPLOYEE")], 2)
        self.assertEqual(self.hooks, [])
        self.assertEqual(self.rows(), [])
        self.consumer.reset_camera(11)
        self.inbound(start=4)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.hooks, [])

    def test_unknown_promoted_to_verified_is_reclassified_without_changing_snapshots(self):
        self.inbound()
        self.consume([self.track(.4)], 2)
        original = self.rows()[0]
        self.consume([self.track(.4, kind="EMPLOYEE")], 3)
        row = self.rows()[0]
        self.assertEqual(row["visit_status"], "EMPLOYEE")
        self.assertEqual(row["employee_id"], 7)
        self.assertEqual(self.rows("VISITOR"), [])
        for key in ("entered_at", "exited_at", "camera_id", "store_id", "zone_name", "camera_name", "store_name", "appearance_id"):
            self.assertEqual(row[key], original[key])
        self.assertEqual([item["direction"] for item in self.hooks], ["IN", "OUT"])
        self.assertEqual(self.hooks[0]["occurred_at"], self.start + timedelta(seconds=1))

    def test_spoof_invalidates_visitor_evidence_without_synthetic_out(self):
        self.inbound()
        self.consume([self.track(.6, kind="SPOOF")], 2)
        self.assertEqual(self.rows("VISITOR"), [])
        self.assertEqual(self.rows()[0]["visit_status"], "SPOOF")
        self.assertIsNone(self.rows()[0]["exited_at"])
        self.assertEqual(self.hooks, [])

    def test_fresh_verified_pad_pass_recovers_after_spoof_only_for_new_crossing(self):
        self.inbound()
        self.consume([self.track(.6, kind="SPOOF")], 2)
        original = self.rows()[0]
        self.consume([self.track(.4, candidate_student_id=7)], 3)
        self.consume([self.track(.6, kind="EMPLOYEE", liveness={"status": "CHECKING"})], 4)
        self.assertEqual(self.hooks, [])
        # The first fresh accepted result is across the line from the blocked
        # position. Recovery must establish a baseline, not replay that old OUT.
        self.consume([self.track(.4, kind="EMPLOYEE")], 5)
        self.assertEqual(self.hooks, [])
        self.consume([self.track(.6, kind="EMPLOYEE")], 6)
        self.consume([self.track(.4, kind="EMPLOYEE")], 7)
        self.assertEqual([item["direction"] for item in self.hooks], ["IN", "OUT"])
        self.assertEqual(self.hooks[0]["occurred_at"], self.start + timedelta(seconds=6))
        self.assertEqual(self.hooks[1]["occurred_at"], self.start + timedelta(seconds=7))
        row = self.rows()[0]
        self.assertEqual(row["visit_status"], "SPOOF")
        self.assertIsNone(row["exited_at"])
        self.assertEqual(row["entered_at"], original["entered_at"])
        self.assertEqual(self.rows("VISITOR"), [])

    def test_attendance_failure_during_promotion_keeps_crossing_for_retry(self):
        self.inbound()
        for second in range(2, 40):
            self.consume([self.track(.6)], second)
        good_hook = self.consumer._in_hook
        attempts = []

        def fail_once(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("synthetic temporary attendance failure")
            return good_hook(*args, **kwargs)

        self.consumer._in_hook = fail_once
        with self.assertRaisesRegex(RuntimeError, "temporary attendance failure"):
            self.consume([self.track(.6, kind="EMPLOYEE")], 40)
        self.assertEqual(self.rows()[0]["visit_status"], "EMPLOYEE")
        self.consume([self.track(.6, kind="EMPLOYEE")], 40.5)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(self.hooks), 1)
        self.assertEqual(self.hooks[0]["occurred_at"], self.start + timedelta(seconds=1))

    def test_failed_visit_commit_rolls_back_and_retries_without_phantom_owner(self):
        self.consume([self.track(.4)], 0)
        original_connection = self.db.connection

        @contextmanager
        def failed_commit():
            with original_connection() as conn:
                yield conn
                raise RuntimeError("synthetic commit failure")

        self.db.connection = failed_commit
        with self.assertRaisesRegex(RuntimeError, "commit failure"):
            self.consume([self.track(.6)], 1)
        self.db.connection = original_connection
        self.assertEqual(self.rows(), [])
        self.assertIsNone(self.consumer._cameras[11].tracks[1].open_visit_id)
        self.consume([self.track(.6)], 1.5)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["entered_at"], (self.start + timedelta(seconds=1)).isoformat())

    def test_loss_stale_and_reset_never_close_open_visit(self):
        self.inbound()
        self.consume([self.track(.4, stale=True, observation_age_ms=400)], 2)
        self.consume([], 4)
        self.consumer.reset_camera(11)
        self.assertIsNone(self.rows()[0]["exited_at"])
        self.assertEqual(self.hooks, [])

    def test_unique_short_same_side_reacquire_keeps_visit_and_out(self):
        self.inbound()
        self.consume([], 1.5)
        self.consume([self.track(.61, tid=2, appearance="appearance-B")], 2)
        self.consume([self.track(.4, tid=2, appearance="appearance-B")], 3)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["exited_at"])
        self.assertNotEqual(rows[0]["entry_track_ref"], rows[0]["exit_track_ref"])
        self.assertEqual(rows[0]["appearance_id"], "appearance-A")

    def test_two_lost_candidates_are_ambiguous_and_do_not_close_either_visit(self):
        self.consume([self.track(.4, x=.45, tid=1), self.track(.4, x=.55, tid=2)], 0)
        self.consume([self.track(.6, x=.45, tid=1), self.track(.6, x=.55, tid=2)], 1)
        self.consume([self.track(.6, tid=3)], 2)
        self.consume([self.track(.4, tid=3)], 3)
        self.assertEqual(len(self.rows()), 2)
        self.assertTrue(all(row["exited_at"] is None for row in self.rows()))

    def test_one_lost_two_new_candidates_are_ambiguous(self):
        self.inbound()
        self.consume([self.track(.6, x=.49, tid=2), self.track(.6, x=.51, tid=3)], 2)
        self.consume([self.track(.4, x=.49, tid=2), self.track(.4, x=.51, tid=3)], 3)
        self.assertEqual(len(self.rows()), 1)
        self.assertIsNone(self.rows()[0]["exited_at"])

    def test_reacquire_far_other_side_and_expired_gap_are_rejected(self):
        self.inbound()
        self.consume([self.track(.6, x=.8, tid=2)], 2)
        self.consume([self.track(.4, x=.8, tid=2)], 3)
        self.assertIsNone(self.rows()[0]["exited_at"])
        self.consumer.reset_camera(11)
        self.inbound(tid=3, start=5)
        self.consume([self.track(.4, tid=4)], 7)  # new alias already opposite side
        self.assertTrue(all(row["exited_at"] is None for row in self.rows()))
        self.consume([self.track(.6, tid=3)], 10)  # same integer after long gap gets new baseline
        self.consume([self.track(.4, tid=3)], 11)
        self.assertTrue(all(row["exited_at"] is None for row in self.rows()))

    def test_context_source_epoch_reset_freezes_persisted_source(self):
        self.inbound()
        self.camera.update(store_id=2, store_name="Store B", camera_name="Renamed", zone_name="Rear")
        self.consume([self.track(.4)], 2, source_epoch=2)
        row = self.rows()[0]
        self.assertEqual((row["store_id"], row["store_name"], row["camera_name"], row["zone_name"]),
                         (1, "Store A", "Entrance A", "Front"))
        self.assertIsNone(row["exited_at"])

    def test_midnight_appearance_rollover_is_not_out(self):
        self.start = datetime(2026, 10, 8, 16, 59, 58, tzinfo=timezone.utc)
        self.inbound()
        self.consume([self.track(.6, appearance="next-day-sequence-1")], 2)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["business_date"], "2026-10-08")
        self.assertIsNone(self.rows()[0]["exited_at"])
        self.consume([self.track(.4, appearance="next-day-sequence-1")], 3)
        self.assertIsNotNone(self.rows()[0]["exited_at"])

    def test_invalid_geometry_stale_result_and_replay_are_fail_closed(self):
        for bad in ([float("nan"), 300, 50, 50], [400, 300, -50, 50], [-1, 300, 50, 50], [990, 300, 50, 50]):
            self.consume([self.track(.4, bbox=bad)], 0)
        self.assertEqual(self.rows(), [])
        self.inbound(start=1)
        self.consume([self.track(.4)], 2)  # replay at already processed timestamp
        self.consume([self.track(.4)], 3, camera_id=12)
        self.consume([self.track(.4)], 4, discarded_generation=True)
        self.assertIsNone(self.rows()[0]["exited_at"])
        with self.assertRaisesRegex(ValueError, "TIMEZONE_REQUIRED"):
            self.consumer.consume(self.camera, {}, datetime(2026, 10, 8))

    def test_concurrent_replayed_crossing_has_one_sql_visit(self):
        self.consume([self.track(.4)], 0)
        barrier = threading.Barrier(2)
        errors = []
        def cross():
            try:
                barrier.wait()
                self.consume([self.track(.6)], 1)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=cross) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.rows()), 1)

    def test_pending_and_track_state_have_finite_limits(self):
        self.module.MAX_TRACKS_PER_CAMERA = 4
        self.module.MAX_PENDING_CROSSINGS = 2
        self.module.PENDING_CLASSIFICATION_SEC = 2
        self.consume([self.track(.4, tid=tid, kind="PENDING") for tid in range(1, 10)], 0)
        result = self.consume([self.track(.6, tid=tid, kind="PENDING") for tid in range(1, 10)], 1)
        self.assertLessEqual(result["tracked"], 4)
        self.consume([self.track(.4, kind="PENDING")], 2)
        self.consume([self.track(.6, kind="PENDING")], 3)
        self.consume([self.track(.6)], 4)
        self.assertEqual(self.rows(), [])  # expired IN is not invented again
        self.consume([], 40)
        self.assertEqual(self.consumer._cameras[11].tracks, {})

    def test_real_shift_hooks_receive_employee_gate_in_out_without_visitor_flag(self):
        attendance = self.load("shift_attendance")
        with self.db.connection() as conn:
            conn.executescript("""
            CREATE TABLE employee_shift_assignments(student_id INTEGER,shift_id INTEGER,effective_from TEXT,
                effective_to TEXT,assigned_by TEXT,created_at TEXT,updated_at TEXT);
            CREATE TABLE work_shifts(id INTEGER,store_id INTEGER,shift_code TEXT,shift_name TEXT,start_time TEXT,
                end_time TEXT,late_grace_minutes INTEGER,early_leave_grace_minutes INTEGER,workdays_json TEXT);
            """)
        attendance.ensure_shift_attendance_schema()
        schedule = {"timezone_name": "Asia/Ho_Chi_Minh", "start_time": "08:00", "end_time": "17:30",
                    "late_grace_minutes": 5, "early_leave_grace_minutes": 5,
                    "workdays_json": json.dumps(list(range(7))), "shift_name": "Day", "shift_code": "DAY"}
        self.db.execute("INSERT INTO employee_shift_assignment_history VALUES(?,?,?,?,?,?,?,?,?)",
                        (7, "2026-10-01", None, 1, 1, json.dumps(schedule), "owner", "2026", "2026"))
        self.consumer = self.module.EntranceVisits()
        self.camera["visitor_counting_enabled"] = False
        self.inbound(kind="EMPLOYEE")
        self.consume([self.track(.4, kind="EMPLOYEE")], 2)
        row = self.db.fetchone("SELECT * FROM shift_attendance_records")
        self.assertEqual(row["first_in_at"], (self.start + timedelta(seconds=1)).isoformat())
        self.assertEqual(row["last_out_at"], (self.start + timedelta(seconds=2)).isoformat())
        self.assertEqual(row["camera_id"], 11)
        self.assertEqual(self.rows(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

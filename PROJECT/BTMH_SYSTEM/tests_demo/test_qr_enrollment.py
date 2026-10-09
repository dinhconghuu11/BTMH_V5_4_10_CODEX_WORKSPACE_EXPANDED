"""Isolated real SQLite/clock lifecycle tests; no installed key/model/customer DB.

The authenticated opaque test codec substitutes the existing crypto boundary,
not a production algorithm. Publication duplicate logic is a deterministic test
adapter reading active rows through the actual supplied SQL transaction.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import threading
import types
import unittest

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"


class QREnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        self.raw = sqlite3.connect(":memory:", check_same_thread=False)
        self.raw.row_factory = sqlite3.Row
        self.raw.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.raw.close)
        lock = threading.RLock()

        @contextmanager
        def connection():
            with lock:
                try:
                    yield self.db._CompatConnection(self.raw, "sqlite")
                    self.raw.commit()
                except BaseException:
                    self.raw.rollback()
                    raise

        self.db.connection = connection
        self.db.init_db()
        self.now = datetime(2026, 10, 8, 2, 0, tzinfo=timezone.utc)
        self.owner = {"id": 1, "role": "SUPER_ADMIN"}
        self.admin = {"id": 2, "role": "ADMIN"}
        with connection() as conn:
            conn.executescript("""
                CREATE TABLE system_users(id INTEGER PRIMARY KEY,role TEXT,active INTEGER);
                INSERT INTO system_users VALUES(1,'SUPER_ADMIN',1),(2,'ADMIN',1),(3,'HR',1),(4,'MANAGER',1),(5,'ADMIN',0);
                CREATE TABLE stores(id INTEGER PRIMARY KEY,store_name TEXT,status TEXT);
                INSERT INTO stores VALUES(1,'Store A','ACTIVE'),(2,'Store B','ACTIVE'),(3,'Closed','INACTIVE');
                CREATE TABLE employee_store_assignments(student_id INTEGER,store_id INTEGER,is_primary INTEGER,created_at TEXT,PRIMARY KEY(student_id,store_id));
                CREATE TABLE face_enrollment_validations(student_id INTEGER PRIMARY KEY,status TEXT,camera_source TEXT,score REAL,margin REAL,
                    validated_at TEXT,validated_by TEXT,note TEXT,created_at TEXT,updated_at TEXT);
            """)
            for sid in (1, 2, 3):
                conn.execute("INSERT INTO students(id,student_code,full_name,consent_at,biometric_consent_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                             (sid, f"E{sid}", f"Employee {sid}", self.now.isoformat(), "NOT_GRANTED", self.now.isoformat(), self.now.isoformat()))
        package = self.db.__package__
        auth = types.ModuleType(package + ".auth")
        auth.permissions_for_role = lambda role: ["employee.enroll"] if role in {"SUPER_ADMIN", "ADMIN", "HR"} else []
        auth.has_permission = lambda user, permission: permission in user["permissions"]
        sys.modules[auth.__name__] = auth
        key = secrets.token_bytes(32)
        crypto = types.ModuleType(package + ".crypto")

        def encrypt(raw):
            nonce = secrets.token_bytes(16)
            stream = hashlib.shake_256(key + nonce).digest(len(raw))
            body = bytes(a ^ b for a, b in zip(raw, stream))
            return nonce + hmac.digest(key, nonce + body, "sha256") + body

        def decrypt(blob):
            nonce, signature, body = blob[:16], blob[16:48], blob[48:]
            if not hmac.compare_digest(signature, hmac.digest(key, nonce + body, "sha256")):
                raise ValueError("invalid isolated ciphertext")
            stream = hashlib.shake_256(key + nonce).digest(len(body))
            return bytes(a ^ b for a, b in zip(body, stream))

        crypto.encrypt_bytes, crypto.decrypt_bytes = encrypt, decrypt
        sys.modules[crypto.__name__] = crypto
        self.crypto = crypto
        spec = importlib.util.spec_from_file_location(package + ".qr_enrollment", SOURCE / "qr_enrollment.py")
        self.qr = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.qr
        spec.loader.exec_module(self.qr)
        self.retired, self.resets, self.refreshes, self.portraits = [], [], [], []

        def duplicate(blob, sid, conn):
            for row in conn.execute("SELECT student_id,embedding_blob FROM face_templates WHERE student_id<>?", (sid,)).fetchall():
                if decrypt(bytes(row["embedding_blob"])) == decrypt(blob):
                    return {"student_id": row["student_id"], "score": .99, "strong": True, "full_name": "Other employee"}
            return None

        def refresh():
            self.assertFalse(self.raw.in_transaction, "INDEX refresh must follow commit")
            self.refreshes.append(self.db.fetchall("SELECT * FROM face_templates"))

        self.qr.bind_runtime_callbacks(retire_capture=self.retired.append, reset_capture=self.resets.append,
                                      duplicate_checker=duplicate, refresh_active_index=refresh,
                                      save_approved_preview=lambda sid, blob, **kwargs: self.portraits.append((sid, blob)))
        self.qr.ensure_qr_enrollment_schema()

    def error(self, code, operation):
        with self.assertRaises(self.qr.EnrollmentError) as caught:
            operation()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def invite(self, sid=1, store=1, **kwargs):
        return self.qr.issue_invitation(self.owner, sid, store, now=self.now, **kwargs)

    def redeem(self, issued=None):
        issued = issued or self.invite()
        return self.qr.redeem_invitation(issued["invite_secret"], now=self.now)

    def consent(self, session):
        return self.qr.accept_capture_consent(session["capture_secret"], now=self.now)

    def draft(self, value=b"face-A", **kwargs):
        data = dict(template_blob=self.crypto.encrypt_bytes(value), preview_blob=self.crypto.encrypt_bytes(b"\xff\xd8test-preview"),
                    pose_count=10, quality={"ready": True, "scan_passes": 2, "pose_counts": {"CENTER": 2}},
                    pad={"status": "PASS", "verified_at": self.now.isoformat(), "source": "existing_passive_pad"})
        data.update(kwargs)
        return self.qr.PreparedDraft(**data)

    def pending(self, sid=1, value=b"face-A"):
        session = self.redeem(self.invite(sid))
        self.consent(session)
        result = self.qr.stage_prepared_request(session["request"]["id"], self.draft(value), session_secret=session["capture_secret"], now=self.now)
        return result["request"], session

    def stored(self, rid):
        return self.db.fetchone("SELECT * FROM face_enrollment_requests WHERE id=?", (rid,))

    def active(self, sid=1):
        row = self.db.fetchone("SELECT * FROM face_templates WHERE student_id=?", (sid,))
        return self.crypto.decrypt_bytes(bytes(row["embedding_blob"])) if row else None

    def old_active(self, sid=1, value=b"old-face"):
        stamp = self.now.isoformat()
        self.db.execute("INSERT INTO face_templates(student_id,embedding_blob,pose_count,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (sid, self.crypto.encrypt_bytes(value), 10, stamp, stamp))

    def approve(self, row, **kwargs):
        data = {"expected_revision": row["revision"], "now": self.now}
        data.update(kwargs)
        return self.qr.approve_request(self.owner, row["id"], **data)

    def test_schema_exact_two_additions_idempotent_legacy_bytes_unchanged(self):
        self.old_active()
        existing = [row["name"] for row in self.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
                    if row["name"] not in {"face_enrollment_requests", "qr_enrollment_invites"}]
        schemas = {name: self.db.fetchone("SELECT sql FROM sqlite_master WHERE name=?", (name,))["sql"] for name in existing}
        records = {name: self.db.fetchall(f"SELECT * FROM {name}") for name in existing}
        before = set(existing)
        trace = []
        self.raw.set_trace_callback(trace.append)
        self.qr.ensure_qr_enrollment_schema()
        self.qr.ensure_qr_enrollment_schema()
        self.raw.set_trace_callback(None)
        after = {row["name"] for row in self.db.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(after - before, {"face_enrollment_requests", "qr_enrollment_invites"})
        self.assertFalse(any(re.match(r"\s*(ALTER|DROP|DELETE|UPDATE)\b", sql, re.I) for sql in trace))
        for name in existing:
            self.assertEqual(schemas[name], self.db.fetchone("SELECT sql FROM sqlite_master WHERE name=?", (name,))["sql"])
            self.assertEqual(records[name], self.db.fetchall(f"SELECT * FROM {name}"))
        self.assertEqual(self.active(), b"old-face")

    def test_invitation_hash_only_no_consent_and_no_secrets_in_dto_audit(self):
        issued = self.invite()
        self.assertEqual(issued["request"]["consent_status"], "NOT_GRANTED")
        self.assertTrue(issued["qr_path"].startswith("/enroll#invite="))
        invite = self.db.fetchone("SELECT * FROM qr_enrollment_invites")
        self.assertEqual(invite["token_hash"], hashlib.sha256(issued["invite_secret"].encode()).hexdigest())
        self.assertNotIn(issued["invite_secret"], json.dumps(invite))
        session = self.redeem(issued)
        for value in (issued["invite_secret"], session["capture_secret"], "template_blob", "token_hash", "session_hash"):
            self.assertNotIn(value, json.dumps(self.qr.capture_status(session["capture_secret"], now=self.now)))
            self.assertNotIn(value, json.dumps(self.db.fetchall("SELECT * FROM audit_events")))
        self.assertIsNone(self.active())

    def test_expiry_reuse_reissue_revocation_and_fixed_session_deadline(self):
        issued = self.invite()
        session = self.redeem(issued)
        self.error("INVITATION_UNAVAILABLE", lambda: self.redeem(issued))
        self.consent(session)
        before = self.qr.capture_status(session["capture_secret"], now=self.now)["session_expires_at"]
        self.qr.reset_capture(session["capture_secret"], now=self.now + timedelta(minutes=10))
        self.assertEqual(self.qr.capture_status(session["capture_secret"], now=self.now + timedelta(minutes=20))["session_expires_at"], before)
        self.error("CAPTURE_UNAVAILABLE", lambda: self.qr.capture_status(session["capture_secret"], now=self.now + timedelta(minutes=30)))
        self.assertEqual(self.stored(issued["request"]["id"])["status"], "EXPIRED")
        fresh = self.invite()
        newer = self.invite(store=2)
        self.error("INVITATION_UNAVAILABLE", lambda: self.redeem(fresh))
        self.assertEqual(self.stored(fresh["request"]["id"])["status"], "CANCELLED")
        self.assertNotEqual(fresh["invite_secret"], newer["invite_secret"])
        expired = self.invite(sid=2)
        self.error("INVITATION_UNAVAILABLE", lambda: self.qr.redeem_invitation(expired["invite_secret"], now=self.now + timedelta(minutes=15)))

    def test_atomic_one_use_redemption_concurrent_threads(self):
        issued, barrier, successes, failures = self.invite(), threading.Barrier(2), [], []

        def run():
            barrier.wait()
            try:
                successes.append(self.redeem(issued))
            except self.qr.EnrollmentError as exc:
                failures.append(exc.code)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(successes), 1)
        self.assertEqual(failures, ["INVITATION_UNAVAILABLE"])

    def test_rbac_current_role_active_status_and_missing_permission(self):
        for actor in ({"id": 3, "role": "ADMIN"}, {"id": 4, "role": "SUPER_ADMIN"}, {"id": 5, "role": "ADMIN"}, {}, {"id": 999, "role": "SUPER_ADMIN"}):
            self.error("ENROLLMENT_FORBIDDEN", lambda: self.qr.issue_invitation(actor, 1, 1, now=self.now))
        issued = self.qr.issue_invitation(self.admin, 1, 1, now=self.now)
        self.assertEqual(issued["request"]["created_by_user_id"], 2)
        self.error("ENROLLMENT_FORBIDDEN", lambda: self.qr.get_request({"id": 3}, issued["request"]["id"], now=self.now))
        self.qr.auth.permissions_for_role = lambda role: []
        self.error("ENROLLMENT_FORBIDDEN", lambda: self.invite(sid=2))

    def test_explicit_store_binding_no_auto_assignment_and_current_mismatch_denied(self):
        row, _ = self.pending()
        self.approve(row)
        self.assertEqual(self.active(), b"face-A")
        self.assertEqual(self.db.fetchall("SELECT * FROM employee_store_assignments"), [])
        self.db.execute("INSERT INTO employee_store_assignments VALUES(2,2,1,'2026')")
        self.error("STORE_ASSIGNMENT_MISMATCH", lambda: self.invite(sid=2, store=1))
        valid = self.invite(sid=2, store=2)
        session = self.redeem(valid)
        self.consent(session)
        row = self.qr.stage_prepared_request(valid["request"]["id"], self.draft(b"face-B"), session_secret=session["capture_secret"], now=self.now)["request"]
        self.db.execute("UPDATE employee_store_assignments SET store_id=1 WHERE student_id=2")
        self.error("STORE_ASSIGNMENT_MISMATCH", lambda: self.approve(row))
        self.assertIsNone(self.active(2))
        self.error("ENROLLMENT_TARGET_UNAVAILABLE", lambda: self.invite(sid=3, store=3))
        self.error("INVALID_ENROLLMENT_INPUT", lambda: self.invite(sid=3, store=None))

    def test_actual_consent_required_frame_submit_approve_withdrawn_not_regranted(self):
        session = self.redeem()
        self.error("CONSENT_REQUIRED", lambda: self.qr.capture_frame_lease(session["capture_secret"], now=self.now).__enter__())
        self.error("CONSENT_REQUIRED", lambda: self.qr.stage_prepared_request(session["request"]["id"], self.draft(), session_secret=session["capture_secret"], now=self.now))
        self.consent(session)
        row = self.qr.stage_prepared_request(session["request"]["id"], self.draft(), session_secret=session["capture_secret"], now=self.now)["request"]
        self.db.execute("UPDATE students SET biometric_consent_status='WITHDRAWN' WHERE id=1")
        self.error("CONSENT_REQUIRED", lambda: self.approve(row))
        newer = self.redeem(self.invite())
        self.error("CONSENT_WITHDRAWN", lambda: self.consent(newer))
        self.assertEqual(self.db.fetchone("SELECT biometric_consent_status FROM students WHERE id=1")["biometric_consent_status"], "WITHDRAWN")

    def test_server_quality_pad_freshness_and_ciphertext_gate(self):
        session = self.redeem()
        self.consent(session)
        values = [("QUALITY_NOT_READY", self.draft(quality={"ready": True, "scan_passes": 1})),
                  ("PAD_NOT_READY", self.draft(pad={"status": "PENDING", "verified_at": self.now.isoformat()})),
                  ("PAD_NOT_READY", self.draft(pad={"status": "FAIL", "verified_at": self.now.isoformat()})),
                  ("PAD_STALE", self.draft(pad={"status": "PASS", "verified_at": (self.now - timedelta(seconds=6)).isoformat()})),
                  ("PAD_STALE", self.draft(pad={"status": "PASS", "verified_at": (self.now + timedelta(seconds=2)).isoformat()})),
                  ("DRAFT_NOT_READY", self.draft(template_blob=b"plaintext"))]
        for code, draft in values:
            self.error(code, lambda: self.qr.stage_prepared_request(session["request"]["id"], draft, session_secret=session["capture_secret"], now=self.now))
        self.error("DRAFT_NOT_READY", lambda: self.qr.stage_prepared_request(session["request"]["id"], {"pad": "PASS"}, session_secret=session["capture_secret"], now=self.now))
        self.assertEqual(self.stored(session["request"]["id"])["status"], "CAPTURING")
        self.assertIsNone(self.active())

    def test_submit_encrypted_pending_idempotent_and_no_capture_after_submit(self):
        row, session = self.pending()
        self.assertEqual(row["status"], "PENDING_REVIEW")
        stored = self.stored(row["id"])
        self.assertNotEqual(bytes(stored["template_blob"]), b"face-A")
        self.assertEqual(self.crypto.decrypt_bytes(bytes(stored["template_blob"])), b"face-A")
        self.assertEqual(self.qr.get_preview(self.owner, row["id"], now=self.now), b"\xff\xd8test-preview")
        self.assertIsNone(self.active())
        self.assertEqual(self.refreshes, [])
        repeated = self.qr.stage_prepared_request(row["id"], None, session_secret=session["capture_secret"], now=self.now)
        self.assertTrue(repeated["already_submitted"])
        self.assertEqual(repeated["request"]["revision"], row["revision"])
        self.error("ALREADY_SUBMITTED", lambda: self.qr.reset_capture(session["capture_secret"], now=self.now))
        self.error("ALREADY_SUBMITTED", lambda: self.qr.capture_frame_lease(session["capture_secret"], now=self.now).__enter__())
        self.assertEqual(self.qr.capture_status(session["capture_secret"], now=self.now)["request"]["status"], "PENDING_REVIEW")
        self.assertIn(row["id"], self.retired)

    def test_explicit_approval_atomic_publication_validation_and_postcommit_refresh(self):
        self.old_active()
        row, session = self.pending()
        self.assertEqual(self.active(), b"old-face")
        self.error("REVISION_CONFLICT", lambda: self.approve(row, expected_revision=0))
        result = self.approve(row)
        self.assertEqual(result["request"]["status"], "APPROVED")
        self.assertEqual(self.active(), b"face-A")
        self.assertEqual(self.db.fetchone("SELECT status FROM face_enrollment_validations WHERE student_id=1")["status"], "PENDING_STORE_VALIDATION")
        self.assertIsNone(self.stored(row["id"])["template_blob"])
        self.assertIsNone(self.stored(row["id"])["preview_blob"])
        self.assertEqual(len(self.refreshes), 1)
        self.assertEqual(len(self.portraits), 1)
        self.error("CAPTURE_UNAVAILABLE", lambda: self.qr.capture_status(session["capture_secret"], now=self.now))
        self.error("REVISION_CONFLICT", lambda: self.approve(row))

    def test_reject_cancel_expire_reenroll_preserve_old_active_and_purge(self):
        self.old_active()
        row, session = self.pending()
        rejected = self.qr.reject_request(self.owner, row["id"], expected_revision=row["revision"], reason="Try better lighting", now=self.now)
        self.assertEqual(rejected["request"]["status"], "REJECTED")
        self.assertEqual(self.active(), b"old-face")
        self.assertIsNone(self.stored(row["id"])["template_blob"])
        self.error("CAPTURE_UNAVAILABLE", lambda: self.qr.capture_status(session["capture_secret"], now=self.now))
        row, session = self.pending()
        fresh = self.qr.request_reenrollment(self.owner, row["id"], expected_revision=row["revision"], reason="Repeat capture", now=self.now)
        self.assertEqual(fresh["previous_request"]["status"], "REJECTED")
        self.assertNotEqual(fresh["request"]["id"], row["id"])
        self.assertEqual(fresh["request"]["status"], "CAPTURING")
        self.error("CAPTURE_UNAVAILABLE", lambda: self.qr.capture_status(session["capture_secret"], now=self.now))
        self.assertEqual(self.active(), b"old-face")
        self.assertTrue(any(json.loads(x["detail_json"])["action"] == "REQUEST_REENROLLMENT" for x in self.db.fetchall("SELECT * FROM audit_events")))
        self.qr.cancel_request(self.owner, fresh["request"]["id"], expected_revision=0, reason="Stop", now=self.now)
        row, _ = self.pending()
        self.assertEqual(self.qr.expire_requests(now=self.now + timedelta(hours=72)), 1)
        self.assertEqual(self.qr.expire_requests(now=self.now + timedelta(hours=72)), 0)
        self.assertEqual(self.stored(row["id"])["status"], "EXPIRED")
        self.assertEqual(self.active(), b"old-face")
        self.assertEqual(self.refreshes, [])

    def test_duplicate_recheck_concurrent_approvals_only_one_active_until_override(self):
        first, _ = self.pending(1)
        second, _ = self.pending(2)
        barrier, approved, denied = threading.Barrier(2), [], []

        def run(row):
            barrier.wait()
            try:
                approved.append(self.approve(row)["request"])
            except self.qr.EnrollmentError as exc:
                denied.append((row, exc.code))

        threads = [threading.Thread(target=run, args=(row,)) for row in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(approved), 1)
        self.assertEqual(denied[0][1], "DUPLICATE_REVIEW_REQUIRED")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM face_templates")["n"], 1)
        row = self.qr.get_request(self.owner, denied[0][0]["id"], now=self.now)["request"]
        self.assertEqual(row["status"], "NEEDS_DUPLICATE_REVIEW")
        self.assertTrue(row["duplicate"]["strong"])
        self.error("REVIEW_REASON_REQUIRED", lambda: self.approve(row, duplicate_override=True))
        self.approve(row, duplicate_override=True, reason="Explicit reviewed duplicate exception")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM face_templates")["n"], 2)

    def test_failed_publish_rolls_back_active_draft_audit_and_never_refreshes(self):
        self.old_active()
        row, _ = self.pending()
        audit_count = self.db.fetchone("SELECT COUNT(*) n FROM audit_events")["n"]
        with self.db.connection() as conn:
            conn.execute("CREATE TRIGGER fail_validation BEFORE INSERT ON face_enrollment_validations BEGIN SELECT RAISE(ABORT,'isolated rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.approve(row)
        self.assertEqual(self.active(), b"old-face")
        self.assertEqual(self.stored(row["id"])["status"], "PENDING_REVIEW")
        self.assertIsNotNone(self.stored(row["id"])["template_blob"])
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM audit_events")["n"], audit_count)
        self.assertEqual(self.refreshes, [])

    def test_restart_only_retires_incomplete_and_review_drafts_survive(self):
        pending, _ = self.pending(1)
        capturing = self.redeem(self.invite(2))
        self.assertEqual(self.qr.recover_incomplete_captures(now=self.now), 1)
        self.assertEqual(self.stored(pending["id"])["status"], "PENDING_REVIEW")
        self.assertIsNotNone(self.stored(pending["id"])["template_blob"])
        self.assertEqual(self.stored(capturing["request"]["id"])["status"], "EXPIRED")
        self.error("CAPTURE_UNAVAILABLE", lambda: self.qr.capture_status(capturing["capture_secret"], now=self.now))
        self.approve(pending)

    def test_withdrawal_outer_transaction_retirement_after_commit_and_rollback(self):
        self.old_active()
        row, _ = self.pending()
        retired_before = list(self.retired)
        with self.assertRaises(RuntimeError):
            with self.qr.publication_transaction() as conn:
                conn.execute("UPDATE students SET biometric_consent_status='WITHDRAWN' WHERE id=1")
                conn.execute("DELETE FROM face_templates WHERE student_id=1")
                self.qr.cancel_employee_requests(1, actor=self.owner, conn=conn, now=self.now)
                raise RuntimeError("isolated rollback")
        self.assertEqual(self.stored(row["id"])["status"], "PENDING_REVIEW")
        self.assertEqual(self.active(), b"old-face")
        self.assertEqual(self.retired, retired_before)
        with self.qr.publication_transaction() as conn:
            conn.execute("UPDATE students SET biometric_consent_status='WITHDRAWN' WHERE id=1")
            conn.execute("DELETE FROM face_templates WHERE student_id=1")
            retired = self.qr.cancel_employee_requests(1, actor=self.owner, conn=conn, now=self.now)
        self.qr.retire_requests(retired)
        self.assertEqual(self.stored(row["id"])["status"], "CANCELLED")
        self.assertIsNone(self.active())
        self.error("REVISION_CONFLICT", lambda: self.approve(row))

    def test_desktop_binding_replay_reset_singleflight_and_late_revocation(self):
        self.db.execute("UPDATE students SET biometric_consent_status='GRANTED' WHERE id=1")
        row = self.qr.start_desktop_request(self.owner, 1, 1, now=self.now)["request"]
        self.error("CAPTURE_FORBIDDEN", lambda: self.qr.desktop_capture_lease(self.admin, row["id"], now=self.now).__enter__())
        self.error("CAPTURE_TARGET_MISMATCH", lambda: self.qr.desktop_capture_lease(self.owner, row["id"], student_id=2, now=self.now).__enter__())
        with self.qr.desktop_capture_lease(self.owner, row["id"], now=self.now) as binding:
            self.assertEqual(binding["student_id"], 1)
            self.error("FRAME_BUSY", lambda: self.qr.desktop_capture_lease(self.owner, row["id"], now=self.now).__enter__())
            self.error("FRAME_BUSY", lambda: self.qr.reset_capture(actor=self.owner, request_id=row["id"], now=self.now))
        result = self.qr.stage_prepared_request(row["id"], self.draft(), actor=self.owner, now=self.now)
        repeat = self.qr.stage_prepared_request(row["id"], None, actor=self.owner, now=self.now)
        self.assertTrue(repeat["already_submitted"])
        self.assertEqual(result["request"], repeat["request"])
        other = self.qr.start_desktop_request(self.owner, 1, 1, now=self.now)["request"]
        with self.assertRaises(self.qr.EnrollmentError):
            with self.qr.desktop_capture_lease(self.owner, other["id"], now=self.now):
                self.qr.cancel_request(self.owner, other["id"], expected_revision=0, reason="Cancel during frame", now=self.now)
        self.assertFalse(self.qr._INFLIGHT)

    def test_unique_active_across_stores_scope_sql_filter_and_employee_delete_compatibility(self):
        issued = self.invite()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.connection() as conn:
                conn.execute("INSERT INTO face_enrollment_requests(id,student_id,store_id,source_kind,status,created_by_user_id,expires_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             ("a" * 32, 1, 2, "DESKTOP", "CAPTURING", 1, self.now.isoformat(), self.now.isoformat(), self.now.isoformat()))
        self.invite(sid=2, store=2)
        filtered = self.qr.list_requests(self.owner, student_id=2, now=self.now)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["student_id"], 2)
        self.qr.scoped_store_ids = lambda actor: frozenset({1})
        self.assertEqual(self.qr.list_requests(self.owner, now=self.now)["total"], 1)
        self.error("STORE_SCOPE_DENIED", lambda: self.invite(sid=3, store=2))
        self.db.execute("DELETE FROM students WHERE id=1")
        self.assertIsNone(self.stored(issued["request"]["id"]))
        self.assertIsNone(self.db.fetchone("SELECT id FROM qr_enrollment_invites WHERE request_id=?", (issued["request"]["id"],)))

    def test_cleanup_without_optional_new_schema_is_noop(self):
        # Drop only isolated test fixtures, never a migration/runtime operation.
        with self.db.connection() as conn:
            conn.execute("DROP TABLE qr_enrollment_invites")
            conn.execute("DROP TABLE face_enrollment_requests")
        self.assertEqual(self.qr.cancel_employee_requests(1, now=self.now), [])


if __name__ == "__main__":
    unittest.main()

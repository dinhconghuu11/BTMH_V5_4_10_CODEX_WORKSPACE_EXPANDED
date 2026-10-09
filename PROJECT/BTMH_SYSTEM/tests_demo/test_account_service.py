"""Account operations against in-memory SQL and actual existing password checks.

No real SMS/secret store or customer DB. Test crypto/provider are isolated; the
password fixture selects existing PBKDF2 fallback so no optional package is needed.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time
import types
import unittest

from test_demo_context import load_isolated_modules

SOURCE = Path(__file__).resolve().parents[1] / "module_app"
PW = "OnlyForAccountTests!550"
NEW = "ChangedForAccountTests!550"


class AccountServiceTests(unittest.TestCase):
    def setUp(self):
        self.db, self.context = load_isolated_modules()
        raw = sqlite3.connect(":memory:", check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(raw.close)
        lock = threading.RLock()

        @contextmanager
        def connection():
            with lock:
                try:
                    yield self.db._CompatConnection(raw, "sqlite")
                    raw.commit()
                except Exception:
                    raw.rollback()
                    raise

        self.db.connection = connection
        self.db.init_db()
        with self.db.connection() as conn:
            conn.executescript("""
                CREATE TABLE system_users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE NOT NULL,
                  display_name TEXT NOT NULL,role TEXT NOT NULL,password_salt TEXT NOT NULL,password_hash TEXT NOT NULL,
                  active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE stores(id INTEGER PRIMARY KEY,store_name TEXT);
                INSERT INTO stores VALUES(1,'Store A'),(2,'Store B');
            """)
        package = self.db.__package__
        crypto = types.ModuleType(package + ".crypto")
        crypto.encrypt_bytes = base64.b64encode
        crypto.decrypt_bytes = base64.b64decode
        sys.modules[crypto.__name__] = crypto
        provider = types.ModuleType(package + ".sms_provider_v542")
        provider.configured = lambda: False
        provider.get_provider = lambda: (_ for _ in ()).throw(AssertionError("no test may contact SMS"))
        sys.modules[provider.__name__] = provider
        for name in ("auth", "sms_auth_v542", "account_service"):
            spec = importlib.util.spec_from_file_location(package + "." + name, SOURCE / (name + ".py"))
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            setattr(self, name, module)
        self.auth._ARGON2 = None
        self.sms = self.sms_auth_v542
        self.auth.ensure_rbac_schema()
        self.sms.ensure_schema()
        self.owner = self.auth.bootstrap_admin("testowner", "Test Owner", PW, phone_verified=False)
        self.token = self.session(self.owner["id"])

    def row(self, uid=None):
        return self.db.fetchone("SELECT * FROM system_users WHERE id=?", (uid or self.owner["id"],))

    def session(self, uid):
        return self.auth._issue_session(self.db.fetchone("SELECT * FROM system_users WHERE id=?", (uid,)))["token"]

    def create(self, **kwargs):
        values = {"username": "teststaff", "display_name": "Test Staff", "role": "MANAGER", "password": PW, "confirm_password": PW}
        values.update(kwargs)
        return self.account_service.provision_account(self.owner, self.token, **values)

    def change(self, **kwargs):
        values = {"current_password": PW, "new_password": NEW, "confirm_password": NEW}
        values.update(kwargs)
        return self.account_service.change_self_password(self.token, **values)

    def assert_error(self, code, callable):
        with self.assertRaises(self.account_service.AccountError) as error:
            callable()
        self.assertEqual(error.exception.code, code)
        return error.exception

    def enable_factor(self, method="SMS"):
        if method == "SMS":
            self.db.execute("INSERT INTO sms_factors_v542 VALUES(?,?,1,'2026')", (self.owner["id"], "test-only-encrypted-phone"))
        else:
            self.db.execute("INSERT INTO account_mfa(user_id,enabled,secret_enc,updated_at) VALUES(?,1,'test-secret','2026')", (self.owner["id"],))
        # New valid session captures the new factor in its credential tag.
        self.token = self.session(self.owner["id"])

    def test_public_self_profile_contains_supported_fields_no_secrets(self):
        self.auth._save_user_profile(self.owner["id"], phone="0912345678", email="test@example.invalid", store_id=1)
        profile = self.account_service.get_self_profile(self.token)
        self.assertEqual(profile["editable_fields"], ["display_name"])
        self.assertEqual(profile["user"]["store_name"], "Store A")
        self.assertEqual(profile["user"]["phone"], "0912345678")
        self.assertEqual(profile["password_policy"]["minimum_length"], 12)
        for secret in ("password_salt", "password_hash", self.token, PW):
            self.assertNotIn(secret, json.dumps(profile))

    def test_name_edit_refreshes_sessions_without_extending_expiry_or_factor_freshness(self):
        second = self.session(self.owner["id"])
        self.auth.mark_factor_verified(self.token)
        before = dict(self.auth._sessions)
        factors, tags = dict(self.auth._session_factor_times), dict(self.auth._session_credential_tags)
        updated = self.account_service.update_self_profile(self.token, display_name="  New Display Name  ")
        self.assertEqual(updated["user"]["display_name"], "New Display Name")
        self.assertEqual(self.row()["display_name"], "New Display Name")
        self.assertEqual(self.auth.user_for_token(second)["display_name"], "New Display Name")
        self.assertEqual({token: expiry for token, (expiry, _) in self.auth._sessions.items()}, {token: expiry for token, (expiry, _) in before.items()})
        self.assertEqual(self.auth._session_factor_times, factors)
        self.assertEqual(self.auth._session_credential_tags, tags)
        self.assertEqual(self.row()["role"], "SUPER_ADMIN")
        with self.assertRaises(TypeError):
            self.account_service.update_self_profile(self.token, display_name="A", role="ADMIN")

    def test_expired_session_disabled_user_and_invalid_name_do_not_write(self):
        self.assert_error("SESSION_EXPIRED", lambda: self.account_service.get_self_profile("missing"))
        self.assert_error("INVALID_ACCOUNT_INPUT", lambda: self.account_service.update_self_profile(self.token, display_name=" "))
        self.assert_error("INVALID_ACCOUNT_INPUT", lambda: self.account_service.update_self_profile(self.token, display_name="a" * 121))
        self.assertEqual(self.row()["display_name"], "Test Owner")
        self.db.execute("UPDATE system_users SET active=0 WHERE id=?", (self.owner["id"],))
        self.assert_error("SESSION_EXPIRED", lambda: self.change())

    def test_current_password_confirmation_and_strength_required_before_mutation(self):
        original = self.row()["password_hash"]
        self.assert_error("PASSWORD_CONFIRMATION_MISMATCH", lambda: self.change(confirm_password="different"))
        self.assert_error("WEAK_PASSWORD", lambda: self.change(new_password="weak", confirm_password="weak"))
        wrong = self.assert_error("CURRENT_PASSWORD_INVALID", lambda: self.change(current_password="wrong"))
        self.assertEqual(wrong.field, "current_password")
        self.assertEqual(self.row()["password_hash"], original)
        self.assertIsNotNone(self.auth.user_for_token(self.token))

    def test_current_password_uses_existing_login_failure_throttle(self):
        for _ in range(self.auth._LOGIN_MAX_FAILURES - 1):
            self.assert_error("CURRENT_PASSWORD_INVALID", lambda: self.change(current_password="wrong"))
        locked = self.assert_error("PASSWORD_RATE_LIMITED", lambda: self.change(current_password="wrong"))
        self.assertEqual(locked.status, 429)
        self.assertTrue(self.auth.login_lock_status(self.owner["username"])["locked"])
        self.assert_error("PASSWORD_RATE_LIMITED", lambda: self.change())

    def test_enrolled_sms_or_totp_requires_fresh_factor_no_missing_provider_bypass(self):
        for method in ("SMS", "TOTP"):
            with self.subTest(method=method):
                self.enable_factor(method)
                self.assert_error("STEP_UP_REQUIRED", lambda: self.change())
                self.auth.mark_factor_verified(self.token)
                self.assertTrue(self.account_service.get_self_profile(self.token)["security"]["fresh_verification"])
                self.auth._session_factor_times[self.token] = time.time() - 301
                self.assert_error("STEP_UP_REQUIRED", lambda: self.change())
                self.auth.mark_factor_verified(self.token)
                # Check only guard here; success/revocation uses its own real fixture.
                self.account_service._factor_guard(self.row(), self.token)

    def test_success_changes_hash_revokes_sessions_trust_challenges_and_preserves_factor(self):
        other = self.create(username="otheruser", role="HR")
        other_token = self.session(other["id"])
        self.enable_factor()
        second = self.session(self.owner["id"])
        self.auth.mark_factor_verified(self.token)
        self.auth.mark_factor_verified(second)
        uid = self.owner["id"]
        self.db.execute("INSERT INTO sms_trusted_browsers_v542(id_hash,user_id,credential_tag,created_at,expires_at,last_used_at,label) VALUES('trust',?,'old',1,9999999999,1,'Test')", (uid,))
        self.db.execute("INSERT INTO sms_challenges_v542(id_hash,user_id,purpose,phone_enc,binding_hash,session_hash,credential_tag,state,created_at,expires_at) VALUES('challenge',?,'STEPUP','none','binding','session','old','NEW',1,9999999999)", (uid,))
        result = self.change()
        self.assertEqual(result, {"ok": True, "relogin_required": True})
        row = self.row()
        self.assertFalse(self.auth._verify_password(PW, row["password_salt"], row["password_hash"])[0])
        self.assertTrue(self.auth._verify_password(NEW, row["password_salt"], row["password_hash"])[0])
        for token in (self.token, second):
            self.assertIsNone(self.auth.user_for_token(token))
            self.assertNotIn(token, self.auth._session_factor_times)
            self.assertNotIn(token, self.auth._session_credential_tags)
        self.assertIsNotNone(self.auth.user_for_token(other_token))
        self.assertEqual(self.db.fetchone("SELECT revoked FROM sms_trusted_browsers_v542")["revoked"], 1)
        self.assertEqual(self.db.fetchone("SELECT state FROM sms_challenges_v542")["state"], "CANCELLED")
        self.assertTrue(self.sms.factor(uid))

    def test_atomic_credentials_compare_rejects_concurrent_reset(self):
        old = self.row()
        self.auth.reset_user_password(old["id"], NEW)
        with self.assertRaisesRegex(ValueError, "đã thay đổi"):
            self.auth.reset_user_password(old["id"], PW, expected_credentials=(old["password_salt"], old["password_hash"]))
        self.assertTrue(self.auth._verify_password(NEW, self.row()["password_salt"], self.row()["password_hash"])[0])

    def test_owner_admin_provision_with_normalized_profile_and_unverified_contacts(self):
        created = self.create(phone="+84 912 345 678", email="TEST@EXAMPLE.INVALID", store_id=2)
        self.assertEqual((created["role"], created["store_id"], created["phone"], created["email"]), ("MANAGER", 2, "0912345678", "test@example.invalid"))
        self.assertFalse(created["phone_verified"])
        self.assertFalse(created["email_verified"])
        self.assertFalse(created["mfa_enabled"])
        self.assertNotIn("password_hash", created)
        admin = self.create(username="testadmin", role="ADMIN")
        admin_token = self.session(admin["id"])
        staff = self.account_service.provision_account(admin, admin_token, username="adminstaff", display_name="Admin Staff", role="EMPLOYEE", password=PW)
        self.assertEqual(staff["role"], "EMPLOYEE")
        self.assert_error("ACCOUNT_PROVISION_DENIED", lambda: self.account_service.provision_account(
            admin, admin_token, username="forgedowner", display_name="Blocked Owner", role="SUPER_ADMIN", password=PW))
        self.assertIsNone(self.db.fetchone("SELECT id FROM system_users WHERE username='forgedowner'"))

    def test_non_admin_cannot_provision_even_with_forged_role_or_foreign_actor(self):
        staff = self.create(role="HR")
        token = self.session(staff["id"])
        self.assert_error("ACCOUNT_PROVISION_DENIED", lambda: self.account_service.provision_account(
            {**staff, "role": "SUPER_ADMIN"}, token, username="blocked", display_name="Blocked", role="ADMIN", password=PW))
        self.assert_error("ACCOUNT_PROVISION_DENIED", lambda: self.account_service.provision_account(
            staff, self.token, username="blocked", display_name="Blocked", role="ADMIN", password=PW))
        self.assertIsNone(self.db.fetchone("SELECT id FROM system_users WHERE username='blocked'"))

    def test_admin_provision_requires_existing_fresh_factor_guard(self):
        self.enable_factor()
        self.assert_error("STEP_UP_REQUIRED", lambda: self.create())
        self.auth.mark_factor_verified(self.token)
        self.assertEqual(self.create()["username"], "teststaff")

    def test_profile_validation_duplicate_contacts_store_and_confirmation_leave_no_partial_user(self):
        created = self.create(phone="0912345678", email="unique@example.invalid", store_id=1)
        for values, code in (({"username": "bad1", "email": "new@example.invalid"}, "PROFILE_PHONE_REQUIRED"),
                             ({"username": "bad2", "phone": "0912345678"}, "ACCOUNT_ALREADY_EXISTS"),
                             ({"username": "bad3", "phone": "0912345679", "email": "UNIQUE@example.invalid"}, "ACCOUNT_ALREADY_EXISTS"),
                             ({"username": "bad4", "phone": "0912345679", "store_id": 999}, "INVALID_ACCOUNT_INPUT"),
                             ({"username": "bad5", "confirm_password": "mismatch"}, "PASSWORD_CONFIRMATION_MISMATCH")):
            self.assert_error(code, lambda values=values: self.create(**values))
            self.assertIsNone(self.db.fetchone("SELECT id FROM system_users WHERE username=?", (values["username"],)))
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM account_profiles")["n"], 1)
        self.assertEqual(created["store_id"], 1)

    def test_profile_insert_failure_rolls_back_user_and_legacy_bare_creation_supported(self):
        self.db.execute("CREATE TRIGGER synthetic_profile_failure BEFORE INSERT ON account_profiles BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.create(phone="0912345678")
        self.assertIsNone(self.db.fetchone("SELECT id FROM system_users WHERE username='teststaff'"))
        self.db.execute("DROP TRIGGER synthetic_profile_failure")
        created = self.create(confirm_password=None)
        self.assertIsNone(created["store_id"])
        self.assertEqual(created["email"], "")
        self.assertEqual(self.db.fetchone("SELECT COUNT(*) n FROM account_profiles")["n"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

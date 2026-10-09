from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
AUTH = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")


def test_mfa_verify_is_public_until_the_challenge_issues_a_session():
    assert '"/api/v1/auth/mfa/verify"' in MAIN.split("MOBILE_PUBLIC_API_PATHS", 1)[0]


def test_owner_credential_is_packaged_as_argon2id_verifier():
    assert '_RELEASE_OWNER_USERNAME = "OWNER_SETUP_REQUIRED"' in AUTH
    assert '_RELEASE_OWNER_PASSWORD_HASH = "$argon2id$' in AUTH


def test_one_time_owner_provision_smoke(tmp_path):
    import os, subprocess, sys, textwrap
    script = textwrap.dedent(r'''
        from module_app.db import init_db, fetchone
        from module_app.production_ops import ensure_production_schema
        from module_app.auth import (
            ensure_rbac_schema, provision_release_owner_account, login,
            change_password_by_verified_phone,
        )
        init_db(); ensure_production_schema(); ensure_rbac_schema()
        first = provision_release_owner_account()
        assert first["provisioned"] is True
        row = fetchone("SELECT username,role,active,password_hash FROM system_users WHERE username=?", ("OWNER_SETUP_REQUIRED",))
        assert row["role"] == "SUPER_ADMIN" and int(row["active"]) == 1
        assert row["password_hash"].startswith("$argon2id$")
        # Provisioning is one-time. A later owner password change must survive
        # subsequent startups instead of being overwritten by the release patch.
        change_password_by_verified_phone("OWNER_SETUP_REQUIRED", "ChangedPass!2026")
        second = provision_release_owner_account()
        assert second["provisioned"] is False
        logged = login("OWNER_SETUP_REQUIRED", "ChangedPass!2026")
        assert logged["token"] and logged["security_setup_required"] is True
    ''')
    env = os.environ.copy()
    env.update({
        "CAMPUSFACE_DB_MODE": "sqlite",
        "CAMPUSFACE_DATA_ROOT": str(tmp_path / "runtime"),
        "PYTHONPATH": str(ROOT),
    })
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=30)

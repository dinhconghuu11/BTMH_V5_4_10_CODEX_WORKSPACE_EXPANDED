from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")
GUARD = (ROOT / "scripts" / "postgres_guard.py").read_text(encoding="utf-8")
START = (ROOT / "START_CAMPUSFACE.bat").read_text(encoding="utf-8")
SETUP = (ROOT / "SETUP_POSTGRESQL_WINDOWS.bat").read_text(encoding="utf-8")
REPAIR = (ROOT / "scripts" / "repair_postgres_windows_487.ps1").read_text(encoding="utf-8-sig")


def test_account_profile_upgrade_is_idempotent_without_expected_ddl_errors():
    assert "information_schema.columns" in AUTH
    assert "PRAGMA table_info(account_profiles)" in AUTH
    assert "existing_columns" in AUTH
    assert 'except Exception:\n            pass\n    # Seed only missing defaults' not in AUTH


def test_private_postgres_uses_conservative_windows_memory_settings():
    assert '"-c", "shared_buffers=32MB"' in GUARD
    assert '"-c", "max_connections=50"' in GUARD
    assert '"-c", "huge_pages=off"' in GUARD


def test_windows_487_has_explicit_detection_and_special_recovery_path():
    assert 'EXIT_WINDOWS_ASLR_487 = 87' in GUARD
    assert '"could not reserve shared memory region"' in GUARD
    assert '"error code 487"' in GUARD
    assert ':pg_win487' in START
    assert 'repair_postgres_windows_487.bat' in START
    assert 'if "%RC%"=="87"' in SETUP


def test_487_repair_changes_only_bottomup_aslr_for_private_postgres_binaries():
    assert 'Set-ProcessMitigation -Name $Postgres -Disable BottomUp' in REPAIR
    assert 'Set-ProcessMitigation -Name $PgCtl -Disable BottomUp' in REPAIR
    assert 'DEP/CFG and other Windows exploit protections were not changed' in REPAIR


def test_stale_postmaster_pid_rejects_recycled_non_postgres_pid():
    assert 'def windows_process_image' in GUARD
    assert 'def pid_is_postgres' in GUARD
    assert 'image == "postgres.exe"' in GUARD

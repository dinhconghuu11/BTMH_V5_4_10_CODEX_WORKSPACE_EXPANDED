from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = (ROOT / "module_app" / "db.py").read_text(encoding="utf-8")


def test_runtime_settings_insert_does_not_request_missing_id_column():
    assert '_POSTGRES_INSERTS_WITHOUT_ID = {"runtime_settings"}' in DB
    assert 'table_name not in _POSTGRES_INSERTS_WITHOUT_ID' in DB


def test_owner_provision_still_uses_runtime_setting_marker():
    auth = (ROOT / "module_app" / "auth.py").read_text(encoding="utf-8")
    assert '_setting_set(_RELEASE_OWNER_PROVISION_KEY, "1")' in auth

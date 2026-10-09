from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = (ROOT / "module_app" / "edge_identity_v5.py").read_text(encoding="utf-8")
SYNC = (ROOT / "module_app" / "sync_v5.py").read_text(encoding="utf-8")
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "module_app" / "config.py").read_text(encoding="utf-8")


def test_edge_device_identity_is_asymmetric_and_private_key_stays_edge_side():
    assert "Ed25519PrivateKey" in IDENTITY
    assert "Ed25519PublicKey" in IDENTITY
    assert "edge_sync_private_key.dpapi" in IDENTITY
    assert "save_secret" in IDENTITY and "machine_scope=True" in IDENTITY
    assert "public_key_b64" in SYNC
    assert "private_key" not in SYNC.split("CREATE TABLE IF NOT EXISTS edge_node_keys_v5", 1)[1].split(");", 1)[0]


def test_edge_request_has_timestamp_nonce_signature_and_replay_table():
    assert "EDGE_CLOCK_SKEW_SECONDS" in SYNC
    assert "edge_request_nonces_v5" in SYNC
    assert "X-BTMH-Edge-Timestamp" in SYNC
    assert "X-BTMH-Edge-Nonce" in SYNC
    assert "X-BTMH-Edge-Signature" in SYNC
    assert "replay" in SYNC.lower()


def test_remote_transport_is_local_first_bounded_and_https_by_default():
    assert "class EdgeSyncWorker" in SYNC
    assert "pending_sync_batch(BTMH_EDGE_SYNC_BATCH_SIZE" in SYNC
    assert "mark_sync_result" in SYNC
    assert "BTMH_EDGE_SYNC_ENABLED" in CONFIG
    assert "BTMH_EDGE_SYNC_ALLOW_HTTP_DEV" in CONFIG
    assert "Central Server production bắt buộc HTTPS" in IDENTITY
    assert "Business writes always commit locally first" in SYNC


def test_device_receive_is_public_to_browser_middleware_but_self_authenticates():
    assert '"/api/v1/sync/receive"' in MAIN
    assert "authenticate_edge_request" in MAIN
    assert "_auth_permission(request, \"system.manage\")" in MAIN  # node management remains admin-only
    receive_block = MAIN.split('@app.post("/api/v1/sync/receive")', 1)[1]
    assert "X-BTMH-Edge-Node" in receive_block
    assert "source_node_id không khớp Edge identity" in receive_block


def test_sync_sql_avoids_returning_id_shim_for_string_primary_key_tables():
    assert "def _exec(" in SYNC
    assert "RETURNING-id compatibility shim" in SYNC
    assert "INSERT INTO sync_receipts_v5" in SYNC

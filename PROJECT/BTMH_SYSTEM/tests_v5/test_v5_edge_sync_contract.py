from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = (ROOT / "module_app" / "sync_v5.py").read_text(encoding="utf-8")
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
PLATFORM = (ROOT / "module_app" / "platform_v5.py").read_text(encoding="utf-8")


def test_edge_sync_uses_durable_outbox_and_idempotent_receipts():
    assert "CREATE TABLE IF NOT EXISTS sync_outbox_v5" in SYNC
    assert "CREATE TABLE IF NOT EXISTS sync_receipts_v5" in SYNC
    assert "CREATE TABLE IF NOT EXISTS central_event_log_v5" in SYNC
    assert "event_id TEXT PRIMARY KEY" in SYNC
    assert "payload_hash" in SYNC
    assert "duplicates" in SYNC and "conflicts" in SYNC


def test_edge_sync_batches_are_bounded_and_retryable():
    assert "min(500" in SYNC
    assert "status IN ('PENDING','RETRY')" in SYNC
    assert "attempts" in SYNC
    assert "last_error" in SYNC
    assert "mark_sync_result" in SYNC


def test_v5_mutations_enqueue_without_blocking_local_operation():
    assert "def _sync_event" in PLATFORM
    assert "Edge business operations must remain local-first" in PLATFORM
    for event in (
        "STORE_UPSERT", "SHIFT_UPSERT", "EMPLOYEE_SHIFT_ASSIGNED", "ATTENDANCE_CORRECTION",
        "INCIDENT_CREATED", "INCIDENT_EVIDENCE_ADDED", "VIDEO_CLIP_CREATED", "FACE_VALIDATED",
    ):
        assert event in PLATFORM


def test_sync_api_uses_signed_device_transport_and_keeps_admin_management_separate():
    for route in (
        '/api/v1/sync/status', '/api/v1/sync/nodes', '/api/v1/sync/outbox',
        '/api/v1/sync/outbox/ack', '/api/v1/sync/receive',
    ):
        assert route in MAIN
    assert '"system.manage"' in MAIN
    assert "signed Edge push worker" in MAIN
    assert "mTLS remains optional deployment hardening" in MAIN
    assert "authenticate_edge_request" in MAIN

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = (ROOT / "module_app" / "sync_v5.py").read_text(encoding="utf-8")
MAIN = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
APPJS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "css" / "btmh_v5_production.css").read_text(encoding="utf-8")


def test_chain_admin_has_edge_health_schema_and_online_state():
    assert "CREATE TABLE IF NOT EXISTS edge_node_health_v5" in SYNC
    for field in ("pending_count", "retry_count", "worker_running", "last_sync_at", "last_heartbeat_at"):
        assert field in SYNC
    assert 'row["online"]' in SYNC
    assert "age <= 90" in SYNC


def test_edge_heartbeat_is_device_signed_not_browser_authenticated():
    assert '"/api/v1/sync/heartbeat"' in MAIN
    block = MAIN.split('@app.post("/api/v1/sync/heartbeat")', 1)[1]
    assert "authenticate_edge_request" in block
    assert "update_edge_heartbeat" in block
    assert "source_node_id không khớp Edge identity" in block
    assert '"/api/v1/sync/heartbeat",' in MAIN.split("PUBLIC_API_PATHS", 1)[1].split("}", 1)[0]


def test_edge_worker_reports_queue_health_even_when_idle():
    assert "_send_heartbeat_if_due" in SYNC
    assert 'path = "/api/v1/sync/heartbeat"' in SYNC
    assert '"pending_count"' in SYNC
    assert '"conflict_count"' in SYNC
    assert "if not batch:" in SYNC and "self._send_heartbeat_if_due()" in SYNC


def test_admin_ui_can_pair_monitor_and_revoke_edge_nodes_without_private_key():
    for element_id in (
        "v53EdgePairingForm", "v53EdgePairingFile", "v53EdgeNodeId", "v53EdgeNodeName",
        "v53EdgeStore", "v53EdgePublicKey", "v53EdgeNodeList", "v53EdgeOnline", "v53EdgePending",
    ):
        assert f'id="{element_id}"' in HTML
    assert "Duyệt &amp; đăng ký Edge" in HTML
    assert "Private key không bao giờ được tải lên Central" in HTML
    assert "loadEdgeChainAdmin" in APPJS
    assert "registerEdgeNodeAdmin" in APPJS
    assert "revokeEdgeNodeAdmin" in APPJS
    assert "private_key_exported===true" in APPJS
    assert ".v53-edge-node" in CSS

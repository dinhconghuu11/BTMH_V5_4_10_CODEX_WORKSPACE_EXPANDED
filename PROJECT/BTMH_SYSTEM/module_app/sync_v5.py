from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import (
    APP_VERSION,
    BTMH_CENTRAL_URL,
    BTMH_EDGE_NODE_ID,
    BTMH_EDGE_NODE_NAME,
    BTMH_EDGE_STORE_ID,
    BTMH_EDGE_SYNC_ALLOW_HTTP_DEV,
    BTMH_EDGE_SYNC_BATCH_SIZE,
    BTMH_EDGE_SYNC_ENABLED,
    BTMH_EDGE_SYNC_INTERVAL_SEC,
)
from .db import connection, fetchall, fetchone, utc_now
from .edge_identity_v5 import (
    EDGE_CLOCK_SKEW_SECONDS,
    EdgeIdentityError,
    load_edge_private_key,
    sign_request,
    validate_central_url,
    validate_public_key,
    verify_request_signature,
)


class EdgeAuthError(RuntimeError):
    pass


def _exec(sql: str, params: tuple | list = ()) -> int:
    """Execute SQL without db.execute()'s PostgreSQL RETURNING-id compatibility shim.

    Sync tables deliberately use string/composite primary keys and have no numeric id.
    Calling the generic helper would append `RETURNING id` to PostgreSQL INSERTs.
    """
    with connection() as conn:
        cur = conn.execute(sql, tuple(params))
        return int(getattr(cur, "rowcount", 0) or 0)


def ensure_sync_v5_schema() -> None:
    schema = """
    CREATE TABLE IF NOT EXISTS edge_nodes_v5 (
        node_id TEXT PRIMARY KEY,
        store_id INTEGER,
        node_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        last_seen_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS edge_node_keys_v5 (
        node_id TEXT PRIMARY KEY,
        public_key_b64 TEXT NOT NULL,
        key_fingerprint TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_edge_node_keys_fingerprint_v5 ON edge_node_keys_v5(key_fingerprint);
    CREATE TABLE IF NOT EXISTS edge_request_nonces_v5 (
        nonce TEXT PRIMARY KEY,
        node_id TEXT NOT NULL,
        seen_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_edge_nonce_seen_v5 ON edge_request_nonces_v5(seen_at);
    CREATE TABLE IF NOT EXISTS sync_outbox_v5 (
        event_id TEXT PRIMARY KEY,
        store_id INTEGER,
        event_type TEXT NOT NULL,
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT NOT NULL DEFAULT '',
        available_at TEXT NOT NULL,
        sent_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sync_outbox_v5_status ON sync_outbox_v5(status,available_at,created_at);
    CREATE INDEX IF NOT EXISTS idx_sync_outbox_v5_store ON sync_outbox_v5(store_id,status,created_at);
    CREATE TABLE IF NOT EXISTS sync_receipts_v5 (
        event_id TEXT PRIMARY KEY,
        source_node_id TEXT NOT NULL,
        payload_hash TEXT NOT NULL,
        received_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS central_event_log_v5 (
        event_id TEXT PRIMARY KEY,
        source_node_id TEXT NOT NULL,
        store_id INTEGER,
        event_type TEXT NOT NULL,
        aggregate_type TEXT NOT NULL,
        aggregate_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        received_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_central_event_v5_store ON central_event_log_v5(store_id,received_at);
    CREATE TABLE IF NOT EXISTS edge_node_health_v5 (
        node_id TEXT PRIMARY KEY,
        store_id INTEGER,
        app_version TEXT NOT NULL DEFAULT '',
        pending_count INTEGER NOT NULL DEFAULT 0,
        retry_count INTEGER NOT NULL DEFAULT 0,
        conflict_count INTEGER NOT NULL DEFAULT 0,
        worker_running INTEGER NOT NULL DEFAULT 0,
        worker_last_success_at TEXT,
        worker_last_error TEXT NOT NULL DEFAULT '',
        last_sync_at TEXT,
        last_heartbeat_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_edge_health_store_v5 ON edge_node_health_v5(store_id,last_heartbeat_at);
    """
    with connection() as conn:
        conn.executescript(schema)


def _json(payload: Any) -> str:
    return json.dumps(payload if payload is not None else {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def _event_hash(event: dict[str, Any]) -> str:
    stable = {
        "event_id": str(event.get("event_id") or ""),
        "store_id": event.get("store_id"),
        "event_type": str(event.get("event_type") or ""),
        "aggregate_type": str(event.get("aggregate_type") or ""),
        "aggregate_id": str(event.get("aggregate_id") or ""),
        "payload": event.get("payload") if isinstance(event.get("payload"), (dict, list)) else event.get("payload_json") or {},
    }
    return hashlib.sha256(_json(stable).encode("utf-8")).hexdigest()


def register_edge_node(node_id: str, node_name: str, store_id: int | None = None, public_key_b64: str = "") -> dict:
    ensure_sync_v5_schema()
    nid = str(node_id or "").strip()
    name = str(node_name or "").strip()
    if not nid or not name:
        raise ValueError("node_id và node_name là bắt buộc")
    now = utc_now()
    existing = fetchone("SELECT node_id FROM edge_nodes_v5 WHERE node_id=?", (nid,))
    if existing:
        _exec(
            "UPDATE edge_nodes_v5 SET node_name=?,store_id=?,status='ACTIVE',updated_at=? WHERE node_id=?",
            (name, int(store_id or 0) or None, now, nid),
        )
    else:
        _exec(
            "INSERT INTO edge_nodes_v5(node_id,store_id,node_name,status,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (nid, int(store_id or 0) or None, name, "ACTIVE", None, now, now),
        )
    key_info = None
    if str(public_key_b64 or "").strip():
        try:
            key_info = validate_public_key(public_key_b64)
        except EdgeIdentityError as exc:
            raise ValueError(str(exc)) from exc
        key_row = fetchone("SELECT node_id FROM edge_node_keys_v5 WHERE node_id=?", (nid,))
        if key_row:
            _exec(
                "UPDATE edge_node_keys_v5 SET public_key_b64=?,key_fingerprint=?,status='ACTIVE',updated_at=?,revoked_at=NULL WHERE node_id=?",
                (key_info["public_key_b64"], key_info["fingerprint"], now, nid),
            )
        else:
            _exec(
                "INSERT INTO edge_node_keys_v5(node_id,public_key_b64,key_fingerprint,status,created_at,updated_at,revoked_at) VALUES(?,?,?,?,?,?,?)",
                (nid, key_info["public_key_b64"], key_info["fingerprint"], "ACTIVE", now, now, None),
            )
    row = fetchone(
        """SELECT n.*,k.key_fingerprint,k.status AS key_status,k.revoked_at
           FROM edge_nodes_v5 n LEFT JOIN edge_node_keys_v5 k ON k.node_id=n.node_id WHERE n.node_id=?""",
        (nid,),
    ) or {}
    row.pop("public_key_b64", None)
    return row


def _parse_utc(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def list_edge_nodes() -> list[dict]:
    ensure_sync_v5_schema()
    rows = fetchall(
        """SELECT n.node_id,n.store_id,n.node_name,n.status,n.last_seen_at,n.created_at,n.updated_at,
                  k.key_fingerprint,k.status AS key_status,k.revoked_at,
                  h.app_version,h.pending_count,h.retry_count,h.conflict_count,h.worker_running,
                  h.worker_last_success_at,h.worker_last_error,h.last_sync_at,h.last_heartbeat_at
           FROM edge_nodes_v5 n LEFT JOIN edge_node_keys_v5 k ON k.node_id=n.node_id
           LEFT JOIN edge_node_health_v5 h ON h.node_id=n.node_id
           ORDER BY n.node_name,n.node_id"""
    )
    now = datetime.now(timezone.utc)
    for row in rows:
        heartbeat = _parse_utc(row.get("last_heartbeat_at") or row.get("last_seen_at"))
        age = int((now - heartbeat).total_seconds()) if heartbeat else None
        active = str(row.get("status") or "").upper() == "ACTIVE" and str(row.get("key_status") or "").upper() == "ACTIVE"
        row["heartbeat_age_sec"] = age
        row["online"] = bool(active and age is not None and age <= 90)
        row["pending_count"] = int(row.get("pending_count") or 0)
        row["retry_count"] = int(row.get("retry_count") or 0)
        row["conflict_count"] = int(row.get("conflict_count") or 0)
        row["worker_running"] = bool(row.get("worker_running"))
    return rows


def revoke_edge_node(node_id: str) -> dict:
    ensure_sync_v5_schema()
    nid = str(node_id or "").strip()
    if not nid:
        raise ValueError("node_id là bắt buộc")
    if not fetchone("SELECT node_id FROM edge_nodes_v5 WHERE node_id=?", (nid,)):
        raise ValueError("Edge node không tồn tại")
    now = utc_now()
    _exec("UPDATE edge_nodes_v5 SET status='REVOKED',updated_at=? WHERE node_id=?", (now, nid))
    _exec("UPDATE edge_node_keys_v5 SET status='REVOKED',revoked_at=?,updated_at=? WHERE node_id=?", (now, now, nid))
    return fetchone("SELECT * FROM edge_nodes_v5 WHERE node_id=?", (nid,)) or {}


def update_edge_heartbeat(node_id: str, payload: dict[str, Any]) -> dict:
    """Persist operational health reported by an authenticated Edge node.

    The caller must authenticate the signed request before invoking this function.
    Health is advisory/operational data only; it never changes business records.
    """
    ensure_sync_v5_schema()
    nid = str(node_id or "").strip()
    node = fetchone("SELECT node_id,store_id,status FROM edge_nodes_v5 WHERE node_id=?", (nid,))
    if not node or str(node.get("status") or "").upper() != "ACTIVE":
        raise ValueError("Edge node chưa được cấp quyền hoặc đã bị thu hồi")
    configured_store = int(node.get("store_id") or 0)
    reported_store = int(payload.get("store_id") or 0)
    if configured_store and reported_store and configured_store != reported_store:
        raise ValueError("store_id heartbeat không khớp Edge đã đăng ký")
    now = utc_now()
    values = (
        configured_store or reported_store or None,
        str(payload.get("app_version") or "")[:80],
        max(0, int(payload.get("pending_count") or 0)),
        max(0, int(payload.get("retry_count") or 0)),
        max(0, int(payload.get("conflict_count") or 0)),
        1 if bool(payload.get("worker_running")) else 0,
        str(payload.get("worker_last_success_at") or "") or None,
        str(payload.get("worker_last_error") or "")[:1000],
        str(payload.get("last_sync_at") or "") or None,
        now,
        now,
    )
    existing = fetchone("SELECT node_id FROM edge_node_health_v5 WHERE node_id=?", (nid,))
    if existing:
        _exec(
            """UPDATE edge_node_health_v5 SET store_id=?,app_version=?,pending_count=?,retry_count=?,conflict_count=?,
               worker_running=?,worker_last_success_at=?,worker_last_error=?,last_sync_at=?,last_heartbeat_at=?,updated_at=? WHERE node_id=?""",
            (*values, nid),
        )
    else:
        _exec(
            """INSERT INTO edge_node_health_v5(node_id,store_id,app_version,pending_count,retry_count,conflict_count,
               worker_running,worker_last_success_at,worker_last_error,last_sync_at,last_heartbeat_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (nid, *values),
        )
    _exec("UPDATE edge_nodes_v5 SET last_seen_at=?,updated_at=? WHERE node_id=?", (now, now, nid))
    return fetchone("SELECT * FROM edge_node_health_v5 WHERE node_id=?", (nid,)) or {}


def authenticate_edge_request(*, node_id: str, timestamp: str, nonce: str, signature: str, method: str, path: str, body: bytes) -> dict:
    """Authenticate a Central sync request using a per-device Ed25519 public key.

    The timestamp window + one-time nonce prevents replay. Only the public key is
    stored at Central; the Edge private key remains local and is DPAPI-protected.
    """
    ensure_sync_v5_schema()
    nid = str(node_id or "").strip()
    ts_raw = str(timestamp or "").strip()
    nonce_value = str(nonce or "").strip()
    sig = str(signature or "").strip()
    if not nid or not ts_raw or not nonce_value or not sig:
        raise EdgeAuthError("Thiếu thông tin xác thực Edge")
    if len(nonce_value) < 16 or len(nonce_value) > 160:
        raise EdgeAuthError("Nonce Edge không hợp lệ")
    try:
        ts = int(ts_raw)
    except ValueError as exc:
        raise EdgeAuthError("Timestamp Edge không hợp lệ") from exc
    if abs(int(time.time()) - ts) > EDGE_CLOCK_SKEW_SECONDS:
        raise EdgeAuthError("Yêu cầu Edge đã hết hạn hoặc đồng hồ thiết bị bị lệch")
    row = fetchone(
        """SELECT n.node_id,n.store_id,n.node_name,n.status,k.public_key_b64,k.key_fingerprint,k.status AS key_status
           FROM edge_nodes_v5 n JOIN edge_node_keys_v5 k ON k.node_id=n.node_id WHERE n.node_id=?""",
        (nid,),
    )
    if not row or str(row.get("status") or "").upper() != "ACTIVE" or str(row.get("key_status") or "").upper() != "ACTIVE":
        raise EdgeAuthError("Edge node chưa được cấp quyền hoặc đã bị thu hồi")
    if fetchone("SELECT nonce FROM edge_request_nonces_v5 WHERE nonce=?", (nonce_value,)):
        raise EdgeAuthError("Yêu cầu Edge bị phát hiện replay")
    try:
        verify_request_signature(
            str(row.get("public_key_b64") or ""), method=method, path=path, body=body,
            timestamp=ts_raw, nonce=nonce_value, signature=sig,
        )
    except EdgeIdentityError as exc:
        raise EdgeAuthError(str(exc)) from exc
    now = utc_now()
    # The unique nonce primary key makes this race-safe even if two copies arrive together.
    try:
        _exec("INSERT INTO edge_request_nonces_v5(nonce,node_id,seen_at) VALUES(?,?,?)", (nonce_value, nid, now))
    except Exception as exc:
        raise EdgeAuthError("Yêu cầu Edge bị phát hiện replay") from exc
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    _exec("DELETE FROM edge_request_nonces_v5 WHERE seen_at<?", (cutoff,))
    _exec("UPDATE edge_nodes_v5 SET last_seen_at=?,updated_at=? WHERE node_id=?", (now, now, nid))
    return {k: v for k, v in row.items() if k != "public_key_b64"}


def enqueue_sync_event(
    event_type: str,
    aggregate_type: str,
    aggregate_id: str | int,
    payload: dict[str, Any],
    *,
    store_id: int | None = None,
    event_id: str = "",
) -> dict:
    """Append a durable, retryable event without blocking the local business flow."""
    ensure_sync_v5_schema()
    et = str(event_type or "").strip().upper()
    at = str(aggregate_type or "").strip().upper()
    aid = str(aggregate_id or "").strip()
    if not et or not at or not aid:
        raise ValueError("event_type, aggregate_type và aggregate_id là bắt buộc")
    eid = str(event_id or f"SYNC-{uuid.uuid4().hex}")
    now = utc_now()
    existing = fetchone("SELECT * FROM sync_outbox_v5 WHERE event_id=?", (eid,))
    if existing:
        return decorate_outbox(existing)
    _exec(
        """INSERT INTO sync_outbox_v5(event_id,store_id,event_type,aggregate_type,aggregate_id,payload_json,status,attempts,last_error,available_at,sent_at,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (eid, int(store_id or 0) or None, et, at, aid, _json(payload), "PENDING", 0, "", now, None, now, now),
    )
    return decorate_outbox(fetchone("SELECT * FROM sync_outbox_v5 WHERE event_id=?", (eid,)) or {})


def decorate_outbox(row: dict) -> dict:
    out = dict(row or {})
    try:
        out["payload"] = json.loads(out.get("payload_json") or "{}")
    except Exception:
        out["payload"] = {}
    return out


def pending_sync_batch(limit: int = 100, store_id: int | None = None) -> list[dict]:
    ensure_sync_v5_schema()
    lim = max(1, min(500, int(limit)))
    now = utc_now()
    if store_id:
        rows = fetchall(
            "SELECT * FROM sync_outbox_v5 WHERE status IN ('PENDING','RETRY') AND available_at<=? AND store_id=? ORDER BY created_at LIMIT ?",
            (now, int(store_id), lim),
        )
    else:
        rows = fetchall(
            "SELECT * FROM sync_outbox_v5 WHERE status IN ('PENDING','RETRY') AND available_at<=? ORDER BY created_at LIMIT ?",
            (now, lim),
        )
    return [decorate_outbox(x) for x in rows]


def mark_sync_result(event_ids: list[str], *, success: bool, error: str = "") -> int:
    ensure_sync_v5_schema()
    ids = [str(x or "").strip() for x in event_ids if str(x or "").strip()]
    if not ids:
        return 0
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    count = 0
    for eid in ids:
        row = fetchone("SELECT attempts FROM sync_outbox_v5 WHERE event_id=?", (eid,))
        if not row:
            continue
        attempts = int(row.get("attempts") or 0) + 1
        if success:
            _exec(
                "UPDATE sync_outbox_v5 SET status='SENT',attempts=?,last_error='',sent_at=?,available_at=?,updated_at=? WHERE event_id=?",
                (attempts, now, now, now, eid),
            )
        else:
            backoff_sec = min(300, max(5, 5 * (2 ** min(attempts - 1, 6))))
            available_at = (now_dt + timedelta(seconds=backoff_sec)).isoformat()
            _exec(
                "UPDATE sync_outbox_v5 SET status='RETRY',attempts=?,last_error=?,available_at=?,updated_at=? WHERE event_id=?",
                (attempts, str(error or "")[:1000], available_at, now, eid),
            )
        count += 1
    return count


def mark_sync_conflicts(event_ids: list[str], error: str = "Central rejected event_id payload conflict") -> int:
    ensure_sync_v5_schema()
    now = utc_now()
    count = 0
    for eid in [str(x or "").strip() for x in event_ids if str(x or "").strip()]:
        row = fetchone("SELECT attempts FROM sync_outbox_v5 WHERE event_id=?", (eid,))
        if not row:
            continue
        _exec(
            "UPDATE sync_outbox_v5 SET status='CONFLICT',attempts=?,last_error=?,updated_at=? WHERE event_id=?",
            (int(row.get("attempts") or 0) + 1, str(error or "")[:1000], now, eid),
        )
        count += 1
    return count


def receive_sync_batch(source_node_id: str, events: list[dict[str, Any]]) -> dict:
    """Idempotently receive authenticated Edge events on a central node."""
    ensure_sync_v5_schema()
    node_id = str(source_node_id or "").strip()
    if not node_id:
        raise ValueError("source_node_id là bắt buộc")
    node = fetchone("SELECT node_id,store_id,status FROM edge_nodes_v5 WHERE node_id=?", (node_id,))
    if not node or str(node.get("status") or "").upper() != "ACTIVE":
        raise ValueError("Edge node chưa được cấp quyền")
    allowed_store_id = int(node.get("store_id") or 0)
    now = utc_now()
    accepted: list[str] = []
    duplicates: list[str] = []
    conflicts: list[str] = []
    rejected: list[str] = []
    for raw in events[:500]:
        event = dict(raw or {})
        eid = str(event.get("event_id") or "").strip()
        if not eid:
            continue
        event_store_id = int(event.get("store_id") or 0)
        if allowed_store_id and event_store_id and event_store_id != allowed_store_id:
            rejected.append(eid)
            continue
        phash = _event_hash(event)
        receipt = fetchone("SELECT payload_hash FROM sync_receipts_v5 WHERE event_id=?", (eid,))
        if receipt:
            if str(receipt.get("payload_hash") or "") == phash:
                duplicates.append(eid)
            else:
                conflicts.append(eid)
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), (dict, list)) else {}
        _exec(
            """INSERT INTO central_event_log_v5(event_id,source_node_id,store_id,event_type,aggregate_type,aggregate_id,payload_json,received_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                eid, node_id, event_store_id or allowed_store_id or None,
                str(event.get("event_type") or "").upper(), str(event.get("aggregate_type") or "").upper(),
                str(event.get("aggregate_id") or ""), _json(payload), now,
            ),
        )
        _exec(
            "INSERT INTO sync_receipts_v5(event_id,source_node_id,payload_hash,received_at) VALUES(?,?,?,?)",
            (eid, node_id, phash, now),
        )
        accepted.append(eid)
    return {
        "accepted": accepted,
        "duplicates": duplicates,
        "conflicts": conflicts,
        "rejected": rejected,
        "received": len(accepted),
    }


def sync_status() -> dict:
    ensure_sync_v5_schema()
    counts: dict[str, int] = {}
    for row in fetchall("SELECT status,COUNT(*) AS total FROM sync_outbox_v5 GROUP BY status"):
        counts[str(row.get("status") or "UNKNOWN")] = int(row.get("total") or 0)
    return {
        "outbox": counts,
        "pending": int(counts.get("PENDING", 0)) + int(counts.get("RETRY", 0)),
        "sent": int(counts.get("SENT", 0)),
        "conflicts": int(counts.get("CONFLICT", 0)),
        "received": int((fetchone("SELECT COUNT(*) AS total FROM sync_receipts_v5") or {}).get("total") or 0),
        "registered_nodes": int((fetchone("SELECT COUNT(*) AS total FROM edge_nodes_v5") or {}).get("total") or 0),
        "transport": "signed-ed25519-edge-push",
    }


def _transport_event(row: dict) -> dict:
    return {
        "event_id": str(row.get("event_id") or ""),
        "store_id": row.get("store_id"),
        "event_type": str(row.get("event_type") or ""),
        "aggregate_type": str(row.get("aggregate_type") or ""),
        "aggregate_id": str(row.get("aggregate_id") or ""),
        "payload": row.get("payload") if isinstance(row.get("payload"), (dict, list)) else {},
        "created_at": str(row.get("created_at") or ""),
    }


class EdgeSyncWorker:
    """Local-first Edge -> Central delivery worker.

    Business writes always commit locally first. This worker only drains the durable
    outbox. Network/TLS/auth failures therefore cannot stop recognition, recording or
    attendance at the store.
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._private_key_b64 = ""
        self._central_url = ""
        self._last_heartbeat_mono = 0.0
        self._state: dict[str, Any] = {
            "enabled": bool(BTMH_EDGE_SYNC_ENABLED),
            "running": False,
            "last_success_at": "",
            "last_error": "",
            "last_attempt_at": "",
            "last_batch_size": 0,
        }

    def start(self) -> dict:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status()
            if not BTMH_EDGE_SYNC_ENABLED:
                self._state.update({"enabled": False, "running": False, "last_error": ""})
                return self.status()
            if not BTMH_EDGE_NODE_ID:
                self._state.update({"running": False, "last_error": "Thiếu BTMH_EDGE_NODE_ID"})
                return self.status()
            try:
                self._central_url = validate_central_url(BTMH_CENTRAL_URL, allow_http_dev=BTMH_EDGE_SYNC_ALLOW_HTTP_DEV)
                self._private_key_b64 = load_edge_private_key()
            except Exception as exc:
                self._state.update({"running": False, "last_error": str(exc)})
                return self.status()
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="btmh-edge-sync-v5", daemon=True)
            self._thread.start()
            self._state.update({"enabled": True, "running": True, "last_error": ""})
            return self.status()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3.0)
        with self._lock:
            self._state["running"] = False

    def status(self) -> dict:
        with self._lock:
            state = dict(self._state)
        state.update({
            "node_id": BTMH_EDGE_NODE_ID,
            "node_name": BTMH_EDGE_NODE_NAME,
            "store_id": BTMH_EDGE_STORE_ID or None,
            "central_url_configured": bool(BTMH_CENTRAL_URL),
            "tls_required": not BTMH_EDGE_SYNC_ALLOW_HTTP_DEV,
            "auth": "Ed25519 signed request + anti-replay nonce",
        })
        return state

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                sent = self.run_once()
                wait = 0.25 if sent else float(BTMH_EDGE_SYNC_INTERVAL_SEC)
            except Exception as exc:
                with self._lock:
                    self._state["last_error"] = str(exc)[:1000]
                wait = float(BTMH_EDGE_SYNC_INTERVAL_SEC)
            self._stop.wait(wait)
        with self._lock:
            self._state["running"] = False

    def run_once(self) -> int:
        if not BTMH_EDGE_SYNC_ENABLED:
            return 0
        batch = pending_sync_batch(BTMH_EDGE_SYNC_BATCH_SIZE)
        if not batch:
            self._send_heartbeat_if_due()
            return 0
        event_ids = [str(x.get("event_id") or "") for x in batch if x.get("event_id")]
        payload = {"source_node_id": BTMH_EDGE_NODE_ID, "events": [_transport_event(x) for x in batch]}
        body = _json(payload).encode("utf-8")
        path = "/api/v1/sync/receive"
        signed = sign_request(self._private_key_b64, method="POST", path=path, body=body)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BTMH-Edge-Sync/5",
            "X-BTMH-Edge-Node": BTMH_EDGE_NODE_ID,
            "X-BTMH-Edge-Timestamp": signed["timestamp"],
            "X-BTMH-Edge-Nonce": signed["nonce"],
            "X-BTMH-Edge-Signature": signed["signature"],
        }
        now = utc_now()
        with self._lock:
            self._state.update({"last_attempt_at": now, "last_batch_size": len(event_ids)})
        try:
            req = urllib.request.Request(self._central_url + path, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                if int(getattr(resp, "status", 200)) >= 300:
                    raise RuntimeError(f"Central sync HTTP {getattr(resp, 'status', 0)}")
            result = json.loads(raw.decode("utf-8") or "{}")
            acked = set(result.get("accepted") or []) | set(result.get("duplicates") or [])
            conflicts = set(result.get("conflicts") or []) | set(result.get("rejected") or [])
            if acked:
                mark_sync_result(sorted(acked), success=True)
            if conflicts:
                mark_sync_conflicts(sorted(conflicts), "Central rejected sync event")
            remaining = [eid for eid in event_ids if eid not in acked and eid not in conflicts]
            if remaining:
                mark_sync_result(remaining, success=False, error="Central response did not acknowledge event")
            with self._lock:
                self._state.update({"last_success_at": utc_now(), "last_error": ""})
            self._send_heartbeat_if_due(force=True)
            return len(acked)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")[:500]
            except Exception:
                pass
            error = f"Central HTTP {exc.code}: {detail or exc.reason}"
            mark_sync_result(event_ids, success=False, error=error)
            with self._lock:
                self._state["last_error"] = error
            return 0
        except Exception as exc:
            error = f"Central unavailable: {exc}"
            mark_sync_result(event_ids, success=False, error=error)
            with self._lock:
                self._state["last_error"] = error[:1000]
            return 0

    def _send_heartbeat_if_due(self, force: bool = False) -> bool:
        now_mono = time.monotonic()
        interval = max(20.0, min(60.0, float(BTMH_EDGE_SYNC_INTERVAL_SEC) * 4.0))
        if not force and (now_mono - self._last_heartbeat_mono) < interval:
            return False
        if not self._central_url or not self._private_key_b64:
            return False
        queue = sync_status()
        with self._lock:
            state = dict(self._state)
        payload = {
            "source_node_id": BTMH_EDGE_NODE_ID,
            "store_id": BTMH_EDGE_STORE_ID or None,
            "app_version": APP_VERSION,
            "pending_count": int(queue.get("pending") or 0),
            "retry_count": int((queue.get("outbox") or {}).get("RETRY") or 0),
            "conflict_count": int(queue.get("conflicts") or 0),
            "worker_running": bool(state.get("running")),
            "worker_last_success_at": str(state.get("last_success_at") or ""),
            "worker_last_error": str(state.get("last_error") or "")[:1000],
            "last_sync_at": str(state.get("last_success_at") or ""),
        }
        body = _json(payload).encode("utf-8")
        path = "/api/v1/sync/heartbeat"
        signed = sign_request(self._private_key_b64, method="POST", path=path, body=body)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BTMH-Edge-Sync/5",
            "X-BTMH-Edge-Node": BTMH_EDGE_NODE_ID,
            "X-BTMH-Edge-Timestamp": signed["timestamp"],
            "X-BTMH-Edge-Nonce": signed["nonce"],
            "X-BTMH-Edge-Signature": signed["signature"],
        }
        try:
            req = urllib.request.Request(self._central_url + path, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=8) as resp:
                if int(getattr(resp, "status", 200)) >= 300:
                    raise RuntimeError(f"Central heartbeat HTTP {getattr(resp, 'status', 0)}")
                resp.read()
            self._last_heartbeat_mono = now_mono
            return True
        except Exception as exc:
            with self._lock:
                self._state["last_error"] = f"Central heartbeat unavailable: {exc}"[:1000]
            return False


EDGE_SYNC_WORKER = EdgeSyncWorker()

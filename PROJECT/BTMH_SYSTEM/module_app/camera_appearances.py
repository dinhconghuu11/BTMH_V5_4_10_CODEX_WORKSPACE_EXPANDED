"""Camera-local daily appearance references; never a person/visit counter.

One existing recognition_events row follows ANALYZING -> classification. Import
does not open a DB. Only a frame bound by the backend can use the writer hook;
unbound legacy event writers retain their existing behavior.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import db
from .demo_context import ATTRIBUTION_FIELDS, _columns, _positive_id, _safe_name, _snapshot

_FRAME = ContextVar("btmh_appearance_frame", default=None)
_SCHEMA_LOCK = threading.RLock()
_COLUMNS = {"appearance_id": "TEXT", "business_date": "TEXT", "daily_sequence": "BIGINT"}


def ensure_appearance_schema():
    """Idempotent additive migration, no attribution/numbering of legacy rows."""
    with _SCHEMA_LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100073)")
        columns = _columns(conn, "recognition_events")
        if not columns:
            return  # The existing database schema owns entity creation.
        for column, declaration in _COLUMNS.items():
            if column not in columns:
                optional = " IF NOT EXISTS" if conn.mode == "postgres" else ""
                conn.execute(f"ALTER TABLE recognition_events ADD COLUMN{optional} {column} {declaration}")
        conn.execute("CREATE TABLE IF NOT EXISTS camera_appearance_counters("
                     "camera_id BIGINT NOT NULL,business_date TEXT NOT NULL,last_sequence BIGINT NOT NULL,"
                     "PRIMARY KEY(camera_id,business_date),CHECK(last_sequence>0))")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_recognition_appearance_id "
                     "ON recognition_events(appearance_id) WHERE appearance_id IS NOT NULL")
        if "camera_id" in columns:
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_recognition_camera_day_sequence "
                         "ON recognition_events(camera_id,business_date,daily_sequence) "
                         "WHERE daily_sequence IS NOT NULL")


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("APPEARANCE_REQUIRES_AWARE_TIMESTAMP")
    return value.astimezone(timezone.utc)


def _track_id(value):
    if isinstance(value, bool):
        return None
    if hasattr(value, "id"):
        value = value.id
    # Existing WalkBy writers use camera-session:track, sometimes :gN:track.
    token = str(value).rsplit(":", 1)[-1]
    if not token.isdigit():
        return None
    return int(token)


def _bbox(value, width, height):
    try:
        x, y, w, h = (float(v) for v in value)
        width, height = float(width), float(height)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(v) for v in (x, y, w, h, width, height)) or min(w, h, width, height) <= 0:
        return None
    # Keep geometry within the actual source image, rejecting wholly offscreen boxes.
    right, bottom = min(width, x + w), min(height, y + h)
    x, y = max(0., x), max(0., y)
    if right <= x or bottom <= y:
        return None
    return x / width, y / height, (right - x) / width, (bottom - y) / height


def _spatial_match(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    intersection = max(0., min(ax + aw, bx + bw) - max(ax, bx)) * max(0., min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - intersection
    iou = intersection / union if union else 0.
    size_ratio = min(aw * ah, bw * bh) / max(aw * ah, bw * bh)
    distance = math.hypot(ax + aw / 2 - bx - bw / 2, ay + ah / 2 - by - bh / 2)
    # Conservative single-camera short-loss continuity. Missing geometry never matches.
    return iou >= .35 and size_ratio >= .65 and distance <= .06


@dataclass
class _Appearance:
    values: dict
    owner: str
    bbox: tuple
    last_seen: float
    last_write: float
    aliases: set = field(default_factory=set)
    classification: tuple = ("ANALYZING", None, False)


class AppearanceManager:
    def __init__(self, *, max_cache=4096, reacquire_sec=1.5, track_idle_sec=3.0, touch_sec=1.0):
        self.max_cache = max(1, int(max_cache))
        self.reacquire_sec = min(3., max(0., float(reacquire_sec)))
        self.track_idle_sec = max(self.reacquire_sec, float(track_idle_sec))
        self.touch_sec = max(.5, float(touch_sec))
        self._lock = threading.RLock()
        self._records = {}
        self._aliases = {}

    @contextmanager
    def frame(self, camera_context, owner_nonce, observed_at):
        frame = AppearanceFrame(self, camera_context, owner_nonce, _utc(observed_at))
        token = _FRAME.set(frame)
        try:
            yield frame
        finally:
            frame.active = False
            _FRAME.reset(token)

    def _drop(self, record):
        self._records.pop(record.values["appearance_id"], None)
        for key in record.aliases:
            if self._aliases.get(key) is record:
                self._aliases.pop(key, None)

    def _prune(self, stamp):
        for record in tuple(self._records.values()):
            if stamp - record.last_seen > self.track_idle_sec:
                self._drop(record)
        excess = len(self._records) - self.max_cache
        if excess > 0:
            for record in sorted(self._records.values(), key=lambda item: item.last_seen)[:excess]:
                self._drop(record)

    def _bind(self, record, key):
        old = self._aliases.get(key)
        if old and old is not record:
            old.aliases.discard(key)
        self._aliases[key] = record
        record.aliases.add(key)
        # Track-ID churn cannot create an unbounded alias set for one appearance.
        while len(record.aliases) > 8:
            old_key = next(item for item in record.aliases if item != key)
            record.aliases.remove(old_key)
            if self._aliases.get(old_key) is record:
                self._aliases.pop(old_key, None)

    def _allocate(self, frame, tid, bbox):
        stamp = frame.observed_at.isoformat()
        appearance_id = uuid.uuid4().hex
        detail = {"first_seen": stamp, "last_seen": stamp, "appearance_timezone": frame.timezone_name,
                  "bbox_norm": list(bbox), "appearance_policy": "CAMERA_DAILY_APPEARANCE_V1"}
        with db.connection() as conn:
            # The counter write locks this camera/day row on PostgreSQL and serializes
            # SQLite writes. Allocation and ANALYZING insertion commit or roll back together.
            counter = conn.execute("INSERT INTO camera_appearance_counters(camera_id,business_date,last_sequence) "
                                   "VALUES(?,?,1) ON CONFLICT(camera_id,business_date) "
                                   "DO UPDATE SET last_sequence=camera_appearance_counters.last_sequence+1 "
                                   "RETURNING last_sequence", (frame.camera_id, frame.business_date)).fetchone()
            sequence = int(dict(counter)["last_sequence"])
            columns = ("track_id,camera_source,direction,status,event_at,detail_json,created_at,"
                       "appearance_id,business_date,daily_sequence," + ",".join(ATTRIBUTION_FIELDS))
            values = (str(tid), frame.camera_source, "OBSERVATION", "ANALYZING", stamp, json.dumps(detail), stamp,
                      appearance_id, frame.business_date, sequence,
                      *(frame.context.get(key) for key in ATTRIBUTION_FIELDS))
            sql = f"INSERT INTO recognition_events({columns}) VALUES({','.join('?' for _ in values)})"
            cur = conn.execute(sql + (" RETURNING id" if conn.mode == "postgres" else ""), values)
            event_id = int(dict(cur.fetchone())["id"]) if conn.mode == "postgres" else int(cur.lastrowid)
        values = {"id": event_id, "event_id": event_id, "event_at": stamp, "appearance_id": appearance_id,
                  "business_date": frame.business_date, "daily_sequence": sequence,
                  "camera_source": frame.camera_source, **frame.context}
        record = _Appearance(values, frame.owner, bbox, frame.stamp, frame.stamp)
        self._records[appearance_id] = record
        return record

    def _touch(self, record, frame, bbox):
        record.bbox, record.last_seen = bbox, max(record.last_seen, frame.stamp)
        if frame.stamp - record.last_write < self.touch_sec:
            return
        with db.connection() as conn:
            row = conn.execute("SELECT detail_json FROM recognition_events WHERE id=? AND appearance_id=?",
                               (record.values["event_id"], record.values["appearance_id"])).fetchone()
            if row:
                detail = db._safe_detail(dict(row).get("detail_json"))
                detail.update(last_seen=frame.observed_at.isoformat(), bbox_norm=list(bbox))
                conn.execute("UPDATE recognition_events SET detail_json=? WHERE id=? AND appearance_id=?",
                             (json.dumps(detail, ensure_ascii=False), record.values["event_id"], record.values["appearance_id"]))
        record.last_write = frame.stamp


class AppearanceFrame:
    def __init__(self, manager, context, owner, observed_at):
        self.manager = manager
        self.context = _snapshot(context)
        self.camera_id = self.context["camera_id"]
        self.owner = str(owner or "")[:160]
        self.observed_at, self.stamp = observed_at, observed_at.timestamp()
        self.timezone_name = str((context or {}).get("timezone_name") or "Asia/Ho_Chi_Minh")
        try:
            zone = ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            zone, self.timezone_name = ZoneInfo("Asia/Ho_Chi_Minh"), "Asia/Ho_Chi_Minh"
        self.business_date = observed_at.astimezone(zone).date().isoformat()
        self.camera_source = _safe_name(self.context.get("camera_name") or f"camera-{self.camera_id}")
        self.mapping = {}
        self.active = True

    def key(self, tid):
        return self.camera_id, self.business_date, self.owner, tid

    def prepare(self, assignments, width, height, now=None):
        """Accept (Track, FaceObservation) or (track_id, bbox_xywh); fresh observations only."""
        self.mapping = {}
        if not self.active or not self.camera_id or not self.owner:
            return {}
        boxes = {}
        for track, observation in assignments:
            tid = _track_id(track)
            box = _bbox(getattr(observation, "bbox", observation), width, height)
            if tid is not None and box is not None:
                boxes[tid] = box
        with self.manager._lock:
            self.manager._prune(self.stamp)
            matched, used = {}, set()
            for tid, box in boxes.items():
                record = self.manager._aliases.get(self.key(tid))
                if (record and record.values["appearance_id"] not in used
                        and 0 <= self.stamp - record.last_seen <= self.manager.track_idle_sec):
                    matched[tid] = record
                    used.add(record.values["appearance_id"])
            candidates = [record for record in self.manager._records.values()
                          if record.values["camera_id"] == self.camera_id and record.values["business_date"] == self.business_date
                          and record.owner == self.owner and record.values["appearance_id"] not in used
                          and 0 <= self.stamp - record.last_seen <= self.manager.reacquire_sec]
            # Reacquire only mutually unique possible matches; do not guess in crowds.
            possibilities = {tid: [record for record in candidates if _spatial_match(box, record.bbox)]
                             for tid, box in boxes.items() if tid not in matched}
            for tid, records in possibilities.items():
                if len(records) == 1 and sum(records[0] in other for other in possibilities.values()) == 1:
                    matched[tid] = records[0]
            for tid, box in boxes.items():
                record = matched.get(tid)
                if record is None:
                    record = self.manager._allocate(self, tid, box)
                else:
                    self.manager._touch(record, self, box)
                self.manager._bind(record, self.key(tid))
                self.mapping[tid] = record
            self.manager._prune(self.stamp)
            return {tid: dict(record.values) for tid, record in self.mapping.items()}

    def annotate(self, result):
        """Attach references to display tracks; never allocate from detector-miss geometry."""
        with self.manager._lock:
            fresh_ids = {record.values["appearance_id"] for record in self.mapping.values()}
            for track in result.get("tracks") or []:
                tid = _track_id(track.get("track_id"))
                record = self.mapping.get(tid) or self.manager._aliases.get(self.key(tid))
                if record and tid not in self.mapping and record.values["appearance_id"] in fresh_ids:
                    # A reacquired fresh tracker replaces its old detector-grace
                    # alias; do not display one appearance on two boxes at once.
                    record = None
                if record and 0 <= self.stamp - record.last_seen <= self.manager.track_idle_sec:
                    track.update({key: record.values[key] for key in ("appearance_id", "business_date", "daily_sequence", "event_id")})
                # Already accepted engine state may survive local midnight. The
                # new day's row still needs that outcome even when WalkBy does
                # not emit another classification. Never re-decide FaceID/PAD,
                # allocate from grace boxes, or write each frame's cached state.
                if (not self.active or tid not in self.mapping or track.get("stale") or track.get("tracking_grace")
                        or track.get("observation_age_ms", 0) != 0):
                    continue
                live = track.get("liveness") or {}
                employee = _positive_id(track.get("student_id") or (track.get("student") or {}).get("id"))
                state = None
                if track.get("spoof_blocked"):
                    state = ("SPOOF_BLOCKED", None, False)
                elif track.get("recognized") and employee and str(live.get("status") or "").upper() == "PASS":
                    state = ("RECOGNIZED", employee, True)
                elif (track.get("unknown") and str(track.get("status") or "").upper() == "UNREGISTERED"
                      and str(live.get("status") or "").upper() == "PASS"):
                    state = ("UNREGISTERED", None, False)
                if state is None or state == record.classification:
                    continue
                if record.classification[0] == "SPOOF_BLOCKED" and state[0] == "UNREGISTERED":
                    continue
                persist_classification(tid, state[1], state[0], track.get("confidence") or 0., live.get("score") or 0.,
                                       state[2], {"liveness": live, "reason": "ACCEPTED_ENGINE_STATE", "bbox_norm": list(record.bbox)},
                                       self.camera_source)
        return result


APPEARANCES = AppearanceManager()


def persist_classification(track_id, student_id, status, confidence, liveness_score,
                           anti_spoof_passed, detail, camera_source):
    """Same-event writer hook. None means no backend binding; use the legacy writer."""
    frame = _FRAME.get()
    tid = _track_id(track_id)
    if frame is None or not frame.active or tid not in frame.mapping:
        return None
    record = frame.mapping[tid]
    values = record.values
    status = str(status or "ANALYZING").upper()
    student_id = _positive_id(student_id)
    with frame.manager._lock, db.connection() as conn:
        suffix = " FOR UPDATE" if conn.mode == "postgres" else ""
        row = conn.execute("SELECT * FROM recognition_events WHERE id=? AND appearance_id=?" + suffix,
                           (values["event_id"], values["appearance_id"])).fetchone()
        if row is None:
            raise RuntimeError("APPEARANCE_EVENT_MISSING")
        row = dict(row)
        # Keep the existing security episode rule: an UNKNOWN branch cannot
        # erase a confirmed spoof while this same physical appearance is active.
        if row.get("status") == "SPOOF_BLOCKED" and status == "UNREGISTERED":
            status, student_id, anti_spoof_passed = "SPOOF_BLOCKED", row.get("student_id"), False
        repeated = (row.get("status") == status and row.get("student_id") == student_id
                    and bool(row.get("anti_spoof_passed")) == bool(anti_spoof_passed))
        if not repeated:
            payload = db._safe_detail(row.get("detail_json"))
            # Existing evidence stays attached to this event; first_seen/location are immutable.
            for key, value in dict(detail or {}).items():
                if key in {"first_seen", "last_seen", "recognized_at", "appearance_timezone", "appearance_policy"}:
                    continue
                if key in {"best_snapshot", "snapshot_path"} and payload.get(key):
                    continue
                payload[key] = value
            payload["last_seen"] = frame.observed_at.isoformat()
            if status == "RECOGNIZED" and anti_spoof_passed and not payload.get("recognized_at"):
                payload["recognized_at"] = frame.observed_at.isoformat()
            if row.get("status") != status:
                payload["previous_status"] = row.get("status")
            conn.execute("UPDATE recognition_events SET student_id=?,track_id=?,status=?,confidence=?,"
                         "liveness_score=?,anti_spoof_passed=?,detail_json=? WHERE id=? AND appearance_id=?",
                         (student_id, str(track_id), status, float(confidence), float(liveness_score), int(bool(anti_spoof_passed)),
                          json.dumps(payload, ensure_ascii=False), values["event_id"], values["appearance_id"]))
            row.update(student_id=student_id, status=status, confidence=float(confidence), liveness_score=float(liveness_score),
                       anti_spoof_passed=int(bool(anti_spoof_passed)), detail_json=json.dumps(payload))
        payload = db._safe_detail(row.get("detail_json"))
        record.classification = (row["status"], row.get("student_id"), bool(row.get("anti_spoof_passed")))
        return {**values, "student_id": row.get("student_id"), "status": row["status"],
                "confidence": row.get("confidence"), "liveness_score": row.get("liveness_score"),
                "anti_spoof_passed": bool(row.get("anti_spoof_passed")), "deduplicated": repeated,
                "recognized_at": payload.get("recognized_at"), "detail": payload}

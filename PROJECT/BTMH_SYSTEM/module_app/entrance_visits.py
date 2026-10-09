"""Backend entrance crossings, separate from legacy visitor observations.

Only actual, fresh track boxes crossing a configured finite segment can create
IN/OUT. WalkBy currently supplies face boxes: a face must remain visible around
the calibrated line. No person detector or cross-camera anonymous re-ID is added.
Use one authoritative counting camera per physical entrance when views overlap.
Track loss, camera reset and midnight never manufacture an OUT.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re
import threading
import uuid
from zoneinfo import ZoneInfo

from . import db
from .demo_context import camera_event_context, event_attribution, validate_entrance_config

_SCHEMA_LOCK = threading.RLock()
MAX_CAMERA_STATES = 32
MAX_TRACKS_PER_CAMERA = 128
MAX_PENDING_CROSSINGS = 8
PENDING_CLASSIFICATION_SEC = 30.0
REACQUIRE_SIZE_RATIO = 2.0


def _utc(value):
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("ENTRANCE_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _id(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number > 0 and str(value).strip() == str(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _reference(value):
    text = str(value or "")
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", text) else None


def ensure_entrance_visits_schema():
    """Explicit startup migration; imports/frames never run DDL or backfill."""
    with _SCHEMA_LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100076)")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS entrance_visits (
            visit_id TEXT PRIMARY KEY, participant_id TEXT NOT NULL,
            camera_id BIGINT NOT NULL, store_id BIGINT NOT NULL,
            camera_name TEXT, store_name TEXT, zone_name TEXT,
            entrance_name TEXT NOT NULL DEFAULT '', timezone_name TEXT NOT NULL,
            business_date TEXT NOT NULL, entered_at TEXT NOT NULL, exited_at TEXT,
            entry_track_ref TEXT NOT NULL, exit_track_ref TEXT,
            appearance_id TEXT, entry_event_id BIGINT, exit_event_id BIGINT,
            anchor_basis TEXT NOT NULL, visit_status TEXT NOT NULL DEFAULT 'VISITOR',
            employee_id BIGINT, confirmed_at TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_entrance_visits_store_entry
            ON entrance_visits(store_id,entered_at);
        CREATE INDEX IF NOT EXISTS idx_entrance_visits_camera_entry
            ON entrance_visits(camera_id,entered_at);
        CREATE INDEX IF NOT EXISTS idx_entrance_visits_participant
            ON entrance_visits(participant_id,visit_status);
        CREATE INDEX IF NOT EXISTS idx_entrance_visits_store_date_status
            ON entrance_visits(store_id,business_date,visit_status);
        CREATE INDEX IF NOT EXISTS idx_entrance_visits_date_status
            ON entrance_visits(business_date,visit_status,store_id);
        """)


def _distance(point, config):
    dx, dy = config["x2"] - config["x1"], config["y2"] - config["y1"]
    return (dx * (point[1] - config["y1"]) - dy * (point[0] - config["x1"])) / math.hypot(dx, dy)


def _side(point, config):
    distance = _distance(point, config)
    return 1 if distance > config["deadband"] else -1 if distance < -config["deadband"] else 0


def _within_roi(point, config):
    roi = config["roi"]
    return roi is None or roi["x1"] <= point[0] <= roi["x2"] and roi["y1"] <= point[1] <= roi["y2"]


def _finite_crossing(before, after, config):
    """Opposite stable sides alone are insufficient: intersect the actual segment."""
    first, last = _distance(before, config), _distance(after, config)
    if first * last >= 0:
        return False
    fraction = first / (first - last)
    intersection = (before[0] + fraction * (after[0] - before[0]),
                    before[1] + fraction * (after[1] - before[1]))
    dx, dy = config["x2"] - config["x1"], config["y2"] - config["y1"]
    projection = ((intersection[0] - config["x1"]) * dx + (intersection[1] - config["y1"]) * dy) / (dx * dx + dy * dy)
    return -1e-9 <= projection <= 1 + 1e-9 and _within_roi(intersection, config)


def _box(track, result, config):
    """Public bbox is xywh in source pixels; optional normalized_bbox is xywh."""
    use_person = config["anchor"].startswith("person_") and track.get("person_bbox") is not None
    raw = track.get("person_bbox") if use_person else track.get("normalized_bbox", track.get("bbox"))
    if not isinstance(raw, (tuple, list)) or len(raw) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in raw)
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            return None
        if not use_person and "normalized_bbox" in track:
            frame_width = frame_height = 1.0
        else:
            frame_width, frame_height = float(result["frame_width"]), float(result["frame_height"])
        if not all(math.isfinite(value) and value > 0 for value in (frame_width, frame_height, width, height)):
            return None
        if x < 0 or y < 0 or x + width > frame_width or y + height > frame_height:
            return None
        box = (x / frame_width, y / frame_height, width / frame_width, height / frame_height)
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    point = (box[0] + box[2] * .5, box[1] + box[3] * (1.0 if config["anchor"] == "person_bottom" else .5))
    return point, box, "PERSON" if use_person else "FACE"


def _classification(track):
    if track.get("spoof_blocked") or "SPOOF" in str(track.get("status") or "").upper():
        return "BLOCKED", None
    if str((track.get("liveness") or {}).get("status") or "").upper() != "PASS":
        return "PENDING", None
    employee = _id(track.get("student_id") or track.get("employee_id") or (track.get("student") or {}).get("id"))
    status = str(track.get("status") or "").upper()
    if track.get("recognized") and employee and status == "RECOGNIZED":
        return "EMPLOYEE", employee
    if (track.get("unknown") and status == "UNREGISTERED" and not track.get("recognized")
            and not employee and not track.get("candidate_student_id")):
        return "VISITOR", None
    return "PENDING", None


@dataclass
class Crossing:
    direction: str
    occurred_at: datetime
    context: dict
    track_ref: str
    appearance_id: str | None
    anchor_basis: str
    event_id: int | None
    crossing_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    confirmed: bool = False


@dataclass
class Participant:
    track_id: int
    context: dict
    point: tuple
    box: tuple
    last_seen: datetime
    participant_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stable_point: tuple | None = None
    side: int = 0
    last_crossing: datetime | None = None
    pending: list = field(default_factory=list)
    kind: str = "PENDING"
    employee_id: int | None = None
    open_visit_id: str | None = None
    appearance_id: str | None = None
    has_visits: bool = False

    def track_ref(self):
        return f"camera-{self.context['camera_id']}:{self.participant_id}:{self.track_id}"


@dataclass
class CameraState:
    signature: str
    tracks: dict = field(default_factory=dict)
    observed_at: datetime | None = None


class EntranceVisits:
    def __init__(self, *, in_hook=None, out_hook=None):
        self._lock = threading.RLock()
        self._cameras = {}
        self._in_hook, self._out_hook = in_hook, out_hook

    def reset_camera(self, camera_id):
        """Forget spatial aliases/pending crossings; keep persisted open visits."""
        with self._lock:
            self._cameras.pop(_id(camera_id), None)

    def _attendance(self, direction, employee, crossing, observed_at):
        if not crossing.context["attendance_enabled"]:
            return {"accepted": False, "reason": "ATTENDANCE_DISABLED"}
        hook = self._in_hook if direction == "IN" else self._out_hook
        if hook is None:
            from .shift_attendance import register_attendance_in, register_attendance_out
            hook = register_attendance_in if direction == "IN" else register_attendance_out
        return hook(employee, crossing.context, crossing.occurred_at,
                    event_id=crossing.event_id or crossing.crossing_id,
                    source_type="GATE_" + direction, observed_at=observed_at)

    def _visitor(self, participant, crossing, observed_at):
        if not crossing.context["visitor_counting_enabled"]:
            return {"accepted": False, "reason": "VISITOR_COUNTING_DISABLED"}
        stamp = crossing.occurred_at.isoformat()
        now = observed_at.isoformat()
        if crossing.direction == "IN" and participant.open_visit_id:
            return {"accepted": False, "reason": "VISIT_ALREADY_OPEN", "visit_id": participant.open_visit_id}
        if crossing.direction == "OUT" and not participant.open_visit_id:
            return {"accepted": False, "reason": "OUT_WITHOUT_VISIT"}
        with db.connection() as conn:
            if crossing.direction == "IN":
                visit_id = uuid.uuid4().hex
                context = crossing.context
                business_date = crossing.occurred_at.astimezone(ZoneInfo(context["timezone_name"])).date().isoformat()
                conn.execute("INSERT INTO entrance_visits "
                             "(visit_id,participant_id,camera_id,store_id,camera_name,store_name,zone_name,entrance_name,"
                             "timezone_name,business_date,entered_at,entry_track_ref,appearance_id,entry_event_id,anchor_basis,"
                             "confirmed_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (visit_id, participant.participant_id, context["camera_id"], context["store_id"],
                              context["camera_name"], context["store_name"], context["zone_name"], context["entrance_config"]["name"],
                              context["timezone_name"], business_date, stamp, crossing.track_ref, crossing.appearance_id,
                              crossing.event_id, crossing.anchor_basis, now, now, now))
                changed = True
            else:
                visit_id = participant.open_visit_id
                cursor = conn.execute("UPDATE entrance_visits SET exited_at=?,exit_track_ref=?,exit_event_id=?,updated_at=? "
                                      "WHERE visit_id=? AND visit_status='VISITOR' AND exited_at IS NULL AND entered_at<=?",
                                      (stamp, crossing.track_ref, crossing.event_id, now, visit_id, stamp))
                changed = bool(cursor.rowcount)
        # Publish in-memory ownership only after the database commit succeeds.
        if changed:
            participant.open_visit_id = visit_id if crossing.direction == "IN" else None
            participant.has_visits = True
            return {"accepted": True, "visit_id": visit_id}
        return {"accepted": False, "reason": "OUT_WITHOUT_OPEN_VISIT", "visit_id": visit_id}

    def _reclassify(self, participant, kind, employee, observed_at):
        """An engine Unknown->Verified promotion must not remain a visitor count."""
        if not participant.has_visits:
            return []
        with db.connection() as conn:
            first = dict(conn.execute("SELECT * FROM entrance_visits WHERE participant_id=? AND visit_status='VISITOR' "
                                      "ORDER BY entered_at LIMIT 1", (participant.participant_id,)).fetchone() or {})
            last = dict(conn.execute("SELECT * FROM entrance_visits WHERE participant_id=? AND visit_status='VISITOR' "
                                     "ORDER BY entered_at DESC LIMIT 1", (participant.participant_id,)).fetchone() or {})
            conn.execute("UPDATE entrance_visits SET visit_status=?,employee_id=?,updated_at=? "
                         "WHERE participant_id=? AND visit_status='VISITOR'",
                         ("EMPLOYEE" if kind == "EMPLOYEE" else "SPOOF", employee, observed_at.isoformat(), participant.participant_id))
        participant.open_visit_id = None
        participant.has_visits = False
        corrected_crossings = []
        if kind == "EMPLOYEE" and first and participant.context["attendance_enabled"]:
            # The shift record needs first IN, latest reentry, and a genuine final
            # OUT only. Avoid an unbounded callback list for repeated visits.
            selected = [first] if first["visit_id"] == last["visit_id"] else [first, last]
            for row in selected:
                crossing = Crossing("IN", _utc(row["entered_at"]), participant.context,
                                    row["entry_track_ref"], row["appearance_id"], row["anchor_basis"], row["entry_event_id"],
                                    crossing_id=row["visit_id"] + ":IN", confirmed=True)
                corrected_crossings.append(crossing)
            if last.get("exited_at"):
                crossing = Crossing("OUT", _utc(last["exited_at"]), participant.context,
                                    last["exit_track_ref"], last["appearance_id"], last["anchor_basis"], last["exit_event_id"],
                                    crossing_id=last["visit_id"] + ":OUT", confirmed=True)
                corrected_crossings.append(crossing)
        # Use the ordinary pending queue: a transient attendance write failure
        # keeps the trusted historical crossing available for the next result.
        participant.pending = corrected_crossings + participant.pending[-MAX_PENDING_CROSSINGS:]
        return []

    @staticmethod
    def _reacquire(tracks, fresh, config, now):
        new = {tid: item for tid, item in fresh.items() if tid not in tracks}
        lost = {tid: part for tid, part in tracks.items() if tid not in fresh and
                0 < (now - part.last_seen).total_seconds() <= config["reacquire_sec"]}
        candidates = {}
        for tid, item in new.items():
            point, box, _, track = item
            side = _side(point, config)
            matches = []
            for old_id, part in lost.items():
                _, employee = _classification(track)
                if not side or side != part.side or not _within_roi(point, config):
                    continue
                if part.employee_id and employee and employee != part.employee_id:
                    continue
                ratios = (box[2] / part.box[2], part.box[2] / box[2], box[3] / part.box[3], part.box[3] / box[3])
                if max(ratios) <= REACQUIRE_SIZE_RATIO and math.dist(point, part.point) <= config["max_distance"]:
                    matches.append(old_id)
            candidates[tid] = matches
        for tid, matches in candidates.items():
            # Mutual uniqueness: two new tracks cannot both inherit one lost visit,
            # nor can a nearby track arbitrarily inherit one of several lost tracks.
            if len(matches) == 1 and sum(matches[0] in values for values in candidates.values()) == 1:
                participant = tracks.pop(matches[0])
                participant.track_id = tid
                tracks[tid] = participant

    def consume(self, camera_context, result, observed_at):
        now = _utc(observed_at)
        camera_id = _id(camera_context.get("camera_id") or camera_context.get("id"))
        store_id = _id(camera_context.get("store_id"))
        try:
            config = validate_entrance_config(camera_context.get("entrance_config"))
            ZoneInfo(camera_context["timezone_name"])
        except (ValueError, TypeError, KeyError):
            self.reset_camera(camera_id)
            return {"accepted": False, "reason": "INVALID_ENTRANCE_CONTEXT", "actions": []}
        if (not camera_id or not store_id or not camera_context.get("zone_name") or not config["enabled"]
                or not (camera_context.get("attendance_enabled") or camera_context.get("visitor_counting_enabled"))):
            self.reset_camera(camera_id)
            return {"accepted": False, "reason": "ENTRANCE_DISABLED_OR_UNASSIGNED", "actions": []}
        if (result.get("discarded_generation") or result.get("ok") is False or
                result.get("camera_id") is not None and _id(result["camera_id"]) != camera_id):
            return {"accepted": False, "reason": "DISCARDED_CAMERA_RESULT", "actions": []}
        with camera_event_context(camera_context):
            context = event_attribution()
        context.update(timezone_name=camera_context["timezone_name"], entrance_config=config,
                       attendance_enabled=bool(camera_context.get("attendance_enabled")),
                       visitor_counting_enabled=bool(camera_context.get("visitor_counting_enabled")))
        signature = json.dumps((context, result.get("source_epoch"), result.get("worker_instance_id")), sort_keys=True)
        fresh = {}
        for track in result.get("tracks") or []:
            tid = _id(track.get("track_id"))
            if (not tid or tid in fresh or track.get("stale") or track.get("tracking_grace")
                    or track.get("observation_age_ms", 0) != 0):
                continue
            box = _box(track, result, config)
            if box and len(fresh) < MAX_TRACKS_PER_CAMERA:
                fresh[tid] = (*box, track)
        event_ids = {_id(event.get("track_id")): _id(event.get("id")) for event in result.get("events") or []}
        with self._lock:
            state = self._cameras.get(camera_id)
            if state is None or state.signature != signature:
                if len(self._cameras) >= MAX_CAMERA_STATES and camera_id not in self._cameras:
                    oldest = min(self._cameras, key=lambda key: self._cameras[key].observed_at or now)
                    self._cameras.pop(oldest)
                state = self._cameras[camera_id] = CameraState(signature)
            if state.observed_at and now <= state.observed_at:
                return {"accepted": False, "reason": "IGNORED_OLD_RESULT", "actions": []}
            self._reacquire(state.tracks, fresh, config, now)
            actions = []
            for tid, (point, box, anchor_basis, track) in fresh.items():
                part = state.tracks.get(tid)
                if part is not None and (now - part.last_seen).total_seconds() > config["reacquire_sec"]:
                    # Even a reused track integer cannot inherit a visit after a
                    # long unobserved interval. The old visit keeps missing OUT.
                    state.tracks.pop(tid)
                    part = None
                if part is None:
                    if len(state.tracks) >= MAX_TRACKS_PER_CAMERA:
                        lost = [key for key in state.tracks if key not in fresh]
                        if not lost:
                            continue
                        state.tracks.pop(min(lost, key=lambda key: state.tracks[key].last_seen))
                    part = state.tracks[tid] = Participant(tid, json.loads(json.dumps(context)), point, box, now)
                part.pending = [crossing for crossing in part.pending
                                if crossing.confirmed or (now - crossing.occurred_at).total_seconds() <= PENDING_CLASSIFICATION_SEC]
                kind, employee = _classification(track)
                if part.kind == "BLOCKED":
                    if kind == "EMPLOYEE":
                        # WalkBy can recover after new PAD/identity evidence. Trust
                        # that accepted employee result, preserving old SPOOF rows
                        # and requiring a newly observed crossing from this baseline.
                        part.pending.clear()
                        part.stable_point, part.side, part.last_crossing = None, 0, None
                        part.kind, part.employee_id = "PENDING", None
                    else:
                        kind = "BLOCKED"
                if part.employee_id and employee and part.employee_id != employee:
                    kind = "BLOCKED"  # Fail closed for a conflicting identity on one physical alias.
                if kind == "VISITOR" and part.kind == "EMPLOYEE":
                    kind = "PENDING"  # A revoked identity needs fresh verification.
                if kind == "BLOCKED":
                    actions.extend(self._reclassify(part, kind, None, now))
                    part.pending.clear()
                    part.kind = "BLOCKED"
                elif kind == "EMPLOYEE":
                    if part.kind == "VISITOR":
                        actions.extend(self._reclassify(part, kind, employee, now))
                    part.kind, part.employee_id = kind, employee
                elif kind == "VISITOR" and part.kind != "EMPLOYEE":
                    part.kind = kind
                # A stale alias returning after the bounded gap starts a new spatial
                # baseline. It cannot turn track loss into a crossing.
                if (now - part.last_seen).total_seconds() > config["reacquire_sec"]:
                    part.stable_point, part.side = None, 0
                side = _side(point, config)
                if not _within_roi(point, config):
                    part.stable_point, part.side = None, 0
                elif side:
                    cooldown_ok = part.last_crossing is None or (now - part.last_crossing).total_seconds() >= config["cooldown_sec"]
                    if (part.stable_point is not None and part.side != side and cooldown_ok
                            and _finite_crossing(part.stable_point, point, config) and kind != "BLOCKED"):
                        direction = "IN" if side == (1 if config["inside_side"] == "positive" else -1) else "OUT"
                        crossing = Crossing(direction, now, json.loads(json.dumps(part.context)), part.track_ref(),
                                            _reference(track.get("appearance_id")), anchor_basis, event_ids.get(tid))
                        if len(part.pending) < MAX_PENDING_CROSSINGS:
                            part.pending.append(crossing)
                        part.last_crossing = now
                    part.stable_point, part.side = point, side
                part.point, part.box, part.last_seen = point, box, now
                part.appearance_id = _reference(track.get("appearance_id"))
                if kind in {"EMPLOYEE", "VISITOR"} and part.kind != "BLOCKED":
                    for crossing in list(part.pending):
                        crossing.confirmed = True
                        if part.kind == "EMPLOYEE":
                            outcome = self._attendance(crossing.direction, part.employee_id, crossing, now)
                        else:
                            outcome = self._visitor(part, crossing, now)
                        actions.append({"kind": part.kind, "direction": crossing.direction,
                                        "occurred_at": crossing.occurred_at.isoformat(), **outcome})
                        part.pending.remove(crossing)
            for tid, part in list(state.tracks.items()):
                keep_sec = PENDING_CLASSIFICATION_SEC if part.pending else config["reacquire_sec"]
                if tid not in fresh and (now - part.last_seen).total_seconds() > keep_sec:
                    state.tracks.pop(tid)
            state.observed_at = now
            return {"accepted": True, "actions": actions, "tracked": len(state.tracks),
                    "pending": sum(len(part.pending) for part in state.tracks.values()),
                    "anchor_basis": "PERSON" if any(item[2] == "PERSON" for item in fresh.values()) else "FACE"}


ENTRY_VISITS = EntranceVisits()

"""Assigned-shift attendance; observation timestamps never manufacture an OUT.

Imports do not open a database. The startup migration is additive and the backend
result consumer accepts only the application's existing verified identity/PAD
decisions. Business dates are the local dates on which assigned shifts start.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import threading
from zoneinfo import ZoneInfo

from . import db

_LOCK = threading.RLock()
_SEEN = {}


def _utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("ATTENDANCE_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _id(value):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
        return number if number > 0 and str(value).strip() == str(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _date(value):
    return value if isinstance(value, date) and not isinstance(value, datetime) else date.fromisoformat(str(value))


def _snapshot(conn, shift):
    store_id = _id(shift.get("store_id"))
    if not store_id and _id(shift.get("student_id")):
        primary = conn.execute("SELECT store_id FROM employee_store_assignments WHERE student_id=? AND is_primary=1",
                               (shift["student_id"],)).fetchall()
        if len(primary) == 1:
            store_id = _id(dict(primary[0])["store_id"])
    store = dict(conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone() or {}) if store_id else {}
    return {key: shift.get(key) for key in ("id", "store_id", "shift_code", "shift_name", "start_time", "end_time",
             "late_grace_minutes", "early_leave_grace_minutes", "workdays_json")} | {
        "store_id": store_id, "timezone_name": store.get("timezone_name"), "store_name": store.get("store_name")}


def ensure_shift_attendance_schema():
    """Seed only actually known assignments; never assign the default shift."""
    with _LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100074)")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS employee_shift_assignment_history (
            student_id INTEGER NOT NULL, effective_from TEXT NOT NULL, effective_to TEXT,
            shift_id INTEGER NOT NULL, store_id INTEGER, schedule_json TEXT NOT NULL,
            assigned_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(student_id,effective_from)
        );
        CREATE INDEX IF NOT EXISTS idx_shift_history_store_dates
            ON employee_shift_assignment_history(store_id,effective_from,effective_to);
        CREATE TABLE IF NOT EXISTS shift_attendance_records (
            employee_id INTEGER NOT NULL, store_id INTEGER NOT NULL, shift_id INTEGER NOT NULL,
            business_date TEXT NOT NULL, expected_start_at TEXT NOT NULL, expected_end_at TEXT NOT NULL,
            schedule_json TEXT NOT NULL, first_in_at TEXT NOT NULL, last_in_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL, last_out_at TEXT, first_event_id TEXT, last_out_event_id TEXT,
            camera_id INTEGER, camera_name TEXT, store_name TEXT, zone_name TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(employee_id,store_id,shift_id,business_date)
        );
        CREATE INDEX IF NOT EXISTS idx_shift_attendance_store_date
            ON shift_attendance_records(store_id,business_date);
        """)
        rows = conn.execute("SELECT a.*,s.id AS schedule_id,s.store_id,s.shift_code,s.shift_name,s.start_time,s.end_time,"
                            "s.late_grace_minutes,s.early_leave_grace_minutes,s.workdays_json "
                            "FROM employee_shift_assignments a JOIN work_shifts s ON s.id=a.shift_id "
                            "WHERE NOT EXISTS (SELECT 1 FROM employee_shift_assignment_history h WHERE h.student_id=a.student_id)").fetchall()
        for raw in rows:
            row = dict(raw)
            try:
                start = _date(row["effective_from"]).isoformat()
                end = _date(row["effective_to"]).isoformat() if row.get("effective_to") else None
            except (ValueError, TypeError):
                continue  # Unknown historical interval remains unknown.
            shift = {**row, "id": row["schedule_id"]}
            snapshot = _snapshot(conn, shift)
            conn.execute("INSERT INTO employee_shift_assignment_history "
                         "(student_id,effective_from,effective_to,shift_id,store_id,schedule_json,assigned_by,created_at,updated_at) "
                         "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(student_id,effective_from) DO NOTHING",
                         (row["student_id"], start, end, row["shift_id"], snapshot["store_id"], json.dumps(snapshot),
                          row.get("assigned_by") or "", row["created_at"], row["updated_at"]))


def save_assignment_history(conn, student_id, shift, effective_from, actor, now):
    """Called in the same transaction as the backwards-compatible assignment row."""
    start = _date(effective_from)
    if conn.mode == "postgres":
        conn.execute("SELECT pg_advisory_xact_lock(54100074)")
    following = conn.execute("SELECT effective_from FROM employee_shift_assignment_history "
                             "WHERE student_id=? AND effective_from>? ORDER BY effective_from LIMIT 1",
                             (student_id, start.isoformat())).fetchone()
    end = (_date(dict(following)["effective_from"]) - timedelta(days=1)).isoformat() if following else None
    conn.execute("UPDATE employee_shift_assignment_history SET effective_to=?,updated_at=? "
                 "WHERE student_id=? AND effective_from<? AND (effective_to IS NULL OR effective_to>=?)",
                 ((start - timedelta(days=1)).isoformat(), now, student_id, start.isoformat(), start.isoformat()))
    snapshot = _snapshot(conn, {**shift, "student_id": student_id})
    conn.execute("INSERT INTO employee_shift_assignment_history "
                 "(student_id,effective_from,effective_to,shift_id,store_id,schedule_json,assigned_by,created_at,updated_at) "
                 "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(student_id,effective_from) DO UPDATE SET "
                 "effective_to=excluded.effective_to,shift_id=excluded.shift_id,store_id=excluded.store_id,"
                 "schedule_json=excluded.schedule_json,assigned_by=excluded.assigned_by,updated_at=excluded.updated_at",
                 (student_id, start.isoformat(), end, shift["id"], snapshot["store_id"], json.dumps(snapshot), actor, now, now))
    return {**snapshot, "student_id": student_id, "shift_id": shift["id"], "effective_from": start.isoformat(), "effective_to": end, "assigned_by": actor}


def assignment_for_date(student_id, business_date):
    day = _date(business_date).isoformat()
    row = db.fetchone("SELECT * FROM employee_shift_assignment_history WHERE student_id=? "
                      "AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) "
                      "ORDER BY effective_from DESC LIMIT 1", (student_id, day, day))
    if not row:
        return None
    return {**json.loads(row["schedule_json"]), **row}


def _instance(assignment, business_date):
    schedule = json.loads(assignment["schedule_json"])
    zone = ZoneInfo(schedule["timezone_name"])
    day = _date(business_date)
    workdays = json.loads(schedule["workdays_json"])
    if day.weekday() not in workdays:
        return None
    start = datetime.combine(day, time.fromisoformat(schedule["start_time"]), zone)
    end = datetime.combine(day, time.fromisoformat(schedule["end_time"]), zone)
    if end <= start:
        end += timedelta(days=1)
    return {"employee_id": int(assignment["student_id"]), "store_id": int(assignment["store_id"]),
            "shift_id": int(assignment["shift_id"]), "business_date": day.isoformat(),
            "expected_start_at": start.astimezone(timezone.utc).isoformat(),
            "expected_end_at": end.astimezone(timezone.utc).isoformat(), "schedule_json": assignment["schedule_json"],
            "schedule": schedule}


def resolve_shift_instance(employee_id, camera_context, occurred_at):
    stamp = _utc(occurred_at)
    store_id = _id(camera_context.get("store_id"))
    if not store_id:
        return None
    try:
        local_day = stamp.astimezone(ZoneInfo(camera_context["timezone_name"])).date()
    except (KeyError, ValueError, TypeError):
        return None
    for day in (local_day - timedelta(days=1), local_day):
        assignment = assignment_for_date(employee_id, day)
        if not assignment or _id(assignment.get("store_id")) != store_id:
            continue
        try:
            item = _instance(assignment, day)
        except (ValueError, TypeError, KeyError):
            continue
        if item and (day == local_day or _utc(item["expected_start_at"]) <= stamp <= _utc(item["expected_end_at"])):
            return item
    return None


def _key(item):
    return tuple(item[name] for name in ("employee_id", "store_id", "shift_id", "business_date"))


def register_attendance_in(employee_id, camera_context, occurred_at, *, event_id=None,
                           source_type="RECOGNITION", observed_at=None):
    if not _id(employee_id) or not camera_context.get("attendance_enabled", False):
        return {"accepted": False, "reason": "ATTENDANCE_DISABLED_OR_UNKNOWN_EMPLOYEE"}
    stamp = _utc(occurred_at).isoformat()
    item = resolve_shift_instance(int(employee_id), camera_context, stamp)
    if not item:
        return {"accepted": False, "reason": "NO_APPLICABLE_ASSIGNED_SHIFT"}
    observed = _utc(observed_at or occurred_at).isoformat()
    key = _key(item)
    with _LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100075)")
        conn.execute("INSERT INTO shift_attendance_records "
                     "(employee_id,store_id,shift_id,business_date,expected_start_at,expected_end_at,schedule_json,"
                     "first_in_at,last_in_at,last_seen_at,first_event_id,camera_id,camera_name,store_name,zone_name,created_at,updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(employee_id,store_id,shift_id,business_date) DO NOTHING",
                     (*key, item["expected_start_at"], item["expected_end_at"], item["schedule_json"], stamp, stamp, observed,
                      f"{source_type}:{event_id}" if event_id is not None else source_type, camera_context.get("camera_id") or camera_context.get("id"),
                      camera_context.get("camera_name"), camera_context.get("store_name"), camera_context.get("zone_name"), observed, observed))
        current = dict(conn.execute("SELECT * FROM shift_attendance_records WHERE employee_id=? AND store_id=? AND shift_id=? AND business_date=?", key).fetchone())
        first = min(current["first_in_at"], stamp)
        last_in = current["last_in_at"]
        # Replayed earlier IN cannot reopen a completed OUT. Continuous sightings
        # update last_seen only while inside; a new valid IN after OUT reopens.
        if current.get("last_out_at") and last_in <= current["last_out_at"] < stamp:
            last_in = stamp
        seen = max(current["last_seen_at"], observed)
        if (first, last_in, seen) != (current["first_in_at"], current["last_in_at"], current["last_seen_at"]):
            earlier = stamp < current["first_in_at"]
            conn.execute("UPDATE shift_attendance_records SET first_in_at=?,last_in_at=?,last_seen_at=?,updated_at=? "
                         "WHERE employee_id=? AND store_id=? AND shift_id=? AND business_date=?",
                         (first, last_in, seen, observed, *key))
            current.update(first_in_at=first, last_in_at=last_in, last_seen_at=seen)
            if earlier:
                provenance = (f"{source_type}:{event_id}" if event_id is not None else source_type,
                              camera_context.get("camera_id") or camera_context.get("id"), camera_context.get("camera_name"),
                              camera_context.get("store_name"), camera_context.get("zone_name"))
                conn.execute("UPDATE shift_attendance_records SET first_event_id=?,camera_id=?,camera_name=?,store_name=?,zone_name=? "
                             "WHERE employee_id=? AND store_id=? AND shift_id=? AND business_date=?", (*provenance, *key))
                current.update(zip(("first_event_id", "camera_id", "camera_name", "store_name", "zone_name"), provenance))
    return {"accepted": True, **_record_state(current, _utc(observed_at or occurred_at))}


def register_attendance_out(employee_id, camera_context, occurred_at, *, event_id=None, source_type="GATE_OUT", observed_at=None):
    """Backend trusted crossing hook. Unknown/unpaired OUT never invents an IN."""
    if source_type != "GATE_OUT" or not _id(employee_id) or not _id(camera_context.get("store_id")) or not camera_context.get("attendance_enabled", False):
        return {"accepted": False, "reason": "INVALID_OUT_SOURCE"}
    stamp = _utc(occurred_at).isoformat()
    with _LOCK, db.connection() as conn:
        if conn.mode == "postgres":
            conn.execute("SELECT pg_advisory_xact_lock(54100075)")
        raw = conn.execute("SELECT * FROM shift_attendance_records WHERE employee_id=? AND store_id=? "
                           "AND first_in_at<=? AND last_in_at<=? AND (last_out_at IS NULL OR last_in_at>last_out_at) "
                           "ORDER BY last_in_at DESC LIMIT 1",
                           (employee_id, camera_context["store_id"], stamp, stamp)).fetchone()
        if not raw:
            return {"accepted": False, "reason": "OUT_WITHOUT_VALID_IN"}
        row = dict(raw)
        if not row.get("last_out_at") or stamp > row["last_out_at"]:
            conn.execute("UPDATE shift_attendance_records SET last_out_at=?,last_out_event_id=?,updated_at=? "
                         "WHERE employee_id=? AND store_id=? AND shift_id=? AND business_date=?",
                         (stamp, str(event_id) if event_id is not None else None, _utc(observed_at or occurred_at).isoformat(), *_key(row)))
            row["last_out_at"] = stamp
    return {"accepted": True, **_record_state(row, _utc(observed_at or occurred_at))}


def touch_attendance_seen(employee_id, camera_context, observed_at):
    stamp = _utc(observed_at).isoformat()
    if not _id(employee_id) or not _id(camera_context.get("store_id")) or not camera_context.get("attendance_enabled", False):
        return None
    with _LOCK, db.connection() as conn:
        row = conn.execute("SELECT * FROM shift_attendance_records WHERE employee_id=? AND store_id=? "
                           "AND first_in_at<=? AND (last_out_at IS NULL OR last_in_at>last_out_at) "
                           "ORDER BY last_in_at DESC LIMIT 1", (employee_id, camera_context["store_id"], stamp)).fetchone()
        if not row:
            return None
        row = dict(row)
        if stamp > row["last_seen_at"]:
            conn.execute("UPDATE shift_attendance_records SET last_seen_at=?,updated_at=? WHERE employee_id=? AND store_id=? AND shift_id=? AND business_date=?",
                         (stamp, stamp, *_key(row)))
            row["last_seen_at"] = stamp
    return _record_state(row, _utc(observed_at))


def _record_state(row, now, correction=None):
    schedule = json.loads(row["schedule_json"])
    raw_in = row.get("first_in_at")
    raw_out = row.get("last_out_at") if row.get("last_out_at") and row["last_out_at"] >= row.get("last_in_at", "") else None
    correction = correction or {}
    first = correction.get("effective_checkin_at") or raw_in
    checkout = correction.get("effective_checkout_at") or raw_out
    ended = now > _utc(row["expected_end_at"])
    late_grace = schedule.get("late_grace_minutes")
    early_grace = schedule.get("early_leave_grace_minutes")
    late = _utc(first) > _utc(row["expected_start_at"]) + timedelta(minutes=int(late_grace)) if first and late_grace is not None else None
    early = _utc(checkout) < _utc(row["expected_end_at"]) - timedelta(minutes=int(early_grace)) if first and checkout and ended and early_grace is not None else None
    if not first:
        status = "ABSENT" if ended else "NOT_YET_DUE"
    elif not checkout:
        status = "MISSING_OUT" if ended else "IN_PROGRESS"
    else:
        status = "LATE" if late else "PRESENT"
    return {**row, "checkin_at": first, "checkout_at": checkout, "raw_checkin_at": raw_in, "raw_checkout_at": raw_out,
            "checkout_source": "APPROVED_CORRECTION" if correction.get("effective_checkout_at") else "GATE_OUT" if raw_out else None,
            "attendance_adjusted": bool(correction), "correction": correction or None, "status": status,
            "late": late, "early_leave": early, "shift_name": schedule.get("shift_name"), "shift_code": schedule.get("shift_code"),
            "late_grace_minutes": late_grace, "early_leave_grace_minutes": early_grace,
            "timezone_name": schedule.get("timezone_name"), "store_name": row.get("store_name") or schedule.get("store_name")}


def _employee(track):
    return _id(track.get("student_id") or track.get("employee_id") or (track.get("student") or {}).get("id"))


def consume_camera_result(camera_context, result, observed_at):
    """Metadata observer; browser presentation has no role in this lifecycle."""
    now = _utc(observed_at)
    if not camera_context.get("attendance_enabled", False) or not _id(camera_context.get("store_id")):
        return []
    from .demo_context import validate_entrance_config
    try:
        gated = validate_entrance_config(camera_context.get("entrance_config"))["enabled"]
    except (ValueError, TypeError):
        gated = False
    updates = []
    if not gated:
        for event in result.get("events") or []:
            if str(event.get("status") or "").upper() != "RECOGNIZED" or not event.get("anti_spoof_passed"):
                continue
            employee = _employee(event)
            # Legacy attribution stays unknown. A cached recognition event must not
            # be moved to today's camera/store; current verified tracks handle now.
            if employee and _id(event.get("store_id")):
                context = {**camera_context, **{key: event.get(key) for key in ("camera_id", "store_id", "camera_name", "store_name", "zone_name")}}
                try:
                    # An appearance event starts before verification. Only successful
                    # recognition time admits IN; legacy events still use event_at.
                    admission_at = event.get("recognized_at") or (event.get("detail") or {}).get("recognized_at") or event["event_at"]
                    updates.append(register_attendance_in(employee, context, admission_at, event_id=event.get("id"), observed_at=admission_at))
                except (ValueError, TypeError, KeyError):
                    continue
    for track in result.get("tracks") or []:
        employee = _employee(track)
        if (not employee or track.get("stale", False) or track.get("tracking_grace", False) or track.get("spoof_blocked", False)
                or track.get("observation_age_ms", 0) != 0 or not track.get("recognized")
                or str((track.get("liveness") or {}).get("status") or "").upper() != "PASS"):
            continue
        throttle_key = (employee, int(camera_context["store_id"]))
        try:
            local_day = now.astimezone(ZoneInfo(camera_context["timezone_name"])).date()
        except (ValueError, KeyError, TypeError):
            continue
        with _LOCK:
            previous = _SEEN.get(throttle_key)
            crossed_boundary = previous is not None and ((previous[1] is not None and previous[0] <= previous[1] < now) or local_day != previous[2])
            if previous is not None and not crossed_boundary and 0 <= (now - previous[0]).total_seconds() < 1:
                continue
        update = touch_attendance_seen(employee, camera_context, now) if gated else register_attendance_in(employee, camera_context, now)
        with _LOCK:
            boundary = _utc(update["expected_end_at"]) if update and update.get("expected_end_at") else None
            _SEEN[throttle_key] = (now, boundary, local_day)
            if len(_SEEN) > 4096:
                cutoff = now - timedelta(minutes=10)
                for key in list(_SEEN):
                    if _SEEN[key][0] < cutoff:
                        _SEEN.pop(key, None)
                if len(_SEEN) > 4096:
                    for key in sorted(_SEEN, key=lambda value: _SEEN[value][0])[:len(_SEEN) - 4096]:
                        _SEEN.pop(key, None)
        if update:
            updates.append(update)
    return updates


def build_shift_attendance_report(start_date, end_date, *, allowed_store_ids=None, store_id=None, now=None):
    """Inclusive business-date range; read-only, including expected unobserved shifts."""
    start, end = _date(start_date), _date(end_date)
    if end < start or (end - start).days > 366:
        raise ValueError("INVALID_ATTENDANCE_DATE_RANGE")
    current = _utc(now)
    scope = None if allowed_store_ids is None else {_id(value) for value in allowed_store_ids} - {None}
    wanted = _id(store_id) if store_id is not None else None
    if store_id is not None and wanted is None:
        raise ValueError("INVALID_STORE")
    if wanted is not None and scope is not None and wanted not in scope:
        raise PermissionError("STORE_SCOPE_DENIED")
    clauses, args = ["h.effective_from<=?", "(h.effective_to IS NULL OR h.effective_to>=?)"], [end.isoformat(), start.isoformat()]
    if wanted is not None:
        clauses.append("h.store_id=?"); args.append(wanted)
    elif scope is not None:
        if not scope:
            return {"rows": [], "totals": {"scheduled_shifts": 0, "present_shifts": 0, "late_cases": 0, "absent_days": 0, "early_leave_cases": 0, "pending_shifts": 0, "missing_out": 0}, "start_date": start.isoformat(), "end_date": end.isoformat()}
        clauses.append("h.store_id IN (" + ",".join("?" for _ in scope) + ")"); args.extend(sorted(scope))
    assignments = db.fetchall("SELECT h.*,s.student_code,s.full_name,s.class_name,s.faculty FROM employee_shift_assignment_history h "
                             "JOIN students s ON s.id=h.student_id WHERE " + " AND ".join(clauses) + " ORDER BY h.student_id,h.effective_from", args)
    record_clauses, record_args = ["business_date>=?", "business_date<=?"], [start.isoformat(), end.isoformat()]
    scope_clause, scope_args = "", []
    if wanted is not None:
        scope_clause, scope_args = "store_id=?", [wanted]
    elif scope is not None:
        scope_clause, scope_args = "store_id IN (" + ",".join("?" for _ in scope) + ")", sorted(scope)
    if scope_clause:
        record_clauses.append(scope_clause); record_args.extend(scope_args)
    records = db.fetchall("SELECT * FROM shift_attendance_records WHERE " + " AND ".join(record_clauses), record_args)
    record_map = {_key(row): row for row in records if (scope is None or row["store_id"] in scope) and (wanted is None or row["store_id"] == wanted)}
    corrections = {}
    correction_sql = "SELECT c.* FROM attendance_corrections_v5 c WHERE c.work_date>=? AND c.work_date<=?"
    correction_args = [start.isoformat(), end.isoformat()]
    if scope_clause:
        correction_sql += " AND EXISTS(SELECT 1 FROM employee_shift_assignment_history h WHERE h.student_id=c.student_id " \
                          "AND h.effective_from<=c.work_date AND (h.effective_to IS NULL OR h.effective_to>=c.work_date) AND h." + scope_clause + ")"
        correction_args.extend(scope_args)
    for row in db.fetchall(correction_sql + " ORDER BY c.created_at,c.id", correction_args):
        if not row.get("approved_by") or len(str(row.get("reason") or "").strip()) < 3:
            continue
        for name in ("effective_checkin_at", "effective_checkout_at"):
            try:
                row[name] = _utc(row[name]).isoformat() if row.get(name) else None
            except (ValueError, TypeError):
                row[name] = None  # Invalid legacy correction cannot break reports.
        key = (int(row["student_id"]), row["work_date"])
        previous = corrections.get(key, {})
        corrections[key] = {**previous, **row, **{name: row.get(name) or previous.get(name) for name in ("effective_checkin_at", "effective_checkout_at")}}
    rows = []
    for assignment in assignments:
        if not _id(assignment.get("store_id")):
            continue
        day = max(start, _date(assignment["effective_from"]))
        last = min(end, _date(assignment["effective_to"])) if assignment.get("effective_to") else end
        while day <= last:
            try:
                item = _instance(assignment, day)
            except (ValueError, KeyError, TypeError):
                item = None
            if item:
                row = record_map.get(_key(item)) or {**item, "first_in_at": None, "last_in_at": None, "last_seen_at": None, "last_out_at": None}
                state = _record_state(row, current, corrections.get((item["employee_id"], day.isoformat())))
                state.update(employee_code=assignment["student_code"], full_name=assignment["full_name"], department=assignment["faculty"], position=assignment["class_name"])
                zone = ZoneInfo(state["timezone_name"])
                for field in ("checkin_at", "checkout_at", "last_seen_at", "expected_start_at", "expected_end_at"):
                    state[field + "_local"] = _utc(state[field]).astimezone(zone).isoformat() if state.get(field) else None
                state["first_in_at"] = state.get("raw_checkin_at")
                state.pop("schedule_json", None); state.pop("schedule", None)
                rows.append(state)
            day += timedelta(days=1)
    totals = {"scheduled_shifts": len(rows), "present_shifts": sum(bool(row["checkin_at"]) for row in rows),
              "late_cases": sum(row["late"] is True for row in rows), "early_leave_cases": sum(row["early_leave"] is True for row in rows),
              "absent_days": sum(row["status"] == "ABSENT" for row in rows), "pending_shifts": sum(row["status"] == "NOT_YET_DUE" for row in rows),
              "missing_out": sum(row["status"] == "MISSING_OUT" for row in rows)}
    return {"rows": rows, "totals": totals, "start_date": start.isoformat(), "end_date": end.isoformat(), "generated_at": current.isoformat()}

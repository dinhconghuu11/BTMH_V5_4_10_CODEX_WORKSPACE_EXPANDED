"""Scoped SQL recognition history and source-free filter options.

Appearance business dates and location snapshots are immutable. Legacy rows
without a date use the Vietnamese calendar's UTC window; their store is never
inferred from a camera's present assignment. Public serialization belongs to
the API boundary, so query items retain server-only evidence detail.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

from . import db
from .demo_context import _positive_id, _safe_name, scoped_store_ids

RESULTS = frozenset(("ANALYZING", "RECOGNIZED", "UNREGISTERED", "SPOOF_BLOCKED"))
SUBJECTS = frozenset(("EMPLOYEE", "VISITOR", "UNKNOWN"))
_EMPLOYEE = "(e.status='RECOGNIZED' AND e.anti_spoof_passed=1 AND e.student_id IS NOT NULL)"


def _date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("INVALID_HISTORY_DATE")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError("INVALID_HISTORY_DATE") from None


def _number(value, name, minimum=1):
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ValueError(f"INVALID_HISTORY_{name.upper()}")
    number = int(value)
    if number < minimum:
        raise ValueError(f"INVALID_HISTORY_{name.upper()}")
    return number


def _scope(allowed):
    if allowed is None:
        return None
    return frozenset(number for number in (_positive_id(item) for item in allowed) if number is not None)


def _store_sql(alias, scope, store_id=None):
    """Always apply scope inside SQL before reading any historical row."""
    if store_id is not None:
        if scope is not None and store_id not in scope:
            raise PermissionError("STORE_SCOPE_DENIED")
        return f"{alias}.store_id=?", [store_id]
    if scope is None:
        return "1=1", []
    if not scope:
        return "1=0", []
    values = sorted(scope)
    return f"{alias}.store_id IN ({','.join('?' for _ in values)})", values


def query_recognition_history(start_date, end_date, *, allowed_store_ids=None, store_id=None,
                              zone_name="", camera_id=None, employee_id=None, subject_type="",
                              result="", search="", limit=100, offset=0, before_id=None):
    start, end = _date(start_date), _date(end_date)
    if end < start or (end - start).days >= 366:
        raise ValueError("INVALID_HISTORY_DATE_RANGE")
    scope = _scope(allowed_store_ids)
    store_id = _number(store_id, "store") if store_id is not None else None
    camera_id = _number(camera_id, "camera") if camera_id is not None else None
    employee_id = _number(employee_id, "employee") if employee_id is not None else None
    before_id = _number(before_id, "cursor") if before_id is not None else None
    limit, offset = min(200, _number(limit, "limit")), _number(offset, "offset", 0)
    subject_type, result = str(subject_type or "").upper(), str(result or "").upper()
    if subject_type and subject_type not in SUBJECTS:
        raise ValueError("INVALID_HISTORY_SUBJECT")
    if result and result not in RESULTS:
        raise ValueError("INVALID_HISTORY_RESULT")
    zone_name, search = str(zone_name or "").strip(), str(search or "").strip()
    if len(zone_name) > 120 or len(search) > 200:
        raise ValueError("INVALID_HISTORY_TEXT_FILTER")
    store_clause, params = _store_sql("e", scope, store_id)
    if scope == frozenset():
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    try:
        utc_start = datetime.combine(start, time.min, zone).astimezone(timezone.utc).isoformat()
        utc_end = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(timezone.utc).isoformat()
    except OverflowError:
        raise ValueError("INVALID_HISTORY_DATE_RANGE") from None
    predicates = [store_clause, "((e.business_date>=? AND e.business_date<=?) OR "
                  "(e.business_date IS NULL AND e.event_at>=? AND e.event_at<?))"]
    params += [start.isoformat(), end.isoformat(), utc_start, utc_end]
    for column, value in (("zone_name", zone_name), ("camera_id", camera_id), ("student_id", employee_id)):
        if value != "" and value is not None:
            predicates.append(f"e.{column}=?")
            params.append(value)
    if result:
        predicates.append("e.status=?")
        params.append(result)
    if subject_type == "EMPLOYEE":
        predicates.append(_EMPLOYEE)
    elif subject_type == "VISITOR":
        predicates.append("e.status='UNREGISTERED'")
    elif subject_type == "UNKNOWN":
        predicates.append(f"NOT ({_EMPLOYEE} OR e.status='UNREGISTERED')")
    if search:
        # Literal substring: parameterization prevents SQL injection; escaping
        # prevents percent/underscore input from silently broadening the search.
        term = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        fields = ("s.full_name", "s.student_code", "s.faculty", "s.class_name",
                  "e.camera_name", "e.store_name", "e.zone_name")
        predicates.append("(" + " OR ".join(f"LOWER(COALESCE({field},'')) LIKE ? ESCAPE '\\'" for field in fields) + ")")
        params += [f"%{term}%"] * len(fields)
    where = " AND ".join(predicates)
    joins = " FROM recognition_events e LEFT JOIN students s ON s.id=e.student_id "
    with db.connection() as conn:
        if search and conn.mode == "sqlite":
            # SQLite's built-in LOWER folds ASCII only. Keep Vietnamese names
            # searchable offline without requiring an ICU extension or new schema.
            conn.raw.create_function("btmh_history_lower", 1, lambda value: str(value or "").lower(), deterministic=True)
            where = where.replace("LOWER(", "btmh_history_lower(")
        total = int(dict(conn.execute("SELECT COUNT(*) AS total" + joins + "WHERE " + where, params).fetchone())["total"])
        page_params = list(params)
        if before_id is not None:
            where += " AND e.id<?"
            page_params.append(before_id)
        items = [dict(row) for row in conn.execute(
            "SELECT e.*,s.student_code,s.full_name,s.class_name,s.faculty" + joins + "WHERE " + where +
            " ORDER BY e.id DESC LIMIT ? OFFSET ?", [*page_params, limit, offset]).fetchall()]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def recognition_filter_options(user):
    """Union scoped current and immutable historical context, no source/detail data."""
    scope = _scope(scoped_store_ids(user))
    empty = {"stores": [], "zones": [], "cameras": [], "employees": [], "departments": []}
    if scope == frozenset():
        return empty
    event_clause, event_params = _store_sql("e", scope)
    assignment_clause, assignment_params = _store_sql("a", scope)
    with db.connection() as conn:
        store_where = "1=1" if scope is None else "s.id IN (" + ",".join("?" for _ in scope) + ")"
        stores = [dict(row) for row in conn.execute("SELECT s.id,s.store_name FROM stores s WHERE " + store_where +
                                                  " ORDER BY s.id", [] if scope is None else sorted(scope)).fetchall()]
        # Historical snapshots remain available even after camera move/delete or
        # a store rename. Anonymous legacy sources are deliberately not options.
        historical = [dict(row) for row in conn.execute(
            "SELECT DISTINCT e.store_id,e.store_name,e.camera_id,e.camera_name,e.zone_name "
            "FROM recognition_events e WHERE " + event_clause + " ORDER BY e.store_id,e.camera_id,e.zone_name,e.camera_name",
            event_params).fetchall()]
        current = [dict(row) for row in conn.execute(
            "SELECT c.id AS camera_id,c.name AS camera_name,c.zone_name,a.store_id,s.store_name "
            "FROM camera_devices c LEFT JOIN camera_store_assignments a ON a.camera_device_id=c.id "
            "LEFT JOIN stores s ON s.id=a.store_id WHERE " + assignment_clause +
            " AND (SELECT COUNT(*) FROM camera_store_assignments n WHERE n.camera_device_id=c.id)<=1 ORDER BY c.id",
            assignment_params).fetchall()]
        employee_params = []
        if scope is None:
            employee_where = "1=1"
        else:
            marks = ",".join("?" for _ in scope)
            employee_where = (f"EXISTS(SELECT 1 FROM employee_store_assignments a WHERE a.student_id=s.id AND a.store_id IN ({marks})) "
                              f"OR EXISTS(SELECT 1 FROM employee_shift_assignment_history h WHERE h.student_id=s.id AND h.store_id IN ({marks})) "
                              f"OR EXISTS(SELECT 1 FROM recognition_events e WHERE e.student_id=s.id AND e.store_id IN ({marks}))")
            employee_params = sorted(scope) * 3
        employees = [dict(row) for row in conn.execute(
            "SELECT s.id,s.student_code,s.full_name,s.faculty,s.class_name FROM students s WHERE " +
            employee_where + " ORDER BY s.full_name,s.id", employee_params).fetchall()]
    store_map = {row["id"]: {"id": row["id"], "store_name": _safe_name(row["store_name"])} for row in stores}
    zones, cameras = {}, {}
    for row in [*current, *historical]:
        sid, cid = _positive_id(row.get("store_id")), _positive_id(row.get("camera_id"))
        store_name, camera_name, zone_name = (_safe_name(row.get(key)) for key in ("store_name", "camera_name", "zone_name"))
        if sid and sid not in store_map:
            store_map[sid] = {"id": sid, "store_name": store_name}
        if zone_name:
            zones[(sid, zone_name)] = {"store_id": sid, "zone_name": zone_name}
        if cid:
            cameras[(cid, sid, zone_name, camera_name)] = {"id": cid, "camera_id": cid, "camera_name": camera_name,
                                                         "store_id": sid, "zone_name": zone_name}
    for row in employees:
        for key in ("student_code", "full_name", "faculty", "class_name"):
            row[key] = _safe_name(row.get(key))
        row["department"] = row["faculty"]
    departments = sorted({row["department"] for row in employees if row["department"]})
    return {"stores": sorted(store_map.values(), key=lambda row: (row["store_name"], row["id"])),
            "zones": sorted(zones.values(), key=lambda row: (row["store_id"] or 0, row["zone_name"])),
            "cameras": sorted(cameras.values(), key=lambda row: (row["store_id"] or 0, row["camera_name"], row["id"], row["zone_name"])),
            "employees": employees, "departments": [{"department": value} for value in departments]}

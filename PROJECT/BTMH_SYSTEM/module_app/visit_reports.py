"""Scoped reports from real entrance INs and canonical assigned-shift records.

No visitor observation/presence session is a visit or working-hours estimate.
Frozen visit dates/timezones/names retain their historical meaning. Current
configuration describes readiness only; it does not prove past camera uptime.
Management latest rows contain INTERNAL detail_json for the API's existing safe
serializer, and must not be returned directly to a browser.
"""
from __future__ import annotations

from datetime import date as CalendarDate, datetime, time, timedelta, timezone
import json
import math
import re
from zoneinfo import ZoneInfo

from . import db
from .demo_context import _positive_id, _safe_name, validate_entrance_config

REPORT_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")
_VERIFIED = "(e.status='RECOGNIZED' AND e.anti_spoof_passed=1 AND e.student_id IS NOT NULL)"


def _utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("REPORT_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _day(value, now):
    if value is None or value == "":
        return now.astimezone(REPORT_ZONE).date()
    if isinstance(value, CalendarDate) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("INVALID_REPORT_DATE")
    try:
        return CalendarDate.fromisoformat(value)
    except ValueError:
        raise ValueError("INVALID_REPORT_DATE") from None


def _scope(allowed_store_ids, store_id):
    scope = None if allowed_store_ids is None else frozenset(
        value for value in (_positive_id(item) for item in allowed_store_ids) if value is not None)
    wanted = _positive_id(store_id) if store_id is not None else None
    if store_id is not None and wanted is None:
        raise ValueError("INVALID_REPORT_STORE")
    if wanted is not None and scope is not None and wanted not in scope:
        raise PermissionError("STORE_SCOPE_DENIED")
    return scope, wanted


def _store_sql(column, scope, wanted):
    if wanted is not None:
        return column + "=?", [wanted]
    if scope is None:
        return "1=1", []
    if not scope:
        return "1=0", []
    return column + " IN (" + ",".join("?" for _ in scope) + ")", sorted(scope)


def _comparison(selected, previous):
    delta = selected - previous
    percent = round(delta * 100.0 / previous, 1) if previous else None if selected else 0.0
    state = "UNCHANGED" if not delta else "NEW_ACTIVITY" if not previous else "INCREASE" if delta > 0 else "DECREASE"
    return {"selected": selected, "previous": previous, "delta": delta, "percent": percent, "change_state": state}


def _hourly():
    return [{"hour": hour, "selected": 0, "previous": 0} for hour in range(24)]


def _configuration(conn, scope, wanted):
    store_clause, store_params = _store_sql("s.id", scope, wanted)
    stores = {int(row["id"]): {"current_store_name": _safe_name(row["store_name"]),
              "current_timezone_name": row["timezone_name"], "configured_camera_ids": []}
              for row in (dict(item) for item in conn.execute(
                  "SELECT s.id,s.store_name,s.timezone_name FROM stores s WHERE " + store_clause + " ORDER BY s.id",
                  store_params).fetchall())}
    assignment_clause, assignment_params = _store_sql("a.store_id", scope, wanted)
    cameras = conn.execute("SELECT c.id,c.zone_name,c.enabled,c.ai_enabled,c.visitor_counting_enabled,c.entrance_config_json,"
                           "a.store_id FROM camera_devices c JOIN camera_store_assignments a ON a.camera_device_id=c.id "
                           "WHERE " + assignment_clause + " AND (SELECT COUNT(*) FROM camera_store_assignments n "
                           "WHERE n.camera_device_id=c.id)=1 ORDER BY c.id", assignment_params).fetchall()
    for raw in cameras:
        row = dict(raw)
        sid = _positive_id(row["store_id"])
        try:
            valid = validate_entrance_config(json.loads(row.get("entrance_config_json") or "{}"))["enabled"]
            ZoneInfo(stores[sid]["current_timezone_name"])
        except (ValueError, TypeError, KeyError):
            continue
        if valid and row["enabled"] and row["ai_enabled"] and row["visitor_counting_enabled"] and row.get("zone_name"):
            stores[sid]["configured_camera_ids"].append(int(row["id"]))
    return stores


def query_visits_report(date=None, *, allowed_store_ids=None, store_id=None, now=None):
    """Compare a selected local business date with the previous date.

    Hour groups are formed in SQL by UTC minute, then converted using each row's
    frozen timezone. This keeps half/quarter-hour offsets correct without loading
    individual visits, and coalesces DST's repeated hour into 24 display buckets.
    Runtime admission/online state is added by the API, which can downgrade the
    configuration readiness and recompute/suppress extremes accordingly.
    """
    current = _utc(now)
    day = _day(date, current)
    try:
        previous = day - timedelta(days=1)
    except OverflowError:
        raise ValueError("INVALID_REPORT_DATE") from None
    scope, wanted = _scope(allowed_store_ids, store_id)
    hourly = _hourly()
    report = {"date": day.isoformat(), "comparison_date": previous.isoformat(), "generated_at": current.isoformat(),
              "source": "ENTRANCE_VALID_IN", "legacy_observations_used": False, "comparison_mode": "DAY_TOTALS",
              "timezone_policy": "FROZEN_VISIT_CONTEXT", "historical_coverage_known": False,
              "totals": _comparison(0, 0), "hourly": hourly, "stores": [], "configuration_state": "UNCONFIGURED",
              "configured_counting_cameras": 0, "configured_store_count": 0, "store_count": 0,
              "max_rise": None, "max_fall": None, "selected_day_in_progress": False}
    if scope == frozenset():
        report["reason"] = "NO_AUTHORIZED_STORES"
        return report
    clause, params = _store_sql("v.store_id", scope, wanted)
    with db.connection() as conn:
        stores = _configuration(conn, scope, wanted)
        groups = [dict(row) for row in conn.execute(
            "SELECT v.store_id,v.business_date,v.timezone_name,v.store_name,SUBSTR(v.entered_at,1,16) AS utc_minute,"
            "COUNT(*) AS visits,MAX(v.entered_at) AS latest_at FROM entrance_visits v WHERE " + clause +
            " AND v.visit_status='VISITOR' AND v.business_date IN (?,?) AND v.entered_at<=? "
            "GROUP BY v.store_id,v.business_date,v.timezone_name,v.store_name,SUBSTR(v.entered_at,1,16)",
            [*params, day.isoformat(), previous.isoformat(), current.isoformat()]).fetchall()]
    snapshots = {}
    for group in groups:
        sid, count = int(group["store_id"]), int(group["visits"])
        item = stores.setdefault(sid, {"current_store_name": None, "current_timezone_name": None, "configured_camera_ids": []})
        item.setdefault("hourly", _hourly())
        item.setdefault("selected", 0); item.setdefault("previous", 0); item.setdefault("hourly_unknown", 0)
        key = "selected" if group["business_date"] == day.isoformat() else "previous"
        item[key] += count
        snapshot_key = (sid, key)
        if snapshot_key not in snapshots or group["latest_at"] > snapshots[snapshot_key]["latest_at"]:
            snapshots[snapshot_key] = group
        try:
            stamp = _utc(group["utc_minute"] + ":00+00:00")
            hour = stamp.astimezone(ZoneInfo(group["timezone_name"])).hour
            item["hourly"][hour][key] += count
            hourly[hour][key] += count
        except (ValueError, TypeError, KeyError):
            item["hourly_unknown"] += count
    rows = []
    for sid, item in sorted(stores.items()):
        selected_snapshot, previous_snapshot = snapshots.get((sid, "selected"), {}), snapshots.get((sid, "previous"), {})
        zone_name = selected_snapshot.get("timezone_name") or previous_snapshot.get("timezone_name") or item["current_timezone_name"]
        try:
            local_day = current.astimezone(ZoneInfo(zone_name)).date()
            day_state = "IN_PROGRESS" if day == local_day else "COMPLETE" if day < local_day else "FUTURE"
        except (ValueError, TypeError, KeyError):
            day_state = "UNKNOWN"
        selected_name = _safe_name(selected_snapshot.get("store_name")) if selected_snapshot else None
        previous_name = _safe_name(previous_snapshot.get("store_name")) if previous_snapshot else None
        configured = bool(item["configured_camera_ids"])
        rows.append({"store_id": sid, "store_name": selected_name or previous_name or item["current_store_name"],
                     "selected_store_name": selected_name, "previous_store_name": previous_name,
                     "current_store_name": item["current_store_name"], "timezone_name": _safe_name(zone_name, 80),
                     **_comparison(item.get("selected", 0), item.get("previous", 0)), "hourly": item.get("hourly", _hourly()),
                     "hourly_unknown": item.get("hourly_unknown", 0), "selected_day_state": day_state,
                     "configured_camera_ids": item["configured_camera_ids"],
                     "configuration_state": "READY" if configured else "UNCONFIGURED",
                     "comparison_eligible": configured and not item.get("hourly_unknown", 0),
                     "historical_data_available": bool(item.get("selected", 0) or item.get("previous", 0))})
    configured_count = sum(row["configuration_state"] == "READY" for row in rows)
    report.update(stores=rows, store_count=len(rows), configured_store_count=configured_count,
                  configured_counting_cameras=sum(len(row["configured_camera_ids"]) for row in rows),
                  configuration_state="UNCONFIGURED" if not configured_count else "READY" if configured_count == len(rows) else "PARTIAL",
                  selected_day_in_progress=any(row["selected_day_state"] == "IN_PROGRESS" for row in rows),
                  totals=_comparison(sum(row["selected"] for row in rows), sum(row["previous"] for row in rows)))
    for name, direction in (("max_rise", 1), ("max_fall", -1)):
        eligible = [row for row in rows if row["comparison_eligible"] and row["delta"] * direction > 0]
        if eligible:
            winner = max(eligible, key=lambda row: (row["delta"] * direction, -row["store_id"]))
            report[name] = {key: winner[key] for key in ("store_id", "store_name", "selected", "previous", "delta", "percent", "change_state")}
    return report


def _table_columns(conn, table):
    if conn.mode == "postgres":
        return {dict(row)["column_name"] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (table,)).fetchall()}
    return {dict(row)["name"] for row in conn.execute("PRAGMA table_info(" + table + ")").fetchall()}


def _event_where(day, scope, wanted, now):
    clause, params = _store_sql("e.store_id", scope, wanted)
    try:
        first = datetime.combine(day, time.min, REPORT_ZONE).astimezone(timezone.utc).isoformat()
        last = datetime.combine(day + timedelta(days=1), time.min, REPORT_ZONE).astimezone(timezone.utc).isoformat()
    except OverflowError:
        raise ValueError("INVALID_REPORT_DATE") from None
    return (clause + " AND (e.business_date=? OR (e.business_date IS NULL AND e.event_at>=? AND e.event_at<?)) "
            "AND e.event_at<=?", [*params, day.isoformat(), first, last, now.isoformat()])


def query_management_summary(date=None, *, allowed_store_ids=None, store_id=None, now=None):
    """API-internal DTO. Latest detail_json must pass through the public serializer."""
    current = _utc(now)
    day = _day(date, current)
    scope, wanted = _scope(allowed_store_ids, store_id)
    visits = query_visits_report(day, allowed_store_ids=scope, store_id=wanted, now=current)
    empty_attendance = {"scheduled_shifts": 0, "present_shifts": 0, "late_cases": 0, "absent_days": 0,
                        "pending_shifts": 0, "missing_out": 0, "early_leave_cases": 0, "configured": False}
    result = {"date": day.isoformat(), "generated_at": current.isoformat(), "attendance_policy": "ASSIGNED_EFFECTIVE_SHIFT",
              "attendance": empty_attendance, "employee_with_valid_data_today": 0,
              "incidents": {"open": None, "count_known": False}, "latest": [], "visits": visits,
              "employees": {"total": 0, "faceid": 0, "faceid_coverage_percent": 0.0},
              "recognition": {"recognized_events": 0, "unknown_events": 0, "spoof_blocked_events": 0},
              "unknown_attribution_excluded": scope is not None or wanted is not None}
    if scope == frozenset():
        return result
    from .shift_attendance import build_shift_attendance_report
    attendance = build_shift_attendance_report(day, day, allowed_store_ids=scope, store_id=wanted, now=current)
    event_clause, event_params = _event_where(day, scope, wanted, current)
    assignment_clause, assignment_params = _store_sql("h.store_id", scope, wanted)
    employee_clause, employee_params = "1=1", []
    if scope is not None or wanted is not None:
        current_clause, current_params = _store_sql("a.store_id", scope, wanted)
        employee_clause = ("EXISTS(SELECT 1 FROM employee_store_assignments a WHERE a.student_id=s.id AND " + current_clause + ") "
                           "OR EXISTS(SELECT 1 FROM employee_shift_assignment_history h WHERE h.student_id=s.id AND " +
                           assignment_clause + " AND h.effective_from<=? AND (h.effective_to IS NULL OR h.effective_to>=?))")
        employee_params = [*current_params, *assignment_params, day.isoformat(), day.isoformat()]
    with db.connection() as conn:
        configured = int(dict(conn.execute("SELECT COUNT(*) AS n FROM employee_shift_assignment_history h WHERE " +
                                          assignment_clause + " AND h.effective_from<=? AND (h.effective_to IS NULL OR h.effective_to>=?)",
                                          [*assignment_params, day.isoformat(), day.isoformat()]).fetchone())["n"]) > 0
        counts = dict(conn.execute("SELECT SUM(CASE WHEN " + _VERIFIED + " THEN 1 ELSE 0 END) AS recognized_events,"
                                  "SUM(CASE WHEN e.status='UNREGISTERED' THEN 1 ELSE 0 END) AS unknown_events,"
                                  "SUM(CASE WHEN e.status='SPOOF_BLOCKED' THEN 1 ELSE 0 END) AS spoof_blocked_events,"
                                  "COUNT(DISTINCT CASE WHEN " + _VERIFIED + " THEN e.student_id END) AS verified_employees "
                                  "FROM recognition_events e WHERE " + event_clause, event_params).fetchone())
        latest = [dict(row) for row in conn.execute(
            "SELECT e.id,e.student_id,e.camera_id,e.store_id,e.zone_name,e.camera_name,e.store_name,e.status,e.confidence,"
            "e.liveness_score,e.anti_spoof_passed,e.event_at,e.business_date,e.daily_sequence,e.appearance_id,e.detail_json,"
            "s.student_code,s.full_name,s.faculty,s.class_name FROM recognition_events e LEFT JOIN students s ON s.id=e.student_id "
            "WHERE " + event_clause + " ORDER BY e.id DESC LIMIT 12", event_params).fetchall()]
        employees = dict(conn.execute("SELECT COUNT(*) AS total,SUM(CASE WHEN EXISTS(SELECT 1 FROM face_templates f WHERE "
                                      "f.student_id=s.id) THEN 1 ELSE 0 END) AS faceid FROM students s WHERE " + employee_clause,
                                      employee_params).fetchone())
        incident_columns = _table_columns(conn, "incidents")
        if "status" in incident_columns and (scope is None and wanted is None or "store_id" in incident_columns):
            incident_clause, incident_params = _store_sql("i.store_id", scope, wanted) if "store_id" in incident_columns else ("1=1", [])
            incident_count = int(dict(conn.execute("SELECT COUNT(*) AS n FROM incidents i WHERE " + incident_clause +
                                                  " AND UPPER(i.status) NOT IN ('CLOSED','RESOLVED')", incident_params).fetchone())["n"])
            result["incidents"] = {"open": incident_count, "count_known": True,
                                   "unknown_attribution_excluded": scope is not None or wanted is not None}
    for row in latest:
        for key in ("zone_name", "camera_name", "store_name", "student_code", "full_name", "faculty", "class_name"):
            row[key] = _safe_name(row[key]) if row.get(key) is not None else None
        for key in ("confidence", "liveness_score"):
            try:
                value = float(row.get(key) or 0)
                row[key] = value if math.isfinite(value) else 0.0
            except (ValueError, TypeError, OverflowError):
                row[key] = 0.0
    total, enrolled = int(employees["total"]), int(employees["faceid"] or 0)
    result.update(attendance={**attendance["totals"], "configured": configured},
                  employee_with_valid_data_today=int(counts["verified_employees"] or 0), latest=latest,
                  employees={"total": total, "faceid": enrolled, "faceid_coverage_percent": round(enrolled * 100.0 / total, 1) if total else 0.0},
                  recognition={key: int(counts[key] or 0) for key in ("recognized_events", "unknown_events", "spoof_blocked_events")})
    return result

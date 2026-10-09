from __future__ import annotations

import json
import math
import zipfile
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from .db import execute, fetchall, fetchone, utc_now

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SHIFT_KEY = "hr_shift_policy_v212"

DEFAULT_SHIFT_POLICY = {
    "enabled": False,
    "name": "Ca hành chính",
    "start_time": "08:00",
    "end_time": "17:30",
    "break_start": "12:00",
    "break_end": "13:30",
    "late_grace_minutes": 10,
    "early_leave_grace_minutes": 10,
    "workdays": [0, 1, 2, 3, 4],
}


def _parse_dt(value: Any) -> datetime | None:
    try:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_hhmm(value: str, fallback: str) -> tuple[int, int]:
    try:
        parts = str(value or fallback).strip().split(":")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h, m
    except Exception:
        h, m = fallback.split(":")
        return int(h), int(m)


def _clean_policy(values: dict | None) -> dict:
    raw = {**DEFAULT_SHIFT_POLICY, **(values or {})}
    workdays = []
    for item in raw.get("workdays") or DEFAULT_SHIFT_POLICY["workdays"]:
        try:
            n = int(item)
            if 0 <= n <= 6 and n not in workdays:
                workdays.append(n)
        except Exception:
            continue
    if not workdays:
        workdays = list(DEFAULT_SHIFT_POLICY["workdays"])
    sh, sm = _parse_hhmm(str(raw.get("start_time") or ""), "08:00")
    eh, em = _parse_hhmm(str(raw.get("end_time") or ""), "17:30")
    bh, bm = _parse_hhmm(str(raw.get("break_start") or ""), "12:00")
    ch, cm = _parse_hhmm(str(raw.get("break_end") or ""), "13:30")
    return {
        "enabled": bool(raw.get("enabled")),
        "name": str(raw.get("name") or "Ca hành chính").strip()[:80] or "Ca hành chính",
        "start_time": f"{sh:02d}:{sm:02d}",
        "end_time": f"{eh:02d}:{em:02d}",
        "break_start": f"{bh:02d}:{bm:02d}",
        "break_end": f"{ch:02d}:{cm:02d}",
        "late_grace_minutes": max(0, min(180, int(raw.get("late_grace_minutes") or 0))),
        "early_leave_grace_minutes": max(0, min(180, int(raw.get("early_leave_grace_minutes") or 0))),
        "workdays": sorted(workdays),
    }


def shift_policy() -> dict:
    row = fetchone("SELECT setting_value FROM runtime_settings WHERE setting_key=?", (SHIFT_KEY,))
    if not row:
        return dict(DEFAULT_SHIFT_POLICY)
    try:
        data = json.loads(str(row.get("setting_value") or "{}")) or {}
    except Exception:
        data = {}
    return _clean_policy(data)


def save_shift_policy(values: dict) -> dict:
    clean = _clean_policy(values)
    now = utc_now()
    payload = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    if fetchone("SELECT setting_key FROM runtime_settings WHERE setting_key=?", (SHIFT_KEY,)):
        execute("UPDATE runtime_settings SET setting_value=?,updated_at=? WHERE setting_key=?", (payload, now, SHIFT_KEY))
    else:
        execute("INSERT INTO runtime_settings(setting_key,setting_value,updated_at) VALUES(?,?,?)", (SHIFT_KEY, payload, now))
    return clean


def _period_range(period: str, anchor: str | None = None) -> tuple[datetime, datetime, date, str]:
    p = str(period or "day").lower().strip()
    if p not in {"day", "week", "month"}:
        p = "day"
    try:
        d = date.fromisoformat(str(anchor or ""))
    except Exception:
        d = datetime.now(VN_TZ).date()
    if p == "week":
        start_date = d - timedelta(days=d.weekday())
        end_date = start_date + timedelta(days=7)
        label = f"{start_date.strftime('%d/%m/%Y')} - {(end_date - timedelta(days=1)).strftime('%d/%m/%Y')}"
    elif p == "month":
        start_date = d.replace(day=1)
        days = monthrange(start_date.year, start_date.month)[1]
        end_date = start_date + timedelta(days=days)
        label = start_date.strftime("Tháng %m/%Y")
    else:
        start_date = d
        end_date = d + timedelta(days=1)
        label = d.strftime("%d/%m/%Y")
    start_local = datetime.combine(start_date, time.min, VN_TZ)
    end_local = datetime.combine(end_date, time.min, VN_TZ)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), start_date, label


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    a = datetime.combine(d, time.min, VN_TZ)
    return a, a + timedelta(days=1)


def _split_local_days(start_utc: datetime, end_utc: datetime) -> list[tuple[date, datetime, datetime]]:
    if end_utc <= start_utc:
        return []
    start_local = start_utc.astimezone(VN_TZ)
    end_local = end_utc.astimezone(VN_TZ)
    out = []
    current = start_local.date()
    while current <= end_local.date():
        ds, de = _day_bounds(current)
        seg_start = max(start_local, ds)
        seg_end = min(end_local, de)
        if seg_end > seg_start:
            out.append((current, seg_start, seg_end))
        current += timedelta(days=1)
    return out


def _shift_times_for_day(d: date, policy: dict) -> dict:
    sh, sm = _parse_hhmm(policy["start_time"], "08:00")
    eh, em = _parse_hhmm(policy["end_time"], "17:30")
    bh, bm = _parse_hhmm(policy["break_start"], "12:00")
    ch, cm = _parse_hhmm(policy["break_end"], "13:30")
    start = datetime.combine(d, time(sh, sm), VN_TZ)
    end = datetime.combine(d, time(eh, em), VN_TZ)
    if end <= start:
        end += timedelta(days=1)
    break_start = datetime.combine(d, time(bh, bm), VN_TZ)
    break_end = datetime.combine(d, time(ch, cm), VN_TZ)
    break_sec = max(0.0, (break_end - break_start).total_seconds()) if start <= break_start < break_end <= end else 0.0
    expected = max(0.0, (end - start).total_seconds() - break_sec)
    return {"start": start, "end": end, "expected_sec": expected}


def _fmt_seconds(seconds: float) -> str:
    total = max(0, int(round(float(seconds or 0))))
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m:02d}p"


def _fmt_time(dt: datetime | None) -> str:
    return dt.astimezone(VN_TZ).strftime("%H:%M") if dt else "—"


def build_hr_report(period: str = "day", anchor: str | None = None, *, allowed_store_ids=None,
                    store_id=None, now=None) -> dict:
    """Assigned-shift facts and separately named observation evidence.

    Legacy presence has no immutable store attribution. Restricted/store-filtered
    reports omit that evidence rather than joining today's mutable camera map.
    """
    from .shift_attendance import build_shift_attendance_report, _utc
    start_utc, end_utc, start_date, label = _period_range(period, anchor)
    current = _utc(now)
    last_date = (end_utc - timedelta(microseconds=1)).astimezone(VN_TZ).date()
    attendance = build_shift_attendance_report(start_date, last_date, allowed_store_ids=allowed_store_ids,
                                             store_id=store_id, now=current)
    store_scope = None if allowed_store_ids is None else sorted({int(value) for value in allowed_store_ids})
    if store_id is not None:
        store_scope = [int(store_id)]
    if store_scope is None:
        employees = fetchall("SELECT id,student_code,full_name,class_name,faculty FROM students ORDER BY full_name,student_code")
    elif not store_scope:
        employees = []
    else:
        marks = ",".join("?" for _ in store_scope)
        employees = fetchall("SELECT s.id,s.student_code,s.full_name,s.class_name,s.faculty FROM students s WHERE "
                             "EXISTS(SELECT 1 FROM employee_store_assignments a WHERE a.student_id=s.id AND a.store_id IN (" + marks + ")) "
                             "OR EXISTS(SELECT 1 FROM employee_shift_assignment_history h WHERE h.student_id=s.id AND h.store_id IN (" + marks + ") "
                             "AND h.effective_from<=? AND (h.effective_to IS NULL OR h.effective_to>=?)) ORDER BY s.full_name,s.student_code",
                             (*store_scope, *store_scope, last_date.isoformat(), start_date.isoformat()))
    by_employee = {}
    for row in attendance["rows"]:
        by_employee.setdefault(row["employee_id"], []).append(row)
    observation_available = store_scope is None
    observation = {}
    if observation_available:
        # last_seen is the last observation, not the report clock or a checkout.
        for row in fetchall("SELECT student_id,started_at,last_seen_at FROM hr_presence_sessions "
                            "WHERE started_at<? AND last_seen_at>=? ORDER BY started_at", (end_utc.isoformat(), start_utc.isoformat())):
            first, last = _parse_dt(row["started_at"]), _parse_dt(row["last_seen_at"])
            if first and last and last >= first:
                observation.setdefault(int(row["student_id"]), []).append((max(first, start_utc), min(last, end_utc, current)))
    rows = []
    labels = {"ABSENT": "Vắng", "NOT_YET_DUE": "Chưa đến thời điểm kết luận", "MISSING_OUT": "Chưa ghi nhận ra",
              "IN_PROGRESS": "Đang trong ca", "LATE": "Đi muộn", "PRESENT": "Có mặt"}
    for employee in employees:
        employee_id = int(employee["id"])
        instances = sorted(by_employee.get(employee_id, []), key=lambda row: row["business_date"])
        admitted = [row for row in instances if row["checkin_at"]]
        latest = admitted[-1] if admitted else instances[-1] if instances else None
        first = min((_utc(row["checkin_at"]) for row in admitted), default=None)
        last_seen = max((_utc(row["last_seen_at"]) for row in instances if row.get("last_seen_at")), default=None)
        checkout = latest.get("checkout_at") if latest else None
        late = sum(row["late"] is True for row in instances) if instances else None
        early = sum(row["early_leave"] is True for row in instances) if instances else None
        absent = sum(row["status"] == "ABSENT" for row in instances) if instances else None
        if not instances:
            status = "Chưa có ca được gán"
        elif any(row["status"] == "MISSING_OUT" for row in instances):
            status = labels["MISSING_OUT"]
        elif not admitted:
            status = labels["ABSENT"] if absent and all(row["status"] == "ABSENT" for row in instances) else labels["NOT_YET_DUE"]
        elif late:
            status = labels["LATE"]
        elif early:
            status = "Rời sớm"
        else:
            status = labels[latest["status"]]
        merged = []
        for first_observed, last_observed in sorted(observation.get(employee_id, [])):
            if last_observed <= first_observed:
                continue
            if not merged or first_observed > merged[-1][1]:
                merged.append([first_observed, last_observed])
            elif last_observed > merged[-1][1]:
                merged[-1][1] = last_observed
        observed_seconds = sum((last - first).total_seconds() for first, last in merged) if observation_available else None
        zone = ZoneInfo(latest["timezone_name"]) if latest else VN_TZ
        def display(value):
            return _utc(value).astimezone(zone).strftime("%d/%m %H:%M:%S") if value else "—"
        rows.append({"student_id": employee_id, "employee_code": employee["student_code"], "full_name": employee["full_name"],
                     "department": employee["faculty"], "position": employee["class_name"], "first_seen": display(first),
                     "last_seen": display(last_seen), "checkin_at": first.isoformat() if first else None, "checkout_at": checkout,
                     "checkout_text": display(checkout) if checkout else "Chưa ghi nhận ra", "last_seen_at": last_seen.isoformat() if last_seen else None,
                     "checkout_source": latest.get("checkout_source") if latest else None,
                     "camera_first_seen": display(first), "camera_last_seen": display(last_seen),
                     "attendance_adjusted": any(row["attendance_adjusted"] for row in instances),
                     "shift_name": latest.get("shift_name") if latest else "", "shift_start": latest.get("expected_start_at") if latest else None,
                     "shift_end": latest.get("expected_end_at") if latest else None, "assignment_state": "ASSIGNED" if instances else "UNASSIGNED",
                     "presence_seconds": observed_seconds, "presence_text": _fmt_seconds(observed_seconds) if observed_seconds is not None else "Chưa có dữ liệu quan sát theo cửa hàng",
                     "outside_seconds": None, "outside_text": "Chưa đủ dữ liệu", "session_count": len(merged) if observation_available else None,
                     "out_count": sum(bool(row.get("raw_checkout_at")) for row in instances), "present_days": len(admitted),
                     "absent_days": absent, "late_days": late, "early_leave_days": early, "compliance_percent": None, "status": status})
    totals = {**attendance["totals"], "employee_count": len(rows), "present_employees": sum(row["present_days"] > 0 for row in rows),
              "absent_employees": sum(row["status"] == "Vắng" for row in rows), "not_recorded_employees": sum(row["present_days"] == 0 for row in rows),
              "unassigned_employees": sum(row["assignment_state"] == "UNASSIGNED" for row in rows),
              "presence_seconds": sum(row["presence_seconds"] or 0 for row in rows) if observation_available else None,
              "outside_seconds": None, "outside_text": "Chưa đủ dữ liệu", "out_events": sum(row["out_count"] for row in rows),
              "present_days": attendance["totals"]["present_shifts"]}
    totals["presence_text"] = _fmt_seconds(totals["presence_seconds"]) if observation_available else "Chưa có dữ liệu quan sát theo cửa hàng"
    return {"period": str(period or "day").lower(), "anchor": start_date.isoformat(), "label": label,
            "generated_at": current.isoformat(), "timezone": "Asia/Ho_Chi_Minh", "shift_policy": shift_policy(),
            "attendance_policy": "ASSIGNED_EFFECTIVE_SHIFT", "observation_available": observation_available,
            "presence_label": "Thời gian giữa các quan sát; không phải giờ làm", "totals": totals, "rows": rows,
            "attendance_rows": attendance["rows"]}


def _xml_escape(value: Any) -> str:
    return escape(str(value if value is not None else ""), quote=False)


def _xlsx_sheet_xml(data: list[list[Any]]) -> str:
    def col_name(n: int) -> str:
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s
    rows = []
    for r_idx, row in enumerate(data, 1):
        cells = []
        for c_idx, value in enumerate(row, 1):
            ref = f"{col_name(c_idx)}{r_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{_xml_escape(value)}</t></is></c>')
        rows.append(f'<row r="{r_idx}">' + "".join(cells) + "</row>")
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' \
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' \
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/>' \
        '<sheetData>' + "".join(rows) + '</sheetData></worksheet>'


def report_xlsx_bytes(report: dict) -> bytes:
    rows = report.get("rows") or []
    summary = [
        ["CampusFace - Báo cáo nhân sự"],
        ["Kỳ báo cáo", report.get("label")],
        ["Múi giờ", report.get("timezone")],
        ["Nhân viên", int((report.get("totals") or {}).get("employee_count") or 0)],
        ["Có mặt", int((report.get("totals") or {}).get("present_employees") or 0)],
        ["Chưa ghi nhận", int((report.get("totals") or {}).get("absent_employees") or 0)],
        ["Khoảng thời gian quan sát (không phải giờ làm)", (report.get("totals") or {}).get("presence_text")],
        ["Tổng ra ngoài", (report.get("totals") or {}).get("outside_text")],
        [],
        ["Mã NV", "Họ tên", "Phòng ban", "Chức vụ/Bộ phận", "Giờ vào", "Lần ghi nhận cuối", "Giờ ra / điều chỉnh đã duyệt", "Khoảng quan sát", "Ra ngoài", "Phiên", "OUT", "Ngày có mặt", "Đi muộn", "Rời sớm", "Tuân thủ %", "Trạng thái"],
    ]
    for r in rows:
        summary.append([
            r.get("employee_code"), r.get("full_name"), r.get("department"), r.get("position"),
            r.get("first_seen"), r.get("last_seen"), r.get("checkout_text"), r.get("presence_text"), r.get("outside_text"),
            int(r.get("session_count") or 0), int(r.get("out_count") or 0), int(r.get("present_days") or 0),
            r.get("late_days") if r.get("late_days") is not None else "Chưa gán ca", r.get("early_leave_days") if r.get("early_leave_days") is not None else "Chưa gán ca",
            r.get("compliance_percent") if r.get("compliance_percent") is not None else "—", r.get("status"),
        ])
    shift = [["Ca đã gán theo ngày hiệu lực; ngày làm việc là ngày bắt đầu ca"],
             ["Nhân viên", "Cửa hàng", "Ngày làm việc", "Ca", "Bắt đầu", "Kết thúc", "Grace muộn (phút)", "Grace về sớm (phút)"]]
    for instance in report.get("attendance_rows") or []:
        shift.append([instance.get("employee_code"), instance.get("store_name"), instance.get("business_date"), instance.get("shift_name"),
                      instance.get("expected_start_at_local"), instance.get("expected_end_at_local"), instance.get("late_grace_minutes"), instance.get("early_leave_grace_minutes")])
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Báo cáo" sheetId="1" r:id="rId1"/><sheet name="Ca làm việc" sheetId="2" r:id="rId2"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet_xml(summary))
        z.writestr("xl/worksheets/sheet2.xml", _xlsx_sheet_xml(shift))
    return out.getvalue()


def report_print_html(report: dict) -> str:
    totals = report.get("totals") or {}
    rows = report.get("rows") or []
    policy = report.get("shift_policy") or {}
    body_rows = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td>{escape(str(r.get('employee_code') or ''))}</td>"
            f"<td><b>{escape(str(r.get('full_name') or ''))}</b></td>"
            f"<td>{escape(str(r.get('department') or '—'))}</td>"
            f"<td>{escape(str(r.get('first_seen') or '—'))}</td>"
            f"<td>{escape(str(r.get('last_seen') or '—'))}</td>"
            f"<td>{escape(str(r.get('checkout_text') or 'Chưa ghi nhận ra'))}</td>"
            f"<td>{escape(str(r.get('presence_text') or '—'))}</td>"
            f"<td>{escape(str(r.get('outside_text') or '—'))}</td>"
            f"<td>{escape(str(r.get('late_days') if r.get('late_days') is not None else 'Chưa gán ca'))}</td>"
            f"<td>{escape(str(r.get('status') or ''))}</td>"
            "</tr>"
        )
    shift_text = "Theo ca đã gán và ngày hiệu lực; không dùng lịch mặc định để kết luận"
    return f'''<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>CampusFace - Báo cáo nhân sự</title>
<style>body{{font-family:Arial,"Segoe UI",sans-serif;color:#152d2b;margin:28px}}h1{{margin:0 0 4px;font-size:24px}}.muted{{color:#6b7c7a}}.kpi{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:18px 0}}.kpi div{{border:1px solid #dce7e5;border-radius:10px;padding:10px}}.kpi b{{display:block;font-size:20px;margin-top:4px}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{border-bottom:1px solid #e2e9e8;padding:8px;text-align:left}}th{{background:#f2f7f6}}.foot{{margin-top:16px;font-size:10px;color:#71827f}}@media print{{button{{display:none}}body{{margin:12mm}}}}</style></head><body>
<h1>CampusFace · Báo cáo nhân sự</h1><div class="muted">Kỳ báo cáo: {escape(str(report.get('label') or ''))} · {escape(shift_text)}</div>
<div class="kpi"><div>Nhân viên<b>{int(totals.get('employee_count') or 0)}</b></div><div>Có mặt<b>{int(totals.get('present_employees') or 0)}</b></div><div>Tổng hiện diện<b>{escape(str(totals.get('presence_text') or '0h'))}</b></div><div>Đi muộn<b>{int(totals.get('late_cases') or 0)}</b></div></div>
<table><thead><tr><th>Mã NV</th><th>Họ tên</th><th>Phòng ban</th><th>Giờ vào</th><th>Lần ghi nhận cuối</th><th>Giờ ra / điều chỉnh đã duyệt</th><th>Khoảng quan sát</th><th>Ra ngoài</th><th>Muộn</th><th>Trạng thái</th></tr></thead><tbody>{''.join(body_rows)}</tbody></table>
<div class="foot">Tạo lúc {escape(str(report.get('generated_at') or ''))} · Khoảng giữa các quan sát không phải giờ làm. Giờ ra dùng OUT thật hoặc điều chỉnh có lý do/người duyệt.</div>
<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),180));</script></body></html>'''

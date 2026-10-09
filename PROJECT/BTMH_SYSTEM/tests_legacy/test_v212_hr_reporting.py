import json
import zipfile
import sys
from io import BytesIO
from pathlib import Path

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from module_app import hr_reporting as hr


def test_v212_hr_report_aggregates_presence_outside_late_early(monkeypatch):
    employees = [{"id": 1, "student_code": "NV001", "full_name": "Nguyen Van A", "class_name": "Ky su", "faculty": "Ky thuat"}]
    sessions = [
        {"id": 1, "student_id": 1, "camera_source": "cam01", "started_at": "2025-01-06T01:20:00+00:00", "last_seen_at": "2025-01-06T05:00:00+00:00", "ended_at": "2025-01-06T05:00:00+00:00", "duration_sec": 13200, "status": "CLOSED", "start_reason": "IN", "end_reason": "OUT"},
        {"id": 2, "student_id": 1, "camera_source": "cam01", "started_at": "2025-01-06T06:00:00+00:00", "last_seen_at": "2025-01-06T10:00:00+00:00", "ended_at": "2025-01-06T10:00:00+00:00", "duration_sec": 14400, "status": "CLOSED", "start_reason": "IN", "end_reason": "OUT"},
    ]
    crossings = [{"student_id": 1, "direction": "OUT", "event_at": "2025-01-06T05:30:00+00:00"}]
    policy = {**hr.DEFAULT_SHIFT_POLICY, "enabled": True, "late_grace_minutes": 10, "early_leave_grace_minutes": 10}

    def fake_fetchone(sql, params=()):
        if "runtime_settings" in sql:
            return {"setting_value": json.dumps(policy)}
        return None

    def fake_fetchall(sql, params=()):
        if "FROM students" in sql:
            return employees
        if "FROM hr_presence_sessions" in sql:
            return sessions
        if "FROM office_crossing_events" in sql:
            return crossings
        return []

    monkeypatch.setattr(hr, "fetchone", fake_fetchone)
    monkeypatch.setattr(hr, "fetchall", fake_fetchall)
    report = hr.build_hr_report("day", "2025-01-06")
    row = report["rows"][0]
    assert row["presence_seconds"] == 27600.0
    assert row["outside_seconds"] == 3600.0
    assert row["session_count"] == 2
    assert row["out_count"] == 1
    assert row["late_days"] == 1
    assert row["early_leave_days"] == 1
    assert "Đi muộn" in row["status"]
    assert report["totals"]["present_employees"] == 1


def test_v212_xlsx_and_print_exports_are_self_contained():
    report = {
        "label": "06/01/2025",
        "timezone": "Asia/Ho_Chi_Minh",
        "generated_at": "2025-01-06T10:00:00+00:00",
        "shift_policy": {**hr.DEFAULT_SHIFT_POLICY, "enabled": True},
        "totals": {"employee_count": 1, "present_employees": 1, "absent_employees": 0, "presence_text": "8h 00p", "outside_text": "1h 00p", "late_cases": 0},
        "rows": [{"employee_code": "NV001", "full_name": "Nguyen Van A", "department": "Ky thuat", "position": "Ky su", "first_seen": "08:00", "last_seen": "17:00", "presence_text": "8h 00p", "outside_text": "1h 00p", "session_count": 2, "out_count": 1, "present_days": 1, "late_days": 0, "early_leave_days": 0, "compliance_percent": 100, "status": "Đúng giờ"}],
    }
    data = hr.report_xlsx_bytes(report)
    assert data[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(data)) as z:
        assert "xl/workbook.xml" in z.namelist()
        assert "xl/worksheets/sheet1.xml" in z.namelist()
    html = hr.report_print_html(report)
    assert "CampusFace" in html
    assert "window.print" in html
    assert "Nguyen Van A" in html


def test_v212_static_ui_and_routes_contract():
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    css = (CORE / "frontend" / "css" / "professional_v23_hr_reporting.css").read_text(encoding="utf-8")
    for path in ["/api/v1/hr-report/summary", "/api/v1/hr-report/shift", "/api/v1/hr-report/export.xlsx", "/api/v1/hr-report/print"]:
        assert path in main
    assert 'data-page="hr-report"' in html
    assert 'id="page-hr-report"' in html
    assert 'id="globalCameraHandoverBadge"' in html  # V2.11 polish remains present
    assert "loadHrReport" in js
    assert ".hr-report-kpis" in css

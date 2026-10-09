from pathlib import Path

from module_app.office_engine import OfficeEngine


def test_virtual_gate_geometry():
    line = {"x1": 0.1, "y1": 0.5, "x2": 0.9, "y2": 0.5}
    assert OfficeEngine._signed_side((0.5, 0.75), line) > 0
    assert OfficeEngine._signed_side((0.5, 0.25), line) < 0
    assert OfficeEngine._side_name(0.03, 0.02) == "positive"
    assert OfficeEngine._side_name(-0.03, 0.02) == "negative"
    assert OfficeEngine._side_name(0.01, 0.02) == "deadband"


def test_office_anchor_normalized():
    p = OfficeEngine._track_anchor({"bbox": [100, 100, 200, 300]}, 1000, 1000, "person_center")
    assert p == (0.2, 0.25)
    b = OfficeEngine._track_anchor({"bbox": [100, 100, 200, 300]}, 1000, 1000, "bottom_center")
    assert b is not None and round(b[0], 4) == 0.2 and round(b[1], 4) == 0.364


def test_frontend_office_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (root / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'data-page="office"' in html
    assert 'id="page-office"' in html
    assert 'id="officeGateCanvas"' in html
    assert '/api/v1/office/config' in js
    assert '/api/v1/office/latest' in js
    assert 'Điều khiển PTZ</span></button>' not in html

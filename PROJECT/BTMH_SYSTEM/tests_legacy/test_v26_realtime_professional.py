from __future__ import annotations

from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def test_v26_professional_history_contract():
    office = (CORE / "module_app" / "office_engine.py").read_text(encoding="utf-8")
    main = (CORE / "module_app" / "main.py").read_text(encoding="utf-8")
    html = (CORE / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (CORE / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert '"close_on_camera_absence": False' in office
    assert '"persist_visibility_events": False' in office
    assert '"TRACK_TEMPORARILY_LOST"' in office
    assert '"TRACK_REACQUIRED"' in office
    assert '/api/v1/history/technical' in main
    assert 'business_types = {"PRESENCE_START", "PRESENCE_END", "ENTRY", "RETURN", "EXIT"}' in main
    assert 'id="historyHrSummaryPanel"' in html
    assert 'id="systemTechnicalList"' in html
    assert 'data-history-tab="EVENTS"' in html
    assert 'data-history-tab="SESSIONS"' in html
    assert 'data-history-tab="SUMMARY"' in html
    assert 'state.historyHrDailySummary=hr.daily_summary||[]' in js


def test_v26_realtime_lane_contract():
    config = (CORE / "module_app" / "config.py").read_text(encoding="utf-8")
    camera = (CORE / "module_app" / "camera.py").read_text(encoding="utf-8")
    assert 'MODULE_CLASSROOM_FACE_AI_FPS", "8"' in config
    assert 'MODULE_CLASSROOM_FACE_AI_WIDTH", "1280"' in config
    assert 'ai_lane = "PERSONNEL_TRACKING"' in camera
    assert 'CLASSROOM_FACE_AI_WIDTH' in camera
    assert '"pipeline_mode": "DECOUPLED_PREVIEW_TRACKING_ACTION"' in camera
    assert '"preview_server_age_ms"' in camera
    assert '"tracking_result_age_ms"' in camera


def test_v26_camera_handover_contract_preserved():
    camera = (CORE / "module_app" / "camera.py").read_text(encoding="utf-8")
    assert 'def safe_select_source' in camera
    assert 'rolled_back' in camera
    assert 'stable_frames' in camera
    assert '_capture_plan_cache' in camera
    assert 'generation == current' in camera

from pathlib import Path

CORE = Path(__file__).resolve().parents[1]


def test_v22_history_selector_is_prominent_and_cache_busted():
    html = (CORE / 'frontend' / 'index.html').read_text(encoding='utf-8')
    css = (CORE / 'frontend' / 'css' / 'professional_v15_history_split.css').read_text(encoding='utf-8')
    js = (CORE / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    assert 'class="history-split-switch panel" id="historyModeTabs"' in html
    assert '<b>Lịch sử nhận diện</b>' in html
    assert '<b>Theo dõi nhân sự</b>' in html
    assert 'professional_v15_history_split.css?v=2.3.0' in html
    assert ('app.js?v=2.3.0-professional-pilot' in html) or ('app.js?v=2.4.0-admin-mobile' in html)
    assert 'position:sticky' in css
    assert "window.scrollTo({top:0" in js
    assert "historyMode==='HR'" in js


def test_v22_history_backends_are_separate():
    js = (CORE / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
    main = (CORE / 'module_app' / 'main.py').read_text(encoding='utf-8')
    assert "/api/v1/history/recognition?limit=1200" in js
    assert "/api/v1/history/hr?limit=1200" in js
    assert '@app.get("/api/v1/history/recognition")' in main
    assert '@app.get("/api/v1/history/hr")' in main
    assert 'repeat_count' in main
    assert 'collapsed_repeats' in main


def test_v22_recognition_write_cooldowns_exist():
    db = (CORE / 'module_app' / 'db.py').read_text(encoding='utf-8')
    assert 'CAMPUSFACE_SAME_CAMERA_DEDUP_SEC", "60"' in db
    assert 'CAMPUSFACE_SPOOF_EVENT_DEDUP_SEC", "30"' in db
    assert 'CAMPUSFACE_UNKNOWN_EVENT_DEDUP_SEC", "30"' in db

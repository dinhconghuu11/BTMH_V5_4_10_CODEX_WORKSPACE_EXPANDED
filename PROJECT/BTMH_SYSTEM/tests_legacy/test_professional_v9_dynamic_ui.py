from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v9_dynamic_assets_and_markup():
    html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
    css = (ROOT / 'frontend' / 'css' / 'professional_v9_hero.css').read_text(encoding='utf-8')
    js = (ROOT / 'frontend' / 'js' / 'professional_v9_hero.js').read_text(encoding='utf-8')
    assert 'id="cfv9Hero"' in html
    assert 'id="cfv9Canvas"' in html
    assert 'V9 DYNAMIC UI' in html
    assert 'professional_v9_hero.css?v=9.0.0' in html
    assert 'professional_v9_hero.js?v=9.0.0' in html
    assert 'v8-hero' not in html
    assert '.cfv9-hero' in css
    assert '@keyframes cfv9Orbit' in css
    assert 'requestAnimationFrame' in js
    assert 'IntersectionObserver' in js


def test_v9_cache_guard_and_version():
    main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
    cfg = (ROOT / 'module_app' / 'config.py').read_text(encoding='utf-8')
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    assert '_campusface_ui_cache_guard' in main
    assert 'X-CampusFace-UI' in main
    assert '1.26.0-v1-face-pro-v9' in cfg
    assert version == '1.26.0-v1-face-pro-v9'

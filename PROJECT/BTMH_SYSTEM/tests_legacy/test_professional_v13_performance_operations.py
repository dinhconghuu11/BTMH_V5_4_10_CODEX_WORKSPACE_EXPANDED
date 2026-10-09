from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
config = (ROOT / 'module_app' / 'config.py').read_text(encoding='utf-8')
camera = (ROOT / 'module_app' / 'camera.py').read_text(encoding='utf-8')
main = (ROOT / 'module_app' / 'main.py').read_text(encoding='utf-8')
html = (ROOT / 'frontend' / 'index.html').read_text(encoding='utf-8')
js = (ROOT / 'frontend' / 'js' / 'app.js').read_text(encoding='utf-8')
css = (ROOT / 'frontend' / 'css' / 'professional_v13_operations.css').read_text(encoding='utf-8')
version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
start = (ROOT / 'START_CAMPUSFACE.bat').read_text(encoding='utf-8', errors='ignore')

assert version == '1.30.0-v1-face-pro-v13-performance-operations'
assert version in config
for token in (
    'PERFORMANCE_GUARD_ENABLED',
    'PERFORMANCE_GUARD_MIN_FPS',
    'PERFORMANCE_GUARD_ADJUST_SEC',
    'PERFORMANCE_GUARD_RECOVER_SEC',
    'PERFORMANCE_GUARD_PTZ_HOLD_SEC',
):
    assert token in config, token

for token in (
    '_performance_target_fps',
    'performance_status',
    'ADAPTIVE_LATEST_FRAME',
    'LATEST_FRAME_DROP_STALE',
    'preview_isolated',
    'event_driven_faceid',
    '_ptz_guard_until',
    'ptz_guard_active',
):
    assert token in camera, token

for token in (
    '/api/v1/performance/status',
    '/api/v1/operations/live/ws',
    'operations_live_ws',
    'performance-operations',
    'pending_exceptions',
    'registered_cameras',
):
    assert token in main, token

for token in (
    'page-live-monitor',
    'v13DashboardPreview',
    'v13OpsEvents',
    'v13PerfState',
    'v13MonitorPreview',
    'v13TopAi',
    'professional_v13_operations.css',
    'TỔNG QUAN',
    'ĐIỂM DANH',
    'CAMERA',
    'HỆ THỐNG',
):
    assert token in html, token

assert 'professional_v9_hero.js' not in html
assert 'professional_v9_hero.css' not in html
assert 'V9 DYNAMIC UI' not in html

for token in (
    'startV13OpsSocket',
    'startV13LiveMonitor',
    'startV13DashboardPreview',
    'renderV13Performance',
    'loadV13MonitorDevices',
    'window.v13ActivateCamera',
    'setInterval(loadHealth,5000)',
    'setInterval(pollClassroom,350)',
):
    assert token in js, token

for token in (
    '.v13-dashboard-main',
    '.v13-monitor-layout',
    '.v13-status-chip',
    '.v13-device-monitor-list',
    'animation-iteration-count:1',
):
    assert token in css, token

assert '?ui=v13' in start

# Catch accidental duplicate IDs in the single-page shell. Duplicate IDs cause
# subtle selector/update bugs once multiple live panels are mounted.
ids = re.findall(r'\bid=["\']([^"\']+)["\']', html)
dupes = sorted({x for x in ids if ids.count(x) > 1})
assert not dupes, f'duplicate HTML ids: {dupes}'

print('[OK] Professional V13 performance + operations contract')

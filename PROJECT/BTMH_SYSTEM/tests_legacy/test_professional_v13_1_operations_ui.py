from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend/js/app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend/css/professional_v13_1_operations_ui.css').read_text(encoding='utf-8')
config=(ROOT/'module_app/config.py').read_text(encoding='utf-8')
main=(ROOT/'module_app/main.py').read_text(encoding='utf-8')
version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
start=(ROOT/'START_CAMPUSFACE.bat').read_text(encoding='utf-8',errors='ignore')
assert version=='1.30.1-v1-face-pro-v13-1-operations-ui'
assert version in config
for token in ('v131-quick-strip','v131TodayCheckins','v131PendingCount','v131FaceCoverage','v131CameraState','professional_v13_1_operations_ui.css','Giám sát trực tiếp','Tình trạng hệ thống','Xem chỉ số kỹ thuật'):
    assert token in html, token
for token in ('v131PerformanceSummary','Tải xử lý ổn định','v131TodayCheckins','v131PendingCount','Giám sát trực tiếp'):
    assert token in js, token
for token in ('.v131-quick-strip','.v131-tech-details','.v131-command-header','.v131-system-summary'):
    assert token in css, token
assert 'professional-v13-1-operations-ui' in main
assert '?ui=v13.1' in start
ids=re.findall(r'\bid=["\']([^"\']+)["\']',html)
dupes=sorted({x for x in ids if ids.count(x)>1})
assert not dupes, dupes
print('[OK] Professional V13.1 lean operations UI contract')

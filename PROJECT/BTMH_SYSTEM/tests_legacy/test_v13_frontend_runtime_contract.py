from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
# Specifically reject the crash that was visible in the user's browser.
assert 'renderClassroomRoster' not in js
# All nav data-page values need a matching page DOM.
pages=set(re.findall(r'id="page-([^"]+)"',html))
nav=set(re.findall(r'data-page="([^"]+)"',html))
assert nav <= pages, (nav-pages)
# Every inline navigate('x') target must exist.
for target in re.findall(r"navigate\('([^']+)'\)",html):
    assert target in pages, target
print('[OK] V1.3 navigation/page runtime contract has no missing classroom target')

from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.config import APP_VERSION
assert APP_VERSION.startswith(('1.25.0-v1-face-pro-v8','1.26.0-v1-face-pro-v9','1.29.0-v1-face-pro-v12-operations'))
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
# V8 assets remain in the bundle for rollback/history, while V9 is the active hero.
assert (ROOT/'frontend/css/professional_v8_hero.css').exists()
assert (ROOT/'frontend/js/professional_v8_hero.js').exists()
if APP_VERSION.startswith('1.26.0-v1-face-pro-v9','1.29.0-v1-face-pro-v12-operations'):
    assert 'id="cfv9Hero"' in html
    assert 'professional_v9_hero.css' in html and 'professional_v9_hero.js' in html
else:
    assert 'id="v8Hero"' in html
print('[OK] Professional V8 lineage / V9 supersession contract')

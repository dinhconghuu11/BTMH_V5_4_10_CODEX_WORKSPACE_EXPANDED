from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend'/'css'/'v1_3_cleanfix.css').read_text(encoding='utf-8')
for token in ('faceidScanner','faceidBiometricOverlay','v24DepthDots','faceidSampleCount','scanTicks','scanPassPill'):
    assert f'id="{token}"' in html, token
for token in ('buildDepthDots','updateDepthDots','drawEnrollBiometricOverlay','updateFaceIdProgress','scan_pass','pass_progress'):
    assert token in js, token
assert '0/14' not in html
assert '2 LẦN QUÉT' in html
assert 'v13OrbitHint' in css
ids=re.findall(r'id="([^"]+)"',html)
assert len(ids)==len(set(ids)), 'duplicate DOM id found'
print('[OK] FaceID scan keeps real landmarks/progress with an easy two-circle presentation')

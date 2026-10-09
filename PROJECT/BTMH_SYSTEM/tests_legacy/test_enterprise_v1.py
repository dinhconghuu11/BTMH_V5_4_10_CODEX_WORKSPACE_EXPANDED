from pathlib import Path
from types import SimpleNamespace
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
config=(ROOT/'module_app'/'config.py').read_text(encoding='utf-8')
anti=(ROOT/'module_app'/'anti_spoof.py').read_text(encoding='utf-8')
classroom=(ROOT/'module_app'/'classroom_engine.py').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')

assert '1.12.0-postgresql-offline-production-ready' in config
assert 'MODULE_ANTI_SPOOF_MODE", "passive"' in config
assert 'random turn challenge' not in anti
assert 'BLINK_TURN' not in anti
assert 'không cần nhìn camera' in anti
assert '"keypoints": None' in classroom and '"skeleton_edges": []' in classroom
block=js[js.index('function drawClassroomOverlay'):js.index('function renderClassroomTracks')]
assert 'strokeRect' in block and 'keypoints' not in block and 'skeleton' not in block
assert 'createImageBitmap' in js and 'createObjectURL' not in js[js.index('function startClassroomWebSocket'):js.index('function startClassroomStream')]
assert 'Action AI' in html and 'enterprise_v1.css' in html
assert 'data-page="platform"' not in html and 'id="page-platform"' not in html

from module_app.anti_spoof import AntiSpoofEngine
eng=AntiSpoofEngine()
eng._rectangular_carrier_score=lambda *a,**k: 0.0
eng._blink_observation=lambda *a,**k: None
img=np.full((480,640,3),128,np.uint8)
def obs(yaw=0.0,pitch=0.0):
    return SimpleNamespace(bbox=(230,110,180,230),yaw=yaw,pitch=pitch)

d=None
for i in range(6):
    d=eng.update('enterprise-passive',img,obs(),now=1.0+i*0.14)
assert d is not None and d.passed,d.public()
assert d.challenge=='' and d.challenge_text==''
print('[OK] CampusFace V1.11 passive classroom enterprise contract')

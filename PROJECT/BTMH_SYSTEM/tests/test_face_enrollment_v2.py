from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.registry import EnrollmentManager

m=EnrollmentManager(); st=m._new_state(1)
assert m.PASS_COUNT==2
assert m.PASS_MIN_SAMPLES==5
assert m.TARGET>=10 and m.MIN_TOTAL>=10
st['samples']=[
    {'pass_no':1,'pose':'center','yaw':0.00,'pitch':0.00},
    {'pass_no':1,'pose':'left','yaw':-0.09,'pitch':0.01},
    {'pass_no':1,'pose':'down','yaw':-0.01,'pitch':0.07},
    {'pass_no':1,'pose':'right','yaw':0.09,'pitch':0.00},
    {'pass_no':1,'pose':'up','yaw':0.00,'pitch':-0.07},
]
st['pass_started']-=2.1
assert m._pass_done(st)
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend'/'css'/'face_enrollment_v2.css').read_text(encoding='utf-8')
for token in ('faceidGuideOrb','faceid-v2-pose-strip','poseCenterCount','poseLeftCount','poseRightCount','poseDownCount','poseUpCount'):
    assert token in html, token
for token in ('FACEID_GUIDE_TEXT','updateFaceIdGuideOrb','layoutScanTicks','faceIdGuideText'):
    assert token in js, token
assert '.faceid-v2-guide-orb' in css
assert '.faceid-v2-pose-strip' in css
print('[OK] Face Enrollment V2 segmented multi-angle scan contract')

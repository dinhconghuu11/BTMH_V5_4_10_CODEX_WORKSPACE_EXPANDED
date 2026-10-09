from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.registry import EnrollmentManager

m=EnrollmentManager()

# Realistic webcam case: strong left/right travel, center captured, one labelled
# vertical sector, but pitch span is smaller than the old 0.10 threshold.
st=m._new_state(1)
st['samples']=[
    {'pass_no':1,'pose':'center','yaw':0.00,'pitch':0.00},
    {'pass_no':1,'pose':'left','yaw':-0.075,'pitch':0.005},
    {'pass_no':1,'pose':'right','yaw':0.070,'pitch':0.010},
    {'pass_no':1,'pose':'down','yaw':0.005,'pitch':0.055},
    {'pass_no':1,'pose':'left','yaw':-0.060,'pitch':0.030},
    {'pass_no':1,'pose':'right','yaw':0.060,'pitch':0.020},
]
st['pass_started']-=4.5
assert m._pass_done(st), 'near-complete natural scan should not stall forever'
assert m._pass_progress(st) == 1.0

# No real vertical movement must still be rejected.
st2=m._new_state(1)
st2['samples']=[
    {'pass_no':1,'pose':'center','yaw':0.00,'pitch':0.00},
    {'pass_no':1,'pose':'left','yaw':-0.075,'pitch':0.005},
    {'pass_no':1,'pose':'right','yaw':0.070,'pitch':0.010},
    {'pass_no':1,'pose':'left','yaw':-0.060,'pitch':0.015},
    {'pass_no':1,'pose':'right','yaw':0.060,'pitch':0.010},
    {'pass_no':1,'pose':'center','yaw':0.01,'pitch':0.015},
]
st2['pass_started']-=5.0
assert not m._pass_done(st2), 'scan without vertical movement must not finalize'
assert m._pass_progress(st2) <= 0.94

js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
assert 'faceIdMissingHint' in js
assert 'Còn thiếu góc dọc' in js
print('[OK] V1.3.3 enrollment no longer parks at 98% for realistic webcam pitch ranges')

from pathlib import Path
from types import SimpleNamespace
import sys, time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.registry import EnrollmentManager

m=EnrollmentManager(); st=m._new_state(1)
# Simulate a laptop mounted below eye level: visually frontal raw pitch is +0.13,
# which the old absolute classifier would call DOWN.
base_t=time.time()-0.8
for i,(yaw,pitch) in enumerate([(0.012,0.128),(0.009,0.132),(0.011,0.129),(0.010,0.131)]):
    if i==0: st['neutral_started']=base_t
    ok,msg=m._neutral_accept(st,SimpleNamespace(yaw=yaw,pitch=pitch),time.time())
assert st['neutral_ready'], msg
assert abs(st['neutral_pitch']-0.130) < 0.01
# The same physical frontal pose must now classify as center, not down.
obs=SimpleNamespace(yaw=0.011,pitch=0.132)
assert m._relative_sector(st,obs)=='center'
ry,rp=m._relative_values(st,obs)
assert abs(ry)<0.01 and abs(rp)<0.01
# Relative head movements should map to useful enrollment sectors.
assert m._relative_sector(st,SimpleNamespace(yaw=st['neutral_yaw']-0.075,pitch=st['neutral_pitch']))=='left'
assert m._relative_sector(st,SimpleNamespace(yaw=st['neutral_yaw']+0.075,pitch=st['neutral_pitch']))=='right'
assert m._relative_sector(st,SimpleNamespace(yaw=st['neutral_yaw'],pitch=st['neutral_pitch']-0.055))=='up'
assert m._relative_sector(st,SimpleNamespace(yaw=st['neutral_yaw'],pitch=st['neutral_pitch']+0.055))=='down'
print('[OK] V1.3.6 neutral calibration removes laptop camera pitch bias')

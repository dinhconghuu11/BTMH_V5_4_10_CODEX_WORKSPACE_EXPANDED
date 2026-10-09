from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.registry import EnrollmentManager

m=EnrollmentManager(); state=m._new_state(1)
assert m.PASS_COUNT==2
assert m.TARGET>=10 and m.MIN_TOTAL>=10
assert state['pass_no']==1 and state['coverage']==set()
# One pass stores five quality samples collected during one natural circular head motion.
state['samples']=[
    {'pass_no':1,'pose':'center','yaw':0.00,'pitch':0.00},
    {'pass_no':1,'pose':'left','yaw':-0.08,'pitch':0.02},
    {'pass_no':1,'pose':'down','yaw':-0.01,'pitch':0.08},
    {'pass_no':1,'pose':'right','yaw':0.07,'pitch':0.01},
    {'pass_no':1,'pose':'up','yaw':0.00,'pitch':-0.06},
]
state['coverage']={'center','left','right','down','up'}
state['pass_started']-=2.0
assert m._pass_done(state)
print('[OK] enrollment uses two natural circle passes with 10 quality templates, not 14 rigid poses')

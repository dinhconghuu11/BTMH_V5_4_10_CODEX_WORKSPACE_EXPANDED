from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.registry import EnrollmentManager
m=EnrollmentManager(); st=m._new_state(1)
assert m.PASS_COUNT==2
assert m.MIN_TOTAL>=10
assert m.TARGET>=10
assert not hasattr(m,'PASS_SEQUENCES')
st['samples']=[
    {'pass_no':1,'pose':'center','yaw':0.00,'pitch':0.00},
    {'pass_no':1,'pose':'left','yaw':-0.07,'pitch':0.01},
    {'pass_no':1,'pose':'down','yaw':-0.01,'pitch':0.08},
    {'pass_no':1,'pose':'right','yaw':0.07,'pitch':0.01},
    {'pass_no':1,'pose':'up','yaw':0.00,'pitch':-0.06},
]
st['coverage']={'center','left','right','down','up'}
st['pass_started']-=2.0
assert m._pass_done(st)
assert 0.90 <= m._pass_progress(st) <= 1.0
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
assert '0/14' not in html
assert '2 LẦN QUÉT' in html
assert 'Xoay đầu chậm một vòng' in html
assert "faceidSampleCount').textContent=ready?'XONG':`VÒNG ${pass}`" in js
print('[OK] enrollment remains two natural circles and no rigid 14-step scan is shown')

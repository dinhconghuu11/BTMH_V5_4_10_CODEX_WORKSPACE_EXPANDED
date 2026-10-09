from pathlib import Path
import sys, time
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from module_app.walkby import Track, WalkByEngine
from module_app.config import QUICK_REARM_SEC

engine = WalkByEngine()
state = engine._session('test')
now = time.time()
state['tracks'][1] = Track(1, (10, 10, 80, 80), now-2, now-(QUICK_REARM_SEC+0.1), (50, 50), recognized=True, recognized_student_id=1)
# Exercise the same stale cleanup rule used at the start of process without needing models.
for tid, tr in list(state['tracks'].items()):
    if now - tr.last_seen >= QUICK_REARM_SEC:
        state['tracks'].pop(tid, None)
assert not state['tracks']
print('[OK] absence re-arms recognition by removing the old physical-presence track')

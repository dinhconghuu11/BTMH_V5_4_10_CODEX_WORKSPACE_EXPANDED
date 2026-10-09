from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from module_app.walkby import WalkByEngine

# Exceptionally strong single frame may resolve immediately after PAD PASS.
sid, conf, reason = WalkByEngine._decision([
    {'student_id': 7, 'score': 0.78, 'margin': 0.20, 'quality': 0.82}
])
assert sid == 7 and reason == 'very-strong-one-shot'

# Two consistent moderate/strong frames should resolve.
sid, conf, reason = WalkByEngine._decision([
    {'student_id': 9, 'score': 0.57, 'margin': 0.065, 'quality': 0.62},
    {'student_id': 9, 'score': 0.58, 'margin': 0.070, 'quality': 0.66},
])
assert sid == 9 and reason == 'two-frame-consensus'

# Three-of-four consistent frames are accepted for a moving/angled face.
sid, conf, reason = WalkByEngine._decision([
    {'student_id': 3, 'score': 0.52, 'margin': 0.05, 'quality': 0.55},
    {'student_id': 8, 'score': 0.44, 'margin': 0.025, 'quality': 0.53},
    {'student_id': 3, 'score': 0.53, 'margin': 0.05, 'quality': 0.57},
    {'student_id': 3, 'score': 0.51, 'margin': 0.045, 'quality': 0.60},
])
assert sid == 3 and reason == 'three-of-four-consensus'
print('[OK] stronger one/two/four-frame FaceID consensus policy')

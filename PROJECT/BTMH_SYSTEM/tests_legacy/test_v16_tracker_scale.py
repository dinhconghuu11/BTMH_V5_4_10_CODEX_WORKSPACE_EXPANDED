from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.walkby as wb
import module_app.classroom_engine as ce
from module_app.anti_spoof import LivenessDecision
from module_app.face_core import FaceObservation
from module_app.config import CLASSROOM_POSE_BUDGET


def _fake_face(x=100, y=100):
    f = np.zeros(15, dtype=np.float32)
    f[:4] = [x, y, 120, 150]
    # 5 landmarks for anti-spoof/pose metadata
    f[4:14] = [x+35,y+50, x+85,y+50, x+60,y+80, x+40,y+115, x+80,y+115]
    f[14] = .99
    return f


def test_event_driven_faceid_stops_embedding_after_identity_cached():
    face = _fake_face()
    calls = {'emb': 0, 'events': 0}
    wb.CORE.detect = lambda *a, **k: [face]
    def observe(image, f, **kwargs):
        return FaceObservation(
            face=f, bbox=(100,100,120,150), embedding=None,
            quality={'score': .92, 'face_px': 120, 'usable': True},
            pose='center', yaw=.02, pitch=.01,
        )
    wb.CORE.observe = observe
    def embedding(*a, **k):
        calls['emb'] += 1
        return np.ones(16, dtype=np.float32)
    wb.CORE.embedding = embedding
    wb.CORE.face_crop = lambda *a, **k: np.zeros((32,32,3), np.uint8)
    wb.CORE.encode_jpeg_data_url = lambda *a, **k: ''
    wb.INDEX.rank = lambda *a, **k: [(7, .95), (8, .30)]
    wb.fetchone = lambda *a, **k: {'id':7,'student_code':'SV7','full_name':'A','class_name':'C','faculty':'F'}
    wb.ANTI_SPOOF.update = lambda *a, **k: LivenessDecision('PASS', .95, 'real')
    wb.add_event = lambda *a, **k: (calls.__setitem__('events', calls['events']+1) or {'id':1,'event_at':'now','status':'RECOGNIZED'})
    wb.add_spoof_event = lambda *a, **k: {'id':2}
    wb.add_unknown_event = lambda *a, **k: {'id':3}
    engine = wb.WalkByEngine()
    frame = np.zeros((480,640,3), np.uint8)
    first = engine.process('v16-cache', frame, max_faces=50, identity_budget=4)
    assert first['tracks'][0]['recognized'] is True, first
    assert calls['emb'] == 1, calls
    second = engine.process('v16-cache', frame, max_faces=50, identity_budget=4)
    assert second['tracks'][0]['recognized'] is True, second
    assert calls['emb'] == 1, 'recognized track must reuse cached identity instead of regenerating SFace embedding'
    assert second['identity_embeddings'] == 0, second


def test_identity_budget_caps_new_embeddings_per_cycle():
    faces = [_fake_face(50,80), _fake_face(260,80), _fake_face(470,80)]
    calls = {'emb':0}
    wb.CORE.detect = lambda *a, **k: faces
    def observe(image, f, **kwargs):
        x,y,w,h = map(int, f[:4])
        return FaceObservation(f, (x,y,w,h), None, {'score':.9,'face_px':120,'usable':True}, 'center', 0.,0.)
    wb.CORE.observe = observe
    wb.CORE.embedding = lambda *a, **k: (calls.__setitem__('emb',calls['emb']+1) or np.ones(16,np.float32))
    wb.CORE.face_crop = lambda *a, **k: np.zeros((32,32,3),np.uint8)
    wb.CORE.encode_jpeg_data_url = lambda *a, **k: ''
    wb.INDEX.rank = lambda *a, **k: []
    wb.add_unknown_event = lambda *a, **k: {'id':3,'event_at':'now','status':'UNREGISTERED'}
    engine=wb.WalkByEngine()
    result=engine.process('v16-budget',np.zeros((480,800,3),np.uint8),max_faces=50,identity_budget=1)
    assert result['identity_embeddings'] == 1, result
    assert calls['emb'] == 1, calls
    assert result['track_count'] == 3, result


def test_adaptive_action_pose_budget_is_bounded():
    engine = ce.ClassroomEngine()
    engine._ensure_pose = lambda: True
    kp = np.zeros((17,2),np.float32); conf=np.zeros(17,np.float32)
    points={0:(100,50),5:(80,100),6:(120,100),7:(75,140),8:(125,140),9:(75,180),10:(125,180),11:(85,200),12:(115,200),13:(85,270),14:(115,270),15:(85,340),16:(115,340)}
    for i,p in points.items(): kp[i]=p; conf[i]=.95
    calls={'pose':0}
    def pose_on_roi(frame, roi):
        calls['pose']+=1
        return kp.copy(), conf.copy(), (40,30,140,330)
    engine._pose_on_roi=pose_on_roi
    ce.fetchone=lambda *a, **k: None
    tracks=[]
    for i in range(12):
        tracks.append({'track_id':i+1,'bbox':[20+i*45,40,36,48],'quality':{'score':.8},'recognized':False,'status':'ANALYZING'})
    face_result={'tracks':tracks,'frame_width':800,'frame_height':450,'policy':'tracker-centric/event-driven-faceid','identity_budget':4,'identity_embeddings':4}
    result=engine._process(np.zeros((450,800,3),np.uint8),face_result)
    assert result['scheduler']['pose_runs'] <= CLASSROOM_POSE_BUDGET, result['scheduler']
    assert calls['pose'] <= CLASSROOM_POSE_BUDGET, calls
    assert result['scheduler']['tracked'] == 12, result['scheduler']
    assert result['identity']['identity_embeddings'] == 4


if __name__ == '__main__':
    for fn in [
        test_event_driven_faceid_stops_embedding_after_identity_cached,
        test_identity_budget_caps_new_embeddings_per_cycle,
        test_adaptive_action_pose_budget_is_bounded,
    ]:
        fn(); print('[PASS]',fn.__name__)
    print('[OK] V1.6 tracker-centric scale tests passed')

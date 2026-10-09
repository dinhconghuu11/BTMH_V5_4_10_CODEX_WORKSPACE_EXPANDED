from __future__ import annotations

import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import module_app.walkby as wb
from module_app.anti_spoof import LivenessDecision
from module_app.face_core import FaceObservation


def install_common_mocks():
    fake_face = np.zeros(15, dtype=np.float32)
    fake_face[:4] = [100, 100, 150, 180]
    fake_face[14] = .99
    obs = FaceObservation(
        face=fake_face,
        bbox=(100, 100, 150, 180),
        embedding=np.ones(16, dtype=np.float32),
        quality={'score': .90, 'face_px': 150, 'usable': True},
        pose='center', yaw=.04, pitch=.01,
    )
    wb.CORE.detect = lambda *a, **k: [fake_face]
    wb.CORE.observe = lambda *a, **k: obs
    wb.CORE.face_crop = lambda *a, **k: np.zeros((64, 64, 3), np.uint8)
    wb.CORE.encode_jpeg_data_url = lambda *a, **k: 'data:image/jpeg;base64,AA=='
    wb.INDEX.rank = lambda *a, **k: [(7, .94), (8, .31)]
    wb.fetchone = lambda *a, **k: {'id': 7, 'student_code': 'SV007', 'full_name': 'Test Student', 'class_name': 'A', 'faculty': 'F'}


def test_success_event_waits_for_liveness_pass():
    install_common_mocks()
    calls = {'n': 0, 'success': 0}
    def live(*a, **k):
        calls['n'] += 1
        return LivenessDecision('CHECKING', .41, 'checking') if calls['n'] == 1 else LivenessDecision('PASS', .81, 'real')
    wb.ANTI_SPOOF.update = live
    wb.add_event = lambda *a, **k: (calls.__setitem__('success', calls['success'] + 1) or {'id': 10, 'event_at': 'now', 'status': 'RECOGNIZED', 'liveness_score': .81, 'anti_spoof_passed': True})
    wb.add_spoof_event = lambda *a, **k: (_ for _ in ()).throw(AssertionError('spoof event should not fire'))
    wb.add_unknown_event = lambda *a, **k: {'id': 99, 'event_at': 'now', 'status': 'UNREGISTERED'}
    engine = wb.WalkByEngine()
    frame = np.zeros((480, 640, 3), np.uint8)
    first = engine.process('gate-pass', frame)
    assert not first['events'], first
    assert first['tracks'][0]['status'] == 'VERIFYING_PASSIVE', first['tracks'][0]
    second = engine.process('gate-pass', frame)
    assert calls['success'] == 1
    assert second['events'] and second['events'][0]['status'] == 'RECOGNIZED'
    assert second['tracks'][0]['recognized'] is True


def test_spoof_never_becomes_successful_recognition():
    install_common_mocks()
    calls = {'success': 0, 'blocked': 0}
    wb.ANTI_SPOOF.update = lambda *a, **k: LivenessDecision('BLOCKED', .08, 'screen detected', screen_score=.95)
    wb.add_event = lambda *a, **k: (calls.__setitem__('success', calls['success'] + 1) or {'id': 1})
    wb.add_spoof_event = lambda *a, **k: (calls.__setitem__('blocked', calls['blocked'] + 1) or {'id': 11, 'event_at': 'now', 'status': 'SPOOF_BLOCKED', 'liveness_score': .08, 'anti_spoof_passed': False})
    wb.add_unknown_event = lambda *a, **k: {'id': 99, 'event_at': 'now', 'status': 'UNREGISTERED'}
    engine = wb.WalkByEngine()
    frame = np.zeros((480, 640, 3), np.uint8)
    result = engine.process('gate-block', frame)
    assert calls['success'] == 0
    assert calls['blocked'] == 1
    assert result['events'][0]['status'] == 'SPOOF_BLOCKED'
    assert result['tracks'][0]['recognized'] is False
    assert result['tracks'][0]['spoof_blocked'] is True


if __name__ == '__main__':
    test_success_event_waits_for_liveness_pass(); print('[PASS] success event waits for passive anti-spoof PASS')
    test_spoof_never_becomes_successful_recognition(); print('[PASS] spoof never becomes successful recognition')
    print('[OK] walk-by passive anti-spoof gate contract passed')

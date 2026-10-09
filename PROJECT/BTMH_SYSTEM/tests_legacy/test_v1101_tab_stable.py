from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from module_app.anti_spoof import AntiSpoofEngine
from module_app.walkby import Track, WalkByEngine


def fake_obs(bbox=(550, 220, 180, 240), yaw=0.0, pitch=0.0):
    return SimpleNamespace(bbox=bbox, yaw=yaw, pitch=pitch)


def test_hero_is_single_line_on_desktop():
    html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
    css=(ROOT/'frontend'/'css'/'v20_1.css').read_text(encoding='utf-8')
    assert 'class="v201-hero-title"' in html
    assert '.v201-hero-title{white-space:nowrap' in css
    assert '@media(max-width:1020px)' in css and '.v201-hero-title{white-space:normal' in css


def test_camera_recognition_width_is_not_switched_by_classroom():
    camera=(ROOT/'module_app'/'camera.py').read_text(encoding='utf-8')
    assert 'work = self._resize_for_ai(frame, AI_WIDTH)' in camera
    assert 'CLASSROOM_FACE_AI_WIDTH if classroom_mode else AI_WIDTH' not in camera


def test_track_geometry_rescales_without_new_identity():
    wb=WalkByEngine()
    state=wb._session('service-camera')
    tr=Track(7,(100,50,80,100),1.0,1.0,(140.0,100.0),velocity=(10.0,5.0))
    state['tracks'][7]=tr
    state['frame_width']=1280;state['frame_height']=720
    image=np.zeros((540,960,3),dtype=np.uint8)
    wb._rescale_tracks_for_frame(state,image)
    assert state['tracks'][7] is tr
    assert tr.bbox==(75,38,60,75),tr.bbox
    assert round(tr.center[0],2)==105.0 and round(tr.center[1],2)==75.0


def test_tab_switch_policy_is_passive_and_never_prompts_challenge():
    eng=AntiSpoofEngine()
    eng._blink_observation=lambda *a,**k: None
    eng._rectangular_carrier_score=lambda *a,**k: 0.0
    image=np.full((720,1280,3),127,np.uint8)
    d=None
    for i in range(6):
        d=eng.update('tab-switch-person',image,fake_obs(),now=1.0+i*0.14)
    assert d is not None and d.passed,d.public()
    assert d.challenge=='' and d.challenge_text==''
    assert not d.blocked


def test_existing_python_precedes_private_installer():
    bat=(ROOT/'SETUP_AND_START_CAMPUSFACE_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
    py_check=bat.index('py -3.12 -c')
    offline_check=bat.index('vendor\\python-3.12.10-amd64.exe')
    assert py_check < offline_check
    install=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
    assert '--no-index --find-links="vendor\\wheels"' in install


if __name__=='__main__':
    tests=[
        test_hero_is_single_line_on_desktop,
        test_camera_recognition_width_is_not_switched_by_classroom,
        test_track_geometry_rescales_without_new_identity,
        test_tab_switch_policy_is_passive_and_never_prompts_challenge,
        test_existing_python_precedes_private_installer,
    ]
    for fn in tests:
        fn();print('[PASS]',fn.__name__)
    print('[OK] V1.10.1 tab-stable regression passed')

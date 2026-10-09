from pathlib import Path
from types import SimpleNamespace
import sys
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.anti_spoof import AntiSpoofEngine


def obs(bbox=(535,195,210,290),yaw=0.0,pitch=0.0):
    return SimpleNamespace(bbox=bbox,yaw=yaw,pitch=pitch)


def test_no_operations_page_and_no_active_prompt():
    html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
    js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
    anti=(ROOT/'module_app'/'anti_spoof.py').read_text(encoding='utf-8')
    assert 'data-page="platform"' not in html
    assert 'id="page-platform"' not in html
    for text in ('Chớp mắt một lần','Quay nhẹ đầu sang trái','Quay nhẹ đầu sang phải','BLINK_TURN'):
        assert text not in anti
    assert 'Thực hiện yêu cầu xác minh' not in js
    assert 'Passive anti-spoof' in js


def test_line_only_rectangle_is_not_hard_block():
    eng=AntiSpoofEngine();eng._blink_observation=lambda *a,**k: None
    # Background frame with line-only suspicion should be allowed to converge.
    eng._rectangular_carrier_score=lambda *a,**k: 0.18
    img=np.full((720,1280,3),128,np.uint8)
    d=None
    for i in range(6):
        d=eng.update('chair-background',img,obs((550,220,180,240)),now=1+i*.14)
    assert d and d.passed,d.public()


def test_closed_phone_photo_carrier_is_blocked():
    eng=AntiSpoofEngine();eng._blink_observation=lambda *a,**k: None
    img=np.full((720,1280,3),180,np.uint8)
    cv2.rectangle(img,(390,90),(890,650),(10,10,10),18)
    cv2.rectangle(img,(420,120),(860,620),(220,220,220),-1)
    cv2.ellipse(img,(640,340),(105,145),0,0,360,(150,160,170),-1)
    d=None
    for i in range(4):
        d=eng.update('phone-photo',img,obs(),now=1+i*.2)
        if d.blocked:
            break
    assert d and d.blocked,d.public()


def test_empty_wheel_dir_does_not_force_offline_install():
    bat=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
    assert 'if exist "vendor\\wheels\\*.whl"' in bat


if __name__=='__main__':
    tests=[test_no_operations_page_and_no_active_prompt,test_line_only_rectangle_is_not_hard_block,test_closed_phone_photo_carrier_is_blocked,test_empty_wheel_dir_does_not_force_offline_install]
    for fn in tests:
        fn();print('[PASS]',fn.__name__)
    print('[OK] V1.11 passive classroom regression passed')

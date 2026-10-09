from __future__ import annotations

import numpy as np
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from module_app.camera import CapturePlan, StaticCameraService


class FakeCapture:
    def __init__(self, opened=True):
        self.opened=opened
        self.released=False
    def isOpened(self):
        return self.opened
    def release(self):
        self.released=True
    def set(self,*args,**kwargs):
        return True
    def get(self,*args,**kwargs):
        return 30.0


def test_frame_validation():
    assert not StaticCameraService._valid_frame(None)
    assert not StaticCameraService._valid_frame(np.zeros((10,10,3),dtype=np.uint8))
    assert not StaticCameraService._valid_frame(np.zeros((480,640,3),dtype=np.uint8))
    good=np.zeros((480,640,3),dtype=np.uint8)
    good[100:300,100:300]=120
    assert StaticCameraService._valid_frame(good)


def test_open_falls_through_to_next_plan():
    svc=StaticCameraService()
    svc._stop.clear()
    p1=CapturePlan('first',None,640,480,30,None)
    p2=CapturePlan('second',None,640,480,30,None)
    svc.capture_plans=lambda source:[p1,p2]
    caps=iter([FakeCapture(opened=False),FakeCapture(opened=True)])
    svc._new_capture=lambda source,backend:next(caps)
    svc._configure_capture=lambda cap,plan,source=None:None
    frame=np.full((480,640,3),100,dtype=np.uint8)
    svc._warmup=lambda cap,**kwargs:frame if cap.opened else None
    cap,got,plan=svc._open_best_capture(0)
    assert cap is not None and got is frame and plan.backend_name=='second'
    svc._release_capture()
    assert cap.released


def test_stop_releases_camera_immediately():
    svc=StaticCameraService()
    cap=FakeCapture(opened=True)
    svc._cap=cap
    svc.stop()
    assert cap.released
    assert svc.status()['state']=='stopped'


if __name__=='__main__':
    test_frame_validation()
    test_open_falls_through_to_next_plan()
    test_stop_releases_camera_immediately()
    print('[OK] camera recovery tests')

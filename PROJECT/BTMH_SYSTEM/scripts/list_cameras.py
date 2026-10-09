from __future__ import annotations

import os
import time

import cv2


def backend_candidates():
    out=[]
    if os.name=='nt' and hasattr(cv2,'CAP_DSHOW'):
        out.append(('dshow',cv2.CAP_DSHOW))
    if os.name=='nt' and hasattr(cv2,'CAP_MSMF'):
        out.append(('msmf',cv2.CAP_MSMF))
    out.append(('auto',None))
    return out


def open_probe(index:int):
    for name,code in backend_candidates():
        cap=cv2.VideoCapture(index) if code is None else cv2.VideoCapture(index,code)
        try:
            if not cap.isOpened():
                continue
            try:
                cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
            except Exception:
                pass
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,480)
            cap.set(cv2.CAP_PROP_FPS,30)
            deadline=time.perf_counter()+0.8
            good=None
            while time.perf_counter()<deadline:
                ok,frame=cap.read()
                if ok and frame is not None and frame.size:
                    good=frame
                    break
                time.sleep(0.02)
            if good is not None:
                h,w=good.shape[:2]
                return name,w,h
        finally:
            cap.release()
    return None


def main():
    try:
        if hasattr(cv2,'setLogLevel'):
            cv2.setLogLevel(0)
    except Exception:
        pass
    print('=== CampusFace V1.1 - Camera scan (0..7) ===')
    found=[]
    for i in range(8):
        result=open_probe(i)
        if result:
            name,w,h=result
            found.append(i)
            print(f'[OK] Camera {i}: {w}x{h} backend={name}')
    if not found:
        print('[WARN] No camera returned a valid frame.')
        print('[ACTION] Close Camera/Teams/Zoom/other CampusFace instances and try again.')
    else:
        print('[FOUND]',','.join(map(str,found)))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

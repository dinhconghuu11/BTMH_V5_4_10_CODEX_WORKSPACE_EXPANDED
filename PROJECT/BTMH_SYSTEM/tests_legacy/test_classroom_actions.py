from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.action_engine import SmoothActionState, extract_pose_features

BBOX=(100,40,300,540)
def base_pose():
    kp=np.zeros((17,2),dtype=np.float32);conf=np.zeros(17,dtype=np.float32)
    points={0:(250,80),5:(210,150),6:(290,150),7:(205,230),8:(295,230),9:(205,310),10:(295,310),11:(220,300),12:(280,300),13:(220,430),14:(280,430),15:(220,550),16:(280,550)}
    for i,p in points.items():kp[i]=p;conf[i]=.95
    return kp,conf
kp,conf=base_pose();standing=extract_pose_features(kp,conf,BBOX)
kp2,c2=base_pose();kp2[13],kp2[14]=(210,390),(290,390);kp2[15],kp2[16]=(300,390),(200,390);seated=extract_pose_features(kp2,c2,BBOX)
kh,ch=base_pose();kh[7],kh[9]=(210,135),(210,80);hand=extract_pose_features(kh,ch,BBOX)
kd,cd=base_pose();kd[0]=(250,125);head=extract_pose_features(kd,cd,BBOX)
ks,cs=base_pose();ks[0]=(250,142);sleep=extract_pose_features(ks,cs,BBOX)
kp3,c3=base_pose();kp3[0]=(250,128);kp3[7],kp3[8]=(232,225),(268,225);kp3[9],kp3[10]=(242,245),(258,245);phone=extract_pose_features(kp3,c3,BBOX)
checks={'standing':standing['raw_posture']=='STANDING','seated':seated['raw_posture']=='SEATED','hand_raised':hand['hand_raised'] is True,'head_down':head['head_down'] is True,'sleeping_hint':sleep['sleeping_hint'] is True,'phone_pose_hint':phone['phone_pose_hint'] is True}
state=SmoothActionState();now=0.;result={}
for _ in range(32):
    now+=.1;result=state.update(raw_posture='SEATED',hand_raised=True,head_down=True,sleeping_hint=True,phone_near=True,anchor_norm=(.5,.5),pose_quality=.9,dt=.1,now=now)
checks['temporal_filter']=result.get('posture')=='SEATED' and result.get('hand_raised') and result.get('head_down') and result.get('sleeping') and result.get('using_phone')
for k,v in checks.items():print(f"[{'PASS' if v else 'FAIL'}] {k}")
assert all(checks.values())
print('[OK] local classroom action geometry/state-machine regression passed')

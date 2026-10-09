from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module_app.classroom_engine import ClassroomEngine
eng=ClassroomEngine()
eng._ensure_pose=lambda: False
frame=np.zeros((720,1280,3),dtype=np.uint8)
face_result={
    'frame_width':640,'frame_height':360,
    'tracks':[{'track_id':7,'bbox':[64,36,64,72],'recognized':False,'confidence':0.0,'quality':{'score':.7}}]
}
out=eng._process(frame,face_result)
assert len(out['tracks'])==1
assert out['tracks'][0]['face_bbox']==[128,72,128,144], out['tracks'][0]['face_bbox']
print('[OK] classroom action ROI maps recognition coordinates back to full camera resolution')

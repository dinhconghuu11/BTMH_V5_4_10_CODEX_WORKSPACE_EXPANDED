from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
train=(ROOT/'scripts'/'train_farface_yolo.py').read_text(encoding='utf-8')
audit=(ROOT/'scripts'/'audit_farface_dataset.py').read_text(encoding='utf-8')
env=(ROOT/'module.env.example').read_text(encoding='utf-8')
doc=(ROOT/'training'/'HUONG_DAN_YOLO_FARFACE.md').read_text(encoding='utf-8')
assert 'yolo26n.pt' in train
assert 'campusface-face-yolo.pt' in train
assert 'imgsz' in train and '1280' in train
assert 'class must be 0 (face)' in audit
assert 'MODULE_USE_CUSTOM_FACE_YOLO=auto' in env
assert 'SFace' in doc and 'mỗi sinh viên = một class' in doc
assert (ROOT/'INSTALL_YOLO_TRAINING_WINDOWS.bat').exists()
assert (ROOT/'TRAIN_YOLO_FARFACE_WINDOWS.bat').exists()
print('[OK] optional YOLO26 FarFace training is isolated from the stable V1 runtime')

from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend/index.html').read_text(encoding='utf-8')
js=(ROOT/'frontend/js/app.js').read_text(encoding='utf-8')
css=(ROOT/'frontend/css/app.css').read_text(encoding='utf-8')
main=(ROOT/'module_app/main.py').read_text(encoding='utf-8')
cam=(ROOT/'module_app/camera.py').read_text(encoding='utf-8')
cfg=(ROOT/'module_app/config.py').read_text(encoding='utf-8')
assert 'Điều khiển camera' in html
assert 'page-camera-control' in html
assert 'data-ptz="left"' in html and 'data-ptz="zoom_in"' in html
assert 'cameraControlPreset' in html
assert '/api/v1/camera/control' in js
assert '/api/v1/camera/select' in js
assert 'DIGITAL PTZ' in js
assert 'camera-control-grid' in css
assert '@app.post("/api/v1/camera/control")' in main
assert '@app.post("/api/v1/camera/select")' in main
assert 'def control_ptz' in cam and 'def select_source' in cam and '_apply_digital_ptz' in cam
assert ('1.28.0-v1-face-pro-v11-camera-control' in cfg) or ('1.29.0-v1-face-pro-v12-operations' in cfg)
assert 'V9 DYNAMIC UI' not in html
print('[OK] Professional V11 camera control contract')

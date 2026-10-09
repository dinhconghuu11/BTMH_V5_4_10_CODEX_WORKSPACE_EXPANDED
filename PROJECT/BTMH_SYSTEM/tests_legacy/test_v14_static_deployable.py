from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
config=(ROOT/'module_app'/'config.py').read_text(encoding='utf-8')
env=(ROOT/'module.env.example').read_text(encoding='utf-8')
js=(ROOT/'frontend'/'js'/'app.js').read_text(encoding='utf-8')
html=(ROOT/'frontend'/'index.html').read_text(encoding='utf-8')
main=(ROOT/'module_app'/'main.py').read_text(encoding='utf-8')
assert '1.4.0-static-camera-deployable' in config
assert 'MODULE_ENROLL_TARGET=8' in env and 'MODULE_ENROLL_MIN_TOTAL=8' in env
assert 'MODULE_CLASSROOM_PREVIEW_FPS=12' in env
assert 'MODULE_CLASSROOM_FACE_AI_FPS=4' in env
assert 'MODULE_CLASSROOM_AI_FPS=2' in env
assert 'START_HERE_WINDOWS.bat' in (ROOT/'README_FIRST.txt').read_text(encoding='utf-8')
assert (ROOT/'BUILD_FULL_OFFLINE_PACKAGE_WINDOWS.bat').exists()
assert 'two-natural-circles' in main
assert 'manual-on-off' in main
assert 'app.js?v=1.4.0' in html
# No regression to old missing function that blanked the classroom page.
assert 'renderClassroomRoster(' not in js
print('[OK] V1.4 static-camera deployable scope and packaging contract')

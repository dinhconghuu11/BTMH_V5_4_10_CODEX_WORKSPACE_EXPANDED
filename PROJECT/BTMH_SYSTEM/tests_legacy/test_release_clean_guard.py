from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
script=(ROOT/'scripts'/'check_release_clean.py').read_text(encoding='utf-8')
builder=(ROOT/'BUILD_PORTABLE_OFFLINE_ZIP_WINDOWS.bat').read_text(encoding='utf-8')
assert 'module.env' in script
assert 'training dataset content' in script
assert '.db' in script and '.key' in script
assert 'check_release_clean.py' in builder
print('[OK] release builder guards against packaging local DB/key/log/backups/training face samples')

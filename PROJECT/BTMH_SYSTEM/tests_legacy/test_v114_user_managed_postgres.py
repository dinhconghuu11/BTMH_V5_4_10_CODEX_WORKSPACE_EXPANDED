from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
setup = (ROOT / 'scripts' / 'setup_embedded_postgres.ps1').read_text(encoding='utf-8', errors='ignore')
ensure = (ROOT / 'scripts' / 'ensure_postgres_running.ps1').read_text(encoding='utf-8', errors='ignore')
install = (ROOT / 'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8', errors='ignore')
start = (ROOT / 'START_CAMPUSFACE.bat').read_text(encoding='utf-8', errors='ignore')
config = (ROOT / 'module_app' / 'config.py').read_text(encoding='utf-8', errors='ignore')
bootstrap = (ROOT / 'scripts' / 'bootstrap_postgres.py').read_text(encoding='utf-8', errors='ignore')
env = (ROOT / 'module.env.example').read_text(encoding='utf-8', errors='ignore')
root_setup = (ROOT.parent.parent / 'CAMPUSFACE_ONECLICK_SETUP.bat').read_text(encoding='utf-8', errors='ignore')

combined = '\n'.join((setup, ensure, install, start, root_setup)).lower()
assert '1.14.0-user-managed-postgresql' in config
assert '%localappdata%\\campusface' in env.lower()
assert 'localappdata' in install.lower()
assert 'localappdata' in setup.lower()
assert 'localappdata' in ensure.lower()
assert 'programdata' not in setup.lower()
assert 'programdata' not in ensure.lower()
assert 'takeown' not in combined
assert 'icacls' not in combined
assert 'setaccesscontrol' not in combined
assert 'register-scheduledtask' not in combined
assert 'start-service' not in combined
assert 'pg_ctl.exe' in setup
assert 'pg_ctl.exe' in ensure
assert '-h 127.0.0.1 -p $port' in setup.lower()
assert 'user-process' in setup.lower()
assert 'machine_scope=False' in bootstrap
assert 'MODELS_DIR = DATA_ROOT / "models"' in config
assert 'RunAs'.lower() not in root_setup.lower()
print('PASS: V1.14 user-managed PostgreSQL contract')

from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
offline=(ROOT/'INSTALL_CAMPUSFACE_V1_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
shared=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
install=offline+'\n'+shared
start=(ROOT/'START_CAMPUSFACE.bat').read_text(encoding='utf-8',errors='ignore').lower()
prepare=(ROOT/'PREPARE_PORTABLE_OFFLINE_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
env=(ROOT/'module.env.example').read_text(encoding='utf-8',errors='ignore').lower()
for old in ('v2.4-faceidpro','v2.3-bossscope','v2.2-originalui','v2.0-ultrasmooth','setup_from_v'):
    assert old not in install
assert '--no-index' in install and 'vendor\\wheels' in install
assert 'python-3.12.10-amd64.exe' in install
assert 'campusface_data_root=%localappdata%\\campusface' in env
assert 'run_module.py' in start
assert 'ensure_postgres_running.ps1' in start
assert 'pip download' in prepare
assert 'install_current_pc_windows.bat' in offline
print('[OK] deployment contract: user-managed local data + portable offline builder')

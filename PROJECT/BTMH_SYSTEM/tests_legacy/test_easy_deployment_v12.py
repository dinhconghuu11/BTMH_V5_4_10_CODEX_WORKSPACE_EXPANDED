from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
root=ROOT.parent.parent
install=(root/'INSTALL_CAMPUSFACE.bat').read_text(encoding='utf-8',errors='ignore').lower()
start=(root/'START_CAMPUSFACE.bat').read_text(encoding='utf-8',errors='ignore').lower()
core_install=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore').lower()
core_start=(ROOT/'START_CAMPUSFACE.bat').read_text(encoding='utf-8',errors='ignore').lower()
readme=(root/'README_FIRST.txt').read_text(encoding='utf-8',errors='ignore').lower()
assert 'install_current_pc_windows.bat' in install
assert 'start_campusface.bat' in start
assert 'localappdata' in core_start
assert 'runtime\\venv\\scripts\\python.exe' in core_start
assert 'ensure_postgres_running.ps1' in core_start
assert 'install_campusface.bat' in readme and 'start_campusface.bat' in readme
assert 'repair' in core_install
assert 'administrator required' in core_install
assert 'no administrator required' in core_install
print('[OK] V1.14 has per-user install/start with repair and PostgreSQL auto-start')

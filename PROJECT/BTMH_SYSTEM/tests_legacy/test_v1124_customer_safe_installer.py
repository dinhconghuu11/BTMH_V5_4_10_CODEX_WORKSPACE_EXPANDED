from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ps=(ROOT/'scripts'/'setup_embedded_postgres.ps1').read_text(encoding='utf-8',errors='ignore')
ensure=(ROOT/'scripts'/'ensure_postgres_running.ps1').read_text(encoding='utf-8',errors='ignore')
start=(ROOT/'START_CAMPUSFACE.bat').read_text(encoding='utf-8',errors='ignore')
install=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore')
config=(ROOT/'module_app'/'config.py').read_text(encoding='utf-8',errors='ignore')
readme=(ROOT.parent.parent/'README_FIRST.txt').read_text(encoding='utf-8',errors='ignore')
assert '1.12.4-customer-safe-postgresql-production-ready' in config
assert ('Repair-ProgramDataAcl' in ps) or ('Grant-PrivateAcl' in ps)
assert ('Ensure-ManagedConfig' in ps) or ('No postgresql.conf rewriting' in ps)
assert ('Test-ClusterForeground' in ps) or ('Test-ClusterPreflight' in ps)
assert 'Try-ServiceMode' in ps and (('Start-ProcessMode' in ps) or ('Start-PrivateProcess' in ps))
assert ('managed-process' in ps.lower()) or ('managed PostgreSQL process' in ps)
assert 'Find-FreeCampusFacePort' in ps
assert 'PG-DATA-001' in ps and 'Customer data was NOT reset' in ps
assert 'ensure_postgres_running.ps1' in start
assert ('managed-process fallback' in ensure) or ('managed PostgreSQL process' in ensure)
assert 'find_python312.ps1' in install
assert 'python-3.12.10-amd64.exe' in install
assert ('khong tu dong xoa du lieu khach hang' in readme.lower()) or ('khong tu dong xoa du lieu da co' in readme.lower())
print('[OK] V1.12.4 customer-safe deployment hardening contract')

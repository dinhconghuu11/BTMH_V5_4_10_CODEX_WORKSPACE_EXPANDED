from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ps=(ROOT/'scripts'/'setup_embedded_postgres.ps1').read_text(encoding='utf-8',errors='ignore')
acl=(ROOT/'scripts'/'repair_programdata_acl.ps1').read_text(encoding='utf-8',errors='ignore')
install=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore')
assert 'repair_programdata_acl.ps1' in install
# V1.13.2 supersedes V1.13.1 command-line ACL repair with .NET ACL APIs.
assert ('acl_common.ps1' in acl) or ('/reset' in acl.lower())
assert 'CampusFacePostgreSQLRuntime' in ps
assert 'managed SYSTEM task' in ps
assert 'postgres_app_password.dpapi' in ps
assert 'No postgresql.conf rewriting' in ps
print('PASS: V1.13.1+ one-click installer compatibility contract')

from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ps=(ROOT/'scripts'/'setup_embedded_postgres.ps1').read_text(encoding='utf-8',errors='ignore')
acl=(ROOT/'scripts'/'repair_programdata_acl.ps1').read_text(encoding='utf-8',errors='ignore')
common=(ROOT/'scripts'/'acl_common.ps1').read_text(encoding='utf-8',errors='ignore')
install=(ROOT/'INSTALL_CURRENT_PC_WINDOWS.bat').read_text(encoding='utf-8',errors='ignore')
all_acl=(acl+'\n'+ps).lower()
assert 'repair_programdata_acl.ps1' in install
assert 'acl_common.ps1' in acl
assert 'acl_common.ps1' in ps
assert 'set-campusfacepathacl' in acl.lower()
assert 'set-campusfacepathacl' in ps.lower()
assert 'directorysecurity' in common.lower()
assert 'filesecurity' in common.lower()
assert 'setaccesscontrol' in common.lower()
assert 'takeown.exe' not in all_acl
assert 'icacls.exe' not in all_acl
assert 'test-campusfacedirectoryio' in acl.lower()
assert 'CampusFacePostgreSQLRuntime' in ps
assert 'managed SYSTEM task' in ps
assert 'postgres_app_password.dpapi' in ps
assert 'No postgresql.conf rewriting' in ps
print('PASS: V1.13.2 .NET ACL one-click installer contract')

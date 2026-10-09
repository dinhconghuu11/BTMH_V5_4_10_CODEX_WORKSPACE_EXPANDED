# CampusFace V1.13.2 - OneClick PostgreSQL / .NET ACL repair

- Replaces the fragile `takeown.exe` / `icacls.exe` installer path with Windows .NET ACL APIs.
- Repairs stale protected/deny ACLs recursively for `C:\ProgramData\CampusFace` without command-line ACL syntax.
- Performs real create/read/rename/delete probes in config, data, logs, backups and PostgreSQL folders before database setup continues.
- Reuses the private PostgreSQL 17 runtime and managed SYSTEM startup task from V1.13.1.
- Does not modify existing `postgresql-x64-*` services.
- Keeps the PostgreSQL password outside `module.env`; DPAPI-protected credential storage remains unchanged.
- Repair/reinstall preserves an already-valid customer database.

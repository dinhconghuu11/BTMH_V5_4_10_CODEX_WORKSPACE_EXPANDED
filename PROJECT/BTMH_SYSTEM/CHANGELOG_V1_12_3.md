# CampusFace V1.12.3 - Embedded PostgreSQL Service Startup Hotfix

- Added a foreground PostgreSQL preflight before Windows service registration so runtime/config/data errors are separated from service-account errors.
- If NetworkService registration succeeds but Windows cannot start the service, CampusFace automatically re-registers the same private cluster with pg_ctl's default Windows service account and retries without deleting customer data.
- Added Service Control Manager and Win32_Service diagnostics to `C:\ProgramData\CampusFace\logs\postgres-install.log`.
- Added explicit errors for occupied port, foreground startup failure, and compatibility fallback failure.
- Existing `postgresql-x64-*` services remain untouched.

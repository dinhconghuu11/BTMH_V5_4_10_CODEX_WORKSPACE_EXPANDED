# CampusFace V1.12.4 Customer-Safe - Test Report

Build date: 2026-09-14

## Automated regression
- 34/34 project regression modules passed in the build environment.
- Python source compilation passed for `module_app` and `scripts`.
- Frontend offline contract passed: no CDN/cloud dependency in the runtime UI.
- FaceID/passive anti-spoof/classroom-action regression contracts passed.
- PostgreSQL production contract passed.
- Customer-safe deployment hardening contract passed.

## Deployment changes validated statically
- ACL repair happens before editing an existing PostgreSQL config.
- Private PostgreSQL cluster is preflight-started before Windows Service registration.
- Existing `postgresql-x64-*` services are not modified.
- `CampusFacePostgreSQL` service is optional: if Windows blocks it, installer falls back to managed `pg_ctl` process mode.
- Daily START can start PostgreSQL without requiring a successful Windows Service.
- Existing production credential/database is preserved on repair; credential validation failure is non-destructive.
- Local port conflict can select another nearby localhost port.
- Python 3.12 discovery includes launcher/PATH and registry/common install paths; private installer is only used when needed.
- Offline installer reuses the same install/repair path instead of maintaining a separate divergent implementation.

## Important boundary
The build environment is Linux, so Windows Service Control Manager, UAC, antivirus/EDR and domain Group Policy behavior cannot be executed here. No responsible release can guarantee zero failures on every Windows/customer policy combination. V1.12.4 is designed to avoid the previously observed service/ACL failure by automatically using a service-independent managed-process fallback.

Before broad customer rollout, smoke-test the prepared offline `Setup.exe` on at least:
1. Clean Windows 10 x64 with no Python/PostgreSQL.
2. Clean Windows 11 x64 with no Python/PostgreSQL.
3. Windows with PostgreSQL 17 already installed.
4. A machine containing a failed older CampusFace PostgreSQL install.
5. Reboot + daily `START_CAMPUSFACE.bat`/Desktop shortcut.

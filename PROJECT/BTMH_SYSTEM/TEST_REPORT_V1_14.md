# CampusFace V1.14.0 test report

- Python source compile: PASS.
- Release clean guard: PASS.
- Regression runner: 32/32 PASS in the build environment.
- V1.14 installer contract verifies LocalAppData user ownership, no ProgramData runtime dependency, no takeown/icacls/SetAccessControl, no service/Scheduled Task, local-only PostgreSQL startup, and per-user DPAPI secret protection.

## Windows smoke test still required

The build environment cannot execute Windows UAC/PowerShell/PostgreSQL binaries. The final acceptance test is therefore a real Windows run of `CAMPUSFACE_ONECLICK_SETUP.bat`, followed by `START_CAMPUSFACE.bat`, restart Windows, start again, and repair-run setup once more.

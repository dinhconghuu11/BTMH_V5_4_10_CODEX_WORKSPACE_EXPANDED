# CampusFace V1.13.0 - Test Report

This build adds regression coverage for the PostgreSQL Windows deployment failures observed during V1.12.x testing.

Static/runtime tests in this environment verify:
- private PostgreSQL runtime/data paths;
- no installer writes to `postgresql.conf`;
- private host/port are passed with `pg_ctl -o`;
- managed-process fallback is retained if Windows Service mode fails;
- bootstrap receives/persists the selected port before application DB initialization;
- no `ALTER SYSTEM` writeback is required during first bootstrap;
- legacy CampusFace recognition/classroom regression tests remain intact.

Windows SCM/UAC/EDR/Group Policy behavior cannot be executed in this Linux build environment. The final release must still receive a Windows clean-machine smoke test before commercial delivery.

## Result in this build environment
- Python compile check: PASS.
- Release-clean guard: PASS.
- Regression suite: **35/35 test modules PASS**.

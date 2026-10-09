# CampusFace V1.12.0 - PostgreSQL Offline Production Ready - Test Report

## Scope

This release keeps the V1.11 Passive Classroom recognition/classroom behavior and replaces the production persistence/deployment layer with a local PostgreSQL design suitable for offline Windows deployment.

## Automated regression

Command used:

```text
CAMPUSFACE_DB_MODE=sqlite CAMPUSFACE_DATA_ROOT=<temporary-test-dir> python tests/run_tests.py
```

Result: **32/32 contract and regression test modules passed**.

Coverage includes:

- passive walk-by recognition with no blink/head-turn/look-at-camera challenge;
- anti-spoof gating and spoof event semantics;
- tracker-centric recognition/classroom behavior and tab-stability regressions;
- enrollment, student deletion, history, attendance, backup/auth contracts;
- offline/deployment packaging contracts;
- PostgreSQL V1.12 configuration/deployment contract;
- production data separation under ProgramData and release-clean checks.

## Static checks

- `python -m compileall -q module_app scripts`: PASS.
- `python scripts/check_release_clean.py`: PASS.

## PostgreSQL Windows installer validation still required

The current build environment cannot execute the Windows PostgreSQL installer/service manager. Before customer delivery, validate the complete V1.12 installer on a clean Windows 10/11 VM with no preinstalled Python/PostgreSQL:

1. prepare the offline dependency bundle;
2. install using the generated CampusFace setup as Administrator;
3. confirm the `CampusFacePostgreSQL` Windows service starts on localhost port 55432;
4. confirm database bootstrap and DPAPI credential creation;
5. register a student and confirm FaceID persists after restart;
6. run backup/restore and SQLite-to-PostgreSQL migration smoke tests;
7. disconnect Internet and verify normal CampusFace operation.

This release should not be described as clean-machine installer validated until that Windows VM test is completed.

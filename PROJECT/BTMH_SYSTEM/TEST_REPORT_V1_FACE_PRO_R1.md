# CampusFace V1 FACE PRO R1 - Regression Report

Automated regression command:

`python tests/run_tests.py`

Result at package build time:

- 34 regression test files passed.
- Added PRO R1 coverage for anti-spoof BLOCK recovery, phone re-entry during recovery, student portrait storage + backup, posture/activity separation, stable data-root compatibility, and native-camera source contract.
- Existing CORE STABLE recognition, camera recovery, classroom, PostgreSQL, installer, privacy/security, and offline frontend regressions remain passing.

Hardware smoke tests are still required on the target Windows PC because camera resolution/autofocus support and real-world anti-spoof behavior depend on the physical camera and lighting.

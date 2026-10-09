# CampusFace V1 FACE PRO R2 - Test Report

Version: `1.22.0-v1-face-pro-r2`

## Automated regression
- Full suite: **35/35 test files passed**.
- R2-specific tests cover:
  - camera quality watchdog (blur/exposure),
  - rejection of a camera driver that silently ignores requested 1080p mode,
  - duplicate identity ownership guard,
  - strong repeated identity mismatch -> release/reacquire,
  - explicit phone/tablet box association with the correct student body region,
  - rejection of far/non-phone/implausibly huge device boxes,
  - R2 release/config/UI contract.
- `python -m compileall -q module_app scripts tests`: passed.
- `scripts/check_release_clean.py`: passed.

## Preserved regression coverage
The suite also re-runs earlier contracts for FaceID, enrollment, camera recovery, anti-spoof pre-FaceID gating, PRO R1 blocked-track recovery, classroom action separation, PostgreSQL deployment/data preservation, frontend/runtime security and offline/deployment behavior.

## Hardware smoke tests still required
Automated tests cannot prove physical camera focus/exposure or real-world multi-person crossing quality. On the target Windows PC, test at minimum:
1. Actual camera mode shown as 1920x1080@30 when supported; otherwise a clearly reported fallback.
2. Camera Quality status/warning under normal, dim and intentionally blurred views.
3. Two registered students crossing paths: names must not swap or duplicate.
4. A real student holding a phone: Action AI should report `Sử dụng điện thoại` when the local device detector or pose cue is available.
5. Phone/photo anti-spoof: BLOCK -> remove phone -> recover -> FaceID reacquires.

No customer database, FaceID templates, photos, PostgreSQL cluster, models or runtime are reset by the R2 update path.

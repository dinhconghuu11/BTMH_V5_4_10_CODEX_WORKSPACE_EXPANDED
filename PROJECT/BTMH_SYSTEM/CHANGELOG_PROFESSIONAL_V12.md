# CampusFace Professional V12 Operations

Version `1.29.0-v1-face-pro-v12-operations`.

## Added
- Camera device registry with zone assignment, source, type, PTZ capability, active selection and runtime health.
- Operations rules for duplicate check-in, re-entry interval, low-confidence exception threshold and evidence retention.
- Attendance record event log (`FIRST_CHECKIN`, `DUPLICATE`, `REPEAT`, `REENTRY`).
- Human exception review layer for unregistered, spoof-blocked and low-confidence recognition events.
- Recognition evidence snapshots stored outside the database under `Snapshots/Recognition`.
- Manual attendance adjustment with required reason and immutable audit trail.
- New Professional Operations UI page.

## Preserved
- V11 Camera Control and digital PTZ fallback.
- V9/V10 dynamic dashboard and history evidence UI.
- FaceID, passive anti-spoof, classroom review, PostgreSQL/offline deployment and backup behavior.

## Safety / integrity behavior
- Exception review does not rewrite the original AI recognition event.
- Confirming identity on a spoof-blocked event does not convert it into a successful attendance event.
- Manual attendance changes require an operator/admin action and reason and are stored in a separate adjustment table.

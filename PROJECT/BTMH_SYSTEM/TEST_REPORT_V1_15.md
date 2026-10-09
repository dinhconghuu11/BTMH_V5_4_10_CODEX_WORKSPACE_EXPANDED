# CampusFace V1.15.0 Test Report

## Scope

Passive anti-spoof is now evaluated before FaceID for every tracked face. The goal is passive classroom/entrance recognition without requiring a student to look at the camera, blink, turn left/right, or stop moving.

## Regression

- 33/33 CampusFace regression modules passed.
- PostgreSQL user-managed runtime contract passed.
- Existing V1.14.3 installer/runtime behavior preserved.
- V1.15 pre-FaceID anti-spoof contract passed.

## V1.15 security checks

- `SPOOF_BLOCKED` prevents SFace/FaceID ranking from running.
- A blocked face cannot become `UNREGISTERED` or successful check-in first.
- Unknown/Unregistered is emitted only after passive anti-spoof PASS.
- UI shows `Nghi giả mạo` instead of `Chưa đăng ký` for blocked presentation attacks.
- No active liveness challenge text is present.

## Screenshot smoke check used during build

On the supplied camera screenshots:

- phone/screen face sample: carrier score ~0.932 -> BLOCKED after 3 observations;
- direct real-face sample: carrier score ~0.176 -> PASS after 4 observations.

This smoke check is specific to those supplied frames and is not a certification of presentation-attack detection across all lighting, cameras, displays, print materials, masks, or replay methods.

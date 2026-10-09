# CampusFace V1.9 Enterprise Production - Architecture

```text
STATIC CAMERA
    |
    +--> Registration: 2-circle FaceID enrollment
    |
    +--> Recognition
    |      Face detector -> SFace identity -> Secure Liveness Gate -> Check-in
    |
    +--> Classroom
           Detector/Tracker
                 |
                 +--> identity cache (FaceID only when needed)
                 +--> adaptive Action AI
                 +--> person bbox + name + simple action
```

## Classroom scalability

- Track ID is the primary state.
- Identity is cached after verification.
- Pose inference is budgeted and prioritized.
- Stable tracks are revisited slowly.
- New/active tracks are processed more frequently.
- Customer UI does not draw skeleton/keypoints.

## Security rule

`identity_match != check_in`

A check-in is created only after the liveness/anti-spoof gate returns PASS.

## V1.9 Production event model
- Recognition event `RECOGNIZED + anti_spoof_passed=1` => CHECKIN_SUCCESS.
- Recognition event `SPOOF_BLOCKED + anti_spoof_passed=0` => CHECKIN_FAILED, identity preserved when FaceID matched.
- `audit_events` stores FACE_REGISTER_SUCCESS/FAILED and SYSTEM_START/STOP.
- `/api/v1/history/feed` normalizes attendance, FaceID audit and classroom action events for the enterprise dashboard.
- Classroom uses short tracking grace; stale tracks can preserve display/identity briefly but never create new identity/action evidence.

# CampusFace V1.16.0

## Continuous passive risk-fusion anti-spoof

- PASS is no longer terminal for a physical track. Screen/photo context is re-checked on every usable frame.
- Fresh phone/screen evidence immediately downgrades PASS to CHECKING and pauses FaceID.
- Repeated strong carrier evidence becomes `SPOOF_BLOCKED` before further identity work.
- A blocked track clears all in-memory identity candidates and never exposes a student name in the spoof event.
- Risk fusion exposes `risk_score`, `context_score`, and signal diagnostics for UI/audit.
- No active blink/turn/look-at-camera challenge is required.
- PostgreSQL/user-managed runtime remains unchanged from the working V1.14.3/V1.15 base.

## Security rationale

V1.15 could keep a cached PASS for the lifetime of a tracker. If a genuine face passed first and a phone/photo later entered the same track, the old PASS could survive. V1.16 continuously re-validates the context so that a phone/photo can revoke PASS and block identity display/check-in.

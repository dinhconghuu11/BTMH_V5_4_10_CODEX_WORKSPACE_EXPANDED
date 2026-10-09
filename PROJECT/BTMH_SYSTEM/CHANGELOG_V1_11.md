# CHANGELOG V1.11.0 – Passive Classroom

## Recognition
- Removed active liveness challenge from walk-by/classroom recognition.
- Recognition no longer asks for blink, head turn, look-up, stop, or look-at-camera.
- Added passive multi-frame PASS/CHECKING/BLOCKED policy.
- Kept legacy `liveness` JSON fields and DB column names for backward compatibility only.

## Anti-spoof
- Strong repeated closed screen/photo carrier evidence can still block check-in.
- Line-only rectangular evidence is down-weighted to avoid false spoof from chair backs, windows and classroom boards.
- Eye blink is optional passive evidence only.

## Frontend
- Removed the “Vận hành” navigation item and page from the user interface.
- Recognition UI now says passive anti-spoof and explicitly says no need to look at camera.
- Updated History wording from active liveness terminology to passive anti-spoof terminology.
- Dashboard hero remains single-line on desktop.

## Deployment
- Full Source installer now checks for actual `vendor\\wheels\\*.whl` before choosing offline-wheel mode.

# TEST REPORT V1.11.0 – Passive Classroom

## Automated regression
- 31 test scripts passed.
- Recognition tracker, classroom engine, deployment, enrollment, DB security events, attendance and frontend contracts all passed.
- Added V1.11 passive-classroom regression covering removal of active challenge, removal of Vận hành UI, line-only background false-positive protection and closed phone/photo carrier blocking.

## Passive anti-spoof sanity checks
- Real classroom-like frame with rectangular background: line-only carrier score reduced to weak evidence; passive verification converged to PASS without blink/turn prompts.
- Synthetic phone/photo rectangle: strong carrier evidence converged to BLOCKED and did not become a successful recognition event.

## Deployment sanity
- Full Source no longer treats an empty `vendor\\wheels` directory as an offline wheel bundle.
- Existing Python 3.12 is preferred before invoking a private Python installer.

## Scope note
RGB passive anti-spoof is not equivalent to IR/depth liveness. V1.11 is designed to reduce friction and false rejections in classroom observation while still blocking strong, repeated screen/photo evidence.

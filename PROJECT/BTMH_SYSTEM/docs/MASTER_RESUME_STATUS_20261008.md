# MASTER resume checkpoint — 2026-10-08

Canonical source: `PROJECT/BTMH_SYSTEM/`. Existing work retained. No rollback, reset, clean or customer/runtime migration execution.

| Scope | At latest resume | Current evidence |
|---|---|---|
| Camera/store/zone attribution | DONE | Safe atomic configuration and immutable event snapshots;10 SQL tests PASS after display-name addition. |
| Four background AI pipelines | DONE | Bounded supervisor/model lanes;12 focused tests PASS. Actual4-camera acceptance outstanding. |
| Four recognition slots and bbox | DONE |11 slots,7 geometry,4 multi-person labels PASS. |
| Daily appearance sequence/dedup | DONE |17 SQL/state tests PASS; same appearance/# and Unknown→Verified preserved. |
| Recent recognition | DONE at source/test level |13 bounded-list/lifecycle/polling/status tests PASS. |
| Assigned-shift attendance | DONE |18 canonical shift/IN/OUT tests PASS; no inferred work hours. |
| Entrance visitor sessions | DONE at source/test level |29 focused IN/OUT tests PASS; employee recovery cannot replay stale crossings. Face-visible entrance hardware limits remain. |
| Server history/CSV/timeline | DONE at source/test level |15 SQL +25 frontend PASS; current scoped route suite30 PASS, including read-only Mobile Viewer compatibility and safe legacy observations. |
| Visits comparison/management dashboard | DONE at functional source/test level |18 backend +8 controller PASS; API and UI wired; Impeccable finish gate underway. |
| Account menu/profile/password/provisioning | DONE at source/test level |13 backend +11 dialog +10 current auth/account tests PASS. Existing login retained. |
| Camera configuration/diagnostics cleanup | DONE at source/test level |17 camera configuration +8 customer diagnostics +24 diagnostics lifecycle PASS. Draft recovery clears on actor/permission/camera loss. |
| Impeccable critique/polish | DONE within current source scope; rendered QA BLOCKED |Two isolated assessments after functional gate, A completed before B findings entered synthesis; snapshot26/40 before polish, priorities corrected/closed. Detector index9/enroll0 has external CSS limits; current browser apps/browsers empty. |
| QR/mobile draft + Owner/Admin biometric approval | DONE at source/test level |Exactly two additive tables and four indexes, no old schema/destructive/data migration. Service18, capture12, HTTP17, race review5, mobile22, admin25, desktop13 PASS. Customer DB migration, installed crypto/PostgreSQL, actual ASGI parsing and phone/HTTPS acceptance remain outstanding. |

Confirmed semantics: `#NNNN` is one camera/day appearance sequence, not visits. Each camera has its own atomic counter, display sequence resets at local00:00, event IDs never reset. A continuous/reacquired accepted appearance retains its number during the same camera/day; Unknown→Verified updates the same event. Midnight creates a new daily appearance. Background AI admission comes from persisted camera configuration, independent of browser slots, page visibility or logout.

Current blockers: Windows sandbox child-process runner EPERM; pytest unavailable/access-denied tool files; no connected browser for current rendered QA; real PostgreSQL, cameras/GPU, Windows capture retirement/soak and trusted-HTTPS LAN mobile acceptance unmeasured. Continue independent work; do not escalate just to run tests.

Latest resume retained all prior passing source. Integration fixes completed capture-reset/portrait races, staged desktop capture before approval, explicit enrollment-store selection without changing HR assignments, pre-parser bounded QR bodies/rates, safe legacy observation DTOs and read-only Mobile Viewer history compatibility. Bounded critique/polish and final focused checks are complete. Final gate route30/management8/auth10/diagnostics24 and post-polish recent13/camera17/report25/mobile22/admin25 PASS; Python compile(source), JS syntax and scoped markup contracts PASS. No real runtime/customer migration, rollback or source discard was performed. Full completion/limits/manifest/acceptance: `FINAL_REPORT_DEMO_PRODUCTION_LITE_20261008.md`. STOP after final delivery.

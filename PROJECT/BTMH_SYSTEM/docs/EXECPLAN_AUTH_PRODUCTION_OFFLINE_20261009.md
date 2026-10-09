# Authentication routing and production offline delivery — 2026-10-09

## Goal and user-visible acceptance

Keep the completed BTMH master implementation and clearly expose existing-account login, invited employee enrollment and secure first-owner bootstrap as separate flows. Production must use the real backend and existing business modules, require verified supported MediaMTX and preserve PostgreSQL, MFA, RBAC and fail-closed PAD. Prepare a complete offline packaging path; never certify an incomplete payload or untested hardware as production ready.

## Current architecture and observed failure

Canonical source is `PROJECT/BTMH_SYSTEM/`. Existing reports show login, account provisioning and staged QR enrollment already implemented. UI Preview uses an isolated empty SQLite database; its first-owner screen is not evidence that operational login was removed. The production launcher stops on `MEDIAMTX_NOT_INSTALLED`. The `.test_media` ZIP was previously identified as corrupt and is not a distributable runtime. Git CLI and `.git` metadata are absent from this workspace, so status/diff cannot be obtained; preserve all existing source and record this limitation. Existing portable/installer scripts require a fresh dependency/provenance audit.

## Expected files/modules

Investigate auth frontend routing and narrow authentication regression tests; production launch/readiness scripts and narrow startup tests; existing offline prepare/setup/build/validation scripts, installer inputs and dependency audit; deployment/import instructions and the final report. Record the exact changed-file inventory after implementation.

## Protected areas and non-goals

Do not rewrite the master task, camera registry/handover, recognition thresholds, FaceID/PAD, appearance/dedup, attendance or approved account/store rules. No production database modification, destructive migration, source rollback/reset/clean, public privileged registration, mocked production data, preview fallback or disabling camera/AI to satisfy readiness. No repeated UI polish or broad refactor.

## Migration and rollback

No schema change is planned. All automated tests use explicitly isolated data roots. Existing customer data and keys remain outside source/package. Source changes are independently reversible by restoring only the files in the final inventory; do not execute a database rollback. Installer upgrades must preserve the separate data root and reject unverified/incomplete artifacts before replacement.

## Test plan

Run focused auth bootstrap/login/logout/enrollment/MFA/RBAC/routing checks, startup policy/order and offline payload/provenance checks first. Use existing workspace test interpreter. Compile changed Python and syntax-check changed JS/PowerShell as applicable. Run release verification once if practical after focused checks. Distinguish source/fixture/API evidence from actual Windows clean installation, authentic MediaMTX/WebRTC, PostgreSQL, camera/GPU, LAN HTTPS and phone acceptance. Missing external artifacts/hardware are BLOCKED; continue independent work.

## Security and privacy

Retain localhost-only first-owner bootstrap and duplicate-owner prevention, existing session/MFA policy and server-side permission/store enforcement. QR enrollment never grants portal Owner/Admin authority. Require the official MediaMTX v1.21.1 ZIP and pinned SHA256 before extraction/execution. Audit licenses/provenance for runtime/model redistribution. Do not copy operational secrets, credentials, biometrics, database or logs into the payload. No network use in customer offline installation.

## Implementation checkpoints

- [x] Read required project instructions and current product/master reports; inspect workspace and artifact availability.
- [x] Audit auth routing; implement the smallest proven regression fix and focused tests.
- [x] Audit production startup; implement proven launch/readiness gaps and focused tests.
- [x] Audit/complete offline packaging validation and official artifact import procedure; actual release payload remains BLOCKED.
- [x] Perform integrated focused checks and practical broader verification; hardware/clean Windows/PostgreSQL acceptance remains NOT_RUN.
- [x] Record DONE/PARTIAL/BLOCKED, file inventory, exact commands and evidence; stop after final report.

## Acceptance evidence

Fresh focused authentication evidence: actual ASGI/private-SQLite routing/QR 9 PASS, database bootstrap/service 7 PASS, existing SMS/MFA 42 PASS. Direct Node routing 11, auth/account 10, mobile enrollment 22, QR approval 25 and desktop enrollment 13 PASS. Python compile and changed JS syntax PASS. SQLite concurrent bootstrap creates exactly one Owner; PostgreSQL lock adapter is not real PostgreSQL acceptance.

Official pinned MediaMTX 1.21.1, Python 3.12.10 amd64 and YuNet/SFace/MiniFASNet models were acquired and SHA256 verified on the build machine. Official PyPI supplied 60 Windows/portable wheels for the unchanged requirements. Authentic MediaMTX offline import, discovery and executable `--version` passed in `.qa_production/media-runtime`; this is not camera/WebRTC acceptance. `.qa_production` evidence/test runtimes must be excluded from distributable packages. Current browser inventory is empty, so rendered acceptance remains BLOCKED. Exact licenses/notices, PostgreSQL payload/provenance and final offline audit remain under review. Previous checkpoint results remain historical only; no production launch or completed commercial installer is claimed while mandatory gates remain missing.

All 60 acquired wheels installed successfully with `--no-index` into `.qa_production/offline-venv`; pip check found no broken requirements. Actual pinned YuNet/SFace loads and Passive PAD ONNX Runtime model probe passed; FFmpeg resolved and executed version 7.1 with GPL/version3 build flags. Exact corresponding FFmpeg source/distribution evidence remains missing. The existing localhost HTTP smoke ran against this exact installed runtime: 8 PASS, 3 pages/36 assets and real auth/session/RBAC/QR APIs. Its isolated preview profile intentionally guards hardware, so these results prove API/assets integration only, not production startup or clean-machine acceptance. See `THIRD_PARTY_DISTRIBUTION_AUDIT_20261009.md` for source links and honest license limits.

Final startup suite: 16 PASS after early inherited-preview rejection in both entrypoints, current PostgreSQL repair return codes, real batch control flow and lifecycle/bind ordering checks. Relevant MediaMTX launcher/importer suites: 25 PASS. Offline payload rejection/staging/active-upgrade/direct-network-dependency suite: 16 PASS. Media lifecycle: 45 PASS after correcting the stale approved-status fixture; product video code unchanged. Source compilation and PowerShell/JavaScript syntax checks passed. Sandbox ACL failures were retried with scoped approved execution; aborted agent approval requests were not counted as executed tests.

Actual payload audit `docs/OFFLINE_PAYLOAD_AUDIT_20261009.json`: dependency closure PASS, 60 wheels, five VERIFIED_PAYLOAD artifacts, fourteen BLOCKED issues for missing PostgreSQL/checksum and distribution/notices evidence. Actual package command returned 2 and created neither stage nor ZIP. No completed customer installer or full Production launch is claimed. Default Production URL is `http://127.0.0.1:8100/`, conditional on successful configured startup. Final bounded handoff is `FINAL_REPORT_AUTH_PRODUCTION_OFFLINE_20261009.md`.

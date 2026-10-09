---
target: BTMH changed operate screens
total_score: 26
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 2
target_identity: "file:C:\\FACE\\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\\PROJECT\\BTMH_SYSTEM\\frontend\\index.html"
target_fingerprint: "sha256:acc8900d79206f04e92e4ae1eff9753708304ada42f298a1678a402de8148480"
target_path: "C:\\FACE\\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\\PROJECT\\BTMH_SYSTEM\\frontend\\index.html"
timestamp: 2026-10-08T13-45-13Z
slug: frontend-index-html
closed: true
---
Method: dual-agent (A: /root/design_assessment_a · B: /root/design_assessment_b)

Target: frontend/index.html and changed recognition/reports/management/account/camera/enrollment surfaces, including frontend/enroll.html. Operate mode. Source-based assessment; current rendered/browser inspection BLOCKED: apps=[], browsers=[]. No detector output entered parent until A completed.

## Design health

| # | Nielsen heuristic | Score /4 | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 3 | Routine polling announces unchanged updates. |
| 2 | Match system and real world | 2 | Corrupted dashboard labels; blocked and unknown merge. |
| 3 | User control and freedom | 2 | Camera draft lost on suspension; reports lack reset. |
| 4 | Consistency and standards | 3 | Cohesive brand; verification terminology differs. |
| 5 | Error prevention | 3 | Scope/expiry/approval/reason guards present. |
| 6 | Recognition rather than recall | 3 | Context repeated; appearance number needs short explanation. |
| 7 | Flexibility and efficiency | 2 | Flexible slots/CSV; overlapping report apply patterns. |
| 8 | Aesthetic and minimalist design | 3 | Restrained identity; excessive simultaneous filters. |
| 9 | Error recovery | 3 | Honest retries; interrupted configuration recovery missing. |
| 10 | Help and documentation | 2 | Good business notes; approval prerequisites need cues. |
| | Total | 26/40 | Acceptable; focused corrections required. |

## Specificity and overall impression

Wine/ivory/subtle gold, local emblem, explicit store/zone/camera context and internal approval make this recognizably BTMH. Preserve the visual world and system font. Operational correctness carries the product character. The largest opportunity is clearer presentation at decisions, rather than another redesign.

Strengths: four presentation slots explicitly independent of AI/recording; truthful shift IN/OUT/last_seen semantics; consent/pending/rejected replacement preserves old FaceID and approval is explicit.

## Priority issues

1. **P1 — Corrupted dashboard copy**, frontend/index.html:107–136. Literal question marks replace Vietnamese letters. Restore only affected source labels, preserving IDs/behavior. Suggested: clarify.
2. **P1 — Blocked verification looks like unknown identity**, btmh_recent_recognition.js:28–35 and CSS unknown tone. Distinguish server SPOOF_BLOCKED/REJECTED/FAIL/BLOCKED as Không qua xác minh; ordinary unknown is neutral. Preserve PAD/FaceID decisions. Suggested: clarify.
3. **P2 — Camera draft lost on tab/navigation**, btmh_camera_configuration.js stop/visibility handlers. Retain same-actor/camera draft in memory while aborting requests/stopping media, clear on logout/actor/permission loss, restore after scoped registry reload. Suggested: harden.
4. **P2 — Nine filters and competing apply models**, index.html report form and btmh_demo_reports.js change handler. Group secondary filters, use a single clearly labeled apply model and add reset. Keep SQL scope/export/pagination. Suggested: distill.
5. **P2 — Background chatter, missing capture guidance announcement**, recent note role=status polling vs enrollment guidance updates. Keep unchanged automatic refresh quiet; announce user refresh/errors/new meaningful states and phase transitions/ready/blocked without frame chatter. Suggested: audit.

Cognitive load: nine default recognition filter decisions and six attendance fields; more than four choices. Navigation groups and staged mobile consent/capture reduce load. Emotional valleys: corrupted overview, red ordinary unknowns, lost camera work. Approval/pending completion is reassuring and honest.

Personas: Owner/Manager first-time operator cannot trust damaged labels/merged states; Admin power user loses draft on tab change and clears filters manually; accessibility-dependent employee/operator hears routine feed polling but misses movement guidance.

Minor observations: mobile font starts Inter instead of pinned Segoe UI; unconditional green success tick also appears for rejected/expired/cancelled; explain # is camera/day appearance, not visits; mark review reason required and explain disabled approval prerequisites. Current touch/layout/computed contrast remain unverified.

## Detector evidence

Index CLI exit2: nine findings (eight warnings, one advisory). Enrollment exit0: zero findings. Full JSON and stderr: assessment-b-index-20261008.json, assessment-b-enroll-20261008.json and assessment-b-evidence-20261008.json in this folder. Twelve unresolved index stylesheet warnings and one enrollment stylesheet warning limit the scan; zero findings is not rendered PASS.

Six broken-image findings map to runtime camera/snapshot slots with mount/empty handling, not missing static assets: index lines102/147/367/701/771/864. Flat-type-hierarchy is a false positive because external CSS was unresolved. Em-dash-overuse mostly marks unmeasured value placeholders and select separators. Low-contrast candidate is playback explanatory text index:96, outside changed modules; actual computed style unavailable. Do not rewrite passing playback during this scoped polish.

Questions skipped: the user fixed product scope/brand and authorized finishing the current MASTER task; follow the existing single automatic filter model and explicit server outcome truth.

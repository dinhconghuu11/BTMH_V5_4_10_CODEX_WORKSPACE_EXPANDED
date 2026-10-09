# QR/mobile FaceID enrollment — proposal for approval

Status: **APPROVED FOR MINIMAL IMPLEMENTATION, 2026-10-08; customer database migration not executed.**

The user explicitly approved this proposal, then limited approval to at most the two new tables below. A scope audit before continuation found no QR schema source created or executed yet, and no schema/active-template writes in the new capture wrapper or registry preparation adapter. QR migration must use only CREATE TABLE/INDEX IF NOT EXISTS for these two tables: zero alteration of existing tables, destructive SQL, backfill, old FaceID rewrite, camera/attendance/RBAC changes or second database. Publication into existing face_templates is a runtime Owner/Admin APPROVE action, never a migration. Existing active templates remain usable during pending, rejection and reenrollment.

Add a partial unique index for one nonterminal request per employee across stores; unique invitation/session digests and atomic conditional redemption block token reuse. REQUEST REENROLLMENT retires the prior request/token and creates a fresh pair in the same transaction, preserving the old active template. Approval uses expected revision plus serialized duplicate check/publication. Operational rollback is to disable the new enrollment entry points, retaining both additive tables and existing active templates; no automatic database rollback or DROP.

Prepared 2026-10-08 from the canonical source. Authorization covers the minimal QR/staged desktop workflow described below, not execution against a customer database, public registration or unrelated changes. The existing A–H demo work continues independently. The daily camera appearance sequence is a separate previously approved event/report change and is not included in this biometric migration.

## Proposed outcome and boundary

Owner/Admin creates an employee profile, chooses its permitted store, and issues a short-lived invitation. Scanning its QR opens a dedicated mobile capture page. The employee accepts biometric consent, completes the same enrollment quality/PAD/duplicate pipeline used by desktop capture, and submits a draft. Submission means **pending review**, not recognition enabled. Only an explicit Owner/Admin approval publishes the encrypted template into the existing `face_templates` table and refreshes INDEX.

There is no public account creation, employee management-portal login, or Mobile Viewer permission expansion. An invitation authorizes only enrollment for one existing employee and one store. Rejected, expired, cancelled, incomplete, or pending drafts never enter INDEX. An already active employee template remains active while its replacement is reviewed; rejecting the replacement preserves that template. Revoked biometric consent continues to revoke existing templates through the current flow and also cancels pending drafts.

Approval of this proposal would authorize **two additive tables and an enrollment publication boundary**, including routing desktop capture through the same draft pipeline. It would not authorize changes to FaceID/PAD models, thresholds, security decisions, SMS/OTP, attendance rules, camera architecture, or public account registration. If review finds that more schema or those protected changes are required, stop and present that additional change first.

## Existing components to reuse

| Existing component | Reuse and necessary distinction |
| --- | --- |
| `module_app/registry.py:493`, `EnrollmentManager.frame` | Existing consent, one-face, framing, size, sharpness, light, calibration and two-pass sample coverage. Its current implementation does **not** call PAD. Add a shared enrollment wrapper; do not describe present enrollment as PAD-gated. |
| `module_app/anti_spoof.py:321`, `AntiSpoofEngine.update` | Existing multi-frame PAD/context decision engine, isolated under an enrollment session key; only a current `PASS` permits accepting enrollment samples. Reset/purge its session state on capture retirement. Preserve all decision thresholds and fallback policy. |
| `module_app/registry.py:709`, `_duplicate_candidate` | Same comparison algorithm for desktop/mobile. Recheck at approval against the then-current active index before publication. Candidate identity is shown only to Owner/Admin. |
| `module_app/registry.py:17`, `encode_template`/`decode_template`; existing crypto helpers | Same encrypted embedding representation and installed encryption key. No new key distribution and no plaintext embedding persistence. |
| `module_app/registry.py:759`, `finalize` | Reuse readiness, sample selection and final template formation. Its current writes at lines790–811 must be separated from preparation: draft preparation cannot write `face_templates` or reload INDEX. |
| `module_app/platform_v5.py:120`, `face_enrollment_validations` | Retain post-publication store-camera validation. `PENDING_STORE_VALIDATION` is not an approval gate: current INDEX loads every active-table template (`registry.py:50`). |
| `frontend/js/btmh_v4.js:187` and `frontend/js/app.js:1354` | Existing browser camera capture, bounded JPEG upload, guidance, cancellation and lifecycle behavior. Mobile presentation shares this capture contract instead of implementing another quality model. |
| `students`, `employee_store_assignments`, `stores`, existing RBAC/audit | Reuse identity, store assignment and consent fields. No second employee/store model or account-to-employee linkage migration. |

Existing `/api/v1/enrollment/frame`, `/finalize`, `/reset` require `employee.enroll` (`module_app/main.py:1327`). The frame route also calls `CAMERA.hold_enrollment_mode`; the dedicated mobile wrapper must require an uploaded image and must not use that route's active-camera fallback or hold the store camera. Existing account approval (`auth.py:730`) activates `system_users`, not biometric templates, and cannot implement this feature. `/api/v1/mobile/` remains read-only (`main.py:381`).

## Minimal additive schema

Use the existing idempotent SQLite/PostgreSQL migration convention. IDs below are server-generated opaque TEXT UUIDs. Employee/store/actor foreign keys use the appropriate existing integer type; encrypted blobs use SQLite BLOB/PostgreSQL BYTEA. Do not alter, rename, backfill or remove any current table/column.

### 1. `face_enrollment_requests`

| Column | Type / invariant |
| --- | --- |
| `id` | TEXT primary key, opaque and server generated |
| `student_id`, `store_id` | Required references to existing `students` and `stores`; request targets cannot be reassigned after creation |
| `source_kind` | TEXT: `DESKTOP` or `QR_MOBILE` |
| `status` | TEXT: `CAPTURING`, `PENDING_REVIEW`, `NEEDS_DUPLICATE_REVIEW`, `APPROVED`, `REJECTED`, `EXPIRED`, `CANCELLED` |
| `template_blob` | Nullable encrypted template; present only after complete quality/PAD-approved capture and submission |
| `preview_blob` | Nullable encrypted representative face crop for administrator review; no raw video/full-frame archive |
| `pose_count` | INTEGER, server computed from the existing enrollment manager |
| `quality_json`, `pad_json`, `duplicate_json` | TEXT JSON server summaries: sample coverage/quality, PAD decision and safe policy/version identifiers, duplicate candidate ID/score and decision. No tokens, raw images, camera sources, network credentials or client-supplied PASS. |
| `created_by_user_id` | Existing Owner/Admin issuing or starting the request |
| `submitted_at`, `expires_at` | Nullable UTC submission time and required UTC expiry |
| `reviewed_by_user_id`, `reviewed_at`, `review_reason` | Decision actor/time/reason; required for reject/cancel and any duplicate override |
| `duplicate_override` | INTEGER boolean default 0, set only by an explicit Owner/Admin decision |
| `revision` | INTEGER default 0, increments on each transition; approval/rejection requires the expected current revision |
| `created_at`, `updated_at` | UTC timestamps |

Indexes: `(status, submitted_at)`, `(student_id, created_at)`, `(store_id, status)`. Application transitions validate enums and invariants on both database modes. No template is copied to the active table by migration or restart recovery.

### 2. `qr_enrollment_invites`

| Column | Type / invariant |
| --- | --- |
| `id` | TEXT primary key, opaque and server generated |
| `request_id` | Required unique reference to one `face_enrollment_requests` row, binding employee/store/source to that request |
| `token_hash` | TEXT unique digest of a cryptographically random 256 bit invitation secret; raw secret returned only once to the issuing browser |
| `created_by_user_id`, `created_at`, `expires_at` | Existing Owner/Admin and UTC issuance/expiry |
| `redeemed_at`, `revoked_at` | Nullable UTC timestamps; atomic redemption succeeds only when both are NULL and the invite has not expired |
| `session_hash`, `session_expires_at` | Nullable unique digest/expiry of a separate random 256 bit capture-session secret issued once on redemption |

No biometric or authentication secret appears in a URL persisted by the server, database logs, app audit, frontend storage, or docs. A reissue cancels the old request, revokes its invitation/session and creates a new request/invite pair; it never reopens a consumed QR token.

## Exact proposed lifetime and state policy

These defaults are reviewable proposal choices, not current implementation behavior:

- Invitation: **15 minutes** from issuance, single atomic redemption. Default configurable within 5–60 minutes. Issuing another invitation for the same employee/store retires the earlier one.
- Capture session: **30 minutes** from redemption, fixed expiry; no extension from frames/polling. A maximum of one in-flight frame request is accepted per session; bounded latest-frame behavior replaces queued work. The mobile client follows the existing 960 px JPEG capture ceiling; the server additionally caps encoded upload size at 2 MiB and decoded pixel count at 1920×1080 before inference.
- Submitted draft: **72 hours** for review. On expiry, cancel publication and purge draft template/preview bytes. Terminal approved/rejected/cancelled rows retain only safe audit metadata after publication or immediate rejection/cancellation; expiry cleanup must be idempotent.
- A server restart retires incomplete `CAPTURING` sessions because their current sample/PAD state is transient. Owner/Admin must issue a fresh QR. Encrypted submitted drafts and their review state survive restart.
- Successful submission revokes capture authority. Duplicate submit returns the same pending request state; it cannot create another active template or approve itself.
- `CAPTURING → PENDING_REVIEW` or `NEEDS_DUPLICATE_REVIEW` requires current consent, adequate existing sample coverage, and a server PAD PASS. No other path produces a reviewable template.
- A submitted draft can become `APPROVED`, `REJECTED`, `EXPIRED` or `CANCELLED`. Duplicate review requires an explicit override with a reason, or rejection/new capture. Neither mobile nor a client boolean may grant that override.
- Approve revalidates request revision, expiry, employee existence/current consent, store assignment/scope, stored quality/PAD evidence, and duplicate comparison against the current active templates. Competing approvals serialize this check/publication using an existing database transaction plus a shared publication lock; serialize across processes if deployment supports multiple application processes. No race between two same-face drafts may bypass duplicate review.
- In one transaction, publish the prepared template into existing `face_templates`, mark the request approved with its actor and audit decision, and clear draft blobs. Reload INDEX only after commit. A failed write/commit leaves the draft unapproved and retryable; it never reports success. Startup already loads committed active templates, covering a crash after commit but before refresh. Publish the optional profile portrait through existing media handling after commit; portrait failure does not change the active-template decision.

## Proposed endpoint and UI contract

These are new proposed routes, not existing APIs:

| Route | Authorization and result |
| --- | --- |
| POST `/api/v1/admin/face-enrollment/invitations` | Owner/Admin only; existing employee/store and scope validated; creates request/invite and returns its QR link once. No account creation. |
| POST `/api/v1/admin/face-enrollment/requests` | Owner/Admin desktop entry, creates a draft using the same service/approval boundary. |
| GET `/api/v1/admin/face-enrollment/requests` and `/{id}` | Owner/Admin only; scoped, paginated pending list and safe review summaries. Separate protected preview endpoint decrypts the draft crop with `Cache-Control: no-store`. |
| POST `/api/v1/admin/face-enrollment/requests/{id}/approve` | Owner/Admin only; expected revision and explicit duplicate decision/reason. Active only on committed approval. |
| POST `/api/v1/admin/face-enrollment/requests/{id}/reject` or `/cancel` | Owner/Admin only; reason and expected revision; purge drafts and revoke capture authority. |
| GET `/enroll` | Dedicated mobile capture shell outside `/mobile` Viewer service-worker scope; no employee data without redemption. |
| POST `/api/v1/qr-enrollment/redeem` | Only unauthenticated enrollment capability entry. Strict input/rate limit; accepts the one-use invite secret and issues a narrow capture session. |
| GET `/api/v1/qr-enrollment/status` | Capture-session capability only; own employee/store display context and own request state, no template/candidate identity or global employee list. |
| POST `/api/v1/qr-enrollment/consent`, `/frame`, `/submit`, `/reset` | Capture-session capability only; target comes solely from the bound server request, not submitted student/store IDs. Explicit consent is stored through the existing consent representation. `/reset` affects only the current nonterminal capture and cannot extend expiry or reopen submission. |

Owner/Admin roles are checked explicitly (`SUPER_ADMIN`/`ADMIN`) as well as normal permissions/scope; an `employee.enroll` permission alone does not grant invitation or approval. Existing desktop routes must delegate to this shared preparation service after this feature is approved; they must not retain a direct finalization bypass. Other mature enrollment callers, if discovered, require a compatibility adapter or a separately reviewed scope change.

QR link format: `/enroll#invite=<secret>`. The fragment avoids sending the invitation in ordinary page requests. The capture page consumes it once, clears it from browser history before requests, and sends the secret only in the redemption body. The redeemed secret is held in memory, never localStorage/sessionStorage; session authority uses a narrow `HttpOnly`, `Secure`, `SameSite=Strict` cookie scoped to `/api/v1/qr-enrollment`. Validate same-origin/CSRF on writes; no cross-origin session use. Return only safe status/error enums and do not echo secrets. Protect redemption, consent, frame, submission and decisions with expiry checks on every request.

The capture page shows only the bound employee/store, consent, camera guidance, progress, retry/reset and submission result. It never exposes a duplicate employee's identity, bypass checkbox, RTSP/MediaMTX/decoder diagnostics, or approval action. The administrator review UI shows who/where/source, quality/PAD result, safe preview, duplicate warning, and approve/reject decisions. Desktop and mobile use the same state labels and service results; no separate thresholds.

## HTTPS and local-first deployment prerequisite

The target phone must open a **trusted HTTPS origin** for browser `getUserMedia`; plain store-LAN HTTP is not the supported capture deployment. The existing Viewer LAN links are HTTP and the current browser camera helper requires `navigator.mediaDevices.getUserMedia` (`btmh_v4.js:190`). Do not reuse those Viewer links and imply mobile enrollment will work. Phone `localhost` points to the phone, not the Windows store server.

Choose a local TLS hostname/certificate trusted by the target devices and reachable in the approved store network. This is an acceptance prerequisite; this proposal does not silently change MediaMTX, SMS, router exposure, firewall, reverse-proxy architecture or certificate trust. If local HTTPS is unavailable, keep QR capture unavailable with an explanatory state and preserve desktop capture. Offline operation means installed code/models and local network capture work without cloud services after HTTPS/device setup. QR generation must use a locally bundled implementation, with no runtime CDN/download or token-bearing third-party QR service.

## Planned files and validation

After explicit approval only:

- New `module_app/qr_enrollment.py`: additive schema, invitations/capture lifecycle, shared preparation/PAD wrapper, staged persistence and atomic review/publication. Small adapters in `registry.py` separate preparation from publication without changing quality/duplicate algorithms; `main.py` supplies narrowly scoped routes and middleware capability checks.
- New dedicated mobile capture HTML/JS/CSS and a scoped administrator review module. Reuse browser capture/guidance contracts. Existing `frontend/mobile/` Viewer remains read-only. No SMS/provider or FaceID/PAD model/configuration changes.
- Focused Python tests with isolated/in-memory fixtures: migration idempotency, zero activation on submit/reject/expiry, encrypted blobs, consent revoked after capture, one-use redemption/replay, expired/revoked session, target/store tampering, Owner/Admin enforcement, active-template preservation on rejected replacement, PAD fail/pending cannot submit, duplicate warning and serialized approval race, atomic rollback/restart recovery, capture retirement and draft purge. PostgreSQL migration/concurrency tests require a separate approved test database; never claim them from SQLite evidence.
- Direct sandbox Node tests: QR fragment consumption/redaction, no secret storage, single-flight/latest-frame upload, camera stop on visibility/pagehide/expiry/submission, honest failure states, no client duplicate override/activation call, administrator decision single-flight, stale auth/request guard, keyboard and scoped preview cleanup.
- Actual device acceptance, only when separately authorized: trusted HTTPS on representative phones, permission refusal/no camera, disconnected local network, successful PAD/quality capture, spoof attempt, duplicate face review, Windows restart while pending, approval then store-camera recognition. No real device/camera/PostgreSQL PASS is claimed by this document.

## Approval question this document supports

Approve the two additive tables and staged unified desktop/QR enrollment boundary above, with **active templates published only after Owner/Admin approval**, while leaving all protected models, thresholds, SMS, account-provisioning policy and camera architecture intact?

If approved, first add this scope to `docs/EXECPLAN_DEMO_PRODUCTION_LITE.md`, then implement and run the focused tests within sandbox. If not approved or unanswered, this remains a proposal and no QR migration/implementation proceeds.

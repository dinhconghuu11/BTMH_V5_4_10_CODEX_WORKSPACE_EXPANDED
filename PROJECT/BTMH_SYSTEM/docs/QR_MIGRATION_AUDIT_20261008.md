# QR enrollment migration audit — 2026-10-08

Scope: the approved minimal proposal in [QR_ENROLLMENT_PROPOSAL.md](QR_ENROLLMENT_PROPOSAL.md). The implementation is in `module_app/qr_enrollment.py`; HTTP integration and shared capture use `qr_enrollment_routes.py` and `enrollment_capture.py`. No customer database migration or device acceptance was executed during this audit.

## Exact schema operations

`ensure_qr_enrollment_schema()` issues exactly two `CREATE TABLE IF NOT EXISTS` statements and four `CREATE INDEX IF NOT EXISTS` statements. SQLite uses INTEGER/BLOB; PostgreSQL uses BIGINT/BYTEA for the existing integer references and encrypted bytes. IDs of the new rows are server UUID text, not a new employee identity model.

```sql
CREATE TABLE IF NOT EXISTS face_enrollment_requests (
    id TEXT PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    store_id INTEGER NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('DESKTOP','QR_MOBILE')),
    status TEXT NOT NULL CHECK(status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW','APPROVED','REJECTED','EXPIRED','CANCELLED')),
    template_blob BLOB, preview_blob BLOB, pose_count INTEGER NOT NULL DEFAULT 0,
    quality_json TEXT NOT NULL DEFAULT '{}', pad_json TEXT NOT NULL DEFAULT '{}', duplicate_json TEXT NOT NULL DEFAULT '{}',
    created_by_user_id INTEGER NOT NULL REFERENCES system_users(id),
    submitted_at TEXT, expires_at TEXT NOT NULL,
    reviewed_by_user_id INTEGER REFERENCES system_users(id) ON DELETE SET NULL, reviewed_at TEXT,
    review_reason TEXT NOT NULL DEFAULT '', duplicate_override INTEGER NOT NULL DEFAULT 0 CHECK(duplicate_override IN (0,1)),
    revision INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qr_enrollment_invites (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE REFERENCES face_enrollment_requests(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_by_user_id INTEGER NOT NULL REFERENCES system_users(id),
    created_at TEXT NOT NULL, expires_at TEXT NOT NULL, redeemed_at TEXT, revoked_at TEXT,
    session_hash TEXT UNIQUE, session_expires_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_face_enrollment_review
    ON face_enrollment_requests(status,submitted_at);
CREATE INDEX IF NOT EXISTS idx_face_enrollment_employee
    ON face_enrollment_requests(student_id,created_at);
CREATE INDEX IF NOT EXISTS idx_face_enrollment_store
    ON face_enrollment_requests(store_id,status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_face_enrollment_one_active
    ON face_enrollment_requests(student_id)
    WHERE status IN ('CAPTURING','PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW');
```

There is no ALTER, DROP, rename, existing-table index/column change, backfill, database copy, migration DELETE/UPDATE, or automatic active-template publication. UNIQUE constraints additionally protect invitation request binding, invitation digests and capture-session digests. New foreign-key cascades preserve the existing explicitly authorized employee-delete behavior; schema creation deletes no row. An isolated test removes only its own in-memory tables to verify feature-disabled compatibility; that test operation is not migration code.

## Compatibility and operational disable

Existing students, stores, assignments, users, encrypted `face_templates`, FaceID/PAD models, thresholds and RBAC schema remain compatible. The invitation can bind an employee with `NOT_GRANTED` consent and does not grant consent. Frame/submission/approval require actual current `GRANTED`. Mobile cannot regrant `WITHDRAWN`; the existing consent withdrawal deletes active templates and now cancels pending authority in the same publication transaction.

The explicitly selected **enrollment store** is immutable for the request and is not an HR/store assignment. If employee store assignments already exist, the selected store must match them at creation and approval. If none exist, Owner/Admin may explicitly select a valid permitted enrollment store; the service inserts no assignment and never chooses the first store.

Only runtime Owner/Admin APPROVE writes the existing encrypted format to `face_templates` and marks existing `face_enrollment_validations` pending store-camera validation. Publication, decision and audit commit atomically; INDEX refresh and optional portrait handling run after commit. Submit, rejection, cancellation, expiry, restart and REQUEST REENROLLMENT do not publish a draft. Prior active templates remain active while a replacement is pending/rejected/reenrolled, unless existing consent withdrawal explicitly revokes them.

REQUEST REENROLLMENT uses these same two tables: the old pending row becomes terminal REJECTED with an explicit actor/reason and an audit action; its secret/session authority is retired; a new CAPTURING request and new one-use invitation are created in one transaction. It never reopens a consumed token.

Operational rollback is `BTMH_QR_ENROLLMENT_ENABLED=0` in the application environment, followed by the normal application restart. The HTTP adapter disables new QR/admin enrollment and staged desktop entry routes; direct desktop finalization has no publication bypass. Keep both additive tables and existing active templates. Do not automatically DROP tables, restore old template data, or roll back the customer database. Existing consent withdrawal/deletion still work when the optional new schema is absent. Submitted drafts remain encrypted and require a later explicit valid approval; startup retires incomplete captures before resumed enrollment.

## Evidence and limits

`tests_demo/test_qr_enrollment.py`: **18/18 PASS** in isolated real SQLite, with explicit UTC clocks, concurrent threads, current-role checks and an authenticated test crypto adapter. It verifies schema idempotency/exactly two additions/unchanged legacy schema and bytes; hashed-only invitations; expiry/reuse/reissue/revocation; consent and server quality/PAD gating; pending-only encrypted submission and replay; explicit approval and after-commit refresh; rejected/reenrolled old-template preservation; serialized duplicate approval and reason-required override; publication rollback; restart; withdrawal transaction rollback/after-commit retirement; desktop binding/single-flight/late revocation; unique active request across stores; SQL-scoped filters; employee delete compatibility; and cancellation without the optional schema. Python compile checks passed.

The test codec substitutes the crypto boundary because the local test interpreters do not have the cryptography dependency. Production continues to call the existing installed crypto helpers; this is not a claim of installed-key/Fernet execution. PostgreSQL DDL/advisory-lock paths are implemented, but no PostgreSQL server/concurrency acceptance is claimed. HTTP adapter tests, real ASGI transport/body enforcement, trusted phone HTTPS, browser camera/PAD hardware and actual customer database migration are separate validation boundaries; no PASS for those is inferred from these service tests.

## Integration review checkpoint

Independent review corrected two publication/capture races without additional schema changes. Reset purges transient capture/PAD evidence inside the publication transaction before a new revision can be leased; reset callback failure rolls back the revision. Optional portrait persistence after approval rechecks current consent and the exact active encrypted template inside a fresh publication transaction, using the existing photo metadata writer on that same connection. A delayed approval cannot recreate a withdrawn portrait or overwrite a later approved replacement. These runtime guards do not rewrite existing FaceID data as a migration.

Focused evidence: service **18 PASS**, capture **12 PASS**, HTTP adapters **17 PASS**, integration race/portrait writer **5 PASS**. HTTP tests execute the actual middleware body-limiter with ASGI receive/send adapters, exact TLS/origin/rate gates, narrow cookie authority and real local QR encode/decode. Full FastAPI/Pydantic request parsing remains **BLOCKED** by sandbox dependency access (`typing_extensions.py` PermissionError); adapter tests must not be described as end-to-end HTTP server acceptance. Mobile UI **22 PASS**, administrator UI **25 PASS** and desktop staging UI **13 PASS** are direct Node VM lifecycle/contract checks, not rendered browser or phone acceptance.

Audit conclusion: **two new tables; no existing schema edits; no destructive migration; no data migration; no second database**. The operational disable path above remains the rollback path. The customer database has not been migrated by this development task.

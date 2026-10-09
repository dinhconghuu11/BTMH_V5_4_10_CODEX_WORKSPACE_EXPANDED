# CampusFace V1 FACE - Test Report

## Regression
- 35 current CampusFace regression modules: PASS.

## Context-first anti-spoof checks
- Phone/screen carrier: hard context evidence -> CHECKING -> BLOCKED before FaceID.
- Genuine face with classroom-line background: remains non-hard and can PASS after passive multi-frame confirmation.
- PASS remains revocable if a strong device/screen context appears later in the same physical track.
- Blocked track clears live identity candidate and cannot produce successful check-in.

## Deployment lineage
- Reuses the proven per-user PostgreSQL profile from V1.14.3.
- No Windows PostgreSQL service.
- No ProgramData ACL repair path.

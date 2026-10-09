# BTMH project instructions for Codex

## Read first
Before making changes, read:
1. `00_START_HERE/README_CODEX.md`
2. `00_START_HERE/PROJECT_MAP.md`
3. `00_START_HERE/ARCHITECTURE.md`
4. `00_START_HERE/CURRENT_STATUS.md`
5. `00_START_HERE/CODEX_RULES.md`

The canonical editable source is `PROJECT/BTMH_SYSTEM/`.
The numbered top-level folders are navigation indexes only. Do not implement fixes inside those index folders.

## Product constraints
- Product: Bảo Tín Mạnh Hải recognition/security/attendance system.
- Target: Windows, local-first, able to operate offline after installation.
- Preserve PostgreSQL, RBAC, camera registry, attendance, FaceID and Passive PAD unless the task explicitly requires changes there.
- Never hard-code customer IPs, camera credentials, owner passwords, SMS secrets, access tokens, or API keys.
- Never put RTSP credentials in browser storage, frontend source, logs, docs, or committed config.
- Treat database camera records as the canonical source for configured cameras.

## Realtime architecture
- Live video transport and AI inference are separate concerns.
- Prefer native media gateway/WebRTC path for Live View.
- JPEG/WebSocket/MJPEG paths are fallbacks only, not the primary architecture.
- AI should not block browser video.
- Realtime AI favors latest-frame behavior instead of unbounded frame queues.

## Change discipline
- Make the smallest coherent change that solves the requested problem.
- Do not rewrite mature FaceID/PAD logic while fixing video transport or UI.
- Do not change recognition thresholds just to improve performance.
- Preserve safe camera handover and camera-registry persistence behavior from 5.4.6/5.4.7.
- For changes touching architecture or more than three subsystems, create/update an ExecPlan following `.agent/PLANS.md` before implementation.

## Validation
After relevant changes, run the narrowest applicable tests first, then broader verification when practical:
- `python -m pytest -q tests_v54`
- `python VERIFY_RELEASE.py`
- JavaScript syntax checks for changed frontend JS files.
- Python compile checks for changed Python files.
Do not report a test as passed unless it was actually run successfully.

# Codex Rules for BTMH

1. Read architecture and current status before editing.
2. Edit only canonical code under `PROJECT/BTMH_SYSTEM/`.
3. Never hard-code the customer's live camera IP or any password/secret into product defaults.
4. Never expose RTSP credentials to frontend code, localStorage, docs, browser logs or audit logs.
5. Treat Live View transport and AI inference as separate pipelines.
6. Native gateway/WebRTC is primary; JPEG transports are fallback only.
7. Do not solve lag by disabling Passive PAD, weakening anti-spoof, lowering recognition thresholds, or removing multi-frame safety unless explicitly requested.
8. Avoid unbounded frame queues; realtime work should prefer fresh frames.
9. Keep Windows/local/offline deployment practical.
10. For every fix, state: observed cause, files changed, regression risk, tests run and rollback path.

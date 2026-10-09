# Useful prompts for Codex

## Understand the project
`Read AGENTS.md and everything in 00_START_HERE. Then inspect the canonical source and explain the current camera/video architecture without changing code.`

## Investigate Live View lag
`Read the 5.4.10 native gateway path end-to-end. Trace Hikvision RTSP -> MediaMTX -> WHEP/WebRTC -> browser <video>. Identify any fallback or code path that can silently return to JPEG and propose a minimal fix with tests.`

## Work on AI performance later
`Do not touch Live View transport. Profile the AI pipeline only. Find where FaceID/PAD latency is accumulated and propose latest-frame, tracking, crop-first and scheduling improvements without lowering recognition or anti-spoof thresholds.`

## UI-only change
`Treat backend camera/AI/database code as protected. Modify only frontend files required for this UI request and run syntax checks on every changed JS file.`

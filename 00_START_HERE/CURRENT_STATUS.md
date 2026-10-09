# Current Status - V5.4.10

## Confirmed working before this development package
- Hikvision DS-2CD1123G0-IUF reachable on LAN.
- RTSP port and H.264 main stream verified externally.
- Camera registry persistence issue from the older 192.168.1.x record was addressed in 5.4.6/5.4.7.
- Live video could display in the web UI, but JPEG-based paths were visibly laggy.

## V5.4.10 objective
Move the primary Live View transport to a native media gateway/WebRTC path so browser video is decoupled from Python JPEG rendering and AI inference latency.

## Next major performance phase
After Live View transport is proven on the real Windows/Hikvision machine, optimize the AI pipeline separately: substream selection, tracking, crop-first inference, scheduling and optional hardware acceleration.

## Protected behavior
Do not regress camera registry persistence, safe source handover, FaceID/PAD correctness, attendance data, RBAC or local-first/offline operation while optimizing performance.

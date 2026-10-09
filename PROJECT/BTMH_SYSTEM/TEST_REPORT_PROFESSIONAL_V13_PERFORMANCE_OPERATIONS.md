# CampusFace V13 - Performance Operations test report

Version: `1.30.0-v1-face-pro-v13-performance-operations`

Validated in the build workspace:
- Python syntax/compile: `config.py`, `camera.py`, `main.py` - PASS.
- Frontend JavaScript syntax (`node --check frontend/js/app.js`) - PASS.
- V13 Performance + Operations static contract - PASS.
- V12.1 Safe Camera Handover regression contract - PASS.
- Camera recovery runtime tests - PASS.
- Recognition page passive anti-spoof contract preservation - PASS.
- Runtime Performance Guard test: overload reduces AI cadence, stable load recovers cadence - PASS.
- Runtime PTZ inference hold test - PASS.

Hardware note: USB/PTZ/RTSP driver behavior and actual latency must still be benchmarked on the customer's physical camera and PC. V13 exposes the relevant FPS, p95 latency and stale-frame metrics for that test.

# README CODEX - BTMH V5.4.10

BTMH is a local-first Windows web application for camera monitoring, FaceID, Passive PAD/anti-spoof, attendance, personnel, evidence, history, RBAC and system administration.

## Current development baseline
- Version line: 5.4.10 Native Video Gateway RC.
- Hikvision camera connection/registry persistence was stabilized in 5.4.6-5.4.7.
- 5.4.8 introduced realtime-performance controls.
- 5.4.9 moved away from HTTP snapshot polling but still used JPEG-over-WebSocket locally.
- 5.4.10 introduces a native media gateway path so Live View can use RTSP H.264 -> MediaMTX -> WHEP/WebRTC -> browser `<video>`.

## Canonical source
All real code lives under `../PROJECT/BTMH_SYSTEM/`.

## First places to read for camera/live-view work
- `../PROJECT/BTMH_SYSTEM/module_app/media_gateway_v5410.py`
- `../PROJECT/BTMH_SYSTEM/module_app/rtsp_native_v545.py`
- `../PROJECT/BTMH_SYSTEM/module_app/camera_registry_v547.py`
- `../PROJECT/BTMH_SYSTEM/frontend/js/btmh_media_v5410.js`
- `../PROJECT/BTMH_SYSTEM/frontend/css/btmh_media_v5410.css`
- `../PROJECT/BTMH_SYSTEM/scripts/ensure_mediamtx_v5410.ps1`
- `../PROJECT/BTMH_SYSTEM/tests_v54/test_native_gateway_v5410.py`

## Do not use this workspace as customer runtime data
This package intentionally excludes local runtime secrets and customer data. Never copy `%LOCALAPPDATA%\CampusFace` credentials/templates into this repository.

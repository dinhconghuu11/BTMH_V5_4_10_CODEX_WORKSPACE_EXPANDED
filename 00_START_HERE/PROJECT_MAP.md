# Project Map

## Backend/API
Canonical folder: `PROJECT/BTMH_SYSTEM/module_app/`
Core entry points include `main.py`, `production_ops.py`, `platform_v5.py`, `config.py`, `db.py` and `registry.py`.

## Camera and realtime video
- `camera.py`, `camera_profiles.py`, `camera_catalog_v543.py`
- `camera_connection_v544.py`, `camera_handover_v544.py`
- `camera_registry_v546.py`, `camera_registry_v547.py`
- `capture_worker_v544.py`, `capture_session_v544.py`
- `camera_fleet_v4.py`, `camera_manager_v17.py`
- `rtsp_native_v545.py`
- `media_webrtc.py`
- `media_gateway_v5410.py`
- `recording.py`, `recording_runtime_v4.py`

## Face AI / liveness
- `face_core.py`
- `passive_pad.py`
- `anti_spoof.py`
- `walkby.py`
- `edge_identity_v5.py`
- `gpu_manager.py`
- `device_context.py`

## Frontend
Canonical folder: `PROJECT/BTMH_SYSTEM/frontend/`
Key current files:
- `index.html`
- `js/app.js`
- `js/btmh_customer_v541.js`
- `js/btmh_runtime_v543.js`
- `js/camera_tools_v544.js`
- `js/btmh_media_v549.js`
- `js/btmh_media_v5410.js`
- `css/btmh_media_v5410.css`
- `css/btmh_ui_v543.css`

## Database/security
- `db.py`, `auth.py`, `crypto.py`, `secret_store.py`
- `security_hardening_v54.py`
- `otp_service.py`
- `sms_auth_v542.py`, `sms_provider_v542.py`, `sms_routes_v542.py`

## Tests
Current camera/realtime tests are in `PROJECT/BTMH_SYSTEM/tests_v54/`, especially:
- `test_camera_v544.py`
- `test_camera_registry_v546.py`
- `test_camera_registry_v547.py`
- `test_rtsp_native_v545.py`
- `test_realtime_performance_v548.py`
- `test_true_realtime_v549.py`
- `test_native_gateway_v5410.py`

## Windows/deployment
- root `.bat` launch/install scripts under `PROJECT/BTMH_SYSTEM/`
- helper scripts under `PROJECT/BTMH_SYSTEM/scripts/`
- MediaMTX bootstrap: `scripts/ensure_mediamtx_v5410.ps1`

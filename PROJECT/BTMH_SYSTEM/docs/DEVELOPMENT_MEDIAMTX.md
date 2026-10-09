# Run BTMH development from VS Code

Open `BTMH_V5_4_10_CODEX.code-workspace`, select **Terminal > Run Task > BTMH: Start Development**. The process task calls the canonical `START_CAMPUSFACE_DEV.bat`. That wrapper forces `BTMH_ENV=development` and passes `--development` to the shared launch sequence, which propagates the existing environment configuration to the checker/backend. The launch prints `[MODE] DEVELOPMENT` and opens the existing frontend at http://127.0.0.1:8100/.

Existing prerequisites remain: Python dependencies, FaceID models, private PostgreSQL and the normal readiness/security checks. The default interpreter is `%LOCALAPPDATA%\CampusFace\runtime\venv\Scripts\python.exe` (or the configured DataRoot runtime). For an already prepared development virtual environment, set `BTMH_DEV_PYTHON` to its `python.exe`; the override applies only in development. A first install stopped at MediaMTX may not have completed the later models/PostgreSQL steps. This change bypasses only the MediaMTX requirement in development.

From the VS Code PowerShell terminal:

```powershell
& "C:\FACE\BTMH_V5_4_10_CODEX_WORKSPACE_EXPANDED\PROJECT\BTMH_SYSTEM\START_CAMPUSFACE_DEV.bat"
```

Missing MediaMTX prints:

```text
[MODE] DEVELOPMENT
[WARN] Native MediaMTX unavailable: MEDIAMTX_NOT_INSTALLED
[INFO] Development fallback transport enabled
```

Unsupported/unverified binaries report `MEDIAMTX_UNSUPPORTED_BINARY`. Backend/frontend continue; the existing fallback chain is Python WebRTC, WebSocket, MJPEG, then polling according to actual availability. Every fallback is shown on the Live View and recorded in media events/diagnostics.

**Production:** use **BTMH: Start Windows** or call `START_CAMPUSFACE.bat` directly. Direct batch launches force `BTMH_ENV=production`, even if a VS Code terminal inherited `BTMH_ENV=development`; the launcher prints `[MODE] PRODUCTION`. The dedicated DEV wrapper is the supported development entrypoint. Previously the shared launcher inherited `BTMH_ENV` and defaulted it to production when absent, which explains production errors when it was called directly from VS Code. Easy Install remains a production entrypoint and requires MediaMTX. Production startup fails before app workers start if a supported verified binary cannot be found; direct uvicorn startup enforces the existing `BTMH_ENV` policy.

## Install MediaMTX from a local ZIP

From `PROJECT/BTMH_SYSTEM`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_mediamtx_offline.ps1 `
  -ZipPath "C:\path\mediamtx_v1.21.1_windows_amd64.zip" `
  -DataRoot "$env:LOCALAPPDATA\CampusFace"
```

Supported release: **1.21.1 Windows amd64**, pinned archive SHA-256:

```text
faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23
```

The installer needs no Internet, rejects incorrect hashes/unsafe ZIP entries, never executes the binary, stages replacement with rollback, and writes `VERSION.txt`, `INSTALL_RECEIPT.json` and `THIRD_PARTY_NOTICE.txt`. Keep the retained ZIP in the installed runtime: it proves executable provenance and makes later startup verification offline.

Discovery order: DataRoot `runtime/mediamtx/mediamtx.exe`, `BTMH_MEDIAMTX_BIN` (legacy `BTMH_MEDIAMTX_BINARY` also accepted), development `tools/mediamtx[/mediamtx.exe]` or `vendor/mediamtx[/mediamtx.exe]`, then system PATH. Candidates must match the executable inside the pinned ZIP, available alongside the executable or in DataRoot `downloads`/`runtime/mediamtx`. A bare version marker or an arbitrary PATH executable is insufficient; discovery does not execute an unverified `--version` probe. The application supplies its own supported, secret-free gateway configuration.

## Confirm the transport

After authentication, inspect `/api/v1/media/gateway/status`. Missing MediaMTX reports:

```json
{"available": false, "reason": "MEDIAMTX_NOT_INSTALLED", "native_webrtc": false, "state": "UNAVAILABLE", "transport": "NONE"}
```

Gateway availability shows that native negotiation is possible; the **Current transport** badge in each Live View shows what the browser is actually rendering. `NATIVE_GATEWAY_WEBRTC` confirms native media; `PYTHON_WEBRTC`, `WEBSOCKET_ACK_BITMAP`, `MJPEG` or `POLLING` indicates explicit fallback. In browser developer tools, `BTMHMedia.stats()` exposes `currentTransport`, gateway state/reason and fallback history. No RTSP credentials are returned.

To install MediaMTX while developing, install the verified ZIP then restart/reconnect the Live View; the bounded gateway watchdog also retries availability automatically. No database/camera-registry migration is required. Roll back by restoring the changed source/task files; customer data and models are unaffected.

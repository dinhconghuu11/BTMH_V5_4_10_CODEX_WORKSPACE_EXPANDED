from __future__ import annotations

import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v549_fallback_transport_retained_behind_native_gateway():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    media = (ROOT / "frontend" / "js" / "btmh_media_v5410.js").read_text(encoding="utf-8")

    assert "btmh_media_v5410.js?v=5.4.10" in html
    assert "btmh_media_v5410.css?v=5.4.10" in html
    assert "BTMHMedia.mount('recognition'" in app
    assert "BTMHMedia.mount('dashboard'" in app
    assert "BTMHMedia.mount('live-monitor'" in app
    assert "const order = ['native', 'webrtc', 'ws', 'mjpeg', 'poll']" in media
    assert "NATIVE_GATEWAY_WEBRTC" in media
    assert "WEBSOCKET_ACK_BITMAP" in media
    assert "/api/v1/media/preview/ws" in media
    assert "/api/v1/media/webrtc/offer" in media
    assert "createImageBitmap" in media  # fallback only
    assert "getStats()" in media
    assert "ws.send('ack')" in media


def test_v549_server_zero_backlog_fallback_contract_remains():
    main = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    media = (ROOT / "module_app" / "media_webrtc.py").read_text(encoding="utf-8")

    assert '@app.websocket("/api/v1/media/preview/ws")' in main
    assert "CAMERA.latest_observation_packet()" in main
    assert "await websocket.send_bytes(jpeg)" in main
    assert "await asyncio.wait_for(websocket.receive_text(), timeout=3.0)" in main
    assert "latest_media_packet()" in media
    assert "MEDIA_WEBRTC_FPS" in media
    assert "MEDIA_WEBRTC_WIDTH" in media


def test_v549_preview_ws_ack_paces_one_frame(monkeypatch):
    import module_app.main as main

    class FakeWebSocket:
        def __init__(self):
            self.accepted = False
            self.sent = []
            self.closed = False

        async def accept(self):
            self.accepted = True

        async def send_bytes(self, data):
            self.sent.append(bytes(data))

        async def receive_text(self):
            return "stop"

        async def close(self, code=None):
            self.closed = True

    ws = FakeWebSocket()
    monkeypatch.setattr(main, "_websocket_user", lambda _ws: {"id": 1, "role": "ADMIN"})
    monkeypatch.setattr(main.CAMERA, "latest_observation_packet", lambda: (b"jpeg-frame", 7, 0.0))
    asyncio.run(main.media_preview_ws(ws))
    assert ws.accepted is True
    assert ws.sent == [b"jpeg-frame"]

from __future__ import annotations

import asyncio
import os
import time
import uuid
from fractions import Fraction
from typing import Any

import cv2
import numpy as np

from .camera import CAMERA
from .camera_profiles import normalize_camera_source
from .config import (
    OBSERVATION_PREVIEW_FPS,
    OBSERVATION_PREVIEW_WIDTH,
    RTSP_PREVIEW_FPS,
    RTSP_PREVIEW_WIDTH,
)

_AIORTC_ERROR = ""
try:  # Optional runtime. Same-PC deployments have a zero-backlog WS fast path.
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCRtpSender, VideoStreamTrack  # type: ignore
    from av import VideoFrame  # type: ignore
    AIORTC_AVAILABLE = os.getenv("MODULE_WEBRTC_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
except Exception as exc:  # pragma: no cover - legacy/offline runtimes may omit aiortc
    RTCPeerConnection = None  # type: ignore
    RTCSessionDescription = None  # type: ignore
    RTCRtpSender = None  # type: ignore
    VideoStreamTrack = object  # type: ignore
    VideoFrame = object  # type: ignore
    AIORTC_AVAILABLE = False
    _AIORTC_ERROR = f"{type(exc).__name__}: {exc}"


MEDIA_WEBRTC_FPS = max(
    10,
    min(
        24,
        int(
            os.getenv(
                "BTMH_MEDIA_WEBRTC_FPS",
                str(min(int(OBSERVATION_PREVIEW_FPS), int(RTSP_PREVIEW_FPS))),
            )
        ),
    ),
)
MEDIA_WEBRTC_WIDTH = max(
    720,
    min(
        1920,
        int(
            os.getenv(
                "BTMH_MEDIA_WEBRTC_WIDTH",
                str(min(int(OBSERVATION_PREVIEW_WIDTH), int(RTSP_PREVIEW_WIDTH))),
            )
        ),
    ),
)


class LatestCameraVideoTrack(VideoStreamTrack):  # type: ignore[misc]
    """WebRTC video track with a strict newest-frame policy.

    No application frame queue is ever created. The track samples the current
    camera frame at a bounded cadence and downscales only the browser media copy.
    FaceID/PAD continue to consume their own backend lane and are not modified.
    """

    kind = "video"

    def __init__(
        self,
        service: "WebRTCMediaService",
        target_fps: int = MEDIA_WEBRTC_FPS,
        target_width: int = MEDIA_WEBRTC_WIDTH,
        source_identity: str | None = None,
    ) -> None:
        if not AIORTC_AVAILABLE:
            raise RuntimeError("aiortc runtime is not installed")
        super().__init__()
        self._service = service
        self._fps = max(10, min(24, int(target_fps or MEDIA_WEBRTC_FPS)))
        self._target_width = max(720, min(1920, int(target_width or MEDIA_WEBRTC_WIDTH)))
        self._time_base = Fraction(1, 90000)
        self._step = max(1, int(round(90000 / self._fps)))
        self._pts = 0
        self._next_due = time.perf_counter()
        self._last_seq = -1
        self._source_identity = source_identity

    @staticmethod
    def _resize(frame: np.ndarray, target_width: int) -> np.ndarray:
        if frame is None or frame.size == 0:
            return frame
        height, width = frame.shape[:2]
        if width <= target_width:
            return frame
        scale = target_width / float(width)
        return cv2.resize(
            frame,
            (target_width, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )

    async def recv(self):  # type: ignore[override]
        now = time.perf_counter()
        wait = self._next_due - now
        if wait > 0:
            await asyncio.sleep(wait)
        now = time.perf_counter()
        self._next_due = max(self._next_due + (1.0 / self._fps), now)

        if self._source_identity is not None and normalize_camera_source(CAMERA.current_source_identity()) != self._source_identity:
            self.stop()
            raise RuntimeError("MEDIA_CAMERA_SOURCE_CHANGED")
        frame, seq, source_at = CAMERA.latest_media_packet()
        # A scoped grid tile must not relabel frames if handover commits while
        # the latest frame is sampled. Generic primary views follow selection.
        if self._source_identity is not None and normalize_camera_source(CAMERA.current_source_identity()) != self._source_identity:
            self.stop()
            raise RuntimeError("MEDIA_CAMERA_SOURCE_CHANGED")
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        else:
            frame = self._resize(frame, self._target_width)

        self._last_seq = int(seq)
        self._pts += self._step
        video = VideoFrame.from_ndarray(frame, format="bgr24")  # type: ignore[union-attr]
        video.pts = self._pts
        video.time_base = self._time_base
        self._service.note_frame(
            seq=int(seq),
            source_at=float(source_at or 0.0),
            shape=frame.shape,
        )
        return video


class WebRTCMediaService:
    def __init__(self) -> None:
        self._peers: dict[str, Any] = {}
        self._created_at: dict[str, float] = {}
        self._owners: dict[str, str] = {}
        self._tracks: dict[str, Any] = {}
        self._sources: dict[str, str | None] = {}
        self._reaper: asyncio.Task | None = None
        self._frames_sent = 0
        self._last_frame_seq = 0
        self._last_source_age_ms: float | None = None
        self._last_width = 0
        self._last_height = 0
        self._last_frame_at = 0.0

    def note_frame(self, *, seq: int, source_at: float, shape) -> None:
        self._frames_sent += 1
        self._last_frame_seq = int(seq)
        self._last_frame_at = time.time()
        if source_at > 0:
            self._last_source_age_ms = max(0.0, (time.perf_counter() - source_at) * 1000.0)
        try:
            self._last_height = int(shape[0])
            self._last_width = int(shape[1])
        except Exception:
            pass

    def capabilities(self) -> dict[str, Any]:
        return {
            "ok": True,
            "webrtc": {
                "available": bool(AIORTC_AVAILABLE),
                "transport": "WEBRTC" if AIORTC_AVAILABLE else "UNAVAILABLE",
                "target_fps": int(MEDIA_WEBRTC_FPS),
                "target_width": int(MEDIA_WEBRTC_WIDTH),
                "zero_backlog": True,
                "native_frame": True,
                "error": "" if AIORTC_AVAILABLE else _AIORTC_ERROR,
            },
            "local_fast_path": {
                "transport": "WEBSOCKET_ACK_BITMAP",
                "zero_backlog": True,
                "reason": "Avoid a second video encode when browser and server are on the same PC",
            },
            "metadata": {
                "transport": "WEBSOCKET_LATEST_STATE",
                "overlay": "BROWSER_CANVAS",
                "server_draws_boxes": False,
                "zero_backlog": True,
            },
            "policy": "AUTO_LOCAL_WS_LAN_WEBRTC",
            "fallback_chain": ["WEBSOCKET_ACK_BITMAP", "MJPEG", "HTTP_SNAPSHOT"],
            "active_peers": len(self._peers),
        }

    def status(self) -> dict[str, Any]:
        out = self.capabilities()
        out.update(
            {
                "frames_sent": int(self._frames_sent),
                "last_frame_seq": int(self._last_frame_seq),
                "last_source_age_ms": None
                if self._last_source_age_ms is None
                else round(self._last_source_age_ms, 1),
                "last_width": int(self._last_width),
                "last_height": int(self._last_height),
                "last_frame_at": float(self._last_frame_at),
            }
        )
        return out

    async def _reap_pending(self) -> None:
        while self._peers:
            await asyncio.sleep(2.0)
            for sid, pc in list(self._peers.items()):
                source = self._sources.get(sid)
                if source is not None and normalize_camera_source(CAMERA.current_source_identity()) != source:
                    await self.close(sid)
                elif getattr(pc, "connectionState", "new") != "connected" and time.time() - self._created_at.get(sid, 0) > 20:
                    await self.close(sid)

    async def create_answer(self, *, sdp: str, offer_type: str = "offer", owner: str = "", source_identity: str | None = None) -> dict[str, Any]:
        if not AIORTC_AVAILABLE or RTCPeerConnection is None or RTCSessionDescription is None:
            raise RuntimeError("WebRTC runtime chưa được cài. Hệ thống sẽ dùng luồng realtime dự phòng.")

        if len(self._peers) >= 32 or (owner and sum(value == owner for value in self._owners.values()) >= 8):
            raise RuntimeError("Đã đạt giới hạn phiên WebRTC đang hoạt động")
        pc = RTCPeerConnection()
        session_id = uuid.uuid4().hex
        self._peers[session_id] = pc
        self._created_at[session_id] = time.time()
        self._owners[session_id] = str(owner)
        self._sources[session_id] = normalize_camera_source(source_identity) if source_identity is not None else None
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_pending())
        try:
            track = LatestCameraVideoTrack(
                self,
                target_fps=int(MEDIA_WEBRTC_FPS),
                target_width=int(MEDIA_WEBRTC_WIDTH),
                source_identity=self._sources[session_id],
            )
            self._tracks[session_id] = track
            sender = pc.addTrack(track)
        except BaseException:
            await self.close(session_id)
            raise

        # VP8 is the safest software codec for aiortc on heterogeneous Windows PCs.
        # Same-PC BTMH normally uses the ACK-paced bitmap fast path, so this encoder
        # is primarily for LAN browsers where WebRTC saves bandwidth and browser work.
        try:
            transceiver = next(x for x in pc.getTransceivers() if x.sender is sender)
            codecs = list(RTCRtpSender.getCapabilities("video").codecs) if RTCRtpSender else []
            vp8 = [x for x in codecs if str(getattr(x, "mimeType", "")).lower() == "video/vp8"]
            rest = [x for x in codecs if x not in vp8]
            if vp8:
                transceiver.setCodecPreferences(vp8 + rest)
        except Exception:
            pass

        @pc.on("connectionstatechange")
        async def _on_state_change():
            if pc.connectionState in {"failed", "closed"}:
                await self.close(session_id)
            elif pc.connectionState == "disconnected":
                # A lost tab must not leave a software encoder running forever.
                await asyncio.sleep(3.0)
                if self._peers.get(session_id) is pc and pc.connectionState == "disconnected":
                    await self.close(session_id)

        try:
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=str(sdp), type=str(offer_type or "offer"))
            )
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            deadline = time.monotonic() + 2.5
            while (
                getattr(pc, "iceGatheringState", "complete") != "complete"
                and time.monotonic() < deadline
            ):
                await asyncio.sleep(0.025)
            local = pc.localDescription
            return {
                "ok": True,
                "session_id": session_id,
                "sdp": str(local.sdp),
                "type": str(local.type),
                "transport": "WEBRTC",
                "target_fps": int(MEDIA_WEBRTC_FPS),
                "target_width": int(MEDIA_WEBRTC_WIDTH),
                "zero_backlog": True,
            }
        except BaseException:
            await self.close(session_id)
            raise

    async def close(self, session_id: str, *, owner: str | None = None) -> bool:
        sid = str(session_id or "").strip()
        if sid in self._peers and owner is not None and self._owners.get(sid) != str(owner):
            raise PermissionError("Phiên WebRTC thuộc người dùng khác")
        pc = self._peers.pop(sid, None)
        self._created_at.pop(sid, None)
        self._owners.pop(sid, None)
        self._sources.pop(sid, None)
        track = self._tracks.pop(sid, None)
        if track is not None:
            track.stop()
        if pc is None:
            return False
        try:
            await pc.close()
        except Exception:
            pass
        return True

    async def close_all(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            try:
                await self._reaper
            except asyncio.CancelledError:
                pass
            self._reaper = None
        for sid in list(self._peers):
            await self.close(sid)


MEDIA = WebRTCMediaService()

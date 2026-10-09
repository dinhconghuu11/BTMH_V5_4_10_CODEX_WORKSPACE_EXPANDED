"""Optional real MediaMTX/H.264/WHEP smoke; never connects to a customer camera.

Run from the source root with aiortc and imageio_ffmpeg installed:
    python tests_integration/native_gateway_smoke.py --binary PATH --seconds 10

This measures a loopback synthetic stream, not browser rendering, Hikvision
compatibility or real-camera LAN latency. All runtime files are temporary.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def free_ports(count: int) -> list[int]:
    """Hold distinct TCP ports while checking UDP availability for ICE too."""
    sockets = []
    ports = []
    try:
        while len(ports) < count:
            tcp = socket.socket()
            tcp.bind(("127.0.0.1", 0))
            port = tcp.getsockname()[1]
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                udp.bind(("127.0.0.1", port))
            except OSError:
                tcp.close()
                udp.close()
                continue
            sockets.extend((tcp, udp))
            ports.append(port)
        return ports
    finally:
        for sock in sockets:
            sock.close()


def spawn(argv: list[str], **kwargs) -> subprocess.Popen:
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    return subprocess.Popen(argv, **kwargs)


def reap(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
    finally:
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()


async def wait_until(predicate, message: str, timeout: float = 12) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = await asyncio.to_thread(predicate)
        if value:
            return value
        await asyncio.sleep(0.15)
    raise RuntimeError(message)


async def run(binary: Path, seconds: float, runtime: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    os.environ["CAMPUSFACE_DATA_ROOT"] = str(runtime / "app-data")
    os.environ["CAMPUSFACE_DB_MODE"] = "sqlite"
    os.environ["BTMH_MEDIAMTX_BINARY"] = str(binary)
    os.environ["BTMH_MEDIA_GATEWAY_ENABLED"] = "1"
    os.environ["BTMH_NETWORK_MODE"] = "local"
    os.environ["MODULE_HOST"] = "127.0.0.1"
    os.environ["BTMH_MEDIA_GATEWAY_ICE_HOSTS"] = ""
    rtsp, api, http, ice, native_api, metrics, relay = free_ports(7)
    for key, value in {"HTTP": http, "ICE": ice, "API": native_api,
                       "METRICS": metrics, "RTSP": relay}.items():
        os.environ[f"BTMH_MEDIA_GATEWAY_{key}_PORT"] = str(value)

    import imageio_ffmpeg
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCRtpReceiver, RTCSessionDescription
    from module_app.media_gateway_v5410 import NativeMediaGateway
    from module_app.rtsp_native_v545 import input_manifest

    version = subprocess.run([str(binary), "--version"], capture_output=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    require(version.returncode == 0 and b"v1.21.1" in version.stdout, "Expected pinned MediaMTX v1.21.1")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    gateway = NativeMediaGateway()
    upstream = publisher = relay_reader = None
    peers = []
    report = {"ok": False, "scope": "SYNTHETIC_LOOPBACK_ONLY", "version": "1.21.1",
              "transport": "NATIVE_GATEWAY_WEBRTC", "codec": "H264",
              "source": {"width": 1920, "height": 1080, "fps": 25}, "peers": []}
    opener = build_opener(ProxyHandler({}))

    def upstream_path():
        try:
            with opener.open(f"http://127.0.0.1:{api}/v3/paths/get/testcam", timeout=0.5) as response:
                return json.loads(response.read(65536))
        except (OSError, ValueError):
            return {}

    async def status():
        def read():
            with gateway._lock:
                gateway._diagnostics_at = 0
            return gateway.status()
        return await asyncio.to_thread(read)

    async def open_peer(name: str):
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        item = {"name": name, "pc": pc, "session_id": "", "tasks": [],
                "frames": 0, "dimensions": set(), "first_frame": 0.0, "last_frame": 0.0}
        peers.append(item)
        transceiver = pc.addTransceiver("video", direction="recvonly")
        transceiver.setCodecPreferences([codec for codec in RTCRtpReceiver.getCapabilities("video").codecs
                                        if codec.mimeType.lower() == "video/h264"])

        async def consume(track):
            while True:
                frame = await track.recv()
                now = time.monotonic()
                item["first_frame"] = item["first_frame"] or now
                item["last_frame"] = now
                item["frames"] += 1
                item["dimensions"].add((frame.width, frame.height))

        @pc.on("track")
        def on_track(track):
            item["tasks"].append(asyncio.create_task(consume(track)))

        await pc.setLocalDescription(await pc.createOffer())
        answer = await asyncio.to_thread(gateway.create_whep_session, pc.localDescription.sdp, "synthetic-smoke")
        item["session_id"] = answer["session_id"]
        require("H264/90000" in answer["sdp"], "MediaMTX answer did not negotiate H264")
        await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
        await wait_until(lambda: item["frames"] >= 3, f"Peer {name} received no decoded H264 frames", 15)
        require(item["dimensions"] == {(1920, 1080)}, f"Peer {name} changed source dimensions")
        return item

    async def close_peer(item):
        await item["pc"].close()
        for task in item["tasks"]:
            task.cancel()
        await asyncio.gather(*item["tasks"], return_exceptions=True)
        if item["session_id"]:
            await asyncio.to_thread(gateway.delete_whep_session, item["session_id"], "synthetic-smoke")
            item["session_id"] = ""

    try:
        upstream_config = runtime / "upstream.yml"
        upstream_config.write_text(f"""logLevel: error
logDestinations: [stdout]
authMethod: internal
authInternalUsers:
  - user: any
    pass:
    ips: [127.0.0.1]
    permissions:
      - action: publish
        path: testcam
      - action: read
        path: testcam
      - action: api
api: true
apiAddress: 127.0.0.1:{api}
rtsp: true
rtspAddress: 127.0.0.1:{rtsp}
rtspTransports: [tcp]
rtmp: false
hls: false
webrtc: false
srt: false
moq: false
paths:
  testcam:
    source: publisher
""", encoding="utf-8")
        upstream = spawn([str(binary), str(upstream_config)], cwd=runtime,
                         env={key: value for key, value in os.environ.items() if not key.startswith("MTX_")},
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await wait_until(lambda: gateway._port_open("127.0.0.1", rtsp), "Synthetic upstream RTSP listener did not start")
        source = f"rtsp://127.0.0.1:{rtsp}/testcam"
        publisher = spawn([ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-re",
                           "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=25",
                           "-an", "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                           "-profile:v", "baseline", "-level:v", "4.0", "-pix_fmt", "yuv420p",
                           "-bf", "0", "-g", "25", "-keyint_min", "25", "-sc_threshold", "0",
                           "-threads", "2", "-f", "rtsp", "-rtsp_transport", "tcp", source],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        await wait_until(lambda: upstream_path().get("available"), "Synthetic H264 publisher failed")
        startup = await asyncio.to_thread(gateway.start, source, "Synthetic loopback 1080p25")
        require(startup["started"], f"Actual gateway failed startup: {startup['last_error']}")
        first = await open_peer("A")
        second = await open_peer("B")
        before = [first["frames"], second["frames"]]
        sample_start = time.monotonic()
        await asyncio.sleep(seconds)
        measured_seconds = time.monotonic() - sample_start
        for index, item in enumerate((first, second)):
            count = item["frames"] - before[index]
            require(count > 0 and item["dimensions"] == {(1920, 1080)}, f"Peer {item['name']} stalled or resized")
            report["peers"].append({"name": item["name"], "measured_seconds": round(measured_seconds, 3),
                                    "decoded_frames": count, "decoded_fps": round(count / measured_seconds, 2),
                                    "frame_dimensions": [1920, 1080]})
        active = await status()
        require(active["source_healthy"] is True and active["webrtc_connected_count"] == 2,
                "Gateway did not report two connected peers and a healthy source")
        readers = len(upstream_path().get("readers", []))
        require(readers == 1, "Two WHEP peers opened duplicate upstream RTSP readers")
        report["concurrent"] = {"upstream_readers": readers, "webrtc_sessions": active["webrtc_session_count"],
                                "app_sessions": active["app_session_count"], "source_codecs": active["source_codecs"]}

        # Probe the production recorder's private ffconcat/stdin relay input and
        # copy mode; no DB rows, recordings or customer runtime are touched.
        relay_source = gateway.relay_source(source)
        require(bool(relay_source), "Matching-source private recorder relay unavailable")
        relay_command = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-progress", "pipe:1",
                         "-protocol_whitelist", "pipe,rtsp,tcp,rtp", "-f", "concat", "-safe", "0", "-i", "pipe:0",
                         "-map", "0:v:0", "-an", "-c:v", "copy", "-frames:v", "50", "-f", "null", "-"]
        require(relay_source not in repr(relay_command) and gateway._internal_password not in repr(relay_command),
                "Relay credentials leaked into argv")
        relay_reader = spawn(relay_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        communicate = asyncio.create_task(asyncio.to_thread(relay_reader.communicate, input_manifest(relay_source, 6000), timeout=15))
        try:
            await asyncio.sleep(0.8)
            require(len(upstream_path().get("readers", [])) == 1, "Private relay opened another camera reader")
            progress, _ = await communicate
            require(relay_reader.returncode == 0 and b"frame=50" in progress, "Private relay copy/stdin probe failed")
            report["recorder_relay_probe"] = {"copied_frames": 50, "exit_code": relay_reader.returncode,
                                              "upstream_readers": 1, "credentials_in_argv": False}
        finally:
            if not communicate.done():
                reap(relay_reader)
                await asyncio.gather(communicate, return_exceptions=True)
            reap(relay_reader)
            relay_reader = None

        await close_peer(first)
        remaining_before = second["frames"]
        await asyncio.sleep(1)
        require(second["frames"] > remaining_before, "Closing one peer stopped the remaining peer")
        await close_peer(second)
        await wait_until(lambda: gateway._api_json("/v3/webrtc/sessions/list").get("itemCount") == 0,
                         "MediaMTX retained closed WHEP sessions")
        reconnected = await open_peer("reconnect")
        await asyncio.sleep(1)
        require(reconnected["frames"] >= 3, "Sequential WHEP reconnect failed")
        report["sequential_reconnect"] = {"decoded_frames": reconnected["frames"], "frame_dimensions": [1920, 1080]}
        await close_peer(reconnected)
        await wait_until(lambda: gateway._api_json("/v3/webrtc/sessions/list").get("itemCount") == 0,
                         "MediaMTX retained reconnected WHEP session")
        final = await status()
        require(final["app_session_count"] == 0 and final["pending_session_count"] == 0, "App session metadata leaked")
        report["cleanup"] = {"app_sessions": 0, "pending_sessions": 0, "webrtc_sessions": final["webrtc_session_count"]}
        report["ok"] = True
    finally:
        cleanup_errors = []
        for item in peers:
            try:
                await close_peer(item)
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
        owned_gateway_process = gateway._process
        await asyncio.to_thread(gateway.shutdown)
        for proc in (owned_gateway_process, relay_reader, publisher, upstream):
            try:
                reap(proc)
            except Exception as exc:
                cleanup_errors.append(type(exc).__name__)
        require(gateway._process is None, "Owned native gateway process was not released")
        require(not cleanup_errors, "Child cleanup failed: " + ",".join(cleanup_errors))
        report.setdefault("cleanup", {})["child_processes_reaped"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True, help="Pinned MediaMTX v1.21.1 executable")
    parser.add_argument("--seconds", type=float, default=10, help="Concurrent peer sample duration (3..300 seconds)")
    parser.add_argument("--report", type=Path, help="Optional JSON evidence file")
    args = parser.parse_args()
    require(args.binary.is_file(), "MediaMTX executable does not exist")
    require(3 <= args.seconds <= 300, "seconds must be between 3 and 300")
    report = {}
    try:
        with tempfile.TemporaryDirectory(prefix="native-smoke-", dir=ROOT / "tests_integration") as temp:
            report = asyncio.run(run(args.binary.resolve(), args.seconds, Path(temp)))
    except Exception as exc:
        report = {"ok": False, "scope": "SYNTHETIC_LOOPBACK_ONLY", "error_type": type(exc).__name__, "error": str(exc)}
    output = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

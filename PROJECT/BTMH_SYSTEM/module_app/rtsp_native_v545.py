"""RTSP-only native FFmpeg adapter. No credentials in argv, files or logs.

One FFmpeg process per source, owned directly by CaptureSession. A single-entry
ffconcat manifest travels over stdin. Decoded PPM frames travel over stdout.
No resizing, JPEG recompression, AI threshold or USB-driver changes are involved.
The existing imageio-ffmpeg wheel supplies the executable; no VLC/plugin needed.
"""
from __future__ import annotations
from pathlib import Path
import os

MAX_FRAME = 4096 * 2160 * 3


def resolve_ffmpeg() -> str | None:
    """Find a locally installed binary only; never download at camera-open time."""
    explicit = os.getenv("BTMH_RTSP_FFMPEG", "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        return str(p.resolve()) if p.is_file() else None
    try:
        import imageio_ffmpeg
        p = Path(imageio_ffmpeg.get_ffmpeg_exe())
        return str(p.resolve()) if p.is_file() else None
    except (ImportError, RuntimeError, OSError):
        return None


def input_manifest(source: str, timeout_ms: int) -> bytes:
    # Only caller-validated RTSP sources are accepted, not arbitrary playlists.
    if not source.lower().startswith("rtsp://") or any(ord(c) < 32 for c in source):
        raise ValueError("INVALID_SOURCE")
    if len(source) > 4096:
        raise ValueError("INVALID_SOURCE")
    # ffconcat quoting: escape a quote outside the quoted segment. Backslashes
    # inside a quoted string are literal. No shell executes this text.
    quoted = "'" + source.replace("'", "'\\''") + "'"
    timeout = max(500, min(int(timeout_ms), 15000)) * 1000
    return ("ffconcat version 1.0\nfile " + quoted +
            "\noption rtsp_transport tcp\noption timeout " + str(timeout) +
            "\noption allowed_media_types video\n").encode("utf-8")


def command(binary: str, output_fps: float = 0., max_width: int = 0) -> list[str]:
    # The camera URI is intentionally absent from this process command line.
    # No input -r/-re and passthrough timestamps: don't synthesize duplicate
    # frames just to pass readiness. Keep original resolution/pixel content.
    args = [binary, "-hide_banner", "-nostdin", "-loglevel", "warning",
            "-protocol_whitelist", "pipe,rtsp,tcp,rtp", "-f", "concat", "-safe", "0",
            "-threads", "2", "-i", "pipe:0", "-map", "0:v:0", "-an", "-sn", "-dn",
            "-fps_mode", "passthrough", "-threads", "1"]
    filters = []
    if output_fps:
        filters.append("fps=" + str(max(1., min(60., float(output_fps)))))
    if max_width:
        width = max(640, min(1920, int(max_width)))
        # Never upscale.  Reducing 1080p to 720p before the raw PPM pipe cuts
        # inter-process bandwidth by more than half on the balanced profile.
        filters.append("scale='min(iw," + str(width) + ")':-2")
    if filters:
        args += ["-vf", ",".join(filters)]
    return args + ["-c:v", "ppm", "-pix_fmt", "rgb24", "-f", "image2pipe", "pipe:1"]


def read_ppm(pipe, read_exact):
    """Read one bounded RGB24 PPM, preserving bytes incl. leading whitespace."""
    magic = pipe.readline(32)
    if not magic:
        raise EOFError
    if magic.strip() != b"P6":
        raise ValueError("DECODER_PROTOCOL")
    def line():
        for _ in range(8):
            raw = pipe.readline(128)
            if not raw or len(raw) >= 128:
                raise ValueError("DECODER_PROTOCOL")
            if not raw.startswith(b"#"):
                return raw
        raise ValueError("DECODER_PROTOCOL")
    parts = line().split()
    if len(parts) != 2:
        raise ValueError("DECODER_PROTOCOL")
    w, h = (int(x) for x in parts)
    if not 16 <= w <= 4096 or not 16 <= h <= 2160 or w * h * 3 > MAX_FRAME:
        raise ValueError("FRAME_TOO_LARGE")
    if line().strip() != b"255":
        raise ValueError("DECODER_PROTOCOL")
    return w, h, read_exact(pipe, w * h * 3)

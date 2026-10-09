from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module_app.camera_profiles import build_rtsp_url, normalize_camera_source, hikvision_secret_path
from module_app.secret_store import save_secret

try:
    import imageio_ffmpeg
except Exception:
    imageio_ffmpeg = None


def data_root() -> Path:
    configured = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.getenv("LOCALAPPDATA", "")) / "CampusFace"
    return ROOT / ".campusface-data"


def ask(label: str, default: str) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def test_tcp(ip: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((ip, port), timeout=3.0):
            return True, "TCP OK"
    except Exception as exc:
        return False, str(exc)


def test_frame(url: str) -> tuple[bool, str]:
    """Bounded RTSP decode test so camera setup can never hang forever."""
    if imageio_ffmpeg is None:
        return False, "FFmpeg runtime chưa sẵn sàng; bỏ qua test decode"
    try:
        exe = str(imageio_ffmpeg.get_ffmpeg_exe() or "")
        if not exe:
            return False, "Không tìm thấy FFmpeg runtime"
        cmd = [
            exe, "-hide_banner", "-loglevel", "error",
            "-rtsp_transport", "tcp", "-rw_timeout", "5000000",
            "-i", url, "-frames:v", "1", "-f", "null", "-",
        ]
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=9.0, text=True)
        if result.returncode == 0:
            return True, "RTSP decode OK"
        detail = (result.stderr or "").strip().splitlines()
        return False, (detail[-1] if detail else f"FFmpeg exit {result.returncode}")[:180]
    except subprocess.TimeoutExpired:
        return False, "RTSP decode timeout sau 9 giây"
    except Exception as exc:
        return False, str(exc)[:180]


def main() -> int:
    parser = argparse.ArgumentParser(description="BTMH local Hikvision configuration")
    parser.add_argument("--ip", default="192.168.1.200")
    parser.add_argument("--port", type=int, default=554)
    parser.add_argument("--stream", default="/Streaming/Channels/101")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--model", default="DS-2CD1123G0-IUF")
    parser.add_argument("--name", default="Hikvision DS-2CD1123G0-IUF - Cửa chính")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    if args.non_interactive:
        password = os.getenv("CAMPUSFACE_HIKVISION_PASSWORD", "")
        if not password:
            print("[ERROR] CAMPUSFACE_HIKVISION_PASSWORD is empty")
            return 2
        ip, port, stream, username, model, name = args.ip, args.port, args.stream, args.username, args.model, args.name
    else:
        print("============================================================")
        print("BTMH SECURITY - CẤU HÌNH HIKVISION CAM01")
        print("Mật khẩu chỉ lưu bằng Windows DPAPI trên máy hiện tại.")
        print("============================================================")
        ip = ask("IP camera", args.ip)
        port = int(ask("RTSP port", str(args.port)))
        stream = ask("RTSP stream", args.stream)
        username = ask("User", args.username)
        model = ask("Model", args.model)
        name = ask("Tên hiển thị", args.name)
        password = getpass.getpass("Mật khẩu camera (không hiển thị): ")
        if not password:
            print("[ERROR] Mật khẩu không được để trống.")
            return 2

    url = normalize_camera_source(build_rtsp_url(ip, username, password, port=port, stream=stream))
    tcp_ok, tcp_msg = test_tcp(ip, port)
    print(f"[{'OK' if tcp_ok else 'WARN'}] RTSP TCP {ip}:{port}: {tcp_msg}")

    secret_path = hikvision_secret_path()
    save_secret(secret_path, password, machine_scope=False)
    profile_path = data_root() / "config" / "hikvision_camera.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "name": name,
        "type": "RTSP",
        "model": model,
        "ip": ip,
        "rtsp_port": port,
        "stream": stream,
        "username": username,
        "password_storage": "Windows DPAPI",
        "purpose": "SURVEILLANCE_PRIMARY",
    }
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] Profile: {profile_path}")
    print(f"[OK] Secret:  {secret_path}")

    frame_ok, frame_msg = test_frame(url)
    print(f"[{'OK' if frame_ok else 'WARN'}] Camera frame: {frame_msg}")
    print("[INFO] Nếu VLC đã lên hình nhưng test frame WARN, hãy đặt Video Encoding của Hikvision về H.264 rồi thử lại.")
    print("[DONE] Khởi động lại BTMH Security để CAM01 tự xuất hiện trong Live View.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

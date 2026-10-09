from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module_app.config import CONFIG_DIR
from module_app.edge_identity_v5 import (
    EDGE_PRIVATE_KEY_PATH,
    EdgeIdentityError,
    generate_device_keypair,
    load_edge_private_key,
    public_from_private,
    save_edge_private_key,
    validate_central_url,
)


def ask(label: str, default: str) -> str:
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def update_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines() if path.exists() else []
    wanted = set(values)
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            key = raw.split("=", 1)[0].strip()
            if key in wanted:
                if key not in seen:
                    out.append(f"{key}={values[key]}")
                    seen.add(key)
                continue
        out.append(line)
    if out and out[-1].strip():
        out.append("")
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="BTMH Edge -> Central signed sync configuration")
    parser.add_argument("--central-url", default="")
    parser.add_argument("--node-id", default="")
    parser.add_argument("--node-name", default="")
    parser.add_argument("--store-id", type=int, default=0)
    parser.add_argument("--rotate-key", action="store_true")
    parser.add_argument("--allow-http-dev", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    args = parser.parse_args()

    hostname = socket.gethostname() or "BTMH-EDGE"
    if args.non_interactive:
        central = args.central_url
        node_id = args.node_id
        node_name = args.node_name or hostname
        store_id = args.store_id
    else:
        print("============================================================")
        print("BTMH SECURITY - CẤU HÌNH EDGE -> CENTRAL")
        print("Private key chỉ được giữ trên Edge PC và bảo vệ bằng Windows DPAPI.")
        print("Central Server chỉ nhận public key để xác minh chữ ký.")
        print("============================================================")
        central = ask("Central URL (HTTPS)", args.central_url or "https://central.example.local")
        node_id = ask("Edge Node ID", args.node_id or f"EDGE-{hostname}")
        node_name = ask("Tên Edge PC", args.node_name or hostname)
        store_id = int(ask("Store ID", str(args.store_id or 1)))

    if not node_id.strip() or store_id <= 0:
        print("[ERROR] Node ID và Store ID hợp lệ là bắt buộc.")
        return 2
    try:
        central = validate_central_url(central, allow_http_dev=args.allow_http_dev)
    except EdgeIdentityError as exc:
        print(f"[ERROR] {exc}")
        return 2

    identity: dict[str, str]
    if EDGE_PRIVATE_KEY_PATH.exists() and not args.rotate_key:
        try:
            identity = public_from_private(load_edge_private_key())
            print("[INFO] Giữ nguyên identity hiện tại. Dùng --rotate-key nếu thực sự cần đổi khóa.")
        except Exception as exc:
            print(f"[ERROR] Không đọc được Edge identity hiện tại: {exc}")
            return 3
    else:
        identity = generate_device_keypair()
        try:
            save_edge_private_key(identity["private_key_b64"])
        except EdgeIdentityError as exc:
            print(f"[ERROR] {exc}")
            return 3
        print("[OK] Đã tạo Ed25519 device identity mới và lưu private key bằng DPAPI.")

    env_path = CONFIG_DIR / "module.env"
    update_env(
        env_path,
        {
            "BTMH_EDGE_SYNC_ENABLED": "1",
            "BTMH_CENTRAL_URL": central,
            "BTMH_EDGE_NODE_ID": node_id.strip(),
            "BTMH_EDGE_NODE_NAME": node_name.strip() or hostname,
            "BTMH_EDGE_STORE_ID": str(store_id),
            "BTMH_EDGE_SYNC_ALLOW_HTTP_DEV": "1" if args.allow_http_dev else "0",
        },
    )
    pairing = {
        "node_id": node_id.strip(),
        "node_name": node_name.strip() or hostname,
        "store_id": store_id,
        "public_key_b64": identity["public_key_b64"],
        "key_fingerprint": identity["fingerprint"],
        "central_url": central,
        "private_key_exported": False,
    }
    pairing_path = CONFIG_DIR / "edge_pairing_public.json"
    pairing_path.write_text(json.dumps(pairing, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] Config:  {env_path}")
    print(f"[OK] Pairing: {pairing_path}")
    print(f"[OK] Fingerprint: {identity['fingerprint']}")
    print("[NEXT] Trên Central Server, đăng ký node bằng nội dung public trong edge_pairing_public.json.")
    print("[NEXT] Sau khi Central duyệt public key, restart BTMH Security trên Edge PC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

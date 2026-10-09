from __future__ import annotations

import importlib


def main() -> int:
    missing = []
    versions = []
    for name in ("aiortc", "av"):
        try:
            mod = importlib.import_module(name)
            versions.append(f"{name}={getattr(mod, '__version__', 'ok')}")
        except Exception as exc:
            missing.append(f"{name}: {exc}")
    if missing:
        print("[FALLBACK] WebRTC optional runtime missing: " + " | ".join(missing))
        print("[FALLBACK] CampusFace will use WebSocket ACK preview + Canvas metadata overlay.")
        return 2
    print("[OK] CampusFace V2.8 WebRTC media runtime ready: " + ", ".join(versions))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

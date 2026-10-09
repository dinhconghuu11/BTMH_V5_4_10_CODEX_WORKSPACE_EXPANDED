"""Run the actual BTMH UI/API offline in its own localhost-only profile."""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="BTMH offline UI Preview (isolated SQLite)")
    parser.add_argument("--port", type=int, default=8810)
    args = parser.parse_args()
    from module_app.ui_preview import prepare_environment
    try:
        root = prepare_environment(port=args.port)
        import uvicorn
        from module_app.main import app
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"[BLOCKED] UI Preview cannot start: {type(exc).__name__}: {exc}")
        print("Use an existing BTMH Python runtime. No dependency download is attempted.")
        return 2
    print("[MODE] UI PREVIEW - isolated data; camera/AI/recording unavailable", flush=True)
    print(f"[DATA] {root}", flush=True)
    print(f"[URL] http://127.0.0.1:{args.port}/ (Chrome / Edge)", flush=True)
    print("Create the first preview Owner in the existing local setup form. Ctrl+C stops preview.", flush=True)
    # A single process, no reload/workers, no proxy trust or external bind.
    uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False, workers=1,
                reload=False, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())

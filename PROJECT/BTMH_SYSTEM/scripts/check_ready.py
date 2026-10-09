from __future__ import annotations

import json
import os
import platform
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
VENDOR_PY = ROOT / "vendor_py"
if VENDOR_PY.exists():
    sys.path.insert(0, str(VENDOR_PY))


_EXTERNAL_URL_RE = re.compile(r"^(?:https?:)?//", re.IGNORECASE)


class _ExternalResourceParser(HTMLParser):
    """Find resources that the browser would actually load from the Internet.

    Plain text, form input values and placeholders may legitimately contain URL
    examples (for example an SMS webhook configured by SUPER_ADMIN). They are
    configuration data, not frontend runtime dependencies, and must not block
    startup.
    """

    _RESOURCE_ATTRS = {
        "script": {"src"},
        "link": {"href"},
        "img": {"src", "srcset"},
        "source": {"src", "srcset"},
        "video": {"src", "poster"},
        "audio": {"src"},
        "iframe": {"src"},
        "object": {"data"},
        "embed": {"src"},
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.external: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        wanted = self._RESOURCE_ATTRS.get(tag.lower())
        if not wanted:
            return
        for name, value in attrs:
            if name.lower() not in wanted or not value:
                continue
            candidates = [value]
            if name.lower() == "srcset":
                candidates = [part.strip().split()[0] for part in value.split(",") if part.strip()]
            for candidate in candidates:
                if _EXTERNAL_URL_RE.match(candidate.strip()):
                    self.external.append(f"<{tag} {name}={candidate!r}>")


def find_external_frontend_dependencies(frontend_root: Path) -> list[str]:
    """Return only hard-coded external dependencies used at browser runtime."""
    findings: list[str] = []

    index_path = frontend_root / "index.html"
    if index_path.exists():
        parser = _ExternalResourceParser()
        parser.feed(index_path.read_text(encoding="utf-8", errors="ignore"))
        findings.extend(parser.external)

    # CSS that imports/loads a remote asset is also a real runtime dependency.
    css_patterns = (
        re.compile(r"@import\s+(?:url\()?\s*['\"]?((?:https?:)?//[^'\")\s;]+)", re.I),
        re.compile(r"url\(\s*['\"]?((?:https?:)?//[^'\")\s]+)", re.I),
    )
    for css_path in frontend_root.rglob("*.css"):
        text = css_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in css_patterns:
            for match in pattern.finditer(text):
                findings.append(f"{css_path.relative_to(frontend_root)} -> {match.group(1)}")

    # Detect hard-coded network calls in JavaScript. A regex literal such as
    # /^https?:\/\// is intentionally NOT considered a dependency.
    js_patterns = (
        re.compile(r"\bfetch\s*\(\s*['\"]((?:https?:)?//[^'\"]+)", re.I),
        re.compile(r"\bWebSocket\s*\(\s*['\"]((?:wss?:)?//[^'\"]+)", re.I),
        re.compile(r"\bEventSource\s*\(\s*['\"]((?:https?:)?//[^'\"]+)", re.I),
        re.compile(r"\bimport\s*\(\s*['\"]((?:https?:)?//[^'\"]+)", re.I),
    )
    for js_path in frontend_root.rglob("*.js"):
        text = js_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in js_patterns:
            for match in pattern.finditer(text):
                findings.append(f"{js_path.relative_to(frontend_root)} -> {match.group(1)}")

    return sorted(set(findings))


def main() -> int:
    print("=== BTMH Security V5 - READY CHECK ===")
    print("Scope: FaceID + anti-spoof + camera/recording + PostgreSQL + local web frontend")
    print("Runtime: local-first after installation; external OTP providers are configurable integrations")
    print("Python:", sys.version.split()[0], platform.architecture()[0])
    errors: list[str] = []
    production = os.getenv("BTMH_ENV", "production").strip().lower() != "development"
    if os.getenv("BTMH_UI_PREVIEW", "0") == "1":
        print("[ERROR] UI_PREVIEW is not a production runtime. Use its separate preview launcher.")
        return 2
    database_allowed = False

    for name in ("fastapi", "uvicorn", "cv2", "numpy", "cryptography", "mediapipe", "psycopg"):
        try:
            mod = __import__(name)
            print(f"[OK] {name}", getattr(mod, "__version__", ""))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            print(f"[ERROR] {name}: {exc}")

    try:
        from module_app.config import (
            APP_VERSION,
            CAMERA_BACKEND,
            CAMERA_SOURCE,
            CAMERA_MODE,
            DATA_ROOT,
            PROFILE,
            SFACE_MODEL,
            DB_MODE,
            POSTGRES_HOST,
            POSTGRES_PORT,
            POSTGRES_DB,
            YUNET_MODEL,
            PAD_MODEL_V2,
        )
        print("[INFO] version:", APP_VERSION)
        # A configured source can contain RTSP credentials; never echo it.
        print("[INFO] profile:", PROFILE, "camera configured:", bool(str(CAMERA_SOURCE).strip()), "backend:", CAMERA_BACKEND)
        print("[INFO] persistent data root:", DATA_ROOT)
        for path, min_size in (
            (YUNET_MODEL, 100_000),
            (SFACE_MODEL, 1_000_000),
        ):
            if path.exists() and path.stat().st_size > min_size:
                print(f"[OK] model {path.name} ({path.stat().st_size/1024/1024:.1f} MB)")
            else:
                errors.append(f"missing model: {path}")
                print(f"[ERROR] missing model: {path}")
        print("[INFO] database mode:", DB_MODE)
        database_allowed = not production or DB_MODE == "postgres"
        if not database_allowed:
            errors.append("production requires PostgreSQL")
            print("[ERROR] Production requires PostgreSQL; SQLite is reserved for explicit development/tests.")
        if production and CAMERA_MODE != "service":
            errors.append("production requires background camera service mode")
            print("[ERROR] Production requires background camera service mode; restore MODULE_CAMERA_MODE=service.")
        if DB_MODE == "postgres":
            print(f"[INFO] PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    except Exception as exc:
        errors.append(f"config: {exc}")
        print("[ERROR] config:", exc)

    try:
        if not database_allowed:
            raise RuntimeError("database initialization withheld until production configuration is valid")
        from module_app.db import db_status, init_db
        init_db()
        print("[OK] database", json.dumps(db_status(), ensure_ascii=False))
    except Exception as exc:
        errors.append(f"database: {exc}")
        print("[ERROR] database:", exc)

    try:
        from module_app.face_core import CORE
        CORE.ensure()
        print("[OK] YuNet + SFace loaded locally")
    except Exception as exc:
        errors.append(f"face core: {exc}")
        print("[ERROR] face core:", exc)

    # Production requires the supported Passive PAD model and a real load/probe.
    # Development retains the existing visible context fallback for diagnostics.
    try:
        from module_app.passive_pad import PAD
        pad_status = PAD.status()
        print("[INFO] Passive PAD", json.dumps(pad_status, ensure_ascii=False))
        if pad_status.get("ready"):
            print("[OK] Passive PAD enhancement ready")
        else:
            if production:
                errors.append("Passive PAD is disabled, missing or failed its verified model probe")
                print("[ERROR] Passive PAD is not ready. Restore the verified model/runtime and enable PAD before production startup.")
            else:
                print("[WARN] Passive PAD enhancement unavailable; multi-frame phone/photo context fallback is active")
    except Exception as exc:
        if production:
            errors.append("Passive PAD runtime check failed")
            print("[ERROR] Passive PAD runtime check failed:", exc)
        else:
            print("[WARN] Passive PAD enhancement unavailable:", exc)

    try:
        from module_app.rtsp_native_v545 import resolve_ffmpeg
        if not resolve_ffmpeg():
            raise RuntimeError("local FFmpeg binary missing; repair the bundled imageio-ffmpeg runtime")
        print("[OK] Local FFmpeg available for RTSP capture and recording")
    except Exception as exc:
        errors.append("local FFmpeg runtime unavailable")
        print("[ERROR] FFmpeg runtime:", exc)

    # V5.2 identity-only runtime: verify the shared camera exposes the observation
    # lane used by live identity monitoring. There is deliberately no pose/action worker.
    try:
        from module_app.camera import CAMERA
        if not callable(getattr(CAMERA, "latest_observation_jpeg", None)):
            raise RuntimeError("identity observation preview is unavailable")
        if not callable(getattr(CAMERA, "latest_result", None)):
            raise RuntimeError("identity result pipeline is unavailable")
        print("[OK] Identity-only camera observer contract ready")
    except Exception as exc:
        errors.append(f"identity observer: {exc}")
        print("[ERROR] identity observer:", exc)

    try:
        import websockets
        print("[OK] local WebSocket transport", getattr(websockets, "__version__", "bundled"))
    except Exception as exc:
        print("[WARN] WebSocket transport unavailable; HTTP newest-frame fallback remains active:", exc)

    try:
        from module_app.mediamtx_runtime import VERSION as GATEWAY_VERSION, require_mediamtx
        if sys.platform == "win32":
            gateway_runtime = require_mediamtx(DATA_ROOT)
            if gateway_runtime.binary is not None:
                print(f"[OK] MediaMTX {GATEWAY_VERSION} verified native video gateway")
            else:
                print(f"[WARN] Development Native Gateway: UNAVAILABLE; Reason: {gateway_runtime.reason}")
                print("[INFO] Backend/frontend remain available; Live View explicitly negotiates its existing fallback chain.")
        else:
            print(f"[INFO] MediaMTX Windows gateway packaging check skipped on {sys.platform}")
    except Exception as exc:
        if sys.platform == "win32":
            errors.append(f"MediaMTX gateway: {exc}")
            print("[ERROR] MediaMTX gateway:", exc)
        else:
            print("[INFO] MediaMTX gateway runtime check skipped:", exc)

    try:
        bad = find_external_frontend_dependencies(ROOT / "frontend")
        if bad:
            errors.append("frontend external runtime dependency")
            print("[ERROR] frontend loads hard-coded external runtime resources:")
            for item in bad:
                print("       -", item)
        else:
            print("[OK] frontend runtime assets/API are local; configurable URL fields are allowed")
    except Exception as exc:
        errors.append(f"frontend check: {exc}")
        print("[ERROR] frontend check:", exc)

    if errors:
        print("\n[STOP] CampusFace is not fully ready:")
        for item in errors:
            print(" -", item)
        print("[ACTION] Re-run INSTALL_CAMPUSFACE.bat after fixing the item above. START is intentionally blocked.")
        return 2

    print("\n[OK] Runtime preflight passed. Backend startup and socket binding still follow.")
    print("[INFO] Actual camera connectivity, WebRTC, AI and recording must be verified in runtime status.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

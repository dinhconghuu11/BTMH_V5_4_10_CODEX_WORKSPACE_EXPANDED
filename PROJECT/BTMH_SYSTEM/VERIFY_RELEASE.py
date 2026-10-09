from __future__ import annotations
import py_compile
import tempfile
import os
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Never run release verification against a customer database or source-tree data.
_isolated = tempfile.TemporaryDirectory(prefix="btmh-release-verify-")
os.environ["CAMPUSFACE_DATA_ROOT"] = _isolated.name
os.environ["CAMPUSFACE_DB_MODE"] = "sqlite"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
# Legacy policy probes round-trip Vietnamese JSON through Python subprocesses.
# Both writers and readers must use UTF-8 on Windows regardless of the ACP.
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.dont_write_bytecode = True
failures = []
passes = []
suite_results = []

def check(name, condition, detail=""):
    (passes if condition else failures).append((name, detail))

text_files = []
excluded_parts = {
    "tests", "tests_v5", "tests_v54", "tests_integration", "docs", "logs", "backups",
    "__pycache__", ".pytest_cache",
}
for p in ROOT.rglob("*"):
    if not p.is_file() or p.suffix.lower() not in {".py", ".js", ".html", ".css", ".json", ".txt", ".bat", ".cmd", ".ps1", ".ini", ".toml", ".yaml", ".yml"}:
        continue
    if any(part in excluded_parts for part in p.parts):
        continue
    if p.name.startswith("VERIFY_RELEASE"):
        continue
    try:
        text_files.append((p, p.read_text(encoding="utf-8", errors="ignore")))
    except Exception:
        pass
joined = "\n".join(t for _, t in text_files)

check("No fixed owner username", ("cong" + "huu24") not in joined)
check("No obvious fixed owner password", not re.search(r'(?i)(release_owner_password|default_admin_password)\s*=\s*["\'][^"\']{6,}', joined))
check("No packaged owner hash", not re.search(r'_RELEASE_OWNER_PASSWORD_HASH\s*=\s*[\"\']\$argon2', joined))
check("V5.4.10 version", (ROOT / "VERSION.txt").exists() and "5.4.10" in (ROOT / "VERSION.txt").read_text(encoding="utf-8"))
check("Auth CSS", any(p.name == "btmh_auth_v54.css" for p, _ in text_files))
check("Auth JS", any(p.name == "btmh_auth_v54.js" for p, _ in text_files))
check("Customer CSS", (ROOT / "frontend" / "css" / "btmh_customer_v541.css").exists())
check("Customer CSS bundle", (ROOT / "frontend" / "css" / "btmh_customer_bundle_v541.css").exists())
check("Customer JS", (ROOT / "frontend" / "js" / "btmh_customer_v541.js").exists())
html_text = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8", errors="ignore")
check("Official BTMH logo", "/static/img/btmh_official_logo.png" in html_text)
check("No public registration UI", 'id="gateRegisterView"' not in html_text and 'id="openRegisterBtn"' not in html_text)
check("No inactive OTP delivery UI", all(x not in html_text for x in ["Gửi OTP SMS", "Gửi OTP Email", "OTP DELIVERY", 'id="otpProviderPanel"']))
check("No visible build label", all(x not in html_text for x in ["BTMH Security V5.4", "Identity · Camera · Evidence", "OPERATIONS PROFESSIONAL", "SUPER_ADMIN -", "OTP DELIVERY"]))
check("Customer stylesheet bundle", "btmh_customer_bundle_v541.css" in html_text and "btmh_media_v5410.css" in html_text)
check("Local first-run owner", '/api/v1/auth/bootstrap-local' in joined and '127.0.0.1' in joined)
check("SMS and optional legacy MFA", '/api/v1/auth/sms/verify' in joined and '_new_mfa_challenge(row, setup=False)' in joined)
customer_env = (ROOT / ".env.customer.example").read_text(encoding="utf-8", errors="ignore") if (ROOT / ".env.customer.example").exists() else ""
check("Public registration off", "BTMH_PUBLIC_REGISTRATION=0" in customer_env)
check("Security middleware", "install_v54_hardening(app)" in joined)
check("MCP default disabled", "MCP_ENABLED=false" in customer_env and "MCP_MODE=read_only" in customer_env)
check("Legacy SMS/Email OTP disabled", "BTMH_LEGACY_OTP_ENABLED=0" in customer_env and "LEGACY_OTP_API_PATHS" in joined)
check("Local host default", 'MODULE_HOST=127.0.0.1' in joined)
check("CSV Request fix", "rows = students(request)" in joined)

nav_js=(ROOT/"frontend/js/btmh_customer_v541.js").read_text(encoding="utf-8")
check("No self-observing navigation mutation loop", "new MutationObserver" not in nav_js)
check("Bounded preview runtime shipped", (ROOT/"frontend/js/btmh_runtime_v543.js").is_file())
check("Gold login artwork shipped", (ROOT/"frontend/img/gold-jewelry-v543.svg").is_file())
check("Camera source catalog shipped", (ROOT/"module_app/camera_catalog_v543.py").is_file())

for rel in ["module_app/capture_worker_v544.py","module_app/capture_session_v544.py","module_app/camera_handover_v544.py","module_app/camera_connection_v544.py","frontend/js/camera_tools_v544.js"]:
    check("Camera component " + rel, (ROOT/rel).is_file())
check("Example camera not activated", json.loads((ROOT/"config/hikvision_test_camera.json").read_text(encoding="utf-8")).get("example_only") is True)

check("Native RTSP adapter shipped", (ROOT/"module_app/rtsp_native_v545.py").is_file())
check("Read-only RTSP diagnostic shipped", (ROOT/"scripts/diagnose_rtsp_v545.py").is_file())
check("Native executable dependency retained", "imageio-ffmpeg==0.6.0" in (ROOT/"requirements-runtime.txt").read_text(encoding="utf-8"))
check("RTSP URI not passed in decoder argv", "input_manifest(self.source" in (ROOT/"module_app/capture_session_v544.py").read_text(encoding="utf-8"))
check("Existing USB worker retained", "capture_worker_v544.py" in (ROOT/"module_app/capture_session_v544.py").read_text(encoding="utf-8"))
check("Camera registry persistence guard shipped", (ROOT/"module_app/camera_registry_v546.py").is_file())

check("Realtime RTSP profile shipped", "BTMH_RTSP_REALTIME_PROFILE" in joined and "RTSP_CAPTURE_MAX_WIDTH" in joined)
check("Latest-frame zero backlog retained", "LATEST_FRAME_DROP_STALE" in joined and '"queue_depth": 0' in joined)
check("Native media gateway browser transport shipped", (ROOT/"frontend/js/btmh_media_v5410.js").is_file() and "NATIVE_GATEWAY_WEBRTC" in (ROOT/"frontend/js/btmh_media_v5410.js").read_text(encoding="utf-8"))
check("Native transport is primary", "const order = ['native', 'webrtc', 'ws', 'mjpeg', 'poll']" in (ROOT/"frontend/js/btmh_media_v5410.js").read_text(encoding="utf-8"))
check("WebRTC fallback retained", "RTCPeerConnection" in (ROOT/"frontend/js/btmh_media_v5410.js").read_text(encoding="utf-8") and "MEDIA_WEBRTC_WIDTH" in joined)
check("MediaMTX gateway manager shipped", (ROOT/"module_app/media_gateway_v5410.py").is_file() and "MTX_PATHS_BTMHMAIN_SOURCE" in (ROOT/"module_app/media_gateway_v5410.py").read_text(encoding="utf-8"))
check("MediaMTX installer pinned", (ROOT/"scripts/ensure_mediamtx_v5410.ps1").is_file() and "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23" in (ROOT/"scripts/ensure_mediamtx_v5410.ps1").read_text(encoding="utf-8"))
check("Camera secret not written to gateway config", "source: publisher" in (ROOT/"module_app/media_gateway_v5410.py").read_text(encoding="utf-8") and "MTX_PATHS_BTMHMAIN_SOURCE" in (ROOT/"module_app/media_gateway_v5410.py").read_text(encoding="utf-8"))
check("Recognition uses BTMHMedia", "BTMHMedia.mount('recognition'" in (ROOT/"frontend/js/app.js").read_text(encoding="utf-8"))
check("Legacy camera registry repair shipped", (ROOT/"module_app/camera_registry_v547.py").is_file())
check("Legacy repair runs before camera startup", "legacy_hikvision_repair_plan(_camera_row)" in main_text if 'main_text' in globals() else "legacy_hikvision_repair_plan(_camera_row)" in (ROOT/"module_app/main.py").read_text(encoding="utf-8", errors="ignore"))
main_text=(ROOT/"module_app/main.py").read_text(encoding="utf-8", errors="ignore")
rec_text=(ROOT/"module_app/recording_runtime_v4.py").read_text(encoding="utf-8", errors="ignore")
tool_text=(ROOT/"frontend/js/camera_tools_v544.js").read_text(encoding="utf-8", errors="ignore")
check("Camera connection read-back verified", "persisted_connection_matches(source, updated)" in main_text)
check("Stale fleet reader invalidated after edit", "FLEET_V4.stop(int(device_id),wait=False)" in main_text)
check("Stale recorder invalidated after edit", "RECORDER_V4.invalidate_camera(int(device_id))" in main_text and "def invalidate_camera" in rec_text)
check("Connection editor verifies saved endpoint", "sameHost" in tool_text and "samePort" in tool_text and "samePath" in tool_text)
check("Connection editor preflights saved endpoint", "'/api/v1/camera/test-source'" in tool_text and "L\\u01b0u & ki\\u1ec3m tra" in tool_text)

# Sensitive routes must be covered by the centralized fail-closed permission map.
try:
    from module_app.main import app, _api_permission_for, PUBLIC_API_PATHS, MOBILE_PUBLIC_API_PATHS
    sensitive_paths = [
        ("GET", "/api/v1/camera/status"),
        ("GET", "/api/v1/camera/stream.mjpg"),
        ("GET", "/api/v1/system/diagnostics"),
        ("POST", "/api/v1/system/self-test"),
        ("GET", "/api/v1/history/recognition"),
        ("GET", "/api/v1/events/{event_id}/evidence.jpg"),
    ]
    for method, path in sensitive_paths:
        check(f"RBAC {path}", _api_permission_for(path, method) is not None)
    check("RBAC camera preflight", _api_permission_for("/api/v1/camera/test-source", "POST") == "camera.switch")
    check("RBAC connection editor", _api_permission_for("/api/v1/cameras/devices/{device_id}/connection", "PUT") == "camera.configure")
    unmapped = []
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", None) or {"GET"}) - {"OPTIONS"}
        if not path.startswith("/api/v1/"):
            continue
        if path in PUBLIC_API_PATHS or path in MOBILE_PUBLIC_API_PATHS or path.startswith("/api/v1/mobile/"):
            continue
        for method in methods:
            if _api_permission_for(path, method) is None:
                unmapped.append(f"{method} {path}")
    check("All private browser APIs mapped", not unmapped, ", ".join(unmapped[:5]))
except Exception as exc:
    check("RBAC permission map import", False, str(exc))

compile_errors=[]
for index, source in enumerate(ROOT.rglob("*.py")):
    if any(part in {"vendor_py", ".venv", "__pycache__"} for part in source.parts):
        continue
    try:
        py_compile.compile(str(source), cfile=str(Path(_isolated.name)/f"check-{index}.pyc"), doraise=True)
    except py_compile.PyCompileError as exc:
        compile_errors.append(str(exc))
check("Python compile", not compile_errors, str(compile_errors[:3]))

# Validate all shipped frontend JS, including the new diagnostics and mobile UI.
for target in sorted((ROOT / "frontend").rglob("*.js")):
    rel = target.relative_to(ROOT).as_posix()
    try:
        proc = subprocess.run(["node", "--check", str(target)], cwd=ROOT, capture_output=True, text=True)
        check(f"JavaScript syntax {rel}", proc.returncode == 0, proc.stderr.strip())
    except FileNotFoundError:
        check(f"JavaScript syntax {rel}", False, "Node.js not found")

# Full current contracts plus applicable legacy identity/enrollment policy checks.
# Historical V5 packaging/navigation/legacy-OTP contracts target older releases;
# these are not a substitute for the current V5.4 security/RBAC suite.
test_suites = [
    ("V5.4 pytest", [ROOT / "tests_v54"]),
    ("Legacy identity/enrollment pytest", [
        ROOT / "tests_v5/test_v536_enrollment_recognition_v2.py",
        ROOT / "tests_v5/test_v5_identity_only_contract.py",
    ]),
]
for index, (name, targets) in enumerate(test_suites):
    junit = Path(_isolated.name) / f"pytest-{index}.xml"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-o", "addopts=", f"--junitxml={junit}", *map(str, targets)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    (Path(_isolated.name) / f"VERIFY_RELEASE_PYTEST_{index}.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    parsed = False
    if junit.exists():
        try:
            tree = ET.parse(junit)
            for suite in tree.getroot().iter("testsuite"):
                for key in counts:
                    counts[key] += int(suite.get(key, "0"))
            parsed = True
        except (ET.ParseError, ValueError):
            pass
    suite_results.append({"name": name, "exit_code": proc.returncode, "counts": counts, "counts_verified": parsed})
    check(name, proc.returncode == 0 and parsed and counts["tests"] > 0,
          f"exit={proc.returncode}, tests={counts['tests']}, failures={counts['failures']}, errors={counts['errors']}, skipped={counts['skipped']}")
    if proc.returncode:
        # Show test identifiers, not captured inputs, credentials or traceback bodies.
        for line in proc.stdout.splitlines():
            if line.startswith(("FAILED ", "ERROR ")):
                print(line.split(" - ", 1)[0])

browser_tests = sorted((ROOT / "tests_browser").glob("*.test.cjs"))
try:
    proc = subprocess.run(["node", "--test", "--test-reporter=tap", *map(str, browser_tests)],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    counts = {}
    for key in ("tests", "pass", "fail", "cancelled", "skipped"):
        match = re.search(rf"^# {key} (\d+)\s*$", proc.stdout, flags=re.M)
        counts[key] = int(match.group(1)) if match else None
    suite_results.append({"name": "Browser lifecycle", "exit_code": proc.returncode, "counts": counts,
                          "counts_verified": counts["tests"] is not None})
    check("Browser lifecycle", proc.returncode == 0 and bool(counts["tests"]),
          f"exit={proc.returncode}, tests={counts['tests']}, passed={counts['pass']}, failed={counts['fail']}")
except FileNotFoundError:
    check("Browser lifecycle", False, "Node.js not found")

external_acceptance = {
    name: "BLOCKED" for name in (
        "real_hikvision_main_small", "real_mediamtx_webrtc", "rendered_fps_lan_latency",
        "five_minute_hardware_soak", "real_faceid_pad_models_gpu", "real_postgresql",
        "rendered_ui_desktop_mobile_focus", "windows_offline_installation", "live_sms_delivery",
    )
}
# Keep reproducible outcomes and numeric counts; raw test logs remain isolated.
report = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "status": "PASS" if not failures else "FAIL",
    "release_stage": "development_rc_external_acceptance_blocked",
    "isolated_sqlite": True,
    "checks_passed": len(passes), "checks_failed": len(failures),
    "checks": [{"name": name, "status": status} for status, entries in (("PASS", passes), ("FAIL", failures)) for name, _ in entries],
    "suites": suite_results, "external_acceptance": external_acceptance,
    "final_easy_install_created": False,
}
(ROOT / "docs/VERIFY_RELEASE_RESULTS_V550.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print("=" * 72)
print("BTMH SECURITY V5.4.10 CUSTOMER RELEASE CHECK")
print("=" * 72)
for name, detail in passes:
    print(f"PASS  {name}" + (f" - {detail}" if detail else ""))
for name, detail in failures:
    print(f"FAIL  {name}" + (f" - {detail}" if detail else ""))
print("-" * 72)
print(f"PASS={len(passes)} FAIL={len(failures)}")
if failures:
    sys.exit(1)
print("AUTOMATED CHECKS PASSED - RC; WINDOWS/CAMERA/LIVE SMS ACCEPTANCE STILL REQUIRED")

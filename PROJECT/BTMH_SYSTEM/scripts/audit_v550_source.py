"""Read-only V550 source checks; write only docs/SOURCE_AUDIT_V550.json.

Uses the standard library without importing the application, extracting the
checkpoint, probing devices, or opening runtime/test data directories.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "backups/CODEX_WEBRTC_PRE_V550_20261006.zip"
OUTPUT = ROOT / "docs/SOURCE_AUDIT_V550.json"
EXPECTED_SHA256 = "8894f11fcaba3caa9bda541d6b0f19b325dc282685c04f84d743b991f9b61fac"
PROTECTED_MODULES = (
    "auth", "db", "security_hardening_v54", "secret_store", "crypto",
    "anti_spoof", "device_context", "edge_identity_v5", "gpu_manager",
    "registry", "otp_service", "sms_auth_v542", "sms_provider_v542", "sms_routes_v542",
)
PROTECTED_POLICY = (
    "_identity_owner", "_decision", "_recognition_quality_gate",
    "_fused_identity_vector", "_drop_locked_identity",
)
SOURCE_ROOTS = (
    "module_app", "frontend", "scripts", "docs", "tests", "tests_browser",
    "tests_integration", "tests_legacy", "tests_v5", "tests_v54",
)
SOURCE_SUFFIXES = {
    ".py", ".js", ".cjs", ".css", ".html", ".md", ".txt", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".svg", ".png", ".webmanifest",
    ".ps1", ".bat", ".cmd",
}
SKIP_DIRECTORIES = {
    "__pycache__", "node_modules", "data", "logs", "models", "backups",
    "vendor", "vendor_py", "runtime", "test_data", "testdata", "dataroot",
}


def digest_file(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def tree(raw: bytes) -> ast.Module:
    return ast.parse(raw.decode("utf-8-sig"))


def dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def named(nodes: list[ast.stmt], name: str) -> ast.AST:
    matches = [node for node in nodes if getattr(node, "name", None) == name]
    if len(matches) != 1:
        raise ValueError("Expected one named source definition")
    return matches[0]


def method(module: ast.Module, owner: str, name: str) -> ast.FunctionDef:
    cls = named(module.body, owner)
    return named(cls.body, name)


def expression(code: str) -> ast.AST:
    return ast.parse(code, mode="eval").body


def statement(code: str) -> ast.stmt:
    return ast.parse(code).body[0]


def config_bindings(module: ast.Module) -> dict[str, list[str]]:
    bindings = defaultdict(list)
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            bindings["|".join(dump(target) for target in targets)].append(dump(node))
    return dict(bindings)


def normalize_pad(module: ast.Module, baseline: ast.Module) -> ast.Module:
    result = copy.deepcopy(module)
    for name, target in (("_probe", "backend"), ("predict", "self._backend")):
        old_condition = expression(f'{target} == "onnxruntime"')
        allowed_condition = expression(f'{target} in {{"onnxruntime", "onnxruntime-cuda"}}')
        old_matches = [node for node in ast.walk(method(baseline, "PassivePadEngine", name))
                       if isinstance(node, ast.If) and dump(node.test) == dump(old_condition)]
        matches = [node for node in ast.walk(method(result, "PassivePadEngine", name))
                   if isinstance(node, ast.If) and dump(node.test) == dump(allowed_condition)]
        if len(old_matches) != 1 or len(matches) != 1:
            raise ValueError("Unexpected PAD dispatch boundary")
        matches[0].test = copy.deepcopy(old_condition)
    return result


def normalize_face_core(module: ast.Module) -> ast.Module:
    result = copy.deepcopy(module)
    cls = named(result.body, "FaceCore")
    init = named(cls.body, "__init__")
    expected_lock = statement("self._lock = threading.RLock()")
    if dump(init.body[0]) != dump(expected_lock):
        raise ValueError("Unexpected model initialization boundary")
    for index, name in ((1, "_detector_lock"), (2, "_recognizer_lock")):
        if dump(init.body[index]) != dump(statement(f"self.{name} = threading.RLock()")):
            raise ValueError("Unexpected independent model lock")
    del init.body[1:3]
    ensure = named(cls.body, "ensure")
    expected_wrapper = statement("def ensure(self) -> None:\n    with self._lock:\n        self._ensure_models()")
    if dump(ensure) != dump(expected_wrapper):
        raise ValueError("Unexpected model initialization wrapper")
    model_init = named(cls.body, "_ensure_models")
    replacement = copy.deepcopy(model_init)
    replacement.name = "ensure"
    cls.body[cls.body.index(ensure)] = replacement
    cls.body.remove(model_init)
    for name, lock in (("detect", "_detector_lock"), ("embedding", "_recognizer_lock")):
        function = named(cls.body, name)
        scope = function.body[0]
        if (not isinstance(scope, ast.With) or len(scope.items) != 1
                or scope.items[0].optional_vars is not None
                or dump(scope.items[0].context_expr) != dump(expression(f"self.{lock}"))):
            raise ValueError("Unexpected inference lock boundary")
        scope.items[0].context_expr = expression("self._lock")
    return result


class Markup(HTMLParser):
    def __init__(self, content: str):
        super().__init__()
        self.ids = Counter()
        self.scripts: list[str] = []
        self.main_count = 0
        self.tags = []
        self.line_offsets = [0] + [match.end() for match in re.finditer("\n", content)]
        self.feed(content)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        self.tags.append((tag, values, start, start + len(self.get_starttag_text())))
        if values.get("id"):
            self.ids[values["id"]] += 1
        if tag == "main":
            self.main_count += 1
        if tag == "script" and values.get("src"):
            self.scripts.append(urlsplit(values["src"]).path)


def inventory_paths() -> list[str]:
    paths = set()
    for folder in SOURCE_ROOTS:
        start = ROOT / folder
        if not start.is_dir():
            continue
        for directory, child_dirs, files in os.walk(start, followlinks=False):
            child_dirs[:] = sorted(name for name in child_dirs
                                   if not name.startswith(".") and name.lower() not in SKIP_DIRECTORIES
                                   and not (Path(directory) / name).is_symlink())
            for name in files:
                path = Path(directory) / name
                if (name.startswith(".") or path.is_symlink() or path.suffix.lower() not in SOURCE_SUFFIXES
                        or path == OUTPUT):
                    continue
                paths.add(path.relative_to(ROOT).as_posix())
    for path in ROOT.iterdir():
        if path.is_file() and not path.is_symlink() and (path.suffix.lower() in {".py", ".md"}
                                                       or path.name in {"VERSION", "VERSION.txt"}):
            paths.add(path.name)
    return sorted(paths)


def category(path: str) -> str:
    first = PurePosixPath(path).parts[0]
    if first.startswith("tests"):
        return "tests"
    if first in {"docs", "scripts"} or Path(path).suffix == ".md":
        return "docs_and_tools"
    return "production"


RTSP_CREDENTIALS = re.compile(r"\brtsps?://[^\s/@'\"<>`{}$\\]+@[^\s/'\"<>`{}$\\]+", re.I)
PRIVATE_IP = re.compile(r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])")
SECRET_NAME = re.compile(r"(?:^|_)(?:(?:owner|admin|default|root)_?)?(?:password|passwd|secret|token|api_?key|access_?key)(?:$|_value$)", re.I)
JS_SECRET = re.compile(r"\b(?:(?:owner|admin|default|root)[_-]?)?(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*(['\"])([^'\"\r\n]+)\1", re.I)
REDACTIONS = {"***", "********", "[redacted]", "<redacted>", "redacted"}


def credential_candidates(path: str, raw: bytes) -> dict[str, list[str]]:
    text = raw.decode("utf-8-sig")
    found = {
        "literal_rtsp_credentials": [match.group(0) for match in RTSP_CREDENTIALS.finditer(text)],
        "private_camera_ip_candidates": [],
        "fixed_secret_candidates": [],
    }
    for match in PRIVATE_IP.finditer(text):
        # CIDR security ranges are not fixed camera endpoints.
        if re.match(r"/\d{1,2}\b", text[match.end():]) or any(int(part) > 255 for part in match.group(0).split(".")):
            continue
        found["private_camera_ip_candidates"].append(match.group(0))
    if path.endswith(".py"):
        for node in ast.walk(tree(raw)):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [target.id if isinstance(target, ast.Name) else target.attr if isinstance(target, ast.Attribute) else "" for target in targets]
                value = node.value.value
                if isinstance(value, str) and value and value.lower() not in REDACTIONS and any(SECRET_NAME.search(name) for name in names):
                    found["fixed_secret_candidates"].append(value)
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (isinstance(key, ast.Constant) and isinstance(key.value, str) and SECRET_NAME.search(key.value)
                            and isinstance(value, ast.Constant) and isinstance(value.value, str)
                            and value.value and value.value.lower() not in REDACTIONS):
                        found["fixed_secret_candidates"].append(value.value)
    else:
        for match in JS_SECRET.finditer(text):
            if match.group(2).lower() not in REDACTIONS and not any(character in match.group(2) for character in "{}$"):
                found["fixed_secret_candidates"].append(match.group(2))
    return found


def reviewed_existing_candidates(path: str, raw: bytes, original: bytes) -> dict[str, Counter]:
    """Recognize only the six reviewed checkpoint references in exact contexts.

    No path-wide exemptions: the Python module AST must remain identical and
    each constant must have its reviewed guard/docstring context. HTML values
    must be unchanged password-toggle references to actual password inputs.
    """
    reviewed = {key: Counter() for key in (
        "literal_rtsp_credentials", "private_camera_ip_candidates", "fixed_secret_candidates")}
    if path in {"module_app/camera_connection_v544.py", "module_app/camera_registry_v547.py"}:
        module = tree(raw)
        if dump(module) != dump(tree(original)):
            return reviewed
        parents = {child: node for node in ast.walk(module) for child in ast.iter_child_nodes(node)}
        for node in ast.walk(module):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            parent = parents.get(node)
            ancestor = parent
            while ancestor is not None and not isinstance(ancestor, ast.FunctionDef):
                ancestor = parents.get(ancestor)
            guard = (path.endswith("camera_connection_v544.py") and isinstance(parent, ast.Compare)
                     and ancestor is not None and ancestor.name == "connection_view")
            assignment = parents.get(parent)
            migration_set = (path.endswith("camera_registry_v547.py") and isinstance(parent, ast.Set)
                             and isinstance(assignment, ast.Assign) and len(assignment.targets) == 1
                             and isinstance(assignment.targets[0], ast.Name)
                             and assignment.targets[0].id == "LEGACY_HIKVISION_HOSTS")
            migration_doc = (path.endswith("camera_registry_v547.py") and isinstance(parent, ast.Expr)
                             and ancestor is not None and ancestor.name == "candidate_hosts_for_legacy"
                             and ancestor.body[0] is parent)
            if guard or migration_set or migration_doc:
                reviewed["private_camera_ip_candidates"].update(match.group(0) for match in PRIVATE_IP.finditer(node.value))
    if path == "frontend/index.html":
        text = raw.decode("utf-8-sig")
        markup = Markup(text)
        inputs = {attrs.get("id") for tag, attrs, _, _ in markup.tags
                  if tag == "input" and attrs.get("type") == "password"}
        old_matches = Counter(match.group(0) for match in JS_SECRET.finditer(original.decode("utf-8-sig")))
        for match in JS_SECRET.finditer(text):
            tag = next((entry for entry in markup.tags if entry[2] <= match.start() and match.end() <= entry[3]), None)
            if (old_matches[match.group(0)] and tag and tag[0] == "button"
                    and tag[1].get("data-toggle-password") == match.group(2) and match.group(2) in inputs):
                reviewed["fixed_secret_candidates"].update([match.group(2)])
                old_matches[match.group(0)] -= 1
    return reviewed


def named_stock_config_scan() -> list[dict]:
    results = []
    for path in ("config/cameras.json", "config/hikvision_test_camera.json"):
        candidate_counts = {"nonempty_secret_fields": 0, "literal_rtsp_userinfo": 0}

        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if (SECRET_NAME.search(str(key)) and isinstance(item, str) and item.strip()):
                        candidate_counts["nonempty_secret_fields"] += 1
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, str):
                candidate_counts["literal_rtsp_userinfo"] += len(RTSP_CREDENTIALS.findall(value))

        visit(json.loads((ROOT / path).read_text(encoding="utf-8-sig")))
        results.append({"path": path, **candidate_counts})
    return results


def main() -> int:
    checks = []
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Source-only standard-library audit against the preserved WebRTC archive; no application imports or runtime writes.",
        "checks": checks,
        "excluded_reads": [".codex_tools", "runtime/customer databases and DataRoots", "isolated pytest DataRoots", "logs", "models", "vendor dependencies"],
        "limitations": [
            "AST equality excludes comments and formatting; it proves the listed definitions and assignments, not every runtime path.",
            "The archive is a selective source checkpoint and includes bytecode; not-in-archive paths are not proof they were created during this run.",
            "Credential scanning is a literal-source heuristic; computed values, external configuration, database credentials and encrypted secret stores are outside its scope.",
            "Frontend media order and API guards are structural checks; lifecycle/security behavior requires the separately executed regression suites.",
            "Archive bytecode is checked for presence and archive CRC only, not used as an application source baseline.",
        ],
        "acceptance": {
            "real_mediamtx_hikvision": {"status": "BLOCKED", "reason": "No hardware acceptance run by this source-only audit."},
            "real_models_gpu": {"status": "BLOCKED", "reason": "No real model/GPU execution by this audit."},
            "real_postgresql": {"status": "BLOCKED", "reason": "No PostgreSQL integration environment exercised by this audit."},
            "rendered_desktop_mobile_ui": {"status": "BLOCKED", "reason": "Source checks do not establish rendered layout, focus, FPS, latency or soak acceptance."},
            "final_easy_install": {"status": "NOT_CREATED"},
        },
    }

    def check(name, passed, **evidence):
        checks.append({"name": name, "status": "PASS" if passed else "FAIL", **evidence})

    def guarded(name, action):
        try:
            action()
        except Exception as error:
            # Exception text and source literals are deliberately never reported.
            checks.append({"name": name, "status": "FAIL", "error_type": type(error).__name__})

    try:
        archive_sha = digest_file(ARCHIVE)
        check("rollback_archive_sha256", archive_sha == EXPECTED_SHA256,
              path=ARCHIVE.relative_to(ROOT).as_posix(), expected_sha256=EXPECTED_SHA256, actual_sha256=archive_sha)
        with zipfile.ZipFile(ARCHIVE, "r") as archive:
            names = archive.namelist()
            check("rollback_archive_entries_crc", len(names) == 210 and archive.testzip() is None,
                  expected_entries=210, actual_entries=len(names))
            safe_names = [name for name in names if not PurePosixPath(name).is_absolute()
                          and ".." not in PurePosixPath(name).parts and ":" not in name and "\\" not in name]
            check("rollback_archive_safe_paths", len(safe_names) == len(names), unsafe_path_count=len(names) - len(safe_names))
            missing = [name for name in safe_names if not (ROOT / name).is_file()]
            check("all_checkpoint_paths_retained", not missing, checked_paths=len(safe_names), missing_paths=missing)
            baseline = lambda name: tree(archive.read(name))
            current = lambda name: tree((ROOT / name).read_bytes())

            def config_check():
                old, new = config_bindings(baseline("module_app/config.py")), config_bindings(current("module_app/config.py"))
                count = sum(map(len, old.values()))
                changed = sum(new.get(target) != definitions for target, definitions in old.items())
                check("original_config_assignments", count == 151 and changed == 0, expected_count=151,
                      original_count=count, current_count=sum(map(len, new.values())), changed_original_bindings=changed)
            guarded("original_config_assignments", config_check)

            def policy_check():
                old, new = baseline("module_app/walkby.py"), current("module_app/walkby.py")
                mismatches = [name for name in PROTECTED_POLICY
                              if dump(method(old, "WalkByEngine", name)) != dump(method(new, "WalkByEngine", name))]
                check("walkby_protected_policy_methods", not mismatches, methods=list(PROTECTED_POLICY), changed_methods=mismatches)
            guarded("walkby_protected_policy_methods", policy_check)

            def modules_check():
                paths = [f"module_app/{name}.py" for name in PROTECTED_MODULES]
                changed = [path for path in paths if dump(baseline(path)) != dump(current(path))]
                check("protected_auth_database_security_context_sms_modules", len(paths) == 14 and not changed,
                      checked_count=len(paths), checked_paths=paths, changed_paths=changed)
            guarded("protected_auth_database_security_context_sms_modules", modules_check)

            def pad_check():
                path = "module_app/passive_pad.py"
                old, new = baseline(path), current(path)
                check("pad_only_cpu_cuda_dispatch_changes", dump(normalize_pad(new, old)) == dump(old), path=path,
                      allowed_dispatch_methods=["_probe", "predict"], unchanged_scope="Models, profiles, hashes, preprocessing, classes, scores and all other module AST.")
            guarded("pad_only_cpu_cuda_dispatch_changes", pad_check)

            def face_check():
                path = "module_app/face_core.py"
                check("face_core_only_model_lock_boundaries", dump(normalize_face_core(current(path))) == dump(baseline(path)), path=path,
                      allowed_changes=["Two independent RLocks", "Serialized ensure/_ensure_models wrapper", "detect detector lock", "embedding recognizer lock"],
                      unchanged_scope="Every other module AST, including models, thresholds, preprocessing and inference policy.")
            guarded("face_core_only_model_lock_boundaries", face_check)

            def markup_check():
                path = "frontend/index.html"
                old, new = Markup(archive.read(path).decode("utf-8-sig")), Markup((ROOT / path).read_text(encoding="utf-8-sig"))
                missing_ids = list((old.ids - new.ids).elements())
                duplicates = [name for name, count in new.ids.items() if count > 1]
                check("checkpoint_html_ids_and_main_landmark", not missing_ids and not duplicates and new.main_count == 1,
                      checkpoint_id_count=sum(old.ids.values()), current_id_count=sum(new.ids.values()),
                      missing_ids=missing_ids, duplicate_ids=duplicates, current_main_count=new.main_count)
                old_scripts = [path for path in new.scripts if path in old.scripts]
                check("checkpoint_script_order_and_single_load", old_scripts == old.scripts and len(new.scripts) == len(set(new.scripts)),
                      checkpoint_scripts=old.scripts, current_scripts=new.scripts)
            guarded("checkpoint_markup", markup_check)

            def media_check():
                path = "frontend/js/btmh_media_v5410.js"
                arrays = []
                for raw in (archive.read(path), (ROOT / path).read_bytes()):
                    match = re.search(r"const\s+order\s*=\s*(\[[^;\n]+\])", raw.decode("utf-8-sig"))
                    if not match:
                        raise ValueError("Missing transport order")
                    arrays.append(ast.literal_eval(match.group(1)))
                check("native_first_media_transport_order", arrays[0] == arrays[1] == ["native", "webrtc", "ws", "mjpeg", "poll"],
                      checkpoint_order=arrays[0], current_order=arrays[1])
            guarded("native_first_media_transport_order", media_check)

            def routes_check():
                old, new = baseline("module_app/main.py"), current("module_app/main.py")
                unchanged = dump(named(old.body, "_auth_permission")) == dump(named(new.body, "_auth_permission"))
                check("rbac_permission_helper_unchanged", unchanged)
                expected_guard = statement('_auth_permission(request, "system.diagnostics")')
                for name, verb, route in (
                    ("system_diagnostics", "get", "/api/v1/system/diagnostics"),
                    ("system_self_test", "post", "/api/v1/system/self-test"),
                    ("system_performance_diagnostics", "get", "/api/v1/system/diagnostics/performance"),
                ):
                    function = named(new.body, name)
                    expected_route = expression(f'app.{verb}("{route}")')
                    check(f"{name}_permission_and_route", bool(function.body) and dump(function.body[0]) == dump(expected_guard)
                          and any(dump(decorator) == dump(expected_route) for decorator in function.decorator_list), route=route,
                          permission="system.diagnostics")
                function = named(new.body, "system_performance_diagnostics")
                expected_return = statement('return JSONResponse(result, headers={"Cache-Control": "no-store"})')
                expected_collect = statement("result = collect_performance_diagnostics(CAMERA, MEDIA_GATEWAY, RECORDER_V4, FLEET_V4, PILOT)")
                check("performance_route_authorization_before_cached_collector_no_store", len(function.body) == 3
                      and dump(function.body[1]) == dump(expected_collect) and dump(function.body[2]) == dump(expected_return))
                function = named(new.body, "system_self_test")
                expected_forward = statement("result = system_diagnostics(request)")
                check("self_test_forwards_request", any(dump(node) == dump(expected_forward) for node in function.body))
            guarded("diagnostics_route_source_guards", routes_check)

            paths = inventory_paths()
            inventory = {group: {"modified_from_archive": [], "not_in_archive": [], "unchanged_archive_count": 0}
                         for group in ("production", "tests", "docs_and_tools")}
            for path in paths:
                group = inventory[category(path)]
                if path not in names:
                    group["not_in_archive"].append(path)
                elif (ROOT / path).read_bytes() != archive.read(path):
                    group["modified_from_archive"].append(path)
                else:
                    group["unchanged_archive_count"] += 1
            report["inventory"] = {"source_roots": list(SOURCE_ROOTS), "file_count": len(paths),
                                   "generated_report_excluded_from_self_inventory": OUTPUT.relative_to(ROOT).as_posix(),
                                   "groups": inventory}

            scan_paths = [path for path in paths if (path.startswith("module_app/") and path.endswith(".py"))
                          or (path.startswith("frontend/") and Path(path).suffix in {".js", ".html"})
                          or ("/" not in path and path.endswith(".py"))]
            findings = {name: {"count": 0, "checkpoint_count": 0, "introduced_count": 0, "reviewed_existing_count": 0,
                               "unreviewed_count": 0, "paths": [], "introduced_paths": [], "reviewed_existing_paths": [], "unreviewed_paths": []}
                        for name in ("literal_rtsp_credentials", "private_camera_ip_candidates", "fixed_secret_candidates")}
            for path in scan_paths:
                found = credential_candidates(path, (ROOT / path).read_bytes())
                old_found = credential_candidates(path, archive.read(path)) if path in names else {key: [] for key in findings}
                reviewed = reviewed_existing_candidates(path, (ROOT / path).read_bytes(), archive.read(path)) if path in names else {key: Counter() for key in findings}
                for key, values in found.items():
                    introduced = sum((Counter(values) - Counter(old_found[key])).values())
                    reviewed_count = sum((Counter(values) & Counter(old_found[key]) & reviewed[key]).values())
                    unreviewed = len(values) - reviewed_count
                    entry = findings[key]
                    entry["count"] += len(values); entry["checkpoint_count"] += len(old_found[key]); entry["introduced_count"] += introduced
                    entry["reviewed_existing_count"] += reviewed_count; entry["unreviewed_count"] += unreviewed
                    if values:
                        entry["paths"].append(path)
                    if introduced:
                        entry["introduced_paths"].append(path)
                    if reviewed_count:
                        entry["reviewed_existing_paths"].append(path)
                    if unreviewed:
                        entry["unreviewed_paths"].append(path)
            total_candidates = sum(entry["count"] for entry in findings.values())
            unreviewed = sum(entry["unreviewed_count"] for entry in findings.values())
            report["credential_hygiene"] = {"status": "PASS" if unreviewed == 0 else "REVIEW_REQUIRED",
                                            "scope": "module_app Python, frontend JavaScript/HTML and top-level Python product tools; tests/docs/runtime excluded; only two explicitly named stock configs read separately",
                                            "scanned_file_count": len(scan_paths), "candidate_count": total_candidates, "findings": findings,
                                            "reviewed_contexts": [
                                                {"path": "module_app/camera_connection_v544.py", "kind": "Unchanged historical camera mismatch comparison; not a camera default."},
                                                {"path": "module_app/camera_registry_v547.py", "kind": "Unchanged legacy migration sentinel set and migration docstring; not a new camera default."},
                                                {"path": "frontend/index.html", "kind": "Unchanged data-toggle-password button references to password input IDs; no password value."},
                                            ],
                                            "values_redacted": True}
            check("credential_source_scan_no_unreviewed_literal_candidates", unreviewed == 0,
                  candidate_count=total_candidates, reviewed_existing_count=sum(entry["reviewed_existing_count"] for entry in findings.values()),
                  unreviewed_count=unreviewed, introduced_candidate_count=sum(entry["introduced_count"] for entry in findings.values()))
            def config_credentials_check():
                results = named_stock_config_scan()
                report["credential_hygiene"]["named_stock_configs"] = results
                check("named_stock_configs_no_fixed_secrets_or_rtsp_userinfo", all(not result["nonempty_secret_fields"]
                      and not result["literal_rtsp_userinfo"] for result in results), checked_paths=[result["path"] for result in results])
            guarded("named_stock_configs_no_fixed_secrets_or_rtsp_userinfo", config_credentials_check)
            check("rollback_archive_sha256_after_audit", digest_file(ARCHIVE) == EXPECTED_SHA256)
    except Exception as error:
        checks.append({"name": "source_audit_execution", "status": "FAIL", "error_type": type(error).__name__})

    failed = sum(check["status"] == "FAIL" for check in checks)
    report["status"] = "PASS" if not failed else "FAIL"
    report["summary"] = {"passed_checks": len(checks) - failed, "failed_checks": failed}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], **report["summary"], "report": OUTPUT.relative_to(ROOT).as_posix()}, ensure_ascii=True))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

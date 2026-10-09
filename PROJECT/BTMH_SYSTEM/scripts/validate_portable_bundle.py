"""Fail-closed offline payload audit; no downloads, installation or DB access.

Build inventory proves payload integrity, not upstream authenticity or hardware
acceptance. Reviewed acquisition and distribution evidence is required separately.
"""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MEDIA_PIN = "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23"
ARTIFACTS = (
    ("python", "vendor/python-3.12.10-amd64.exe", 20_000_000, ("67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb",), "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"),
    ("postgresql", "vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip", 20_000_000, (), "https://get.enterprisedb.com/postgresql/postgresql-17.11-3-windows-x64-binaries.zip"),
    ("mediamtx", "vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip", 1_000_000, (MEDIA_PIN,), "https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/mediamtx_v1.21.1_windows_amd64.zip"),
    ("yunet", "models/face_detection_yunet_2023mar.onnx", 100_000, ("8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",), "https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet"),
    ("sface", "models/face_recognition_sface_2021dec.onnx", 1_000_000, ("0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",), "https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface"),
    ("pad", "models/minifasnet_v2.onnx", 100_000, ("b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907", "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b"), "https://github.com/yakhyo/face-anti-spoofing/releases/tag/weights"),
)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    rel = PurePosixPath(relative.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or any(p in (".", "..") or ":" in p for p in rel.parts):
        raise ValueError("unsafe payload path")
    path = root.joinpath(*rel.parts)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("payload path escapes bundle")
    return path


def pe_x64(data: bytes) -> bool:
    if len(data) < 64 or data[:2] != b"MZ":
        return False
    offset = struct.unpack_from("<I", data, 60)[0]
    return offset + 6 <= len(data) and data[offset:offset + 4] == b"PE\0\0" and struct.unpack_from("<H", data, offset + 4)[0] == 0x8664


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements(root: Path) -> dict[str, str]:
    pins = {}
    for filename in ("requirements-runtime.txt", "requirements-media.txt"):
        for line in (root / filename).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            match = re.fullmatch(r"([\w.-]+)(?:\[[\w,.-]+\])?==([\w.+-]+)", line)
            if not match:
                raise ValueError(f"unpinned production requirement in {filename}")
            pins[normalize(match[1])] = match[2]
    return pins


def audit(root: Path, *, resolve: bool = True) -> dict:
    root = root.resolve()
    issues, inventory = [], []
    try:
        provenance = json.loads((root / "vendor/offline-provenance.json").read_text(encoding="utf-8-sig"))["artifacts"]
    except (OSError, ValueError, KeyError):
        provenance = {}
        issues.append("ACQUISITION_EVIDENCE_MISSING: vendor/offline-provenance.json")
    for name, relative, minimum, pins, source in ARTIFACTS:
        item = {"component": name, "path": relative, "source": source, "expected_sha256": list(pins), "status": "BLOCKED"}
        path = safe_path(root, relative)
        if not path.is_file() or path.stat().st_size < minimum:
            issues.append(f"ARTIFACT_MISSING_OR_TRUNCATED: {relative}")
        else:
            item.update(size=path.stat().st_size, sha256=digest(path))
            evidence = provenance.get(name, {})
            expected = pins or (str(evidence.get("upstream_sha256", "")),)
            if item["sha256"] not in expected:
                issues.append(f"UPSTREAM_HASH_MISMATCH_OR_UNKNOWN: {relative}")
            elif not evidence.get("source_url", "").startswith("https://") or not evidence.get("verification_method"):
                issues.append(f"ACQUISITION_EVIDENCE_MISSING: {name}")
            else:
                item["status"] = "VERIFIED_PAYLOAD"
            try:
                # WiX/Burn can use a 32-bit bootstrap executable for an amd64
                # installer. Runtime architecture is checked after installation.
                if name == "python" and path.read_bytes()[:2] != b"MZ":
                    raise ValueError("Python installer is not a Windows executable")
                if name in ("postgresql", "mediamtx"):
                    with zipfile.ZipFile(path) as archive:
                        names = archive.namelist()
                        for entry in names:
                            safe_path(root, entry)
                        expected_exe = "mediamtx.exe" if name == "mediamtx" else next((n for n in names if n.lower().endswith("/bin/postgres.exe")), "")
                        if not expected_exe or not pe_x64(archive.read(expected_exe)[:1024 * 1024]):
                            raise ValueError("archive Windows x64 binary missing")
            except (OSError, ValueError, KeyError, zipfile.BadZipFile):
                issues.append(f"INVALID_BINARY_ARCHIVE: {name}")
                item["status"] = "BLOCKED"
        for filename, minimum_size in (("LICENSE.txt", 100), ("DISTRIBUTION_REVIEW.txt", 40)):
            path = root / "vendor/licenses" / name / filename
            if not path.is_file() or path.stat().st_size < minimum_size:
                issues.append(f"DISTRIBUTION_EVIDENCE_MISSING: vendor/licenses/{name}/{filename}")
        inventory.append(item)
    wheel_inventory = []
    for path in sorted((root / "vendor/wheels").glob("*.whl")):
        try:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.namelist():
                    safe_path(root, entry)
                metadata_path = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
                metadata = BytesParser().parsebytes(archive.read(metadata_path))
                tag_path = next(n for n in archive.namelist() if n.endswith(".dist-info/WHEEL"))
                if not re.search(r"^Tag: .+-(?:win_amd64|any)$", archive.read(tag_path).decode("utf-8"), re.M):
                    raise ValueError("wheel not Windows x64 or platform independent")
                licenses = [n for n in archive.namelist() if "license" in n.lower() or "copying" in n.lower()]
                if not licenses:
                    issues.append(f"WHEEL_LICENSE_NOTICE_MISSING: {path.name}")
                dependencies = metadata.get_all("Requires-Dist", [])
                if any("@" in requirement or "http://" in requirement or "https://" in requirement or "git+" in requirement for requirement in dependencies):
                    issues.append(f"REMOTE_WHEEL_DEPENDENCY: {path.name}")
                record = {"path": path.relative_to(root).as_posix(), "name": normalize(metadata["Name"]), "version": metadata["Version"], "sha256": digest(path), "size": path.stat().st_size, "licenses": licenses, "requires_dist": dependencies}
                if record["name"] == "imageio-ffmpeg":
                    binaries = [n for n in archive.namelist() if n.lower().endswith(".exe") and "ffmpeg" in n.lower()]
                    if not binaries or not pe_x64(archive.read(binaries[0])[:1024 * 1024]):
                        issues.append("FFMPEG_WINDOWS_X64_BINARY_MISSING")
                    else:
                        record["ffmpeg_binary"] = binaries[0]
                wheel_inventory.append(record)
        except (OSError, ValueError, KeyError, TypeError, StopIteration, zipfile.BadZipFile):
            issues.append(f"INVALID_WHEEL: {path.name}")
    try:
        for name, version in requirements(root).items():
            if not any(w["name"] == name and w["version"] == version for w in wheel_inventory):
                issues.append(f"PINNED_WHEEL_MISSING: {name}=={version}")
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
    if not any(w.get("ffmpeg_binary") for w in wheel_inventory):
        issues.append("FFMPEG_WINDOWS_X64_BINARY_MISSING: imageio-ffmpeg wheel")
    for filename in ("LICENSE.txt", "DISTRIBUTION_REVIEW.txt", "SOURCE.txt"):
        path = root / "vendor/licenses/ffmpeg" / filename
        if not path.is_file() or path.stat().st_size < 40:
            issues.append(f"FFMPEG_DISTRIBUTION_EVIDENCE_MISSING: vendor/licenses/ffmpeg/{filename}")
    frontend = root / "frontend/index.html"
    if not frontend.is_file():
        issues.append("FRONTEND_MISSING")
    else:
        for ref in re.findall(r'(?:src|href)=["\']([^"\']+)["\']', frontend.read_text(encoding="utf-8")):
            if ref.startswith(("http://", "https://", "//")):
                issues.append("REMOTE_FRONTEND_ASSET: offline production must use local assets")
            elif not ref.startswith(("#", "data:", "mailto:", "/api/")):
                relative = ref.split("?", 1)[0].split("#", 1)[0].lstrip("/").removeprefix("frontend/").removeprefix("static/")
                if relative and not safe_path(root / "frontend", relative).is_file():
                    issues.append(f"FRONTEND_ASSET_MISSING: {relative}")
    pg_archive = root / "vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip"
    pg_sidecar = pg_archive.with_name(pg_archive.name + ".sha256")
    try:
        expected = pg_sidecar.read_text(encoding="ascii").strip().split()[0].lower()
        recorded = str(provenance.get("postgresql", {}).get("upstream_sha256", "")).lower()
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or expected != recorded or not pg_archive.is_file() or digest(pg_archive) != expected:
            issues.append("POSTGRESQL_ACQUISITION_CHECKSUM_MISMATCH")
    except (OSError, IndexError, UnicodeError):
        issues.append("POSTGRESQL_ACQUISITION_CHECKSUM_MISSING: vendor/postgresql/postgresql-17.11-3-windows-x64-binaries.zip.sha256")
    dependency_check = "NOT_RUN"
    if resolve and any(issue.startswith("REMOTE_WHEEL_DEPENDENCY") for issue in issues):
        issues.append("OFFLINE_DEPENDENCY_CLOSURE_REFUSED: remote wheel dependency")
    elif resolve and wheel_inventory:
        if os.name != "nt" or sys.version_info[:2] != (3, 12):
            issues.append("DEPENDENCY_RESOLUTION_REQUIRES_WINDOWS_PYTHON_3_12")
        else:
            with tempfile.TemporaryDirectory(prefix="btmh-offline-audit-") as tmp:
                command = [sys.executable, "-m", "pip", "install", "--dry-run", "--ignore-installed", "--disable-pip-version-check", "--no-index", "--find-links", str(root / "vendor/wheels"), "--report", str(Path(tmp) / "resolve.json")]
                for filename in ("requirements-runtime.txt", "requirements-media.txt"):
                    command.extend(["-r", str(root / filename)])
                try:
                    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
                    dependency_check = "PASS" if result.returncode == 0 else "FAIL"
                except (OSError, subprocess.TimeoutExpired):
                    dependency_check = "BLOCKED"
                if dependency_check != "PASS":
                    issues.append("OFFLINE_DEPENDENCY_CLOSURE_FAILED: pip --dry-run --no-index could not resolve all requirements")
    elif resolve:
        issues.append("OFFLINE_DEPENDENCY_CLOSURE_NOT_RUN: no wheels")
    return {"product": "BTMH", "version": "5.4.10", "status": "BLOCKED" if issues else "PAYLOAD_VERIFIED", "issues": sorted(set(issues)), "artifacts": inventory, "wheels": wheel_inventory, "dependency_resolution": dependency_check, "hardware_acceptance": "NOT_RUN"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = audit(args.root)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for issue in result["issues"]:
        print("[BLOCKED] " + issue)
    print(f"[{result['status']}] Offline payload audit; real Windows/camera/GPU/phone acceptance remains separate.")
    return 2 if result["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if os.name == "nt":
    default_root = r"%LOCALAPPDATA%\CampusFace"
    data_root = Path(os.path.expandvars(os.environ.get("CAMPUSFACE_DATA_ROOT", default_root)))
else:
    data_root = Path(os.environ.get("CAMPUSFACE_DATA_ROOT", str(ROOT / ".campusface-data")))

MODELS = data_root / "models"
MODELS.mkdir(parents=True, exist_ok=True)
SOURCE_MODELS = ROOT / "models"


PAD_MODEL_PAGE = "https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx/blob/main/minifasnet_v2.onnx"


def curl_download_verified(url: str, dst: Path, spec: dict) -> tuple[bool, str]:
    """Windows fallback when urllib is blocked by a proxy/firewall but curl works."""
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return False, "curl not available"
    tmp = dst.with_suffix(dst.suffix + ".curl.part")
    try:
        tmp.unlink(missing_ok=True)
        cp = subprocess.run(
            [curl, "-L", "--fail", "--retry", "2", "--retry-delay", "2",
             "--connect-timeout", "20", "--max-time", "150", "-o", str(tmp), url],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180,
        )
        if cp.returncode != 0:
            return False, (cp.stdout or f"curl exit {cp.returncode}")[-400:]
        variant = valid_variant(tmp, spec)
        if variant is None:
            got = tmp.stat().st_size if tmp.exists() else 0
            digest = sha256_file(tmp) if tmp.exists() and got > 0 else ""
            tmp.unlink(missing_ok=True)
            return False, f"curl download failed verification ({got} bytes, sha256={digest[:16]}...)"
        tmp.replace(dst)
        return True, f"ok/{variant.get('name', 'verified')}"
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False, str(exc)


def browser_assisted_pad_recovery(dst: Path, spec: dict, wait_seconds: int = 180) -> bool:
    """Last-resort guided recovery for networks that allow browser downloads only."""
    if os.name != "nt":
        return False
    downloads = Path(os.path.expandvars(r"%USERPROFILE%\Downloads"))
    print("[ASSIST] Automatic PAD download was blocked by the network.")
    print("[ASSIST] CampusFace will open the official MiniFASNet V2 page in your browser.")
    print("[ASSIST] Click Download, keep the original .onnx filename, and save it to Downloads.")
    print(f"[ASSIST] Expected SHA256: {spec['variants'][1]['sha256']}")
    try:
        webbrowser.open(PAD_MODEL_PAGE, new=2)
    except Exception:
        pass
    deadline = time.time() + max(30, int(wait_seconds))
    last_notice = 0.0
    aliases = list(dict.fromkeys(["minifasnet_v2.onnx", "MiniFASNetV2.onnx"]))
    while time.time() < deadline:
        for alias in aliases:
            candidate = downloads / alias
            if valid(candidate, spec) and copy_verified(candidate, dst, spec):
                v = valid_variant(dst, spec) or {}
                print(f"[RECOVERED] minifasnet_v2.onnx copied from Downloads ({v.get('name','verified')})")
                return True
        now = time.time()
        if now - last_notice >= 15:
            left = int(max(0, deadline - now))
            print(f"[WAIT] Waiting for verified MiniFASNet V2 in Downloads... {left}s")
            last_notice = now
        time.sleep(2)
    return False

MODEL_SPECS = {
    "face_detection_yunet_2023mar.onnx": {
        "variants": [
            {"size": 232589, "sha256": "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"},
        ],
        "aliases": ["face_detection_yunet_2023mar.onnx"],
        "urls": [
            "https://files.kde.org/digikam/facesengine/yunet/face_detection_yunet_2023mar.onnx",
            "https://mirrors.dotsrc.org/kde-applicationdata/digikam/facesengine/yunet/face_detection_yunet_2023mar.onnx",
            "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx?download=true",
            "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        ],
    },
    "face_recognition_sface_2021dec.onnx": {
        "variants": [
            {"size": 38696353, "sha256": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"},
        ],
        "aliases": ["face_recognition_sface_2021dec.onnx"],
        "urls": [
            "https://files.kde.org/digikam/facesengine/dnnface/face_recognition_sface_2021dec.onnx",
            "https://kde.cs.nycu.edu.tw/files/digikam/facesengine/dnnface/face_recognition_sface_2021dec.onnx",
            "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx?download=true",
            "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        ],
    },
    "minifasnet_v2.onnx": {
        # Two independently published, verified ONNX exports are supported.
        # Runtime selects preprocessing/class order from SHA-256.
        "variants": [
            {"size": None, "sha256": "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907", "name": "yakhyo"},
            {"size": 1744116, "sha256": "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b", "name": "huggingface"},
        ],
        "aliases": ["minifasnet_v2.onnx", "MiniFASNetV2.onnx"],
        "urls": [
            # GitHub Release first: more reliable on many Windows customer networks.
            "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx",
            "https://github.com/leandroveronezi/go-onnxface/releases/download/models-v1/minifasnet_v2.onnx",
            "https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx/resolve/main/minifasnet_v2.onnx?download=true",
            "https://huggingface.co/garciafido/minifasnet-v2-anti-spoofing-onnx/resolve/main/minifasnet_v2.onnx",
        ],
    },
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def valid_variant(path: Path, spec: dict) -> dict | None:
    try:
        if not path.is_file() or path.stat().st_size < 100_000:
            return None
        digest = sha256_file(path)
        size = path.stat().st_size
        for variant in spec.get("variants", []):
            expected_size = variant.get("size")
            if expected_size is not None and size != int(expected_size):
                continue
            if digest == str(variant.get("sha256", "")).lower():
                return dict(variant)
    except OSError:
        return None
    return None


def valid(path: Path, spec: dict) -> bool:
    return valid_variant(path, spec) is not None


def candidate_roots() -> list[Path]:
    roots: list[Path] = [SOURCE_MODELS]
    if os.name == "nt":
        local = Path(os.path.expandvars(r"%LOCALAPPDATA%"))
        program_data = Path(os.path.expandvars(r"%PROGRAMDATA%"))
        user = Path(os.path.expandvars(r"%USERPROFILE%"))
        roots += [
            local / "CampusFaceV1142" / "models",
            local / "CampusFaceV1141" / "models",
            local / "CampusFaceV1140" / "models",
            local / "CampusFace" / "models",
            program_data / "CampusFace" / "models",
            user / "Downloads",
        ]
    return roots


def candidate_paths(root: Path, name: str, spec: dict) -> list[Path]:
    aliases = list(dict.fromkeys([name, *spec.get("aliases", [])]))
    if root.is_file():
        return [root]
    return [root / alias for alias in aliases]


def find_existing(name: str, spec: dict) -> Path | None:
    for root in candidate_roots():
        for p in candidate_paths(root, name, spec):
            if valid(p, spec):
                return p

    # Older source builds may contain either canonical or release-style file names.
    if os.name == "nt":
        face_root = Path(r"C:\FACE")
        if face_root.exists():
            aliases = list(dict.fromkeys([name, *spec.get("aliases", [])]))
            try:
                for alias in aliases:
                    for p in face_root.rglob(alias):
                        if valid(p, spec):
                            return p
            except (OSError, PermissionError):
                pass
    return None


def copy_verified(src: Path, dst: Path, spec: dict) -> bool:
    try:
        if src.resolve() == dst.resolve():
            return valid(dst, spec)
    except OSError:
        pass
    tmp = dst.with_suffix(dst.suffix + ".copying")
    try:
        tmp.unlink(missing_ok=True)
        shutil.copy2(src, tmp)
        if not valid(tmp, spec):
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dst)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def download_verified(url: str, dst: Path, spec: dict) -> tuple[bool, str]:
    tmp = dst.with_suffix(dst.suffix + ".part")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CampusFace-V1-FACE-STABLE",
                "Accept": "application/octet-stream,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as src, tmp.open("wb") as out:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        variant = valid_variant(tmp, spec)
        if variant is None:
            got = tmp.stat().st_size if tmp.exists() else 0
            digest = sha256_file(tmp) if tmp.exists() and got > 0 else ""
            tmp.unlink(missing_ok=True)
            return False, f"download failed verification ({got} bytes, sha256={digest[:16]}...)"
        tmp.replace(dst)
        return True, f"ok/{variant.get('name', 'verified')}"
    except Exception as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False, str(exc)


def main() -> int:
    print(f"[INFO] CampusFace model directory: {MODELS}")
    print("[INFO] Model policy: verified local -> bundled -> recovery -> GitHub/KDE/HF mirrors")

    for name, spec in MODEL_SPECS.items():
        dst = MODELS / name
        variant = valid_variant(dst, spec)
        if variant is not None:
            print(f"[OK] {name} already verified ({dst.stat().st_size/1024/1024:.1f} MB, {variant.get('name','verified')})")
            continue

        # 1) Full-offline bundle.
        for alias in list(dict.fromkeys([name, *spec.get("aliases", [])])):
            bundled = SOURCE_MODELS / alias
            if valid(bundled, spec) and copy_verified(bundled, dst, spec):
                v = valid_variant(dst, spec) or {}
                print(f"[OK] {name} copied from bundled package ({v.get('name','verified')})")
                break
        else:
            bundled = None
        if bundled is not None and valid(dst, spec):
            continue

        # 2) Recover a verified model already present on this PC.
        existing = find_existing(name, spec)
        if existing is not None and copy_verified(existing, dst, spec):
            v = valid_variant(dst, spec) or {}
            print(f"[RECOVERED] {name} copied from: {existing} ({v.get('name','verified')})")
            continue

        # 3) Download mirrors. A failed network source is not fatal until all fail.
        print(f"[INFO] No verified local copy found for {name}; trying download mirrors...")
        last_error = "no source attempted"
        success = False
        for index, url in enumerate(spec.get("urls", []), start=1):
            for attempt in range(1, 3):
                print(f"[DOWNLOAD] {name} source {index}/{len(spec['urls'])}, attempt {attempt}/2")
                ok, detail = download_verified(url, dst, spec)
                if ok:
                    v = valid_variant(dst, spec) or {}
                    print(f"[OK] {name} verified ({dst.stat().st_size/1024/1024:.1f} MB, {v.get('name','verified')})")
                    success = True
                    break
                last_error = detail
                print(f"[WARN] Source failed: {detail}")
                time.sleep(0.8)
            if success:
                break

        # 4) PAD-only network fallbacks.  Some Windows networks block Python urllib
        # while curl/browser downloads still work.  Never accept an unverified file.
        if not success and name == "minifasnet_v2.onnx":
            print("[INFO] Python download was not enough; trying Windows curl fallback...")
            for index, url in enumerate(spec.get("urls", []), start=1):
                print(f"[CURL] {name} source {index}/{len(spec['urls'])}")
                ok, detail = curl_download_verified(url, dst, spec)
                if ok:
                    v = valid_variant(dst, spec) or {}
                    print(f"[OK] {name} verified ({dst.stat().st_size/1024/1024:.1f} MB, {v.get('name','verified')})")
                    success = True
                    break
                last_error = detail
                print(f"[WARN] curl source failed: {detail}")

        if not success and name == "minifasnet_v2.onnx":
            success = browser_assisted_pad_recovery(dst, spec, wait_seconds=180)

        if not success:
            print(f"[ERROR] Cannot prepare {name} from local recovery or any verified source.")
            print(f"[DETAIL] Last error: {last_error}")
            print("[ACTION] CampusFace will NOT mark recognition ready without all verified models.")
            print("[ACTION] Download the official MiniFASNet V2 ONNX, then place it in Downloads or:")
            print(f"         {SOURCE_MODELS}")
            print("         and run REPAIR_PAD_MODEL.bat or INSTALL_CAMPUSFACE.bat again.")
            return 2

    print("[OK] All required AI models are present and cryptographically verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

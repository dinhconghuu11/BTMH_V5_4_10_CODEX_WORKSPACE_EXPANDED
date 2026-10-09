"""One-shot build-machine acquisition evidence; never a customer install step."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SPECS = {
    "mediamtx": (
        "vendor/mediamtx/mediamtx_v1.21.1_windows_amd64.zip",
        "https://github.com/bluenviron/mediamtx/releases/download/v1.21.1/mediamtx_v1.21.1_windows_amd64.zip",
        "faa97974861eb75a68b5aa326c78e7e7a6f670b5ef191bace78e715130381f23",
        "https://raw.githubusercontent.com/bluenviron/mediamtx/v1.21.1/LICENSE",
    ),
    "python": (
        "vendor/python-3.12.10-amd64.exe",
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe",
        "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb",
        "https://raw.githubusercontent.com/python/cpython/v3.12.10/LICENSE",
    ),
    "yunet": (
        "models/face_detection_yunet_2023mar.onnx",
        "https://huggingface.co/opencv/face_detection_yunet/resolve/main/face_detection_yunet_2023mar.onnx?download=true",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/LICENSE",
    ),
    "sface": (
        "models/face_recognition_sface_2021dec.onnx",
        "https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx?download=true",
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
        "https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_recognition_sface/LICENSE",
    ),
    "pad": (
        "models/minifasnet_v2.onnx",
        "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx",
        "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907",
        "https://raw.githubusercontent.com/yakhyo/face-anti-spoofing/main/LICENSE",
    ),
}


def acquire(item):
    name, (relative, url, expected, license_url) = item
    destination = ROOT / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        digest = hashlib.sha256()
        request = urllib.request.Request(url, headers={"User-Agent": "BTMH-build-artifact-audit"})
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        actual = digest.hexdigest()
        if actual != expected:
            temporary.unlink(missing_ok=True)
            return name, {"status": "BLOCKED", "reason": "SHA256_MISMATCH", "actual_sha256": actual}
        temporary.replace(destination)
        license_directory = ROOT / "vendor" / "licenses" / name
        license_directory.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(license_url, timeout=30) as response:
            license_bytes = response.read(2 * 1024 * 1024)
        (license_directory / "LICENSE.txt").write_bytes(license_bytes)
        (license_directory / "ACQUISITION.txt").write_text(
            f"Acquired 2026-10-09 from {url}\nSHA256: {actual}\n"
            f"Primary license source: {license_url}\n"
            "Acquisition proves pinned bytes. Exact redistribution notices and obligations must still be reviewed before commercial release.\n",
            encoding="utf-8",
        )
        return name, {"status": "ACQUIRED", "path": relative, "sha256": actual,
                      "source_url": url, "license_url": license_url, "bytes": destination.stat().st_size}
    except Exception as error:
        temporary.unlink(missing_ok=True)
        return name, {"status": "BLOCKED", "reason": type(error).__name__, "detail": str(error)[:220]}


def main():
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = dict(executor.map(acquire, SPECS.items()))
    evidence = ROOT / ".qa_production" / "artifact-acquisition.json"
    evidence.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if all(item["status"] == "ACQUIRED" for item in results.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())

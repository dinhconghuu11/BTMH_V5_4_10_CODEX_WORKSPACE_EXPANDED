from __future__ import annotations

import subprocess
import threading
import time
from typing import Any

_LOCK = threading.RLock()
_CACHE: dict[str, Any] | None = None
_CACHE_AT = 0.0


def _nvidia_smi() -> dict[str, Any]:
    try:
        cp = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=1.5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        line = (cp.stdout or "").strip().splitlines()[0]
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 4:
            return {
                "nvidia_driver_visible": True,
                "name": parts[0],
                "memory_used_mb": float(parts[1]),
                "memory_total_mb": float(parts[2]),
                "utilization_percent": float(parts[3]),
            }
    except Exception:
        pass
    return {"nvidia_driver_visible": False}


def gpu_status(force: bool = False) -> dict[str, Any]:
    global _CACHE, _CACHE_AT
    now = time.time()
    with _LOCK:
        if _CACHE is not None and not force and now - _CACHE_AT < 2.0:
            return dict(_CACHE)

    data: dict[str, Any] = {
        "available": False,
        "name": "CPU fallback",
        "memory_used_mb": 0.0,
        "memory_total_mb": 0.0,
        "utilization_percent": 0.0,
        "torch_cuda": False,
        "onnx_cuda": False,
        "opencv_cuda": False,
        "nvidia_driver_visible": False,
        "acceleration": [],
    }
    smi = _nvidia_smi()
    data.update(smi)
    if smi.get("nvidia_driver_visible"):
        data["available"] = True

    try:
        import torch
        if torch.cuda.is_available():
            p = torch.cuda.get_device_properties(0)
            data.update({
                "available": True,
                "torch_cuda": True,
                "name": p.name,
                "memory_used_mb": round(torch.cuda.memory_allocated(0) / (1024 * 1024), 1),
                "memory_total_mb": round(p.total_memory / (1024 * 1024), 1),
            })
            data["acceleration"].append("PyTorch CUDA")
    except Exception:
        pass

    try:
        import onnxruntime as ort
        providers = list(ort.get_available_providers())
        data["onnx_providers"] = providers
        if "CUDAExecutionProvider" in providers:
            data["available"] = True
            data["onnx_cuda"] = True
            data["acceleration"].append("ONNX Runtime CUDA")
    except Exception:
        data["onnx_providers"] = []

    try:
        import cv2
        count = int(cv2.cuda.getCudaEnabledDeviceCount()) if hasattr(cv2, "cuda") else 0
        data["opencv_cuda_devices"] = count
        if count > 0:
            data["available"] = True
            data["opencv_cuda"] = True
            data["acceleration"].append("OpenCV CUDA")
    except Exception:
        data["opencv_cuda_devices"] = 0

    if data.get("nvidia_driver_visible") and not data["acceleration"]:
        data["acceleration"].append("NVIDIA GPU detected; current FaceID OpenCV backend remains CPU")
    data["mode"] = "GPU_ASSISTED" if any((data.get("torch_cuda"), data.get("onnx_cuda"), data.get("opencv_cuda"))) else ("GPU_DETECTED" if data.get("nvidia_driver_visible") else "CPU")

    with _LOCK:
        _CACHE = dict(data)
        _CACHE_AT = now
    return data


def inference_device() -> str:
    status = gpu_status()
    return "cuda" if status.get("torch_cuda") else "cpu"


def ultralytics_device():
    return 0 if gpu_status().get("torch_cuda") else "cpu"


def onnx_providers() -> list[str]:
    status = gpu_status()
    if status.get("onnx_cuda"):
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]

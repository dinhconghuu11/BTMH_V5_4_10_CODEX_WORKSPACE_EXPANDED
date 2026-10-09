from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from .config import PAD_ENABLED, PAD_MODEL_V2
from .gpu_manager import onnx_providers

# CampusFace accepts two verified MiniFASNetV2 ONNX exports.
# They are the same upstream architecture/weights family but use different
# preprocessing/class-index conventions, so the runtime selects the correct
# contract from SHA-256 instead of guessing.
_HF_HASH = "d7b3cd9ba8a7ceb13baa8c4720902e27ca3112eff52f926c08804af6b6eecc7b"
_YAKHYO_HASH = "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907"


@dataclass
class PadResult:
    ready: bool
    live_score: float = 0.0
    spoof_score: float = 0.0
    print_score: float = 0.0
    replay_score: float = 0.0
    label: str = "UNKNOWN"
    reason: str = ""
    source: str = "MiniFASNetV2"
    signals: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "live_score": round(float(self.live_score), 4),
            "spoof_score": round(float(self.spoof_score), 4),
            "print_score": round(float(self.print_score), 4),
            "replay_score": round(float(self.replay_score), 4),
            "label": str(self.label),
            "reason": str(self.reason),
            "source": str(self.source),
            "signals": dict(self.signals or {}),
        }


class PassivePadEngine:
    """Passive presentation-attack detection using a verified MiniFASNetV2 ONNX.

    CampusFace intentionally supports two known-good ONNX exports because Windows
    customer networks often reach GitHub releases more reliably than Hugging Face.
    The two exports have different inference conventions:

    * HuggingFace export (sha d7b3...): BGR / 255.0, live class index 0.
    * yakhyo export (sha b329...): BGR float 0..255, live class index 1.

    Selecting by hash avoids the previous failure mode where a valid model could be
    loaded with the wrong normalization/class order and silently classify everything
    incorrectly.  No active blink/head-turn challenge is used.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._net = None
        self._attempted = False
        self._error = ""
        self._sha256 = ""
        self._profile = ""
        self._backend = ""
        self._input_name = ""
        self._output_name = ""

    @staticmethod
    def _sha256_file(path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().lower()

    @classmethod
    def profile_for_hash(cls, digest: str) -> str:
        digest = str(digest or "").lower()
        if digest == _HF_HASH:
            return "hf_live0_norm01"
        if digest == _YAKHYO_HASH:
            return "yakhyo_live1_raw255"
        return ""

    @property
    def ready(self) -> bool:
        return bool(PAD_ENABLED and PAD_MODEL_V2.is_file() and self._ensure() is not None)

    @property
    def error(self) -> str:
        return str(self._error or "")

    def status(self) -> dict[str, Any]:
        ready = bool(self.ready)
        return {
            "enabled": bool(PAD_ENABLED),
            "ready": ready,
            "model": str(PAD_MODEL_V2),
            "backend": self._backend or "not-loaded",
            "sha256": self._sha256,
            "profile": self._profile,
            "error": self.error,
        }

    def _probe(self, engine, profile: str, backend: str) -> None:
        # Real smoke test: execute the graph and require three finite logits.
        tensor = np.zeros((1, 3, 80, 80), dtype=np.float32)
        tensor.fill(127.0 if profile == "yakhyo_live1_raw255" else 0.5)
        if backend in {"onnxruntime", "onnxruntime-cuda"}:
            raw = np.asarray(engine.run([self._output_name], {self._input_name: tensor})[0], dtype=np.float32).reshape(-1)
        else:
            engine.setInput(tensor)
            raw = np.asarray(engine.forward(), dtype=np.float32).reshape(-1)
        if raw.size < 3 or not np.isfinite(raw[:3]).all():
            raise RuntimeError(f"Unexpected PAD output shape/value: {tuple(raw.shape)}")

    def _ensure(self):
        if not PAD_ENABLED:
            self._error = "Passive PAD disabled by configuration"
            return None
        with self._lock:
            if self._attempted:
                return self._net
            self._attempted = True
            if not PAD_MODEL_V2.is_file():
                self._error = f"PAD model missing: {PAD_MODEL_V2}"
                return None
            try:
                digest = self._sha256_file(PAD_MODEL_V2)
                profile = self.profile_for_hash(digest)
                self._sha256 = digest
                self._profile = profile
                if not profile:
                    raise RuntimeError(
                        "Unsupported/unverified MiniFASNetV2 model hash: " + digest
                    )
                # ONNX Runtime is the primary backend because the published
                # MiniFASNet exports are reference-tested with ORT. OpenCV DNN remains
                # a fallback for prepared offline environments that omit ORT.
                try:
                    import onnxruntime as ort
                    session = ort.InferenceSession(str(PAD_MODEL_V2), providers=onnx_providers())
                    self._input_name = session.get_inputs()[0].name
                    self._output_name = session.get_outputs()[0].name
                    self._backend = "onnxruntime-cuda" if "CUDAExecutionProvider" in session.get_providers() else "onnxruntime"
                    self._probe(session, profile, self._backend)
                    self._net = session
                except Exception as ort_exc:
                    try:
                        net = cv2.dnn.readNetFromONNX(str(PAD_MODEL_V2))
                        net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                        net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                        self._backend = "opencv-dnn"
                        self._probe(net, profile, self._backend)
                        self._net = net
                    except Exception as cv_exc:
                        raise RuntimeError(f"ONNXRuntime failed: {ort_exc}; OpenCV DNN failed: {cv_exc}") from cv_exc
                self._error = ""
            except Exception as exc:
                self._net = None
                self._error = str(exc)
            return self._net

    @staticmethod
    def _crop_scaled(image: np.ndarray, box, scale: float = 2.7) -> np.ndarray | None:
        ih, iw = image.shape[:2]
        x, y, w, h = [float(v) for v in box]
        if w < 8 or h < 8 or ih < 8 or iw < 8:
            return None
        cx = x + w * 0.5
        cy = y + h * 0.5
        effective = min((ih - 1) / max(1.0, h), (iw - 1) / max(1.0, w), float(scale))
        sw = max(w, w * effective)
        sh = max(h, h * effective)
        x1 = max(0, int(round(cx - sw * 0.5)))
        y1 = max(0, int(round(cy - sh * 0.5)))
        x2 = min(iw, int(round(cx + sw * 0.5)))
        y2 = min(ih, int(round(cy + sh * 0.5)))
        if x2 - x1 < 12 or y2 - y1 < 12:
            return None
        crop = image[y1:y2, x1:x2]
        return crop if crop.size else None

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        x = np.asarray(logits, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return x
        x = x - float(np.max(x))
        ex = np.exp(x)
        return ex / max(1e-8, float(np.sum(ex)))

    def _decode(self, probs: np.ndarray) -> tuple[float, float, float, float, str]:
        if self._profile == "hf_live0_norm01":
            live = float(probs[0])
            print_attack = float(probs[1])
            replay_attack = float(probs[2])
            idx = int(np.argmax(probs[:3]))
            label = "REAL" if idx == 0 else ("PRINT" if idx == 1 else "REPLAY")
            return live, print_attack + replay_attack, print_attack, replay_attack, label

        # yakhyo/LocalAI export: index 1 is REAL; 0 and 2 are spoof classes.
        live = float(probs[1])
        spoof_a = float(probs[0])
        spoof_b = float(probs[2])
        idx = int(np.argmax(probs[:3]))
        label = "REAL" if idx == 1 else "SPOOF"
        return live, spoof_a + spoof_b, spoof_a, spoof_b, label

    def predict(self, image: np.ndarray, face_box) -> PadResult:
        net = self._ensure()
        if net is None:
            return PadResult(False, reason=self.error or "PAD model unavailable")
        crop = self._crop_scaled(image, face_box, 2.7)
        if crop is None:
            return PadResult(False, reason="Face crop too small for PAD")
        try:
            resized = cv2.resize(crop, (80, 80), interpolation=cv2.INTER_AREA)
            tensor = resized.astype(np.float32)
            if self._profile == "hf_live0_norm01":
                tensor /= 255.0
            tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
            with self._lock:
                if self._backend in {"onnxruntime", "onnxruntime-cuda"}:
                    raw = net.run([self._output_name], {self._input_name: tensor})[0]
                else:
                    net.setInput(tensor)
                    raw = net.forward()
            probs = self._softmax(raw)
            if probs.size < 3 or not np.isfinite(probs[:3]).all():
                return PadResult(False, reason=f"Unexpected PAD output: {tuple(np.asarray(raw).shape)}")
            live, spoof, print_attack, replay_attack, label = self._decode(probs)
            return PadResult(
                True,
                live_score=live,
                spoof_score=spoof,
                print_score=print_attack,
                replay_score=replay_attack,
                label=label,
                reason="MiniFASNetV2 passive PAD",
                source=f"MiniFASNetV2/{self._profile}",
                signals={
                    "input_size": [80, 80],
                    "crop_scale": 2.7,
                    "model_sha256": self._sha256,
                    "profile": self._profile,
                },
            )
        except Exception as exc:
            return PadResult(False, reason=f"PAD inference failed: {exc}")


PAD = PassivePadEngine()

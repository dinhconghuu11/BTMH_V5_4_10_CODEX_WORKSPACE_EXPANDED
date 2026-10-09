"""Model-lane contracts with fake inference; no GPU, model or camera required."""
from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from module_app import face_core, passive_pad


class FakeOrtSession:
    def __init__(self, providers, logits):
        self.providers = providers
        self.logits = np.asarray(logits, dtype=np.float32)
        self.tensors = []

    def get_inputs(self):
        return [SimpleNamespace(name="image")]

    def get_outputs(self):
        return [SimpleNamespace(name="logits")]

    def get_providers(self):
        return list(self.providers)

    def run(self, output_names, inputs):
        assert output_names == ["logits"]
        assert set(inputs) == {"image"}
        self.tensors.append(inputs["image"].copy())
        return [self.logits.copy()]


class FakeDnn:
    def __init__(self, logits):
        self.logits = np.asarray(logits, dtype=np.float32)
        self.tensors = []
        self.backend = self.target = None

    def setPreferableBackend(self, backend):
        self.backend = backend

    def setPreferableTarget(self, target):
        self.target = target

    def setInput(self, tensor):
        self.tensors.append(tensor.copy())

    def forward(self):
        return self.logits.copy()


def _pad_engine(monkeypatch, tmp_path, digest=passive_pad._HF_HASH):
    model = tmp_path / "test_pad.onnx"
    model.write_bytes(b"fake model; inference is mocked")
    monkeypatch.setattr(passive_pad, "PAD_ENABLED", True)
    monkeypatch.setattr(passive_pad, "PAD_MODEL_V2", model)
    engine = passive_pad.PassivePadEngine()
    monkeypatch.setattr(engine, "_sha256_file", lambda _path: digest)
    return engine


@pytest.mark.parametrize("cuda", [False, True], ids=["cpu", "cuda"])
@pytest.mark.parametrize("digest,profile,logits,probe_value,input_value", [
    (passive_pad._HF_HASH, "hf_live0_norm01", [[4, 1, 0]], 0.5, 128 / 255),
    (passive_pad._YAKHYO_HASH, "yakhyo_live1_raw255", [[1, 4, 0]], 127, 128),
], ids=["hf", "yakhyo"])
def test_pad_ort_probe_and_predict_keep_selected_provider_and_profile(
    monkeypatch, tmp_path, cuda, digest, profile, logits, probe_value, input_value
):
    engine = _pad_engine(monkeypatch, tmp_path, digest)
    providers = (["CUDAExecutionProvider"] if cuda else []) + ["CPUExecutionProvider"]
    session = FakeOrtSession(providers, logits)
    created = []

    def create_session(path, *, providers):
        created.append((path, providers))
        return session

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=create_session))
    monkeypatch.setattr(passive_pad, "onnx_providers", lambda: providers)
    monkeypatch.setattr(passive_pad.cv2.dnn, "readNetFromONNX", lambda _path: pytest.fail("healthy ORT fell back to OpenCV"))

    assert engine._ensure() is session
    assert engine.ready
    assert len(created) == 1 and created[0][1] == providers
    assert engine.status()["backend"] == ("onnxruntime-cuda" if cuda else "onnxruntime")
    assert engine.status()["profile"] == profile
    np.testing.assert_allclose(session.tensors[0], probe_value)

    result = engine.predict(np.full((160, 160, 3), 128, np.uint8), (50, 50, 40, 40))
    assert result.ready and result.label == "REAL"
    assert result.signals["profile"] == profile
    assert result.signals["model_sha256"] == digest
    assert result.signals["crop_scale"] == 2.7
    assert result.live_score == pytest.approx(np.exp(4) / (np.exp(4) + np.exp(1) + 1))
    assert result.live_score + result.spoof_score == pytest.approx(1)
    assert len(session.tensors) == 2
    assert session.tensors[1].shape == (1, 3, 80, 80)
    assert session.tensors[1].dtype == np.float32
    np.testing.assert_allclose(session.tensors[1], input_value)


@pytest.mark.parametrize("ort_logits", [[[np.nan, 0, 1]], [[0, 1]]], ids=["nonfinite", "short"])
def test_pad_invalid_ort_probe_uses_verified_cpu_fallback(monkeypatch, tmp_path, ort_logits):
    engine = _pad_engine(monkeypatch, tmp_path)
    session = FakeOrtSession(["CUDAExecutionProvider", "CPUExecutionProvider"], ort_logits)
    fallback = FakeDnn([[4, 1, 0]])
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *a, **kw: session))
    monkeypatch.setattr(passive_pad, "onnx_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(passive_pad.cv2.dnn, "readNetFromONNX", lambda _path: fallback)

    assert engine._ensure() is fallback
    assert len(session.tensors) == 1
    assert engine.status()["backend"] == "opencv-dnn"
    assert fallback.backend == passive_pad.cv2.dnn.DNN_BACKEND_OPENCV
    assert fallback.target == passive_pad.cv2.dnn.DNN_TARGET_CPU
    assert engine.predict(np.full((160, 160, 3), 128, np.uint8), (50, 50, 40, 40)).ready
    assert len(fallback.tensors) == 2


def test_pad_invalid_outputs_from_both_backends_fail_closed(monkeypatch, tmp_path):
    engine = _pad_engine(monkeypatch, tmp_path)
    session = FakeOrtSession(["CPUExecutionProvider"], [[0, 1]])
    fallback = FakeDnn([[np.nan, 1, 0]])
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *a, **kw: session))
    monkeypatch.setattr(passive_pad, "onnx_providers", lambda: ["CPUExecutionProvider"])
    monkeypatch.setattr(passive_pad.cv2.dnn, "readNetFromONNX", lambda _path: fallback)

    result = engine.predict(np.full((160, 160, 3), 128, np.uint8), (50, 50, 40, 40))
    assert not engine.ready and not result.ready
    assert result.label == "UNKNOWN" and result.live_score == 0
    assert "ONNXRuntime failed" in result.reason and "OpenCV DNN failed" in result.reason


def test_pad_unverified_model_never_reaches_either_backend(monkeypatch, tmp_path):
    engine = _pad_engine(monkeypatch, tmp_path, "0" * 64)
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(InferenceSession=lambda *a, **kw: pytest.fail("unverified model loaded")))
    monkeypatch.setattr(passive_pad.cv2.dnn, "readNetFromONNX", lambda _path: pytest.fail("unverified model loaded"))
    assert engine._ensure() is None
    assert "Unsupported/unverified" in engine.error


def _background(call):
    result = {}
    done = threading.Event()

    def run():
        try:
            result["value"] = call()
        except BaseException as exc:
            result["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, done, result


@pytest.mark.parametrize("blocked_lane", ["detect", "embedding"])
def test_detector_and_recognizer_progress_independently(monkeypatch, blocked_lane):
    """One model can remain busy while the other finishes real core dispatch."""
    core = face_core.FaceCore()
    entered = threading.Event()
    release = threading.Event()
    face = np.array([10, 10, 60, 60, 25, 25, 55, 25, 40, 40, 28, 55, 52, 55, .9], np.float32)
    image = np.full((100, 100, 3), 128, np.uint8)

    def block(lane):
        if blocked_lane == lane:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release fake model")

    class Detector:
        def setInputSize(self, size):
            assert size == (100, 100)

        def detect(self, _image):
            block("detect")
            return 1, face[None, :]

    class Recognizer:
        def alignCrop(self, _image, _face):
            return _image

        def feature(self, _image):
            block("embedding")
            return np.array([[3, 4]], np.float32)

    # Keep ensure() and its initialization lock active, with existing fake handles.
    monkeypatch.setattr(face_core, "YUNET_MODEL", SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(face_core, "SFACE_MODEL", SimpleNamespace(exists=lambda: True))
    monkeypatch.setattr(core, "enhance", lambda frame: frame)
    core._detector = core._far_detector = Detector()
    core._recognizer = Recognizer()
    calls = {
        "detect": lambda: core.detect(image, long_range=False),
        "embedding": lambda: core.embedding(image, face),
    }
    threads = []
    try:
        first = _background(calls[blocked_lane])
        threads.append(first[0])
        assert entered.wait(2), "blocked model never entered inference"
        other_lane = "embedding" if blocked_lane == "detect" else "detect"
        other = _background(calls[other_lane])
        threads.append(other[0])
        assert other[1].wait(2), "independent model waited for blocked model"
        assert "error" not in other[2]
        assert not first[1].is_set(), "blocked model unexpectedly completed"
        if other_lane == "embedding":
            np.testing.assert_allclose(other[2]["value"], [.6, .8])
        else:
            np.testing.assert_array_equal(other[2]["value"][0], face)
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
            assert not thread.is_alive()
    assert "error" not in first[2]

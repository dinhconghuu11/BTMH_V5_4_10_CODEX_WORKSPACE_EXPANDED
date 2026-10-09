from __future__ import annotations

import base64
import math
import threading
from dataclasses import dataclass

import cv2
import numpy as np

from .gpu_manager import ultralytics_device
from .config import (
    CUSTOM_FACE_MODEL,
    CUSTOM_YOLO_CONF,
    CUSTOM_YOLO_IMGSZ,
    FACE_DETECT_SCORE,
    FACE_LONG_RANGE_SCORE,
    FACE_MIN_PX,
    FACE_NMS,
    SFACE_MODEL,
    USE_CUSTOM_FACE_YOLO,
    YUNET_MODEL,
)


@dataclass
class FaceObservation:
    face: np.ndarray
    bbox: tuple[int, int, int, int]
    embedding: np.ndarray | None
    quality: dict
    pose: str
    yaw: float
    pitch: float


class FaceCore:
    """Fast local face detector + SFace identity feature extractor.

    The runtime uses YuNet as the primary detector because it is very fast on CPU.
    An optional trained YOLO detector can be used only as a long-range proposal
    generator. YuNet then refines each YOLO proposal to recover the five landmarks
    required by SFace. No Internet calls are made here.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # YuNet and SFace own different mutable OpenCV model handles. Serialize
        # callers of each model, while allowing detection and identity concurrently.
        self._detector_lock = threading.RLock()
        self._recognizer_lock = threading.RLock()
        self._detector = None
        self._far_detector = None
        self._recognizer = None
        self._yolo = None
        self._yolo_attempted = False

    @property
    def ready(self) -> bool:
        return YUNET_MODEL.exists() and SFACE_MODEL.exists()

    @property
    def custom_detector_ready(self) -> bool:
        return bool(USE_CUSTOM_FACE_YOLO and CUSTOM_FACE_MODEL.exists())

    def ensure(self) -> None:
        with self._lock:
            self._ensure_models()

    def _ensure_models(self) -> None:
        if not self.ready:
            missing = []
            if not YUNET_MODEL.exists():
                missing.append(YUNET_MODEL.name)
            if not SFACE_MODEL.exists():
                missing.append(SFACE_MODEL.name)
            raise RuntimeError(
                "Thiếu model FaceID offline: " + ", ".join(missing) + ". "
                "Đặt model vào thư mục models trước khi chạy nhận diện."
            )
        if self._detector is None:
            self._detector = cv2.FaceDetectorYN.create(
                str(YUNET_MODEL), "", (320, 320), FACE_DETECT_SCORE, FACE_NMS, 5000
            )
        if self._far_detector is None:
            self._far_detector = cv2.FaceDetectorYN.create(
                str(YUNET_MODEL), "", (320, 320), FACE_LONG_RANGE_SCORE, FACE_NMS, 5000
            )
        if self._recognizer is None:
            self._recognizer = cv2.FaceRecognizerSF.create(str(SFACE_MODEL), "")

    def _ensure_yolo(self):
        if self._yolo_attempted:
            return self._yolo
        self._yolo_attempted = True
        if not self.custom_detector_ready:
            return None
        try:
            from ultralytics import YOLO
            self._yolo = YOLO(str(CUSTOM_FACE_MODEL))
        except Exception:
            self._yolo = None
        return self._yolo

    @staticmethod
    def decode_data_url(data_url: str) -> np.ndarray:
        payload = data_url.split(",", 1)[1] if "," in data_url else data_url
        raw = base64.b64decode(payload)
        arr = np.frombuffer(raw, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Ảnh camera không hợp lệ")
        return image

    @staticmethod
    def encode_jpeg_data_url(image: np.ndarray, quality: int = 86) -> str:
        ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")

    @staticmethod
    def illumination(image: np.ndarray) -> dict:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return {
            "brightness": float(np.mean(gray)),
            "contrast": float(np.std(gray)),
        }

    @staticmethod
    def enhance(image: np.ndarray) -> np.ndarray:
        """Low-light recovery only when it is useful.

        It is intentionally conservative: unnecessary CLAHE/gamma changes can hurt
        face embeddings, so bright/normal frames are returned unchanged.
        """
        info = FaceCore.illumination(image)
        if info["brightness"] >= 92 and info["contrast"] >= 30:
            return image
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clip = 2.0 if info["brightness"] >= 55 else 2.5
        l = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(l)
        work = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
        if info["brightness"] < 78:
            gamma = 0.74 if info["brightness"] >= 48 else 0.62
            table = np.array([((i / 255.0) ** gamma) * 255.0 for i in range(256)]).astype("uint8")
            work = cv2.LUT(work, table)
        return work

    @staticmethod
    def _rescale_face(face: np.ndarray, scale: float) -> np.ndarray:
        out = np.asarray(face, dtype=np.float32).copy()
        inv = 1.0 / max(scale, 1e-6)
        out[:14] *= inv
        return out

    @staticmethod
    def _translate_face(face: np.ndarray, dx: float, dy: float, scale: float = 1.0) -> np.ndarray:
        out = np.asarray(face, dtype=np.float32).copy()
        if scale != 1.0:
            out[:14] /= max(scale, 1e-6)
        out[0] += dx
        out[1] += dy
        for i in range(4, 14, 2):
            out[i] += dx
            out[i + 1] += dy
        return out

    def _detect_with(self, detector, image: np.ndarray) -> list[np.ndarray]:
        h, w = image.shape[:2]
        detector.setInputSize((w, h))
        _retval, faces = detector.detect(image)
        if faces is None:
            return []
        return [np.asarray(f, dtype=np.float32) for f in faces]

    @staticmethod
    def iou(a, b) -> float:
        ax, ay, aw, ah = map(float, a[:4])
        bx, by, bw, bh = map(float, b[:4])
        x1, y1 = max(ax, bx), max(ay, by)
        x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def _merge_faces(self, faces: list[np.ndarray]) -> list[np.ndarray]:
        ranked = sorted(faces, key=lambda f: float(f[14]) if len(f) > 14 else 0.0, reverse=True)
        kept: list[np.ndarray] = []
        for candidate in ranked:
            if any(self.iou(candidate[:4], current[:4]) > 0.42 for current in kept):
                continue
            kept.append(candidate)
        return kept

    def _yolo_proposals_to_yunet(self, work: np.ndarray) -> list[np.ndarray]:
        model = self._ensure_yolo()
        if model is None:
            return []
        ih, iw = work.shape[:2]
        try:
            results = model.predict(
                source=work,
                conf=CUSTOM_YOLO_CONF,
                imgsz=CUSTOM_YOLO_IMGSZ,
                verbose=False,
                max_det=50,
                device=ultralytics_device(),
            )
        except Exception:
            return []
        if not results:
            return []
        boxes_obj = getattr(results[0], "boxes", None)
        if boxes_obj is None or getattr(boxes_obj, "xyxy", None) is None:
            return []
        try:
            boxes = boxes_obj.xyxy.cpu().numpy()
        except Exception:
            boxes = np.asarray(boxes_obj.xyxy)
        recovered: list[np.ndarray] = []
        for x1, y1, x2, y2 in boxes:
            x1, y1, x2, y2 = map(float, (x1, y1, x2, y2))
            bw, bh = x2 - x1, y2 - y1
            if min(bw, bh) < 10:
                continue
            px = 0.28 * bw
            py = 0.34 * bh
            rx1 = max(0, int(x1 - px))
            ry1 = max(0, int(y1 - py))
            rx2 = min(iw, int(x2 + px))
            ry2 = min(ih, int(y2 + py))
            roi = work[ry1:ry2, rx1:rx2]
            if roi.size == 0:
                continue
            rh, rw = roi.shape[:2]
            # Small proposals are enlarged only inside their ROI, which is cheaper
            # than upscaling the whole frame and still gives YuNet landmark detail.
            scale = min(3.0, max(1.0, 180.0 / max(1.0, min(rw, rh))))
            roi_work = cv2.resize(roi, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale > 1.05 else roi
            local_faces = self._detect_with(self._far_detector, roi_work)
            if not local_faces:
                continue
            # Prefer the detection closest to the proposal center.
            pcx = (x1 + x2) * 0.5 - rx1
            pcy = (y1 + y2) * 0.5 - ry1
            def rank_local(f):
                fx, fy, fw, fh = map(float, f[:4])
                cx = (fx + fw * 0.5) / scale
                cy = (fy + fh * 0.5) / scale
                dist = math.hypot(cx - pcx, cy - pcy)
                conf = float(f[14]) if len(f) > 14 else 0.0
                return dist - conf * 40.0
            best = min(local_faces, key=rank_local)
            recovered.append(self._translate_face(best, rx1, ry1, scale))
        return recovered

    def detect(self, image: np.ndarray, long_range: bool = True, use_custom: bool = False) -> list[np.ndarray]:
        with self._detector_lock:
            self.ensure()
            work = self.enhance(image)
            faces = self._detect_with(self._detector, work)
            # YuNet pyramid fallback is cheap enough to use when the main pass finds
            # no face or only very small faces.
            if long_range and (not faces or min(min(float(f[2]), float(f[3])) for f in faces) < 52):
                h, w = work.shape[:2]
                scale = min(1.75, 2400.0 / max(h, w))
                if scale > 1.06:
                    up = cv2.resize(work, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                    faces.extend(self._rescale_face(f, scale) for f in self._detect_with(self._far_detector, up))
            if use_custom and self.custom_detector_ready:
                faces.extend(self._yolo_proposals_to_yunet(work))
            faces = self._merge_faces(faces)
            faces.sort(key=lambda f: float(f[14]) if len(f) > 14 else 0.0, reverse=True)
            return faces

    @staticmethod
    def bbox(face: np.ndarray, shape=None) -> tuple[int, int, int, int]:
        x, y, w, h = [int(round(float(v))) for v in face[:4]]
        if shape is not None:
            ih, iw = shape[:2]
            x = max(0, min(iw - 1, x))
            y = max(0, min(ih - 1, y))
            w = max(1, min(iw - x, w))
            h = max(1, min(ih - y, h))
        return x, y, w, h

    def embedding(self, image: np.ndarray, face: np.ndarray) -> np.ndarray:
        with self._recognizer_lock:
            self.ensure()
            info = self.illumination(image)
            source = self.enhance(image) if info["brightness"] < 82 else image
            aligned = self._recognizer.alignCrop(source, face)
            feat = self._recognizer.feature(aligned).flatten().astype(np.float32)
            norm = float(np.linalg.norm(feat))
            return feat / max(norm, 1e-8)

    @staticmethod
    def pose(face: np.ndarray) -> tuple[str, float, float]:
        pts = np.asarray(face[4:14], dtype=np.float32).reshape(5, 2)
        eye_mid = (pts[0] + pts[1]) * 0.5
        mouth_mid = (pts[3] + pts[4]) * 0.5
        eye_dist = max(1.0, float(np.linalg.norm(pts[0] - pts[1])))
        vertical = max(1.0, float(mouth_mid[1] - eye_mid[1]))
        yaw = float((pts[2][0] - eye_mid[0]) / eye_dist)
        nose_y_ratio = float((pts[2][1] - eye_mid[1]) / vertical)
        pitch = nose_y_ratio - 0.52
        if yaw < -0.14:
            label = "left"
        elif yaw > 0.14:
            label = "right"
        elif pitch < -0.11:
            label = "up"
        elif pitch > 0.12:
            label = "down"
        else:
            label = "center"
        return label, yaw, pitch

    @staticmethod
    def quality(image: np.ndarray, face: np.ndarray) -> dict:
        x, y, w, h = FaceCore.bbox(face, image.shape)
        crop = image[y:y + h, x:x + w]
        if crop.size == 0:
            return {"score": 0.0, "sharpness": 0.0, "brightness": 0.0, "contrast": 0.0, "face_px": 0}
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright = float(np.mean(gray))
        contrast = float(np.std(gray))
        conf = float(face[14]) if len(face) > 14 else 0.5
        face_px = int(min(w, h))
        size_score = min(1.0, face_px / 145.0)
        sharp_score = min(1.0, math.log1p(max(0.0, sharp)) / math.log1p(180.0))
        light_score = max(0.0, 1.0 - abs(bright - 128.0) / 128.0)
        contrast_score = min(1.0, contrast / 52.0)
        score = 0.33 * size_score + 0.27 * sharp_score + 0.22 * conf + 0.10 * light_score + 0.08 * contrast_score
        return {
            "score": round(float(score), 4),
            "sharpness": round(sharp, 2),
            "brightness": round(bright, 1),
            "contrast": round(contrast, 1),
            "face_px": face_px,
            "detector_confidence": round(conf, 4),
            "usable": bool(face_px >= FACE_MIN_PX and conf >= 0.45),
        }

    def observe(self, image: np.ndarray, face: np.ndarray, *, with_embedding: bool = True) -> FaceObservation:
        """Build a face observation.

        V1.6 separates cheap detection/tracking metadata from expensive identity
        embedding extraction. Classroom mode creates observations without SFace
        embeddings for every face, then requests an embedding only for tracks that
        actually need identity work.
        """
        q = self.quality(image, face)
        pose, yaw, pitch = self.pose(face)
        emb = self.embedding(image, face) if with_embedding else None
        return FaceObservation(face, self.bbox(face, image.shape), emb, q, pose, yaw, pitch)

    @staticmethod
    def face_crop(image: np.ndarray, bbox: tuple[int, int, int, int], pad: float = 0.30) -> np.ndarray:
        x, y, w, h = bbox
        ih, iw = image.shape[:2]
        px, py = int(w * pad), int(h * pad)
        x1, y1 = max(0, x - px), max(0, y - py)
        x2, y2 = min(iw, x + w + px), min(ih, y + h + py)
        return image[y1:y2, x1:x2].copy()


CORE = FaceCore()

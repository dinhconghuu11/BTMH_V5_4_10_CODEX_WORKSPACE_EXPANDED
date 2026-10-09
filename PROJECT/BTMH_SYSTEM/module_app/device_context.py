from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .gpu_manager import ultralytics_device
from .config import (
    DEVICE_CONTEXT_ENABLED,
    DEVICE_CONTEXT_MODEL,
    DEVICE_CONTEXT_CONF,
    DEVICE_CONTEXT_IMGSZ,
    DEVICE_CONTEXT_INTERVAL_SEC,
)


@dataclass
class DeviceEvidence:
    risk: float = 0.0
    hard: bool = False
    reason: str = ""
    source: str = "none"
    device: str = ""
    confidence: float = 0.0
    inside_ratio: float = 0.0
    geometry_score: float = 0.0
    box: tuple[int, int, int, int] | None = None
    signals: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "risk": round(float(self.risk), 4),
            "hard": bool(self.hard),
            "reason": str(self.reason or ""),
            "source": str(self.source or "none"),
            "device": str(self.device or ""),
            "confidence": round(float(self.confidence), 4),
            "inside_ratio": round(float(self.inside_ratio), 4),
            "geometry_score": round(float(self.geometry_score), 4),
            "box": list(self.box) if self.box is not None else None,
            "signals": dict(self.signals or {}),
        }


class DeviceContextEngine:
    """Full-frame device/screen context detector used before FaceID.

    Preferred path: an optional local YOLO COCO detector (yolo11n/yolov8n) detects
    cell phones, laptops and TVs.  The runtime never downloads a model itself.
    If a model isn't present, a strict OpenCV geometry fallback still looks for a
    phone/photo-like carrier that *contains* the face.

    This class deliberately never blocks merely because a phone exists somewhere in
    the frame.  A device must contain most of the detected face or the fallback must
    find a strong screen/photo carrier around that face.
    """

    DEVICE_NAMES = {
        "cell phone": 1.00,
        "mobile phone": 1.00,
        "phone": 1.00,
        "tv": 0.92,
        "monitor": 0.92,
        "laptop": 0.88,
        "tablet": 0.95,
    }

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model = None
        self._model_attempted = False
        self._cache_at = 0.0
        self._cache_shape: tuple[int, int] = (0, 0)
        self._cache: list[dict[str, Any]] = []

    @staticmethod
    def _intersection_over_face(face, carrier) -> float:
        fx, fy, fw, fh = [float(v) for v in face]
        cx, cy, cw, ch = [float(v) for v in carrier]
        x1 = max(fx, cx)
        y1 = max(fy, cy)
        x2 = min(fx + fw, cx + cw)
        y2 = min(fy + fh, cy + ch)
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        return inter / max(1.0, fw * fh)

    @staticmethod
    def _contains_center(face, carrier) -> bool:
        fx, fy, fw, fh = [float(v) for v in face]
        cx, cy, cw, ch = [float(v) for v in carrier]
        px, py = fx + fw * 0.5, fy + fh * 0.5
        return cx <= px <= cx + cw and cy <= py <= cy + ch

    def _ensure_model(self):
        if self._model_attempted:
            return self._model
        self._model_attempted = True
        if not DEVICE_CONTEXT_ENABLED or not Path(DEVICE_CONTEXT_MODEL).exists():
            return None
        try:
            from ultralytics import YOLO  # optional; installer does not require it
            self._model = YOLO(str(DEVICE_CONTEXT_MODEL))
        except Exception:
            self._model = None
        return self._model

    def _detect_devices_yolo(self, image: np.ndarray, now: float) -> list[dict[str, Any]]:
        model = self._ensure_model()
        if model is None:
            return []
        h, w = image.shape[:2]
        with self._lock:
            if (
                self._cache
                and now - self._cache_at < DEVICE_CONTEXT_INTERVAL_SEC
                and self._cache_shape == (w, h)
            ):
                return list(self._cache)
        try:
            results = model.predict(
                source=image,
                conf=float(DEVICE_CONTEXT_CONF),
                imgsz=int(DEVICE_CONTEXT_IMGSZ),
                verbose=False,
                max_det=30,
                classes=None,
                device=ultralytics_device(),
            )
        except Exception:
            return []
        found: list[dict[str, Any]] = []
        if results:
            r = results[0]
            boxes = getattr(r, "boxes", None)
            names = getattr(r, "names", {}) or {}
            if boxes is not None and getattr(boxes, "xyxy", None) is not None:
                try:
                    xyxy = boxes.xyxy.cpu().numpy()
                    confs = boxes.conf.cpu().numpy()
                    classes = boxes.cls.cpu().numpy().astype(int)
                except Exception:
                    xyxy = np.asarray(boxes.xyxy)
                    confs = np.asarray(boxes.conf)
                    classes = np.asarray(boxes.cls).astype(int)
                for b, conf, cid in zip(xyxy, confs, classes):
                    name = str(names.get(int(cid), cid)).lower().strip()
                    if name not in self.DEVICE_NAMES:
                        continue
                    x1, y1, x2, y2 = [float(v) for v in b]
                    found.append({
                        "name": name,
                        "confidence": float(conf),
                        "box": (int(round(x1)), int(round(y1)), max(1, int(round(x2 - x1))), max(1, int(round(y2 - y1)))),
                    })
        with self._lock:
            self._cache_at = now
            self._cache_shape = (w, h)
            self._cache = list(found)
        return found

    def detect_devices(self, image: np.ndarray, *, now: float | None = None) -> list[dict[str, Any]]:
        """Return object-detector device boxes without applying anti-spoof policy.

        Identity/PAD can use this optional context signal to reject screen/photo replay artifacts.
        Only the local YOLO object detector is exposed here; the geometry fallback is
        intentionally excluded because a rectangular classroom object is not enough
        evidence that a student is using a phone.
        """
        if not DEVICE_CONTEXT_ENABLED or image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return []
        ts = float(time.time() if now is None else now)
        return [dict(x) for x in self._detect_devices_yolo(image, ts)]

    @staticmethod
    def _edge_strip_score(edges: np.ndarray, box: tuple[int, int, int, int]) -> float:
        x, y, w, h = box
        ih, iw = edges.shape[:2]
        if w < 8 or h < 8:
            return 0.0
        t = max(2, int(round(min(w, h) * 0.025)))
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(iw, x + w), min(ih, y + h)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        strips = [
            edges[y1:min(y2, y1 + t), x1:x2],
            edges[max(y1, y2 - t):y2, x1:x2],
            edges[y1:y2, x1:min(x2, x1 + t)],
            edges[y1:y2, max(x1, x2 - t):x2],
        ]
        vals = []
        for s in strips:
            if s.size:
                vals.append(float(np.count_nonzero(s)) / float(s.size))
        if not vals:
            return 0.0
        # Borders don't need every pixel to be edge; 8-15% is already meaningful.
        return float(min(1.0, np.mean(vals) / 0.11))

    @staticmethod
    def _ring_contrast(gray: np.ndarray, box: tuple[int, int, int, int]) -> float:
        x, y, w, h = box
        ih, iw = gray.shape[:2]
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(iw, x + w), min(ih, y + h)
        if x2 - x1 < 10 or y2 - y1 < 10:
            return 0.0
        inner = gray[y1:y2, x1:x2]
        pad = max(4, int(round(min(w, h) * 0.08)))
        ox1, oy1 = max(0, x1 - pad), max(0, y1 - pad)
        ox2, oy2 = min(iw, x2 + pad), min(ih, y2 + pad)
        outer = gray[oy1:oy2, ox1:ox2]
        if outer.size <= inner.size:
            return 0.0
        mask = np.ones(outer.shape, dtype=np.uint8)
        iy1, ix1 = y1 - oy1, x1 - ox1
        mask[iy1:iy1 + inner.shape[0], ix1:ix1 + inner.shape[1]] = 0
        ring = outer[mask.astype(bool)]
        if not ring.size:
            return 0.0
        diff = abs(float(np.mean(inner)) - float(np.mean(ring)))
        return float(min(1.0, diff / 42.0))

    @staticmethod
    def _line_enclosure_score(edges: np.ndarray, face: tuple[int, int, int, int]) -> tuple[float, dict[str, int]]:
        fx, fy, fw, fh = [float(v) for v in face]
        ih, iw = edges.shape[:2]
        px = int(max(40, fw * 2.6))
        py = int(max(50, fh * 2.6))
        x1 = max(0, int(fx + fw * 0.5 - px))
        x2 = min(iw, int(fx + fw * 0.5 + px))
        y1 = max(0, int(fy + fh * 0.5 - py))
        y2 = min(ih, int(fy + fh * 0.5 + py))
        roi = edges[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0, {"left": 0, "right": 0, "top": 0, "bottom": 0}
        lines = cv2.HoughLinesP(
            roi,
            1,
            np.pi / 180.0,
            threshold=max(24, int(min(roi.shape[:2]) * 0.085)),
            minLineLength=max(36, int(min(fw, fh) * 0.62)),
            maxLineGap=max(16, int(min(fw, fh) * 0.24)),
        )
        hits = {"left": 0, "right": 0, "top": 0, "bottom": 0}
        if lines is None:
            return 0.0, hits
        fl = fx - x1
        fr = fx + fw - x1
        ft = fy - y1
        fb = fy + fh - y1
        for raw in lines[:, 0]:
            lx1, ly1, lx2, ly2 = [float(v) for v in raw]
            dx, dy = lx2 - lx1, ly2 - ly1
            length = math.hypot(dx, dy)
            if length <= 1:
                continue
            mx, my = (lx1 + lx2) * 0.5, (ly1 + ly2) * 0.5
            if abs(dx) <= max(4.0, abs(dy) * 0.34) and length >= fh * 0.50:
                if fl - 3.4 * fw <= mx <= fl - 0.12 * fw:
                    hits["left"] += 1
                if fr + 0.12 * fw <= mx <= fr + 3.4 * fw:
                    hits["right"] += 1
            if abs(dy) <= max(4.0, abs(dx) * 0.34) and length >= fw * 0.72:
                if ft - 3.5 * fh <= my <= ft - 0.10 * fh:
                    hits["top"] += 1
                if fb + 0.10 * fh <= my <= fb + 2.8 * fh:
                    hits["bottom"] += 1
        sides = sum(1 for k in hits if hits[k] > 0)
        opposite = (hits["left"] > 0 and hits["right"] > 0) or (hits["top"] > 0 and hits["bottom"] > 0)
        if sides >= 4:
            score = 1.0
        elif sides == 3 and opposite:
            score = 0.90
        elif sides == 3:
            score = 0.80
        elif sides == 2 and opposite:
            score = 0.72
        elif sides == 2:
            score = 0.52
        else:
            score = 0.0
        return score, hits


    @staticmethod
    def _projection_enclosure_score(gray: np.ndarray, face: tuple[int, int, int, int]) -> tuple[float, dict[str, float]]:
        """Find phone/screen edges using gradient projections around the face.

        This catches partial devices whose bottom or one corner is outside the camera
        frame.  It requires *both* vertical carrier sides near the face, which avoids
        treating ordinary classroom walls/doors as a device.
        """
        fx, fy, fw, fh = [int(v) for v in face]
        ih, iw = gray.shape[:2]
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        gx = np.abs(cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3))
        gy = np.abs(cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3))
        x0 = max(0, int(fx - 2.4 * fw)); x3 = min(iw, int(fx + fw + 2.4 * fw))
        y0 = max(0, int(fy - 2.5 * fh)); y3 = min(ih, int(fy + fh + 1.5 * fh))
        if x3 - x0 < 20 or y3 - y0 < 20:
            return 0.0, {}
        roi_x = gx[y0:y3, x0:x3]
        roi_y = gy[y0:y3, x0:x3]
        tx = max(8.0, float(np.percentile(roi_x, 86)))
        ty = max(8.0, float(np.percentile(roi_y, 86)))

        def best_vertical(a: float, b: float):
            a = max(x0, int(a)); b = min(x3, int(b))
            if b <= a:
                return 0.0, -1
            sub = gx[y0:y3, a:b]
            density = (sub > tx).mean(axis=0)
            idx = int(np.argmax(density))
            return float(density[idx]), a + idx

        def best_horizontal(a: float, b: float):
            a = max(y0, int(a)); b = min(y3, int(b))
            if b <= a:
                return 0.0, -1
            sub = gy[a:b, x0:x3]
            density = (sub > ty).mean(axis=1)
            idx = int(np.argmax(density))
            return float(density[idx]), a + idx

        ld, lx = best_vertical(fx - 1.8 * fw, fx - 0.10 * fw)
        rd, rx = best_vertical(fx + fw + 0.10 * fw, fx + fw + 1.8 * fw)
        td, typos = best_horizontal(fy - 2.2 * fh, fy - 0.10 * fh)
        bd, by = best_horizontal(fy + fh + 0.10 * fh, fy + fh + 1.2 * fh)
        left_gap = (fx - lx) / max(1.0, fw) if lx >= 0 else 99.0
        right_gap = (rx - (fx + fw)) / max(1.0, fw) if rx >= 0 else 99.0
        top_gap = (fy - typos) / max(1.0, fh) if typos >= 0 else 99.0
        bottom_gap = (by - (fy + fh)) / max(1.0, fh) if by >= 0 else 99.0
        left_ok = ld >= 0.24 and 0.08 <= left_gap <= 1.8
        right_ok = rd >= 0.24 and 0.08 <= right_gap <= 1.8
        top_ok = td >= 0.18 and 0.08 <= top_gap <= 2.2
        bottom_ok = bd >= 0.18 and 0.08 <= bottom_gap <= 1.2
        score = 0.0
        if left_ok and right_ok:
            score = 0.78
            score += 0.12 if (top_ok or bottom_ok) else 0.0
            score += 0.06 if (top_ok and bottom_ok) else 0.0
            score += 0.04 * min(1.0, (ld + rd) / 1.0)
        elif (left_ok or right_ok) and top_ok and bottom_ok:
            score = 0.60
        details = {
            'proj_left_density': round(ld,4), 'proj_right_density': round(rd,4),
            'proj_top_density': round(td,4), 'proj_bottom_density': round(bd,4),
            'proj_left_gap': round(left_gap,4), 'proj_right_gap': round(right_gap,4),
            'proj_top_gap': round(top_gap,4), 'proj_bottom_gap': round(bottom_gap,4),
        }
        return float(min(1.0, score)), details

    def _geometry_carrier(self, image: np.ndarray, face: tuple[int, int, int, int]) -> DeviceEvidence:
        ih, iw = image.shape[:2]
        fx, fy, fw, fh = [int(v) for v in face]
        face_area = float(max(1, fw * fh))
        if fw < 18 or fh < 18:
            return DeviceEvidence(source="geometry")

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 36, 118)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

        best_score = 0.0
        best_box = None
        best_parts: dict[str, float] = {}
        masks: list[np.ndarray] = [edges]
        # Bright/dark screen panels create useful boundaries even when Canny misses
        # one side.  These masks are only proposal generators; final scoring still
        # requires face containment + rectangle/edge evidence.
        for p in (58, 68, 78):
            thr = float(np.percentile(gray, p))
            _, m = cv2.threshold(gray, thr, 255, cv2.THRESH_BINARY)
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8), iterations=2)
            masks.append(m)

        for mask in masks:
            contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = float(abs(cv2.contourArea(cnt)))
                if area < face_area * 1.45 or area > float(iw * ih) * 0.58:
                    continue
                x, y, w, h = cv2.boundingRect(cnt)
                carrier = (x, y, w, h)
                frame_cover = float(w * h) / max(1.0, float(iw * ih))
                if frame_cover > 0.52:
                    continue
                inside = self._intersection_over_face(face, carrier)
                if inside < 0.74 or not self._contains_center(face, carrier):
                    continue
                ratio = float(w * h) / face_area
                if ratio < 1.55 or ratio > 14.0:
                    continue
                aspect = w / max(1.0, float(h))
                if aspect < 0.34 or aspect > 2.65:
                    continue
                face_fill = face_area / max(1.0, float(w * h))
                # At least two carrier margins should be visible around the face.
                ml = (fx - x) / max(1.0, fw)
                mr = (x + w - (fx + fw)) / max(1.0, fw)
                mt = (fy - y) / max(1.0, fh)
                mb = (y + h - (fy + fh)) / max(1.0, fh)
                visible_margins = sum(1 for m in (ml, mr, mt, mb) if m >= 0.12)
                if visible_margins < 2:
                    continue
                contour_rect = min(1.0, area / max(1.0, float(w * h)))
                border = self._edge_strip_score(edges, carrier)
                contrast = self._ring_contrast(gray, carrier)
                size_term = min(1.0, max(0.0, (ratio - 1.55) / 4.4))
                separation = min(1.0, max(0.0, (0.72 - face_fill) / 0.58))
                margin_term = min(1.0, visible_margins / 4.0)
                score = (
                    0.24 * border
                    + 0.18 * contrast
                    + 0.18 * contour_rect
                    + 0.16 * size_term
                    + 0.14 * separation
                    + 0.10 * margin_term
                )
                # Portrait/landscape device-like proportions are a modest bonus.
                if 0.42 <= aspect <= 0.92 or 1.08 <= aspect <= 2.25:
                    score += 0.08
                if ratio >= 3.0 and inside >= 0.92 and visible_margins >= 3:
                    score += 0.08
                score = float(min(1.0, score))
                if score > best_score:
                    best_score = score
                    best_box = carrier
                    best_parts = {
                        "inside": inside,
                        "ratio": ratio,
                        "aspect": aspect,
                        "border": border,
                        "contrast": contrast,
                        "rectangularity": contour_rect,
                        "visible_margins": float(visible_margins),
                        "frame_cover": float(frame_cover),
                        "face_fill": float(face_fill),
                    }

        line_score, hits = self._line_enclosure_score(edges, face)
        projection_score, projection_signals = self._projection_enclosure_score(gray, face)
        # Screen/phone evidence is stronger when both a rectangular proposal and
        # independent long-line enclosure agree.  A 3-4 sided enclosure alone is
        # also enough to enter SUSPECT state, not immediate hard block.
        if best_box is None:
            # Projection-only evidence is not enough to block: a real face may be
            # seated in front of chair/window edges.  Use it only as a weak SUSPECT
            # hint unless an actual carrier rectangle is also found.
            combined = max(0.15 * line_score, 0.18 * projection_score)
        else:
            combined = max(best_score, 0.82 * projection_score, 0.62 * best_score + 0.28 * line_score + 0.24 * projection_score)
        combined = float(min(1.0, combined))
        # Built-in carrier detector used when the optional PAD/YOLO models are not
        # available.  A hard result requires a *closed, phone/photo-like carrier*
        # around almost the entire face.  Long lines/projection evidence alone never
        # hard-block because classroom windows/chairs can create similar geometry.
        aspect = float(best_parts.get("aspect", 0.0))
        ratio = float(best_parts.get("ratio", 0.0))
        inside = float(best_parts.get("inside", 0.0))
        border = float(best_parts.get("border", 0.0))
        contrast = float(best_parts.get("contrast", 0.0))
        rectangularity = float(best_parts.get("rectangularity", 0.0))
        margins = float(best_parts.get("visible_margins", 0.0))
        frame_cover = float(best_parts.get("frame_cover", 1.0))
        phone_like_aspect = (0.42 <= aspect <= 0.92) or (1.08 <= aspect <= 1.85)
        strict_carrier = bool(
            best_box is not None
            and inside >= 0.92
            and 1.75 <= ratio <= 8.5
            and margins >= 3.0
            and border >= 0.44
            and contrast >= 0.30
            and rectangularity >= 0.58
            and frame_cover <= 0.48
            and phone_like_aspect
        )
        if strict_carrier:
            combined = max(combined, 0.94)
        else:
            combined = float(min(combined, 0.58))
        hard = bool(strict_carrier)
        reason = "FACE_INSIDE_PHONE_OR_PHOTO" if hard else ("SCREEN_GEOMETRY_HINT" if combined >= 0.46 else "")
        source = "geometry_carrier" if hard else "geometry_hint"
        signals = dict(best_parts)
        signals.update({"line_score": round(line_score, 4), "projection_score": round(projection_score,4), "strict_carrier": bool(strict_carrier), **projection_signals, **{f"line_{k}": v for k, v in hits.items()}})
        return DeviceEvidence(
            risk=combined,
            hard=hard,
            reason=reason,
            source=source,
            device="phone/photo-carrier" if hard else ("screen/photo-hint" if combined >= 0.46 else ""),
            confidence=combined,
            inside_ratio=inside,
            geometry_score=combined,
            box=best_box,
            signals=signals,
        )

    def evaluate_face(self, image: np.ndarray, face_box, *, now: float | None = None) -> DeviceEvidence:
        now = float(now or time.time())
        face = tuple(int(v) for v in face_box)
        # 1) Real object detector when a local model is available.
        yolo_best: DeviceEvidence | None = None
        for obj in self._detect_devices_yolo(image, now):
            box = tuple(int(v) for v in obj["box"])
            inside = self._intersection_over_face(face, box)
            if inside < 0.42 or not self._contains_center(face, box):
                continue
            name = str(obj["name"])
            conf = float(obj["confidence"])
            weight = float(self.DEVICE_NAMES.get(name, 0.85))
            # Containment is more important than raw detector confidence: a phone in
            # someone's hand next to their real face must not be blocked.
            risk = min(1.0, (0.62 * inside + 0.38 * conf) * weight + (0.10 if inside >= 0.82 else 0.0))
            hard = bool(inside >= 0.72 and conf >= 0.30 and name in {"cell phone", "mobile phone", "phone", "tablet"})
            ev = DeviceEvidence(
                risk=float(risk),
                hard=hard,
                reason="FACE_INSIDE_PHONE_SCREEN" if hard else "FACE_OVERLAPS_DEVICE",
                source="yolo",
                device=name,
                confidence=conf,
                inside_ratio=inside,
                geometry_score=0.0,
                box=box,
                signals={"detector": "YOLO", "containment": round(inside, 4)},
            )
            if yolo_best is None or ev.risk > yolo_best.risk:
                yolo_best = ev

        # 2) Geometry fallback is deliberately non-blocking. It may hold FaceID in
        # CHECKING while PAD gathers frames, but it cannot label a real student as
        # spoof by itself. This is the key false-positive fix for classroom scenes.
        geo = self._geometry_carrier(image, face)
        if yolo_best is None:
            return geo
        if yolo_best.hard:
            yolo_best.geometry_score = geo.geometry_score
            yolo_best.risk = float(max(yolo_best.risk, geo.risk * 0.35))
            yolo_best.signals["geometry_risk"] = round(geo.risk, 4)
            return yolo_best
        fused = float(min(0.82, max(yolo_best.risk, 0.72 * yolo_best.risk + 0.24 * geo.risk)))
        yolo_best.risk = fused
        yolo_best.geometry_score = geo.geometry_score
        yolo_best.hard = False
        yolo_best.signals["geometry_risk"] = round(geo.risk, 4)
        return yolo_best


DEVICE_CONTEXT = DeviceContextEngine()

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "training" / "farface_dataset"
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def check_split(split: str) -> tuple[int, int, list[str]]:
    images_dir = DATA / "images" / split
    labels_dir = DATA / "labels" / split
    images = [p for p in images_dir.iterdir() if p.suffix.lower() in EXTS] if images_dir.exists() else []
    boxes = 0
    errors: list[str] = []
    for img in images:
        label = labels_dir / f"{img.stem}.txt"
        if not label.exists():
            errors.append(f"{split}: missing label for {img.name}")
            continue
        for line_no, raw in enumerate(label.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 5:
                errors.append(f"{label.name}:{line_no}: expected 5 values, got {len(parts)}")
                continue
            try:
                cls = int(float(parts[0])); vals = [float(v) for v in parts[1:]]
            except ValueError:
                errors.append(f"{label.name}:{line_no}: non-numeric label")
                continue
            if cls != 0:
                errors.append(f"{label.name}:{line_no}: class must be 0 (face)")
            if any(v <= 0 or v > 1 for v in vals[2:]) or any(v < 0 or v > 1 for v in vals[:2]):
                errors.append(f"{label.name}:{line_no}: bbox values must be normalized 0..1")
            boxes += 1
    return len(images), boxes, errors


def main() -> int:
    print("=== CampusFace FarFace YOLO dataset audit ===")
    total_images = total_boxes = 0
    errors: list[str] = []
    for split in ("train", "val"):
        images, boxes, split_errors = check_split(split)
        total_images += images; total_boxes += boxes; errors.extend(split_errors)
        print(f"[{split}] images={images} boxes={boxes} errors={len(split_errors)}")
    if total_images == 0:
        print("[STOP] Dataset is empty. Add real camera images before training.")
        return 2
    if total_boxes == 0:
        print("[STOP] No face boxes found.")
        return 3
    if errors:
        for item in errors[:40]: print("[ERROR]", item)
        if len(errors) > 40: print(f"... {len(errors)-40} more errors")
        return 4
    print("[OK] Dataset structure and YOLO face boxes are valid.")
    print("[NOTE] Include far/small faces, left/right profiles, up/down, low light and motion blur from the target camera.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

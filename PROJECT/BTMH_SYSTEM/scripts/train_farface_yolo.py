from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_args():
    p = argparse.ArgumentParser(description="Train a one-class YOLO face proposal detector for CampusFace FarFace")
    p.add_argument("--model", default=str(ROOT / "training" / "base_models" / "yolo26n.pt"), help="YOLO26 pretrained .pt path")
    p.add_argument("--data", default=str(ROOT / "training" / "farface_dataset" / "data.yaml"))
    p.add_argument("--epochs", type=int, default=160)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--batch", default="-1", help="batch size or -1 for auto")
    p.add_argument("--device", default="", help="e.g. 0, cpu; empty lets Ultralytics decide")
    p.add_argument("--workers", type=int, default=4)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    model_path = Path(args.model)
    if not model_path.exists():
        print("[STOP] Base YOLO26 model not found:", model_path)
        print("Put yolo26n.pt into training/base_models or pass --model <path>.")
        return 2
    data_path = Path(args.data)
    if not data_path.exists():
        print("[STOP] Dataset YAML not found:", data_path)
        return 3
    try:
        from ultralytics import YOLO
    except Exception as exc:
        print("[STOP] Ultralytics training environment is not installed:", exc)
        return 4
    batch = int(args.batch) if str(args.batch).lstrip("-").isdigit() else args.batch
    kwargs = dict(
        data=str(data_path),
        epochs=max(1, args.epochs),
        imgsz=max(640, args.imgsz),
        batch=batch,
        workers=max(0, args.workers),
        project=str(ROOT / "training" / "runs"),
        name="campusface_farface",
        exist_ok=True,
        patience=35,
        close_mosaic=12,
        degrees=8.0,
        translate=0.10,
        scale=0.45,
        fliplr=0.5,
        mosaic=0.8,
        mixup=0.05,
        plots=True,
    )
    if args.device:
        kwargs["device"] = args.device
    print("[TRAIN] model:", model_path)
    print("[TRAIN] data:", data_path)
    model = YOLO(str(model_path))
    result = model.train(**kwargs)
    save_dir = Path(getattr(result, "save_dir", ROOT / "training" / "runs" / "campusface_farface"))
    best = save_dir / "weights" / "best.pt"
    if not best.exists():
        print("[STOP] Training completed but best.pt was not found at", best)
        return 5
    target = ROOT / "models" / "campusface-face-yolo.pt"
    shutil.copy2(best, target)
    print("[OK] CampusFace FarFace model copied to:", target)
    print("[IMPORTANT] YOLO detects/proposes far faces; SFace remains the identity recognizer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

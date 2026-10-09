from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []

# Local configuration may contain camera/IP/path choices from the build machine.
if (ROOT / "module.env").exists():
    errors.append("module.env exists; ship module.env.example instead")

for folder_name in ("data", "logs", "backups"):
    folder = ROOT / folder_name
    if not folder.exists():
        continue
    for path in folder.rglob("*"):
        if path.is_file() and path.name != ".gitkeep":
            errors.append(f"runtime artifact in {path.relative_to(ROOT)}")

# Never package real training images/labels into a customer deployment bundle.
dataset = ROOT / "training" / "farface_dataset"
if dataset.exists():
    for path in dataset.rglob("*"):
        if path.is_file() and path.name not in {".gitkeep", "data.yaml"}:
            errors.append(f"training dataset content in {path.relative_to(ROOT)}")

skip_roots = {".venv", ".venv-training", "runtime", "vendor", "dist"}
for path in ROOT.rglob("*"):
    if not path.is_file():
        continue
    rel = path.relative_to(ROOT)
    if rel.parts and rel.parts[0] in skip_roots:
        continue
    if "__pycache__" in rel.parts:
        continue
    if path.suffix.lower() in {".db", ".key", ".log", ".cfacebak"}:
        marker = f"sensitive/generated file in {rel}"
        if marker not in errors:
            errors.append(marker)

if errors:
    print("[STOP] Release tree is not clean:")
    for item in sorted(set(errors)):
        print(" -", item)
    print("[ACTION] Move local data/training samples out of the source tree, then build again.")
    raise SystemExit(2)

print("[OK] Release tree is clean: no local DB/key/log/backup/training samples/module.env.")

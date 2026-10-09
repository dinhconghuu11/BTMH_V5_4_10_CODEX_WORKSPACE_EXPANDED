from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    from module_app.db import db_status
    print(json.dumps(db_status(), ensure_ascii=False))
except Exception as exc:
    print(f'[ERROR] {exc}')
    raise SystemExit(2)

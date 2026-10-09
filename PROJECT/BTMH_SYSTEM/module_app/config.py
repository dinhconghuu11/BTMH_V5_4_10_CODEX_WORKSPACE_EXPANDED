from __future__ import annotations

import os
from pathlib import Path
from .ui_preview import validated_preview

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Customer data is intentionally separated from the application/version folder.
# Fresh Windows installations use %LOCALAPPDATA%\CampusFace. Existing V1.14.x
# installations are detected and reused in-place so an upgrade never loses the
# customer's PostgreSQL cluster, FaceID templates, models or configuration.
def _windows_profile_root() -> Path:
    configured = os.getenv("CAMPUSFACE_DATA_ROOT", "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))
    local = Path(os.path.expandvars(r"%LOCALAPPDATA%"))
    stable = local / "CampusFace"
    legacy = local / "CampusFaceV1142"
    stable_markers = (stable / "config" / "module.env", stable / "PostgreSQL" / "data" / "PG_VERSION")
    legacy_markers = (legacy / "config" / "module.env", legacy / "PostgreSQL" / "data" / "PG_VERSION")
    if stable.exists() and any(x.exists() for x in stable_markers):
        return stable
    if legacy.exists() and any(x.exists() for x in legacy_markers):
        return legacy
    return stable


UI_PREVIEW = validated_preview()
if not UI_PREVIEW:
    if os.name == "nt":
        _bootstrap_data_root = _windows_profile_root()
    else:
        _bootstrap_data_root = BASE_DIR / ".campusface-data"
    _load_env_file(_bootstrap_data_root / "config" / "module.env")
    _load_env_file(BASE_DIR / "module.env")


def _expand_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


# Production data lives outside the application folder. New customer PCs get a
# version-independent profile. Existing V1.14.x PCs continue using their current
# profile until the operator explicitly migrates it.
if os.name == "nt":
    _default_data_root = _windows_profile_root()
else:
    _default_data_root = BASE_DIR / ".campusface-data"
DATA_ROOT = _expand_path(os.getenv("CAMPUSFACE_DATA_ROOT", str(_default_data_root)))
DATA_DIR = DATA_ROOT / "data"
MODELS_DIR = DATA_ROOT / "models"
LOG_DIR = DATA_ROOT / "logs"
BACKUP_DIR = DATA_ROOT / "backups"
CONFIG_DIR = DATA_ROOT / "config"
PHOTOS_DIR = DATA_ROOT / "Photos"
STUDENT_PHOTOS_DIR = PHOTOS_DIR / "Students"
EVENT_SNAPSHOTS_DIR = DATA_ROOT / "Snapshots"
TRAINING_DIR = DATA_ROOT / "training" if UI_PREVIEW else BASE_DIR / "training"
for folder in (DATA_DIR, MODELS_DIR, LOG_DIR, BACKUP_DIR, CONFIG_DIR, PHOTOS_DIR, STUDENT_PHOTOS_DIR, EVENT_SNAPSHOTS_DIR, TRAINING_DIR):
    folder.mkdir(parents=True, exist_ok=True)

APP_NAME = "Bảo Tín Mạnh Hải Security Management Platform"
APP_VERSION = "5.4.10-native-video-gateway"
# compatibility marker: 1.42.0-facev1.3.2-laptop-return-stable-fix
# compatibility marker: 1.41.0-facev1.3.1-enrollment-laptop-handover-fix
BUILD_FLAVOR = "BTMH Security V5 Production Preview - Windows"
# Compatibility lineage: 1.31.2-v1-face-pro-v14-2-camera-handover-recovery
# V1 FACE: passive anti-spoof is continuously re-evaluated before and after FaceID; PASS is revocable when phone/screen context appears.
# compatibility marker: 1.12.4-customer-safe-postgresql-production-ready
# Regression lineage markers retained for automated compatibility checks:
# 1.14.0-user-managed-postgresql
# 1.12.0-postgresql-offline-production-ready
# 1.4.0-static-camera-deployable
# 1.9.0-enterprise-production
# BTMH_OBSERVATION_FACE_AI_FPS", "4"
# BTMH_OBSERVATION_PREVIEW_FPS", "12"
# BTMH_OBSERVATION_PREVIEW_WIDTH", "800"
# BTMH_OBSERVATION_JPEG_QUALITY", "65"
# BTMH_OBSERVATION_FACE_AI_WIDTH", "960"
HOST = os.getenv("MODULE_HOST", "127.0.0.1")
PORT = int(os.getenv("MODULE_PORT", "8100"))
PROFILE = os.getenv("MODULE_PROFILE", "MAX").strip().upper()
if PROFILE not in {"FAST", "HIGH", "MAX"}:
    PROFILE = "MAX"

YUNET_MODEL = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
SFACE_MODEL = MODELS_DIR / "face_recognition_sface_2021dec.onnx"
CUSTOM_FACE_MODEL = MODELS_DIR / "campusface-face-yolo.pt"
DEVICE_CONTEXT_MODEL = MODELS_DIR / "yolo11n.pt"
PAD_MODEL_V2 = MODELS_DIR / "minifasnet_v2.onnx"
KEY_PATH = DATA_DIR / "face_templates.key"
SQLITE_PATH = DATA_DIR / "recognition_module.db"  # migration/test compatibility only
PG_SECRET_PATH = DATA_DIR / "postgres_app_password.dpapi"

# V1.12 production database. Runtime is still fully offline; PostgreSQL is local-only.
# SQLite remains available only when explicitly selected for tests/migration.
DB_MODE = os.getenv("CAMPUSFACE_DB_MODE", "postgres").strip().lower()
if DB_MODE not in {"postgres", "sqlite"}:
    DB_MODE = "postgres"
POSTGRES_HOST = os.getenv("CAMPUSFACE_POSTGRES_HOST", "127.0.0.1").strip()
POSTGRES_PORT = int(os.getenv("CAMPUSFACE_POSTGRES_PORT", "55442"))
POSTGRES_DB = os.getenv("CAMPUSFACE_POSTGRES_DB", "campusface").strip()
POSTGRES_USER = os.getenv("CAMPUSFACE_POSTGRES_USER", "campusface_app").strip()
POSTGRES_SSLMODE = os.getenv("CAMPUSFACE_POSTGRES_SSLMODE", "disable").strip()
POSTGRES_CONNECT_TIMEOUT = max(2, min(30, int(os.getenv("CAMPUSFACE_POSTGRES_CONNECT_TIMEOUT", "5"))))
POSTGRES_BIN = _expand_path(
    os.getenv(
        "CAMPUSFACE_POSTGRES_BIN",
        str(DATA_ROOT / "runtime" / "PostgreSQL17" / "bin")
        if os.name == "nt"
        else "/usr/bin",
    )
)

# The service owns the camera. The browser only renders a local MJPEG preview.
CAMERA_MODE = os.getenv("MODULE_CAMERA_MODE", "service").strip().lower()
CAMERA_SOURCE = os.getenv("MODULE_CAMERA_SOURCE", "0")
CAMERA_BACKEND = os.getenv("MODULE_CAMERA_BACKEND", "auto").strip().lower()
CAMERA_WIDTH = int(os.getenv("MODULE_CAMERA_WIDTH", "1920"))
CAMERA_HEIGHT = int(os.getenv("MODULE_CAMERA_HEIGHT", "1080"))
CAMERA_FPS = int(os.getenv("MODULE_CAMERA_FPS", "30"))
CAMERA_PREVIEW_FPS = int(os.getenv("MODULE_CAMERA_PREVIEW_FPS", "25"))
JPEG_QUALITY = int(os.getenv("MODULE_JPEG_QUALITY", "82"))
CAMERA_FOURCC = os.getenv("MODULE_CAMERA_FOURCC", "auto").strip().upper()
CAMERA_RECONNECT = os.getenv("MODULE_CAMERA_RECONNECT", "1").strip().lower() in {"1", "true", "yes", "on"}
CAMERA_FAIL_LIMIT = max(3, min(30, int(os.getenv("MODULE_CAMERA_FAIL_LIMIT", "8"))))
CAMERA_WARMUP_FRAMES = max(6, min(60, int(os.getenv("MODULE_CAMERA_WARMUP_FRAMES", "18"))))
CAMERA_AUTOFOCUS = os.getenv("MODULE_CAMERA_AUTOFOCUS", "1").strip().lower() in {"1", "true", "yes", "on"}
CAMERA_AUTO_EXPOSURE = os.getenv("MODULE_CAMERA_AUTO_EXPOSURE", "1").strip().lower() in {"1", "true", "yes", "on"}
# Camera-quality watchdog runs on a lightweight downscaled frame. It never blocks AI;
# it exposes actionable diagnostics so installers can fix blur/exposure before tuning FaceID.
CAMERA_QUALITY_INTERVAL_SEC = max(0.25, min(3.0, float(os.getenv("MODULE_CAMERA_QUALITY_INTERVAL_SEC", "0.65"))))
CAMERA_SHARPNESS_WARN = max(10.0, min(500.0, float(os.getenv("MODULE_CAMERA_SHARPNESS_WARN", "55"))))
CAMERA_SHARPNESS_GOOD = max(CAMERA_SHARPNESS_WARN + 5.0, min(1200.0, float(os.getenv("MODULE_CAMERA_SHARPNESS_GOOD", "105"))))
CAMERA_BRIGHTNESS_LOW = max(5.0, min(100.0, float(os.getenv("MODULE_CAMERA_BRIGHTNESS_LOW", "42"))))
CAMERA_BRIGHTNESS_HIGH = max(155.0, min(250.0, float(os.getenv("MODULE_CAMERA_BRIGHTNESS_HIGH", "218"))))
CAMERA_CONTRAST_WARN = max(5.0, min(80.0, float(os.getenv("MODULE_CAMERA_CONTRAST_WARN", "24"))))
CAMERA_MODE_ACCEPT_RATIO = max(0.60, min(0.98, float(os.getenv("MODULE_CAMERA_MODE_ACCEPT_RATIO", "0.82"))))

# V5.4.8 realtime policy for IP cameras.  The browser and AI do not need to
# consume every 1080p/25 frame.  RTSP capture is bounded before frames enter
# Python so a weak PC cannot accumulate latency in the decoder pipe.  USB
# cameras keep the legacy behaviour.  Operators can select quality/light via
# module.env without changing FaceID/PAD thresholds or models.
RTSP_REALTIME_PROFILE = os.getenv("BTMH_RTSP_REALTIME_PROFILE", "balanced").strip().lower()
if RTSP_REALTIME_PROFILE not in {"light", "balanced", "quality"}:
    RTSP_REALTIME_PROFILE = "balanced"
_RTSP_PROFILE_DEFAULTS = {
    "light":    {"capture_fps": 15, "max_width": 960,  "ai_fps": 5, "ai_width": 720,  "preview_fps": 12, "preview_width": 960,  "jpeg_quality": 74},
    "balanced": {"capture_fps": 18, "max_width": 1280, "ai_fps": 7, "ai_width": 960,  "preview_fps": 15, "preview_width": 1280, "jpeg_quality": 78},
    "quality":  {"capture_fps": 22, "max_width": 1920, "ai_fps": 8, "ai_width": 1280, "preview_fps": 18, "preview_width": 1440, "jpeg_quality": 82},
}
_RTP = _RTSP_PROFILE_DEFAULTS[RTSP_REALTIME_PROFILE]
RTSP_CAPTURE_FPS = max(5, min(30, int(os.getenv("BTMH_RTSP_CAPTURE_FPS", str(_RTP["capture_fps"])))) )
RTSP_CAPTURE_MAX_WIDTH = max(640, min(1920, int(os.getenv("BTMH_RTSP_CAPTURE_MAX_WIDTH", str(_RTP["max_width"])))) )
RTSP_AI_TARGET_FPS = max(2, min(12, int(os.getenv("BTMH_RTSP_AI_FPS", str(_RTP["ai_fps"])))) )
RTSP_AI_WIDTH = max(640, min(1600, int(os.getenv("BTMH_RTSP_AI_WIDTH", str(_RTP["ai_width"])))) )
# AI substream settings affect the private decoder only, never camera /101.
AI_ASYNC_ENABLED = os.getenv("BTMH_AI_ASYNC", "1").strip().lower() in {"1", "true", "yes", "on"}
ADAPTIVE_VIDEO_QUALITY = os.getenv("BTMH_ADAPTIVE_VIDEO_QUALITY", "1").strip().lower() in {"1", "true", "yes", "on"}
AI_SUBSTREAM_ENABLED = os.getenv("BTMH_AI_SUBSTREAM", "1").strip().lower() in {"1", "true", "yes", "on"}
AI_SUBSTREAM_CAPTURE_FPS = max(5, min(25, int(os.getenv("BTMH_AI_SUBSTREAM_CAPTURE_FPS", "12"))))
AI_SUBSTREAM_OPEN_TIMEOUT_SEC = max(1.0, min(15.0, float(os.getenv("BTMH_AI_SUBSTREAM_OPEN_TIMEOUT_SEC", "6"))))
AI_SUBSTREAM_MAX_AGE_SEC = max(0.15, min(1.5, float(os.getenv("BTMH_AI_SUBSTREAM_MAX_AGE_SEC", "0.75"))))
AI_EVIDENCE_SYNC_SEC = max(0.02, min(0.25, float(os.getenv("BTMH_AI_EVIDENCE_SYNC_SEC", "0.15"))))
RTSP_PREVIEW_FPS = max(8, min(24, int(os.getenv("BTMH_RTSP_PREVIEW_FPS", str(_RTP["preview_fps"])))) )
RTSP_PREVIEW_WIDTH = max(720, min(1920, int(os.getenv("BTMH_RTSP_PREVIEW_WIDTH", str(_RTP["preview_width"])))) )
RTSP_JPEG_QUALITY = max(65, min(90, int(os.getenv("BTMH_RTSP_JPEG_QUALITY", str(_RTP["jpeg_quality"])))) )

_PROFILE_DEFAULTS = {
    "FAST": {"ai_fps": 10, "ai_width": 720, "max_faces": 5, "long_every": 10, "min_face": 28},
    "HIGH": {"ai_fps": 13, "ai_width": 960, "max_faces": 8, "long_every": 7, "min_face": 24},
    "MAX":  {"ai_fps": 12, "ai_width": 1920, "max_faces": 10, "long_every": 5, "min_face": 22},
}
_PD = _PROFILE_DEFAULTS[PROFILE]
AI_TARGET_FPS = max(2, min(30, int(os.getenv("MODULE_AI_TARGET_FPS", str(_PD["ai_fps"])))))
AI_WIDTH = max(480, min(1920, int(os.getenv("MODULE_AI_WIDTH", str(_PD["ai_width"])))))
AI_NATIVE_FRAME = os.getenv("MODULE_AI_NATIVE_FRAME", "1" if PROFILE == "MAX" else "0").strip().lower() in {"1", "true", "yes", "on"}
AI_NATIVE_MAX_WIDTH = max(640, min(3840, int(os.getenv("MODULE_AI_NATIVE_MAX_WIDTH", "1920"))))
# V13 Performance Guard: keep realtime latency bounded by adapting inference cadence.
PERFORMANCE_GUARD_ENABLED = os.getenv("MODULE_PERFORMANCE_GUARD", "1").strip().lower() in {"1", "true", "yes", "on"}
PERFORMANCE_GUARD_MIN_FPS = max(2, min(8, int(os.getenv("MODULE_PERFORMANCE_GUARD_MIN_FPS", "3"))))
PERFORMANCE_GUARD_ADJUST_SEC = max(0.8, min(8.0, float(os.getenv("MODULE_PERFORMANCE_GUARD_ADJUST_SEC", "1.8"))))
PERFORMANCE_GUARD_RECOVER_SEC = max(1.0, min(15.0, float(os.getenv("MODULE_PERFORMANCE_GUARD_RECOVER_SEC", "3.0"))))
PERFORMANCE_GUARD_PTZ_HOLD_SEC = max(0.15, min(2.5, float(os.getenv("MODULE_PERFORMANCE_GUARD_PTZ_HOLD_SEC", "0.55"))))
MAX_FACES = max(1, min(64, int(os.getenv("MODULE_MAX_FACES", str(_PD["max_faces"])))))
LONG_RANGE_EVERY = max(2, min(30, int(os.getenv("MODULE_LONG_RANGE_EVERY", str(_PD["long_every"])))))
FACE_MIN_PX = max(16, int(os.getenv("MODULE_FACE_MIN_PX", str(_PD["min_face"]))))

FACE_DETECT_SCORE = float(os.getenv("MODULE_FACE_DETECT_SCORE", "0.62"))
FACE_LONG_RANGE_SCORE = float(os.getenv("MODULE_FACE_LONG_RANGE_SCORE", "0.46"))
FACE_NMS = float(os.getenv("MODULE_FACE_NMS", "0.30"))

ONE_SHOT_CONF = float(os.getenv("MODULE_ONE_SHOT_CONF", "0.72"))
ONE_SHOT_MARGIN = float(os.getenv("MODULE_ONE_SHOT_MARGIN", "0.12"))
TWO_SHOT_CONF = float(os.getenv("MODULE_TWO_SHOT_CONF", "0.56"))
TWO_SHOT_MARGIN = float(os.getenv("MODULE_TWO_SHOT_MARGIN", "0.055"))
THREE_SHOT_CONF = float(os.getenv("MODULE_THREE_SHOT_CONF", "0.50"))
THREE_SHOT_MARGIN = float(os.getenv("MODULE_THREE_SHOT_MARGIN", "0.04"))
UNKNOWN_MIN_SCORE = float(os.getenv("MODULE_UNKNOWN_MIN_SCORE", "0.43"))
MAX_SAMPLES_PER_TRACK = max(3, min(12, int(os.getenv("MODULE_MAX_SAMPLES", "6"))))
SAMPLE_MIN_GAP_SEC = max(0.02, min(0.5, float(os.getenv("MODULE_SAMPLE_MIN_GAP_SEC", "0.08"))))


DEVICE_CONTEXT_ENABLED = os.getenv("MODULE_DEVICE_CONTEXT", "1").strip().lower() in {"1", "true", "yes", "on"}
DEVICE_CONTEXT_CONF = max(0.15, min(0.80, float(os.getenv("MODULE_DEVICE_CONTEXT_CONF", "0.26"))))
DEVICE_CONTEXT_IMGSZ = max(416, min(960, int(os.getenv("MODULE_DEVICE_CONTEXT_IMGSZ", "640"))))
DEVICE_CONTEXT_INTERVAL_SEC = max(0.08, min(0.50, float(os.getenv("MODULE_DEVICE_CONTEXT_INTERVAL_SEC", "0.18"))))
DEVICE_CONTEXT_HARD_RISK = max(0.70, min(0.99, float(os.getenv("MODULE_DEVICE_CONTEXT_HARD_RISK", "0.88"))))
DEVICE_CONTEXT_SUSPECT_RISK = max(0.40, min(0.85, float(os.getenv("MODULE_DEVICE_CONTEXT_SUSPECT_RISK", "0.58"))))
# Core-stable fallback: the dedicated neural PAD model improves security when present,
# but it is no longer allowed to disable face detection/FaceID completely. A strict
# multi-frame phone/photo carrier detector remains active when PAD is unavailable.
PAD_REQUIRED = os.getenv("MODULE_PAD_REQUIRED", "0").strip().lower() in {"1", "true", "yes", "on"}
CONTEXT_FALLBACK_ENABLED = os.getenv("MODULE_CONTEXT_FALLBACK", "1").strip().lower() in {"1", "true", "yes", "on"}
CONTEXT_BLOCK_STREAK = max(2, min(5, int(os.getenv("MODULE_CONTEXT_BLOCK_STREAK", "2"))))
CONTEXT_PASS_STREAK = max(2, min(8, int(os.getenv("MODULE_CONTEXT_PASS_STREAK", "3"))))
CONTEXT_PASS_RISK_MAX = max(0.45, min(0.80, float(os.getenv("MODULE_CONTEXT_PASS_RISK_MAX", "0.66"))))
ANTI_SPOOF_RECOVERY_SEC = max(0.35, min(2.5, float(os.getenv("MODULE_ANTI_SPOOF_RECOVERY_SEC", "0.55"))))
ANTI_SPOOF_RECOVERY_CLEAN_FRAMES = max(2, min(12, int(os.getenv("MODULE_ANTI_SPOOF_RECOVERY_CLEAN_FRAMES", "3"))))
ANTI_SPOOF_RECOVERY_CONTEXT_MAX = max(0.15, min(0.55, float(os.getenv("MODULE_ANTI_SPOOF_RECOVERY_CONTEXT_MAX", "0.35"))))

PAD_ENABLED = os.getenv("MODULE_PAD_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
PAD_WINDOW = max(4, min(12, int(os.getenv("MODULE_PAD_WINDOW", "6"))))
PAD_MIN_OBS = max(3, min(PAD_WINDOW, int(os.getenv("MODULE_PAD_MIN_OBS", "4"))))
PAD_PASS_LIVE = max(0.55, min(0.98, float(os.getenv("MODULE_PAD_PASS_LIVE", "0.60"))))
PAD_STRONG_LIVE = max(PAD_PASS_LIVE, min(0.995, float(os.getenv("MODULE_PAD_STRONG_LIVE", "0.72"))))
PAD_SPOOF_BLOCK = max(0.60, min(0.99, float(os.getenv("MODULE_PAD_SPOOF_BLOCK", "0.82"))))
PAD_PASS_VOTES = max(2, min(PAD_WINDOW, int(os.getenv("MODULE_PAD_PASS_VOTES", "3"))))
PAD_BLOCK_VOTES = max(2, min(PAD_WINDOW, int(os.getenv("MODULE_PAD_BLOCK_VOTES", "3"))))

ANTI_SPOOF_ENABLED = os.getenv("MODULE_ANTI_SPOOF", "1").strip().lower() in {"1", "true", "yes", "on"}
ANTI_SPOOF_MODE = os.getenv("MODULE_ANTI_SPOOF_MODE", "passive").strip().lower()
if ANTI_SPOOF_MODE not in {"passive", "secure", "adaptive"}:
    ANTI_SPOOF_MODE = "passive"

QUICK_REARM_SEC = max(0.60, min(3.5, float(os.getenv("MODULE_QUICK_REARM_SEC", "2.60"))))
TRACK_TTL_SEC = max(1.0, min(8.0, float(os.getenv("MODULE_TRACK_TTL_SEC", "3.2"))))
TRACK_IOU_MIN = float(os.getenv("MODULE_TRACK_IOU_MIN", "0.03"))
TRACK_DIST_MAX = float(os.getenv("MODULE_TRACK_DIST_MAX", "2.4"))
# Periodic identity revalidation protects against name swaps when two tracked faces cross.
# It is deliberately budgeted and multi-frame: a single weak mismatch never changes identity.
IDENTITY_REVERIFY_SEC = max(0.35, min(3.0, float(os.getenv("MODULE_IDENTITY_REVERIFY_SEC", "1.20"))))
IDENTITY_REVERIFY_SCORE = max(0.45, min(0.95, float(os.getenv("MODULE_IDENTITY_REVERIFY_SCORE", "0.58"))))
IDENTITY_REVERIFY_MARGIN = max(0.02, min(0.30, float(os.getenv("MODULE_IDENTITY_REVERIFY_MARGIN", "0.055"))))
IDENTITY_REVERIFY_MISMATCHES = max(2, min(5, int(os.getenv("MODULE_IDENTITY_REVERIFY_MISMATCHES", "2"))))
IDENTITY_OWNER_GRACE_SEC = max(0.25, min(2.0, float(os.getenv("MODULE_IDENTITY_OWNER_GRACE_SEC", "0.75"))))

ENROLL_TARGET = max(8, min(12, int(os.getenv("MODULE_ENROLL_TARGET", "8"))))
ENROLL_MIN_TOTAL = max(8, min(16, int(os.getenv("MODULE_ENROLL_MIN_TOTAL", "8"))))
ENROLL_MIN_FACE_PX = max(48, int(os.getenv("MODULE_ENROLL_MIN_FACE_PX", "72")))
ENROLL_MIN_SHARPNESS = float(os.getenv("MODULE_ENROLL_MIN_SHARPNESS", "16"))
ENROLL_SAMPLE_GAP_SEC = max(0.12, min(0.7, float(os.getenv("MODULE_ENROLL_SAMPLE_GAP_SEC", "0.24"))))

_custom_yolo_mode = os.getenv("MODULE_USE_CUSTOM_FACE_YOLO", "auto").strip().lower()
USE_CUSTOM_FACE_YOLO = (_custom_yolo_mode in {"1", "true", "yes", "on"}) or (_custom_yolo_mode == "auto" and CUSTOM_FACE_MODEL.exists())
CUSTOM_YOLO_CONF = float(os.getenv("MODULE_CUSTOM_YOLO_CONF", "0.28"))
CUSTOM_YOLO_IMGSZ = int(os.getenv("MODULE_CUSTOM_YOLO_IMGSZ", "1280"))

# Identity-only observation lane. New BTMH_* names are preferred while the old
# MODULE_CLASSROOM_* environment names remain read-only fallbacks for upgrades.
def _obs_env(new_name: str, legacy_name: str, default: str) -> str:
    return os.getenv(new_name, os.getenv(legacy_name, default))

OBSERVATION_FACE_AI_FPS = max(2, min(12, int(_obs_env("BTMH_OBSERVATION_FACE_AI_FPS", "MODULE_CLASSROOM_FACE_AI_FPS", "8"))))
OBSERVATION_FACE_AI_WIDTH = max(640, min(1600, int(_obs_env("BTMH_OBSERVATION_FACE_AI_WIDTH", "MODULE_CLASSROOM_FACE_AI_WIDTH", "1280"))))
OBSERVATION_PREVIEW_FPS = max(10, min(30, int(_obs_env("BTMH_OBSERVATION_PREVIEW_FPS", "MODULE_CLASSROOM_PREVIEW_FPS", "25"))))
OBSERVATION_PREVIEW_WIDTH = max(720, min(1920, int(_obs_env("BTMH_OBSERVATION_PREVIEW_WIDTH", "MODULE_CLASSROOM_PREVIEW_WIDTH", "1920"))))
OBSERVATION_JPEG_QUALITY = max(75, min(95, int(_obs_env("BTMH_OBSERVATION_JPEG_QUALITY", "MODULE_CLASSROOM_JPEG_QUALITY", "92"))))
OBSERVATION_PREVIEW_ENHANCE = _obs_env("BTMH_OBSERVATION_PREVIEW_ENHANCE", "MODULE_CLASSROOM_PREVIEW_ENHANCE", "1").strip().lower() in {"1", "true", "yes", "on"}
OBSERVATION_PREVIEW_SHARPEN = max(0.0, min(0.40, float(_obs_env("BTMH_OBSERVATION_PREVIEW_SHARPEN", "MODULE_CLASSROOM_PREVIEW_SHARPEN", "0.18"))))
OBSERVATION_PREVIEW_CONTRAST = max(1.0, min(1.18, float(_obs_env("BTMH_OBSERVATION_PREVIEW_CONTRAST", "MODULE_CLASSROOM_PREVIEW_CONTRAST", "1.05"))))
OBSERVATION_PREVIEW_BRIGHTNESS_TARGET = max(96.0, min(170.0, float(_obs_env("BTMH_OBSERVATION_PREVIEW_BRIGHTNESS_TARGET", "MODULE_CLASSROOM_PREVIEW_BRIGHTNESS_TARGET", "130"))))
OBSERVATION_MAX_FACES = max(4, min(64, int(_obs_env("BTMH_OBSERVATION_MAX_FACES", "MODULE_CLASSROOM_MAX_FACES", "50"))))
OBSERVATION_IDENTITY_BUDGET = max(1, min(12, int(_obs_env("BTMH_OBSERVATION_IDENTITY_BUDGET", "MODULE_CLASSROOM_IDENTITY_BUDGET", "4"))))

STORE_SNAPSHOTS = os.getenv("MODULE_STORE_SNAPSHOTS", "0").strip().lower() in {"1", "true", "yes", "on"}


# V5 Edge -> Central synchronization. Disabled by default so a single-store/offline
# deployment remains fully local. Production remote sync requires HTTPS plus a
# per-device Ed25519 identity whose private key is protected by Windows DPAPI.
BTMH_EDGE_SYNC_ENABLED = os.getenv("BTMH_EDGE_SYNC_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
BTMH_CENTRAL_URL = os.getenv("BTMH_CENTRAL_URL", "").strip().rstrip("/")
BTMH_EDGE_NODE_ID = os.getenv("BTMH_EDGE_NODE_ID", "").strip()
BTMH_EDGE_NODE_NAME = os.getenv("BTMH_EDGE_NODE_NAME", "").strip()
try:
    BTMH_EDGE_STORE_ID = int(os.getenv("BTMH_EDGE_STORE_ID", "0") or 0)
except ValueError:
    BTMH_EDGE_STORE_ID = 0
BTMH_EDGE_SYNC_INTERVAL_SEC = max(2.0, min(120.0, float(os.getenv("BTMH_EDGE_SYNC_INTERVAL_SEC", "5"))))
BTMH_EDGE_SYNC_BATCH_SIZE = max(1, min(500, int(os.getenv("BTMH_EDGE_SYNC_BATCH_SIZE", "100"))))
BTMH_EDGE_SYNC_ALLOW_HTTP_DEV = os.getenv("BTMH_EDGE_SYNC_ALLOW_HTTP_DEV", "0").strip().lower() in {"1", "true", "yes", "on"}

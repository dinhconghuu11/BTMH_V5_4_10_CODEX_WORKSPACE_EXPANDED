"""Camera registry persistence guards introduced in BTMH 5.4.6.

The helpers in this module deliberately do not open a camera. They only compare
canonical registry values so connection edits can be verified independently of
FaceID/PAD/runtime state.
"""
from __future__ import annotations

from .camera_profiles import normalize_camera_source


def canonical_source(value: object) -> str:
    return normalize_camera_source(str(value or ""))


def persisted_connection_matches(expected_source: str, row: dict | None) -> bool:
    if not row:
        return False
    return canonical_source(expected_source) == canonical_source(row.get("source"))


def startup_source_tracks_previous(settings_source: object, previous_source: object) -> bool:
    """Return True when startup settings point at the registry value being edited."""
    return canonical_source(settings_source) == canonical_source(previous_source)

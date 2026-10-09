"""Security policy for future MCP read-only integration."""
from __future__ import annotations
import os

MCP_ENABLED = os.getenv("MCP_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
MCP_MODE = os.getenv("MCP_MODE", "read_only").strip().lower()
ALLOWED_READ_TOOLS = frozenset({
    "system_health",
    "camera_status",
    "attendance_summary",
    "recognition_statistics",
    "incident_summary",
    "report_query",
})
BLOCKED_DATA_FIELDS = frozenset({
    "password", "secret", "token", "mfa_secret", "private_key",
    "face_embedding", "face_template", "camera_password", "database_password",
})

def assert_read_only(tool_name: str) -> None:
    if not MCP_ENABLED:
        raise PermissionError("MCP is disabled")
    if MCP_MODE != "read_only" or tool_name not in ALLOWED_READ_TOOLS:
        raise PermissionError("MCP tool is not allowed in V5.4 read-only mode")

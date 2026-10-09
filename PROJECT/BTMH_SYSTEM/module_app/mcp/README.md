# MCP boundary (V5.4)

MCP is **disabled by default** in V5.4. This directory defines the security boundary for a later read-only integration. MCP must call the shared service layer, inherit the signed-in user RBAC context, write an audit record for every call, and never access PostgreSQL, RTSP credentials or biometric templates directly.

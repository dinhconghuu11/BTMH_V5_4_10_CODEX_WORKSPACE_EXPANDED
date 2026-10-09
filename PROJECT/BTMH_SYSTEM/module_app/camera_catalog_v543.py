"""Credential-free selection catalog; reading it never opens a video source."""
from __future__ import annotations
from typing import Any
from .camera_profiles import normalize_camera_source


def build_source_catalog(rows: list[dict[str, Any]], current_source: str, runtime: dict) -> dict:
    current = normalize_camera_source(str(current_source or '0'))
    items = []
    seen_laptop = False
    for row in rows:
        source = normalize_camera_source(str(row.get('source') or ''))
        cid = int(row.get('id') or 0)
        is_laptop = source == '0'
        if is_laptop and seen_laptop:
            continue
        seen_laptop |= is_laptop
        enabled = bool(row.get('enabled', True))
        configured = bool(source) and (source.isdigit() or source.lower().startswith(('rtsp://', 'http://', 'https://')))
        active = source == current
        state = ('DISABLED' if not enabled else 'INVALID' if not configured else
                 'ONLINE' if active and runtime.get('opened') and runtime.get('state') == 'online' else
                 'OFFLINE' if active and runtime.get('state') in {'error', 'reconnecting', 'stopped'} else 'UNTESTED')
        items.append({
            'id': cid, 'source_key': '0' if is_laptop else f'CAM{cid:02d}',
            'name': str(row.get('name') or ('Camera laptop' if is_laptop else f'Camera {cid}')),
            'camera_type': str(row.get('camera_type') or ('LAPTOP' if is_laptop else 'IP')),
            'zone_name': str(row.get('zone_name') or ''),
            'enabled': enabled, 'configured': configured, 'selectable': enabled and configured,
            'active': active, 'health_status': state,
        })
    if not seen_laptop:
        items.insert(0, {'id': None, 'source_key': '0', 'name': 'Camera laptop', 'camera_type': 'LAPTOP',
                        'zone_name': '', 'enabled': True, 'configured': True, 'selectable': True,
                        'active': current == '0', 'health_status': 'UNTESTED'})
    return {'items': items, 'active_source_key': next((x['source_key'] for x in items if x['active']), None)}

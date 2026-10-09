"""CampusFace V17 Camera Manager Core
Camera abstraction layer for USB / RTSP / ONVIF sources.
This module keeps AI pipeline independent from camera hardware.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass
class CameraProfile:
    camera_id: str
    name: str
    camera_type: str
    source: str
    enabled: bool = True

class CameraManagerV17:
    def __init__(self):
        self.profiles = {}
        self.active_id: Optional[str] = None

    def add(self, profile: CameraProfile):
        self.profiles[profile.camera_id] = profile

    def select(self, camera_id: str):
        if camera_id not in self.profiles:
            raise KeyError(camera_id)
        self.active_id = camera_id
        return self.profiles[camera_id]

    def list(self):
        return list(self.profiles.values())

    def get_active(self):
        return self.profiles.get(self.active_id)


def build_hikvision_test_camera():
    return CameraProfile(
        camera_id="hikvision_001",
        name="Hikvision DS-2CD1123G0-IUF",
        camera_type="RTSP",
        source="rtsp://admin:<password>@<camera-ip>:554/Streaming/Channels/101"
    )

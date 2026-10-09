from __future__ import annotations
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
ENV=ROOT/'module.env'


def ask(label,default):
    value=input(f'{label} [{default}]: ').strip()
    return value or str(default)


def read_existing():
    out={}
    if ENV.exists():
        for raw in ENV.read_text(encoding='utf-8',errors='ignore').splitlines():
            line=raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k,v=line.split('=',1);out[k.strip()]=v.strip()
    return out


def main():
    print('=== CampusFace Recognition Module V1.7 - STATIC CAMERA CONFIG ===')
    print('No cloud, PostgreSQL or PTZ setting is required.')
    old=read_existing()
    source=ask('Camera source (0/1 or static RTSP URL)',old.get('MODULE_CAMERA_SOURCE','0'))
    backend=ask('Windows backend (auto/dshow/msmf)',old.get('MODULE_CAMERA_BACKEND','auto'))
    profile=ask('Performance profile (FAST/HIGH/MAX)',old.get('MODULE_PROFILE','MAX')).upper()
    width=ask('Camera width',old.get('MODULE_CAMERA_WIDTH','1920'))
    height=ask('Camera height',old.get('MODULE_CAMERA_HEIGHT','1080'))
    fps=ask('Camera FPS',old.get('MODULE_CAMERA_FPS','30'))
    values={
        'CAMPUSFACE_DATA_ROOT':old.get('CAMPUSFACE_DATA_ROOT',r'%LOCALAPPDATA%\CampusFaceV1'),
        'MODULE_PROFILE':profile,
        'MODULE_CAMERA_MODE':'service',
        'MODULE_CAMERA_SOURCE':source,
        'MODULE_CAMERA_BACKEND':backend,
        'MODULE_CAMERA_WIDTH':width,
        'MODULE_CAMERA_HEIGHT':height,
        'MODULE_CAMERA_FPS':fps,
        'MODULE_CAMERA_PREVIEW_FPS':old.get('MODULE_CAMERA_PREVIEW_FPS','25'),
        'MODULE_CAMERA_FOURCC':old.get('MODULE_CAMERA_FOURCC','auto'),
        'MODULE_CAMERA_RECONNECT':'1',
        'MODULE_CAMERA_FAIL_LIMIT':old.get('MODULE_CAMERA_FAIL_LIMIT','8'),
        'MODULE_CAMERA_WARMUP_FRAMES':old.get('MODULE_CAMERA_WARMUP_FRAMES','18'),
        'MODULE_AI_TARGET_FPS':old.get('MODULE_AI_TARGET_FPS','16'),
        'MODULE_AI_WIDTH':old.get('MODULE_AI_WIDTH','1280'),
        'MODULE_MAX_FACES':old.get('MODULE_MAX_FACES','10'),
        'MODULE_QUICK_REARM_SEC':old.get('MODULE_QUICK_REARM_SEC','0.65'),
        'MODULE_ENROLL_TARGET':'8',
        'MODULE_ENROLL_MIN_TOTAL':'8',
        'MODULE_ENROLL_SAMPLE_GAP_SEC':old.get('MODULE_ENROLL_SAMPLE_GAP_SEC','0.22'),
        'MODULE_CLASSROOM_AI_FPS':old.get('MODULE_CLASSROOM_AI_FPS','2'),
        'MODULE_CLASSROOM_FACE_AI_FPS':old.get('MODULE_CLASSROOM_FACE_AI_FPS','4'),
        'MODULE_CLASSROOM_FACE_AI_WIDTH':old.get('MODULE_CLASSROOM_FACE_AI_WIDTH','960'),
        'MODULE_CLASSROOM_PREVIEW_FPS':old.get('MODULE_CLASSROOM_PREVIEW_FPS','20'),
        'MODULE_CLASSROOM_PREVIEW_WIDTH':old.get('MODULE_CLASSROOM_PREVIEW_WIDTH','1920'),
        'MODULE_CLASSROOM_JPEG_QUALITY':old.get('MODULE_CLASSROOM_JPEG_QUALITY','94'),
        'MODULE_CLASSROOM_PREVIEW_ENHANCE':old.get('MODULE_CLASSROOM_PREVIEW_ENHANCE','1'),
        'MODULE_CLASSROOM_PREVIEW_SHARPEN':old.get('MODULE_CLASSROOM_PREVIEW_SHARPEN','0.18'),
        'MODULE_CLASSROOM_PREVIEW_CONTRAST':old.get('MODULE_CLASSROOM_PREVIEW_CONTRAST','1.045'),
        'MODULE_CLASSROOM_PREVIEW_BRIGHTNESS_TARGET':old.get('MODULE_CLASSROOM_PREVIEW_BRIGHTNESS_TARGET','128'),
        'MODULE_CLASSROOM_MAX_POSE_TRACKS':old.get('MODULE_CLASSROOM_MAX_POSE_TRACKS','4'),
        'MODULE_STORE_SNAPSHOTS':old.get('MODULE_STORE_SNAPSHOTS','0'),
    }
    ENV.write_text('\n'.join(f'{k}={v}' for k,v in values.items())+'\n',encoding='utf-8')
    print('[OK] Saved:',ENV)
    print('[DATA]',values['CAMPUSFACE_DATA_ROOT'])
    print('[NEXT] CHECK_READY_WINDOWS.bat -> START_CAMPUSFACE.bat')
    return 0


if __name__=='__main__':
    raise SystemExit(main())

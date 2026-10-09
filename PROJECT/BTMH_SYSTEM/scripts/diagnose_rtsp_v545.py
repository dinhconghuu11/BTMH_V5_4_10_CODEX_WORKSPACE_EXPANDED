"""Interactive read-only RTSP test using BTMH's exact decoder and private Python.

Does not edit the registry, database, AI settings, camera firmware or live source.
No image/video is saved. Password is read with getpass, never put in argv/logs.
"""
from __future__ import annotations
from pathlib import Path
import getpass
import json
import os
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from module_app.camera_profiles import build_rtsp_url
from module_app.capture_session_v544 import CaptureSession
from module_app.rtsp_native_v545 import resolve_ffmpeg


def main() -> int:
    print("BAO TIN MANH HAI - KIEM TRA RTSP (KHONG DOI CAU HINH)")
    print("Nhap IP camera thuc te. Khong reset camera, khong xoa du lieu.")
    try:
        host=input("IP / hostname: ").strip()
        port=int(input("Cong RTSP [554]: ").strip() or "554")
        path=input("Duong dan [/Streaming/Channels/101]: ").strip() or "/Streaming/Channels/101"
        user=input("Tai khoan camera: ").strip()
        password=getpass.getpass("Mat khau camera (khong hien khi go): ")
        source=build_rtsp_url(host,user,password,port=port,stream=path)
        session=CaptureSession(source)
    except (ValueError, EOFError, KeyboardInterrupt):
        print("Thong tin chua hop le hoac da huy.");return 2
    report={"version":"5.4.5","native_available":bool(resolve_ffmpeg()),"python":sys.version.split()[0]}
    try:
        session.start();report.update(session.wait_ready(frames=5,timeout=18.))
    except Exception:
        report.update(ok=False,code="START_FAILED",message="Khong khoi dong duoc bo doc. Chay lai Cai dat lan dau.")
    finally:
        session.close()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    # Only the allowlisted diagnostic object is persisted, never raw input/frame.
    root=Path(os.getenv("CAMPUSFACE_DATA_ROOT") or (Path(os.getenv("LOCALAPPDATA") or str(Path.home()))/"CampusFace"))
    folder=root/"logs";folder.mkdir(parents=True,exist_ok=True)
    output=folder/"camera-diagnostic-latest.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Ket qua da luu:",output)
    return 0 if report.get("ok") else 1

if __name__=="__main__":
    raise SystemExit(main())

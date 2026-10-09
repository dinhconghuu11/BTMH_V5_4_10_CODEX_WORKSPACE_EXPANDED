from pathlib import Path
import sys
import subprocess
import os
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from module_app.rtsp_native_v545 import resolve_ffmpeg

def main():
    exe=resolve_ffmpeg()
    if not exe:
        print("[WARN] Native RTSP reader unavailable; existing OpenCV reader is the fallback.")
        return 2
    kw={"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {}
    try:
        r=subprocess.run([exe,"-hide_banner","-version"],capture_output=True,text=True,timeout=6,**kw)
        if r.returncode:raise RuntimeError()
        print("[OK] Native RTSP reader:",r.stdout.splitlines()[0])
        return 0
    except (OSError,RuntimeError,subprocess.TimeoutExpired):
        print("[ERROR] Native RTSP executable cannot start; repair runtime first.")
        return 1
if __name__=="__main__":raise SystemExit(main())

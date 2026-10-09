from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_employee_create_update_routes_return_detail_with_request_context():
    src = (ROOT / "module_app" / "main.py").read_text(encoding="utf-8")
    assert "return get_student(int(sid), request)" in src
    assert src.count("return get_student(student_id, request)") >= 2


def test_new_employee_flow_enters_faceid_step_without_waiting_for_list_refresh():
    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert "state.enrollStudentProfile=s" in js
    assert "await beginFaceIdSetup(s);" in js
    begin = js[js.index("async function beginFaceIdSetup"):js.index("async function finalizeEnrollment")]
    assert begin.index("setEnrollPhase(true)") < begin.index("prepareEnrollmentLaptopCamera()")
    assert "Hồ sơ đã lưu. Đang mở camera" in begin



def test_enrollment_retry_reopens_camera_before_resuming_scan_loop():
    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    start = js.index("async function resetEnrollment")
    end = js.index("function setRecognitionProgress", start)
    block = js[start:end]
    assert "await prepareEnrollmentLaptopCamera()" in block
    assert "if(!cameraReady)" in block
    assert block.index("prepareEnrollmentLaptopCamera()") < block.index("startEnrollLoop()")

def _run_walkby_probe(code: str) -> dict:
    # Import biometric modules in an isolated external DATA_ROOT so tests never create
    # runtime secrets inside the release tree.
    with tempfile.TemporaryDirectory(prefix="btmh-v536-test-") as td:
        env = dict(os.environ)
        env["CAMPUSFACE_DATA_ROOT"] = td
        env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        cp = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(ROOT), env=env, text=True, capture_output=True, check=True,
        )
        return json.loads(cp.stdout.strip())


def test_recognition_quality_gate_rejects_oblique_frame_as_uncertain_not_spoof():
    out = _run_walkby_probe(r'''
import json, numpy as np
from module_app.face_core import FaceObservation
from module_app.walkby import WalkByEngine
q={"score":.78,"sharpness":85.0,"brightness":128.0,"face_px":150,"usable":True}
obs=FaceObservation(np.zeros(15,dtype=np.float32),(0,0,150,150),None,q,"right",.45,0.0)
p=WalkByEngine._recognition_quality_gate(obs,for_pad=True)
i=WalkByEngine._recognition_quality_gate(obs,for_pad=False)
print(json.dumps({"pad":p,"identity":i},ensure_ascii=False))
''')
    assert out["pad"][0] is False and out["identity"][0] is False
    assert "chưa kết luận giả mạo" in out["pad"][1]
    assert "chưa kết luận danh tính" in out["identity"][1]


def test_recognition_quality_gate_accepts_clear_frontal_frame():
    out = _run_walkby_probe(r'''
import json, numpy as np
from module_app.face_core import FaceObservation
from module_app.walkby import WalkByEngine
q={"score":.80,"sharpness":90.0,"brightness":125.0,"face_px":160,"usable":True}
obs=FaceObservation(np.zeros(15,dtype=np.float32),(0,0,160,160),None,q,"center",.03,.02)
print(json.dumps({"pad":WalkByEngine._recognition_quality_gate(obs,for_pad=True)[0],"identity":WalkByEngine._recognition_quality_gate(obs,for_pad=False)[0]}))
''')
    assert out == {"pad": True, "identity": True}


def test_temporal_embedding_fusion_is_normalized_and_quality_weighted():
    out = _run_walkby_probe(r'''
import json, numpy as np
from module_app.walkby import WalkByEngine
f=WalkByEngine._fused_identity_vector([
 {"embedding":np.asarray([1.,0.],dtype=np.float32),"quality":.90},
 {"embedding":np.asarray([.8,.2],dtype=np.float32),"quality":.80},
 {"embedding":np.asarray([.7,.3],dtype=np.float32),"quality":.55},
])
print(json.dumps({"norm":float(np.linalg.norm(f)),"a":float(f[0]),"b":float(f[1])}))
''')
    assert abs(out["norm"] - 1.0) < 1e-5
    assert out["a"] > out["b"]


def test_unknown_is_delayed_and_ui_has_quality_observation_state():
    walkby = (ROOT / "module_app" / "walkby.py").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    assert "enough_attempts = tr.processed >= 6" in walkby
    assert "enough_time = (now - tr.first_seen) >= 1.60" in walkby
    assert 'public_status = "OBSERVING_QUALITY"' in walkby
    assert "status==='OBSERVING_QUALITY'" in js
    assert "renderRecognitionPending" in js


def test_pad_hard_block_requires_temporal_consensus():
    anti = (ROOT / "module_app" / "anti_spoof.py").read_text(encoding="utf-8")
    assert "pad_n >= max(PAD_MIN_OBS, 5)" in anti
    assert "spoof_votes >= max(PAD_BLOCK_VOTES, 4)" in anti
    assert "very_strong_explicit" in anti
    assert "V5.3.6-temporal-pad-v3" in anti

from pathlib import Path
import os, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[1]
tests=[
    'test_decision_policy.py','test_offline_frontend.py','test_reentry_policy.py','test_camera_recovery.py',
    'test_recognition_preserved.py','test_v1_stable_ui.py','test_enrollment_two_pass.py','test_deleted_student_contract.py',
    'test_classroom_actions.py','test_deployment_contract.py','test_v1_2_faceid_scan.py','test_student_activity_profile.py',
    'test_classroom_resolution_mapping.py','test_easy_deployment_v12.py','test_farface_yolo_training_contract.py',
    'test_release_clean_guard.py','test_v13_classroom_cleanfix.py','test_v13_two_circle_enrollment.py',
    'test_v13_frontend_runtime_contract.py','test_v131_smooth_classroom.py','test_v14_static_deployable.py',
    'test_v15_security_action.py','test_v15_walkby_liveness_gate.py','test_v15_db_security_event.py',
    'test_v16_tracker_scale.py','test_v17_realtime_classroom.py','test_enterprise_production_v19.py',
    'test_production_ready_v110.py',
    'test_v114_user_managed_postgres.py','test_v115_passive_antispoof_preid.py','test_v1_face_best_recognition.py','test_v1_face_stable_runtime.py','test_v1_face_core_stable.py','test_v1_face_pro_r1.py','test_v1_face_pro_r2.py','test_v1_face_pro_r3_hotfix.py','test_camera_hd_v5.py','test_professional_v6.py','test_professional_v7.py',
]
for name in tests:
    print(f'--- {name} ---')
    with tempfile.TemporaryDirectory(prefix='cf-test-') as td:
        env=os.environ.copy()
        # Unit/regression tests use isolated SQLite maintenance mode. Production default remains PostgreSQL.
        env['CAMPUSFACE_DB_MODE']='sqlite'
        env['CAMPUSFACE_DATA_ROOT']=td
        p=subprocess.run([sys.executable,str(ROOT/'tests'/name)],cwd=ROOT,env=env)
    if p.returncode:
        raise SystemExit(p.returncode)
print(f'[OK] {len(tests)} CampusFace V1 FACE PRO Professional V7 tests passed')

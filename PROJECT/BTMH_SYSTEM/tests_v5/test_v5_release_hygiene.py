from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]


def test_no_packaged_camera_or_sms_secrets_in_known_config_files():
    candidates = [PROJECT / "config" / "cameras_v17.json", PROJECT / "config" / "hikvision_test_camera.json"]
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        # Password fields may exist as placeholders but must not contain embedded user secrets.
        assert '"password":"' not in text.replace(" ", "") or '"password":""' in text.replace(" ", "")


def test_runtime_requirements_include_security_and_database_dependencies():
    req = (ROOT / "requirements-runtime.txt").read_text(encoding="utf-8")
    for dep in ("fastapi", "cryptography", "psycopg[binary]", "argon2-cffi"):
        assert dep in req


def test_sqlite_auth_otp_pending_approval_and_evidence_lock_smoke(tmp_path):
    import os, subprocess, sys, textwrap
    script = textwrap.dedent(r'''
        from module_app.db import init_db, execute, fetchone, utc_now
        from module_app.production_ops import ensure_production_schema
        from module_app.auth import ensure_rbac_schema, bootstrap_admin, register_public_user, approve_user, login
        from module_app.otp_service import ensure_otp_schema, request_otp, verify_otp
        from module_app.platform_v5 import ensure_platform_v5_schema, set_face_enrollment_validation_pending, create_incident, add_incident_evidence, lock_incident_evidence
        from module_app.recording import ensure_recording_schema
        init_db(); ensure_production_schema(); ensure_rbac_schema(); ensure_otp_schema(); ensure_platform_v5_schema(); ensure_recording_schema()
        r=request_otp(purpose='BOOTSTRAP',phone='0900000101',payload={'username':'rootadmin'})
        assert verify_otp(challenge_id=r['challenge_id'],otp=r['demo_otp'],purpose='BOOTSTRAP')['ok']
        root=bootstrap_admin('rootadmin','Root Admin','StrongPass!2026','0900000101','admin@example.test',phone_verified=True)
        assert root['role']=='SUPER_ADMIN'
        r2=request_otp(purpose='REGISTER',phone='0900000102',payload={'username':'employee1'})
        assert verify_otp(challenge_id=r2['challenge_id'],otp=r2['demo_otp'],purpose='REGISTER')['ok']
        u=register_public_user('employee1','Employee One','0900000102','EmployeePass!2026','employee1@example.test')
        assert not u['active']
        assert approve_user(u['id'],role='EMPLOYEE',store_id=1,actor='rootadmin')['active']
        assert login('employee1','EmployeePass!2026')['user']['username']=='employee1'
        now=utc_now()
        sid=execute("INSERT INTO students(student_code,full_name,class_name,faculty,email,phone,consent_at,biometric_consent_status,biometric_consent_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",('NV001','Employee One','','','employee1@example.test','0900000102',now,'GRANTED',now,now,now))
        assert set_face_enrollment_validation_pending(sid,note='smoke')['status']=='PENDING_STORE_VALIDATION'
        seg='SEG-SMOKE-1'
        execute("INSERT INTO recording_segments(segment_id,camera_source,start_at,end_at,storage_type,media_uri,size_bytes,protected,detail_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(seg,'cam01',now,now,'LOCAL','file:///tmp/x.mp4',1,0,'{}',now,now))
        inc=create_incident({'title':'Smoke incident','occurred_at':now},'rootadmin')
        add_incident_evidence(inc['incident_id'],'VIDEO_SEGMENT',seg,'rootadmin','cam01',now,'smoke')
        lock_incident_evidence(inc['incident_id'],'rootadmin')
        assert int(fetchone('SELECT protected FROM recording_segments WHERE segment_id=?',(seg,))['protected'])==1
    ''')
    env = os.environ.copy()
    env.update({
        'CAMPUSFACE_DB_MODE': 'sqlite',
        'CAMPUSFACE_DATA_ROOT': str(tmp_path / 'runtime'),
        'BTMH_SMS_PROVIDER': 'DEMO',
        'PYTHONPATH': str(ROOT),
    })
    subprocess.run([sys.executable, '-c', script], env=env, check=True, timeout=30)


def test_runtime_face_template_key_is_not_packaged_with_application_source():
    # Every installation must create/restore its own biometric encryption key in
    # the external DATA_ROOT; shipping one shared key would weaken tenant isolation.
    assert not (ROOT / ".campusface-data" / "data" / "face_templates.key").exists()

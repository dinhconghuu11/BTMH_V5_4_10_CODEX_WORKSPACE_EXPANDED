"""Executable auth/API tests against isolated SQLite; SMS provider is mocked.

No messages are sent. PostgreSQL/Windows and carrier delivery require acceptance
on the deployment PC. These tests are not evidence of live SMS delivery.
"""
import concurrent.futures
import secrets
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from argon2 import PasswordHasher
from module_app import auth,db,sms_auth_v542 as sms,sms_provider_v542 as provider
from module_app.production_ops import ensure_production_schema
from module_app.main import app

PW='OnlyForAutomatedTests!542'
PHONE='+84912345678'
CODE='825419'

class FakeProvider:
    def __init__(self): self.sent=[]; self.fail=False; self.check_fail=False
    def send(self,phone):
        if self.fail: raise provider.ProviderError()
        self.sent.append(phone)
        return 'VE'+'a'*32
    def check(self,sid,phone,code):
        if self.check_fail: raise provider.ProviderError()
        return sid=='VE'+'a'*32 and phone==PHONE and code==CODE

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_MODE','sqlite')
    monkeypatch.setattr(db,'SQLITE_PATH',tmp_path/'auth.db')
    monkeypatch.setattr(auth,'_ARGON2',PasswordHasher(time_cost=1,memory_cost=8192,parallelism=1))
    auth._sessions.clear();auth._mfa_challenges.clear();auth._failed_logins.clear()
    auth._session_factor_times.clear();auth._session_credential_tags.clear()
    db.init_db();ensure_production_schema();auth.ensure_rbac_schema()
    owner=auth.bootstrap_admin('qaowner','QA Owner',PW,phone_verified=False)
    fake=FakeProvider()
    monkeypatch.setattr(provider,'configured',lambda:True)
    monkeypatch.setattr(provider,'get_provider',lambda:fake)
    return owner,fake

def client(https=False,remote=False):
    return TestClient(app,base_url='https://btmh.test' if https else 'http://127.0.0.1',client=('192.168.1.60' if remote else '127.0.0.1',12345))

def login(c,name='qaowner',password=PW):
    return c.post('/api/v1/auth/login',json={'username':name,'password':password})

def post(c,path,body):
    return c.post('/api/v1/auth/sms/'+path,json=body)

def enroll(c):
    assert login(c).status_code==200
    r=post(c,'enroll',{'current_password':PW,'phone':'0912345678'})
    assert r.status_code==200,r.text
    cid=r.json()['challenge_id']
    assert post(c,'send',{'challenge_id':cid}).status_code==200
    r=post(c,'verify',{'challenge_id':cid,'code':CODE})
    assert r.status_code==200,r.text
    return r.json()['recovery_codes']

def expire_cooldown():
    db.execute('UPDATE sms_send_clock_v542 SET next_at=0')

def begin_sms(c):
    r=login(c);assert r.status_code==200,r.text
    assert r.json()['mfa_method']=='SMS'
    return r.json()['challenge_id']

def test_unenrolled_user_no_forced_totp(env):
    c=client();r=login(c)
    assert r.status_code==200 and r.json()['authenticated']
    assert 'mfa_setup' not in r.json() and not r.json()['user']['mfa_enabled']
    assert 'token' not in r.json()

def test_wrong_password_cannot_create_challenge(env):
    c=client();r=login(c,password='wrong')
    assert r.status_code==401
    assert sms.PENDING_COOKIE not in c.cookies

def test_enrollment_password_required_and_phone_not_pretrusted(env):
    c=client();login(c)
    assert post(c,'enroll',{'current_password':'wrong','phone':PHONE}).status_code==400
    assert not sms.factor(env[0]['id'])

def test_phone_normalization_and_validation(env):
    assert sms.normalize_phone('0912 345 678')==PHONE
    with pytest.raises(sms.SmsError):sms.normalize_phone('123')

def test_enrollment_requires_real_code_and_returns_recovery_once(env):
    c=client();codes=enroll(c)
    assert len(codes)==8 and len(set(codes))==8
    data=c.get('/api/v1/auth/sms/security').json()
    assert data['method']=='SMS' and data['enabled'] and data['recovery_remaining']==8
    assert PHONE not in str(data)
    assert 'recovery_codes' not in data
    rows=db.fetchall('SELECT code_hash FROM account_mfa_recovery_codes')
    assert all(code not in str(rows) for code in codes)
    assert env[1].sent==[PHONE]

def test_login_phone_is_server_bound_not_input(env):
    enroll(client());c=client();cid=begin_sms(c)
    expire_cooldown()
    r=post(c,'send',{'challenge_id':cid,'phone':'+19999999999'})
    assert r.status_code==422
    assert post(c,'send',{'challenge_id':cid}).status_code==200
    assert env[1].sent[-1]==PHONE

def test_password_alone_never_issues_session_for_sms_account(env):
    enroll(client());c=client();cid=begin_sms(c)
    assert 'campusface_session' not in c.cookies
    assert c.get('/api/v1/auth/status').json()['authenticated'] is False
    assert c.get('/api/v1/students').status_code==401

def test_provider_unconfigured_no_demo_no_bypass(env,monkeypatch):
    c=client();login(c)
    monkeypatch.setattr(provider,'configured',lambda:False)
    r=post(c,'enroll',{'current_password':PW,'phone':PHONE})
    assert r.status_code==503
    assert not sms.factor(env[0]['id'])

def test_send_failure_is_not_success_and_does_not_disable_factor(env):
    enroll(client());c=client();cid=begin_sms(c);expire_cooldown();env[1].fail=True
    r=post(c,'send',{'challenge_id':cid})
    assert r.status_code==503 and 'accepted' not in r.json()
    assert 'campusface_session' not in c.cookies and sms.factor(env[0]['id'])
    r=post(c,'send',{'challenge_id':cid})
    assert r.status_code==429 # failed carrier attempts consume anti-spam quota

def test_resend_cooldown_and_attempts_not_reset(env):
    enroll(client());c=client();cid=begin_sms(c);expire_cooldown()
    assert post(c,'send',{'challenge_id':cid}).status_code==200
    assert post(c,'verify',{'challenge_id':cid,'code':'000000'}).status_code==401
    r=post(c,'send',{'challenge_id':cid});assert r.status_code==429
    assert int(r.headers['Retry-After'])>0
    expire_cooldown();assert post(c,'send',{'challenge_id':cid}).status_code==200
    assert db.fetchone('SELECT attempts FROM sms_challenges_v542 WHERE id_hash=?',(sms.digest(cid),))['attempts']==1

def test_max_five_attempts(env):
    enroll(client());c=client();cid=begin_sms(c);expire_cooldown();post(c,'send',{'challenge_id':cid})
    for _ in range(5):assert post(c,'verify',{'challenge_id':cid,'code':'000000'}).status_code==401
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==429

def test_challenge_expiry(env):
    enroll(client());c=client();cid=begin_sms(c)
    db.execute('UPDATE sms_challenges_v542 SET expires_at=1 WHERE id_hash=?',(sms.digest(cid),))
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==401

def test_binding_cookie_prevents_other_browser_using_challenge(env):
    enroll(client());a=client();cid=begin_sms(a);b=client()
    assert post(b,'send',{'challenge_id':cid}).status_code==401
    assert post(b,'verify',{'challenge_id':cid,'code':CODE}).status_code==401

def test_trust_only_after_verified_factor_and_always_needs_password(env):
    enroll(client());c=client();cid=begin_sms(c);expire_cooldown();post(c,'send',{'challenge_id':cid})
    assert post(c,'verify',{'challenge_id':cid,'code':'000000','trust_browser':True}).status_code==401
    assert sms.TRUST_COOKIE not in c.cookies
    r=post(c,'verify',{'challenge_id':cid,'code':CODE,'trust_browser':True})
    assert r.status_code==200 and r.json()['authenticated']
    raw=c.cookies[sms.TRUST_COOKIE]
    assert raw not in r.text
    saved=db.fetchone('SELECT * FROM sms_trusted_browsers_v542 WHERE id_hash=?',(sms.digest(raw),))
    assert saved['expires_at']-saved['created_at']==30*86400
    assert raw not in str(saved)
    c.cookies.delete('campusface_session')
    assert login(c,password='wrong').status_code==401
    r=login(c);assert r.status_code==200 and r.json()['authenticated'] and r.json()['trusted_browser']
    assert not auth.factor_is_fresh(c.cookies['campusface_session'])

def test_trust_expired_revoked_and_cross_account_denied(env):
    user=db.fetchone('SELECT * FROM system_users WHERE id=?',(env[0]['id'],))
    token=sms.issue_trust(user['id'],'Test')
    assert sms.trust(user,token)
    other=auth.create_user('qaother','QA Other','ADMIN',PW)
    other=db.fetchone('SELECT * FROM system_users WHERE id=?',(other['id'],))
    assert not sms.trust(other,token)
    db.execute('UPDATE sms_trusted_browsers_v542 SET expires_at=1 WHERE id_hash=?',(sms.digest(token),))
    assert not sms.trust(user,token)
    token=sms.issue_trust(user['id'],'Test');sms.revoke_user(user['id'])
    assert not sms.trust(user,token)

def test_password_reset_and_role_change_revoke_trust(env):
    user=db.fetchone('SELECT * FROM system_users WHERE id=?',(env[0]['id'],))
    cookie=sms.issue_trust(user['id'],'Test')
    auth.reset_user_password(user['id'],'NewTestPassword!542')
    user=db.fetchone('SELECT * FROM system_users WHERE id=?',(user['id'],))
    assert not sms.trust(user,cookie)
    other=auth.create_user('qaother','QA Other','ADMIN',PW)
    cookie=sms.issue_trust(other['id'],'Test')
    auth.update_user(other['id'],role='HR')
    other=db.fetchone('SELECT * FROM system_users WHERE id=?',(other['id'],))
    assert not sms.trust(other,cookie)

def test_recovery_works_offline_once(env,monkeypatch):
    codes=enroll(client());c=client();cid=begin_sms(c)
    monkeypatch.setattr(provider,'get_provider',lambda:(_ for _ in ()).throw(provider.ProviderError()))
    r=post(c,'verify',{'challenge_id':cid,'code':codes[0]})
    assert r.status_code==200 and r.json()['authenticated']
    c=client();cid=begin_sms(c)
    assert post(c,'verify',{'challenge_id':cid,'code':codes[0]}).status_code==401
    assert post(c,'verify',{'challenge_id':cid,'code':codes[1]}).status_code==200

def test_recovery_cannot_verify_new_phone(env):
    c=client();login(c);r=post(c,'enroll',{'current_password':PW,'phone':PHONE});cid=r.json()['challenge_id']
    assert post(c,'verify',{'challenge_id':cid,'code':'AAAAAA-BBBBBB-CCCCCC-DDDDDD'}).status_code==400
    assert not sms.factor(env[0]['id'])

def test_recovery_double_submit_only_one_session(env):
    codes=enroll(client());user=db.fetchone('SELECT * FROM system_users WHERE id=?',(env[0]['id'],))
    binding=secrets.token_urlsafe(32);cid=sms.begin_login(user,binding)['challenge_id']
    def attempt():
        try:return bool(sms.verify(cid,binding,codes[0]).get('token'))
        except sms.SmsError:return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==[False,True]

def test_sms_double_submit_only_one_session(env):
    enroll(client());user=db.fetchone('SELECT * FROM system_users WHERE id=?',(env[0]['id'],))
    binding=secrets.token_urlsafe(32);cid=sms.begin_login(user,binding)['challenge_id'];expire_cooldown();sms.send(cid,binding,'127.0.0.1')
    def attempt():
        try:return bool(sms.verify(cid,binding,CODE).get('token'))
        except sms.SmsError:return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:attempt(),range(2)))
    assert sorted(results)==[False,True]

def test_provider_check_outage_no_session(env):
    enroll(client());c=client();cid=begin_sms(c);expire_cooldown();post(c,'send',{'challenge_id':cid});env[1].check_fail=True
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==503
    assert 'campusface_session' not in c.cookies

def test_new_enrollment_does_not_downgrade_existing_totp(env):
    uid=env[0]['id'];secret=auth._totp_secret();auth._persist_mfa_setup(uid,secret,auth._totp_step()-1)
    c=client();r=login(c);assert r.json()['mfa_method']=='TOTP' and not r.json()['mfa_setup_required']
    assert 'campusface_session' not in c.cookies
    r=c.post('/api/v1/auth/mfa/verify',json={'challenge_id':r.json()['challenge_id'],'code':auth._totp_code(secret)})
    assert r.status_code==200 and r.json()['authenticated']
    r=post(c,'enroll',{'current_password':PW,'phone':PHONE});assert r.status_code==200
    assert auth._mfa_record(uid)['enabled'] # still active before new phone verified
    cid=r.json()['challenge_id'];assert post(c,'send',{'challenge_id':cid}).status_code==200
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==200
    assert sms.factor(uid) and not auth._mfa_record(uid)

def test_phone_change_requires_recent_factor(env):
    c=client();enroll(c)
    auth._session_factor_times[c.cookies['campusface_session']]=1
    r=post(c,'enroll',{'current_password':PW,'phone':'+84988888888'})
    assert r.status_code==403
    assert r.json()['detail']['code']=='STEP_UP_REQUIRED'

def test_stepup_recovery_refreshes_proof_without_provider(env):
    c=client();codes=enroll(c);auth._session_factor_times[c.cookies['campusface_session']]=1
    r=post(c,'step-up',{'current_password':PW});assert r.status_code==200
    r=post(c,'verify',{'challenge_id':r.json()['challenge_id'],'code':codes[0]})
    assert r.status_code==200 and r.json()['purpose']=='STEPUP'
    assert auth.factor_is_fresh(c.cookies['campusface_session'])

def test_sensitive_action_requires_stepup_after_trusted_login(env):
    c=client();enroll(c);auth._session_factor_times[c.cookies['campusface_session']]=1
    r=c.post('/api/v1/admin/users/1/mfa/reset',json={})
    assert r.status_code==403 and r.json()['code']=='STEP_UP_REQUIRED'

def test_enrollment_challenge_invalid_after_logout(env):
    c=client();login(c);r=post(c,'enroll',{'current_password':PW,'phone':PHONE});cid=r.json()['challenge_id']
    raw=c.cookies['campusface_session'];auth.logout(raw)
    assert post(c,'send',{'challenge_id':cid}).status_code==401

def test_mfa_cookies_secure_httponly_same_site_no_raw_token_json(env):
    c=client(https=True);enroll(c);c=client(https=True);cid=begin_sms(c);expire_cooldown();post(c,'send',{'challenge_id':cid})
    r=post(c,'verify',{'challenge_id':cid,'code':CODE,'trust_browser':True})
    cookies=r.headers.get_list('set-cookie')
    cookie=next(x for x in cookies if x.startswith(sms.TRUST_COOKIE+'='))
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie and 'Domain=' not in cookie
    assert r.headers['cache-control']=='no-store'
    assert 'token' not in r.json()

def test_lan_plain_http_rejected(env):
    c=client(remote=True)
    assert login(c).status_code==403

def test_csrf_origin_rejected(env):
    c=client();r=c.post('/api/v1/auth/login',json={'username':'qaowner','password':PW},headers={'origin':'https://evil.invalid'})
    assert r.status_code==403

def test_legacy_demo_endpoints_remain_disabled(env):
    c=client()
    assert c.post('/api/v1/auth/2fa/request-otp',json={}).status_code==404

def test_otp_phone_and_token_not_in_audit(env):
    c=client();enroll(c)
    text=str(db.fetchall('SELECT detail_json FROM audit_events'))
    assert PHONE not in text and CODE not in text and PW not in text
    assert c.cookies['campusface_session'] not in text

def test_schema_repeated_does_not_erase_enrollment(env):
    c=client();enroll(c);auth.ensure_rbac_schema();auth.ensure_rbac_schema()
    assert sms.factor(env[0]['id'])
    assert c.get('/api/v1/auth/sms/security').json()['recovery_remaining']==8

def test_trusted_browser_persists_across_process_session_reset(env):
    c=client();enroll(c);user=db.fetchone('SELECT * FROM system_users WHERE id=?',(env[0]['id'],))
    raw=sms.issue_trust(user['id'],'Test')
    auth._sessions.clear();auth._session_factor_times.clear();auth._session_credential_tags.clear()
    assert sms.trust(user,raw)
    out=auth.login('qaowner',PW,trusted_cookie=raw,binding=secrets.token_urlsafe(32),allow_trust=True)
    assert out['trusted_browser'] and out['token']

def test_private_security_requires_authentication(env):
    c=client()
    assert c.get('/api/v1/auth/sms/security').status_code==401
    assert post(c,'enroll',{'current_password':PW,'phone':PHONE}).status_code==401

def test_disabled_user_pending_challenge_revoked(env):
    enroll(client());c=client();cid=begin_sms(c)
    # Simulate external management SQL as well as the supported API.
    db.execute('UPDATE system_users SET active=0 WHERE id=?',(env[0]['id'],))
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==401

def test_six_digit_code_provider_contract_checks_target_and_sid(env):
    real=provider.TwilioVerifyProvider(provider.VerifyConfig('AC'+'a'*32,'SK'+'b'*32,'secret-for-test','VA'+'c'*32))
    result={'status':'approved','valid':True,'sid':'VE'+'a'*32,'to':PHONE,'channel':'sms'}
    with patch.object(real,'_post',return_value=result):assert real.check(result['sid'],PHONE,CODE)
    with patch.object(real,'_post',return_value={**result,'to':'+19999999999'}):assert not real.check(result['sid'],PHONE,CODE)
    with patch.object(real,'_post',return_value={**result,'status':'pending'}):assert not real.check(result['sid'],PHONE,CODE)

def test_new_owner_http_bootstrap_sets_real_session_without_forced_totp(env):
    with db.connection() as conn:
        conn.execute('DELETE FROM system_users')
    auth._sessions.clear()
    c=client();r=c.post('/api/v1/auth/bootstrap-local',json={'username':'newowner','display_name':'New Owner','password':PW,'phone':''})
    assert r.status_code==200,r.text
    assert r.json()['authenticated'] and 'mfa_setup' not in r.json()
    assert c.get('/api/v1/auth/status').json()['authenticated']

def test_enroll_cannot_reuse_another_accounts_session(env):
    c=client();login(c);r=post(c,'enroll',{'current_password':PW,'phone':PHONE});cid=r.json()['challenge_id']
    other=auth.create_user('qaother','QA Other','ADMIN',PW)
    session=auth.login('qaother',PW)['token']
    c.cookies.set('campusface_session',session,domain='127.0.0.1',path='/')
    assert post(c,'send',{'challenge_id':cid}).status_code==401

def test_single_use_after_success_even_with_same_cookie(env):
    enroll(client());c=client();cid=begin_sms(c);binding=c.cookies[sms.PENDING_COOKIE];expire_cooldown();post(c,'send',{'challenge_id':cid})
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==200
    c.cookies.set(sms.PENDING_COOKIE,binding,domain='127.0.0.1',path='/')
    assert post(c,'verify',{'challenge_id':cid,'code':CODE}).status_code==401

def test_factor_verification_budget_persists_across_new_challenges(env):
    codes=enroll(client()) # one verification attempt used during enrollment
    for index in range(9):
        c=client();cid=begin_sms(c)
        assert post(c,'verify',{'challenge_id':cid,'code':'AAAAAA-BBBBBB-CCCCCC-DDDDDD'}).status_code==401
    c=client();cid=begin_sms(c)
    assert post(c,'verify',{'challenge_id':cid,'code':codes[0]}).status_code==429


def test_auth_validation_does_not_reflect_submitted_secrets(env):
    c=client();login(c)
    secret='SecretShouldNotBeReflected'*20
    r=post(c,'enroll',{'current_password':secret,'phone':PHONE})
    assert r.status_code==422
    assert secret not in r.text and 'input' not in r.text


def test_provider_approved_without_legacy_valid_property(env):
    real=provider.TwilioVerifyProvider(provider.VerifyConfig('AC'+'a'*32,'SK'+'b'*32,'secret-for-test','VA'+'c'*32))
    result={'status':'approved','sid':'VE'+'a'*32,'to':PHONE,'channel':'sms'}
    with patch.object(real,'_post',return_value=result):
        assert real.check('VE'+'a'*32,PHONE,CODE)
    result['valid']=False
    with patch.object(real,'_post',return_value=result):
        assert not real.check('VE'+'a'*32,PHONE,CODE)

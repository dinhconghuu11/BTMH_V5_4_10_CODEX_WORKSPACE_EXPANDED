"""SMS second factor, durable one-use challenges and revocable browser trust.

Only a verified, bound phone is used at login. A missing provider never grants a
session. SQL is compatible with PostgreSQL and SQLite (the latter is test-only).
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import time
from .db import connection, fetchone, fetchall, utc_now, add_audit_event
from .crypto import encrypt_bytes, decrypt_bytes
from . import sms_provider_v542 as provider

CHALLENGE_TTL = 300
TRUST_TTL = 30 * 24 * 3600
FRESH_TTL = 300
TRUST_COOKIE = 'btmh_trusted_browser'
PENDING_COOKIE = 'btmh_auth_pending'

class SmsError(ValueError):
    def __init__(self, message: str, code='SMS_ERROR', status=400, retry_after=0):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(message)

EXPIRED = 'Phi\u00ean x\u00e1c minh kh\u00f4ng h\u1ee3p l\u1ec7 ho\u1eb7c \u0111\u00e3 h\u1ebft h\u1ea1n. H\u00e3y \u0111\u0103ng nh\u1eadp l\u1ea1i.'
UNAVAILABLE = 'Ch\u01b0a g\u1eedi \u0111\u01b0\u1ee3c SMS. Ki\u1ec3m tra k\u1ebft n\u1ed1i/nh\u00e0 cung c\u1ea5p ho\u1eb7c d\u00f9ng m\u00e3 kh\u00f4i ph\u1ee5c.'
INVALID = 'M\u00e3 kh\u00f4ng h\u1ee3p l\u1ec7, \u0111\u00e3 d\u00f9ng ho\u1eb7c \u0111\u00e3 h\u1ebft h\u1ea1n.'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sms_factors_v542 (
 user_id INTEGER PRIMARY KEY REFERENCES system_users(id) ON DELETE CASCADE,
 phone_enc TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, verified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sms_challenges_v542 (
 id_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL, phone_enc TEXT NOT NULL, binding_hash TEXT NOT NULL,
 session_hash TEXT NOT NULL, credential_tag TEXT NOT NULL, provider_sid TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL, created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, last_sent_at BIGINT NOT NULL DEFAULT 0,
 consumed_at BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sms_challenge_user ON sms_challenges_v542(user_id,purpose);
CREATE TABLE IF NOT EXISTS sms_trusted_browsers_v542 (
 id_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES system_users(id) ON DELETE CASCADE,
 credential_tag TEXT NOT NULL, created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL,
 last_used_at BIGINT NOT NULL, label TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sms_trust_user ON sms_trusted_browsers_v542(user_id);
CREATE TABLE IF NOT EXISTS sms_rate_v542 (
 bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL DEFAULT 0, expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS sms_send_clock_v542 (
 user_id INTEGER PRIMARY KEY REFERENCES system_users(id) ON DELETE CASCADE,
 next_at BIGINT NOT NULL DEFAULT 0
);
'''

def ensure_schema():
    with connection() as conn:
        conn.executescript(SCHEMA)

def digest(value: str) -> str:
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()

def normalize_phone(phone: str) -> str:
    raw = re.sub(r'[\s().-]', '', str(phone))
    if re.fullmatch(r'0[35789][0-9]{8}', raw):
        raw = '+84' + raw[1:]
    if not re.fullmatch(r'\+[1-9][0-9]{7,14}', raw):
        raise SmsError('S\u1ed1 \u0111i\u1ec7n tho\u1ea1i kh\u00f4ng h\u1ee3p l\u1ec7. V\u00ed d\u1ee5: 09xxxxxxxx ho\u1eb7c +84xxxxxxxxx.')
    return raw

def mask_phone(phone):
    return phone[:3] + '*' * max(4, len(phone) - 5) + phone[-2:]

def _lock_user(conn, uid):
    if conn.mode == 'postgres':
        conn.execute('SELECT id FROM system_users WHERE id=? FOR UPDATE', (uid,)).fetchone()
    else:
        conn.execute('UPDATE system_users SET id=id WHERE id=?', (uid,))

def _row(conn, sql, args=()):
    value = conn.execute(sql, args).fetchone()
    return dict(value) if value is not None else None

def _user(conn, uid):
    user = _row(conn, 'SELECT * FROM system_users WHERE id=?', (uid,))
    profile = _row(conn, 'SELECT account_status FROM account_profiles WHERE user_id=?', (uid,)) or {}
    if not user or not user['active'] or profile.get('account_status', 'ACTIVE') in ('DISABLED', 'LOCKED', 'REJECTED', 'PENDING'):
        raise SmsError(EXPIRED, 'CHALLENGE_INVALID', 401)
    return user

def credential_tag(user, conn=None):
    if conn is None:
        with connection() as current:
            return credential_tag(user, current)
    uid = int(user['id'])
    sms = _row(conn, 'SELECT * FROM sms_factors_v542 WHERE user_id=?', (uid,)) or {}
    totp = _row(conn, 'SELECT enabled,secret_enc,method FROM account_mfa WHERE user_id=?', (uid,)) or {}
    values = [user.get(k) for k in ('id', 'password_salt', 'password_hash', 'active', 'role')]
    values += [sms, totp]
    return digest(json.dumps(values, sort_keys=True))

def factor(uid):
    return fetchone('SELECT * FROM sms_factors_v542 WHERE user_id=? AND enabled=1', (uid,)) or {}

def _audit(event, uid, status='SUCCESS', **detail):
    # Deliberate allowlist. Never log code, phone, credentials, raw cookies or challenge IDs.
    add_audit_event('SECURITY', event, status, detail={'user_id': uid, **detail})

def _take_budget(conn, scope, seconds, limit):
    now = int(time.time())
    end = (now // seconds + 1) * seconds
    bucket = digest(scope) + ':' + str(end)
    conn.execute('INSERT INTO sms_rate_v542(bucket,hits,expires_at) VALUES(?,0,?) ON CONFLICT(bucket) DO NOTHING', (bucket, end))
    result = conn.execute('UPDATE sms_rate_v542 SET hits=hits+1 WHERE bucket=? AND hits<?', (bucket, limit))
    if result.rowcount != 1:
        raise SmsError('Qu\u00e1 nhi\u1ec1u y\u00eau c\u1ea7u. Vui l\u00f2ng th\u1eed l\u1ea1i sau.', 'RATE_LIMITED', 429, end-now)

def _reserve_send(uid, phone, ip):
    now = int(time.time())
    with connection() as conn:
        _lock_user(conn, uid)
        clock = _row(conn, 'SELECT next_at FROM sms_send_clock_v542 WHERE user_id=?', (uid,))
        if clock and clock['next_at'] > now:
            raise SmsError('Vui l\u00f2ng ch\u1edd tr\u01b0\u1edbc khi g\u1eedi l\u1ea1i m\u00e3.', 'RATE_LIMITED', 429, clock['next_at']-now)
        # Reserve before network I/O. Failed sends still count toward quotas.
        scopes = [('global',86400,100), ('ip:'+ip,3600,20), ('phone:'+phone,3600,5),
                  ('phone:'+phone,86400,10), ('user:'+str(uid),3600,5), ('user:'+str(uid),86400,10)]
        for scope, seconds, limit in sorted(scopes):
            _take_budget(conn, scope, seconds, limit)
        conn.execute('INSERT INTO sms_send_clock_v542(user_id,next_at) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET next_at=excluded.next_at', (uid, now+60))
        conn.execute('DELETE FROM sms_rate_v542 WHERE expires_at<?', (now-86400,))

def _new_challenge(uid, purpose, phone, binding, session=''):
    raw = secrets.token_urlsafe(32)
    now = int(time.time())
    with connection() as conn:
        _lock_user(conn, uid)
        user = _user(conn, uid)
        conn.execute("UPDATE sms_challenges_v542 SET state='CANCELLED',consumed_at=? WHERE user_id=? AND purpose=? AND consumed_at=0", (now,uid,purpose))
        conn.execute('DELETE FROM sms_challenges_v542 WHERE expires_at<?', (now-86400,))
        conn.execute('INSERT INTO sms_challenges_v542(id_hash,user_id,purpose,phone_enc,binding_hash,session_hash,credential_tag,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (digest(raw),uid,purpose,encrypt_bytes(phone.encode()).decode(),digest(binding),digest(session),credential_tag(user,conn),'NEW',now,now+CHALLENGE_TTL))
    return {'mfa_required': True, 'mfa_setup_required': False, 'mfa_method': 'SMS',
            'challenge_id': raw, 'destination_hint': mask_phone(phone),
            'expires_in': CHALLENGE_TTL, 'provider_ready': provider.configured(), 'purpose': purpose}

def begin_login(user, binding):
    item = factor(int(user['id']))
    if not item:
        raise SmsError(EXPIRED, status=401)
    return _new_challenge(int(user['id']), 'LOGIN', decrypt_bytes(item['phone_enc'].encode()).decode(), binding)

def _get_challenge(conn, cid, binding, session='', lock=False):
    if not (20 <= len(cid) <= 128 and 20 <= len(binding) <= 128):
        raise SmsError(EXPIRED, 'CHALLENGE_INVALID', 401)
    item = _row(conn, 'SELECT * FROM sms_challenges_v542 WHERE id_hash=?', (digest(cid),))
    if not item:
        raise SmsError(EXPIRED, 'CHALLENGE_INVALID', 401)
    if lock:
        _lock_user(conn, item['user_id'])
        item = _row(conn, 'SELECT * FROM sms_challenges_v542 WHERE id_hash=?', (digest(cid),))
    if (item['consumed_at'] or item['state'] == 'CANCELLED' or item['expires_at'] <= int(time.time())
        or not hmac.compare_digest(item['binding_hash'], digest(binding))
        or (item['purpose'] != 'LOGIN' and not hmac.compare_digest(item['session_hash'], digest(session)))):
        raise SmsError(EXPIRED, 'CHALLENGE_INVALID', 401)
    if item['purpose'] != 'LOGIN':
        from . import auth
        active = auth.user_for_token(session)
        if not active or int(active['id']) != int(item['user_id']):
            raise SmsError(EXPIRED, 'CHALLENGE_INVALID', 401)
    user = _user(conn, item['user_id'])
    if not hmac.compare_digest(item['credential_tag'], credential_tag(user, conn)):
        raise SmsError(EXPIRED, 'CHALLENGE_INVALID', 401)
    return item, user

def send(cid, binding, ip, session=''):
    with connection() as conn:
        item, _ = _get_challenge(conn,cid,binding,session)
    try:
        sender = provider.get_provider()
    except provider.ProviderError:
        raise SmsError(UNAVAILABLE, 'SMS_NOT_CONFIGURED', 503) from None
    phone = decrypt_bytes(item['phone_enc'].encode()).decode()
    _reserve_send(item['user_id'], phone, ip)
    with connection() as conn:
        item, _ = _get_challenge(conn,cid,binding,session,lock=True)
        if item['state'] == 'SENDING':
            raise SmsError('Y\u00eau c\u1ea7u \u0111ang \u0111\u01b0\u1ee3c x\u1eed l\u00fd.', 'SMS_BUSY', 409)
        conn.execute("UPDATE sms_challenges_v542 SET state='SENDING',last_sent_at=? WHERE id_hash=?", (int(time.time()), digest(cid)))
    try:
        sid = sender.send(phone)
    except provider.ProviderError:
        with connection() as conn:
            conn.execute("UPDATE sms_challenges_v542 SET state='FAILED' WHERE id_hash=? AND state='SENDING' AND consumed_at=0", (digest(cid),))
        _audit('SMS_SEND_FAILED',item['user_id'],'FAILED')
        raise SmsError(UNAVAILABLE, 'SMS_UNAVAILABLE', 503) from None
    with connection() as conn:
        item, _ = _get_challenge(conn,cid,binding,session,lock=True)
        conn.execute("UPDATE sms_challenges_v542 SET state='SENT',provider_sid=? WHERE id_hash=?", (sid,digest(cid)))
    _audit('SMS_SEND_ACCEPTED',item['user_id'])
    return {'accepted': True, 'resend_after': 60, 'expires_in': max(0,item['expires_at']-int(time.time())),
            'message': 'Nh\u00e0 cung c\u1ea5p \u0111\u00e3 ti\u1ebfp nh\u1eadn y\u00eau c\u1ea7u. Vui l\u00f2ng ch\u1edd tin nh\u1eafn tr\u00ean \u0111i\u1ec7n tho\u1ea1i.'}

def verify(cid, binding, code, session=''):
    from . import auth
    raw = str(code).strip()
    recovery = not bool(re.fullmatch(r'[0-9]{6}', raw))
    with connection() as conn:
        item, user = _get_challenge(conn,cid,binding,session,lock=True)
        if item['attempts'] >= 5:
            raise SmsError(INVALID, 'ATTEMPTS_EXHAUSTED', 429)
        if recovery and item['purpose'] == 'ENROLL':
            raise SmsError('Nh\u1eadp m\u00e3 SMS \u0111\u1ec3 x\u00e1c minh s\u1ed1 \u0111i\u1ec7n tho\u1ea1i m\u1edbi.', status=400)
        _take_budget(conn, 'verify:'+str(item['user_id']), 900, 10)
        conn.execute('UPDATE sms_challenges_v542 SET attempts=attempts+1 WHERE id_hash=?', (digest(cid),))
    # Provider failure consumes an attempt, never becomes successful verification.
    if not recovery:
        if item['state'] != 'SENT' or not item['provider_sid']:
            raise SmsError('H\u00e3y g\u1eedi m\u00e3 SMS tr\u01b0\u1edbc khi x\u00e1c minh.', status=400)
        try:
            accepted = provider.get_provider().check(item['provider_sid'],decrypt_bytes(item['phone_enc'].encode()).decode(),raw)
        except provider.ProviderError:
            raise SmsError(UNAVAILABLE,'SMS_UNAVAILABLE',503) from None
        if not accepted:
            _audit('SMS_VERIFY_FAILED',item['user_id'],'FAILED')
            raise SmsError(INVALID,'INVALID_CODE',401)
    codes = []
    with connection() as conn:
        item, user = _get_challenge(conn,cid,binding,session,lock=True)
        if recovery:
            if not re.fullmatch(r'[A-Za-z0-9-]{12,40}',raw):
                raise SmsError(INVALID,'INVALID_CODE',401)
            used = conn.execute('UPDATE account_mfa_recovery_codes SET used_at=? WHERE user_id=? AND code_hash=? AND used_at IS NULL', (utc_now(),item['user_id'],auth._recovery_hash(raw)))
            if used.rowcount != 1:
                raise SmsError(INVALID,'INVALID_CODE',401)
        conn.execute("UPDATE sms_challenges_v542 SET state='CONSUMED',consumed_at=? WHERE id_hash=? AND consumed_at=0", (int(time.time()),digest(cid)))
        if item['purpose'] == 'ENROLL':
            conn.execute('INSERT INTO sms_factors_v542(user_id,phone_enc,enabled,verified_at) VALUES(?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET phone_enc=excluded.phone_enc,enabled=1,verified_at=excluded.verified_at', (item['user_id'],item['phone_enc'],utc_now()))
            # Only replace the old TOTP after both password/old-factor proof and
            # verification of the NEW phone. Existing protections never disappear on upgrade.
            conn.execute('DELETE FROM account_mfa WHERE user_id=?', (item['user_id'],))
            conn.execute('DELETE FROM account_mfa_recovery_codes WHERE user_id=?',(item['user_id'],))
            for _ in range(8):
                value = secrets.token_hex(12).upper()
                value = '-'.join(value[i:i+6] for i in range(0,24,6))
                codes.append(value)
                conn.execute('INSERT INTO account_mfa_recovery_codes(user_id,code_hash,used_at,created_at) VALUES(?,?,NULL,?)',(item['user_id'],auth._recovery_hash(value),utc_now()))
            _revoke_sql(conn,item['user_id'])
    _audit('SMS_'+item['purpose']+'_VERIFIED',item['user_id'],method='RECOVERY' if recovery else 'SMS')
    if item['purpose'] == 'STEPUP':
        auth.mark_factor_verified(session)
        return {'ok': True, 'purpose': 'STEPUP', 'message': 'X\u00e1c minh th\u00e0nh c\u00f4ng. H\u00e3y th\u1ef1c hi\u1ec7n l\u1ea1i thao t\u00e1c.'}
    if item['purpose'] == 'ENROLL':
        auth.revoke_user_sessions(item['user_id'])
    out = auth._issue_session(user)
    auth.mark_factor_verified(out['token'])
    out.update(mfa_verified=True,purpose=item['purpose'],recovery_codes=codes)
    return out

def _revoke_sql(conn, uid):
    conn.execute('UPDATE sms_trusted_browsers_v542 SET revoked=1 WHERE user_id=?',(uid,))
    conn.execute("UPDATE sms_challenges_v542 SET state='CANCELLED',consumed_at=? WHERE user_id=? AND consumed_at=0",(int(time.time()),uid))

def revoke_user(uid):
    with connection() as conn:
        _revoke_sql(conn,uid)

def trust(user, raw, allowed=True):
    if not allowed or not raw or len(raw)>128:
        return False
    now = int(time.time())
    with connection() as conn:
        current = _user(conn,int(user['id']))
        item = _row(conn,'SELECT * FROM sms_trusted_browsers_v542 WHERE id_hash=? AND user_id=?',(digest(raw),int(user['id'])))
        valid = bool(item and not item['revoked'] and item['expires_at']>now
                     and hmac.compare_digest(item['credential_tag'],credential_tag(current,conn)))
        if valid:
            conn.execute('UPDATE sms_trusted_browsers_v542 SET last_used_at=? WHERE id_hash=?',(now,digest(raw)))
        return valid

def issue_trust(uid, user_agent, old_cookie=''):
    raw, now = secrets.token_urlsafe(32),int(time.time())
    with connection() as conn:
        _lock_user(conn,uid)
        user = _user(conn,uid)
        if old_cookie:
            conn.execute('UPDATE sms_trusted_browsers_v542 SET revoked=1 WHERE user_id=? AND id_hash=?',(uid,digest(old_cookie)))
        conn.execute('DELETE FROM sms_trusted_browsers_v542 WHERE expires_at<?',(now-86400,))
        count = _row(conn,'SELECT COUNT(*) AS n FROM sms_trusted_browsers_v542 WHERE user_id=? AND revoked=0 AND expires_at>?',(uid,now))['n']
        if count >= 10:
            conn.execute('UPDATE sms_trusted_browsers_v542 SET revoked=1 WHERE id_hash=(SELECT id_hash FROM sms_trusted_browsers_v542 WHERE user_id=? AND revoked=0 ORDER BY created_at LIMIT 1)',(uid,))
        conn.execute('INSERT INTO sms_trusted_browsers_v542(id_hash,user_id,credential_tag,created_at,expires_at,last_used_at,label) VALUES(?,?,?,?,?,?,?)',
            (digest(raw),uid,credential_tag(user,conn),now,now+TRUST_TTL,now,str(user_agent)[:120]))
    _audit('TRUSTED_BROWSER_CREATED',uid,days=30)
    return raw

def status(uid, session):
    from . import auth
    item = factor(uid)
    totp = auth._mfa_record(uid)
    enabled = bool(item or totp.get('enabled'))
    recovery = fetchone('SELECT COUNT(*) AS n FROM account_mfa_recovery_codes WHERE user_id=? AND used_at IS NULL',(uid,)) or {}
    browsers = fetchall('SELECT id_hash,created_at,expires_at,last_used_at,label FROM sms_trusted_browsers_v542 WHERE user_id=? AND revoked=0 AND expires_at>? ORDER BY created_at DESC',(uid,int(time.time())))
    return {'enabled':enabled,'method':'SMS' if item else 'TOTP' if totp.get('enabled') else '',
            'destination_hint':mask_phone(decrypt_bytes(item['phone_enc'].encode()).decode()) if item else '',
            'provider_ready':provider.configured(),'fresh_verification':auth.factor_is_fresh(session),
            'recovery_remaining':int(recovery.get('n') or 0),'trusted_browsers':browsers}

def begin_enroll(user, password, phone, binding, session):
    from . import auth
    confirmed = auth._authenticate_password(user['username'],password)
    if int(confirmed['id'])!=int(user['id']):
        raise SmsError(EXPIRED,status=401)
    prior = factor(user['id']) or auth._mfa_record(user['id']).get('enabled')
    if prior and not auth.factor_is_fresh(session):
        raise SmsError('H\u00e3y x\u00e1c minh b\u1ea3o m\u1eadt tr\u01b0\u1edbc khi \u0111\u1ed5i ph\u01b0\u01a1ng th\u1ee9c/s\u1ed1 \u0111i\u1ec7n tho\u1ea1i.', 'STEP_UP_REQUIRED',403)
    if not provider.configured():
        raise SmsError('Ch\u01b0a c\u1ea5u h\u00ecnh d\u1ecbch v\u1ee5 SMS. T\u00ednh n\u0103ng ch\u01b0a \u0111\u01b0\u1ee3c b\u1eadt; m\u1eadt kh\u1ea9u hi\u1ec7n t\u1ea1i kh\u00f4ng thay \u0111\u1ed5i.', 'SMS_NOT_CONFIGURED',503)
    return _new_challenge(user['id'],'ENROLL',normalize_phone(phone),binding,session)

def begin_stepup(user, password, binding, session):
    from . import auth
    auth._authenticate_password(user['username'],password)
    item = factor(user['id'])
    if not item:
        raise SmsError('T\u00e0i kho\u1ea3n ch\u01b0a b\u1eadt SMS. V\u1edbi Authenticator c\u0169, h\u00e3y \u0111\u0103ng xu\u1ea5t r\u1ed3i x\u00e1c minh l\u1ea1i.', 'SMS_NOT_ENROLLED',409)
    return _new_challenge(user['id'],'STEPUP',decrypt_bytes(item['phone_enc'].encode()).decode(),binding,session)

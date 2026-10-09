"""HTTP boundary for SMS security. Cookies are never returned in JSON."""
from __future__ import annotations
import re
import secrets
from urllib.parse import urlsplit
from fastapi import HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from . import auth
from . import sms_auth_v542 as sms

class StrictPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
class ChallengePayload(StrictPayload):
    challenge_id: str = Field(min_length=20,max_length=128)
class VerifyPayload(ChallengePayload):
    code: str = Field(min_length=6,max_length=40)
    trust_browser: bool = False
class EnrollPayload(StrictPayload):
    current_password: str = Field(min_length=1,max_length=256)
    phone: str = Field(min_length=8,max_length=25)
class StepUpPayload(StrictPayload):
    current_password: str = Field(min_length=1,max_length=256)
class DisablePayload(StepUpPayload):
    confirm_disable: bool = False

LOOPBACK = {'127.0.0.1','::1','localhost'}

def secure_transport(request: Request) -> bool:
    if request.url.scheme == 'https':
        return True
    return bool(request.client and request.client.host in LOOPBACK and (request.url.hostname or '').lower() in LOOPBACK)

def browser_guard(request: Request):
    """Protect auth cookies from insecure LAN and cross-origin mutations.

    Local HTTP is explicitly confined to loopback. LAN requires correctly
    configured HTTPS; a VPN does not by itself change the URL scheme.
    """
    path = request.url.path
    if not path.startswith('/api/v1/') or path.startswith('/api/v1/sync/'):
        return None
    if path.startswith('/api/v1/auth/') and not secure_transport(request):
        return JSONResponse({'detail':'Truy c\u1eadp t\u1eeb m\u1ea1ng LAN c\u1ea7n HTTPS. Tr\u00ean PC trung t\u00e2m, d\u00f9ng http://127.0.0.1:8100.', 'code':'HTTPS_REQUIRED'},status_code=403)
    if request.method in {'POST','PUT','PATCH','DELETE'}:
        origin = request.headers.get('origin')
        expected = str(request.url).split('/',3)[:3]
        expected = '/'.join(expected).lower()
        if request.headers.get('sec-fetch-site','') == 'cross-site' or (origin and origin.lower().rstrip('/') != expected):
            return JSONResponse({'detail':'Y\u00eau c\u1ea7u kh\u00e1c ngu\u1ed3n b\u1ecb t\u1eeb ch\u1ed1i.','code':'ORIGIN_REJECTED'},status_code=403)
        # JSON endpoints cannot be submitted by an ordinary cross-site HTML form.
        if path.startswith('/api/v1/auth/') and request.headers.get('content-type','').split(';',1)[0].strip() != 'application/json':
            return JSONResponse({'detail':'Y\u00eau c\u1ea7u c\u1ea7n d\u1eef li\u1ec7u JSON.','code':'JSON_REQUIRED'},status_code=415)
    return None

def set_pending(response, binding, request):
    response.set_cookie(sms.PENDING_COOKIE,binding,max_age=sms.CHALLENGE_TTL,httponly=True,
                        secure=request.url.scheme=='https',samesite='strict',path='/')
    response.headers['Cache-Control']='no-store'

def set_auth_result(response, request, result, auth_cookie, trust_browser=False):
    result = dict(result)
    raw = result.pop('token',None)
    if raw:
        response.set_cookie(auth_cookie,raw,max_age=int(result.get('expires_in') or 28800),
                            httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
        result['authenticated']=True
    if raw and trust_browser and result.get('mfa_verified'):
        if not secure_transport(request):
            raise HTTPException(403,'HTTPS required')
        cookie = sms.issue_trust(int(result['user']['id']),request.headers.get('user-agent','Browser'),request.cookies.get(sms.TRUST_COOKIE,''))
        response.set_cookie(sms.TRUST_COOKIE,cookie,max_age=sms.TRUST_TTL,httponly=True,
                            secure=request.url.scheme=='https',samesite='strict',path='/')
        result['trusted_browser']=True
    response.delete_cookie(sms.PENDING_COOKIE,path='/')
    response.headers['Cache-Control']='no-store'
    return result

def _error(exc):
    if isinstance(exc,sms.SmsError):
        headers={'Cache-Control':'no-store'}
        if exc.retry_after:
            headers['Retry-After']=str(exc.retry_after)
        raise HTTPException(exc.status,{'message':str(exc),'code':exc.code,'retry_after':exc.retry_after},headers=headers)
    raise HTTPException(400,str(exc))

def sensitive_action_guard(request, user, session):
    if request.method in {'GET','HEAD','OPTIONS'}:
        return None
    path=request.url.path
    sensitive = (path.startswith('/api/v1/admin/users') or '/restore' in path
                 or path.startswith('/api/v1/auth/admin-security'))
    if not sensitive:
        return None
    uid=int(user['id'])
    enabled=bool(sms.factor(uid) or auth._mfa_record(uid).get('enabled'))
    if enabled and not auth.factor_is_fresh(session):
        return JSONResponse({'detail':'H\u00e3y v\u00e0o B\u1ea3o m\u1eadt t\u00e0i kho\u1ea3n, x\u00e1c minh l\u1ea1i r\u1ed3i th\u1ef1c hi\u1ec7n thao t\u00e1c n\u00e0y.','code':'STEP_UP_REQUIRED'},status_code=403)
    return None

def install_sms_routes(app, request_user, request_token, auth_cookie):
    @app.exception_handler(RequestValidationError)
    async def safe_validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith('/api/v1/auth/'):
            return JSONResponse({'detail': 'Dữ liệu yêu cầu không hợp lệ.', 'code': 'INVALID_REQUEST'},
                                status_code=422, headers={'Cache-Control': 'no-store'})
        return await request_validation_exception_handler(request, exc)

    def user(request):
        found=request_user(request)
        if not found:
            raise HTTPException(401,'C\u1ea7n \u0111\u0103ng nh\u1eadp')
        return found

    @app.get('/api/v1/auth/sms/security')
    def security(request:Request, response:Response):
        response.headers['Cache-Control']='no-store'
        return sms.status(int(user(request)['id']),request_token(request))

    @app.post('/api/v1/auth/sms/enroll')
    def enroll(payload:EnrollPayload,request:Request,response:Response):
        actor=user(request)
        binding=secrets.token_urlsafe(32)
        try:
            out=sms.begin_enroll(actor,payload.current_password,payload.phone,binding,request_token(request))
            set_pending(response,binding,request)
            return out
        except ValueError as exc:
            _error(exc)

    @app.post('/api/v1/auth/sms/step-up')
    def stepup(payload:StepUpPayload,request:Request,response:Response):
        actor=user(request)
        binding=secrets.token_urlsafe(32)
        try:
            out=sms.begin_stepup(actor,payload.current_password,binding,request_token(request))
            set_pending(response,binding,request)
            return out
        except ValueError as exc:
            _error(exc)

    @app.post('/api/v1/auth/sms/send')
    def send(payload:ChallengePayload,request:Request,response:Response):
        response.headers['Cache-Control']='no-store'
        try:
            return sms.send(payload.challenge_id,request.cookies.get(sms.PENDING_COOKIE,''),
                            request.client.host if request.client else 'unknown',request_token(request))
        except ValueError as exc:
            _error(exc)

    @app.post('/api/v1/auth/sms/verify')
    def verify(payload:VerifyPayload,request:Request,response:Response):
        try:
            out=sms.verify(payload.challenge_id,request.cookies.get(sms.PENDING_COOKIE,''),payload.code,request_token(request))
            return set_auth_result(response,request,out,auth_cookie,payload.trust_browser)
        except ValueError as exc:
            _error(exc)

    @app.post('/api/v1/auth/sms/cancel')
    def cancel(payload:ChallengePayload,request:Request,response:Response):
        try:
            with sms.connection() as conn:
                item,_=sms._get_challenge(conn,payload.challenge_id,request.cookies.get(sms.PENDING_COOKIE,''),request_token(request),lock=True)
                conn.execute("UPDATE sms_challenges_v542 SET state='CANCELLED',consumed_at=? WHERE id_hash=?",(int(sms.time.time()),sms.digest(payload.challenge_id)))
        except sms.SmsError:
            pass
        response.delete_cookie(sms.PENDING_COOKIE,path='/')
        response.headers['Cache-Control']='no-store'
        return {'ok':True}

    @app.delete('/api/v1/auth/sms/trusted-browsers/{browser_id}')
    def revoke_browser(browser_id:str,request:Request,response:Response):
        actor=user(request)
        if not re.fullmatch(r'[a-f0-9]{64}',browser_id):
            raise HTTPException(400,'Invalid browser ID')
        with sms.connection() as conn:
            conn.execute('UPDATE sms_trusted_browsers_v542 SET revoked=1 WHERE user_id=? AND id_hash=?',(int(actor['id']),browser_id))
        if sms.digest(request.cookies.get(sms.TRUST_COOKIE,''))==browser_id:
            response.delete_cookie(sms.TRUST_COOKIE,path='/')
        sms._audit('TRUSTED_BROWSER_REVOKED',int(actor['id']))
        return {'ok':True}

    @app.post('/api/v1/auth/sms/revoke-all')
    def revoke_all(request:Request,response:Response):
        actor=user(request)
        sms.revoke_user(int(actor['id']))
        # Revocation prevents the next password login from skipping OTP; it does
        # not silently kill this authenticated session needed to finish recovery.
        response.delete_cookie(sms.TRUST_COOKIE,path='/')
        sms._audit('ALL_TRUSTED_BROWSERS_REVOKED',int(actor['id']))
        return {'ok':True}

    @app.post('/api/v1/auth/sms/disable')
    def disable(payload:DisablePayload,request:Request,response:Response):
        actor=user(request)
        if not payload.confirm_disable:
            raise HTTPException(400,'C\u1ea7n x\u00e1c nh\u1eadn t\u1eaft SMS')
        try:
            auth._authenticate_password(actor['username'],payload.current_password)
            if not auth.factor_is_fresh(request_token(request)):
                raise sms.SmsError('H\u00e3y x\u00e1c minh l\u1ea1i b\u1eb1ng SMS ho\u1eb7c m\u00e3 kh\u00f4i ph\u1ee5c tr\u01b0\u1edbc khi t\u1eaft.', 'STEP_UP_REQUIRED',403)
            with sms.connection() as conn:
                sms._lock_user(conn,int(actor['id']))
                conn.execute('DELETE FROM sms_factors_v542 WHERE user_id=?',(int(actor['id']),))
                conn.execute('DELETE FROM account_mfa_recovery_codes WHERE user_id=?',(int(actor['id']),))
                sms._revoke_sql(conn,int(actor['id']))
            auth.revoke_user_sessions(int(actor['id']))
            response.delete_cookie(auth_cookie,path='/')
            response.delete_cookie(sms.TRUST_COOKIE,path='/')
            sms._audit('SMS_DISABLED',int(actor['id']))
            return {'ok':True,'login_required':True}
        except ValueError as exc:
            _error(exc)

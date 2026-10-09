"""Twilio Verify adapter. No demo delivery, arbitrary URL or plaintext secret files."""
from __future__ import annotations
import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from .config import CONFIG_DIR
from .secret_store import load_secret, save_secret

CONFIG_PATH = CONFIG_DIR / 'sms_verify_provider.dpapi'

class ProviderError(RuntimeError):
    def __init__(self, code: str = 'SMS_UNAVAILABLE'):
        self.code = code
        super().__init__(code)

@dataclass(frozen=True)
class VerifyConfig:
    account_sid: str
    api_key_sid: str
    api_secret: str
    service_sid: str
    def validate(self) -> None:
        for value, prefix in [(self.account_sid, 'AC'), (self.api_key_sid, 'SK'), (self.service_sid, 'VA')]:
            if not re.fullmatch(prefix + r'[0-9a-fA-F]{32}', value):
                raise ProviderError('SMS_CONFIGURATION_INVALID')
        if not self.api_secret or len(self.api_secret) > 256 or any(c in self.api_secret for c in '\r\n'):
            raise ProviderError('SMS_CONFIGURATION_INVALID')

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('SMS_UNAVAILABLE')

def load_config() -> VerifyConfig:
    try:
        # The environment is for deployment secret injection, not a demo mode.
        if os.getenv('BTMH_SMS_VERIFY_SERVICE_SID'):
            data = dict(account_sid=os.getenv('BTMH_SMS_ACCOUNT_SID', ''),
                        api_key_sid=os.getenv('BTMH_SMS_API_KEY_SID', ''),
                        api_secret=os.getenv('BTMH_SMS_API_SECRET', ''),
                        service_sid=os.environ['BTMH_SMS_VERIFY_SERVICE_SID'])
        else:
            raw = load_secret(CONFIG_PATH)
            if not raw:
                raise ProviderError('SMS_NOT_CONFIGURED')
            data = json.loads(raw)
        config = VerifyConfig(**data)
        config.validate()
        return config
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('SMS_CONFIGURATION_INVALID') from None

def save_config(config: VerifyConfig) -> None:
    config.validate()
    # Windows current-user scope, not machine scope. Run as the app's Windows user.
    save_secret(CONFIG_PATH, json.dumps(config.__dict__), machine_scope=False)

def configured() -> bool:
    try:
        load_config()
        return True
    except ProviderError:
        return False

class TwilioVerifyProvider:
    def __init__(self, config: VerifyConfig | None = None):
        self.config = config or load_config()
        self.config.validate()

    def _post(self, resource: str, fields: dict) -> dict:
        url = f'https://verify.twilio.com/v2/Services/{self.config.service_sid}/{resource}'
        auth = base64.b64encode(f'{self.config.api_key_sid}:{self.config.api_secret}'.encode()).decode('ascii')
        request = urllib.request.Request(url, urllib.parse.urlencode(fields).encode('ascii'),
            {'Authorization': 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded',
             'Accept': 'application/json'}, method='POST')
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                if response.status not in (200, 201):
                    raise ProviderError()
                result = json.loads(response.read(32768))
                if not isinstance(result, dict):
                    raise ProviderError()
                return result
        except urllib.error.HTTPError as exc:
            # Do not include provider bodies, URLs, phone numbers or credentials in logs/API.
            if exc.code == 429:
                raise ProviderError('SMS_PROVIDER_LIMIT') from None
            if resource == 'VerificationCheck' and exc.code in (400, 404):
                raise ProviderError('SMS_INVALID_CODE') from None
            raise ProviderError() from None
        except ProviderError:
            raise
        except Exception:
            raise ProviderError() from None

    def send(self, phone: str) -> str:
        result = self._post('Verifications', {'To': phone, 'Channel': 'sms'})
        sid = str(result.get('sid') or '')
        if (result.get('status') != 'pending' or result.get('to') != phone
                or result.get('channel') != 'sms' or not re.fullmatch(r'VE[0-9a-fA-F]{32}', sid)):
            raise ProviderError()
        return sid

    def check(self, sid: str, phone: str, code: str) -> bool:
        if not re.fullmatch(r'[0-9]{6}', code) or not re.fullmatch(r'VE[0-9a-fA-F]{32}', sid):
            return False
        try:
            result = self._post('VerificationCheck', {'VerificationSid': sid, 'Code': code})
        except ProviderError as exc:
            if exc.code == 'SMS_INVALID_CODE':
                return False
            raise
        # Twilio documents status as authoritative; valid is a legacy optional field.
        return bool(result.get('status') == 'approved' and result.get('valid', True) is True
                    and result.get('sid') == sid and result.get('to') == phone
                    and result.get('channel') == 'sms')

def get_provider() -> TwilioVerifyProvider:
    return TwilioVerifyProvider()

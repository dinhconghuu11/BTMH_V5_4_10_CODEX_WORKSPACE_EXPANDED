"""Local deployment helper. Saves Verify credentials in Windows user DPAPI.

No SMS is sent by this script. A verified phone is enrolled in the web UI.
"""
from __future__ import annotations
import getpass
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from module_app.sms_provider_v542 import VerifyConfig, save_config, ProviderError
from module_app.secret_store import SecretStoreError

def main():
    if os.name != 'nt':
        print('Cau hinh nay dung Windows DPAPI. Khong ghi secret ra file ro tren he dieu han khac.')
        return 2
    print('BAO TIN MANH HAI - CAU HINH SMS (TWILIO VERIFY)')
    print('Chay bang cung tai khoan Windows chay ung dung, KHONG Run as administrator.')
    print('Can tai khoan nha cung cap, Verify Service, API Key va quyen gui SMS den Viet Nam.')
    print('Chon Verify Service co ma 6 so. Dich vu SMS co phi theo nha cung cap.')
    print('Khong dan API Secret/ma OTP len chat, anh chup man hinh hoac file ho tro.')
    try:
        account=input('Account SID (AC...): ').strip()
        key=input('API Key SID (SK...): ').strip()
        service=input('Verify Service SID (VA...): ').strip()
        secret=getpass.getpass('API Secret (an khi nhap): ').strip()
        config=VerifyConfig(account,key,secret,service);config.validate()
        if input('Luu cau hinh vao DPAPI cua tai khoan Windows nay? Go LUU: ').strip()!='LUU':
            print('Da huy; khong thay doi cau hinh.')
            return 1
        save_config(config)
        print('[OK] Da luu cau hinh duoc bao ve. CHUA kiem chung gui SMS that.')
        print('Khoi dong lai he thong. Vao Tai khoan & phan quyen -> Bao mat tai khoan.')
        print('Nhap mat khau, so dien thoai -> Bat SMS -> Gui ma -> Xac minh -> luu ma khoi phuc.')
        return 0
    except (KeyboardInterrupt,EOFError):
        print('\nDa huy.')
        return 1
    except (ProviderError,SecretStoreError):
        print('[ERROR] Cau hinh khong hop le hoac DPAPI khong luu duoc. Khong in secret.')
        return 2

if __name__=='__main__':
    raise SystemExit(main())

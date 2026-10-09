/* Phone OTP UI. No password, OTP, recovery code or trust token goes in storage. */
(() => {
  'use strict';
  const el = id => document.getElementById(id);
  let current = null, recovery = [], loginTimer = null, settingsTimer = null;
  const feedback = (message, bad=false) => { const node=el('smsSettingsFeedback'); if(node){node.textContent=message;node.classList.toggle('sms-error',bad);} };
  const request = (url,body) => api(url,{method:'POST',body:JSON.stringify(body)});
  function countdown(button,seconds,login=false){
    const end=Date.now()+seconds*1000;
    clearInterval(login?loginTimer:settingsTimer);
    const tick=()=>{
      const left=Math.ceil((end-Date.now())/1000);
      button.disabled=left>0;
      button.textContent=left>0?`Gửi lại sau ${left}s`:'Gửi lại SMS';
      // Literal Vietnamese is normalized below at build time.
      if(left<=0)clearInterval(login?loginTimer:settingsTimer);
    };
    if(login)loginTimer=setInterval(tick,1000);else settingsTimer=setInterval(tick,1000);
    tick();
  }
  function stopLoginTimer(){clearInterval(loginTimer);}
  async function sendLogin(){
    if(!state.mfaChallenge||state.mfaMethod!=='SMS')return;
    const id=state.mfaChallenge, button=el('gateSmsSend');button.disabled=true;
    try{
      const out=await request('/api/v1/auth/sms/send',{challenge_id:id});
      if(state.mfaChallenge!==id)return;
      setAuthFeedback('#gateMfaNote',out.message,'success');countdown(button,out.resend_after||60,true);
    }catch(e){
      if(state.mfaChallenge!==id)return;
      setAuthFeedback('#gateMfaNote',e.message,'error');
      if(e.retryAfter)countdown(button,e.retryAfter,true);else button.disabled=false;
    }
  }
  async function loadSecurity(){
    if(!el('smsSecuritySummary'))return;
    try{
      const data=await api('/api/v1/auth/sms/security');
      el('adminSecurityState').textContent=data.enabled?'ĐÃ BẬT':'CHƯA BẬT';
      el('adminSecurityHeroState').textContent=data.enabled?'ĐÃ BẬT XÁC MINH':'MẬT KHẨU';
      el('smsSecuritySummary').textContent=data.method==='SMS'
        ?`SMS: ${data.destination_hint}. Còn ${data.recovery_remaining} mã khôi phục.`
        :data.method==='TOTP'?'Tài khoản đang dùng Authenticator. Chỉ thay thế sau khi xác minh số điện thoại mới.'
        :'Đăng nhập bằng mật khẩu. SMS là tùy chọn, chỉ bật sau khi xác minh số điện thoại.';
      el('smsProviderNote').textContent=data.provider_ready
        ?'Đã có cấu hình SMS. Gửi và kiểm tra mã cần Internet; chưa có nghĩa tin nhắn đã đến máy.'
        :'Chưa kết nối dịch vụ SMS. Người cài đặt cần cấu hình nhà cung cấp trước. Không gửi mã thử nghiệm.';
      el('smsEnrollBtn').disabled=!data.provider_ready;
      el('smsStepUpBtn').disabled=data.method!=='SMS';
      el('smsDisable').disabled=data.method!=='SMS';
      const list=el('smsTrustedBrowsers');list.replaceChildren();
      if(!data.trusted_browsers.length)list.textContent='Chưa có trình duyệt được tin cậy.';
      data.trusted_browsers.forEach((device,index)=>{
        const row=document.createElement('div');row.className='sms-device';
        const label=document.createElement('span');
        label.textContent=`Trình duyệt ${index+1} - hết hạn ${new Date(device.expires_at*1000).toLocaleString('vi-VN')}`;
        const button=document.createElement('button');button.type='button';button.className='btn ghost';button.textContent='Thu hồi';
        button.addEventListener('click',async()=>{try{await api('/api/v1/auth/sms/trusted-browsers/'+encodeURIComponent(device.id_hash),{method:'DELETE'});await loadSecurity();}catch(e){feedback(e.message,true);}});
        row.append(label,button);list.append(row);
      });
    }catch(e){feedback(e.message,true);}
  }
  function openChallenge(data){
    current=data;clearInterval(settingsTimer);
    el('smsSettingsChallenge').classList.remove('hidden');
    el('smsSettingsDestination').textContent=`Xác minh ${data.destination_hint}`;
    el('smsSettingsCodeLabel').textContent=data.purpose==='ENROLL'?'Mã SMS 6 số':'Mã SMS hoặc mã khôi phục';
    el('smsSettingsCode').inputMode=data.purpose==='ENROLL'?'numeric':'text';
    el('smsSettingsCode').value='';el('smsSettingsTrust').checked=false;
    el('smsSettingsTrust').closest('label').classList.toggle('hidden',data.purpose==='STEPUP');
    el('smsSettingsSend').textContent='Gửi mã SMS';el('smsSettingsSend').disabled=!data.provider_ready;
    feedback('Chọn gửi mã SMS. Khi mất mạng, bước xác minh lại có thể dùng mã khôi phục.');
  }
  async function begin(enroll){
    const password=el('smsCurrentPassword').value;
    if(!password){feedback('Hãy nhập mật khẩu hiện tại.',true);el('smsCurrentPassword').focus();return;}
    const button=el(enroll?'smsEnrollBtn':'smsStepUpBtn');button.disabled=true;
    try{
      const out=await request(enroll?'/api/v1/auth/sms/enroll':'/api/v1/auth/sms/step-up',
        enroll?{current_password:password,phone:el('smsPhone').value}:{current_password:password});
      el('smsCurrentPassword').value='';openChallenge(out);
    }catch(e){feedback(e.message,true);}finally{await loadSecurity();}
  }
  async function cancelSettings(){
    const old=current;current=null;clearInterval(settingsTimer);
    el('smsSettingsCode').value='';el('smsSettingsChallenge').classList.add('hidden');
    if(old)await request('/api/v1/auth/sms/cancel',{challenge_id:old.challenge_id}).catch(()=>{});
  }
  async function sendSettings(){
    if(!current)return;const id=current.challenge_id, button=el('smsSettingsSend');button.disabled=true;
    try{
      const out=await request('/api/v1/auth/sms/send',{challenge_id:id});
      if(current?.challenge_id!==id)return;
      countdown(button,out.resend_after||60);feedback(out.message);
    }catch(e){
      feedback(e.message,true);
      if(e.retryAfter)countdown(button,e.retryAfter);else button.disabled=false;
    }
  }
  async function verifySettings(){
    if(!current)return;const id=current.challenge_id,button=el('smsSettingsVerify');button.disabled=true;
    try{
      const out=await request('/api/v1/auth/sms/verify',{challenge_id:id,code:el('smsSettingsCode').value.trim(),trust_browser:!!el('smsSettingsTrust').checked});
      current=null;clearInterval(settingsTimer);el('smsSettingsCode').value='';el('smsSettingsChallenge').classList.add('hidden');
      recovery=Array.isArray(out.recovery_codes)?out.recovery_codes:[];
      const list=el('smsRecoveryCodes');list.replaceChildren();
      recovery.forEach(value=>{const code=document.createElement('code');code.textContent=value;list.append(code);});
      el('smsRecoveryPanel').classList.toggle('hidden',recovery.length===0);
      feedback(recovery.length?'Đã bật SMS. Lưu mã khôi phục ngay; chúng chỉ hiển thị lần này.':'Đã xác minh lại. Thao tác nhạy cảm được cho phép trong 5 phút.');
      if(out.authenticated){const status=await api('/api/v1/auth/status');state.authUser=status.user;applyRoleUi(state.authUser);}
      await loadSecurity();
    }catch(e){feedback(e.message,true);}finally{button.disabled=false;}
  }
  function bind(){
    el('gateSmsSend')?.addEventListener('click',sendLogin);
    el('gateMfaCode')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();gateMfaVerify();}});
    el('gateUseRecovery')?.addEventListener('click',()=>{el('gateMfaCode').inputMode='text';el('gateMfaCode').placeholder='Mã khôi phục';el('gateMfaCode').focus();setAuthFeedback('#gateMfaNote','Nhập một mã khôi phục đã lưu. Mã này chỉ sử dụng một lần.');});
    el('smsEnrollForm')?.addEventListener('submit',e=>{e.preventDefault();begin(true);});
    el('smsStepUpBtn')?.addEventListener('click',()=>begin(false));
    el('smsSettingsSend')?.addEventListener('click',sendSettings);
    el('smsSettingsVerify')?.addEventListener('click',verifySettings);
    el('smsSettingsCancel')?.addEventListener('click',cancelSettings);
    el('smsCopyRecovery')?.addEventListener('click',()=>copyTextValue(recovery.join('\n')));
    el('smsSavedRecovery')?.addEventListener('click',()=>{recovery=[];el('smsRecoveryCodes').replaceChildren();el('smsRecoveryPanel').classList.add('hidden');});
    el('smsRevokeAll')?.addEventListener('click',async()=>{try{await request('/api/v1/auth/sms/revoke-all',{});await loadSecurity();feedback('Đã thu hồi các trình duyệt tin cậy. Đăng nhập lần tới sẽ cần xác minh.');}catch(e){feedback(e.message,true);}});
    el('smsDisable')?.addEventListener('click',async()=>{
      if(!confirm('Tắt SMS sẽ để tài khoản chỉ còn mật khẩu. Bạn chắc chắn muốn tắt?'))return;
      try{await request('/api/v1/auth/sms/disable',{current_password:el('smsCurrentPassword').value,confirm_disable:true});location.reload();}catch(e){feedback(e.message,true);}
    });
  }
  window.btmhSms={loadSecurity,stopLoginTimer};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})();

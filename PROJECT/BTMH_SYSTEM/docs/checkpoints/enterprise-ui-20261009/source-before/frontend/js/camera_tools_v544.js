/* Camera preflight and safe connection editor. No credentials in localStorage. */
(()=>{
'use strict';
const $=s=>document.querySelector(s);
let busy=false, editingId=null, editEpoch=0;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function request(url,opts={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),30000);
  try{
    const headers={'Content-Type':'application/json',...(opts.headers||{})};
    let token=null;try{token=localStorage.getItem('campusface_token');}catch(_){}if(token)headers.Authorization='Bearer '+token;
    const r=await fetch(url,{...opts,headers,signal:controller.signal,credentials:'same-origin',cache:'no-store'});
    const d=await r.json();if(!r.ok){const e=new Error(d.detail||d.message||'Kh\u00f4ng th\u1ec3 ho\u00e0n t\u1ea5t thao t\u00e1c.');e.result=d;throw e;}return d;
  }finally{clearTimeout(timer);}
}
function report(select,data){
  let box=document.querySelector(`[data-camera-report="${select.id}"]`);
  if(!box){box=document.createElement('div');box.className='camera544-report';box.dataset.cameraReport=select.id;select.closest('.v5-recognition-sourcebar,.v5-camera-switchbar')?.after(box);}
  const d=data.diagnostic||data;
  box.dataset.ok=data.ok?'yes':'no';box.setAttribute('role','status');
  const info=[d.source_display,d.backend?`B\u1ed9 \u0111\u1ecdc: ${d.backend.toUpperCase()}`:'',d.transport?`Truy\u1ec1n: ${d.transport.toUpperCase()}`:'',
    d.width?`${d.width} \u00d7 ${d.height}`:'',d.observed_fps?`${d.observed_fps} h\u00ecnh/gi\u00e2y quan s\u00e1t`:'',
    d.stable_frames?`${d.stable_frames} khung h\u00ecnh li\u00ean ti\u1ebfp`:''].filter(Boolean);
  box.innerHTML=`<strong>${esc(data.message||d.message||'K\u1ebft qu\u1ea3 ki\u1ec3m tra')}</strong><small>${info.map(esc).join(' \u00b7 ')}</small>`;
  if(!data.ok&&d.code)box.innerHTML+=`<small>M\u00e3 ch\u1ea9n \u0111o\u00e1n: ${esc(d.code)}</small>`;
  if(d.credential_supplied===false && /^rtsp:/i.test(d.source_display||'')){
    const hint=document.createElement('small');hint.textContent='Địa chỉ này chưa kèm tài khoản camera. Kiểm tra trong Sửa kết nối.';box.append(hint);
  }
  const copy=document.createElement('button');copy.type='button';copy.className='btn ghost';copy.textContent='Sao chép chẩn đoán';
  copy.addEventListener('click',async()=>{
    const safe={version:'5.4.10',ok:!!data.ok,kept_previous:!!data.kept_previous};
    for(const key of ['code','stage','source_display','backend','reader','transport','width','height','observed_fps','stable_frames','elapsed_ms','frame_age_ms','credential_supplied'])if(d[key]!==undefined)safe[key]=d[key];
    try{await navigator.clipboard.writeText(JSON.stringify(safe,null,2));copy.textContent='Đã sao chép';}
    catch(_){copy.textContent='Trình duyệt chưa cho phép sao chép';}
  });box.append(copy);

}
function setBusy(value){busy=value;document.querySelectorAll('[data-camera-test],[data-camera-edit],#v5RecognitionSwitchBtn,#v5SwitchCameraBtn,#v5RecognitionCameraSelect,#v5ActiveCameraSelect').forEach(x=>x.disabled=value);}
async function run(select,button,note,testOnly){
  if(!select||busy)return;
  setBusy(true);const label=button?.textContent;
  if(button)button.textContent='\u0110ang ki\u1ec3m tra...';
  if(note)note.textContent='\u0110ang ki\u1ec3m tra camera m\u1edbi. Ngu\u1ed3n hi\u1ec7n t\u1ea1i v\u1eabn ho\u1ea1t \u0111\u1ed9ng.';
  try{
    const d=await request(testOnly?'/api/v1/camera/test-source':'/api/v1/camera/select',{method:'POST',body:JSON.stringify({source:select.value})});
    report(select,d);if(note)note.textContent=d.message||'Camera \u0111\u00e3 s\u1eb5n s\u00e0ng.';
    if(d.ok&&!testOnly){document.dispatchEvent(new CustomEvent('btmh:camera-source-changed'));await window.BTMHV4?.refreshActiveCameraStatus();}
  }catch(e){
    const d=e.result||{ok:false,message:e.name==='AbortError'?'Ch\u01b0a nh\u1eadn \u0111\u01b0\u1ee3c ph\u1ea3n h\u1ed3i. Ki\u1ec3m tra tr\u1ea1ng th\u00e1i camera tr\u01b0\u1edbc khi th\u1eed l\u1ea1i.':e.message};
    report(select,d);if(note)note.textContent=d.message||d.detail;
  }finally{setBusy(false);if(button)button.textContent=label;}
}
function dialog(){
  let d=$('#cameraConnectionDialog');if(d)return d;
  d=document.createElement('dialog');d.id='cameraConnectionDialog';d.className='camera544-dialog';
  d.setAttribute('aria-labelledby','camera544Title');
  d.innerHTML=`<form id="camera544Form"><header><div><small>K\u1ebeT N\u1ed0I CAMERA</small><h2 id="camera544Title">S\u1eeda k\u1ebft n\u1ed1i</h2></div><button type="button" data-close-camera aria-label="\u0110\u00f3ng">\u00d7</button></header>
  <p>Nhập thông tin camera thực tế. Lưu kết nối không dừng nguồn đang chạy.</p>
  <details id="camera545Import"><summary>Dán địa chỉ RTSP đã kiểm tra</summary>
  <label for="camera545Reference">Địa chỉ RTSP<input id="camera545Reference" type="text" maxlength="4096" autocomplete="off" placeholder="rtsp://IP:554/Streaming/Channels/101"></label>
  <button type="button" class="btn ghost" id="camera545Apply">Áp dụng vào biểu mẫu</button>
  <small>Không tự thay đổi IP trên camera. Kiểm tra các trường bên dưới rồi bấm Lưu.</small></details>
  <div class="camera544-grid"><label for="camera544Host">\u0110\u1ecba ch\u1ec9 IP / t\u00ean m\u00e1y<input id="camera544Host" name="host" required maxlength="253" autocomplete="off"></label><label for="camera544Port">C\u1ed5ng RTSP<input id="camera544Port" name="port" type="number" min="1" max="65535" value="554" required></label></div>
  <label for="camera544Path">\u0110\u01b0\u1eddng d\u1eabn lu\u1ed3ng<input id="camera544Path" name="path" required maxlength="1500" placeholder="/Streaming/Channels/101" autocomplete="off"></label>
  <label for="camera544User">T\u00e0i kho\u1ea3n camera<input id="camera544User" name="username" maxlength="256" autocomplete="off"></label>
  <label for="camera544Pass">M\u1eadt kh\u1ea9u camera<input id="camera544Pass" name="password" type="password" maxlength="1024" autocomplete="new-password" placeholder="\u0110\u1ec3 tr\u1ed1ng \u0111\u1ec3 gi\u1eef m\u1eadt kh\u1ea9u \u0111\u00e3 l\u01b0u"></label>
  <small id="camera544CredentialState"></small><p id="camera544Message" role="status"></p>
  <footer><button type="button" class="btn ghost" data-close-camera>H\u1ee7y</button><button type="submit" class="btn primary" id="camera544Save">L\u01b0u & ki\u1ec3m tra</button></footer></form>`;
  document.body.append(d);
  $('#camera545Apply').addEventListener('click',()=>{
    try {
      const raw=$('#camera545Reference').value.trim();
      if(/[\r\n\t]/.test(raw))throw new Error('invalid');
      const url=new URL(raw);
      if(url.protocol!=='rtsp:'||!url.hostname||url.hash)throw new Error('invalid');
      const port=Number(url.port||554);if(!Number.isInteger(port)||port<1||port>65535)throw new Error('invalid');
      $('#camera544Host').value=url.hostname.replace(/^\[|\]$/g,'');
      $('#camera544Port').value=port;$('#camera544Path').value=(url.pathname||'/')+url.search;
      if(url.username)$('#camera544User').value=decodeURIComponent(url.username);
      if(url.password)$('#camera544Pass').value=decodeURIComponent(url.password);
      $('#camera545Reference').value='';
      $('#camera544Message').textContent='Đã lấy địa chỉ '+url.hostname+'. Chưa lưu; hãy xác nhận tài khoản camera rồi bấm Lưu.';
    } catch(_) {$('#camera544Message').textContent='Địa chỉ RTSP chưa hợp lệ. Nên dán địa chỉ không có mật khẩu và nhập mật khẩu ở ô riêng.';}
  });
  d.querySelectorAll('[data-close-camera]').forEach(b=>b.addEventListener('click',()=>d.close()));
  d.addEventListener('click',e=>{if(e.target===d)d.close();});
  d.addEventListener('close',()=>{editEpoch++;editingId=null;$('#camera544Pass').value='';$('#camera544Form').reset();});
  $('#camera544Form').addEventListener('submit',async e=>{
    e.preventDefault();if(editingId==null||!$('#camera544Form').reportValidity())return;
    const epoch=editEpoch,id=editingId,saveBtn=$('#camera544Save');saveBtn.disabled=true;saveBtn.textContent='\u0110ang l\u01b0u...';
    const secret=$('#camera544Pass').value;
    const body={host:$('#camera544Host').value.trim(),port:Number($('#camera544Port').value),path:$('#camera544Path').value.trim(),username:$('#camera544User').value.trim()||null,password:secret||null};
    try{
      const saved=await request(`/api/v1/cameras/devices/${id}/connection`,{method:'PUT',body:JSON.stringify(body)});
      if(epoch!==editEpoch)return;
      // Verify the exact database row after the PUT. A stale/default IP is never
      // reported as saved successfully.
      const verify=await request(`/api/v1/cameras/devices/${id}/connection`);
      if(epoch!==editEpoch)return;
      const sameHost=String(verify.host||'').toLowerCase()===String(body.host||'').toLowerCase();
      const samePort=Number(verify.port||0)===Number(body.port||0);
      const samePath=String(verify.path||'')===String(body.path||'');
      if(!saved.persisted||!sameHost||!samePort||!samePath)throw new Error('H\u1ec7 th\u1ed1ng ch\u01b0a l\u01b0u \u0111\u00fang \u0111\u1ecba ch\u1ec9 camera. C\u1ea5u h\u00ecnh c\u0169 v\u1eabn \u0111\u01b0\u1ee3c gi\u1eef an to\u00e0n.');
      $('#camera544Pass').value='';
      $('#camera544Message').textContent=`\u0110\u00e3 l\u01b0u ${verify.host}:${verify.port}${verify.path}. \u0110ang \u0111\u1ecdc th\u1eed khung h\u00ecnh...`;
      document.querySelectorAll('[data-camera-report]').forEach(x=>x.remove());
      document.dispatchEvent(new CustomEvent('btmh:camera-registry-changed'));
      saveBtn.textContent='\u0110ang ki\u1ec3m tra...';
      const sourceKey=`CAM${String(id).padStart(2,'0')}`;
      let tested=null;
      try{tested=await request('/api/v1/camera/test-source',{method:'POST',body:JSON.stringify({source:sourceKey})});}
      catch(testErr){tested=testErr.result||{ok:false,message:testErr.message};}
      if(epoch!==editEpoch)return;
      if(tested?.ok){
        $('#camera544Message').textContent=`\u0110\u00e3 l\u01b0u ${verify.host} v\u00e0 \u0111\u1ecdc \u0111\u01b0\u1ee3c khung h\u00ecnh camera.`;
        window.toast?.(`Camera ${verify.host} \u0111\u00e3 s\u1eb5n s\u00e0ng.`);
        d.close();
      }else{
        const diag=tested?.diagnostic||tested||{};
        const code=diag.code?` (m\u00e3 ${diag.code})`:'';
        $('#camera544Message').textContent=`\u0110\u00e3 l\u01b0u \u0111\u00fang IP ${verify.host}, nh\u01b0ng ch\u01b0a \u0111\u1ecdc \u0111\u01b0\u1ee3c h\u00ecnh${code}. ${tested?.message||diag.message||''}`.trim();
        window.toast?.('\u0110\u00e3 l\u01b0u IP camera; c\u1ea7n x\u1eed l\u00fd ph\u1ea7n m\u1edf lu\u1ed3ng video.',true);
      }
    }catch(err){if(epoch===editEpoch)$('#camera544Message').textContent=err.message;}
    finally{if(epoch===editEpoch){saveBtn.disabled=false;saveBtn.textContent='L\u01b0u & ki\u1ec3m tra';}}
  });return d;
}
async function edit(select){
  if(busy||!select)return;
  const match=/^CAM(\d+)$/i.exec(select.value);
  if(!match){window.toast?.('Camera laptop kh\u00f4ng c\u1ea7n IP ho\u1eb7c m\u1eadt kh\u1ea9u.');return;}
  const d=dialog();editingId=Number(match[1]);const epoch=++editEpoch;
  $('#camera544Message').textContent='\u0110ang t\u1ea3i c\u1ea5u h\u00ecnh...';$('#camera544Save').disabled=true;d.showModal();
  try{
    const data=await request(`/api/v1/cameras/devices/${editingId}/connection`);if(epoch!==editEpoch)return;
    if(!data.editable){$('#camera544Message').textContent='Ngu\u1ed3n n\u00e0y kh\u00f4ng ph\u1ea3i camera RTSP.';return;}
    $('#camera544Title').textContent=data.name||'S\u1eeda k\u1ebft n\u1ed1i';$('#camera544Host').value=data.host;
    $('#camera544Port').value=data.port;$('#camera544Path').value=data.path;$('#camera544User').value=data.username||'';
    $('#camera544Pass').value='';$('#camera544Message').textContent=data.legacy_host_warning||'';
    $('#camera544CredentialState').textContent=data.credential_saved?'\u0110\u00e3 c\u00f3 m\u1eadt kh\u1ea9u tr\u00ean m\u00e1y ch\u1ee7; kh\u00f4ng g\u1eedi v\u1ec1 tr\u00ecnh duy\u1ec7t.':'Ch\u01b0a l\u01b0u m\u1eadt kh\u1ea9u camera.';
    $('#camera544Save').disabled=false;$('#camera544Host').focus();
  }catch(e){if(epoch===editEpoch)$('#camera544Message').textContent=e.message;}
}
window.BTMHCameraTools={switchSource:(s,b,n)=>run(s,b,n,false),edit};
document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('#v5RecognitionCameraSelect,#v5ActiveCameraSelect').forEach(sel=>sel.addEventListener('change',()=>{document.querySelector(`[data-camera-report="${sel.id}"]`)?.remove();}));
 document.querySelectorAll('[data-camera-test]').forEach(b=>b.addEventListener('click',()=>{const s=$('#'+b.dataset.cameraTest);run(s,b,$(b.dataset.note||'#v5RecognitionCameraNote'),true);}));
 document.querySelectorAll('[data-camera-edit]').forEach(b=>b.addEventListener('click',()=>edit($('#'+b.dataset.cameraEdit))));
});
document.addEventListener('btmh:auth',e=>{if(!e.detail?.authenticated)$('#cameraConnectionDialog')?.close();});
})();

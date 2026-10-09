(()=>{
'use strict';
if(window.BTMHV4)return;
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let sourceItems=[],authReady=false,authEpoch=0,pageEpoch=0,fleetOwner=null,sourcesOwner=null,presented=true,preparedPage=null;
let v4Fleet=[],v4Layout=2,v4EnrollmentStream=null,v4EnrollmentCanvas=null,selectedPlaybackSegment=null,modalCameraId=null;
const fleetTiles=new Map();
let fleetEmpty=null,enrollmentEpoch=0,enrollmentPending=null,presenceOwner=null,playbackOwner=null,playbackSearchEpoch=0;
function token(){return localStorage.getItem('campusface_token')||''}
async function v4api(url,opts={}){const headers={'Content-Type':'application/json',...(opts.headers||{})};const t=token();if(t)headers.Authorization='Bearer '+t;const r=await BTMHRuntime.request(url,{...opts,headers,timeoutMs:opts.method?90000:12000});let j={};try{j=await r.json()}catch(_){}if(!r.ok)throw new Error(j.detail||j.message||('Lỗi '+r.status));return j}
function esc(s=''){return String(s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function streamUrl(id){return `/api/v1/cameras/${encodeURIComponent(id)}/stream.mjpg?ts=${Date.now()}`}
function cameraName(c){return c.name||c.camera_name||`CAM${c.id||''}`}
function formatLocal(v){if(!v)return '—';try{return new Date(v).toLocaleString('vi-VN')}catch(_){return v}}
function toLocalInput(v){if(!v)return '';const d=new Date(v);if(Number.isNaN(d.getTime()))return '';const z=n=>String(n).padStart(2,'0');return `${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`}

function cameraAllowed(){return authReady&&typeof hasUiPermission==='function'&&hasUiPermission('camera.live');}
async function loadSources(){
  if(!cameraAllowed()||document.hidden||!presented)return;
  if(sourcesOwner)return sourcesOwner.promise;
  const owner={epoch:authEpoch,controller:new AbortController(),promise:null};sourcesOwner=owner;
  const current=()=>sourcesOwner===owner&&owner.epoch===authEpoch&&!owner.controller.signal.aborted&&cameraAllowed()&&!document.hidden&&presented;
  owner.promise=(async()=>{
    try{
      const d=await v4api('/api/v1/camera/sources',{signal:owner.controller.signal});if(!current())return;
      sourceItems=d.items||[];populateCameraSwitchers();
      for(const el of $$('[data-source-note]'))el.textContent=sourceItems.filter(x=>x.source_key!=='0').length?'Camera ch\u01b0a k\u1ebft n\u1ed1i v\u1eabn hi\u1ec7n trong danh s\u00e1ch.':'Ch\u01b0a khai b\u00e1o camera c\u1eeda h\u00e0ng. Ch\u1ecdn Qu\u1ea3n l\u00fd camera \u0111\u1ec3 th\u00eam.';
      return d;
    }catch(e){if(current()&&e.name!=='AbortError')for(const el of $$('[data-source-note]'))el.textContent='Kh\u00f4ng t\u1ea3i \u0111\u01b0\u1ee3c danh s\u00e1ch camera. B\u1ea5m T\u1ea3i l\u1ea1i.';}
    finally{if(sourcesOwner===owner)sourcesOwner=null;}
  })();return owner.promise;
}
function cancelFleet(){const old=fleetOwner;fleetOwner=null;old?.controller.abort();}
function cancelSources(){const old=sourcesOwner;sourcesOwner=null;old?.controller.abort();}
function cancelPageRequests(){const owners=[presenceOwner,playbackOwner];presenceOwner=null;playbackOwner=null;for(const owner of owners)owner?.controller.abort();}
function pageAllowed(page,permission){return authReady&&presented&&!document.hidden&&!!$(`#page-${page}.active`)&&typeof hasUiPermission==='function'&&hasUiPermission(permission);}
async function loadV4Fleet(){
  if(!cameraAllowed()||!$('#page-live-grid.active')||document.hidden||!presented)return;
  if(fleetOwner)return fleetOwner.promise;
  const owner={page:pageEpoch,auth:authEpoch,controller:new AbortController(),promise:null};fleetOwner=owner;
  const current=()=>fleetOwner===owner&&owner.page===pageEpoch&&owner.auth===authEpoch&&!owner.controller.signal.aborted&&cameraAllowed()&&!document.hidden&&presented&&!!$('#page-live-grid.active');
  owner.promise=(async()=>{
    try{
      const d=await v4api('/api/v1/cameras/fleet/v4',{signal:owner.controller.signal});if(!current())return;
      v4Fleet=Array.isArray(d.items)?d.items:[];renderV4Grid();renderV4CameraRoles(d);void loadSources();
    }catch(e){if(current()&&e.name!=='AbortError'){closeV4Camera(false);clearFleetTiles();showFleetEmpty('Không tải được danh sách camera. Bấm Tải lại.');}}
    finally{if(fleetOwner===owner)fleetOwner=null;}
  })();return owner.promise;
}
function renderV4CameraRoles(data={}){const enroll=$('#v4EnrollmentCameraName'),surv=$('#v4SurveillanceCameraName'),survState=$('#v4SurveillanceCameraState');if(enroll)enroll.textContent='Laptop Camera';const primary=(data.items||[]).find(x=>x.role==='SURVEILLANCE_PRIMARY')||(data.items||[])[0];if(surv)surv.textContent=primary?cameraName(primary):'Chưa cấu hình camera cửa hàng';if(survState){if(!primary)survState.textContent='Chờ camera';else if(!primary.online)survState.textContent='Offline';else if(primary.recording_active)survState.textContent='Online · REC';else survState.textContent='Online · REC đang khởi động';}}
function renderV4Grid(){
  const host=$('#v4CameraGrid');if(!host||!$('#page-live-grid.active')||!cameraAllowed()||document.hidden||!presented)return;
  host.className=`v4-camera-grid cols-${v4Layout}`;
  const cameras=new Map();
  for(const camera of v4Fleet){const id=Number(camera.id);if(Number.isSafeInteger(id)&&id>0&&!cameras.has(id))cameras.set(id,camera);}
  const selected=cameras.get(modalCameraId);
  if(modalCameraId!==null&&(!selected||selected.enabled===false))closeV4Camera(false);
  for(const [id,tile] of fleetTiles){if(!cameras.has(id)){stopTile(tile);tile.card.remove();fleetTiles.delete(id);}}
  if(!cameras.size){showFleetEmpty('Chưa khai báo camera cửa hàng. Thêm camera trong Quản lý camera.');return;}
  for(const empty of host.querySelectorAll('.v4-empty'))empty.remove();fleetEmpty=null;
  const mediaStats=window.BTMHMedia?.stats?.()||{};
  let index=0;
  for(const [id,camera] of cameras){
    let tile=fleetTiles.get(id);if(!tile){tile=createTile(id);fleetTiles.set(id,tile);}
    updateTile(tile,camera);
    if(host.children[index]!==tile.card)host.insertBefore(tile.card,host.children[index]||null);
    index++;
    mountTile(tile,mediaStats);
  }
  if(selected&&modalCameraId!==null){$('#v4CameraModalTitle').textContent=cameraName(selected);if(mediaStats['grid-modal'])renderGridPlayback({...mediaStats['grid-modal'],key:'grid-modal'});else $('#v4CameraModalMeta').textContent=selected.zone_name||'';}
}
function element(tag,className='',text=''){const el=document.createElement(tag);el.className=className;el.textContent=text;return el;}
function createTile(id){
  const card=element('article','v4-camera-card'),meta=element('div','meta'),info=element('div'),name=element('b'),zone=element('small'),flags=element('div','flags'),badge=element('span'),recording=element('span','rec','Đang ghi');
  card.dataset.cameraId=String(id);card.setAttribute('role','button');meta.style.zIndex='2';info.append(name,zone);flags.append(badge,recording);meta.append(info,flags);card.append(meta);
  card.addEventListener('click',()=>openV4Camera(id));card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();openV4Camera(id);}});
  return {id,card,meta,name,zone,badge,recording,image:null,placeholder:null,enabled:false,requestedQuality:null,playback:null};
}
function stopTile(tile){window.BTMHMedia?.stop?.(`grid-${tile.id}`);if(tile.image)BTMHRuntime.stopPreview(tile.image);tile.requestedQuality=null;tile.playback=null;}
function clearFleetTiles(){for(const tile of fleetTiles.values()){stopTile(tile);tile.card.remove();}fleetTiles.clear();fleetEmpty?.remove();fleetEmpty=null;}
function showFleetEmpty(message){const host=$('#v4CameraGrid');if(!host)return;if(!fleetEmpty){for(const empty of host.querySelectorAll('.v4-empty'))empty.remove();fleetEmpty=element('div','v4-empty');host.append(fleetEmpty);}fleetEmpty.textContent=message;}
function updateTile(tile,camera){
  const enabled=camera.enabled!==false,label=cameraName(camera);
  tile.card.setAttribute('aria-label',label);tile.card.setAttribute('aria-disabled',String(!enabled));tile.card.tabIndex=enabled?0:-1;
  if(tile.name.textContent!==label)tile.name.textContent=label;
  const zone=camera.zone_name||'Camera cửa hàng';if(tile.zone.textContent!==zone)tile.zone.textContent=zone;
  tile.recording.hidden=!camera.recording_active;
  if(!enabled){
    if(tile.image){stopTile(tile);tile.image.remove();tile.image=null;}
    if(!tile.placeholder){tile.placeholder=element('div','placeholder');tile.placeholder.append(element('strong'),element('p','','Đã tắt'));tile.card.insertBefore(tile.placeholder,tile.meta);}
    tile.placeholder.children[0].textContent=label;
  }else{
    tile.placeholder?.remove();tile.placeholder=null;
    if(!tile.image){tile.image=element('img');tile.image.dataset.fleetPreview=String(tile.id);tile.card.insertBefore(tile.image,tile.meta);}
    tile.image.alt=label;
  }
  tile.enabled=enabled;
  if(tile.playback&&enabled)renderGridPlayback(tile.playback);else tile.badge.textContent=enabled?(camera.online?'Trực tuyến':'Chưa kết nối'):'Đã tắt';
}
function mountTile(tile,mediaStats){
  if(!tile.enabled||modalCameraId===tile.id)return;
  const quality=v4Layout>1?'small':'main',key=`grid-${tile.id}`;
  if(window.BTMHMedia){
    if(mediaStats[key]&&tile.requestedQuality===quality)return;
    if(mediaStats[key])stopTile(tile);
    tile.requestedQuality=quality;
    BTMHMedia.mount(key,{cameraId:tile.id,quality,wrap:tile.card,image:tile.image,fit:'contain',allowMjpeg:false,pollInterval:400,mjpegUrl:`/api/v1/cameras/${tile.id}/stream.mjpg`,pollUrl:`/api/v1/cameras/${tile.id}/frame.jpg`});
  }else{tile.requestedQuality=quality;BTMHRuntime.preview(tile.image,`/api/v1/cameras/${tile.id}/frame.jpg`,400);}
}
function openV4Camera(id){
  const c=v4Fleet.find(x=>Number(x.id)===id),ready=fleetTiles.get(id);if(!c||c.enabled===false||!ready?.enabled||!ready.requestedQuality||!cameraAllowed()||document.hidden||!presented||!$('#page-live-grid.active'))return;const modal=$('#v4CameraModal');if(!modal)return;
  closeV4Camera(false);modalCameraId=id;const tile=fleetTiles.get(id);if(tile)stopTile(tile);renderV4Grid();
  $('#v4CameraModalTitle').textContent=cameraName(c);$('#v4CameraModalMeta').textContent=c.zone_name||'';modal.classList.remove('hidden');
  if(c.enabled!==false){if(window.BTMHMedia)BTMHMedia.mount('grid-modal',{cameraId:id,quality:'main',wrap:'#v4CameraModalViewport',image:'#v4CameraModalStream',fit:'contain',mjpegUrl:`/api/v1/cameras/${id}/stream.mjpg`,pollUrl:`/api/v1/cameras/${id}/frame.jpg`});else BTMHRuntime.preview($('#v4CameraModalStream'),`/api/v1/cameras/${id}/frame.jpg`,90);}
}
function closeV4Camera(resume=true){const m=$('#v4CameraModal');if(m)m.classList.add('hidden');window.BTMHMedia?.stop?.('grid-modal');BTMHRuntime.stopPreview($('#v4CameraModalStream'));modalCameraId=null;if(resume&&cameraAllowed()&&!document.hidden&&$('#page-live-grid.active'))renderV4Grid();}
function renderGridPlayback(d={}){
  const match=/^grid-(\d+)$/.exec(d.key||'');
  const status=d.state==='live'?'LIVE':['error','offline','stopped'].includes(d.state)?'Mất kết nối':d.state==='unavailable'?'Camera không khả dụng':'Đang kết nối';
  if(match){const tile=fleetTiles.get(Number(match[1]));if(tile&&tile.enabled&&tile.requestedQuality){tile.playback=d;tile.badge.textContent=status;tile.badge.title='';}}
  if(d.key==='grid-modal'){const meta=$('#v4CameraModalMeta');if(meta){const c=v4Fleet.find(x=>Number(x.id)===modalCameraId);meta.textContent=[c?.zone_name,status].filter(Boolean).join(' · ');}}
}
document.addEventListener('btmh:media-state',e=>renderGridPlayback(e.detail));
document.addEventListener('btmh:media-stats',e=>renderGridPlayback(e.detail));
function bindLayout(){$$('[data-v4-layout]').forEach(b=>b.addEventListener('click',()=>{v4Layout=Number(b.dataset.v4Layout)||2;$$('[data-v4-layout]').forEach(x=>x.classList.toggle('active',x===b));renderV4Grid()}));$('#v4CameraModalClose')?.addEventListener('click',closeV4Camera);$('#v4CameraModal')?.addEventListener('click',e=>{if(e.target.id==='v4CameraModal')closeV4Camera()})}

function sourceLabel(c){const tag=c.enabled===false?'\u0111\u00e3 t\u1eaft':c.health_status==='ONLINE'?'\u0111ang d\u00f9ng':c.health_status==='OFFLINE'?'m\u1ea5t k\u1ebft n\u1ed1i':c.health_status==='INVALID'?'ch\u01b0a c\u1ea5u h\u00ecnh':'ch\u01b0a ki\u1ec3m tra';return `${c.name} \u00b7 ${tag}`;}
function populateSelect(sel,includeBrowser=false){
  if(!sel)return;
  const current=sel.value,first=sel.dataset.sourcesLoaded!=='1';
  const opts=sourceItems.map(c=>({...c,value:c.source_key,label:sourceLabel(c)}));
  if(includeBrowser)opts.unshift({value:'browser',label:'Camera laptop (tr\u00ecnh duy\u1ec7t)',selectable:true});
  sel.innerHTML=opts.map(o=>`<option value="${esc(o.value)}" ${o.selectable===false?'disabled':''}>${esc(o.label)}</option>`).join('');
  const active=opts.find(o=>o.active);
  if(first&&active&&!includeBrowser)sel.value=active.value;
  else if(opts.some(o=>o.value===current))sel.value=current;
  sel.dataset.sourcesLoaded='1';
}
function populateCameraSwitchers(){populateSelect($('#v5ActiveCameraSelect'));populateSelect($('#v5RecognitionCameraSelect'));populateSelect($('#v5EnrollmentCameraSelect'),true);populatePlayback();}
function populatePlayback(){const sel=$('#v4PlaybackCamera');if(!sel)return;const current=sel.value;sel.innerHTML='<option value="">Ch\u1ecdn camera</option>'+sourceItems.map(c=>`<option value="${esc(c.source_key)}">${esc(c.name)}</option>`).join('');if([...sel.options].some(o=>o.value===current))sel.value=current;}
async function refreshActiveCameraStatus(){await loadSources();const active=sourceItems.find(c=>c.active);const el=$('#v5ActiveCameraLabel');if(el)el.textContent=active?.name||'Camera hi\u1ec7n t\u1ea1i';}
async function switchCameraSource(sel,btn,note){
  if(!sel||!cameraAllowed())return;
  if(window.BTMHCameraTools)return BTMHCameraTools.switchSource(sel,btn,note);
  if(note)note.textContent='Tai giao dien moi bang Ctrl+F5 de su dung cong cu camera.';
}
async function switchActiveCamera(){return switchCameraSource($('#v5ActiveCameraSelect'),$('#v5SwitchCameraBtn'),$('#v5CameraSwitchNote'));}
async function switchRecognitionCamera(){return switchCameraSource($('#v5RecognitionCameraSelect'),$('#v5RecognitionSwitchBtn'),$('#v5RecognitionCameraNote'));}
async function loadPresenceV4(){
  const host=$('#v4PresenceList');if(!host||!pageAllowed('operations','attendance.view'))return;
  if(presenceOwner)return presenceOwner.promise;
  const owner={auth:authEpoch,page:pageEpoch,controller:new AbortController(),promise:null};presenceOwner=owner;
  const current=()=>presenceOwner===owner&&owner.auth===authEpoch&&owner.page===pageEpoch&&!owner.controller.signal.aborted&&pageAllowed('operations','attendance.view');
  owner.promise=(async()=>{
    try{
      const d=await v4api('/api/v1/presence/current',{signal:owner.controller.signal});if(!current())return;const rows=d.items||[];
      $('#v4PresenceNow').textContent=rows.length;$('#v4PresenceTotal').textContent=d.employee_total??'—';$('#v4PresenceAway').textContent=Math.max(0,Number(d.employee_total||0)-rows.length);$('#v4PresenceVisitors').textContent=d.active_visitors??0;
      host.innerHTML=rows.length?rows.map(r=>`<div class="v4-presence-row"><div><b>${esc(r.full_name||'Nhân viên')}</b><small>${esc(r.employee_code||'')} · ${esc(r.department||'')}</small></div><span class="v4-state-present">● Đang có mặt</span><span>Lần cuối: ${esc(formatLocal(r.last_seen_at||r.started_at))}</span></div>`).join(''):'<div class="v4-empty">Chưa ghi nhận nhân viên đang có mặt.</div>';
    }catch(e){if(current()&&e.name!=='AbortError')host.innerHTML='<div class="v4-empty">Không tải được danh sách hiện diện. Bấm Tải lại.</div>';}
    finally{if(presenceOwner===owner)presenceOwner=null;}
  })();return owner.promise;
}
async function loadPlaybackV4(){await loadSources();populatePlayback();}
async function searchPlaybackV4(){
  if(!pageAllowed('playback','camera.playback'))return;
  const source=$('#v4PlaybackCamera')?.value||'',date=$('#v4PlaybackDate')?.value||'',host=$('#v4PlaybackResults');if(!host)return;
  playbackOwner?.controller.abort();
  const owner={auth:authEpoch,page:pageEpoch,search:++playbackSearchEpoch,controller:new AbortController()};playbackOwner=owner;
  const viewCurrent=()=>owner.search===playbackSearchEpoch&&owner.auth===authEpoch&&owner.page===pageEpoch&&!owner.controller.signal.aborted&&pageAllowed('playback','camera.playback');
  const current=()=>playbackOwner===owner&&viewCurrent();
  if(!source||!date){host.innerHTML='<div class="v4-empty">Chọn camera và ngày để xem bản ghi.</div>';if(playbackOwner===owner)playbackOwner=null;return;}
  const localStart=new Date(`${date}T00:00:00`),localEnd=new Date(`${date}T23:59:59.999`);
  try{
    const start=localStart.toISOString(),end=localEnd.toISOString();
    const d=await v4api(`/api/v1/recordings/segments?camera_source=${encodeURIComponent(source)}&start_at=${encodeURIComponent(start)}&end_at=${encodeURIComponent(end)}&limit=500`,{signal:owner.controller.signal});if(!current())return;
    const rows=d.items||[];
    if(rows.length){host.innerHTML=rows.map((r,i)=>`<button class="btn ghost" data-v4-segment="${i}" style="width:100%;margin-bottom:8px;text-align:left">${esc(formatLocal(r.start_at))} → ${esc(formatLocal(r.end_at))}${r.protected?' · EVIDENCE':''}</button>`).join('');$$('[data-v4-segment]').forEach(b=>b.addEventListener('click',()=>{if(viewCurrent())playSegment(rows[Number(b.dataset.v4Segment)]);}));return;}
    let msg='Chưa có đoạn video đã hoàn tất trong ngày này. Segment đang ghi chỉ xuất hiện sau khi file MP4 được đóng.';
    try{const st=await v4api('/api/v1/recordings/status',{signal:owner.controller.signal});if(!current())return;const cam=st?.runtime?.cameras?.[source]||{};if(st?.runtime?.ready===false)msg='Ghi hình chưa sẵn sàng trên máy này. Liên hệ quản trị viên.';else if(cam.active===false&&cam.last_error)msg='Chưa ghi hình. Kiểm tra camera hoặc liên hệ quản trị viên.';else if(cam.active)msg='Đang ghi hình. Đoạn video đầu tiên sẽ xuất hiện sau khi hoàn tất.';}catch(e){if(!current()||e.name==='AbortError')return;}
    if(current())host.innerHTML=`<div class="v4-empty">${esc(msg)}</div>`;
  }catch(e){if(current()&&e.name!=='AbortError')host.innerHTML='<div class="v4-empty">Không tải được bản ghi. Bấm Tìm lại.</div>';}
  finally{if(playbackOwner===owner)playbackOwner=null;}
}
function playSegment(r){if(!pageAllowed('playback','camera.playback'))return;selectedPlaybackSegment=r||null;const v=$('#v4PlaybackVideo'),empty=$('#v4PlaybackEmpty'),clipBtn=$('#v5CreateClipBtn');if(clipBtn)clipBtn.disabled=!r;if($('#v5ClipStart'))$('#v5ClipStart').value=toLocalInput(r?.start_at);if($('#v5ClipEnd'))$('#v5ClipEnd').value=toLocalInput(r?.end_at);if($('#v5ClipState'))$('#v5ClipState').textContent=r?`Đã chọn segment ${r.segment_id||''}.`:'Chưa chọn segment.';if(!v)return;const uri=String(r?.media_uri||'');if(!uri){empty.textContent='Segment đã được index nhưng nguồn media hiện chưa phát trực tiếp được.';empty.style.display='block';v.style.display='none';return}let url=uri;if(!/^https?:\/\//i.test(uri)&&!uri.startsWith('/'))url=`/api/v1/recordings/media?path=${encodeURIComponent(uri)}`;v.onerror=()=>{if(!pageAllowed('playback','camera.playback'))return;empty.textContent='Không phát được MP4 này. Hãy kiểm tra camera đang dùng H.264 (không phải H.265/H.265+) và recorder đã đóng segment hoàn chỉnh.';empty.style.display='block';v.style.display='none';};v.src=url;v.load();v.style.display='block';empty.style.display='none';v.play().catch(()=>{})}
async function createClip(){const state=$('#v5ClipState'),btn=$('#v5CreateClipBtn');if(!selectedPlaybackSegment)return;btn&&(btn.disabled=true);try{const start=$('#v5ClipStart')?.value||'',end=$('#v5ClipEnd')?.value||'';if(!start||!end)throw new Error('Hãy chọn thời gian bắt đầu và kết thúc.');const out=await v4api('/api/v1/video/clips',{method:'POST',body:JSON.stringify({segment_id:String(selectedPlaybackSegment.segment_id||''),start_at:new Date(start).toISOString(),end_at:new Date(end).toISOString()})});const c=out.clip||{};state&&(state.textContent=c.status==='READY'?`Đã tạo clip ${c.clip_id} và lưu media.`:`Đã index clip ${c.clip_id}; nguồn NVR/remote sẽ được lấy theo khoảng thời gian khi cần.`);window.toast?.(`Đã tạo ${c.clip_id||'clip'}.`)}catch(e){state&&(state.textContent=e.message);window.toast?.(e.message,true)}finally{btn&&(btn.disabled=false)}}

function enrollmentAllowed(){return authReady&&presented&&!document.hidden&&!!$('#page-register.active')&&typeof hasUiPermission==='function'&&hasUiPermission('employee.enroll');}
function retireBrowserStream(stream){stream?.getTracks().forEach(track=>track.stop());}
function startEnrollmentBrowserCamera(){
  const video=$('#enrollVideo');if(!video||!navigator.mediaDevices?.getUserMedia||!enrollmentAllowed())return Promise.resolve(false);
  if(v4EnrollmentStream?.active){video.srcObject=v4EnrollmentStream;return Promise.resolve(true);}
  if(enrollmentPending)return enrollmentPending.promise;
  const owner={epoch:enrollmentEpoch,promise:null};enrollmentPending=owner;
  owner.promise=(async()=>{
    try{
      const stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:1280},height:{ideal:720}},audio:false});
      if(enrollmentPending!==owner||owner.epoch!==enrollmentEpoch||!enrollmentAllowed()||$('#enrollVideo')!==video){retireBrowserStream(stream);return false;}
      v4EnrollmentStream=stream;video.srcObject=stream;video.style.display='block';video.play().catch(()=>{});$('#enrollEmpty')?.classList.add('hidden');return true;
    }catch(_){return false;}
    finally{if(enrollmentPending===owner)enrollmentPending=null;}
  })();return owner.promise;
}
function stopEnrollmentBrowserCamera(){
  enrollmentEpoch++;enrollmentPending=null;
  const stream=v4EnrollmentStream;v4EnrollmentStream=null;retireBrowserStream(stream);
  const video=$('#enrollVideo');if(video){video.srcObject=null;video.style.display='none';}
}
function enrollmentDataUrl(){const video=$('#enrollVideo');if(!video||!video.videoWidth)return '';if(!v4EnrollmentCanvas)v4EnrollmentCanvas=document.createElement('canvas');const maxW=960,scale=Math.min(1,maxW/video.videoWidth);v4EnrollmentCanvas.width=Math.round(video.videoWidth*scale);v4EnrollmentCanvas.height=Math.round(video.videoHeight*scale);const ctx=v4EnrollmentCanvas.getContext('2d');ctx.drawImage(video,0,0,v4EnrollmentCanvas.width,v4EnrollmentCanvas.height);return v4EnrollmentCanvas.toDataURL('image/jpeg',.86)}
function leavePage(next){
  preparedPage=next;pageEpoch++;cancelFleet();cancelPageRequests();closeV4Camera(false);
  for(const tile of fleetTiles.values())stopTile(tile);
  stopEnrollmentBrowserCamera();
  if(next!=='playback'){const v=$('#v4PlaybackVideo');if(v){v.pause();v.removeAttribute('src');v.load();}}
}
window.BTMHV4={loadFleet:loadV4Fleet,loadPresence:loadPresenceV4,loadPlayback:loadPlaybackV4,loadSources,leavePage,startEnrollmentBrowserCamera,stopEnrollmentBrowserCamera,enrollmentDataUrl,refreshActiveCameraStatus};
document.addEventListener('btmh:auth',e=>{
  authEpoch++;cancelFleet();cancelSources();cancelPageRequests();closeV4Camera(false);for(const tile of fleetTiles.values())stopTile(tile);stopEnrollmentBrowserCamera();authReady=!!e.detail?.authenticated;
  if(authReady){void loadSources();resumeV4();}else{leavePage('signed-out');sourceItems=[];v4Fleet=[];clearFleetTiles();}
});
function resumeV4(){if(!authReady||document.hidden||!presented)return;if($('#page-live-grid.active'))void loadV4Fleet();if($('#page-register.active'))void startEnrollmentBrowserCamera();}
document.addEventListener('btmh:navigate',e=>{const page=e.detail?.page;if(preparedPage!==page)leavePage(page);preparedPage=null;if(['recognition','register','live-grid','playback','system'].includes(page))void loadSources();resumeV4();});
document.addEventListener('btmh:camera-registry-changed',()=>{pageEpoch++;cancelFleet();cancelSources();void loadSources();void loadV4Fleet();});
document.addEventListener('visibilitychange',()=>{if(document.hidden){leavePage('hidden');cancelSources();}else resumeV4();});
window.addEventListener('pagehide',()=>{presented=false;leavePage('pagehide');cancelSources();});
window.addEventListener('pageshow',()=>{presented=true;resumeV4();});
document.addEventListener('DOMContentLoaded',()=>{
  bindLayout();$('#v4PlaybackSearch')?.addEventListener('click',searchPlaybackV4);$('#v4PlaybackRefresh')?.addEventListener('click',loadPlaybackV4);$('#v5SwitchCameraBtn')?.addEventListener('click',switchActiveCamera);$('#v5RecognitionSwitchBtn')?.addEventListener('click',switchRecognitionCamera);$('#v5CreateClipBtn')?.addEventListener('click',createClip);
  document.querySelectorAll('[data-refresh-sources]').forEach(b=>b.addEventListener('click',()=>void loadSources()));
  if($('#v4PlaybackDate'))$('#v4PlaybackDate').value=new Date().toISOString().slice(0,10);
  // Never issue authenticated fleet/playback requests before login.
  setInterval(()=>{if(!authReady||document.hidden||!presented)return;if($('#page-live-grid.active'))void loadV4Fleet();if($('#page-operations.active'))void loadPresenceV4();},5000);
},{once:true});
})();

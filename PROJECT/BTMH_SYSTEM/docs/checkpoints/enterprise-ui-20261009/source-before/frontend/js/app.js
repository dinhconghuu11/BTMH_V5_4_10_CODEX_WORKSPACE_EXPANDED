// legacy V2.5 contract marker: type!=='STATUS_CHANGE'
// Passive anti-spoof trước FaceID: nay dung MiniFASNet V2 multi-frame PAD.
// Passive anti-spoof: MiniFASNet V2 multi-frame PAD before FaceID.
'use strict';

const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];

const state = {
  activePage: 'dashboard',
  students: [],
  events: [],
  latestSnapshots: new Map(),
  enrollStudentId: null,
  enrollStudentProfile: null,
  enrollSession: null,
  enrollTimer: null,
  enrollBusy: false,
  enrollStarting: false,
  qrAdminViews: [],
  enrollFinalizing: false,
  enrollCompleted: false,
  studentPage: 1,
  studentPageSize: 12,
  studentScope: 'ALL',
  health: null,
  lastEventId: 0,
  lastSpoofTrack: null,
  enrollLastResponse: null,
  loginOtpChallenge: '',
  mfaChallenge: '',
  mfaOtpChallenge: '',
  mfaSelectedMethod: '',
  mfaMethods: [],
  adminSecurityChallenge: '',
  adminSecurityMethod: '',
  setupOtpChallenge: '',
  registerOtpChallenge: '',
  forgotOtpChallenge: '',
  enrollmentSourceMode: 'browser',
  enrollDuplicatePending: false,
  enrollDuplicateCandidate: null,
  enrollValidationBusy: false,
  studentDetailId: null,
  studentProfileTab: 'detail',
  historyFeed: [],
  historyRecognitionFeed: [],
  historyHrFeed: [],
  historyHrSessions: [],
  historyHrSummary: {},
  historyHrCurrent: [],
  historyHrRealtime: [],
  historyHrDailySummary: [],
  historyHrPolicy: {},
  historyTechnicalFeed: [],
  historyMode: 'RECOGNITION',
  historyRecognitionView: [],
  historyHrView: [],
  historyRecognitionTab: 'ALL',
  historyHrTab: 'EVENTS',
  historyView: [],
  historyTab: 'ALL',
  attendanceSessions: [],
  attendanceSessionId: null,
  authUser: null,
  systemDiag: null,
  recognitionEnteredAt: 0,
  recognitionProfileKey: '',
  dashboardSummary: null,
  systemTimer: null,
  systemDiagController: null,
  systemDiagEpoch: 0,
  presentationSuspended: false,
  pagePresented: true,
  presentationEpoch: 0,
  clockTimer: null,
  appPollingTimers: [],
  suspendedEnrollment: null,
  enrollRequestController: null,
  systemProductionController: null,
  systemProductionCheckController: null,
  systemEdgeController: null,
  cameraControlTimer: null,
  cameraPreset: 'laptop',
  opsDevices: [],
  opsExceptions: [],
  attendanceAdjustStudentId: null,
  v13DashboardFrameTimer: null,
  v13MonitorTimer: null,
  v13OpsSocket: null,
  v13OpsSocketRetry: null,
  v13LastSummaryAt: 0,
  hrReportPeriod: 'day',
  hrReportData: null,
};

const pageMeta = {
  dashboard: ['Tổng quan', 'Tình trạng vận hành cửa hàng'],
  'live-monitor': ['Giám sát trực tiếp', 'Tình trạng camera và thiết bị'],
  'live-grid': ['Xem trực tiếp', 'Theo dõi các khu vực trong cửa hàng'],
  playback: ['Xem lại camera', 'Tìm và xem lại bản ghi theo thời gian'],
  students: ['Nhân sự', 'Hồ sơ, khuôn mặt và ca làm của nhân viên'],
  'work-shifts': ['Ca làm và giờ làm', 'Thiết lập ca và phân công nhân viên'],
  incidents: ['Sự cố và bằng chứng', 'Kiểm tra, xác minh và lưu bằng chứng'],
  visitors: ['Khách ra vào', 'Phiên khách và các trường hợp cần xác minh'],
  register: ['Đăng ký khuôn mặt', 'Thêm dữ liệu nhận diện cho nhân viên'],
  recognition: ['Nhận diện và chấm công', 'Theo dõi ra vào theo thời gian thực'],
  history: ['Lịch sử và báo cáo', 'Tra cứu chấm công và nhận diện'],
  operations: ['Hiện diện', 'Theo dõi có mặt, ra ngoài và quay lại'],
  'hr-report': ['Báo cáo nhân sự', 'Tổng hợp ngày, tuần và tháng'],
  'camera-control': ['Điều khiển camera', 'Kiểm tra và điều khiển thiết bị'],
  'ops-center': ['Camera và vận hành', 'Các trường hợp cần người quản lý xử lý'],
  'admin-security': ['Tài khoản và phân quyền', 'Quản lý người dùng, vai trò và bảo mật'],
  system: ['Cài đặt hệ thống', 'Camera, sao lưu và tình trạng vận hành'],
};

const FACULTY_CATALOG = [
  ['Ban quản lý', ['Giám đốc cửa hàng', 'Quản lý cửa hàng', 'Trợ lý quản lý']],
  ['Bán hàng - Tư vấn', ['Trưởng nhóm bán hàng', 'Nhân viên tư vấn', 'Chăm sóc khách hàng']],
  ['Thu ngân', ['Trưởng ca thu ngân', 'Nhân viên thu ngân']],
  ['Kế toán - Tài chính', ['Kế toán trưởng', 'Kế toán viên']],
  ['Kho - Kiểm kê', ['Quản lý kho', 'Nhân viên kho', 'Kiểm kê']],
  ['An ninh - Bảo vệ', ['Trưởng ca bảo vệ', 'Nhân viên bảo vệ']],
  ['Nhân sự - Hành chính', ['Nhân sự', 'Hành chính']],
  ['Kỹ thuật - CNTT', ['Kỹ thuật camera', 'Quản trị hệ thống']],
  ['Khác', ['Khác']],
];

const CAMERA_PRESETS = {
  laptop: { label: 'Camera laptop', source: '0' },
  ptz: { label: 'Hikvision Camera', source: 'hikvision' },
};

function cameraPresetFromSource(source='0'){
  const raw=String(source??'').trim().toLowerCase();
  return raw==='1'||raw==='ptz'||raw==='hikvision'||raw.includes('ptz')||raw.startsWith('rtsp://')?'ptz':'laptop';
}
function cameraPresetLabel(preset='laptop'){
  return (CAMERA_PRESETS[preset]||CAMERA_PRESETS.laptop).label;
}
function syncCameraPresetUi(preset=state.cameraPreset||'laptop'){
  const current=CAMERA_PRESETS[preset]?preset:'laptop';
  state.cameraPreset=current;
  $$('select[data-camera-picker]').forEach(sel=>{if(sel.value!==current)sel.value=current;});
  $$('[data-camera-current]').forEach(el=>el.textContent=cameraPresetLabel(current));
  if($('#camSource'))$('#camSource').value=(CAMERA_PRESETS[current]||CAMERA_PRESETS.laptop).source;
}
function setupCameraPresetUi(){
  $$('select[data-camera-picker]').forEach(sel=>{
    if(sel.dataset.cameraBound==='1')return;
    sel.innerHTML=Object.entries(CAMERA_PRESETS).map(([key,val])=>`<option value="${key}">${val.label}</option>`).join('');
    sel.addEventListener('change',handleCameraPresetChange);
    sel.dataset.cameraBound='1';
  });
  syncCameraPresetUi(state.cameraPreset||'laptop');
}
function setCameraHandoverUi(active=false, meta={}){
  document.body.classList.toggle('camera-handover-active',!!active && meta.state!=='CHECKING');
  const banner=$('#v121HandoverBanner'),title=$('#v121HandoverState'),desc=$('#v121HandoverMeta'),badge=$('#globalCameraHandoverBadge');
  const stateName=String(meta.state||'').toUpperCase();
  const isError=stateName==='FAILED';
  if(banner){
    banner.classList.toggle('is-active',!!active);
    banner.classList.toggle('is-error',isError);
    banner.classList.toggle('is-ready',!active&&['READY','IDLE','ROLLED_BACK'].includes(String(meta.state||'IDLE').toUpperCase()));
  }
  if(badge){
    badge.textContent=active?'Đang chuyển':(isError?'Lỗi camera':'Sẵn sàng');
    badge.classList.toggle('is-active',!!active);
    badge.classList.toggle('is-error',isError);
    badge.classList.toggle('is-ready',!active&&!isError);
  }
  if(title)title.textContent=active?(meta.message||'Đang chuyển camera an toàn'):(meta.message||'Sẵn sàng');
  if(desc){
    const from=meta.from_label||meta.from_source||'',to=meta.to_label||meta.to_source||'';
    desc.textContent=active&&to?`${from?from+' → ':''}${to} · ${meta.state==='CHECKING'?'Nguồn hiện tại vẫn hoạt động':'Đang hoàn tất chuyển nguồn'}`:(meta.message||'FaceID chỉ hoạt động sau khi camera mới có đủ frame ổn định.');
  }
  const order=['PAUSING','RELEASING','OPENING','ROLLBACK','READY'];
  const stepIndex=stateName==='PAUSING'?0:stateName==='RELEASING'?1:stateName==='OPENING'?2:stateName==='ROLLBACK'?2:stateName==='READY'?4:-1;
  $$('.v121-handover-steps i').forEach((el,i)=>{el.classList.toggle('done',stepIndex>=0&&i<stepIndex);el.classList.toggle('active',active&&i===stepIndex);});
  $$('select[data-camera-picker]').forEach(sel=>sel.disabled=!!active);
  $$('.v12-device-actions button.primary').forEach(btn=>btn.disabled=!!active);
}

async function persistCameraPreset(preset='laptop'){
  const target=CAMERA_PRESETS[preset]||CAMERA_PRESETS.laptop;
  const previous=state.cameraPreset||'laptop';
  syncCameraPresetUi(preset);
  setCameraHandoverUi(true,{state:'CHECKING',from_label:cameraPresetLabel(previous),to_label:target.label,message:`Đang chuyển sang ${target.label}`});
  if($('#cameraStatus'))$('#cameraStatus').textContent=`Đang chuyển sang ${target.label}`;
  try{
    const out=await api('/api/v1/camera/select',{method:'POST',body:JSON.stringify({source:target.source})});
    if(out.ok!==false)document.dispatchEvent(new CustomEvent('btmh:camera-source-changed'));
    if($('#camSource'))$('#camSource').value=target.source;
    setCameraHandoverUi(false,out.handover||{state:'READY',message:`${target.label} đã sẵn sàng`});
    toast(`Đã chuyển an toàn sang ${target.label}.`);
    if(state.activePage==='camera-control'){mountCameraControlPreview();renderCameraControlStatus(out.ptz||{});}
    await Promise.all([loadHealth(),state.activePage==='ops-center'?loadOpsDevices():Promise.resolve()]);
    return true;
  }catch(e){
    toast(e.message,true);
    setCameraHandoverUi(false,{state:'ROLLED_BACK',message:'Camera mới không ổn định; hệ thống đã giữ hoặc khôi phục camera cũ'});
    try{await Promise.all([loadCameraSettings(),loadHealth(),state.activePage==='ops-center'?loadOpsDevices():Promise.resolve()]);}catch(_){}
    return false;
  }
}

async function prepareEnrollmentLaptopCamera(){
  const selector=$('#v5EnrollmentCameraSelect');
  const source=String(selector?.value||'browser');
  state.enrollmentSourceMode=source==='browser'?'browser':'backend';
  try{
    if(state.enrollmentSourceMode==='browser'){
      const ok=await window.BTMHV4?.startEnrollmentBrowserCamera?.();
      if(!ok)throw new Error('Camera laptop chưa sẵn sàng');
      const video=$('#enrollVideo');if(video){video.style.visibility='visible';video.style.display='block';}
      const backendPreview=$('#moduleEnrollPreview');if(backendPreview)backendPreview.remove();
      if($('#enrollHint'))$('#enrollHint').textContent='Laptop Camera đã sẵn sàng. Giữ khuôn mặt trong khung và làm theo hướng dẫn góc mặt.';
      return true;
    }
    window.BTMHV4?.stopEnrollmentBrowserCamera?.();
    if($('#enrollHint'))$('#enrollHint').textContent='Đang chuyển nguồn AI sang camera cửa hàng...';
    await api('/api/v1/camera/select',{method:'POST',body:JSON.stringify({source})});
    document.dispatchEvent(new CustomEvent('btmh:camera-source-changed'));
    mountCameraPreview('enroll');
    if($('#enrollHint'))$('#enrollHint').textContent='Camera cửa hàng đã sẵn sàng. Đứng trong vùng nhận diện và làm theo hướng dẫn.';
    return true;
  }catch(e){
    if($('#enrollHint'))$('#enrollHint').textContent=e.message||'Không mở được camera đăng ký.';
    return false;
  }
}

async function handleCameraPresetChange(ev){
  await persistCameraPreset(ev?.target?.value||'laptop');
}

function escapeHtml(v='') {
  return String(v).replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function initials(name='') {
  const p=String(name).trim().split(/\s+/).filter(Boolean);
  return (p.length ? (p[0][0] + (p.length>1?p[p.length-1][0]:'')) : 'SV').toUpperCase();
}
function pct(v) { return Math.max(0, Math.min(100, Math.round(Number(v||0)*100))); }
function formatDate(v) {
  if(!v) return '—';
  const d=new Date(v); return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('vi-VN');
}
function formatTime(v) {
  if(!v) return '—'; const d=new Date(v); return Number.isNaN(d.getTime())?String(v):d.toLocaleTimeString('vi-VN');
}
function localDateInput(d=new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function toast(msg, bad=false) {
  const el=$('#toast'); if(!el) return;
  el.textContent=msg; el.className='toast show'+(bad?' bad':'');
  clearTimeout(toast._t); toast._t=setTimeout(()=>el.className='toast',3000);
}
async function api(url, opts={}) {
  const token=localStorage.getItem('campusface_token')||'';
  const auth=token?{'Authorization':`Bearer ${token}`}:{ };
  const res=await BTMHRuntime.request(url,{...opts,timeoutMs:opts.timeoutMs||((opts.method&&opts.method!=='GET')?90000:15000),headers:{'Content-Type':'application/json',...auth,...(opts.headers||{})}});
  if(res.ok&&opts.rawResponse)return res;
  let data={}; try{data=await res.json()}catch(_){data={};}
  if(!res.ok){
    if(res.status===401&&!String(url).includes('/api/v1/auth/')){
      localStorage.removeItem('campusface_token');state.authUser=null;setAuthGate({authenticated:false,setup_required:false});
    }
    const detail=data.detail;
    const error=new Error((typeof detail==='string'?detail:detail?.message)||data.message||`HTTP ${res.status}`);
    error.status=res.status;
    error.code=detail?.code||data.code||'';error.retryAfter=Number(detail?.retry_after||res.headers.get('Retry-After')||0);
    error.field=detail?.field||'';
    throw error;
  }
  return data;
}

function applyRoleUi(user){
  const authenticated=!!user,role=String(user?.role||'').toUpperCase(),perms=new Set(user?.permissions||[]),all=perms.has('*');
  const rank={EMPLOYEE:1,VIEWER:1,SECURITY:2,TECHNICIAN:2,HR:2,OPERATOR:2,MANAGER:3,ADMIN:4,SUPER_ADMIN:5};
  $$('[data-role-min]').forEach(el=>{const required=String(el.dataset.roleMin||'').toUpperCase();const allowed=authenticated&&(!required||all||(rank[role]||0)>=(rank[required]||99));el.classList.toggle('role-locked',!allowed);});
  $$('[data-permission]').forEach(el=>{const required=String(el.dataset.permission||'').trim();el.classList.toggle('permission-locked',!authenticated||(!all&&!perms.has(required)));});
  const name=user?.display_name||user?.username||'Chưa đăng nhập';
  if($('#v23UserName'))$('#v23UserName').textContent=user?name:'Chưa đăng nhập';
  if($('#v23UserInitial'))$('#v23UserInitial').textContent=user?String(name).trim().charAt(0).toUpperCase()||'?':'?';
  syncAccountMenu(user);
  if($('#authPermissionSummary')){const shown=[...perms].filter(x=>x!=='*').slice(0,8);$('#authPermissionSummary').innerHTML=user?(all?'<span>Toàn quyền hệ thống</span>':shown.map(x=>`<span>${escapeHtml(x)}</span>`).join('')):'';}
  const privileged=['ADMIN','SUPER_ADMIN'].includes(role);
  $('#adminSecurityNav')?.classList.toggle('hidden',!privileged);
}
function syncAccountMenu(user){
  const role=String(user?.role||'').toUpperCase(),privileged=['ADMIN','SUPER_ADMIN'].includes(role);
  const roles={SUPER_ADMIN:'Chủ sở hữu',ADMIN:'Quản trị viên',MANAGER:'Quản lý',HR:'Nhân sự',SECURITY:'An ninh',TECHNICIAN:'Kỹ thuật viên',OPERATOR:'Vận hành',VIEWER:'Người xem',EMPLOYEE:'Nhân viên'};
  if($('#v23UserChip'))$('#v23UserChip').disabled=!user;
  if($('#accountMenuName'))$('#accountMenuName').textContent=user?.display_name||user?.username||'Chưa đăng nhập';
  if($('#accountMenuUsername'))$('#accountMenuUsername').textContent=user?.username?`@${user.username}`:'';
  if($('#accountMenuRole'))$('#accountMenuRole').textContent=user?(roles[role]||'Tài khoản được cấp'):'';
  const manage=$('#accountMenuManageBtn'),perms=new Set(user?.permissions||[]);
  if(manage){manage.hidden=!user||(!privileged&&!perms.has('*')&&!perms.has('system.health'));manage.textContent=privileged?'Tài khoản & bảo mật':'Cài đặt hệ thống';}
  if(!user)setAccountMenuOpen(false);
}
function setAccountMenuOpen(open=false,focus=false){
  const menu=$('#btmhAccountMenu'),trigger=$('#v23UserChip');if(!menu||!trigger)return;
  const visible=!!open&&!!state.authUser&&!document.hidden;
  menu.hidden=!visible;trigger.setAttribute('aria-expanded',String(visible));
  if(focus){if(visible)menu.querySelector('[role="menuitem"]:not([hidden]):not(:disabled)')?.focus();else trigger.focus();}
}
function toggleAccountMenu(){
  const menu=$('#btmhAccountMenu');if(!menu)return;
  if(menu.hidden){const note=$('#accountMenuNote');if(note){note.hidden=true;note.textContent='';}}
  setAccountMenuOpen(menu.hidden,true);
}
let accountMenuUiBound=false;
function bindAccountMenuUI(){
  if(accountMenuUiBound)return;accountMenuUiBound=true;
  const trigger=$('#v23UserChip'),menu=$('#btmhAccountMenu'),control=$('#btmhAccountControl');
  if(!trigger||!menu||!control)return;
  trigger.addEventListener('click',toggleAccountMenu);
  trigger.addEventListener('keydown',e=>{if(e.key==='ArrowDown'){e.preventDefault();setAccountMenuOpen(true,true);}});
  menu.addEventListener('keydown',e=>{
    if(e.key==='Escape'){e.preventDefault();setAccountMenuOpen(false,true);return;}
    if(e.key==='Tab'){setAccountMenuOpen(false,true);return;}
    if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;
    const items=Array.from(menu.querySelectorAll('[role="menuitem"]:not([hidden]):not(:disabled)'));if(!items.length)return;
    e.preventDefault();const current=items.indexOf(document.activeElement);
    const index=e.key==='Home'?0:e.key==='End'?items.length-1:e.key==='ArrowDown'?(current+1)%items.length:(current<=0?items.length:current)-1;
    items[index].focus();
  });
  $('#accountMenuManageBtn')?.addEventListener('click',openCurrentAccountModule);
  $('#accountMenuProfileBtn')?.addEventListener('click',()=>openAccountProfile('profile'));
  $('#accountMenuPasswordBtn')?.addEventListener('click',()=>openAccountProfile('password'));
  $('#accountMenuLogoutBtn')?.addEventListener('click',logoutSystem);
  document.addEventListener('pointerdown',e=>{if(!control.contains(e.target))setAccountMenuOpen(false);});
  document.addEventListener('focusin',e=>{if(!control.contains(e.target))setAccountMenuOpen(false);});
  document.addEventListener('btmh:navigate',()=>setAccountMenuOpen(false));
  document.addEventListener('btmh:auth',e=>{if(!e.detail?.authenticated)setAccountMenuOpen(false);});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)setAccountMenuOpen(false);});
  window.addEventListener('pagehide',()=>setAccountMenuOpen(false));
}
function openCurrentAccountModule(){
  if(!state.authUser)return;
  const role=String(state.authUser.role||'').toUpperCase();setAccountMenuOpen(false);
  if(['ADMIN','SUPER_ADMIN'].includes(role))navigate('admin-security');
  else if(hasUiPermission('system.health'))navigate('system');
}
window.openCurrentAccountModule=openCurrentAccountModule;
let accountProfileUi=null;
function openAccountProfile(mode='profile'){
  if(!state.authUser||!window.btmhAccountProfile)return;
  setAccountMenuOpen(false);
  if(!accountProfileUi)accountProfileUi=window.btmhAccountProfile.install({state,api,logout:logoutSystem,toast,
    onUserChanged:user=>{state.authUser=user;applyRoleUi(user);},
    openSecurity:async()=>{await logoutSystem();if(!state.authUser)setAuthFeedback('#gateLoginNote','Đăng nhập và hoàn tất xác thực để tiếp tục đổi mật khẩu.','info');}});
  const trigger=$('#v23UserChip');
  if(mode==='password')accountProfileUi.openPassword(trigger);else accountProfileUi.openProfile(trigger);
}
function hasUiPermission(permission){const p=new Set(state.authUser?.permissions||[]);return !!state.authUser&&(p.has('*')||p.has(permission));}

function setAuthGate(status){
  const gate=$('#authGate'),setup=$('#authGateSetup'),login=$('#authGateLogin');if(!gate)return;
  const authenticated=!!status?.authenticated;state.authSetupRequired=!authenticated&&status?.setup_required===true;
  gate.classList.toggle('hidden',authenticated);setup?.classList.add('hidden');login?.classList.remove('hidden');
  $('#gateOpenSetupBtn')?.classList.toggle('hidden',!state.authSetupRequired);
  $('#gateFirstSetupNotice')?.classList.toggle('hidden',!state.authSetupRequired);
  const shell=$('.app-shell');if(shell)shell.inert=!authenticated;
  if(authenticated){state.authUser=status.user||null;state.presentationSuspended=!!document.hidden||state.pagePresented===false;applyRoleUi(state.authUser);}else{state.authUser=null;state.suspendedEnrollment=null;applyRoleUi(null);pauseAppPresentation('signed-out');setGateAuthMode('login');}
  document.dispatchEvent(new CustomEvent('btmh:auth',{detail:{authenticated,user:state.authUser}}));
}
async function enforceManagementPortalAccess(status){
  const role=String(status?.user?.role||'').toUpperCase();
  if(status?.authenticated&&role==='EMPLOYEE'){
    try{await api('/api/v1/auth/logout',{method:'POST'});}catch(_){}
    const message='Tài khoản Nhân viên không có quyền vào trang quản lý. Hãy sử dụng ứng dụng nhân viên khi được triển khai.';
    const signedOut={setup_required:false,authenticated:false,user:null};
    setAuthGate(signedOut);
    setAuthFeedback('#gateLoginNote',message,'error');
    return {...signedOut,portal_denied:true,portal_message:message};
  }
  return status;
}
async function ensureProfessionalAuth(){
  try{
    const raw=await api('/api/v1/auth/status');
    const status=await enforceManagementPortalAccess(raw);
    setAuthGate(status);
    return status;
  }catch(e){
    setAuthGate({setup_required:false,authenticated:false});
    setAuthFeedback('#gateLoginNote','Không kết nối được dịch vụ xác thực. '+e.message,'error');
    return null;
  }
}
function setAuthFeedback(selector,message,type=''){
  const el=$(selector);if(!el)return;
  el.textContent=String(message||'');
  el.classList.remove('loading','success','error');
  if(type)el.classList.add(type);
}
async function verifyBrowserSession(){
  const status=await api('/api/v1/auth/status');
  if(!status?.authenticated||!status?.user)throw new Error('Máy chủ chưa xác nhận phiên đăng nhập. Hãy thử lại.');
  return status;
}
async function gateLogin(ev){
  ev?.preventDefault?.();
  const btn=$('#gateLoginBtn');if(btn?.disabled)return;
  if(btn){btn.disabled=true;const label=btn.querySelector('span');if(label)label.textContent='Đang đăng nhập...';}
  setAuthFeedback('#gateLoginNote','Đang xác thực tài khoản...','loading');
  try{
    const username=$('#gateLoginUsername')?.value?.trim()||'';
    const password=$('#gateLoginPassword')?.value||'';
    if(!username||!password)throw new Error('Hãy nhập tên đăng nhập và mật khẩu.');
    if($('#gateRememberUsername')?.checked)localStorage.setItem('btmh_remembered_username',username);
    else localStorage.removeItem('btmh_remembered_username');
    const data=await api('/api/v1/auth/login',{method:'POST',body:JSON.stringify({username,password})});
    if(data?.mfa_required||data?.mfa_setup_required){enterMfaChallenge(data);return;}
    if(!data?.token&&!data?.authenticated)throw new Error('Máy chủ chưa tạo phiên đăng nhập hợp lệ.');
    localStorage.removeItem('campusface_token');
    const status=await enforceManagementPortalAccess(await verifyBrowserSession());
    if(status?.portal_denied)throw new Error(status.portal_message);
    setAuthGate(status);
    if($('#gateLoginPassword'))$('#gateLoginPassword').value='';
    setAuthFeedback('#gateLoginNote','Đăng nhập thành công.','success');
    toast(`Xin chào ${status.user?.display_name||status.user?.username||username}.`);
    await bootAuthenticated();
    window.scrollTo({top:0,left:0,behavior:'auto'});
  }catch(e){
    localStorage.removeItem('campusface_token');
    setAuthFeedback('#gateLoginNote',e.message||'Đăng nhập thất bại.','error');
    toast(e.message||'Đăng nhập thất bại.',true);
  }finally{
    if(btn){btn.disabled=false;const label=btn.querySelector('span');if(label)label.textContent='Đăng nhập';}
  }
}
function setGateAuthMode(mode='login'){
  let normalized=['login','registration','setup','forgot','mfa'].includes(String(mode||'').toLowerCase())?String(mode).toLowerCase():'login';
  if(normalized==='setup'&&!state.authSetupRequired)normalized='login';
  state.gateAuthMode=normalized;
  if(normalized!=='registration'&&$('#gateEnrollmentInvite'))$('#gateEnrollmentInvite').value='';
  const login=$('#gateLoginView'),forgot=$('#gateForgotView'),mfa=$('#gateMfaView'),registration=$('#gateRegistrationView');
  $('#authGateSetup')?.classList.toggle('hidden',normalized!=='setup');
  $('#authGateLogin')?.classList.toggle('hidden',normalized==='setup');
  $('#gateEntryActions')?.classList.toggle('hidden',normalized==='mfa');
  login?.classList.toggle('hidden',normalized!=='login');
  forgot?.classList.toggle('hidden',normalized!=='forgot');
  mfa?.classList.toggle('hidden',normalized!=='mfa');
  registration?.classList.toggle('hidden',normalized!=='registration');
  [['#gateOpenLoginBtn','login'],['#gateOpenRegistrationBtn','registration'],['#gateOpenSetupBtn','setup']].forEach(([selector,value])=>$(selector)?.setAttribute('aria-pressed',String(normalized===value)));
  const target=normalized==='setup'?$('#gateSetupDisplay'):normalized==='registration'?$('#gateEnrollmentInvite'):normalized==='forgot'?$('#forgotReturnBtn'):normalized==='mfa'?$('#gateMfaCode'):$('#gateLoginUsername');
  setTimeout(()=>target?.focus(),80);
}

function gateOpenEnrollment(ev){
  ev?.preventDefault?.();
  const input=$('#gateEnrollmentInvite'),value=String(input?.value||'').trim();
  try{
    let invite=value;
    if(!/^[A-Za-z0-9_-]{43}$/.test(value)){
      const url=new URL(value,window.location.origin);
      if(url.origin!==window.location.origin||url.pathname!=='/enroll'||url.search)throw new Error('Hãy dùng lời mời đăng ký của hệ thống này.');
      const fragment=new URLSearchParams(url.hash.slice(1));
      invite=fragment.get('invite')||'';
      if([...fragment.keys()].some(key=>key!=='invite')||fragment.getAll('invite').length!==1)throw new Error('Lời mời đăng ký không hợp lệ.');
    }
    if(!/^[A-Za-z0-9_-]{43}$/.test(invite))throw new Error('Nhập mã hoặc đường dẫn lời mời do Chủ sở hữu / Quản trị viên cấp.');
    if(input)input.value='';
    // Keep the capability in the fragment; the enrollment page consumes it
    // into memory and removes it from browser history before contacting APIs.
    window.location.assign('/enroll#invite='+encodeURIComponent(invite));
  }catch(e){if(input)input.value='';setAuthFeedback('#gateEnrollmentNote',e.message||'Lời mời đăng ký không hợp lệ.','error');}
}

function validateStrongPassword(password,confirmation,min=12){
  const raw=String(password||'');
  if(raw.length<min)throw new Error(`Mật khẩu phải có ít nhất ${min} ký tự.`);
  if(!/[A-Z]/.test(raw)||!/[a-z]/.test(raw)||!/[0-9]/.test(raw)||!/[^A-Za-z0-9]/.test(raw)){
    throw new Error('Mật khẩu cần có chữ hoa, chữ thường, số và ký tự đặc biệt.');
  }
  if(raw!==String(confirmation||''))throw new Error('Mật khẩu nhập lại không khớp.');
}

function enterMfaChallenge(data={}){
  state.mfaChallenge=String(data.challenge_id||'');
  state.mfaSetupRequired=false;
  state.mfaMethod=data.mfa_method||'TOTP';
  state.mfaRecoveryCodes=[];
  state.pendingMfaStatus=null;
  if(!state.mfaChallenge)throw new Error('Máy chủ chưa tạo phiên xác thực hai lớp.');
  $('#authGateSetup')?.classList.add('hidden');
  $('#authGateLogin')?.classList.remove('hidden');
  const setup=data.mfa_setup||{};
  $('#gateMfaSetupBox')?.classList.toggle('hidden',!state.mfaSetupRequired);
  $('#gateMfaVerifyBox')?.classList.remove('hidden');
  $('#gateMfaRecoveryBox')?.classList.add('hidden');
  if($('#gateMfaSecret'))$('#gateMfaSecret').textContent=setup.secret||'—';
  if($('#gateMfaUri'))$('#gateMfaUri').value=setup.otpauth_uri||'';
  if($('#gateMfaCode'))$('#gateMfaCode').value='';
  if($('#gateMfaTitle'))$('#gateMfaTitle').textContent=state.mfaSetupRequired?'Thiết lập ứng dụng xác thực':'Xác minh đăng nhập';
  if($('#gateMfaDescription'))$('#gateMfaDescription').textContent=state.mfaSetupRequired
    ?'Thêm tài khoản vào Google Authenticator hoặc Microsoft Authenticator, rồi nhập mã 6 số để kích hoạt.'
    :'Nhập mã 6 số từ ứng dụng Authenticator hoặc một mã khôi phục còn hiệu lực.';
  const smsMode=state.mfaMethod==='SMS';
  $('#gateSmsActions')?.classList.toggle('hidden',!smsMode);
  $('#gateTrustBrowser').checked=false;
  if(smsMode){
    $('#gateMfaTitle').textContent='Xác minh qua điện thoại';
    $('#gateMfaDescription').textContent=`Gửi mã đến số đã xác minh ${data.destination_hint||''}. Không cần cài ứng dụng xác thực.`;
    $('#gateSmsSend').disabled=!data.provider_ready;
    $('#gateSmsSend').textContent='Gửi mã SMS';
    setAuthFeedback('#gateMfaNote',data.provider_ready?'Chọn gửi SMS hoặc nhập mã khôi phục.':'SMS chưa sẵn sàng. Dùng mã khôi phục hoặc liên hệ người quản lý.');
  }else{
    setAuthFeedback('#gateMfaNote','Tài khoản đã bật Authenticator. Sau khi đăng nhập, có thể chuyển sang SMS trong Bảo mật tài khoản.');
  }
  setGateAuthMode('mfa');
}

async function finishMfaLogin(){
  const status=await enforceManagementPortalAccess(state.pendingMfaStatus||await verifyBrowserSession());
  state.pendingMfaStatus=null;
  window.btmhSms?.stopLoginTimer();
  if($('#gateLoginPassword'))$('#gateLoginPassword').value='';
  if($('#gateMfaCode'))$('#gateMfaCode').value='';
  state.mfaChallenge='';state.mfaSetupRequired=false;state.mfaRecoveryCodes=[];
  if(status?.portal_denied)throw new Error(status.portal_message);
  setAuthGate(status);
  toast('Xác thực thành công.');
  await bootAuthenticated();
  window.scrollTo({top:0,left:0,behavior:'auto'});
}

async function gateMfaVerify(){
  const btn=$('#gateMfaVerifyBtn');if(btn?.disabled)return;if(btn)btn.disabled=true;
  setAuthFeedback('#gateMfaNote','Đang xác minh...','loading');
  try{
    if(!state.mfaChallenge)throw new Error('Phiên xác thực đã hết hạn. Hãy đăng nhập lại.');
    const code=$('#gateMfaCode')?.value?.trim()||'';
    if(!/^\d{6}$/.test(code)&&!/^[A-Za-z0-9-]{12,40}$/.test(code))throw new Error('Nhập mã xác minh 6 số hoặc mã khôi phục hợp lệ.');
    const out=await api(state.mfaMethod==='SMS'?'/api/v1/auth/sms/verify':'/api/v1/auth/mfa/verify',{method:'POST',body:JSON.stringify({challenge_id:state.mfaChallenge,code,trust_browser:!!$('#gateTrustBrowser')?.checked})});
    if(!out?.token&&!out?.authenticated)throw new Error('Máy chủ chưa tạo phiên đăng nhập sau xác thực.');
    localStorage.removeItem('campusface_token');
    state.pendingMfaStatus=await verifyBrowserSession();
    const recovery=Array.isArray(out.recovery_codes)?out.recovery_codes:[];
    if(recovery.length){
      state.mfaRecoveryCodes=recovery;
      if($('#gateMfaRecoveryCodes'))$('#gateMfaRecoveryCodes').innerHTML=recovery.map(x=>`<code>${escapeHtml(x)}</code>`).join('');
      $('#gateMfaVerifyBox')?.classList.add('hidden');
      $('#gateMfaSetupBox')?.classList.add('hidden');
      $('#gateMfaRecoveryBox')?.classList.remove('hidden');
      setAuthFeedback('#gateMfaNote','Hãy lưu các mã khôi phục trước khi tiếp tục.','success');
      return;
    }
    await finishMfaLogin();
  }catch(e){
    setAuthFeedback('#gateMfaNote',e.message||'Mã xác thực không hợp lệ.','error');
    toast(e.message||'Mã xác thực không hợp lệ.',true);
  }finally{if(btn)btn.disabled=false;}
}

function gateMfaCancel(){
  window.btmhSms?.stopLoginTimer();
  if(state.mfaMethod==='SMS'&&state.mfaChallenge)api('/api/v1/auth/sms/cancel',{method:'POST',body:JSON.stringify({challenge_id:state.mfaChallenge})}).catch(()=>{});
  state.mfaChallenge='';state.mfaSetupRequired=false;state.mfaRecoveryCodes=[];state.pendingMfaStatus=null;
  $('#gateMfaSetupBox')?.classList.add('hidden');
  $('#gateMfaRecoveryBox')?.classList.add('hidden');
  $('#gateMfaVerifyBox')?.classList.remove('hidden');
  if($('#gateMfaCode'))$('#gateMfaCode').value='';
  setGateAuthMode('login');
  setAuthFeedback('#gateLoginNote','Phiên xác thực đã hủy. Hãy đăng nhập lại.','');
}

async function copyTextValue(text,success='Đã sao chép.'){
  const value=String(text||'');if(!value)return;
  try{await navigator.clipboard.writeText(value);toast(success);}catch{toast('Không thể sao chép tự động. Hãy sao chép thủ công.',true);}
}

async function gateBootstrap(ev){
  ev?.preventDefault?.();
  const btn=$('#gateSetupBtn');if(btn?.disabled)return;if(btn)btn.disabled=true;
  setAuthFeedback('#gateSetupNote','Đang khởi tạo tài khoản Chủ sở hữu...','loading');
  try{
    const username=$('#gateSetupUsername')?.value?.trim()||'';
    const display_name=$('#gateSetupDisplay')?.value?.trim()||'';
    const password=$('#gateSetupPassword')?.value||'';
    const password2=$('#gateSetupPassword2')?.value||'';
    if(username.length<3)throw new Error('Tên đăng nhập phải có ít nhất 3 ký tự.');
    if(!display_name)throw new Error('Hãy nhập họ và tên Chủ sở hữu.');
    validateStrongPassword(password,password2,12);
    const out=await api('/api/v1/auth/bootstrap-local',{method:'POST',body:JSON.stringify({username,display_name,password,phone:''})});
    if(out?.mfa_required||out?.mfa_setup_required){enterMfaChallenge(out);return;}
    localStorage.removeItem('campusface_token');
    const status=await verifyBrowserSession();
    setAuthGate(status);
    $('#gateSetupPassword').value='';$('#gateSetupPassword2').value='';
    await bootAuthenticated();
    toast('Đã tạo Chủ sở hữu. Có thể bật SMS sau trong Bảo mật tài khoản.');
  }catch(e){
    setAuthFeedback('#gateSetupNote',e.message||'Không thể khởi tạo Chủ sở hữu.','error');
    if([400,409].includes(e.status)){
      try{
        const status=await api('/api/v1/auth/status');
        if(!status?.setup_required){
          setAuthGate(status);
          if(status?.authenticated)await bootAuthenticated();
          else setAuthFeedback('#gateLoginNote','Hệ thống đã được thiết lập. Hãy đăng nhập bằng tài khoản được cấp.','');
        }
      }catch(_){}
    }
    toast(e.message||'Không thể khởi tạo Chủ sở hữu.',true);
  }finally{if(btn)btn.disabled=false;}
}

function setDot(el, status='') {
  if(!el) return; el.className='dot'+(status==='ok'?' green':status==='warn'?' amber':status==='bad'?' red':'');
}
function setSignal(sel,status='') {
  const el=$(sel); if(!el)return; el.className='signal-dot'+(status?` ${status}`:'');
}

function resetRecognitionTransientUi(){
  state.recognitionProfileKey='';
  setEntryBadge('Sẵn sàng','neutral');
  setRecognitionProgress(0,'Sẵn sàng');
  if($('#recognitionAlert')){
    $('#recognitionAlert').className='alert-box neutral';
    $('#recognitionAlert').textContent='Camera vẫn chạy liên tục; AI sẽ cập nhật theo trạng thái hiện tại.';
  }
}

function navigate(page) {
  if(!document.getElementById(`page-${page}`))return;
  if(!appPresentationActive())return;
  state.presentationEpoch++;
  const previousPage=state.activePage;
  stopQREnrollmentPanels();
  // Stop page-owned browser work, not background recognition/recording.
  window.BTMHV4?.leavePage?.(page);
  if(previousPage==='register'&&page!=='register'){
    clearInterval(state.enrollTimer);state.enrollTimer=null;
    state.enrollRequestController?.abort();state.enrollRequestController=null;state.enrollBusy=false;state.suspendedEnrollment=null;
    window.BTMHV4?.stopEnrollmentBrowserCamera?.();
  }
  BTMHRuntime.stopAll();
  if(previousPage==='recognition'){window.BTMHRecognitionSlots?.stop?.();window.BTMHRecentRecognition?.stop?.();}
  if(previousPage==='history')window.BTMHDemoReports?.stop?.();
  if(previousPage==='ops-center')window.BTMHCameraConfiguration?.stop?.();
  window.BTMHMedia?.stopAll?.();
  state.activePage=page;
  if(page!=='register')pauseCameraPreview('enroll');
  if(page!=='recognition')pauseCameraPreview('recognition');
  if(page!=='system')pauseSystemCameraPreview();
  if(page!=='camera-control')stopCameraControlView();
  if(page!=='live-monitor')stopV13LiveMonitor();
  if(page!=='dashboard')stopV13DashboardPreview();
  if(!['dashboard','live-monitor'].includes(page))stopV13OpsSocket();
  if(previousPage==='recognition'&&page!=='recognition')resetRecognitionTransientUi();
  $$('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${page}`));
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===page));
  const meta=pageMeta[page]||[page,''];
  if($('#pageTitle')) $('#pageTitle').textContent=meta[0];
  if($('#pageSubtitle')) $('#pageSubtitle').textContent=meta[1];
  if(page==='students'){loadStudents();showStudentList();}
  if(page==='work-shifts'){loadV5ShiftWorkspace();}
  if(page==='incidents'){loadV5Incidents();}
  if(page==='visitors'){loadVisitors();}
  if(page==='register'){loadStudents();loadEnrollmentStores();}
  if(page==='recognition'){state.recognitionEnteredAt=Date.now();resetRecognitionTransientUi();mountCameraPreview('recognition');loadRecognitionHistory();}
  if(page==='history'){state.historyMode=state.historyMode||'RECOGNITION';loadHistory();requestAnimationFrame(()=>{window.scrollTo({top:0,left:0,behavior:'auto'});document.querySelector('.main')?.scrollTo({top:0,left:0,behavior:'auto'});});}
  if(page==='dashboard'){if(window.BTMHManagement)window.BTMHManagement.start();else{startV13DashboardPreview();startV13OpsSocket();loadDashboard();}}
  if(page==='live-monitor'){startV13LiveMonitor();startV13OpsSocket();}
  if(page==='hr-report'){loadHrReport();}
  if(page==='operations'){window.BTMHV4?.loadPresence?.();}
  if(page==='live-grid'){window.BTMHV4?.loadFleet?.();}
  if(page==='playback'){window.BTMHV4?.loadPlayback?.();}
  if(page==='camera-control'){startCameraControlView();}
  if(page==='ops-center'){loadOpsCenter();}
  if(page==='admin-security'){loadAdminSecurityModule();}
  if(page==='system'){mountSystemCameraPreview();void loadSystemPage().catch(e=>{if(e.name!=='AbortError')console.warn('[BTMH] system page load failed:',e);});}
  document.dispatchEvent(new CustomEvent('btmh:navigate',{detail:{page,previousPage}}));
}
window.navigate=navigate;

function bindNavigation(){
  $$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>navigate(btn.dataset.page)));
}
function startClock(){
  if(state.clockTimer||document.hidden||state.presentationSuspended||state.pagePresented===false)return;
  const tick=()=>{if(!document.hidden&&!state.presentationSuspended&&state.pagePresented!==false&&$('#clock'))$('#clock').textContent=new Date().toLocaleTimeString('vi-VN')}; tick(); state.clockTimer=setInterval(tick,1000);
}
function stopAppPolling(){
  if(state.clockTimer){clearInterval(state.clockTimer);state.clockTimer=null;}
  for(const timer of state.appPollingTimers||[])clearInterval(timer);
  state.appPollingTimers=[];
}
function startAppPolling(){
  if(!appPresentationActive())return;
  startClock();
  if(state.appPollingTimers?.length)return;
  state.appPollingTimers=[
    setInterval(()=>{if(appPresentationActive())BTMHRuntime.once('health',()=>appPresentationActive()?loadHealth():undefined).catch(()=>{})},5000),
    setInterval(()=>{if(appPresentationActive()&&hasUiPermission('camera.live'))BTMHRuntime.once('recognition',pollRecognition).catch(()=>{})},650),
    setInterval(()=>{if(!appPresentationActive())return;if(state.activePage==='operations'&&hasUiPermission('attendance.view'))BTMHRuntime.once('attendance',()=>appPresentationActive()&&state.activePage==='operations'?loadAttendancePage():undefined).catch(()=>{});if(state.activePage==='visitors'&&hasUiPermission('visitor.view'))BTMHRuntime.once('visitors',()=>appPresentationActive()&&state.activePage==='visitors'?loadVisitors():undefined).catch(()=>{});if(state.activePage==='dashboard'&&hasUiPermission('dashboard.view')&&Date.now()-state.v13LastSummaryAt>10000)BTMHRuntime.once('dashboard',()=>appPresentationActive()&&state.activePage==='dashboard'?loadDashboard():undefined).catch(()=>{});},5000),
  ];
}

// One physical camera service feeds enrollment and recognition previews.
function setCameraEmpty(kind, show, text=''){
  const sel={enroll:'#enrollEmpty',recognition:'#recognitionEmpty'}[kind];
  const el=sel?$(sel):null;if(!el)return;
  el.style.display=show?'grid':'none';
  if(text){const p=el.querySelector('p');if(p)p.textContent=text;}
}

function mountCameraPreview(kind){
  if(!appPresentationActive())return;
  if(kind==='recognition'&&window.BTMHRecognitionSlots){window.BTMHRecognitionSlots.start();return;}
  const configs={
    enroll:{wrap:'.faceid-camera-wrap',video:'#enrollVideo',empty:'#enrollEmpty',id:'moduleEnrollPreview',mirror:true,stream:'/api/v1/camera/stream_raw.mjpg'},
    recognition:{wrap:'.entry-camera-wrap',video:'#recognitionVideo',empty:'#recognitionEmpty',id:'moduleRecognitionPreview',mirror:false,fit:'contain',stream:'/api/v1/camera/stream.mjpg'},
  };
  const cfg=configs[kind]||configs.recognition;
  const wrap=$(cfg.wrap),video=$(cfg.video);if(!wrap)return;
  let img=$(`#${cfg.id}`);
  if(!img){
    img=document.createElement('img');img.id=cfg.id;img.className='module-service-preview';img.alt='Camera local';
    img.style.cssText=`position:absolute;inset:0;width:100%;height:100%;object-fit:${cfg.fit||'cover'};object-position:center center;z-index:2;transform:${cfg.mirror?'scaleX(-1)':'none'};`;
    const canvas=wrap.querySelector('canvas');if(canvas)wrap.insertBefore(img,canvas);else wrap.prepend(img);
  }

  // V5.4.10: recognition prefers native MediaMTX/WHEP transport. The compatibility layer
  // falls back to Python WebRTC, then ACK-paced WebSocket bitmap only if needed.
  // All fallbacks are bounded and independent from FaceID/PAD latency.
  if(kind==='recognition'&&window.BTMHMedia){
    if(window.BTMHMedia.stats?.().recognition)return;
    if(video)video.style.visibility='visible';
    setCameraEmpty(kind,true,'Đang mở luồng camera realtime...');
    window.BTMHMedia.mount('recognition',{
      wrap,video,image:img,empty:$('#recognitionEmpty'),overlay:$('#recognitionOverlay'),
      fit:'contain',mirror:false,mjpegUrl:'/api/v1/camera/stream.mjpg',pollUrl:'/api/v1/camera/frame.jpg'
    });
    return;
  }

  if(video)video.style.visibility='hidden';
  img.onload=()=>setCameraEmpty(kind,false);
  img.onerror=()=>setCameraEmpty(kind,true,'Đang kết nối lại camera...');
  if(!img.dataset.started){BTMHRuntime.preview(img,cfg.stream.replace('stream_raw.mjpg','frame_raw.jpg').replace('stream.mjpg','frame.jpg'),90);setCameraEmpty(kind,true,'Đang mở camera...');}
}

function pauseCameraPreview(kind){
  if(kind==='recognition'&&window.BTMHRecognitionSlots){window.BTMHRecognitionSlots.stop();return;}
  if(kind==='recognition')window.BTMHMedia?.stop?.('recognition');
  const id={enroll:'moduleEnrollPreview',recognition:'moduleRecognitionPreview'}[kind];
  const img=id?document.getElementById(id):null;if(!img)return;
  BTMHRuntime.stopPreview(img);delete img.dataset.started;
}

function cameraUiName(value=''){
  return String(value||'').replace(/[\x00-\x1f\x7f]/g,' ').replace(/(?:rtsps?|https?):\/\/\S+/gi,'[ẩn]').replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g,'[ẩn]').slice(0,120)||'Camera';
}
function cameraUiStatus(camera={}){
  const name=String(camera.state||'').toLowerCase();
  return name==='online'&&camera.opened?'Trực tuyến':['opening','connecting','reconnecting'].includes(name)?'Đang kết nối':['error','offline','stopped','stopping'].includes(name)?'Mất kết nối':'Chưa ghi nhận';
}
function renderMediaPlayback(d={}){
  const targets={recognition:[null,'.entry-live-badge'],dashboard:[null,'#v13DashboardLive'],'live-monitor':[null,'#v13MonitorLive']};
  const target=targets[d.key];if(!target)return;
  const badge=$(target[1]);if(badge){const label=d.state==='live'?'LIVE':['failed','offline','stopped'].includes(d.state)?'Mất kết nối':'Đang kết nối';badge.classList.toggle('offline',d.state!=='live');badge.innerHTML=`<i></i> ${label}`;badge.title=label;}
  if(d.key==='recognition'){if(d.state==='live')setCameraEmpty('recognition',false);else setCameraEmpty('recognition',true,'Đang kết nối luồng realtime...');}
}
document.addEventListener('btmh:media-stats',e=>renderMediaPlayback(e.detail||{}));
document.addEventListener('btmh:media-state',e=>renderMediaPlayback(e.detail||{}));

function mountSystemCameraPreview(){
  if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('camera.live'))return;
  const img=$('#systemCameraPreview'),empty=$('#systemCameraEmpty');if(!img)return;
  if(img.dataset.started==='1')return;
  img.dataset.started='1';
  img.onload=()=>empty?.classList.add('hidden');
  img.onerror=()=>empty?.classList.remove('hidden');
  BTMHRuntime.preview(img,'/api/v1/camera/frame_raw.jpg',150);
}
function pauseSystemCameraPreview(){
  state.systemSettingsController?.abort();state.systemSettingsController=null;
  state.systemTechnicalController?.abort();state.systemTechnicalController=null;
  state.systemDiagEpoch++;state.systemDiagController?.abort();state.systemDiagController=null;
  state.systemProductionController?.abort();state.systemProductionController=null;
  state.systemProductionCheckController?.abort();state.systemProductionCheckController=null;
  state.systemEdgeController?.abort();state.systemEdgeController=null;
  for(const key of ['system-production-status','system-production-check','system-edge-nodes'])BTMHRuntime.cancel?.(key);
  if(state.systemTimer){clearInterval(state.systemTimer);state.systemTimer=null;}
  const img=$('#systemCameraPreview');if(!img)return;
  BTMHRuntime.stopPreview(img);delete img.dataset.started;img.onload=null;img.onerror=null;
  $('#systemCameraEmpty')?.classList.remove('hidden');
}

async function loadHealth(){
  if(!appPresentationActive())return;
  const epoch=state.presentationEpoch;
  try{
    const h=await api('/api/v1/health');if(epoch!==state.presentationEpoch||!appPresentationActive())return; state.health=h; const c=h.camera||{},handover=c.handover||{};
    const cameraState=String(c.state||'').toLowerCase();
    if(c.source!==undefined&&c.source!==null)syncCameraPresetUi(cameraPresetFromSource(c.source));
    const inHandover=!!(c.handover_active||handover.active);
    const recognitionPaused=!!c.recognition_paused;
    const opened=!!c.opened && cameraState==='online';
    const cameraText=inHandover?'Đang chuyển camera':`Camera · ${cameraUiStatus(c)}`;
    if($('#cameraStatus'))$('#cameraStatus').textContent=cameraText;
    setDot($('#cameraDot'),opened?'ok':cameraState==='error'?'bad':'warn');
    setCameraHandoverUi(inHandover,handover);
    const playback=window.BTMHMedia?.stats?.().recognition;if(playback)renderMediaPlayback(playback);
    if($('#latencyValue'))$('#latencyValue').textContent=`${Math.round(Number(c.last_ai_ms||0))||0} ms`;
    if($('#v20StudentsMeta'))$('#v20StudentsMeta').textContent=`${state.students.length} đang quản lý`;
    renderV13TopStatus(h);renderV13Performance(c.performance||{},c);
    if(opened || cameraState==='opening' || cameraState==='reconnecting'){if(state.activePage==='recognition')mountCameraPreview('recognition');if(state.activePage==='register'&&state.enrollmentSourceMode!=='browser')mountCameraPreview('enroll');}
  }catch(e){
    if(epoch!==state.presentationEpoch||!appPresentationActive())return;
    if($('#cameraStatus'))$('#cameraStatus').textContent='Module chưa kết nối'; setDot($('#cameraDot'),'bad');
  }
}

function v13ToneForLoad(load='NORMAL'){
  const v=String(load||'NORMAL').toUpperCase();return v==='HIGH'?'high':v==='BUSY'?'busy':v==='RECOVERING'?'recovering':'';
}
function setV13Chip(sel,text,tone=''){
  const el=$(sel);if(!el)return;el.classList.remove('warn','bad');if(tone)el.classList.add(tone);const b=el.querySelector('b');if(b)b.textContent=text;
}
function renderV13TopStatus(h={}){
  const c=h.camera||{},db=h.database||{},templates=h.templates||{};
  const load=String(c.ai_load_state||c.performance?.load_state||'NORMAL').toUpperCase();
  const aiReady=!!h.models_ready&&String(c.state||'').toLowerCase()==='online';
  setV13Chip('#v13TopAi',aiReady?(load==='NORMAL'?'\u1ed4n \u0111\u1ecbnh':load==='HIGH'?'T\u1ea3i cao':'\u0110ang x\u1eed l\u00fd'):'\u0110ang ch\u1edd',aiReady?(load==='HIGH'?'bad':load==='BUSY'?'warn':''):'warn');
  const dbOk=String(db.mode||'').toLowerCase()!=='error'&&!!db.mode;setV13Chip('#v13TopDb',dbOk?'Đã cấu hình':'Cần kiểm tra',dbOk?'':'bad');
  const playback=window.BTMHMedia?.stats?.()||{};
  ['dashboard','live-monitor'].forEach(key=>{if(playback[key])renderMediaPlayback(playback[key]);});
  if($('#v13DashboardCameraName'))$('#v13DashboardCameraName').textContent=cameraUiName(c.camera_name||c.source_label||'Camera hiện tại');
  if($('#v13MonitorCameraName'))$('#v13MonitorCameraName').textContent=cameraUiName(c.camera_name||c.source_label||'Camera hiện tại');
}
function renderV13Performance(perf={},camera={}){
  const p=Object.keys(perf||{}).length?perf:(camera.performance||{});const load=String(p.load_state||camera.ai_load_state||'NORMAL').toUpperCase();const tone=v13ToneForLoad(load);
  const loadLabels={NORMAL:'BÌNH THƯỜNG',BUSY:'ĐANG TẢI',HIGH:'TẢI CAO',RECOVERING:'ĐANG PHỤC HỒI'};const loadText=loadLabels[load]||load;
  [['#v13PerfState',loadText],['#v13MonitorPerfState',loadText]].forEach(([sel,text])=>{const el=$(sel);if(!el)return;el.textContent=text;el.className=`v13-perf-state ${tone}`.trim();});
  const target=Number(p.effective_target_fps??camera.ai_target_fps_effective??0),actual=Number(p.actual_ai_fps??camera.ai_fps??0),p95=Number(p.p95_ai_ms??camera.p95_ai_ms??0),drop=Number(p.drop_ratio??camera.ai_drop_ratio??0)*100;
  const values={v13PerfTarget:`${target.toFixed(1)} FPS`,v13PerfActual:`${actual.toFixed(1)} FPS`,v13PerfP95:`${Math.round(p95)} ms`,v13PerfDrop:`${drop.toFixed(1)}%`,v13MonitorTarget:`${target.toFixed(1)} FPS`,v13MonitorActual:`${actual.toFixed(1)} FPS`,v13MonitorLatency:`${Math.round(p95)} ms`,v13MonitorDrop:`${drop.toFixed(1)}%`,v13DashFaces:String(p.visible_faces??camera.visible_faces??0),v13DashTracks:String(p.visible_tracks??camera.visible_tracks??0),v13DashAiFps:`${actual.toFixed(1)} FPS`,v13DashLatency:`${Math.round(Number(p.last_ai_ms??camera.last_ai_ms??0))} ms`,v13MonitorFaces:String(p.visible_faces??camera.visible_faces??0),v13MonitorTracks:String(p.visible_tracks??camera.visible_tracks??0),v13MonitorAiFps:`${actual.toFixed(1)} FPS`,v13MonitorP95:`${Math.round(p95)} ms`};
  Object.entries(values).forEach(([id,val])=>{const el=document.getElementById(id);if(el)el.textContent=val;});
  const summary=load==='HIGH'?'Tải xử lý cao · hệ thống đang tự giảm nhịp AI':load==='BUSY'?'Đang xử lý nhiều người · vẫn ưu tiên nhận diện':load==='RECOVERING'?'Tải đã giảm · hệ thống đang phục hồi nhịp xử lý':'Tải xử lý ổn định';if($('#v131PerformanceSummary'))$('#v131PerformanceSummary').textContent=summary;
  if($('#v13PerfReason'))$('#v13PerfReason').textContent=summary;if($('#v13MonitorReason'))$('#v13MonitorReason').textContent=summary;
}
function renderV13Events(items=[]){
  const host=$('#v13OpsEvents');if(!host)return;const rows=(items||[]).slice(0,7);host.innerHTML=rows.length?rows.map(x=>{const st=String(x.status||'').toUpperCase(),unknown=st==='UNREGISTERED'||st==='UNKNOWN_PERSON',blocked=st==='SPOOF_BLOCKED',tone=st==='RECOGNIZED'?'success':blocked?'bad':unknown?'warn':'',icon=st==='RECOGNIZED'?'ID':blocked?'!':'K';const name=blocked?'Khuôn mặt bị chặn':unknown?'Khách hàng':(x.full_name||x.student?.full_name||'Chưa xác định');const meta=unknown?'Khách chưa có FaceID nhân viên':(x.student_code||x.student?.student_code||st||'EVENT');return `<div class="v13-event-row ${tone}"><div class="icon">${icon}</div><div><b>${escapeHtml(name)}</b><small>${escapeHtml(meta)}${unknown?'':` · ${pct(x.confidence||0)}%`}</small></div><time>${formatDate(x.event_at)}</time></div>`}).join(''):'<div class="empty-card">Chưa có sự kiện.</div>';
}
function stopV13DashboardPreview(){if(state.v13DashboardFrameTimer){clearTimeout(state.v13DashboardFrameTimer);state.v13DashboardFrameTimer=null;}window.BTMHMedia?.stop?.('dashboard');const img=$('#v13DashboardPreview');if(img){img.removeAttribute('src');img.onload=null;img.onerror=null;}$('#v13DashboardPreviewEmpty')?.classList.remove('hidden');}
function startV13DashboardPreview(){
  if(!appPresentationActive()||state.activePage!=='dashboard'||!hasUiPermission('camera.live'))return;
  stopV13DashboardPreview();const img=$('#v13DashboardPreview'),empty=$('#v13DashboardPreviewEmpty');if(!img)return;
  if(window.BTMHMedia){window.BTMHMedia.mount('dashboard',{wrap:'.v13-dashboard-preview',image:img,empty,fit:'contain',mjpegUrl:'/api/v1/camera/stream.mjpg',pollUrl:'/api/v1/camera/frame.jpg'});return;}
  img.onload=()=>empty?.classList.add('hidden');img.onerror=()=>empty?.classList.remove('hidden');BTMHRuntime.preview(img,'/api/v1/camera/frame.jpg',180);
}
function stopV13LiveMonitor(){
  if(state.v13MonitorTimer){clearInterval(state.v13MonitorTimer);state.v13MonitorTimer=null;}window.BTMHMedia?.stop?.('live-monitor');const img=$('#v13MonitorPreview');if(img){img.removeAttribute('src');img.onload=null;img.onerror=null;}$('#v13MonitorEmpty')?.classList.remove('hidden');
}
async function loadV13MonitorDevices(){
  const host=$('#v13MonitorDevices');if(!host||!appPresentationActive()||state.activePage!=='live-monitor'||!hasUiPermission('camera.live'))return;
  const actor=state.authUser,epoch=state.presentationEpoch;
  try{const d=await api('/api/v1/recognition/cameras',{timeoutMs:6000});if(actor!==state.authUser||epoch!==state.presentationEpoch||!appPresentationActive()||state.activePage!=='live-monitor')return;const rows=d.items||[];
    host.innerHTML=rows.length?rows.map(x=>{const online=x.connection_state==='ONLINE',label=online?'Trực tuyến':x.connection_state==='OFFLINE'?'Mất kết nối':'Chưa ghi nhận';return `<div class="v13-device-row ${online?'online':''}"><i></i><div><b>${escapeHtml(cameraUiName(x.camera_name||x.name))}</b><small>${escapeHtml([cameraUiName(x.store_name||'Chưa gán cửa hàng'),cameraUiName(x.zone_name||'Chưa đặt khu vực')].join(' · '))}</small><small>${label}</small></div></div>`}).join(''):'<div class="empty-card">Chưa có camera trong phạm vi được cấp quyền.</div>';
  }catch(e){if(actor===state.authUser&&epoch===state.presentationEpoch&&appPresentationActive()&&state.activePage==='live-monitor')host.innerHTML='<div class="empty-card">Không tải được camera. Chọn Làm mới để thử lại.</div>';}
}
window.v13ActivateCamera=async(id)=>{if(typeof window.activateOpsCamera==='function'){await window.activateOpsCamera(id);await loadV13MonitorDevices();}else{toast('Chức năng chuyển camera chưa sẵn sàng.',true)}};
async function loadV13Performance(){if(!hasUiPermission('system.diagnostics')||(!$('#v13MonitorPerfState')&&!$('#v13PerfState')))return null;try{const d=await api('/api/v1/performance/status');renderV13Performance(d.performance||{},d.camera||{});renderV13TopStatus({camera:d.camera||{},database:state.health?.database||{},templates:state.health?.templates||{},models_ready:state.health?.models_ready});return d;}catch(_){return null}}
function startV13LiveMonitor(){
  if(!appPresentationActive()||state.activePage!=='live-monitor'||!hasUiPermission('camera.live'))return;
  const refresh=()=>{if(appPresentationActive()&&state.activePage==='live-monitor')return BTMHRuntime.once('live-monitor-refresh',()=>Promise.all([loadV13MonitorDevices(),loadV13Performance()]));};
  stopV13LiveMonitor();const img=$('#v13MonitorPreview'),empty=$('#v13MonitorEmpty');if(img){if(window.BTMHMedia)window.BTMHMedia.mount('live-monitor',{wrap:'.v13-monitor-video',image:img,empty,fit:'contain',mjpegUrl:'/api/v1/camera/stream.mjpg',pollUrl:'/api/v1/camera/frame.jpg'});else{img.onload=()=>empty?.classList.add('hidden');img.onerror=()=>empty?.classList.remove('hidden');BTMHRuntime.preview(img,'/api/v1/camera/frame.jpg',150);}}void refresh()?.catch(()=>{});state.v13MonitorTimer=setInterval(()=>{void refresh()?.catch(()=>{});},3000);
}
function stopV13OpsSocket(){
  const ws=state.v13OpsSocket;state.v13OpsSocket=null;
  if(ws){ws.onclose=ws.onerror=ws.onmessage=null;try{ws.close()}catch(_){}}
  clearTimeout(state.v13OpsSocketRetry);state.v13OpsSocketRetry=null;
  clearTimeout(state.v543SocketWatchdog);state.v543SocketWatchdog=null;
}
function startV13OpsSocket(){
  const allowed=()=>appPresentationActive()&&hasUiPermission('camera.live')&&['dashboard','live-monitor'].includes(state.activePage);
  if(!('WebSocket' in window)||!allowed())return;
  if(state.v13OpsSocket&&state.v13OpsSocket.readyState<=1)return;
  const scheme=location.protocol==='https:'?'wss':'ws';
  const ws=new WebSocket(`${scheme}://${location.host}/api/v1/operations/live/ws`);state.v13OpsSocket=ws;
  const watchdog=()=>{clearTimeout(state.v543SocketWatchdog);state.v543SocketWatchdog=setTimeout(()=>{if(state.v13OpsSocket===ws)ws.close();},8000);};
  watchdog();
  ws.onmessage=e=>{if(state.v13OpsSocket!==ws||!allowed())return;watchdog();try{const d=JSON.parse(e.data||'{}');if(d.camera)renderV13TopStatus({camera:d.camera,database:state.health?.database||{},templates:state.health?.templates||{},models_ready:state.health?.models_ready});if(d.performance)renderV13Performance(d.performance,d.camera||{});if(d.latest_event&&state.activePage==='dashboard'){const old=state.dashboardSummary?.latest||[];renderV13Events([d.latest_event,...old.filter(x=>Number(x.id)!==Number(d.latest_event.id))]);}}catch(_){}};
  ws.onclose=()=>{if(state.v13OpsSocket!==ws)return;state.v13OpsSocket=null;clearTimeout(state.v543SocketWatchdog);if(allowed())state.v13OpsSocketRetry=setTimeout(startV13OpsSocket,1800);};
  ws.onerror=()=>{};
}

function fillFacultyOptions(){
  const extra=[...new Set(state.students.map(s=>String(s.faculty||'').trim()).filter(Boolean))];
  const names=[...new Set([...FACULTY_CATALOG.map(x=>x[0]),...extra])];
  for(const id of ['#faculty','#newStudentFaculty','#studentFacultyFilter']){
    const el=$(id); if(!el)continue; const old=el.value; const placeholder=id==='#studentFacultyFilter'?'Tất cả phòng ban':'Chọn phòng ban';
    el.innerHTML=`<option value="">${placeholder}</option>`+names.map(n=>`<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
    if(old&&names.includes(old))el.value=old;
  }
  fillMajorOptions('#major',$('#faculty')?.value||'');
  fillMajorOptions('#newStudentMajor',$('#newStudentFaculty')?.value||'');
}
function fillMajorOptions(selector,faculty){
  const el=$(selector); if(!el)return; const old=el.value;
  const found=FACULTY_CATALOG.find(x=>x[0]===faculty); const majors=found?found[1]:[];
  el.innerHTML='<option value="">Chọn chức vụ</option>'+majors.map(n=>`<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
  if(old&&majors.includes(old))el.value=old;
}

async function loadStudents(){
  const actor=state.authUser,epoch=state.presentationEpoch;
  try{
    const students=await api('/api/v1/students');
    if(actor!==state.authUser||epoch!==state.presentationEpoch||!appPresentationActive())return;
    state.students=students;fillFacultyOptions();refreshEnrollSelect();renderStudents();updateDashboardStats();
  }catch(e){if(actor===state.authUser&&epoch===state.presentationEpoch&&appPresentationActive())toast(e.message,true);}
}
function updateDashboardStats(){
  const total=state.students.length, enrolled=state.students.filter(x=>Number(x.enrolled)>0).length;
  if($('#v20Students'))$('#v20Students').textContent=total;
  if($('#v20FaceId'))$('#v20FaceId').textContent=enrolled;
  if($('#v20FaceIdMeta'))$('#v20FaceIdMeta').textContent=total?`${Math.round(enrolled/total*100)}%`:'0%';
  if($('#v20FaceIdBar'))$('#v20FaceIdBar').style.width=(total?Math.round(enrolled/total*100):0)+'%';
  const verified=state.events.filter(x=>String(x.status||'').toUpperCase()==='RECOGNIZED'&&!!x.anti_spoof_passed).length;
  if($('#v20Checkins'))$('#v20Checkins').textContent=verified;
  if($('#v20CheckinsMeta'))$('#v20CheckinsMeta').textContent=`${verified} lượt đã xác minh`;
  if($('#v20Classes'))$('#v20Classes').textContent='—';
  if($('#v20ClassesMeta'))$('#v20ClassesMeta').textContent='Module camera tĩnh';
  if($('#v22PulseClass'))$('#v22PulseClass').textContent='Module đăng ký & nhận diện camera tĩnh';
  if($('#v22PulseCourse'))$('#v22PulseCourse').textContent='Chạy local · không cần Internet';
  if($('#v22PulseChecked'))$('#v22PulseChecked').textContent=String(verified);
}
function setV6Dot(sel,tone){const el=$(sel);if(!el)return;el.className=`v6-health-dot ${tone||''}`.trim();}
function renderProfessionalSummary(d){
  if(!d)return;state.dashboardSummary=d;
  const st=d.students||{},today=d.today||{},cam=d.camera||{},db=d.database||{},store=d.storage||{};
  const online=!!cam.opened&&String(cam.state||'').toLowerCase()==='online';
  const quality=String(cam.camera_quality||'UNKNOWN').toUpperCase();
  if($('#v6CameraHealth'))$('#v6CameraHealth').textContent=online?(quality==='POOR'?'Online · cần chỉnh':'Online · '+quality):String(cam.state||'Offline').toUpperCase();
  if($('#v6CameraMeta'))$('#v6CameraMeta').textContent=`${cam.actual_width||0}×${cam.actual_height||0} · ${Math.round(Number(cam.capture_fps||0))} FPS`;
  setV6Dot('#v6CameraDot',online?(quality==='POOR'?'warn':'ok'):'bad');
  if($('#v6FaceHealth'))$('#v6FaceHealth').textContent=`${Math.round(Number(st.faceid_coverage||0))}%`;
  if($('#v6FaceMeta'))$('#v6FaceMeta').textContent=`${st.faceid||0} / ${st.total||0} nhân viên`;
  setV6Dot('#v6FaceDot',Number(st.total||0)===0?'warn':Number(st.faceid_coverage||0)>=90?'ok':Number(st.faceid_coverage||0)>=60?'warn':'bad');
  if($('#v6DbHealth'))$('#v6DbHealth').textContent=String(db.mode||'DB').toUpperCase();
  if($('#v6DbMeta'))$('#v6DbMeta').textContent=db.mode==='postgres'?`${db.host||'local'}:${db.port||''}`:'Local maintenance';
  setV6Dot('#v6DbDot',db.mode?'ok':'bad');
  if($('#v6StorageHealth'))$('#v6StorageHealth').textContent=formatBytes(store.free_bytes||0);
  if($('#v6StorageMeta'))$('#v6StorageMeta').textContent=`${store.backup_count||0} backup · DB ${formatBytes(store.db_size||0)}`;
  setV6Dot('#v6StorageDot',Number(store.free_bytes||0)>1024*1024*1024?'ok':'warn');
  const risks=Number(today.spoof_blocked||0)+Number((d.operations||{}).open_incidents||0);
  if($('#v6RiskHealth'))$('#v6RiskHealth').textContent=`${risks} cảnh báo`;
  if($('#v6RiskMeta'))$('#v6RiskMeta').textContent=`Khách ${today.visitor_sessions??today.unknown??0} · Bị chặn ${today.spoof_blocked||0}`;
  setV6Dot('#v6RiskDot',Number(today.spoof_blocked||0)>0?'bad':risks>0?'warn':'ok');
  if($('#v20Students'))$('#v20Students').textContent=st.total||0;
  if($('#v20FaceId'))$('#v20FaceId').textContent=st.faceid||0;
  if($('#v20FaceIdMeta'))$('#v20FaceIdMeta').textContent=`${Math.round(Number(st.faceid_coverage||0))}%`;
  if($('#v20FaceIdBar'))$('#v20FaceIdBar').style.width=`${Math.min(100,Number(st.faceid_coverage||0))}%`;
  if($('#v20Checkins'))$('#v20Checkins').textContent=today.recognized_events||0;
  if($('#v20CheckinsMeta'))$('#v20CheckinsMeta').textContent=`${today.unique_students||0} nhân viên khác nhau`;
  if($('#v20Classes'))$('#v20Classes').textContent=today.attendance_sessions||0;
  if($('#v20ClassesMeta'))$('#v20ClassesMeta').textContent=`${today.active_sessions||0} đang diễn ra`;
  if($('#v22PulseChecked'))$('#v22PulseChecked').textContent=String(today.recognized_events||0);
  const ops=d.operations||{},perf=d.performance||{};renderV13Performance(perf,cam);renderV13Events(d.latest||[]);
  const pending=Number(ops.pending_exceptions||0)+Number(today.spoof_blocked||0)+Number(ops.open_incidents||0);
  if($('#v13AlertCount'))$('#v13AlertCount').textContent=String(pending);
  if($('#v131PendingCount'))$('#v131PendingCount').textContent=String(pending);
  if($('#v131TodayCheckins'))$('#v131TodayCheckins').textContent=String(today.recognized_events||0);
  if($('#v131FaceCoverage'))$('#v131FaceCoverage').textContent=`${Math.round(Number(st.faceid_coverage||0))}%`;
  if($('#v5DashPresentToday'))$('#v5DashPresentToday').textContent=String(today.unique_students||0);
  if($('#v5DashVisitorsToday'))$('#v5DashVisitorsToday').textContent=String(today.visitor_sessions??today.unknown??0);
  if($('#v5DashVisitorsNow'))$('#v5DashVisitorsNow').textContent=String(today.active_visitors||0);
  if($('#v5DashOpenIncidents'))$('#v5DashOpenIncidents').textContent=String(ops.open_incidents||0);
  if($('#v5DashCameraOnline'))$('#v5DashCameraOnline').textContent=`${Number(ops.online_cameras||0)} / ${Number(ops.registered_cameras||0)}`;
  const camOnline=!!cam.opened&&String(cam.state||'').toLowerCase()==='online';
  if($('#v131CameraState'))$('#v131CameraState').textContent=camOnline?'ONLINE':'OFFLINE';
  if($('#v131CameraLabel'))$('#v131CameraLabel').textContent=cam.source_label||'Camera hiện tại';
  const free=Number(store.free_bytes||0);setV13Chip('#v13TopStorage',free?formatBytes(free):'—',free&&free<1024*1024*1024?'warn':'');
  if($('#v13DashboardCameraName'))$('#v13DashboardCameraName').textContent=cam.source_label||'Camera hiện tại';
}
async function loadProfessionalSummary(silent=true){
  if(window.BTMHManagement){window.BTMHManagement.start();return null;}
  try{const d=await api('/api/v1/dashboard/summary');renderProfessionalSummary(d);return d;}catch(e){if(!silent)toast(e.message,true);return null;}
}
function studentFiltered(){
  const q=($('#studentSearch')?.value||'').trim().toLowerCase(); const faculty=$('#studentFacultyFilter')?.value||''; const cls=$('#studentClassFilter')?.value||''; const face=$('#studentFaceFilter')?.value||'';
  return state.students.filter(s=>{
    const hay=[s.student_code,s.full_name,s.email,s.phone,s.faculty,s.class_name].join(' ').toLowerCase();
    if(q&&!hay.includes(q))return false; if(faculty&&s.faculty!==faculty)return false; if(cls&&s.class_name!==cls)return false;
    if(face==='YES'&&!s.enrolled)return false; if(face==='NO'&&s.enrolled)return false;
    if(state.studentScope==='NO_FACEID'&&s.enrolled)return false;
    if(state.studentScope==='IN_CLASS'&&!s.class_name)return false;
    if(['RESERVED','TRANSFERRED','GRADUATING','ATTENTION'].includes(state.studentScope))return false;
    return true;
  });
}
function populateStudentFilters(){
  const cls=$('#studentClassFilter'); if(cls){const old=cls.value;const vals=[...new Set(state.students.map(s=>s.class_name).filter(Boolean))].sort();cls.innerHTML='<option value="">Tất cả bộ phận</option>'+vals.map(v=>`<option>${escapeHtml(v)}</option>`).join('');if(vals.includes(old))cls.value=old;}
}
function faceValidationMeta(s={}){
  if(!s.enrolled)return {label:'Chưa đăng ký',tone:'warn',verified:false};
  const st=String(s.face_validation_status||'PENDING_STORE_VALIDATION').toUpperCase();
  if(st==='VERIFIED')return {label:'Đã xác minh camera',tone:'ok',verified:true};
  return {label:'Chờ xác minh camera',tone:'warn',verified:false};
}
function renderStudents(){
  const body=$('#studentsBody'); if(!body)return; populateStudentFilters(); const all=studentFiltered();
  const pages=Math.max(1,Math.ceil(all.length/state.studentPageSize));state.studentPage=Math.max(1,Math.min(state.studentPage,pages)); const start=(state.studentPage-1)*state.studentPageSize;const list=all.slice(start,start+state.studentPageSize);
  if($('#studentListCount'))$('#studentListCount').textContent=`Tổng cộng: ${all.length}`;
  if($('#studentPageInfo'))$('#studentPageInfo').textContent=`${state.studentPage} / ${pages}`;
  if($('#studentPrevPage'))$('#studentPrevPage').disabled=state.studentPage<=1;if($('#studentNextPage'))$('#studentNextPage').disabled=state.studentPage>=pages;
  body.innerHTML=list.length?list.map(s=>{
    const portrait=s.has_photo?`<img class="student-mini-photo" src="/api/v1/students/${Number(s.id)}/photo" alt="">`:`<div class="student-mini-avatar">${initials(s.full_name)}</div>`;
    const poses=Number(s.face_pose_count||0),seen=s.last_seen_at?formatDate(s.last_seen_at):'Chưa nhận diện',fv=faceValidationMeta(s);
    return `<tr>
      <td class="student-expand-col"><button class="student-row-plus" type="button" onclick="event.stopPropagation();openStudentProfile(${s.id})">+</button></td>
      <td onclick="openStudentProfile(${s.id})"><div class="student-cell">${portrait}<div><b>${escapeHtml(s.full_name)}</b><small>${escapeHtml(s.student_code||'')}</small><div class="student-operational-meta"><span class="student-op-chip ${s.enrolled?'ok':'warn'}">${s.enrolled?`FaceID ${poses} góc`:'Chưa FaceID'}</span><span class="student-op-chip">${Number(s.recognition_count||0)} lượt</span></div></div></div></td>
      <td><b>${escapeHtml(s.email||'—')}</b><small>${escapeHtml(s.phone||'')}</small><span class="student-last-seen">Gần nhất: ${escapeHtml(seen)}</span></td>
      <td><span class="student-op-chip ${fv.tone}">${s.enrolled?`${poses} góc · ${fv.label}`:fv.label}</span></td>
      <td><span class="student-status-chip active">Đang hoạt động</span></td>
      <td><b>${escapeHtml(s.class_name||'—')}</b><small>${escapeHtml(s.faculty||'')}</small></td>
      <td class="student-actions">${hasUiPermission('employee.enroll')?`<button class="btn small ghost" onclick="event.stopPropagation();openStudentFaceId(${s.id})">FaceID</button>`:''}${hasUiPermission('employee.manage')?`<button class="btn small danger" onclick="event.stopPropagation();deleteStudentFromList(${s.id})">Xóa</button>`:''}</td>
    </tr>`}).join(''):'<tr><td colspan="7" class="empty-card">Không có nhân viên phù hợp.</td></tr>';
}
function showStudentList(){
  stopQREnrollmentPanels();
  state.studentDetailId=null;state.studentProfileTab='detail';
  $('#studentListView')?.classList.remove('hidden'); $('#studentDetailView')?.classList.add('hidden');
}
function studentDetailCard(s){
  const photo=s.has_photo?`<img src="/api/v1/students/${Number(s.id)}/photo?v=${Date.now()}" alt="Ảnh hồ sơ ${escapeHtml(s.full_name)}" style="width:132px;height:156px;object-fit:cover;border-radius:18px;border:1px solid rgba(35,61,89,.15);background:#f4f7fb">`:`<div style="width:132px;height:156px;border-radius:18px;display:flex;align-items:center;justify-content:center;background:#eef3f8;font-size:34px;font-weight:800;color:#607086">${initials(s.full_name)}</div>`;
  const last=s.last_seen_at?formatDate(s.last_seen_at):'Chưa có';
  return `<section class="mona-detail-card"><h3>Thông tin nhân viên</h3><div style="display:grid;grid-template-columns:148px minmax(0,1fr);gap:18px;align-items:start"><div>${photo}<small style="display:block;margin-top:8px;color:#7b8797">${s.has_photo?'Ảnh hồ sơ lưu riêng ngoài database':'Ảnh sẽ được tạo sau khi đăng ký FaceID'}</small></div><div><div class="student-v12-info-grid"><div class="mona-info-row"><span>Mã nhân viên</span><b>${escapeHtml(s.student_code)}</b></div><div class="mona-info-row"><span>Họ tên</span><b>${escapeHtml(s.full_name)}</b></div><div class="mona-info-row"><span>Bộ phận</span><b>${escapeHtml(s.class_name||'—')}</b></div><div class="mona-info-row"><span>Phòng ban</span><b>${escapeHtml(s.faculty||'—')}</b></div><div class="mona-info-row"><span>Email</span><b>${escapeHtml(s.email||'—')}</b></div><div class="mona-info-row"><span>FaceID</span><b>${s.enrolled?`Đã đăng ký · ${Number(s.face_pose_count||0)} góc · ${faceValidationMeta(s).label}`:'Chưa đăng ký'}</b></div><div class="mona-info-row"><span>Lần nhận diện</span><b>${Number(s.recognition_count||0)}</b></div><div class="mona-info-row"><span>Nhận diện gần nhất</span><b>${escapeHtml(last)}</b></div></div><div class="student-v12-actions">${hasUiPermission('employee.enroll')?`<button class="btn primary" onclick="openStudentFaceId(${s.id})">${s.enrolled?'Đăng ký lại FaceID':'Đăng ký FaceID'}</button>`:''}<button class="btn ghost" type="button" onclick="setStudentProfileTab('history')">Xem lịch sử</button></div></div></div></section>`;
}
function studentFaceIdCard(s){
  const poses=Number(s.face_pose_count||0),quality=!s.enrolled?'CHƯA CÓ':poses>=8?'TỐT':poses>=5?'KHÁ':'NÊN QUÉT LẠI',fv=faceValidationMeta(s);
  return `<section class="mona-detail-card student-faceid-summary"><div class="student-tab-title"><div><span>FACEID</span><h3>Hồ sơ khuôn mặt</h3></div><span class="student-live-chip ${fv.tone}">${escapeHtml(fv.label)}</span></div><p>${s.enrolled?(fv.verified?'Bộ FaceID đa góc đã được xác minh trên camera cửa hàng và sẵn sàng dùng cho nhận diện thực tế.':'Bộ FaceID đa góc đã được lưu. Cần xác minh một lần trên camera cửa hàng để hoàn tất quy trình.'):'Nhân viên chưa có FaceID. Cần đăng ký trước để camera cửa hàng có thể xác định đúng nhân viên.'}</p><div class="student-face-quality"><div><span>Số góc mẫu</span><b>${poses}</b></div><div><span>Chất lượng</span><b>${quality}</b></div><div><span>Xác minh camera</span><b>${escapeHtml(fv.label)}</b></div><div><span>Lần cập nhật</span><b style="font-size:10px">${escapeHtml(s.face_updated_at?formatDate(s.face_updated_at):'—')}</b></div></div>${hasUiPermission('employee.enroll')?`<button class="btn primary" onclick="openStudentFaceId(${s.id})">${s.enrolled?'Quét lại / xác minh FaceID':'Đăng ký FaceID ngay'}</button>`:''}</section>`;
}

async function loadStudentTimeline(s){
  const host=$('#studentProfileContent');if(!host)return;
  host.innerHTML='<section class="mona-detail-card"><h3>Lịch sử nhân viên</h3><div class="empty-card">Đang tải lịch sử...</div></section>';
  try{
    const d=await api(`/api/v1/students/${Number(s.id)}/timeline?limit=80`),rows=d.items||[];
    host.innerHTML=`<section class="mona-detail-card"><div class="student-tab-title"><div><span>TIMELINE</span><h3>Lịch sử nhận diện & hoạt động</h3></div><span class="student-live-chip">${rows.length} sự kiện</span></div><div class="student-timeline">${rows.length?rows.map(x=>`<div class="student-timeline-row"><time>${escapeHtml(formatDate(x.event_at))}</time><span>${escapeHtml(x.kind||'SYSTEM')}</span><b>${escapeHtml(x.label||x.status||'—')}</b><em>${x.confidence!==undefined&&x.confidence!==null?pct(x.confidence)+'%':'—'}</em></div>`).join(''):'<div class="empty-card">Chưa có lịch sử cho nhân viên này.</div>'}</div></section>`;
  }catch(e){host.innerHTML=`<section class="mona-detail-card"><h3>Lịch sử nhân viên</h3><div class="empty-card">${escapeHtml(e.message)}</div></section>`;}
}
function setStudentProfileTab(tab='detail'){
  stopQREnrollmentPanels();
  const s=state.students.find(x=>Number(x.id)===Number(state.studentDetailId));if(!s)return;
  state.studentProfileTab=tab;
  $$('#studentProfileTabs [data-student-tab]').forEach(b=>b.classList.toggle('active',b.dataset.studentTab===tab));
  const host=$('#studentProfileContent');if(!host)return;
  if(tab==='detail')host.innerHTML=studentDetailCard(s);
  else if(tab==='faceid')host.innerHTML=studentFaceIdCard(s);
  else if(tab==='history'){loadStudentTimeline(s);}
  else host.innerHTML=`<section class="mona-detail-card"><h3>${escapeHtml(({academic:'Thông tin công việc',classes:'Khu vực làm việc',attendance:'Hiện diện',recordings:'Clip tương tác',notes:'Ghi chú'}[tab]||'Thông tin'))}</h3><div class="empty-card">Mục này sẵn sàng để tích hợp dữ liệu nhân sự bổ sung; hệ thống không tạo dữ liệu giả.</div></section>`;
  if(['detail','faceid'].includes(tab)&&canManageEnrollment()){
    const panel=document.createElement('div');panel.id='qrEmployeeReviewPanel';host.appendChild(panel);mountQREnrollmentPanel(panel,s);
  }
}
window.setStudentProfileTab=setStudentProfileTab;
window.openStudentProfile=(id)=>{
  const s=state.students.find(x=>Number(x.id)===Number(id));if(!s)return;
  state.studentDetailId=Number(id);state.studentProfileTab='detail';
  $('#studentListView')?.classList.add('hidden'); $('#studentDetailView')?.classList.remove('hidden');
  if($('#studentDetailAvatar'))$('#studentDetailAvatar').textContent=initials(s.full_name);
  if($('#studentDetailName'))$('#studentDetailName').textContent=s.full_name;
  if($('#studentDetailMeta'))$('#studentDetailMeta').textContent=`${s.student_code}${s.class_name?' · '+s.class_name:''}`;
  if($('#studentDetailStatus')){const fv=faceValidationMeta(s);$('#studentDetailStatus').innerHTML=s.enrolled?`<span class="student-status-chip ${fv.verified?'active':''}">${escapeHtml(fv.label)}</span>`:'<span class="student-status-chip">Chưa có FaceID</span>';}
  setStudentProfileTab('detail');
};
window.openStudentFaceId=(id)=>{state.enrollStudentId=Number(id);navigate('register');setTimeout(()=>{const sel=$('#enrollStudentSelect');if(sel){sel.value=String(id);sel.dispatchEvent(new Event('change'));}},100)};
window.deleteStudentFromList=async(id)=>{const s=state.students.find(x=>Number(x.id)===Number(id));if(!confirm(`Xóa hồ sơ ${s?.full_name||'nhân viên'}?`))return;try{await api(`/api/v1/students/${id}`,{method:'DELETE'});toast('Đã xóa hồ sơ.');await loadStudents()}catch(e){toast(e.message,true)}};

function closeStudentCreate(){ $('#studentCreateModal')?.classList.add('hidden'); $('#studentCreateForm')?.reset(); }
async function createStudentFromModal(e){
  e.preventDefault();
  try{
    const faculty=$('#newStudentFaculty')?.value||'';
    await api('/api/v1/students',{method:'POST',body:JSON.stringify({student_code:$('#newStudentCode')?.value.trim(),full_name:$('#newStudentName')?.value.trim(),class_name:$('#newStudentClass')?.value.trim()||'',faculty,email:$('#newStudentEmail')?.value.trim()||'',phone:$('#newStudentPhone')?.value.trim()||'',consent:false})});
    closeStudentCreate();toast('Đã thêm nhân viên.');await loadStudents();
  }catch(e2){toast(e2.message,true)}
}

function refreshEnrollSelect(){
  const sel=$('#enrollStudentSelect'); if(!sel)return; const old=String(state.enrollStudentId||sel.value||'');
  sel.innerHTML='<option value="">— Chọn nhân viên —</option>'+state.students.map(s=>`<option value="${s.id}">${escapeHtml(s.student_code)} — ${escapeHtml(s.full_name)}${s.enrolled?' ✓':''}</option>`).join('');
  if(old&&state.students.some(s=>String(s.id)===old))sel.value=old;
  if($('#startExistingFaceBtn'))$('#startExistingFaceBtn').disabled=!sel.value||!canManageEnrollment();
  syncQREnrollmentPanel();
}
function canManageEnrollment(){return ['SUPER_ADMIN','ADMIN'].includes(String(state.authUser?.role||'').toUpperCase())&&hasUiPermission('employee.enroll');}
function stopQREnrollmentPanels(){for(const view of state.qrAdminViews||[])view?.stop?.();state.qrAdminViews=[];}
function mountQREnrollmentPanel(host,student){
  if(!host||!window.BTMHQREnrollmentAdmin||!canManageEnrollment()||!appPresentationActive())return;
  const view=window.BTMHQREnrollmentAdmin.mount(host,{student,api,getUser:()=>state.authUser,getPermission:hasUiPermission,toast,
    getPreview:async(url,{signal}={})=>(await api(url,{signal,rawResponse:true})).blob()});
  if(view)state.qrAdminViews.push(view);
}
function syncQREnrollmentPanel(){
  if(state.activePage!=='register')return;
  stopQREnrollmentPanels();const host=$('#qrEnrollmentPanel');if(host)host.replaceChildren();
  mountQREnrollmentPanel(host,selectedEnrollStudent());
}
async function loadEnrollmentStores(){
  const select=$('#enrollmentStoreSelect');if(!select||!canManageEnrollment())return;
  const actor=state.authUser,epoch=state.presentationEpoch,old=select.value;
  try{
    const data=await api('/api/v1/stores');
    if(actor!==state.authUser||epoch!==state.presentationEpoch||!appPresentationActive())return;
    select.innerHTML='<option value="">— Chọn cửa hàng —</option>'+(data.items||[]).filter(x=>x.status==='ACTIVE').map(x=>`<option value="${Number(x.id)}">${escapeHtml(x.store_name)}</option>`).join('');
    if([...select.options].some(x=>x.value===old))select.value=old;
  }catch(e){if(actor===state.authUser&&epoch===state.presentationEpoch)toast(e.message,true);}
}
function selectedEnrollStudent(){
  if(state.enrollStudentProfile&&Number(state.enrollStudentProfile.id)===Number(state.enrollStudentId))return state.enrollStudentProfile;
  return state.students.find(s=>Number(s.id)===Number(state.enrollStudentId))||null;
}
function setEnrollPhase(face){
  const profile=$('#registrationProfilePhase'),scan=$('#registrationFacePhase');
  profile?.classList.toggle('active',!face);scan?.classList.toggle('active',face);
  if(face){requestAnimationFrame(()=>scan?.scrollIntoView({behavior:'smooth',block:'start'}));}
  else{clearInterval(state.enrollTimer);state.enrollTimer=null;state.enrollRequestController?.abort();window.BTMHV4?.stopEnrollmentBrowserCamera?.();pauseCameraPreview('enroll');syncQREnrollmentPanel();}
}
function updateEnrollPerson(){const s=selectedEnrollStudent();if(!s)return;if($('#enrollPersonAvatar'))$('#enrollPersonAvatar').textContent=initials(s.full_name);if($('#enrollPersonName'))$('#enrollPersonName').textContent=s.full_name;if($('#enrollPersonCode'))$('#enrollPersonCode').textContent=`${s.student_code}${s.class_name?' · '+s.class_name:''}`;}
const ENROLL_POSE_ORDER=['center','left','right','up','down'];
const ENROLL_POSE_LABEL={center:'Chính diện',left:'Nghiêng trái',right:'Nghiêng phải',up:'Ngẩng nhẹ',down:'Cúi nhẹ'};
function layoutScanTicks(){
  const host=$('#scanTicks'),scanner=$('#faceidScanner');if(!host||!scanner)return;
  const count=host.children.length||40;
  [...host.children].forEach((t,i)=>{
    const a=(-90+i*(360/count))*Math.PI/180;
    const x=50+49.2*Math.cos(a),y=50+49.2*Math.sin(a);
    t.style.left=`${x}%`;t.style.top=`${y}%`;
    t.style.transform=`translate(-50%,-50%) rotate(${a*180/Math.PI+90}deg)`;
  });
}
function buildScanTicks(){
  const host=$('#scanTicks');if(!host)return;
  if(!host.children.length){
    const count=40;
    for(let i=0;i<count;i++){
      const t=document.createElement('i');
      if(i%5===0)t.classList.add('head');
      t.dataset.scanIndex=String(i);host.appendChild(t);
    }
  }
  requestAnimationFrame(layoutScanTicks);
  if(!buildScanTicks._bound){window.addEventListener('resize',()=>requestAnimationFrame(layoutScanTicks));buildScanTicks._bound=true;}
}

const FACEID_GUIDE_TEXT={
  center:'Nhìn thẳng vào camera',
  left:'Quay đầu nhẹ sang trái',
  right:'Quay đầu nhẹ sang phải',
  down:'Hơi cúi đầu xuống',
  up:'Hơi ngẩng đầu lên'
};
const FACEID_GUIDE_ANGLE={center:-90,left:180,right:0,down:90,up:-90};
function updateFaceIdGuideOrb(guide='center',ready=false){
  const orb=$('#faceidGuideOrb');if(!orb)return;
  if(ready){orb.classList.add('done');return;}
  orb.classList.remove('done');
  const a=(FACEID_GUIDE_ANGLE[guide]??-90)*Math.PI/180;
  orb.style.left=`${50+51*Math.cos(a)}%`;orb.style.top=`${50+51*Math.sin(a)}%`;
  orb.dataset.guide=guide;
}
function faceIdGuideText(guide='center'){return FACEID_GUIDE_TEXT[guide]||'Xoay đầu chậm theo điểm sáng';}
function faceIdMissingHint(r){
  const missing=Array.isArray(r?.missing_requirements)?r.missing_requirements:[];
  const pp=Number(r?.pass_progress||0);
  if(pp<0.82||!missing.length)return '';
  if(missing.includes('vertical'))return 'Còn thiếu góc dọc: ngẩng đầu nhẹ rồi cúi nhẹ một lần, giữ mỗi hướng khoảng nửa giây.';
  if(missing.includes('horizontal'))return 'Còn thiếu góc ngang: quay chậm sang trái rồi sang phải, không cần quay quá mạnh.';
  if(missing.includes('center'))return 'Còn thiếu mẫu chính diện: nhìn thẳng vào camera trong khoảng một giây.';
  return '';
}

function buildDepthDots(){
  const host=$('#v24DepthDots');if(!host||host.children.length)return;
  // A restrained depth-map style cloud. It is visual feedback only; actual biometric
  // landmarks are drawn on faceidBiometricOverlay from YuNet metadata.
  let idx=0;
  for(let row=0;row<13;row++){
    for(let col=0;col<11;col++){
      const nx=(col-5)/5,ny=(row-6)/6;
      const ellipse=(nx*nx)/0.95+(ny*ny)/1.08;
      if(ellipse>1)continue;
      const dot=document.createElement('i');
      dot.className='v24-depth-dot';
      const wobble=((row*17+col*11)%7-3)*0.22;
      dot.style.left=`${50+nx*42+wobble}%`;
      dot.style.top=`${50+ny*45-wobble*.45}%`;
      dot.dataset.phase=String((idx*37)%101);
      host.appendChild(dot);idx++;
    }
  }
}
function updateDepthDots(r,yaw=0,pitch=0){
  const host=$('#v24DepthDots');if(!host)return;buildDepthDots();
  const progress=Math.max(0,Math.min(1,Number(r?.progress||0)));
  const locked=!!r?.ok;
  host.style.opacity=locked?'.82':'.34';
  host.style.setProperty('--dot-shift-x',`${yaw*3.5}px`);
  host.style.setProperty('--dot-shift-y',`${pitch*3.5}px`);
  $$('#v24DepthDots .v24-depth-dot').forEach((dot,i)=>{
    const phase=Number(dot.dataset.phase||0)/100;
    const active=locked && (phase<=Math.max(.08,progress) || ((i+Math.round(progress*17))%19===0));
    dot.classList.toggle('hot',active);
    dot.style.opacity=String(locked?(.38+((i*13)%7)*.07):.18);
  });
}

function ensurePassToast(){
  const wrap=$('.faceid-pro-camera-wrap');if(!wrap)return null;
  let el=$('#faceidPassToast');
  if(!el){el=document.createElement('div');el.id='faceidPassToast';el.className='faceid-pass-toast';wrap.appendChild(el);}
  return el;
}
function announcePassSwitch(text='Vòng quét 1 hoàn tất · Chuẩn bị vòng 2'){
  const scanner=$('#faceidScanner');const toastEl=ensurePassToast();
  scanner?.classList.add('pass-switch');
  if(toastEl){toastEl.textContent=text;toastEl.classList.add('show');}
  clearTimeout(announcePassSwitch._t);announcePassSwitch._t=setTimeout(()=>{scanner?.classList.remove('pass-switch');toastEl?.classList.remove('show');},760);
}
function updateFaceIdProgress(frac=0, guide='center', ready=false, scanPass=1, passProgress=0, passTransition=false){
  const overall=Math.max(0,Math.min(1,Number(frac)||0));
  const pass=Math.max(1,Math.min(2,Number(scanPass)||1));
  const local=ready?1:Math.max(0,Math.min(1,Number(passProgress)||0));
  const localPct=Math.round(local*100);
  // The large percentage describes the CURRENT scan pass.  Previously pass 1 at
  // 92% was displayed as 46% because it used two-pass overall progress, which made
  // a healthy scan look broken.
  if($('#faceidPercent'))$('#faceidPercent').textContent=(ready?100:localPct)+'%';
  if($('#faceidSampleCount'))$('#faceidSampleCount').textContent=ready?'XONG':`VÒNG ${pass}`;
  if($('#scanSummaryFill'))$('#scanSummaryFill').style.width=(ready?100:localPct)+'%';
  const scanner=$('#faceidScanner');
  if(scanner){
    scanner.style.setProperty('--scan-angle',`${localPct*3.6}deg`);
    scanner.style.setProperty('--pass-angle',`${localPct*3.6}deg`);
    scanner.style.setProperty('--scan-progress',String(local));
    scanner.classList.toggle('scanning',!ready&&localPct>0&&localPct<100);
    scanner.classList.toggle('pass-complete',ready||localPct>=100);
    scanner.dataset.guide=guide||'center';
  }
  updateFaceIdGuideOrb(guide,ready);
  if($('#scanPassLabel'))$('#scanPassLabel').textContent=ready?'Hoàn tất 2/2':`Vòng quét ${pass}/2`;
  if($('#scanPassSub'))$('#scanPassSub').textContent=ready?'FaceID đã đủ dữ liệu':`Xoay đầu chậm theo vòng tròn · ${localPct}%`;
  if($('#scanPassPill'))$('#scanPassPill').textContent=ready?'ĐÃ HOÀN TẤT 2 VÒNG':`VÒNG QUÉT ${pass}/2`;
  $('#v23PassOne')?.classList.toggle('active',pass===1&&!ready);
  $('#v23PassOne')?.classList.toggle('done',pass===2||ready);
  $('#v23PassTwo')?.classList.toggle('active',pass===2&&!ready);
  $('#v23PassTwo')?.classList.toggle('done',ready);
  if($('#v23PassOneState'))$('#v23PassOneState').textContent=pass===1&&!ready?'Đang quét':'Hoàn tất';
  if($('#v23PassTwoState'))$('#v23PassTwoState').textContent=ready?'Hoàn tất':pass===2?'Đang quét':'Chờ';
  if(passTransition)announcePassSwitch();
  // Illuminate the radial tick marks using the progress of the current pass only.
  const ticks=$$('#scanTicks i');if(ticks.length){
    const n=Math.round(ticks.length*local);
    ticks.forEach((t,i)=>{t.classList.toggle('done',i<n);t.classList.toggle('current',!ready&&i===Math.min(ticks.length-1,n));});
  }
}

function renderEnrollPoseProgress(counts={}, guide='center', goals={}, coverage=[]){
  const map={center:'poseCenterCount',left:'poseLeftCount',right:'poseRightCount',up:'poseUpCount',down:'poseDownCount'};
  const covered=new Set(Array.isArray(coverage)?coverage:[]);
  Object.entries(map).forEach(([pose,id])=>{
    const el=$(`#${id}`);if(!el)return;
    const n=Number(counts[pose]||0);
    el.textContent=n>0?String(n):'—';
  });
  $$('.pose-chip').forEach(chip=>{
    const pose=chip.dataset.pose,n=Number(counts[pose]||0);
    chip.classList.toggle('active',pose===guide);
    chip.classList.toggle('done',covered.has(pose)||n>=2);
  });
  const scanner=$('#faceidScanner');if(scanner)scanner.dataset.guide=guide||'center';
}

function enrollCoverPoint(nx,ny,frameW,frameH,canvasW,canvasH,mirror=true){
  const scale=Math.max(canvasW/Math.max(1,frameW),canvasH/Math.max(1,frameH));
  const rw=frameW*scale,rh=frameH*scale,ox=(canvasW-rw)/2,oy=(canvasH-rh)/2;
  let x=ox+nx*frameW*scale,y=oy+ny*frameH*scale;
  if(mirror)x=canvasW-x;
  return [x,y];
}
function clearEnrollBiometricOverlay(){
  const canvas=$('#faceidBiometricOverlay');if(!canvas)return;
  const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
}
function drawEnrollBiometricOverlay(r){
  const canvas=$('#faceidBiometricOverlay'),wrap=canvas?.parentElement;if(!canvas||!wrap)return;
  const rect=wrap.getBoundingClientRect(),dpr=Math.min(2,window.devicePixelRatio||1);
  const cw=Math.max(1,Math.round(rect.width)),ch=Math.max(1,Math.round(rect.height));
  if(canvas.width!==Math.round(cw*dpr)||canvas.height!==Math.round(ch*dpr)){canvas.width=Math.round(cw*dpr);canvas.height=Math.round(ch*dpr);canvas.style.width=cw+'px';canvas.style.height=ch+'px';}
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,cw,ch);
  const fw=Number(r?.frame_width||0),fh=Number(r?.frame_height||0),pts=r?.landmarks_norm||[];
  if(!fw||!fh||pts.length<5)return;
  const scanner=$('#faceidScanner'),cursor=$('#v24OrbitCursor');
  const yaw=Math.max(-1,Math.min(1,Number(r?.yaw||0)/.34)),pitch=Math.max(-1,Math.min(1,Number(r?.pitch||0)/.24));
  updateDepthDots(r,yaw,pitch);
  if(scanner){scanner.style.setProperty('--head-x',String(yaw));scanner.style.setProperty('--head-y',String(pitch));}
  if(cursor){cursor.style.left=`${50+yaw*27}%`;cursor.style.top=`${50+pitch*28}%`;}
  const mapped=pts.map(p=>enrollCoverPoint(Number(p.x),Number(p.y),fw,fh,cw,ch,true));
  // Five real landmarks from YuNet. Keep them subtle and biometric-looking.
  ctx.lineWidth=1;ctx.strokeStyle='rgba(111,255,224,.26)';ctx.fillStyle='rgba(115,255,225,.90)';
  const links=[[0,1],[0,2],[1,2],[2,3],[2,4],[3,4]];
  links.forEach(([a,b])=>{ctx.beginPath();ctx.moveTo(...mapped[a]);ctx.lineTo(...mapped[b]);ctx.stroke();});
  mapped.forEach(([x,y],i)=>{ctx.beginPath();ctx.arc(x,y,i===2?3.2:2.4,0,Math.PI*2);ctx.fill();ctx.beginPath();ctx.arc(x,y,i===2?7:5.4,0,Math.PI*2);ctx.stroke();});
  // Small corner brackets around the actual detected face, not a permanent box.
  const b=r?.face_bbox_norm;if(b){
    const p1=enrollCoverPoint(Number(b.x),Number(b.y),fw,fh,cw,ch,true);
    const p2=enrollCoverPoint(Number(b.x)+Number(b.w),Number(b.y)+Number(b.h),fw,fh,cw,ch,true);
    const x1=Math.min(p1[0],p2[0]),x2=Math.max(p1[0],p2[0]),y1=Math.min(p1[1],p2[1]),y2=Math.max(p1[1],p2[1]);
    const L=Math.min(20,Math.max(10,(x2-x1)*.12));ctx.strokeStyle='rgba(80,239,204,.48)';ctx.lineWidth=1.25;
    [[x1,y1,1,1],[x2,y1,-1,1],[x1,y2,1,-1],[x2,y2,-1,-1]].forEach(([x,y,sx,sy])=>{ctx.beginPath();ctx.moveTo(x+sx*L,y);ctx.lineTo(x,y);ctx.lineTo(x,y+sy*L);ctx.stroke();});
  }
}
function updateEnrollLock(r){
  const chip=$('#faceidLockChip');if(!chip)return;
  const text=chip.querySelector('span');
  chip.classList.toggle('locked',!!r?.ok);
  $('#faceidScanner')?.classList.toggle('face-locked',!!r?.ok);
  chip.classList.remove('captured');
  if(r?.accepted){if(text)text.textContent='Đã thu mẫu chất lượng';chip.classList.add('captured');setTimeout(()=>chip.classList.remove('captured'),420);}
  else if(r?.ok){if(text)text.textContent='Khuôn mặt đã khóa';}
  else{if(text)text.textContent=r?.face_count===0?'Đang tìm khuôn mặt':'Đang căn chỉnh';}
}
function flashAcceptedSample(){
  const scanner=$('#faceidScanner');if(!scanner)return;scanner.classList.remove('capture-accepted');void scanner.offsetWidth;scanner.classList.add('capture-accepted');setTimeout(()=>scanner.classList.remove('capture-accepted'),420);
}

function resetFaceIdUI(){
  state.enrollFinalizing=false;state.enrollCompleted=false;state.enrollLastResponse=null;state.enrollDuplicatePending=false;state.enrollDuplicateCandidate=null;state.enrollValidationBusy=false;
  buildDepthDots();buildScanTicks();updateFaceIdProgress(0,'center',false,1,0,false);renderEnrollPoseProgress({},'center',{},[]);$('#faceidSuccess')?.classList.remove('show');clearEnrollBiometricOverlay();updateDepthDots({ok:false,progress:0},0,0);
  if($('#faceidTitle'))$('#faceidTitle').textContent='Đưa khuôn mặt vào khung';
  if($('#enrollHint'))$('#enrollHint').textContent='Đưa khuôn mặt vào giữa khung, sau đó di chuyển đầu chậm theo vòng quét.';
  if($('#faceidInstruction'))$('#faceidInstruction').innerHTML='<span class="instruction-icon">◎</span><span>Đưa khuôn mặt vào vùng quét để bắt đầu.</span>';
  const scanner=$('#faceidScanner');if(scanner){scanner.classList.remove('aligning','liveness','capture-accepted','face-locked','pass-switch');scanner.dataset.guide='center';}
  const lock=$('#faceidLockChip');if(lock){lock.className='faceid-lock-chip';const t=lock.querySelector('span');if(t)t.textContent='Đang tìm khuôn mặt';}
  ['#qSharp','#qLight','#qPose','#qScore'].forEach(sel=>{if($(sel))$(sel).textContent='—'});setSignal('#enrollFaceSignal');setSignal('#enrollQualitySignal');setSignal('#enrollLiveSignal');
  if($('#finalizeEnrollBtn')){$('#finalizeEnrollBtn').disabled=true;$('#finalizeEnrollBtn').classList.add('hidden');}
}
async function ensureConsent(student){
  if(student?.biometric_consent_status==='GRANTED')return true;
  if(!confirm('Nhân viên chưa xác nhận đăng ký FaceID. Xác nhận cấp quyền sinh trắc học để tiếp tục?'))return false;
  try{await api(`/api/v1/students/${student.id}/consent`,{method:'PUT',body:JSON.stringify({granted:true})});await loadStudents();return true}catch(e){toast(e.message,true);return false}
}
async function beginFaceIdSetup(profile=null){
  if(state.enrollStarting)return false;
  if(!canManageEnrollment()){toast('Chỉ Chủ sở hữu hoặc Quản trị viên được mở đăng ký FaceID.',true);return false;}
  if(profile?.id){state.enrollStudentId=Number(profile.id);state.enrollStudentProfile=profile;}
  if(!state.enrollStudentId){toast('Hãy chọn nhân viên trước.',true);return false}
  const store=Number($('#enrollmentStoreSelect')?.value||0);if(!store){toast('Chọn cửa hàng đăng ký trước khi mở phiên quét.',true);return false;}
  const actor=state.authUser,student=state.enrollStudentId,epoch=state.presentationEpoch;
  state.enrollStarting=true;
  try{
  // Enter STEP 02 immediately after the profile transaction succeeds. Camera startup
  // happens inside the scan phase so a slow/blocked webcam can never make the UI look
  // as if the employee profile was not saved.
  setEnrollPhase(true);resetFaceIdUI();updateEnrollPerson();
  if($('#faceidTitle'))$('#faceidTitle').textContent='Đang chuẩn bị camera';
  if($('#enrollHint'))$('#enrollHint').textContent='Hồ sơ đã lưu. Đang mở camera để bắt đầu quét FaceID...';
  let s=selectedEnrollStudent();
  if(!await ensureConsent(s)){setEnrollPhase(false);return false}
  if(actor!==state.authUser||student!==state.enrollStudentId||epoch!==state.presentationEpoch||!appPresentationActive())return false;
  s=selectedEnrollStudent();if(s)state.enrollStudentProfile=s;updateEnrollPerson();
  const started=await api('/api/v1/admin/face-enrollment/requests',{method:'POST',body:JSON.stringify({student_id:student,store_id:store})});
  if(actor!==state.authUser||student!==state.enrollStudentId||epoch!==state.presentationEpoch||!appPresentationActive())return false;
  if(!started?.request?.id)throw new Error('Không mở được phiên đăng ký.');
  state.enrollSession=started.request.id;
  const cameraReady=await prepareEnrollmentLaptopCamera();
  if(actor!==state.authUser||student!==state.enrollStudentId||epoch!==state.presentationEpoch||!appPresentationActive())return false;
  if(!cameraReady){
    if($('#faceidTitle'))$('#faceidTitle').textContent='Camera chưa sẵn sàng';
    if($('#faceidInstruction'))$('#faceidInstruction').innerHTML='<span class="instruction-icon">!</span><span>Kiểm tra quyền camera rồi bấm Quét lại để tiếp tục.</span>';
    toast('Hồ sơ đã lưu, nhưng camera đăng ký chưa sẵn sàng.',true);
    return false;
  }
  if(actor!==state.authUser||student!==state.enrollStudentId||epoch!==state.presentationEpoch||!appPresentationActive())return false;
  resetFaceIdUI();updateEnrollPerson();if(state.enrollmentSourceMode!=='browser')mountCameraPreview('enroll');startEnrollLoop();return true;
  }catch(e){if(actor===state.authUser&&epoch===state.presentationEpoch){toast(e.message,true);if($('#enrollHint'))$('#enrollHint').textContent=e.message;}return false;}
  finally{state.enrollStarting=false;}
}
async function finalizeEnrollment(auto=false,confirmDuplicate=false){
  if(state.enrollFinalizing||state.enrollCompleted||state.enrollDuplicatePending||!state.enrollStudentId)return;
  state.enrollFinalizing=true;
  const actor=state.authUser,session=state.enrollSession,student=state.enrollStudentId,epoch=state.presentationEpoch;
  if($('#faceidTitle'))$('#faceidTitle').textContent='Đang tạo hồ sơ FaceID';
  if($('#faceidInstruction'))$('#faceidInstruction').innerHTML='<span class="instruction-icon">✓</span><span>Đang mã hóa và kiểm tra bộ mẫu FaceID.</span>';
  try{
    const r=await api('/api/v1/enrollment/finalize',{method:'POST',body:JSON.stringify({request_id:session,student_id:student})});
    if(actor!==state.authUser||epoch!==state.presentationEpoch||session!==state.enrollSession||student!==state.enrollStudentId||!appPresentationActive())return;
    if(!['PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW'].includes(r?.request?.status))throw new Error('Chưa nhận được xác nhận hồ sơ chờ duyệt.');
    state.enrollCompleted=true;state.enrollDuplicatePending=false;state.enrollDuplicateCandidate=null;clearInterval(state.enrollTimer);state.enrollTimer=null;
    updateFaceIdProgress(1,'center',true,2,1,false);setSignal('#enrollLiveSignal','ok');$('#faceidSuccess')?.classList.add('show');clearEnrollBiometricOverlay();
    window.BTMHV4?.stopEnrollmentBrowserCamera?.();pauseCameraPreview('enroll');
    updateFaceValidationUi({status:r.request.status});
    await loadStudents();if(actor===state.authUser&&epoch===state.presentationEpoch&&appPresentationActive())toast('Đã gửi hồ sơ khuôn mặt. Mẫu mới chỉ hoạt động sau khi được duyệt.');
  }catch(e){if(actor===state.authUser&&epoch===state.presentationEpoch&&session===state.enrollSession&&student===state.enrollStudentId&&appPresentationActive()){state.enrollFinalizing=false;if(!auto)toast(e.message,true);if($('#enrollHint'))$('#enrollHint').textContent=e.message;}}
}
function showFaceDuplicateReview(candidate={}){
  const modal=$('#v5DuplicateFaceModal');if(!modal)return;
  const score=Math.round(Number(candidate?.score||0)*100);
  if($('#v5DuplicateFaceCandidate'))$('#v5DuplicateFaceCandidate').textContent=candidate?.full_name||candidate?.name||'Hồ sơ khác';
  if($('#v5DuplicateFaceMeta'))$('#v5DuplicateFaceMeta').textContent=`${candidate?.student_code||''}${score?` · độ tương đồng ${score}%`:''}`.replace(/^ · /,'');
  modal.classList.remove('hidden');
}
function closeFaceDuplicateReview(resetScan=false){
  $('#v5DuplicateFaceModal')?.classList.add('hidden');
  state.enrollDuplicatePending=false;state.enrollDuplicateCandidate=null;
  if(resetScan)resetEnrollment();
}
async function confirmFaceDuplicateEnrollment(){
  $('#v5DuplicateFaceModal')?.classList.add('hidden');
  state.enrollDuplicatePending=false;
  toast('Hãy quyết định trùng khuôn mặt trong hồ sơ chờ duyệt.',true);setEnrollPhase(false);
}
function updateFaceValidationUi(validation={}){
  const status=String(validation?.status||'PENDING_STORE_VALIDATION').toUpperCase();
  if(['PENDING_REVIEW','NEEDS_DUPLICATE_REVIEW'].includes(status)){
    const badge=$('#v5FaceValidationBadge');if(badge){badge.textContent=status==='NEEDS_DUPLICATE_REVIEW'?'CẦN KIỂM TRA TRÙNG':'CHỜ DUYỆT';badge.className='v5-face-validation-badge warn';}
    if($('#v5FaceValidationNote'))$('#v5FaceValidationNote').textContent='Mẫu mới chưa hoạt động. Chủ sở hữu hoặc Quản trị viên cần duyệt; FaceID cũ vẫn giữ nguyên nếu đã có.';
    const btn=$('#v5ValidateStoreCameraBtn');if(btn){btn.disabled=true;btn.textContent='Chờ duyệt FaceID';}return;
  }
  const verified=status==='VERIFIED';
  const badge=$('#v5FaceValidationBadge');if(badge){badge.textContent=verified?'ĐÃ XÁC MINH CAMERA':'CHỜ XÁC MINH CAMERA';badge.className=`v5-face-validation-badge ${verified?'ok':'warn'}`;}
  const note=$('#v5FaceValidationNote');if(note)note.textContent=verified?'FaceID đã được kiểm tra trên camera cửa hàng.':'FaceID đang hoạt động. Có thể kiểm tra thêm trên camera cửa hàng.';
  const btn=$('#v5ValidateStoreCameraBtn');if(btn){btn.disabled=verified;btn.textContent=verified?'✓ Đã xác minh camera cửa hàng':'Xác minh bằng camera cửa hàng';}
}
async function validateEnrollmentOnStoreCamera(){
  if(state.enrollValidationBusy||!state.enrollStudentId)return;
  const sel=$('#v5EnrollmentCameraSelect');
  if(!sel){toast('Không tìm thấy bộ chọn camera.',true);return;}
  if(String(sel.value||'browser')==='browser'){
    const storeOption=[...sel.options].find(o=>o.value&&o.value!=='browser');
    if(!storeOption){toast('Chưa có camera cửa hàng online/cấu hình để xác minh FaceID.',true);return;}
    sel.value=storeOption.value;
  }
  state.enrollValidationBusy=true;
  const btn=$('#v5ValidateStoreCameraBtn');if(btn){btn.disabled=true;btn.textContent='Đang chuyển camera & xác minh...';}
  const note=$('#v5FaceValidationNote');if(note)note.textContent='Đang handover sang camera cửa hàng và chờ frame ổn định...';
  try{
    const ready=await prepareEnrollmentLaptopCamera();
    if(!ready)throw new Error('Camera cửa hàng chưa sẵn sàng.');
    await new Promise(resolve=>setTimeout(resolve,900));
    const r=await api(`/api/v1/employees/${Number(state.enrollStudentId)}/face-validation`,{method:'POST',body:JSON.stringify({session_id:`validate-${Date.now()}`,student_id:state.enrollStudentId,image:''})});
    if(!r?.ok){
      updateFaceValidationUi({status:'PENDING_STORE_VALIDATION'});
      if(note)note.textContent=r?.message||'Camera chưa xác minh chắc chắn. Hãy đứng tự nhiên trong vùng quan sát và thử lại.';
      if(btn){btn.disabled=false;btn.textContent='Thử xác minh lại';}
      return;
    }
    updateFaceValidationUi(r.validation||{status:'VERIFIED',camera_source:r.camera_source});
    await loadStudents();toast('FaceID đã được xác minh trên camera cửa hàng.');
  }catch(e){
    updateFaceValidationUi({status:'PENDING_STORE_VALIDATION'});
    if(note)note.textContent=e.message||'Không xác minh được FaceID trên camera cửa hàng.';
    if(btn){btn.disabled=false;btn.textContent='Thử xác minh lại';}
    toast(e.message||'Không xác minh được FaceID.',true);
  }finally{state.enrollValidationBusy=false;}
}
window.validateEnrollmentOnStoreCamera=validateEnrollmentOnStoreCamera;

function startEnrollLoop(){
  clearInterval(state.enrollTimer);state.enrollTimer=setInterval(async()=>{
    if(!appPresentationActive()||!hasUiPermission('employee.enroll')||state.activePage!=='register'||state.enrollBusy||state.enrollFinalizing||state.enrollCompleted||state.enrollDuplicatePending||!state.enrollStudentId||!$('#registrationFacePhase')?.classList.contains('active'))return;
    const controller=new AbortController(),epoch=state.presentationEpoch,session=state.enrollSession,student=state.enrollStudentId;
    state.enrollRequestController=controller;
    state.enrollBusy=true;
    try{
      const r=await api('/api/v1/enrollment/frame',{method:'POST',signal:controller.signal,timeoutMs:8000,body:JSON.stringify({request_id:session,student_id:student,image:(state.enrollmentSourceMode==='browser'?(window.BTMHV4?.enrollmentDataUrl?.()||''):'')})});
      if(controller.signal.aborted||epoch!==state.presentationEpoch||!appPresentationActive()||!hasUiPermission('employee.enroll')||state.activePage!=='register'||session!==state.enrollSession||student!==state.enrollStudentId)return;
      state.enrollLastResponse=r;drawEnrollBiometricOverlay(r);updateEnrollLock(r);
      setSignal('#enrollLiveSignal',r?.pad?.status==='PASS'?'ok':['BLOCKED','MODEL_UNAVAILABLE'].includes(r?.pad?.status)?'bad':'warn');
      if(!r.ok){
        if($('#faceidTitle'))$('#faceidTitle').textContent='Căn chỉnh khuôn mặt';
        if($('#enrollHint'))$('#enrollHint').textContent=r.message||'Đang chờ khuôn mặt';
        setSignal('#enrollFaceSignal','bad');setSignal('#enrollQualitySignal','warn');$('#faceidScanner')?.classList.add('aligning');
        if($('#faceidInstruction'))$('#faceidInstruction').innerHTML=`<span class="instruction-icon">◎</span><span>${escapeHtml(r.message||'Đưa khuôn mặt vào giữa khung.')}</span>`;
        return;
      }
      const c=r.pose_counts||{},goals=r.pose_goals||{};const ready=!!r.ready_to_finalize;
      updateFaceIdProgress(r.progress||0,r.guide||'center',ready,r.scan_pass||1,r.pass_progress||0,!!r.pass_transition);renderEnrollPoseProgress(c,r.guide||'center',goals,r.coverage||[]);$('#faceidScanner')?.classList.remove('aligning');
      const calibrating=r.neutral_ready===false;
      setSignal('#enrollFaceSignal','ok');setSignal('#enrollQualitySignal',(r.quality?.score||0)>.55?'ok':'warn');
      if(r.accepted)flashAcceptedSample();
      if($('#qSharp'))$('#qSharp').textContent=`${r.sharp_label||'—'} · ${Math.round(Number(r.quality?.sharpness||0))}`;
      if($('#qLight'))$('#qLight').textContent=`${r.light_label||'—'} · ${Math.round(Number(r.quality?.brightness||0))}`;
      if($('#qPose'))$('#qPose').textContent=r.pose_label||ENROLL_POSE_LABEL[r.pose]||r.pose||'—';
      if($('#qScore'))$('#qScore').textContent=`${r.quality_label||''} ${Math.round(Number(r.quality?.score||0)*100)}%`.trim();
      const guide=r.guide||'center';
      if($('#faceidTitle'))$('#faceidTitle').textContent=ready?'Đã hoàn tất 2 vòng quét':(calibrating?'Nhìn thẳng vào camera':faceIdGuideText(guide));
      const missingHint=calibrating?'':faceIdMissingHint(r);
      if($('#enrollHint'))$('#enrollHint').textContent=ready?'Đã thu đủ dữ liệu đa góc để tạo hồ sơ FaceID.':(calibrating?(r.message||'Nhìn thẳng vào camera để hiệu chuẩn tư thế chính diện.'):(missingHint||(r.accepted?'Đã lưu góc này. Tiếp tục di chuyển đầu chậm theo điểm sáng.':(r.message||'Giữ chuyển động chậm và tự nhiên.'))));
      if($('#faceidInstruction'))$('#faceidInstruction').innerHTML=`<span class="instruction-icon">${ready?'✓':'◎'}</span><span>${ready?'Hoàn tất. Đang tạo hồ sơ FaceID.':(calibrating?(r.message||'Nhìn thẳng vào camera khoảng một giây.'):(missingHint||faceIdGuideText(guide)))}</span>`;
      if($('#finalizeEnrollBtn')){$('#finalizeEnrollBtn').disabled=!ready;$('#finalizeEnrollBtn').classList.toggle('hidden',!ready);}
      if(Number(r.progress||0)>=1&&ready&&!state.enrollFinalizing)finalizeEnrollment(true);
    }catch(e){if(!controller.signal.aborted&&epoch===state.presentationEpoch&&session===state.enrollSession&&student===state.enrollStudentId&&state.activePage==='register'&&hasUiPermission('employee.enroll')&&appPresentationActive()){
      if($('#enrollHint'))$('#enrollHint').textContent=e.message;setSignal('#enrollQualitySignal','bad');updateEnrollLock({ok:false});
      if([403,410,429].includes(e.status)){clearInterval(state.enrollTimer);state.enrollTimer=null;window.BTMHV4?.stopEnrollmentBrowserCamera?.();pauseCameraPreview('enroll');}
    }}
    finally{if(state.enrollRequestController===controller){state.enrollRequestController=null;state.enrollBusy=false;}}
  },230);
}
function guideTitle(g){return faceIdGuideText(g);}
function guideText(g,ready=false){return ready?'Quét hoàn tất. Hệ thống đang tạo hồ sơ FaceID đa góc.':`${faceIdGuideText(g)} · di chuyển chậm và tự nhiên.`;}

async function resetEnrollment(){
  if(state.enrollCompleted){toast('Hồ sơ đã gửi. Dùng yêu cầu quét lại trong phần duyệt để tạo phiên mới.',true);return false;}
  if(!state.enrollSession)return beginFaceIdSetup();
  const actor=state.authUser,epoch=state.presentationEpoch,session=state.enrollSession,student=state.enrollStudentId;
  const current=()=>actor===state.authUser&&epoch===state.presentationEpoch&&session===state.enrollSession&&student===state.enrollStudentId&&state.activePage==='register'&&canManageEnrollment()&&appPresentationActive();
  if(!current())return false;
  clearInterval(state.enrollTimer);state.enrollTimer=null;state.enrollRequestController?.abort();state.enrollRequestController=null;state.enrollBusy=false;
  const cameraReady=await prepareEnrollmentLaptopCamera();
  if(!current())return false;
  if(!cameraReady){
    if($('#faceidTitle'))$('#faceidTitle').textContent='Camera chưa sẵn sàng';
    if($('#enrollHint'))$('#enrollHint').textContent='Không thể mở camera đăng ký. Kiểm tra camera/quyền truy cập rồi thử lại.';
    toast('Camera đăng ký chưa sẵn sàng.',true);
    return false;
  }
  try{await api('/api/v1/enrollment/reset',{method:'POST',body:JSON.stringify({request_id:session,student_id:student})});}
  catch(e){if(current()){toast(e.message,true);window.BTMHV4?.stopEnrollmentBrowserCamera?.();pauseCameraPreview('enroll');}return false;}
  if(!current())return false;
  resetFaceIdUI();updateEnrollPerson();if(state.enrollmentSourceMode!=='browser')mountCameraPreview('enroll');startEnrollLoop();return true;
}

function setRecognitionProgress(frac=0,label='Sẵn sàng'){
  const p=Math.max(0,Math.min(100,Math.round(Number(frac||0)*100)));if($('#v21RecognitionPercent'))$('#v21RecognitionPercent').textContent=p+'%';if($('#v21RecognitionFill'))$('#v21RecognitionFill').style.width=p+'%';if($('#v21RecognitionState'))$('#v21RecognitionState').textContent=label;
}
function setEntryBadge(text,tone='neutral'){const e=$('#entryStateBadge');if(!e)return;e.textContent=text;e.className='entry-state-badge '+tone;}
function renderRecognitionPending(active,title='Đang xác minh',detail='AI đang chờ thêm khung hình tốt hơn.'){
  // Clear a previous temporary UNKNOWN/SPOOF card as soon as the same physical
  // track recovers. Pending states are not history events.
  state.lastSpoofTrack=null;state.lastUnknownTrack='';state.recognitionProfileKey='';
  const snap=active?.best_snapshot||'';const img=$('#recognitionSnapshot');
  if(img){if(snap){img.src=snap;img.style.display='block';$('#recognitionSnapshotEmpty')?.classList.add('hidden');}else{img.removeAttribute('src');img.style.display='none';$('#recognitionSnapshotEmpty')?.classList.remove('hidden');}}
  if($('#profileAvatar'))$('#profileAvatar').textContent='…';
  if($('#profileName'))$('#profileName').textContent=title;
  if($('#profileCode'))$('#profileCode').textContent=detail;
  if($('#profileConfidence'))$('#profileConfidence').textContent='—';
  if($('#profileClass'))$('#profileClass').textContent='—';if($('#profileFaculty'))$('#profileFaculty').textContent='—';
  if($('#profileLiveness'))$('#profileLiveness').textContent='ĐANG KIỂM TRA';
  if($('#profileTime'))$('#profileTime').textContent=formatTime(new Date().toISOString());
}
function renderRecognitionSlotSelection(detail={}){
  const camera=detail.camera,meta=camera&&Number(detail.metadata?.camera_id)===Number(camera.camera_id)?detail.metadata:null;
  const aiState=String(camera?.ai_state||meta?.ai_state||'').toUpperCase();
  const canConfigure=typeof hasUiPermission==='function'&&hasUiPermission('camera.configure');
  const configureHelp=canConfigure?'Mở Quản lý camera, chọn camera, gán cửa hàng và khu vực, bật Nhận diện AI rồi Lưu cấu hình.':'Liên hệ người quản lý để gán cửa hàng, khu vực và bật Nhận diện AI cho camera này.';
  let unavailable=null;
  if(camera){
    if(camera.ai_enabled===false||aiState==='DISABLED')unavailable={title:'AI chưa bật',detail:configureHelp};
    else if(!camera.store_id)unavailable={title:'AI chưa được gán cửa hàng',detail:configureHelp};
    else if(!String(camera.zone_name||'').trim())unavailable={title:'AI chưa được đặt khu vực',detail:configureHelp};
    else if(camera.reason_code==='AI_WORKER_START_FAILED')unavailable={title:'AI chưa khả dụng',detail:'Không khởi động được xử lý AI cho camera này. Kiểm tra trạng thái hệ thống hoặc liên hệ người quản lý.'};
    else unavailable=({ERROR:{title:'AI gặp lỗi xử lý',detail:'Chưa có kết quả nhận diện mới. Kiểm tra trạng thái hệ thống hoặc liên hệ người quản lý.'},PAUSED:{title:'AI đang tạm dừng',detail:'Chưa có kết quả nhận diện mới trong lúc AI tạm dừng.'},STARTING:{title:'AI đang khởi động',detail:'Chờ AI xử lý khung hình đầu tiên; video vẫn hoạt động độc lập.'},OFFLINE:{title:'AI mất kết nối',detail:'Chưa nhận được khung hình cho AI. Kiểm tra kết nối camera hoặc liên hệ người quản lý.'},WAITING_FOR_CAPACITY:{title:'AI chờ lượt xử lý',detail:'Camera đã bật AI và đang chờ dung lượng xử lý. Chọn ô hiển thị không thay đổi lượt AI.'},STOPPING:{title:'AI đang chuyển trạng thái',detail:'Chờ xử lý trước đó dừng để áp dụng cấu hình camera.'}})[aiState]||null;
    if(!unavailable&&aiState!=='ACTIVE')unavailable={title:'Chưa có trạng thái AI',detail:'Chưa cập nhật được trạng thái xử lý AI. Chọn Tải lại hoặc liên hệ người quản lý.'};
    if(!unavailable&&meta?.metadata_stale)unavailable={title:'Chờ dữ liệu nhận diện mới',detail:'Kết quả trước đã quá hạn. Video và AI nền hoạt động độc lập; đang chờ dữ liệu mới từ camera này.'};
  }
  // Availability takes precedence over a cached identity from an earlier observation.
  const tracks=!unavailable&&Array.isArray(meta?.tracks)?meta.tracks:[];
  const track=tracks.find(item=>item.recognized&&!item.spoof_blocked)||tracks[0];
  const blocked=!!track?.spoof_blocked||String(track?.status||'').toUpperCase()==='SPOOF_BLOCKED';
  const verified=!!track?.recognized&&!blocked;
  const unregistered=!!track?.unregistered||String(track?.status||'').toUpperCase()==='UNREGISTERED';
  const name=!camera?'Chưa chọn camera':unavailable?unavailable.title:!meta?'Đang chờ dữ liệu nhận diện':!track?'Chưa có nhận diện':blocked?'Không qua xác minh':verified?(track.full_name||'Đã xác minh danh tính'):unregistered?'Chưa có FaceID nhân viên':'Đang xác minh';
  const verificationHelp=({PAD_BLOCKED:'Passive PAD chưa xác minh người thật; danh tính vẫn bị chặn.',PAD_CHECKING:'Đang tích lũy kết quả Passive PAD trước FaceID.',PAD_INFERENCE_FAILED:'PAD chưa xử lý thành công; danh tính vẫn bị chặn.',FACE_TOO_SMALL:'Khuôn mặt còn nhỏ hoặc chưa rõ để xác minh.',FACE_POSE:'Góc mặt đang nghiêng; AI chờ khung hình phù hợp.',FACE_PITCH:'Góc nhìn dọc chưa phù hợp để xác minh.',FACE_BLUR:'Khuôn mặt chưa đủ nét để xác minh.',FACE_LIGHTING:'Ánh sáng khuôn mặt chưa phù hợp để xác minh.',FACE_QUALITY_WAIT:'AI đang chờ khung hình khuôn mặt rõ hơn.'})[track?.verification_reason_code]||'';
  const set=(id,value)=>{const element=$(id);if(element)element.textContent=value;};
  set('#recognitionSelectedContext',camera?[camera.store_name||'Chưa gán cửa hàng',camera.zone_name||'Chưa gán khu vực',camera.camera_name].filter(Boolean).join(' · '):'Chưa chọn camera');
  set('#profileName',name);set('#profileCode',unavailable?unavailable.detail:verified?(track.student_code||''):verificationHelp|| (camera?'Kết quả từ camera đang chọn':'Chọn camera để xem nhận diện'));
  set('#profileAvatar',verified?initials(track.full_name||''):blocked?'!':'?');
  set('#profileConfidence',verified&&Number.isFinite(Number(track.confidence))?pct(track.confidence)+'%':'—');
  set('#profileCamera',camera?.camera_name||'—');
  set('#profileSubject',verified?'Nhân viên':track?'Chưa xác định':'—');
  const currentCard=$('#page-recognition')?.querySelector?.('.entry-current-card');
  if(currentCard)currentCard.dataset.tone=verified?'verified':blocked?'blocked':track?'pending':'idle';
  set('#profileClass','—');set('#profileFaculty','—');
  const pad=String(track?.pad_status||'').toUpperCase();
  set('#profileLiveness',blocked?'Không qua kiểm tra':pad==='PASS'?'Đã qua kiểm tra':pad==='FAIL'?'Không qua kiểm tra':track?'Đang kiểm tra':'—');
  const stamp=Number(!unavailable&&meta?.updated_at||0);
  set('#profileTime',stamp>0&&Number.isFinite(stamp)?formatTime(new Date(stamp*1000).toISOString()):'—');
  set('#profileDirection','Chưa ghi nhận');
  // Fetch only the selected appearance's protected saved photo; metadata stays image-free.
  if(window.BTMHRecentRecognition?.renderSelectedPhoto)window.BTMHRecentRecognition.renderSelectedPhoto(detail);
  else{const image=$('#recognitionSnapshot');if(image){image.removeAttribute('src');image.style.display='none';}$('#recognitionSnapshotEmpty')?.classList.remove('hidden');}
  state.recognitionProfileKey=camera&&track?`${camera.camera_id}:${track.track_id}:${track.status||''}`:'';
  const progressLabel=unavailable?unavailable.title:verified?'Đã xác minh':blocked?'Cần kiểm tra':track?'Đang quan sát':camera?!meta?'Chờ dữ liệu nhận diện':'Chờ khuôn mặt':'Chưa chọn camera';
  setEntryBadge(progressLabel,verified?'good':blocked?'bad':'neutral');
  // This fraction describes verification only; it is not AI startup or inference progress.
  setRecognitionProgress(verified||blocked?1:0,progressLabel);
  const alert=$('#recognitionAlert');if(alert){alert.className='alert-box '+(blocked?'bad':verified?'good':'neutral');alert.textContent=unavailable?unavailable.detail:blocked?'Không xác minh danh tính cho quan sát này.':camera?'Trạng thái nhận diện theo camera đang chọn. Hướng ra/vào được ghi nhận từ sự kiện qua cổng.':'Chọn camera để xem trạng thái nhận diện tại khu vực đó.';}
}
document.addEventListener('btmh:recognition-selection',event=>renderRecognitionSlotSelection(event.detail||{}));
function isUnregisteredRecognition(ev){
  return String(ev?.status||'').toUpperCase()==='UNREGISTERED' || !!ev?.unknown || !!ev?.unregistered || (!ev?.student_id && !ev?.student?.id && String(ev?.full_name||'').toLowerCase().includes('chưa đăng ký'));
}
function isSpoofBlocked(ev){return String(ev?.status||'').toUpperCase()==='SPOOF_BLOCKED'||!!ev?.spoof_blocked;}
function passiveAntiSpoofText(ev){
  const l=ev?.liveness||{},pad=l?.signals?.pad||{};
  const live=Math.round(Number(pad.live_score??ev?.liveness_score??l.score??0)*100);
  const spoof=Math.round(Number(pad.spoof_score??l.risk_score??0)*100);
  if(isSpoofBlocked(ev))return `BỊ CHẶN${spoof?` · PAD spoof ${spoof}%`:''}`;
  if(ev?.anti_spoof_passed||String(l.status||'').toUpperCase()==='PASS')return `Người thật ✓${live?` · PAD live ${live}%`:''}`;
  if(pad.ready===false)return String(l.status||'').toUpperCase()==='PASS'?'Người thật ✓ · Anti-spoof context':'Đang kiểm tra điện thoại/ảnh thẻ đa khung';
  return l.reason||`Đang xác minh PAD${live?` · live ${live}%`:''}`;
}
function renderLatestRecognition(ev,recordHistory=true){
  if(!ev)return;
  if(state.activePage==='recognition'&&window.BTMHRecognitionSlots)return;
  const blocked=isSpoofBlocked(ev),unregistered=!blocked&&isUnregisteredRecognition(ev),s=ev.student||ev,p=pct(ev.confidence);
  if(recordHistory&&ev.id!=null)state.latestSnapshots.set(Number(ev.id),ev.best_snapshot||'');
  if($('#recognitionSnapshot')){
    const img=$('#recognitionSnapshot');
    if(ev.best_snapshot){img.src=ev.best_snapshot;img.style.display='block';$('#recognitionSnapshotEmpty')?.classList.add('hidden')}
    else{img.removeAttribute('src');img.style.display='none';$('#recognitionSnapshotEmpty')?.classList.remove('hidden')}
  }
  const matchedName=s.full_name||'';
  if($('#profileAvatar'))$('#profileAvatar').textContent=blocked?'!':(unregistered?'?':initials(matchedName||''));
  if($('#profileName'))$('#profileName').textContent=blocked?'Khuôn mặt bị chặn':(unregistered?'Khách hàng':(matchedName||'Đã nhận diện'));
  if($('#profileCode'))$('#profileCode').textContent=blocked?'FaceID không được thực hiện':(unregistered?'Không có FaceID trong hệ thống':(s.student_code||''));
  if($('#profileConfidence'))$('#profileConfidence').textContent=(blocked||unregistered)?'—':p+'%';
  if($('#profileClass'))$('#profileClass').textContent=(blocked||unregistered)?'—':(s.class_name||'—');
  if($('#profileFaculty'))$('#profileFaculty').textContent=(blocked||unregistered)?'—':(s.faculty||'—');
  if($('#profileLiveness'))$('#profileLiveness').textContent=blocked?'BỊ CHẶN':(unregistered?'Không có FaceID nhân viên':passiveAntiSpoofText(ev));
  if($('#profileTime'))$('#profileTime').textContent=formatTime(ev.event_at||new Date().toISOString());
  if($('#profileDirection'))$('#profileDirection').textContent='Vào';
  if(blocked){
    setEntryBadge('Nghi giả mạo','bad');setRecognitionProgress(1,'SPOOF BLOCKED');
    if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box bad';$('#recognitionAlert').textContent=ev.reason||ev?.liveness?.reason||'Phát hiện khuôn mặt trên điện thoại/màn hình hoặc ảnh phẳng. FaceID và check-in đã bị chặn.';}
  }else if(unregistered){
    setEntryBadge('Khách hàng','warn');setRecognitionProgress(1,'Khách hàng');
    if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box warn';$('#recognitionAlert').textContent='Người này chưa khớp FaceID nhân viên và được hiển thị là Khách hàng.';}
  }else{
    setEntryBadge('Đã xác minh','good');setRecognitionProgress(1,'FaceID + Anti-spoof PASS');
    if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box good';$('#recognitionAlert').textContent='Đã xác minh danh tính sau chống giả mạo thụ động; không yêu cầu nhìn camera hoặc thực hiện động tác.';}
  }
  if(recordHistory){
    const row={id:ev.id,event_at:ev.event_at||new Date().toISOString(),student_id:unregistered?null:(s.id||ev.student_id),student_code:unregistered?'':(s.student_code||''),full_name:blocked?'Khuôn mặt bị chặn':(unregistered?'Khách hàng':(s.full_name||'')),class_name:unregistered?'':(s.class_name||''),faculty:unregistered?'':(s.faculty||''),confidence:unregistered?0:Number(ev.confidence||0),liveness_score:Number(ev.liveness_score??ev?.liveness?.score??0),anti_spoof_passed:!!ev.anti_spoof_passed,best_snapshot:ev.best_snapshot||'',reason:ev.reason||ev?.liveness?.reason||'',status:blocked?'SPOOF_BLOCKED':(unregistered?'UNREGISTERED':'RECOGNIZED')};
    state.events=[row,...state.events.filter(x=>Number(x.id)!==Number(ev.id))];
    renderRecognitionRecent();renderRecognitionPreviewHistory();updateDashboardStats();
  }
}
function renderRecognitionRecent(){
  if(window.BTMHRecentRecognition)return;
  const host=$('#recognitionRecentShots');if(!host)return;const list=state.events.filter(e=>state.latestSnapshots.get(Number(e.id))||e.best_snapshot).slice(0,5);if($('#recognitionRecentCount'))$('#recognitionRecentCount').textContent=String(state.events.length);
  host.innerHTML=list.length?list.map(e=>{const blocked=isSpoofBlocked(e),unreg=!blocked&&isUnregisteredRecognition(e),snap=state.latestSnapshots.get(Number(e.id))||e.best_snapshot||'';return `<button class="entry-shot-thumb" type="button" onclick="showRecognitionEvent(${Number(e.id)})">${snap?`<img src="${snap}" alt="Best shot">`:`<span class="entry-shot-placeholder">?</span>`}<span>${escapeHtml(blocked?'Khuôn mặt bị chặn':(unreg?'Khách hàng':(e.full_name||'Đã nhận diện')))}</span></button>`}).join(''):'<div class="entry-recent-empty">Chưa có lượt nhận diện.</div>';
}
window.showRecognitionEvent=(id)=>{if(state.activePage==='recognition'&&window.BTMHRecentRecognition)return;const e=state.events.find(x=>Number(x.id)===Number(id));if(!e)return;renderLatestRecognition({...e,student:e,best_snapshot:state.latestSnapshots.get(Number(id))||e.best_snapshot||''});};
function renderRecognitionPreviewHistory(){
  const body=$('#recognitionRecentBody');if(!body)return;const list=state.events.slice(0,30);
  body.innerHTML=list.length?list.map((e,i)=>{const blocked=isSpoofBlocked(e),unreg=!blocked&&isUnregisteredRecognition(e),snap=state.latestSnapshots.get(Number(e.id))||e.best_snapshot||'';const status=blocked?'Bị chặn giả mạo':(unreg?'Khách hàng':'Đã nhận diện');return `<tr><td>${i+1}</td><td>${formatTime(e.event_at)}</td><td><div class="entry-history-face">${snap?`<img src="${snap}" alt="">`:initials(e.full_name||'')}</div></td><td><span class="entry-history-name">${escapeHtml(blocked?'Khuôn mặt bị chặn':(unreg?'Khách hàng':(e.full_name||'Chưa xác định')))}</span></td><td>${escapeHtml((unreg||blocked)?'—':(e.student_code||'—'))}</td><td>${escapeHtml((unreg||blocked)?'—':(e.class_name||'—'))}</td><td>${escapeHtml((unreg||blocked)?'—':(e.faculty||'—'))}</td><td><span class="entry-history-direction">Vào</span></td><td><span class="entry-history-status${(unreg||blocked)?' is-unknown':''}">${status}</span></td><td><span class="entry-history-confidence">${(unreg||blocked)?'—':pct(e.confidence)+'%'}</span></td></tr>`}).join(''):'<tr><td colspan="10" class="empty-card">Chưa có lượt nhận diện.</td></tr>';
}
async function loadRecognitionHistory(){
  if(state.activePage==='recognition'&&window.BTMHRecentRecognition)return window.BTMHRecentRecognition.requestRefresh();
  try{const rows=await api('/api/v1/events?limit=80');const mem=new Map(state.events.map(x=>[Number(x.id),x]));state.events=rows.map(x=>({...x,best_snapshot:mem.get(Number(x.id))?.best_snapshot||'',status:x.status||mem.get(Number(x.id))?.status||''}));renderRecognitionPreviewHistory();renderRecognitionRecent();updateDashboardStats();}catch(e){console.warn(e)}
}
async function pollRecognition(){
  if(!appPresentationActive()||!hasUiPermission('camera.live'))return;
  const onRecognition=state.activePage==='recognition',onDashboard=state.activePage==='dashboard';
  if(onRecognition&&window.BTMHRecognitionSlots)return;
  if(!onRecognition&&!onDashboard)return;
  try{
    const enteredPage=state.activePage,epoch=state.presentationEpoch;const r=await api('/api/v1/camera/latest-result');if(state.activePage!==enteredPage||epoch!==state.presentationEpoch||!appPresentationActive()||!hasUiPermission('camera.live'))return;const tracks=r.tracks||[],handover=r.handover||{};
    if(onRecognition){
      if(r.recognition_paused){
        setEntryBadge('Đang chuyển camera','neutral');setRecognitionProgress(.18,'PAUSE FaceID');
        if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box neutral';$('#recognitionAlert').textContent=handover.message||'FaceID đang tạm dừng trong lúc chuyển camera và sẽ tự tiếp tục khi camera mới ổn định.';}
        if($('#recognitionFaceCount'))$('#recognitionFaceCount').textContent='0';if($('#recognitionTrackCount'))$('#recognitionTrackCount').textContent='0';
        return;
      }
      if($('#recognitionFaceCount'))$('#recognitionFaceCount').textContent=String(r.face_count||0);
      if($('#recognitionTrackCount'))$('#recognitionTrackCount').textContent=String(r.track_count??tracks.length);
      if($('#recognitionQueueCount'))$('#recognitionQueueCount').textContent='0';
      const active=tracks[0],status=String(active?.status||'').toUpperCase(),live=active?.liveness||{};
      if(status==='SPOOF_BLOCKED'){
        const justEntered=(Date.now()-Number(state.recognitionEnteredAt||0))<450;
        if(!justEntered){
          setEntryBadge('Nghi giả mạo','bad');setRecognitionProgress(1,'SPOOF BLOCKED');
          if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box bad';$('#recognitionAlert').textContent=live.reason||'Phát hiện khuôn mặt trên điện thoại/màn hình hoặc ảnh phẳng. FaceID bị chặn.';}
          const spoofKey=`spoof-track-${active?.track_id||0}`;
          if(active&&state.lastSpoofTrack!==spoofKey){state.lastSpoofTrack=spoofKey;renderLatestRecognition({id:-2000000-Number(active.track_id||0),event_at:new Date().toISOString(),status:'SPOOF_BLOCKED',spoof_blocked:true,student:active.candidate_student||{},confidence:Number(active.candidate_confidence||0),best_snapshot:active.best_snapshot||'',liveness:live,liveness_score:Number(live.score||0),anti_spoof_passed:false,reason:live.reason||'Không vượt qua xác minh người thật'});}
        }
      }else if(status==='OBSERVING_QUALITY'){
        const reason=active?.quality_gate?.reason||'AI đang chờ khuôn mặt rõ hơn; chưa kết luận danh tính hoặc giả mạo.';
        renderRecognitionPending(active,'Đang quan sát','Chưa đủ khung hình chất lượng');
        setEntryBadge('Đang quan sát','neutral');setRecognitionProgress(.30,'Chờ frame tốt');
        if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box neutral';$('#recognitionAlert').textContent=reason;}
      }else if(status==='VERIFYING_PASSIVE'||status==='VERIFYING_LIVENESS'||status==='LIVENESS_CHALLENGE'||status==='CHECKING'){
        const pad=live?.signals?.pad||{},livePct=Math.round(Number(pad.live_score||0)*100),spoofPct=Math.round(Number(pad.spoof_score||0)*100),padReady=pad.ready!==false;
        renderRecognitionPending(active,'Đang xác minh','Đang kiểm tra người thật và FaceID đa khung');
        setEntryBadge(padReady?'Đang xác minh Passive PAD':'Đang kiểm tra chống giả mạo','neutral');
        setRecognitionProgress(.58,padReady?`PAD đa khung · live ${livePct}% · spoof ${spoofPct}%`:'Kiểm tra điện thoại/ảnh thẻ đa khung');
        if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box neutral';$('#recognitionAlert').textContent=live.reason||(padReady?'Đang xác minh người thật bằng Passive PAD đa khung; nhân viên không cần nhìn camera hay thực hiện động tác.':'Đang kiểm tra bối cảnh điện thoại/ảnh thẻ; FaceID sẽ tự chạy khi đủ khung hình sạch.');}
      }else if(active?.unknown || status==='UNREGISTERED'){
        const key=`unknown-track-${active.track_id}`;
        if(state.lastUnknownTrack!==key){state.lastUnknownTrack=key;renderLatestRecognition({id:-1000000-Number(active.track_id||0),event_at:new Date().toISOString(),status:'UNREGISTERED',unknown:true,best_snapshot:active.best_snapshot||'',confidence:0});}
      }else if(active&&!active.recognized){
        const samples=Number(active.samples||0),fused=Number(active?.quality_gate?.fused_frames||0);renderRecognitionPending(active,'Đang nhận diện',`Đã chọn ${Math.max(samples,fused)} frame tốt · tiếp tục tự cập nhật`);setEntryBadge('Đang phân tích','neutral');setRecognitionProgress(Math.min(.82,.2+Math.max(samples,fused)*.12),'Đang nhận diện đa khung');if($('#recognitionAlert')){$('#recognitionAlert').className='alert-box neutral';$('#recognitionAlert').textContent='Camera vẫn chạy; AI đang tổng hợp nhiều frame tốt và sẽ tự nâng kết quả khi khuôn mặt rõ hơn.';}
      }else if(active?.recognized){
        state.lastUnknownTrack='';state.lastSpoofTrack=null;
        const st=active.student||active.candidate_student||{};
        const sid=Number(active.student_id||st.id||0);
        const profileKey=`recognized-track-${Number(active.track_id||0)}-student-${sid}`;
        if(state.recognitionProfileKey!==profileKey){
          state.recognitionProfileKey=profileKey;
          renderLatestRecognition({
            id:-3000000-Number(active.track_id||0),
            event_at:new Date().toISOString(),
            status:'RECOGNIZED',
            student:{...st,id:sid||st.id},
            student_id:sid||null,
            confidence:Number(active.confidence||active.candidate_confidence||0),
            best_snapshot:active.best_snapshot||'',
            liveness:live,
            liveness_score:Number(live.score||0),
            anti_spoof_passed:true,
            reason:'live-track-sync'
          },false);
        }
      }else if(!active){resetRecognitionTransientUi();}
    }
    const j=await api('/api/v1/camera/latest-event');
    if(state.activePage!==enteredPage||epoch!==state.presentationEpoch||!appPresentationActive()||!hasUiPermission('camera.live'))return;
    if(j.event&&Number(j.event.id)!==Number(state.lastEventId)){
      state.lastEventId=Number(j.event.id);
      if(onRecognition)renderLatestRecognition(j.event);
      else loadRecognitionHistory().catch(()=>{});
    }
  }catch(_){ }
}

function mountCameraControlPreview(){
  const img=$('#cameraControlPreview'),empty=$('#cameraControlPreviewEmpty');if(!img)return;
  img.onload=()=>{if(empty)empty.style.display='none'};
  img.onerror=()=>{if(empty){empty.style.display='grid';const s=empty.querySelector('span');if(s)s.textContent='Đang kết nối lại camera...'};};
  BTMHRuntime.preview(img,'/api/v1/camera/frame_raw.jpg',150);
}
function stopCameraControlView(){
  if(state.cameraControlTimer){clearInterval(state.cameraControlTimer);state.cameraControlTimer=null;}
  const img=$('#cameraControlPreview');if(img){BTMHRuntime.stopPreview(img);img.onload=img.onerror=null;}
}
function renderCameraControlStatus(d={}){
  const mode=String(d.mode||'digital').toUpperCase();
  if($('#cameraControlMode')){$('#cameraControlMode').textContent=mode==='HARDWARE'?'PTZ PHẦN CỨNG':'DIGITAL PTZ';$('#cameraControlMode').className='pr-state '+(d.camera_online?'ok':'warn');}
  if($('#cameraControlModeValue'))$('#cameraControlModeValue').textContent=mode;
  if($('#cameraControlPan'))$('#cameraControlPan').textContent=Number(d.pan||0).toFixed(2);
  if($('#cameraControlTilt'))$('#cameraControlTilt').textContent=Number(d.tilt||0).toFixed(2);
  if($('#cameraControlZoomValue'))$('#cameraControlZoomValue').textContent=`${Number(d.zoom||1).toFixed(2)}×`;
  if($('#cameraControlZoom'))$('#cameraControlZoom').textContent=`Zoom ${Number(d.zoom||1).toFixed(2)}×`;
  if($('#cameraControlOnline'))$('#cameraControlOnline').textContent=d.camera_online?'ONLINE':'OFFLINE';
  if($('#cameraControlMessage'))$('#cameraControlMessage').textContent=d.message||'Camera control sẵn sàng';
}
async function loadCameraControlStatus(){
  if(!appPresentationActive()||state.activePage!=='camera-control'||!hasUiPermission('camera.live'))return;
  return BTMHRuntime.once('camera-control-status',async()=>{
    const epoch=state.presentationEpoch;
    try{const result=await api('/api/v1/camera/control/status');if(epoch===state.presentationEpoch&&appPresentationActive()&&state.activePage==='camera-control')renderCameraControlStatus(result);}
    catch(e){if(epoch===state.presentationEpoch&&appPresentationActive()&&$('#cameraControlMessage'))$('#cameraControlMessage').textContent=e.message;}
  });
}
async function sendCameraControl(action){
  if(!action)return;const speed=Math.max(.1,Math.min(1,Number($('#cameraControlSpeed')?.value||50)/100));
  try{renderCameraControlStatus(await api('/api/v1/camera/control',{method:'POST',body:JSON.stringify({action,speed})}));}catch(e){toast(e.message,true)}
}
function startCameraControlView(){
  if(!appPresentationActive()||state.activePage!=='camera-control'||!hasUiPermission('camera.live'))return;
  setupCameraPresetUi();mountCameraControlPreview();loadCameraControlStatus();
  if(!state.cameraControlTimer)state.cameraControlTimer=setInterval(()=>{if(state.activePage==='camera-control')loadCameraControlStatus()},1500);
}

async function loadEvents(){await loadRecognitionHistory();}
async function loadDashboardPresence(){
  const host=$('#v5DashPresenceList');if(!host)return;
  if(!hasUiPermission('attendance.view')){host.innerHTML='<div class="empty-card">Vai trò hiện tại không có quyền xem hiện diện toàn cửa hàng.</div>';return;}
  try{const d=await api('/api/v1/presence/current'),rows=d.items||[];if($('#v5DashVisitorsNow'))$('#v5DashVisitorsNow').textContent=String(d.active_visitors||0);host.innerHTML=rows.length?rows.slice(0,12).map(r=>`<div class="v5-presence-row"><div class="v5-presence-avatar">${escapeHtml(initials(r.full_name||'?'))}</div><div><b>${escapeHtml(r.full_name||'Nhân viên')}</b><small>${escapeHtml(r.employee_code||'—')} · ${escapeHtml(r.department||r.group||'Nhân viên')}</small></div><time>${r.last_seen_at?formatTime(r.last_seen_at):'—'}</time></div>`).join('')+`<div class="v5-presence-visitors">Khách đang có mặt: <b>${Number(d.active_visitors||0)}</b></div>`:'<div class="empty-card">Chưa có nhân viên đang được ghi nhận trong cửa hàng.</div>'+`<div class="v5-presence-visitors">Khách đang có mặt: <b>${Number(d.active_visitors||0)}</b></div>`;}catch(e){host.innerHTML=`<div class="empty-card">${escapeHtml(e.message||'Không tải được dữ liệu hiện diện.')}</div>`;}
}
async function loadDashboard(){
  if(window.BTMHManagement){window.BTMHManagement.start();state.v13LastSummaryAt=Date.now();return;}
  const jobs=[loadRecognitionHistory(),loadProfessionalSummary(true),loadDashboardPresence()];if(!state.students.length)jobs.push(loadStudents());await Promise.all(jobs);state.v13LastSummaryAt=Date.now();
  const host=$('#v20RecentCheckins');const latest=state.dashboardSummary?.latest||state.events.slice(0,6);renderV13Events(latest);
  if(host){host.innerHTML=latest.length?latest.slice(0,6).map(e=>`<div class="v20-feed-item"><div class="v20-feed-icon">ID</div><div><b>${escapeHtml(e.full_name||'Chưa đăng ký')}</b><span>${escapeHtml(e.student_code||e.status||'')} · ${escapeHtml(e.class_name||'')}</span><small>${formatDate(e.event_at)} · ${pct(e.confidence)}%</small></div></div>`).join(''):'<div class="empty-card">Chưa có nhận diện hôm nay.</div>';}
}
function historyMethodLabel(method=''){
  return ({PHONE_SCREEN:'Điện thoại / màn hình',FACE_INSIDE_PHONE_SCREEN:'Khuôn mặt trong điện thoại / màn hình',FACE_INSIDE_SCREEN_GEOMETRY:'Khuôn mặt trong khung màn hình / ảnh phẳng',FACE_OVERLAPS_DEVICE:'Khuôn mặt chồng lên thiết bị điện tử',PHOTO:'Ảnh / bề mặt phẳng',LIVENESS_FAILED:'Liveness thất bại',ANTI_SPOOF:'Chống giả mạo'})[String(method||'').toUpperCase()]||'Chống giả mạo';
}
function historyEventMeta(item){
  const type=String(item?.event_type||'').toUpperCase(),cat=String(item?.category||'').toUpperCase(),d=item?.detail||{};
  if(type==='RECOGNIZED'||type==='CHECKIN_SUCCESS')return {title:'Nhận diện thành công',tone:'success',result:'ĐÃ XÁC ĐỊNH',sub:'FaceID + chống giả mạo đạt'};
  if(type==='SPOOF_BLOCKED'||type==='CHECKIN_FAILED')return {title:'Giả mạo bị chặn',tone:'failed',result:'BỊ CHẶN',sub:historyMethodLabel(item.spoof_method)};
  if(type==='UNREGISTERED'||type==='UNKNOWN_PERSON')return {title:'Khách hàng',tone:'warning',result:'KHÁCH HÀNG',sub:'Không có FaceID nhân viên'};
  if(type==='FACE_REGISTER_SUCCESS')return {title:'Đăng ký FaceID',tone:'success',result:'THÀNH CÔNG',sub:`${Number(d.pose_count||0)||'—'} mẫu khuôn mặt`};
  if(type==='FACE_REGISTER_FAILED')return {title:'Đăng ký FaceID',tone:'failed',result:'THẤT BẠI',sub:item.reason||'Không hoàn tất đăng ký'};
  if(type==='PRESENCE_START')return {title:'Bắt đầu hiện diện',tone:'success',result:'CÓ MẶT',sub:d.status==='SEATED'?'Đang ngồi':d.status==='STANDING'?'Đang đứng':'Đã thấy trong khu vực'};
  if(type==='ENTRY')return {title:'Vào văn phòng',tone:'success',result:'IN',sub:d.line_name||'Đường ảo'};
  if(type==='RETURN')return {title:'Quay lại văn phòng',tone:'success',result:'QUAY LẠI',sub:d.line_name||'Đường ảo'};
  if(type==='EXIT')return {title:'Ra ngoài',tone:'warning',result:'OUT',sub:d.line_name||'Đường ảo'};
  if(type==='BACK_IN_VIEW')return {title:'Trở lại vùng quan sát',tone:'info',result:'ĐÃ THẤY LẠI',sub:`Mất dấu ${Math.round(Number(d.absence_sec||0))} giây`};
  if(type==='NOT_VISIBLE')return {title:'Tạm mất khỏi vùng quan sát',tone:'warning',result:'KHÔNG THẤY',sub:'Chưa kết luận đã ra ngoài'};
  if(type==='PRESENCE_END')return {title:'Kết thúc phiên hiện diện',tone:'info',result:'KẾT THÚC',sub:d.reason==='CAMERA_NOT_VISIBLE'?'Không thấy trong thời gian dài':(d.reason||'')};
  if(type==='STATUS_CHANGE'){const m={SEATED:'Ngồi',STANDING:'Đứng',PRESENT:'Có mặt'};return {title:'Thay đổi trạng thái',tone:'info',result:m[String(d.to_status||'').toUpperCase()]||String(d.to_status||'').toUpperCase(),sub:`${m[String(d.from_status||'').toUpperCase()]||d.from_status||'—'} → ${m[String(d.to_status||'').toUpperCase()]||d.to_status||'—'}`};}
  if(cat==='CLASSROOM')return {title:item.action||'Hoạt động khu vực làm việc',tone:'info',result:'ĐÃ GHI NHẬN',sub:item.track_id||''};
  return {title:type||cat||'Sự kiện',tone:String(item?.status||'').toUpperCase()==='FAILED'?'failed':'info',result:String(item?.status||'INFO'),sub:item.reason||''};
}
function historyDatePass(item){
  const start=$('#v22HistoryStart')?.value||'',end=$('#v22HistoryEnd')?.value||'',cls=$('#v20HistoryClass')?.value||'',q=($('#v22HistorySearch')?.value||'').trim().toLowerCase();
  const d=item?.event_at?new Date(item.event_at):null;const day=d&&!Number.isNaN(d.getTime())?localDateInput(d):'';
  if(start&&day<start)return false;if(end&&day>end)return false;if(cls&&item.class_name!==cls)return false;
  if(q&&!`${item.student_code||''} ${item.full_name||''} ${item.action||''} ${item.reason||''} ${item.event_type||''}`.toLowerCase().includes(q))return false;
  return true;
}
function historyTabPass(item){
  const tab=String(state.historyTab||'ALL').toUpperCase(),type=String(item?.event_type||'').toUpperCase();
  if(tab==='ALL')return true;
  if(state.historyMode==='RECOGNITION'){
    if(tab==='SUCCESS')return type==='RECOGNIZED'||type==='CHECKIN_SUCCESS';
    if(tab==='UNREGISTERED')return type==='UNREGISTERED'||type==='UNKNOWN_PERSON';
    if(tab==='SECURITY')return type==='SPOOF_BLOCKED'||type==='CHECKIN_FAILED'||!!item.spoof_method;
    if(tab==='FACEID')return type.startsWith('FACE_');
    return true;
  }
  if(tab==='PRESENCE')return ['PRESENCE_START','PRESENCE_END'].includes(type);
  if(tab==='GATE')return ['ENTRY','RETURN','EXIT'].includes(type);
  if(tab==='STATUS')return type==='STATUS_CHANGE';
  if(tab==='VISIBILITY')return ['NOT_VISIBLE','BACK_IN_VIEW'].includes(type);
  return true;
}
function renderHistoryHourlyInto(hostSel,totalSel,items){
  const host=$(hostSel);if(!host)return;
  const hours=Array.from({length:12},(_,i)=>i+7),counts=new Map(hours.map(h=>[h,0]));
  const today=localDateInput();let total=0;
  items.forEach(x=>{const d=new Date(x.event_at);if(Number.isNaN(d.getTime())||localDateInput(d)!==today)return;const h=d.getHours();if(counts.has(h)){counts.set(h,counts.get(h)+1);total++;}});
  const max=Math.max(1,...counts.values());host.innerHTML=hours.map(h=>{const n=counts.get(h)||0;const height=Math.max(n?8:3,Math.round((n/max)*100));return `<div class="prod-hour-col"><div class="prod-hour-bar-wrap"><i class="prod-hour-bar" style="height:${height}%"></i></div><b>${n}</b><span>${String(h).padStart(2,'0')}h</span></div>`}).join('');
  if($(totalSel))$(totalSel).textContent=`${total} sự kiện`;
}
function setHistoryModeUi(){
  const hr=state.historyMode==='HR';
  $$('#historyModeTabs [data-history-mode]').forEach(b=>b.classList.toggle('active',(b.dataset.historyMode||'RECOGNITION')===state.historyMode));
  $('#historyRecognitionWorkspace')?.classList.toggle('hidden',hr);
  $('#historyHrWorkspace')?.classList.toggle('hidden',!hr);
  if($('#historySectionEyebrow'))$('#historySectionEyebrow').textContent=hr?'LỊCH SỬ NHÂN SỰ':'LỊCH SỬ NHẬN DIỆN';
  if($('#historySectionTitle'))$('#historySectionTitle').textContent=hr?'Theo dõi nhân sự 24/7':'Nhận diện';
  if($('#historySectionDesc'))$('#historySectionDesc').textContent=hr?'AI quan sát liên tục nhưng database chỉ lưu Event + Session có ý nghĩa; trạng thái realtime không tạo log theo frame.':'FaceID chỉ lưu các sự kiện cần kiểm tra; nhận diện lặp trong cùng phiên hiện diện được hạn chế để giảm dữ liệu.';
}
function formatDurationSeconds(sec){
  const n=Math.max(0,Math.round(Number(sec||0)));const h=Math.floor(n/3600),m=Math.floor((n%3600)/60),ss=n%60;
  if(h)return `${h}h ${m}m`;if(m)return `${m}m ${ss}s`;return `${ss}s`;
}
function historyRecognitionTabPass(item){
  const tab=String(state.historyRecognitionTab||'ALL').toUpperCase(),type=String(item?.event_type||'').toUpperCase();
  if(tab==='ALL')return true;if(tab==='SUCCESS')return ['RECOGNIZED','CHECKIN_SUCCESS'].includes(type);if(tab==='UNREGISTERED')return ['UNREGISTERED','UNKNOWN_PERSON'].includes(type);if(tab==='SECURITY')return ['SPOOF_BLOCKED','CHECKIN_FAILED'].includes(type)||!!item.spoof_method;if(tab==='FACEID')return type.startsWith('FACE_');return true;
}
function historyHrTabPass(item){
  const type=String(item?.event_type||'').toUpperCase();
  return ['PRESENCE_START','PRESENCE_END','ENTRY','RETURN','EXIT'].includes(type);
}
function setHrHistoryView(view='EVENTS'){
  const next=['EVENTS','SESSIONS','SUMMARY'].includes(String(view).toUpperCase())?String(view).toUpperCase():'EVENTS';
  state.historyHrTab=next;
  $$('#historyHrTabs [data-history-tab]').forEach(b=>b.classList.toggle('active',String(b.dataset.historyTab||'').toUpperCase()===next));
  $('#historyHrEventsPanel')?.classList.toggle('hidden',next!=='EVENTS');
  $('#historySessionsPanel')?.classList.toggle('hidden',next!=='SESSIONS');
  $('#historyHrSummaryPanel')?.classList.toggle('hidden',next!=='SUMMARY');
}
function renderRecognitionHistory(){
  const base=(state.historyRecognitionFeed||[]).filter(historyDatePass);
  const success=base.filter(x=>['RECOGNIZED','CHECKIN_SUCCESS'].includes(String(x.event_type||'').toUpperCase()));
  const failed=base.filter(x=>['SPOOF_BLOCKED','CHECKIN_FAILED'].includes(String(x.event_type||'').toUpperCase()));
  const enroll=base.filter(x=>String(x.event_type||'').toUpperCase()==='FACE_REGISTER_SUCCESS');
  const review=base.filter(x=>String(x.event_type||'').toUpperCase()==='RECOGNITION_REVIEW'||String(x.event_type||'').toUpperCase()==='FACE_REGISTER_FAILED');
  const unknown=base.filter(x=>['UNREGISTERED','UNKNOWN_PERSON'].includes(String(x.event_type||'').toUpperCase()));
  if($('#recHistorySuccess'))$('#recHistorySuccess').textContent=String(success.length);
  if($('#recHistorySpoof'))$('#recHistorySpoof').textContent=String(failed.length);
  if($('#recHistoryEnroll'))$('#recHistoryEnroll').textContent=String(enroll.length);
  if($('#recHistoryReview'))$('#recHistoryReview').textContent=String(review.length);
  if($('#recHistoryUnknown'))$('#recHistoryUnknown').textContent=String(unknown.length);
  const methods={PHONE_SCREEN:0,PHOTO:0,LIVENESS_FAILED:0,OTHER:0};failed.forEach(x=>{const m=String(x.spoof_method||'').toUpperCase();if(m==='PHONE_SCREEN')methods.PHONE_SCREEN++;else if(m==='PHOTO')methods.PHOTO++;else if(m==='LIVENESS_FAILED')methods.LIVENESS_FAILED++;else methods.OTHER++;});
  if($('#recHistoryPhoneScreen'))$('#recHistoryPhoneScreen').textContent=String(methods.PHONE_SCREEN);if($('#recHistoryPhotoSpoof'))$('#recHistoryPhotoSpoof').textContent=String(methods.PHOTO);if($('#recHistoryLivenessFailed'))$('#recHistoryLivenessFailed').textContent=String(methods.LIVENESS_FAILED);if($('#recHistoryOtherSpoof'))$('#recHistoryOtherSpoof').textContent=String(methods.OTHER);
  renderHistoryHourlyInto('#recHistoryHourlyChart','#recHistoryTodayTotal',base);
  const view=base.filter(historyRecognitionTabPass);state.historyRecognitionView=view;if(state.historyMode==='RECOGNITION'){state.historyView=view;state.historyTab=state.historyRecognitionTab;}
  if($('#recognitionHistoryCount'))$('#recognitionHistoryCount').textContent=String(view.length);
  const body=$('#historyRecognitionBody');if(body)body.innerHTML=view.length?view.slice(0,500).map((x,i)=>historyRowHtml(x,'RECOGNITION',i)).join(''):'<tr><td colspan="6" class="empty-card">Không có sự kiện nhận diện phù hợp bộ lọc.</td></tr>';
}
function renderHistoryCurrentPresence(){
  const host=$('#historyCurrentPresence'),sessionRows=state.historyHrCurrent||[],live=state.historyHrRealtime||[];if(!host)return;
  const liveMap=new Map(live.map(x=>[Number(x.student_id),x]));
  const rows=sessionRows.map(x=>({...x,realtime:liveMap.get(Number(x.student_id))||null}));
  if($('#historyCurrentCount'))$('#historyCurrentCount').textContent=String(rows.filter(x=>x.realtime?.visible!==false).length);
  if(!rows.length){host.innerHTML='<div class="empty-card">Chưa có nhân viên đang hiện diện.</div>';return;}
  host.innerHTML=rows.slice(0,24).map(x=>{
    const elapsed=x.started_at?Math.max(0,Math.floor((Date.now()-new Date(x.started_at).getTime())/1000)):0,r=x.realtime||{},visible=r.visible!==false,obs=visible?'ĐANG QUAN SÁT':'TẠM NGOÀI KHUNG';
    return `<div class="history-current-person ${visible?'':'is-lost'}"><div><b>${escapeHtml(x.full_name||'—')}</b><small>${escapeHtml(x.student_code||'—')} · ${escapeHtml(x.class_name||'Chưa phân bộ phận')}</small><em>${escapeHtml(obs)}${!visible&&r.missing_sec!=null?` · ${Math.round(Number(r.missing_sec||0))}s`:''}</em></div><span>${formatDurationSeconds(elapsed)}</span></div>`
  }).join('');
}
function renderHistorySessions(){
  const body=$('#historySessionsBody');if(!body)return;
  const start=$('#v22HistoryStart')?.value||'',end=$('#v22HistoryEnd')?.value||'',cls=$('#v20HistoryClass')?.value||'',q=($('#v22HistorySearch')?.value||'').trim().toLowerCase();
  const rows=(state.historyHrSessions||[]).filter(x=>{const d=x.started_at?new Date(x.started_at):null,day=d&&!Number.isNaN(d.getTime())?localDateInput(d):'';if(start&&day<start)return false;if(end&&day>end)return false;if(cls&&x.class_name!==cls)return false;if(q&&!`${x.student_code||''} ${x.full_name||''} ${x.end_reason||''}`.toLowerCase().includes(q))return false;return true;});
  if($('#historySessionCount'))$('#historySessionCount').textContent=String(rows.length);
  const today=localDateInput();const sessionsToday=rows.filter(x=>{const d=x.started_at?new Date(x.started_at):null;return d&&!Number.isNaN(d.getTime())&&localDateInput(d)===today;}).length;if($('#hrHistorySessionsToday'))$('#hrHistorySessionsToday').textContent=String(sessionsToday);
  const reasonLabel=x=>({VIRTUAL_GATE_OUT:'Qua đường ảo OUT',CAMERA_NOT_VISIBLE:'Legacy: mất camera',MANUAL:'Thủ công',SYSTEM_RESTART:'Hệ thống khởi động lại'})[String(x||'').toUpperCase()]||x||'Đang mở';
  body.innerHTML=rows.length?rows.slice(0,300).map(x=>`<tr><td><div class="prod-history-person"><b>${escapeHtml(x.full_name||'—')}</b><small>${escapeHtml(x.student_code||'—')}</small></div></td><td>${formatDate(x.started_at)}</td><td>${x.ended_at?formatDate(x.ended_at):'<span class="prod-status success">ĐANG CÓ MẶT</span>'}</td><td>${x.ended_at?formatDurationSeconds(x.duration_sec):'Đang tính'}</td><td>${escapeHtml(reasonLabel(x.end_reason))}</td></tr>`).join(''):'<tr><td colspan="5" class="empty-card">Chưa có phiên hiện diện phù hợp bộ lọc.</td></tr>';
}
function renderHrDailySummary(){
  const body=$('#historyHrSummaryBody');if(!body)return;
  const start=$('#v22HistoryStart')?.value||'',end=$('#v22HistoryEnd')?.value||'',cls=$('#v20HistoryClass')?.value||'',q=($('#v22HistorySearch')?.value||'').trim().toLowerCase();
  const rows=(state.historyHrDailySummary||[]).filter(x=>{if(start&&String(x.date||'')<start)return false;if(end&&String(x.date||'')>end)return false;if(cls&&x.class_name!==cls)return false;if(q&&!`${x.student_code||''} ${x.full_name||''}`.toLowerCase().includes(q))return false;return true;});
  if($('#historyHrSummaryCount'))$('#historyHrSummaryCount').textContent=String(rows.length);
  body.innerHTML=rows.length?rows.slice(0,400).map(x=>`<tr><td><div class="prod-history-person"><b>${escapeHtml(x.full_name||'—')}</b><small>${escapeHtml(x.student_code||'—')} · ${escapeHtml(x.class_name||'—')}</small></div></td><td>${escapeHtml(x.date||'—')}</td><td>${formatDurationSeconds(x.presence_sec)}</td><td>${formatDurationSeconds(x.outside_sec)}</td><td>${Number(x.session_count||0)}</td><td>${Number(x.exit_count||0)}</td><td>${x.first_seen?formatDate(x.first_seen):'—'}<br><small>${x.last_seen?formatDate(x.last_seen):'—'}</small></td></tr>`).join(''):'<tr><td colspan="7" class="empty-card">Chưa có dữ liệu tổng hợp phù hợp bộ lọc.</td></tr>';
}
function renderHrPolicy(){
  const p=state.historyHrPolicy||{},gate=!!p.virtual_gate_enabled,el=$('#historyHrAuthority');if(!el)return;
  el.className=`history-policy-chip ${gate?'good':'warn'}`;
  el.textContent=gate?'OUT/IN XÁC NHẬN BỞI VIRTUAL GATE':'CHƯA BẬT GATE · KHÔNG SUY DIỄN OUT';
  const note=$('#historyHrAuthorityNote');if(note)note.textContent=gate?'Phiên hiện diện dùng Virtual Gate làm căn cứ ra/vào.':'Camera mất dấu chỉ là trạng thái kỹ thuật; hệ thống không tự kết luận nhân viên đã ra ngoài.';
}
function renderHrHistory(){
  const base=(state.historyHrFeed||[]).filter(historyDatePass),current=Number(state.historyHrSummary?.currently_present||0),exit=base.filter(x=>x.event_type==='EXIT').length,entry=base.filter(x=>['ENTRY','RETURN'].includes(x.event_type)).length;
  const today=localDateInput(),todayPresence=(state.historyHrDailySummary||[]).filter(x=>String(x.date||'')===today).reduce((n,x)=>n+Number(x.presence_sec||0),0);
  if($('#hrHistoryPresent'))$('#hrHistoryPresent').textContent=String(current);if($('#hrHistoryExit'))$('#hrHistoryExit').textContent=String(exit);if($('#hrHistoryEntry'))$('#hrHistoryEntry').textContent=String(entry);if($('#hrHistoryPresenceTime'))$('#hrHistoryPresenceTime').textContent=formatDurationSeconds(todayPresence);
  renderHrPolicy();renderHistoryCurrentPresence();renderHistorySessions();renderHrDailySummary();setHrHistoryView(state.historyHrTab||'EVENTS');
  const view=base.filter(historyHrTabPass);state.historyHrView=view;if(state.historyMode==='HR'){state.historyView=view;state.historyTab=state.historyHrTab;}
  if($('#hrHistoryEventCount'))$('#hrHistoryEventCount').textContent=String(view.length);
  const body=$('#historyHrBody');if(body)body.innerHTML=view.length?view.slice(0,500).map((x,i)=>historyRowHtml(x,'HR',i)).join(''):'<tr><td colspan="6" class="empty-card">Chưa có sự kiện nghiệp vụ phù hợp bộ lọc.</td></tr>';
}
function historyRowHtml(x,mode,index){
  const meta=historyEventMeta(x),person=x.full_name||'Chưa xác định',code=x.student_code||x.class_name||'';let detail=x.reason||meta.sub||x.action||'—';const repeats=Number(x.repeat_count||1);if(repeats>1)detail=`${detail} · Đã gộp ${repeats} lần lặp`;
  return `<tr><td>${formatDate(x.event_at)}</td><td><div class="prod-history-person"><b>${escapeHtml(person)}</b><small>${escapeHtml(code||'—')}</small></div></td><td><span class="prod-event-title">${escapeHtml(meta.title)}</span><span class="prod-event-sub">${escapeHtml(meta.sub||'')}</span></td><td><span class="prod-status ${meta.tone}">${escapeHtml(meta.result)}</span></td><td>${escapeHtml(detail)}</td><td><button class="prod-detail-btn" type="button" onclick="showHistoryDetail('${mode}',${index})">Chi tiết</button></td></tr>`;
}
function renderHistoryDashboard(){setHistoryModeUi();renderRecognitionHistory();renderHrHistory();}
window.showHistoryDetail=(mode,index)=>{
  const source=mode==='HR'?(state.historyHrView||[]):(state.historyRecognitionView||[]),x=source[Number(index)];if(!x)return;const meta=historyEventMeta(x);if($('#historyDetailTitle'))$('#historyDetailTitle').textContent=meta.title;
  const rows=[['Kết quả',meta.result],['Thời gian',formatDate(x.event_at)],['Họ tên',x.full_name||'—'],['Mã nhân viên',x.student_code||'—'],['Bộ phận',x.class_name||'—'],['Camera',x.camera_source||cameraPresetLabel(state.cameraPreset)||'—']];
  if(x.confidence!=null)rows.push(['Độ khớp FaceID',`${pct(x.confidence)}%`]);if(x.liveness_score!=null)rows.push(['Anti-spoof',`${Math.round(Number(x.liveness_score||0)*100)}%`]);if(x.spoof_method)rows.push(['Phương thức bị chặn',historyMethodLabel(x.spoof_method)]);if(x.action)rows.push(['Trạng thái',x.action]);if(x.reason)rows.push(['Lý do',x.reason]);if(x.track_id)rows.push(['Track',x.track_id]);const d=x.detail||{};if(d.from_status||d.to_status)rows.push(['Chuyển trạng thái',`${d.from_status||'—'} → ${d.to_status||'—'}`]);if(d.absence_sec!=null)rows.push(['Thời gian không thấy',`${Math.round(Number(d.absence_sec||0))} giây`]);if(d.session_id)rows.push(['Phiên hiện diện',`#${d.session_id}`]);if(d.line_name)rows.push(['Đường ảo',d.line_name]);
  const snap=String(x.snapshot_url||x.best_snapshot||(x.detail||{}).best_snapshot||'').trim(),previewWrap=$('#historyDetailPreviewWrap'),previewImg=$('#historyDetailPreview'),previewEmpty=$('#historyDetailPreviewEmpty');
  if(previewWrap&&previewImg&&previewEmpty){
    previewWrap.classList.remove('hidden');
    previewImg.onload=()=>{previewImg.classList.remove('hidden');previewEmpty.classList.add('hidden');};
    previewImg.onerror=()=>{previewImg.removeAttribute('src');previewImg.classList.add('hidden');previewEmpty.classList.remove('hidden');};
    if(snap){previewImg.classList.add('hidden');previewEmpty.classList.remove('hidden');previewImg.src=snap;}else{previewImg.removeAttribute('src');previewImg.classList.add('hidden');previewEmpty.classList.remove('hidden');}
  }
  if($('#historyDetailContent'))$('#historyDetailContent').innerHTML=rows.map(([a,b])=>`<div class="prod-detail-row"><span>${escapeHtml(a)}</span><b>${escapeHtml(b)}</b></div>`).join('');$('#historyDetailModal')?.classList.remove('hidden');
};
function closeHistoryDetail(){$('#historyDetailModal')?.classList.add('hidden');if($('#historyDetailPreview'))$('#historyDetailPreview').removeAttribute('src');}
function exportHistoryCsv(){
  const rows=state.historyMode==='HR'?(state.historyHrView||[]):(state.historyRecognitionView||[]);if(!rows.length){toast('Không có dữ liệu để xuất.',true);return;}let table=[];
  if(state.historyMode==='HR'){const head=['Thời gian','Họ tên','Mã nhân viên','Bộ phận','Sự kiện','Kết quả','Track','Chi tiết'];table=[head,...rows.map(x=>{const m=historyEventMeta(x);return [formatDate(x.event_at),x.full_name||'',x.student_code||'',x.class_name||'',m.title,m.result,x.track_id||'',x.reason||m.sub||'']})];}
  else{const head=['Thời gian','Họ tên','Mã nhân viên','Bộ phận','Sự kiện','Kết quả','Độ khớp','Anti-spoof','Lý do'];table=[head,...rows.map(x=>{const m=historyEventMeta(x);return [formatDate(x.event_at),x.full_name||'',x.student_code||'',x.class_name||'',m.title,m.result,x.confidence==null?'':pct(x.confidence)+'%',x.liveness_score==null?'':Math.round(Number(x.liveness_score||0)*100)+'%',x.reason||m.sub||'']})];}
  const csv=table.map(r=>r.map(v=>`"${String(v??'').replaceAll('"','""')}"`).join(',')).join('\r\n'),blob=new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`CampusFace_${state.historyMode==='HR'?'HR_History':'Recognition_History'}_${localDateInput()}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function loadHistory(){
  if(window.BTMHDemoReports)return window.BTMHDemoReports.start();
  try{const [rec,hr]=await Promise.all([api('/api/v1/history/recognition?limit=1200'),api('/api/v1/history/hr?limit=1200')]);state.historyRecognitionFeed=rec.items||[];state.historyHrFeed=hr.items||[];state.historyHrSessions=hr.sessions||[];state.historyHrSummary=hr.summary||{};state.historyHrCurrent=hr.current||[];state.historyHrRealtime=hr.realtime||[];state.historyHrDailySummary=hr.daily_summary||[];state.historyHrPolicy=hr.policy||{};
    const classEl=$('#v20HistoryClass');if(classEl){const old=classEl.value;const classes=[...new Set(state.students.map(s=>s.class_name).filter(Boolean))].sort();classEl.innerHTML='<option value="">Tất cả bộ phận</option>'+classes.map(x=>`<option>${escapeHtml(x)}</option>`).join('');if(classes.includes(old))classEl.value=old;}renderHistoryDashboard();
  }catch(e){toast(e.message,true)}
}

function attendanceStatusLabel(v=''){
  const x=String(v||'').toUpperCase();return ({ACTIVE:'Đang diễn ra',SCHEDULED:'Sắp diễn ra',ENDED:'Đã kết thúc',CLOSED:'Đã đóng',PRESENT:'Có mặt',LATE:'Đi muộn',ABSENT:'Chưa có mặt',EXCUSED:'Vắng có phép',EARLY_LEAVE:'Về sớm'})[x]||x||'—';
}
function isoFromLocalInput(sel){const v=$(sel)?.value||'';if(!v)return '';const d=new Date(v);return Number.isNaN(d.getTime())?'':d.toISOString();}
function setAttendanceDefaults(){
  const now=new Date(),end=new Date(now.getTime()+2*60*60*1000);const fmt=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  if($('#attendanceStart')&&!$('#attendanceStart').value)$('#attendanceStart').value=fmt(now);if($('#attendanceEnd')&&!$('#attendanceEnd').value)$('#attendanceEnd').value=fmt(end);
}
function fillAttendanceClasses(){
  const el=$('#attendanceClass');if(!el)return;const old=el.value,classes=[...new Set((state.students||[]).map(s=>s.class_name).filter(Boolean))].sort();el.innerHTML='<option value="">Tất cả nhân viên</option>'+classes.map(x=>`<option value="${escapeHtml(x)}">${escapeHtml(x)}</option>`).join('');if(classes.includes(old))el.value=old;
}
function renderAttendanceSessions(){
  const body=$('#attendanceSessionsBody');if(!body)return;const rows=state.attendanceSessions||[];
  body.innerHTML=rows.length?rows.map(x=>{const q=x.summary||{},done=Number(q.present||0)+Number(q.late||0)+Number(q.excused||0)+Number(q.early_leave||0),total=Number(q.total||0),pctDone=total?Math.round(done*100/total):0,status=String(x.status||'').toLowerCase();return `<tr><td><div class="pr-session-name"><b>${escapeHtml(x.name)}</b><small>${escapeHtml(x.room_name||'Chưa đặt phòng')}</small></div></td><td>${escapeHtml(x.class_name||'Tất cả')}</td><td>${formatDate(x.start_at)}<br><small>${formatDate(x.end_at)}</small></td><td><span class="pr-badge ${status}">${attendanceStatusLabel(x.status)}</span></td><td><div class="pr-progress"><i style="width:${pctDone}%"></i></div><small>${done}/${total}</small></td><td><div class="pr-row-actions"><button type="button" onclick="selectAttendanceSession(${x.id})">Chi tiết</button></div></td></tr>`}).join(''):'<tr><td colspan="6" class="empty-card">Chưa có phiên hiện diện.</td></tr>';
}
function renderAttendanceSummary(s){const q=s?.summary||{};[['#attTotal','total'],['#attPresent','present'],['#attLate','late'],['#attAbsent','absent'],['#attRejected','rejected_attempts']].forEach(([sel,k])=>{if($(sel))$(sel).textContent=String(q[k]||0)});}

async function selectAttendanceSession(id){
  state.attendanceSessionId=Number(id)||null;if(!state.attendanceSessionId)return;
  try{
    const data=await api(`/api/v1/attendance/sessions/${state.attendanceSessionId}/ledger`),s=data.session||{},rows=data.items||[];
    renderAttendanceSummary(s);
    if($('#attendanceLedgerTitle'))$('#attendanceLedgerTitle').textContent=`${s.name||'Phiên'} · ${s.class_name||'Tất cả'}`;
    if($('#attendanceExport'))$('#attendanceExport').disabled=false;
    if($('#attendanceClose'))$('#attendanceClose').disabled=String(s.status||'').toUpperCase()==='CLOSED';
    const body=$('#attendanceLedgerBody');
    if(body)body.innerHTML=rows.length?rows.map(r=>{
      const adj=r.manual_adjustment||null;
      const note=adj?`<small class="v12-manual-note">Đã sửa: ${escapeHtml(adj.actor||'')} · ${escapeHtml(adj.reason||'')}</small>`:'';
      return `<tr><td><div class="pr-person"><b>${escapeHtml(r.full_name)}</b><small>${escapeHtml(r.student_code)}</small></div></td><td>${escapeHtml(r.class_name||'—')}</td><td>${formatDate(r.first_checkin_at)}</td><td>${formatDate(r.last_checkin_at)}</td><td><span class="pr-badge ${String(r.final_status||'').toLowerCase()}">${attendanceStatusLabel(r.final_status)}</span>${note}</td><td>${Number(r.attempts||0)}<small style="display:block;color:#789">Re-entry ${Number(r.reentry_count||0)} · Trùng ${Number(r.duplicate_count||0)}</small></td><td>${Number(r.rejected_attempts||0)}</td><td><button class="v12-ledger-adjust" type="button" onclick="openAttendanceAdjust(${Number(r.student_id)},'${String(r.final_status||'ABSENT').replaceAll("'","")}')">Điều chỉnh</button></td></tr>`;
    }).join(''):'<tr><td colspan="8" class="empty-card">Không có nhân viên trong phiên.</td></tr>';
  }catch(e){toast(e.message,true)}
}

window.selectAttendanceSession=selectAttendanceSession;
async function loadAttendancePage(){
  setAttendanceDefaults();if(!(state.students||[]).length)await loadStudents();fillAttendanceClasses();
  try{const data=await api('/api/v1/attendance/sessions?limit=100');state.attendanceSessions=data.items||[];renderAttendanceSessions();let id=state.attendanceSessionId;const exists=state.attendanceSessions.some(x=>Number(x.id)===Number(id));if(!exists){const active=state.attendanceSessions.find(x=>String(x.status).toUpperCase()==='ACTIVE')||state.attendanceSessions[0];id=active?.id||null;}if(id)await selectAttendanceSession(id);else renderAttendanceSummary({summary:{}});}catch(e){toast(e.message,true)}
}
async function createAttendanceSession(ev){
  ev.preventDefault();try{const payload={name:$('#attendanceName').value.trim(),class_name:$('#attendanceClass').value||'',room_name:$('#attendanceRoom').value.trim(),start_at:isoFromLocalInput('#attendanceStart'),end_at:isoFromLocalInput('#attendanceEnd'),grace_minutes:Number($('#attendanceGrace').value||5)};const s=await api('/api/v1/attendance/sessions',{method:'POST',body:JSON.stringify(payload)});toast('Đã tạo phiên hiện diện.');state.attendanceSessionId=s.id;await loadAttendancePage();}catch(e){toast(e.message,true)}
}
async function closeAttendanceSession(){if(!state.attendanceSessionId)return;if(!confirm('Đóng phiên hiện diện này?'))return;try{await api(`/api/v1/attendance/sessions/${state.attendanceSessionId}/close`,{method:'POST'});toast('Đã đóng phiên.');await loadAttendancePage();}catch(e){toast(e.message,true)}}
async function downloadAuthed(url,filename){const token=localStorage.getItem('campusface_token')||'';const r=await fetch(url,{headers:token?{'Authorization':`Bearer ${token}`}:{}});if(!r.ok){let m='Không tải được file';try{const j=await r.json();m=j.detail||m}catch(_){}throw new Error(m)}const b=await r.blob(),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=filename||'download';document.body.appendChild(a);a.click();setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove()},500);}
async function exportAttendanceSession(){if(!state.attendanceSessionId)return;try{await downloadAuthed(`/api/v1/attendance/sessions/${state.attendanceSessionId}/export.csv`,`BTMH-Session-${state.attendanceSessionId}.csv`)}catch(e){toast(e.message,true)}}


function closeAttendanceAdjust(){
  $('#attendanceAdjustModal')?.classList.add('hidden');state.attendanceAdjustStudentId=null;
}
window.openAttendanceAdjust=(studentId,status='ABSENT')=>{
  state.attendanceAdjustStudentId=Number(studentId)||null;
  const name=(state.students||[]).find(x=>Number(x.id)===Number(studentId))?.full_name||'Nhân viên';
  if($('#attendanceAdjustStudentId'))$('#attendanceAdjustStudentId').value=String(studentId||'');
  if($('#attendanceAdjustTitle'))$('#attendanceAdjustTitle').textContent=`Điều chỉnh · ${name||'Nhân viên'}`;
  if($('#attendanceAdjustStatus'))$('#attendanceAdjustStatus').value=['PRESENT','LATE','ABSENT','EXCUSED','EARLY_LEAVE'].includes(String(status).toUpperCase())?String(status).toUpperCase():'ABSENT';
  if($('#attendanceAdjustReason'))$('#attendanceAdjustReason').value='';
  $('#attendanceAdjustModal')?.classList.remove('hidden');
};
async function submitAttendanceAdjust(ev){
  ev.preventDefault();
  const sid=Number(state.attendanceSessionId||0),studentId=Number(state.attendanceAdjustStudentId||$('#attendanceAdjustStudentId')?.value||0);
  if(!sid||!studentId){toast('Chưa chọn phiên hoặc nhân viên.',true);return;}
  try{
    await api(`/api/v1/attendance/sessions/${sid}/records/${studentId}`,{method:'PUT',body:JSON.stringify({status:$('#attendanceAdjustStatus').value,reason:$('#attendanceAdjustReason').value.trim()})});
    toast('Đã lưu điều chỉnh và Audit Log.');closeAttendanceAdjust();await selectAttendanceSession(sid);
  }catch(e){toast(e.message,true)}
}

function exceptionKind(item){
  const st=String(item?.status||'').toUpperCase();
  if(st==='SPOOF_BLOCKED')return {label:'Chống giả mạo',cls:'spoof'};
  if(st==='UNREGISTERED')return {label:'Khách hàng',cls:''};
  return {label:'Độ khớp thấp',cls:'low'};
}
function studentOptions(selected=''){
  return '<option value="">— Chọn nhân viên —</option>'+(state.students||[]).map(s=>`<option value="${Number(s.id)}" ${Number(selected)===Number(s.id)?'selected':''}>${escapeHtml(s.student_code)} · ${escapeHtml(s.full_name)}</option>`).join('');
}
function renderOpsDevices(){
  if(window.BTMHCameraConfiguration)return;
  const host=$('#v12CameraDeviceList');if(!host)return;
  const rows=state.opsDevices||[];
  host.innerHTML=rows.length?rows.map(d=>`<div class="v12-device-row ${String(d.health_status||'').toUpperCase()==='HANDOVER'?'is-handover':''}"><div class="v12-device-main"><b>${escapeHtml(d.name||'Camera')}</b><small>${escapeHtml(d.source_display||d.source||'—')} · ${escapeHtml(d.resolution||'—')} @ ${Number(d.target_fps||0)} FPS</small></div><div class="v12-device-meta"><b>${escapeHtml(d.zone_name||'Chưa gán khu vực')}</b><small>${escapeHtml(d.camera_type||'USB')}</small></div><div class="v12-device-tags"><span class="v12-tag ${d.active?'active':''}">${escapeHtml(d.health_status|| (d.active?'ĐANG DÙNG':'STANDBY'))}</span>${d.ptz_enabled?'<span class="v12-tag ptz">PTZ</span>':''}</div><div class="v12-device-actions"><button class="primary" type="button" onclick="activateOpsCamera(${Number(d.id)})" ${String(d.health_status||'').toUpperCase()==='HANDOVER'?'disabled':''}>${d.active?'Đang dùng':'Dùng camera'}</button>${d.active?'':`<button class="danger" type="button" onclick="deleteOpsCamera(${Number(d.id)})">Xóa</button>`}</div></div>`).join(''):'<div class="empty-card">Chưa khai báo camera.</div>';
}
async function loadOpsDevices(){
  if(window.BTMHCameraConfiguration)return window.BTMHCameraConfiguration.refresh();
  const d=await api('/api/v1/cameras/devices');state.opsDevices=d.items||[];renderOpsDevices();const runtime=d.runtime||{},handover=runtime.handover||{};setCameraHandoverUi(!!(runtime.handover_active||handover.active),handover);
}
window.activateOpsCamera=async(id)=>{const target=(state.opsDevices||[]).find(x=>Number(x.id)===Number(id));setCameraHandoverUi(true,{state:'CHECKING',from_label:(state.opsDevices||[]).find(x=>x.active)?.name||'',to_label:target?.name||'camera',message:`Đang chuyển sang ${target?.name||'camera'}`});try{const d=await api(`/api/v1/cameras/devices/${Number(id)}/activate`,{method:'POST'});if(d.ok!==false)document.dispatchEvent(new CustomEvent('btmh:camera-source-changed'));setCameraHandoverUi(false,d.runtime?.handover||{state:'READY',message:`${d.device?.name||'Camera'} đã sẵn sàng`});toast(`Đã chuyển an toàn sang ${d.device?.name||'camera'}.`);await Promise.all([loadOpsDevices(),loadCameraSettings(),loadHealth()]);}catch(e){toast(e.message,true);setCameraHandoverUi(false,{state:'KEPT_PREVIOUS',message:e.message});try{await Promise.all([loadOpsDevices(),loadCameraSettings(),loadHealth()]);}catch(_){}}};
window.deleteOpsCamera=async(id)=>{if(!confirm('Xóa camera này khỏi danh mục?'))return;try{await api(`/api/v1/cameras/devices/${Number(id)}`,{method:'DELETE'});toast('Đã xóa camera khỏi danh mục.');await loadOpsDevices();}catch(e){toast(e.message,true)}};
async function createOpsCamera(ev){
  ev.preventDefault();
  try{
    await api('/api/v1/cameras/devices',{method:'POST',body:JSON.stringify({name:$('#v12DeviceName').value.trim(),source:$('#v12DeviceSource').value.trim(),camera_type:$('#v12DeviceType').value,zone_name:$('#v12DeviceZone').value.trim(),resolution:'1920x1080',target_fps:30,ptz_enabled:$('#v12DevicePtz').checked,enabled:true,notes:''})});
    toast('Đã thêm camera.');ev.target.reset();await loadOpsDevices();
  }catch(e){toast(e.message,true)}
}
function renderOpsRules(r={}){
  if($('#v12DuplicateSeconds'))$('#v12DuplicateSeconds').value=r.duplicate_window_seconds??45;
  if($('#v12ReentryMinutes'))$('#v12ReentryMinutes').value=r.reentry_gap_minutes??10;
  if($('#v12LowConfidence'))$('#v12LowConfidence').value=r.exception_low_confidence??0.72;
  if($('#v12EvidenceRetention'))$('#v12EvidenceRetention').value=r.evidence_retention_days??30;
  if($('#v12EvidenceDays'))$('#v12EvidenceDays').textContent=`${r.evidence_retention_days??30} ngày`;
}
async function saveOpsRules(ev){
  ev.preventDefault();
  try{const d=await api('/api/v1/operations/rules',{method:'PUT',body:JSON.stringify({duplicate_window_seconds:Number($('#v12DuplicateSeconds').value||45),reentry_gap_minutes:Number($('#v12ReentryMinutes').value||10),exception_low_confidence:Number($('#v12LowConfidence').value||0.72),evidence_retention_days:Number($('#v12EvidenceRetention').value||30)})});renderOpsRules(d.rules||{});toast('Đã lưu quy tắc nghiệp vụ.');await loadOpsExceptions();}catch(e){toast(e.message,true)}
}
function renderOpsExceptions(){
  const host=$('#v12ExceptionList');if(!host)return;const rows=state.opsExceptions||[];
  host.innerHTML=rows.length?rows.map(x=>{
    const k=exceptionKind(x),snap=x.snapshot_url||'',id=Number(x.id),count=Math.max(1,Number(x.observation_count||x.repeat_count||1));
    const first=x.first_seen||x.event_at,last=x.last_seen||x.event_at,timeMeta=first&&last&&first!==last?`${formatDate(first)} → ${formatDate(last)}`:formatDate(last);
    return `<article class="v12-exception-card"><div class="v12-exception-image">${snap?`<img src="${snap}" alt="Ảnh case xác minh" onerror="this.style.display='none';this.parentElement.textContent='Không mở được ảnh'">`:'Không có ảnh'}</div><div><div class="v12-exception-top"><div><b>${escapeHtml(x.full_name||'Chưa xác định')}</b><small>${escapeHtml(x.student_code||x.track_id||'—')} · ${escapeHtml(timeMeta)}</small></div><span class="v12-exception-status ${k.cls}">${k.label}</span></div><div class="v12-exception-info"><span>Quan sát <b>${count}</b></span><span>FaceID <b>${pct(x.confidence)}%</b></span><span>Anti-spoof <b>${Math.round(Number(x.liveness_score||0)*100)}%</b></span><span>Camera <b>${escapeHtml(x.camera_source||'—')}</b></span></div><select id="v12ResolveStudent-${id}">${studentOptions(x.resolved_student_id)}</select><textarea id="v12ResolveNote-${id}" placeholder="Ghi chú xác minh">${escapeHtml(x.note||'')}</textarea><div class="v12-exception-actions"><button class="confirm" type="button" onclick="reviewOpsException(${id},'CONFIRMED_IDENTITY')">Xác nhận danh tính</button><button class="unknown" type="button" onclick="reviewOpsException(${id},'MARKED_UNKNOWN')">Khách / chưa đăng ký</button><button class="dismiss" type="button" onclick="reviewOpsException(${id},'DISMISSED')">Bỏ qua</button></div></div></article>`
  }).join(''):'<div class="empty-card">Không có case đang chờ xử lý.</div>';
}
async function loadOpsExceptions(){
  const decision=$('#v12ExceptionFilter')?.value||'PENDING';const d=await api(`/api/v1/exceptions?limit=80&decision=${encodeURIComponent(decision)}`);state.opsExceptions=d.items||[];renderOpsExceptions();if(d.rules)renderOpsRules(d.rules);
}
window.reviewOpsException=async(eventId,decision)=>{
  const select=$(`#v12ResolveStudent-${Number(eventId)}`),note=$(`#v12ResolveNote-${Number(eventId)}`);
  const studentId=Number(select?.value||0)||null;
  if(decision==='CONFIRMED_IDENTITY'&&!studentId){toast('Chọn nhân viên trước khi xác nhận danh tính.',true);return;}
  try{await api(`/api/v1/exceptions/${Number(eventId)}`,{method:'PUT',body:JSON.stringify({decision,resolved_student_id:studentId,note:note?.value?.trim()||''})});toast('Đã lưu quyết định xác minh.');await Promise.all([loadOpsExceptions(),loadOpsSummary()]);}catch(e){toast(e.message,true)}
};
async function loadOpsSummary(){
  const d=await api('/api/v1/operations/summary');if($('#v12DeviceCount'))$('#v12DeviceCount').textContent=String(d.camera_devices||0);if($('#v12DeviceEnabled'))$('#v12DeviceEnabled').textContent=`${d.enabled_devices||0} đang bật`;if($('#v12PendingExceptions'))$('#v12PendingExceptions').textContent=String(d.pending_exceptions||0);if($('#v12ActiveSessions'))$('#v12ActiveSessions').textContent=String(d.active_sessions||0);renderOpsRules(d.rules||{});return d;
}
async function loadOpsCenter(){
  if(window.BTMHCameraConfiguration)return window.BTMHCameraConfiguration.start();
  if(!(state.students||[]).length)await loadStudents();
  try{await Promise.all([loadOpsSummary(),loadOpsDevices(),loadOpsExceptions()]);}catch(e){toast(e.message,true)}
}

function formatBytes(n){n=Number(n||0);if(n<1024)return `${n} B`;if(n<1024*1024)return `${(n/1024).toFixed(1)} KB`;if(n<1024*1024*1024)return `${(n/1024/1024).toFixed(1)} MB`;return `${(n/1024/1024/1024).toFixed(1)} GB`;}
async function loadAuthStatus(){
  const authUserAtRequest=state.authUser;if(state.logoutPending)return null;
  try{
    const st=await api('/api/v1/auth/status');
    if(state.logoutPending||state.authUser!==authUserAtRequest)return null;
    state.authUser=st.user||null;setAuthGate(st);applyRoleUi(state.authUser);
    const setup=$('#authSetupArea'),login=$('#authLoginArea'),user=$('#authUserArea'),badge=$('#authState');
    setup?.classList.toggle('hidden',!st.setup_required);
    login?.classList.toggle('hidden',st.setup_required||st.authenticated);
    user?.classList.toggle('hidden',!st.authenticated);
    if(badge){
      badge.textContent=st.setup_required?'Chưa thiết lập':st.authenticated?'Đang đăng nhập':'Chưa đăng nhập';
      badge.className='pr-state '+(st.authenticated?'ok':st.setup_required?'warn':'bad');
    }
    if($('#authCurrentUser')&&st.user)$('#authCurrentUser').textContent=st.user.display_name||st.user.username||'Tài khoản';
    return st;
  }catch(e){if(!state.logoutPending&&state.authUser===authUserAtRequest)toast(e.message,true);return null;}
}

async function setupAdmin(){try{const data=await api('/api/v1/auth/bootstrap',{method:'POST',body:JSON.stringify({username:$('#authUsername').value.trim(),display_name:$('#authDisplayName').value.trim(),password:$('#authPassword').value})});localStorage.setItem('campusface_token',data.token);setAuthGate({authenticated:true,user:data.user});toast('Đã tạo tài khoản Admin.');await loadSystemPage();}catch(e){toast(e.message,true)}}
async function loginSystem(){try{const data=await api('/api/v1/auth/login',{method:'POST',body:JSON.stringify({username:$('#loginUsername').value.trim(),password:$('#loginPassword').value})});if(data?.second_factor_required){enterMfaChallenge(data);return;}if(!data?.token&&!data?.authenticated)throw new Error('Máy chủ chưa tạo phiên đăng nhập.');localStorage.removeItem('campusface_token');const st=await verifyBrowserSession();setAuthGate(st);toast('Đăng nhập thành công.');await loadSystemPage();}catch(e){toast(e.message,true)}}
async function logoutSystem(){
  if(state.logoutPending||!state.authUser)return;
  state.logoutPending=true;
  const buttons=[$('#authLogoutBtn'),$('#accountMenuLogoutBtn')].filter(Boolean);
  buttons.forEach(button=>{button.disabled=true;button.textContent='Đang đăng xuất...';});
  const note=$('#accountMenuNote');if(note){note.hidden=true;note.textContent='';}
  try{
    try{await api('/api/v1/auth/logout',{method:'POST',timeoutMs:8000});}catch(e){if(e.status!==401)throw e;}
    localStorage.removeItem('campusface_token');
    state.mfaChallenge='';state.mfaSetupRequired=false;state.mfaRecoveryCodes=[];state.pendingMfaStatus=null;
    window.btmhSms?.stopLoginTimer?.();
    ['#gateLoginPassword','#gateMfaCode','#gateMfaUri'].forEach(selector=>{const input=$(selector);if(input)input.value='';});
    if($('#gateMfaSecret'))$('#gateMfaSecret').textContent='—';
    if($('#gateMfaRecoveryCodes'))$('#gateMfaRecoveryCodes').textContent='';
    setAuthGate({authenticated:false,setup_required:false});
    setAuthFeedback('#gateLoginNote','Đã đăng xuất. Bạn có thể đăng nhập bằng tài khoản khác.','success');
    toast('Đã đăng xuất.');
  }catch(e){
    const message='Chưa đăng xuất được. Hãy thử lại.';
    if(note){note.textContent=message;note.hidden=false;}
    toast(message,true);
  }finally{
    state.logoutPending=false;buttons.forEach(button=>{button.disabled=false;button.textContent='Đăng xuất';});
  }
}

function visitorDuration(sec){sec=Math.max(0,Number(sec||0));if(sec<60)return `${Math.round(sec)} giây`;const m=Math.floor(sec/60),h=Math.floor(m/60);return h?`${h}h ${m%60}p`:`${m} phút`;}
function visitorTypeLabel(v='UNKNOWN'){return ({UNKNOWN:'Chưa xác nhận',KNOWN:'Khách quen',VIP:'Khách VIP',WATCHLIST:'Cần chú ý',IGNORED:'Bỏ qua'})[String(v||'UNKNOWN').toUpperCase()]||v;}
async function loadVisitors(){
  const host=$('#visitorGrid');if(!host)return;
  const actor=state.authUser,epoch=state.presentationEpoch;
  const filter=$('#visitorStatusFilter')?.value||'';
  try{
    const d=await api(`/api/v1/visitors?status=${encodeURIComponent(filter)}&limit=120`),rows=d.items||[];
    if(actor!==state.authUser||epoch!==state.presentationEpoch||state.activePage!=='visitors'||!appPresentationActive())return;
    const active=rows.filter(x=>x.status==='ACTIVE').length,unknown=rows.filter(x=>String(x.visitor_type||'UNKNOWN')==='UNKNOWN').length;
    if($('#visitorActiveCount'))$('#visitorActiveCount').textContent=String(active);if($('#visitorTotalCount'))$('#visitorTotalCount').textContent=String(rows.length);if($('#visitorUnknownCount'))$('#visitorUnknownCount').textContent=String(unknown);
    host.innerHTML=rows.length?rows.map(x=>{
      const code=escapeHtml(x.session_code||''),shots=(x.best_shots||[]).slice(0,3),status=String(x.status||'').toUpperCase(),type=String(x.visitor_type||'UNKNOWN').toUpperCase();
      const shotHtml=[0,1,2].map(i=>shots[i]?`<div class="btmh-shot"><img src="${escapeHtml(shots[i].snapshot_url||'')}" alt="Best shot ${i+1}"><span>#${i+1} · ${Math.round(Number(shots[i].quality||0)*100)}%</span></div>`:'<div class="btmh-shot empty">Chưa có ảnh</div>').join('');
      return `<article class="btmh-visitor-card ${status==='ACTIVE'?'active':''} ${type==='WATCHLIST'?'watchlist':''}"><div class="btmh-visitor-card-head"><div><b>${code}</b><small>${formatDate(x.entry_at)} · ${escapeHtml(visitorTypeLabel(type))}</small></div><span class="btmh-visitor-status ${status==='ACTIVE'?'active':''}">${status==='ACTIVE'?'QUAN SÁT ĐANG MỞ':'PHIÊN ĐÃ ĐÓNG'}</span></div><div class="btmh-best-shots">${shotHtml}</div><div class="btmh-visitor-meta"><div><span>Camera</span><b>${escapeHtml(x.camera_name||'Chưa rõ camera')}</b></div><div><span>Khoảng quan sát</span><b>${visitorDuration(x.duration_sec)}</b></div></div><div class="btmh-visitor-review" data-permission="visitor.review"><select id="visitorType_${code}" aria-label="Nhãn quan sát"><option value="UNKNOWN" ${type==='UNKNOWN'?'selected':''}>Chưa xác nhận</option><option value="KNOWN" ${type==='KNOWN'?'selected':''}>Khách quen</option><option value="VIP" ${type==='VIP'?'selected':''}>Khách VIP</option><option value="WATCHLIST" ${type==='WATCHLIST'?'selected':''}>Cần chú ý</option><option value="IGNORED" ${type==='IGNORED'?'selected':''}>Bỏ qua</option></select><input id="visitorLabel_${code}" value="${escapeHtml(x.label||'')}" placeholder="Tên / nhãn ghi nhớ" aria-label="Ghi chú quan sát"><button class="btn soft" type="button" onclick="saveVisitorReview('${code}')">Lưu xác nhận</button></div></article>`;
    }).join(''):`<div class="empty-card">${d.coverage==='LEGACY_UNATTRIBUTED'?'Quan sát cũ chưa có nguồn cửa hàng để xác nhận phạm vi. Xem Lịch sử → Lượt khách để dùng dữ liệu có nguồn.':'Chưa có quan sát phù hợp bộ lọc.'}</div>`;
    applyRoleUi(state.authUser);
  }catch(e){if(actor===state.authUser&&epoch===state.presentationEpoch&&state.activePage==='visitors'&&appPresentationActive())host.innerHTML=`<div class="empty-card">${escapeHtml(e.message)}</div>`;}
}
async function saveVisitorReview(code){try{const visitor_type=$(`#visitorType_${code}`)?.value||'UNKNOWN',label=$(`#visitorLabel_${code}`)?.value||'';await api(`/api/v1/visitors/${encodeURIComponent(code)}/review`,{method:'PUT',body:JSON.stringify({visitor_type,label,note:''})});toast('Đã cập nhật ghi chú quan sát.');await loadVisitors();}catch(e){toast(e.message,true)}}window.saveVisitorReview=saveVisitorReview;

async function loadRbacAdmin(){
  if(!hasUiPermission('account.approve'))return;
  const userHost=$('#rbacUserList'),roleHost=$('#rbacRoleCatalog'),roleSelect=$('#rbacRole');if(!userHost)return;
  try{
    const [rolesData,usersData,storesData]=await Promise.all([api('/api/v1/admin/roles'),api('/api/v1/admin/users'),api('/api/v1/stores')]);
    const roles=rolesData.items||[],users=usersData.items||[],stores=storesData.items||[];
    const actorRole=String(state.authUser?.role||'').toUpperCase();
    const visibleRoleOrder=['SUPER_ADMIN','ADMIN','MANAGER','HR','SECURITY','EMPLOYEE'];
    const roleByName=new Map(roles.map(r=>[String(r.role||'').toUpperCase(),r]));
    const visibleRoles=visibleRoleOrder.map(k=>roleByName.get(k)).filter(Boolean);
    const assignableNames=actorRole==='MANAGER'?['EMPLOYEE']:['ADMIN','MANAGER','HR','SECURITY','EMPLOYEE'];
    const assignable=assignableNames.map(k=>roleByName.get(k)).filter(Boolean);
    if(roleSelect)roleSelect.innerHTML=assignable.map(r=>`<option value="${escapeHtml(r.role)}">${escapeHtml(r.label||r.role)}</option>`).join('');
    const createStore=$('#rbacStore');if(createStore){const selected=createStore.value;createStore.innerHTML='<option value="">Chưa gán cửa hàng</option>'+stores.map(st=>`<option value="${Number(st.id)}">${escapeHtml(st.store_name||st.store_code)}</option>`).join('');createStore.value=stores.some(st=>String(st.id)===selected)?selected:'';}
    if(roleHost)roleHost.innerHTML=visibleRoles.map(r=>`<article class="btmh-role-pill"><b>${escapeHtml(r.label||r.role)}</b><small>${escapeHtml(r.description||'')}</small></article>`).join('');
    userHost.innerHTML=users.length?users.map(u=>{
      const role=String(u.role||'').toUpperCase();
      const status=String(u.account_status||(u.active?'ACTIVE':'PENDING')).toUpperCase();
      const pending=status==='PENDING';
      const roleOpts=assignable.map(r=>`<option value="${escapeHtml(r.role)}" ${role===String(r.role).toUpperCase()?'selected':''}>${escapeHtml(r.label||r.role)}</option>`).join('');
      const storeOpts='<option value="">Tất cả chi nhánh / chưa gán</option>'+stores.map(st=>`<option value="${Number(st.id)}" ${Number(u.store_id||0)===Number(st.id)?'selected':''}>${escapeHtml(st.store_name||st.store_code)}</option>`).join('');
      if(pending)return `<article class="btmh-user-row v5-pending-user"><div class="btmh-user-id"><b>${escapeHtml(u.display_name||u.username)}</b><small>@${escapeHtml(u.username)}</small></div><select id="rbacApproveRole_${u.id}" aria-label="Vai trò">${roleOpts}</select><select id="rbacApproveStore_${u.id}" aria-label="Chi nhánh">${storeOpts}</select><span class="pr-state warn">Chờ duyệt</span><div class="btmh-user-actions"><button type="button" class="btn primary" onclick="approveRbacUser(${Number(u.id)})">Duyệt tài khoản</button></div></article>`;
      const canEdit=hasUiPermission('system.manage')&&role!=='SUPER_ADMIN';
      const mfaBadge=u.mfa_enabled?'<span class="btmh-mini-badge ok">Authenticator đã bật</span>':(['ADMIN','SUPER_ADMIN'].includes(role)?'<span class="btmh-mini-badge warn">Cần thiết lập Authenticator</span>':'');
      return `<article class="btmh-user-row"><div class="btmh-user-id"><b>${escapeHtml(u.display_name||u.username)}</b><small>@${escapeHtml(u.username)} · ${escapeHtml(u.role_label||role)}</small>${mfaBadge}</div>${canEdit?`<select id="rbacRole_${u.id}" aria-label="Vai trò">${roleOpts}</select><label class="btmh-user-active"><input id="rbacActive_${u.id}" type="checkbox" ${u.active?'checked':''}> Hoạt động</label>`:`<span class="btmh-role-readonly">${escapeHtml(u.role_label||role)}</span>`}<span class="pr-state ${u.active?'ok':'warn'}">${u.active?'Đang hoạt động':'Đã khóa'}</span>${canEdit?`<div class="btmh-user-actions"><button type="button" class="btn ghost" onclick="saveRbacUser(${Number(u.id)})">Lưu quyền</button><button type="button" class="btn ghost" onclick="resetRbacPassword(${Number(u.id)},'${escapeHtml(u.username)}')">Đổi mật khẩu</button>${role==='ADMIN'?`<button type="button" class="btn ghost danger" onclick="resetRbacMfa(${Number(u.id)},'${escapeHtml(u.username)}')">Đặt lại Authenticator</button>`:''}</div>`:''}</article>`;
    }).join(''):'<div class="empty-card">Chưa có tài khoản.</div>';
  }catch(e){userHost.innerHTML=`<div class="empty-card">${escapeHtml(e.message||'Không tải được tài khoản.')}</div>`;}
}
async function approveRbacUser(id){try{const role=$(`#rbacApproveRole_${id}`)?.value||'EMPLOYEE',storeRaw=$(`#rbacApproveStore_${id}`)?.value||'';await api(`/api/v1/admin/users/${id}/approve`,{method:'POST',body:JSON.stringify({role,store_id:storeRaw?Number(storeRaw):null})});toast('Đã phê duyệt và kích hoạt tài khoản.');await loadRbacAdmin();}catch(e){toast(e.message,true)}}window.approveRbacUser=approveRbacUser;

async function createRbacUser(ev){
  ev.preventDefault();const form=ev.target;if(form.dataset.pending==='1')return;
  const button=form.querySelector('button[type="submit"]'),feedback=$('#rbacCreateFeedback'),actor=state.authUser;
  const password=$('#rbacPassword')?.value||'',confirmation=$('#rbacPasswordConfirm')?.value||'';
  const show=message=>{if(feedback)feedback.textContent=message;};
  if(password.length<12||password!==confirmation){show('Mật khẩu cần ít nhất 12 ký tự và phần xác nhận phải khớp.');$('#rbacPasswordConfirm')?.focus();return;}
  form.dataset.pending='1';if(button)button.disabled=true;show('Đang tạo tài khoản…');
  try{
    await api('/api/v1/admin/users',{method:'POST',body:JSON.stringify({username:$('#rbacUsername')?.value?.trim()||'',display_name:$('#rbacDisplayName')?.value?.trim()||'',role:$('#rbacRole')?.value||'EMPLOYEE',password,confirm_password:confirmation,
      phone:$('#rbacPhone')?.value?.trim()||'',email:$('#rbacEmail')?.value?.trim()||'',store_id:Number($('#rbacStore')?.value)||null})});
    if(state.authUser!==actor)return;show('Đã tạo tài khoản và áp dụng quyền.');form.reset();await loadRbacAdmin();
  }catch(e){if(state.authUser===actor){show(e.message||'Chưa tạo được tài khoản. Hãy thử lại.');if(e.field==='new_password')$('#rbacPassword')?.focus();else if(e.field==='confirm_password')$('#rbacPasswordConfirm')?.focus();}}
  finally{form.dataset.pending='0';if(button)button.disabled=false;for(const id of ['#rbacPassword','#rbacPasswordConfirm'])if($(id))$(id).value='';}
}
async function saveRbacUser(id){try{await api(`/api/v1/admin/users/${id}`,{method:'PUT',body:JSON.stringify({role:$(`#rbacRole_${id}`)?.value||'EMPLOYEE',active:!!$(`#rbacActive_${id}`)?.checked})});toast('Đã cập nhật quyền tài khoản.');await loadRbacAdmin();}catch(e){toast(e.message,true)}}window.saveRbacUser=saveRbacUser;
async function resetRbacPassword(id,username){const password=prompt(`Mật khẩu mới cho ${username} (tối thiểu 12 ký tự, gồm chữ hoa, chữ thường, số và ký tự đặc biệt):`);if(password===null)return;try{validateStrongPassword(password,password,12);await api(`/api/v1/admin/users/${id}/password`,{method:'PUT',body:JSON.stringify({password})});toast('Đã đổi mật khẩu và thu hồi các phiên đăng nhập cũ.');}catch(e){toast(e.message,true)}}window.resetRbacPassword=resetRbacPassword;
async function resetRbacMfa(id,username){if(!confirm(`Đặt lại Authenticator của ${username}? Tài khoản sẽ phải thiết lập lại ở lần đăng nhập kế tiếp.`))return;try{const out=await api(`/api/v1/admin/users/${id}/mfa/reset`,{method:'POST'});toast(out.message||'Đã đặt lại Authenticator.');await loadRbacAdmin();}catch(e){toast(e.message,true)}}window.resetRbacMfa=resetRbacMfa;

// --------------------------- BTMH V5 Shift / Attendance ---------------------------
function v5EmployeeOptions(){return state.students.map(s=>`<option value="${Number(s.id)}">${escapeHtml(s.student_code||'')} · ${escapeHtml(s.full_name||'Nhân viên')}</option>`).join('')}
async function loadV5ShiftWorkspace(){
  try{
    if(!state.students.length&&hasUiPermission('employee.view'))await loadStudents();
    const [shiftData,corrData]=await Promise.all([api('/api/v1/work-shifts'),hasUiPermission('attendance.view')?api('/api/v1/attendance/corrections?limit=80'):Promise.resolve({items:[]})]);
    const shifts=shiftData.items||[],corr=corrData.items||[];
    const list=$('#v5ShiftList');if(list)list.innerHTML=shifts.length?shifts.map(x=>`<button type="button" class="v5-shift-card" data-v5-shift-id="${Number(x.id)}"><div><b>${escapeHtml(x.shift_code)} · ${escapeHtml(x.shift_name)}</b><small>${escapeHtml(x.start_time)} → ${escapeHtml(x.end_time)} · muộn ${Number(x.late_grace_minutes||0)}p · về sớm ${Number(x.early_leave_grace_minutes||0)}p</small></div><span class="pr-state ${x.active?'ok':'warn'}">${x.active?'ACTIVE':'OFF'}</span></button>`).join(''):'<div class="empty-card">Chưa có ca làm.</div>';
    $$('[data-v5-shift-id]').forEach(b=>b.addEventListener('click',()=>{const x=shifts.find(v=>Number(v.id)===Number(b.dataset.v5ShiftId));if(!x)return;$('#v5ShiftId').value=x.id||'';$('#v5ShiftCode').value=x.shift_code||'';$('#v5ShiftName').value=x.shift_name||'';$('#v5ShiftStart').value=x.start_time||'08:00';$('#v5ShiftEnd').value=x.end_time||'17:30';$('#v5ShiftLate').value=x.late_grace_minutes??5;$('#v5ShiftEarly').value=x.early_leave_grace_minutes??5;}));
    const employees=v5EmployeeOptions();if($('#v5ShiftEmployee'))$('#v5ShiftEmployee').innerHTML=employees;if($('#v5CorrectionEmployee'))$('#v5CorrectionEmployee').innerHTML=employees;
    if($('#v5ShiftAssignment'))$('#v5ShiftAssignment').innerHTML=shifts.filter(x=>x.active).map(x=>`<option value="${Number(x.id)}">${escapeHtml(x.shift_code)} · ${escapeHtml(x.shift_name)} (${escapeHtml(x.start_time)}–${escapeHtml(x.end_time)})</option>`).join('');
    if($('#v5ShiftEffective')&&!$('#v5ShiftEffective').value)$('#v5ShiftEffective').value=localDateInput();
    if($('#v5CorrectionDate')&&!$('#v5CorrectionDate').value)$('#v5CorrectionDate').value=localDateInput();
    const corrHost=$('#v5CorrectionList');if(corrHost)corrHost.innerHTML=corr.length?corr.map(x=>`<div class="v5-audit-row"><b>${escapeHtml(x.full_name||`Nhân viên #${x.student_id}`)} · ${escapeHtml(x.work_date)}</b><small>Camera: ${escapeHtml(x.original_checkin_at||x.original_checkout_at||'—')} → Hiệu lực: ${escapeHtml(x.effective_checkin_at||x.effective_checkout_at||'—')} · ${escapeHtml(x.reason||'')} · duyệt bởi ${escapeHtml(x.approved_by||'—')}</small></div>`).join(''):'<div class="empty-card">Chưa có điều chỉnh chấm công.</div>';
  }catch(e){toast(e.message,true)}
}
async function saveV5Shift(ev){ev.preventDefault();try{const payload={id:Number($('#v5ShiftId')?.value||0)||null,shift_code:$('#v5ShiftCode')?.value?.trim()||'',shift_name:$('#v5ShiftName')?.value?.trim()||'',start_time:$('#v5ShiftStart')?.value||'08:00',end_time:$('#v5ShiftEnd')?.value||'17:30',late_grace_minutes:Number($('#v5ShiftLate')?.value||0),early_leave_grace_minutes:Number($('#v5ShiftEarly')?.value||0),workdays:[0,1,2,3,4,5],active:true};await api('/api/v1/work-shifts',{method:'PUT',body:JSON.stringify(payload)});toast('Đã lưu ca làm.');$('#v5ShiftId').value='';await loadV5ShiftWorkspace()}catch(e){toast(e.message,true)}}
async function assignV5Shift(ev){ev.preventDefault();try{const studentId=Number($('#v5ShiftEmployee')?.value||0),shift_id=Number($('#v5ShiftAssignment')?.value||0),effective_from=$('#v5ShiftEffective')?.value||localDateInput();if(!studentId||!shift_id)throw new Error('Hãy chọn nhân viên và ca làm.');const out=await api(`/api/v1/employees/${studentId}/shift`,{method:'PUT',body:JSON.stringify({shift_id,effective_from})});const a=out.assignment||{};if($('#v5ShiftAssignmentState'))$('#v5ShiftAssignmentState').innerHTML=`<div class="v5-audit-row"><b>Đã gán ca ${escapeHtml(a.shift_code||'')}</b><small>Hiệu lực từ ${escapeHtml(a.effective_from||effective_from)} · ${escapeHtml(a.start_time||'')} → ${escapeHtml(a.end_time||'')}</small></div>`;toast('Đã gán ca cho nhân viên.')}catch(e){toast(e.message,true)}}
function dtInputToIsoOrNull(v){if(!v)return null;const d=new Date(v);return Number.isNaN(d.getTime())?v:d.toISOString()}
async function saveV5AttendanceCorrection(ev){ev.preventDefault();try{const student_id=Number($('#v5CorrectionEmployee')?.value||0),work_date=$('#v5CorrectionDate')?.value||'',original=$('#v5CorrectionOriginal')?.value||'',effective=$('#v5CorrectionEffective')?.value||'',reason=$('#v5CorrectionReason')?.value?.trim()||'';if(!student_id||!work_date||!effective||reason.length<3)throw new Error('Hãy chọn nhân viên, ngày, giờ hiệu chỉnh và nhập lý do.');await api('/api/v1/attendance/corrections',{method:'POST',body:JSON.stringify({student_id,work_date,original_checkin_at:dtInputToIsoOrNull(original),effective_checkin_at:dtInputToIsoOrNull(effective),correction_type:'MANUAL_ADJUSTMENT',reason})});toast('Đã lưu điều chỉnh; dữ liệu camera gốc không bị thay đổi.');$('#v5CorrectionReason').value='';await loadV5ShiftWorkspace()}catch(e){toast(e.message,true)}}

// --------------------------- BTMH V5 Incident / Evidence ---------------------------
let v5IncidentSelected='';
async function loadV5Incidents(){const host=$('#v5IncidentList');if(!host)return;try{const d=await api('/api/v1/incidents?limit=200'),rows=d.items||[];host.innerHTML=rows.length?rows.map(x=>`<div class="v5-incident-card ${v5IncidentSelected===x.incident_id?'active':''}" data-v5-incident="${escapeHtml(x.incident_id)}"><span class="v5-incident-badge">${escapeHtml(x.status||'OPEN')}</span><b>${escapeHtml(x.title||x.incident_id)}</b><div class="meta">${escapeHtml(x.incident_id)} · ${escapeHtml(formatDate(x.occurred_at))}${x.evidence_locked?' · 🔒 Evidence':''}</div></div>`).join(''):'<div class="empty-card">Chưa có sự cố.</div>';$$('[data-v5-incident]').forEach(el=>el.addEventListener('click',()=>loadV5IncidentDetail(el.dataset.v5Incident)));if(v5IncidentSelected&&!rows.some(x=>x.incident_id===v5IncidentSelected))v5IncidentSelected='';}catch(e){host.innerHTML=`<div class="empty-card">${escapeHtml(e.message)}</div>`}}
async function loadV5IncidentDetail(id){const host=$('#v5IncidentDetail');if(!host)return;v5IncidentSelected=String(id||'');try{const [x,clipsData]=await Promise.all([api(`/api/v1/incidents/${encodeURIComponent(id)}`),hasUiPermission('camera.playback')?api('/api/v1/video/clips?limit=30'):Promise.resolve({items:[]})]);const ev=x.evidence||[],clips=clipsData.items||[];host.innerHTML=`<div class="panel-head"><div><span class="btmh-kicker">${escapeHtml(x.incident_id)}</span><h2>${escapeHtml(x.title)}</h2><p>${escapeHtml(formatDate(x.occurred_at))} · ${escapeHtml(x.severity||'NORMAL')} · tạo bởi ${escapeHtml(x.created_by||'—')}</p></div><span class="v5-incident-badge">${x.evidence_locked?'🔒 ĐÃ KHÓA':'OPEN'}</span></div><p>${escapeHtml(x.note||'Chưa có ghi chú.')}</p>${x.visitor_session_code?`<div class="v5-audit-row"><b>Khách liên quan</b><small>${escapeHtml(x.visitor_session_code)}</small></div>`:''}<h3>Bằng chứng (${ev.length})</h3><div>${ev.length?ev.map(e=>`<div class="v5-evidence-row"><div><b>${escapeHtml(e.evidence_type)}</b><small>${escapeHtml(e.evidence_ref)}${e.camera_source?' · '+escapeHtml(e.camera_source):''}</small></div><time>${escapeHtml(formatDate(e.captured_at||e.created_at))}</time></div>`).join(''):'<div class="empty-card">Chưa gắn bằng chứng.</div>'}</div>${hasUiPermission('incident.manage')?`<div class="student-modal-actions"><button class="btn ghost" type="button" id="v5AttachLatestClip" ${clips.length?'':'disabled'}>Gắn clip gần nhất</button><button class="btn primary" type="button" id="v5LockIncident" ${x.evidence_locked?'disabled':''}>${x.evidence_locked?'Đã khóa bằng chứng':'Khóa bằng chứng'}</button></div>`:''}`;$('#v5AttachLatestClip')?.addEventListener('click',()=>attachV5Clip(id,clips[0]));$('#v5LockIncident')?.addEventListener('click',()=>lockV5Incident(id));await loadV5Incidents()}catch(e){host.innerHTML=`<div class="empty-card">${escapeHtml(e.message)}</div>`}}
async function createV5Incident(ev){ev.preventDefault();try{const title=$('#v5IncidentTitle')?.value?.trim()||'',severity=$('#v5IncidentSeverity')?.value||'NORMAL',visitor_session_code=$('#v5IncidentVisitor')?.value?.trim()||'',occurred_at=dtInputToIsoOrNull($('#v5IncidentTime')?.value)||'',note=$('#v5IncidentNote')?.value?.trim()||'';const out=await api('/api/v1/incidents',{method:'POST',body:JSON.stringify({title,severity,visitor_session_code,occurred_at,note})});closeV5IncidentModal();toast('Đã tạo hồ sơ sự cố.');v5IncidentSelected=out.incident?.incident_id||'';await loadV5Incidents();if(v5IncidentSelected)await loadV5IncidentDetail(v5IncidentSelected)}catch(e){toast(e.message,true)}}
function openV5IncidentModal(){const m=$('#v5IncidentModal');m?.classList.remove('hidden');if($('#v5IncidentTime')&&!$('#v5IncidentTime').value){const d=new Date(),z=n=>String(n).padStart(2,'0');$('#v5IncidentTime').value=`${d.getFullYear()}-${z(d.getMonth()+1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}:${z(d.getSeconds())}`}}
function closeV5IncidentModal(){$('#v5IncidentModal')?.classList.add('hidden')}
async function attachV5Clip(incidentId,clip){if(!clip)return;try{await api(`/api/v1/incidents/${encodeURIComponent(incidentId)}/evidence`,{method:'POST',body:JSON.stringify({evidence_type:'VIDEO_CLIP',evidence_ref:clip.clip_id,camera_source:clip.camera_source||'',captured_at:clip.start_at||'',note:'Clip được gắn từ Playback'})});toast('Đã gắn video clip vào sự cố.');await loadV5IncidentDetail(incidentId)}catch(e){toast(e.message,true)}}
async function lockV5Incident(id){if(!confirm('Khóa toàn bộ bằng chứng của sự cố này khỏi retention tự động?'))return;try{await api(`/api/v1/incidents/${encodeURIComponent(id)}/lock`,{method:'POST'});toast('Đã khóa bằng chứng.');await loadV5IncidentDetail(id)}catch(e){toast(e.message,true)}}

function renderDiagnostics(d){
  state.systemDiag=d;const badge=$('#systemOverall');if(badge){badge.textContent=d?.ok?'SẴN SÀNG':'CẦN KIỂM TRA';badge.className='pr-state '+(d?.ok?'ok':'warn')}
  const labels={camera:'Camera',camera_quality:'Hình ảnh camera',face_detector:'Nhận diện',passive_pad:'Chống giả mạo',templates:'Hồ sơ khuôn mặt',database:'Dữ liệu',storage:'Dung lượng',identity:'Quan sát',backup:'Sao lưu'};
  const host=$('#systemHealthList');if(host)host.innerHTML=(d?.checks||[]).filter(c=>Object.hasOwn(labels,c.key)).map(c=>`<div class="pr-health-row ${c.ok===true?'ok':'bad'}"><i></i><b>${labels[c.key]}</b><span>${c.ok===true?'Sẵn sàng':c.ok===false?'Cần kiểm tra':'Chưa ghi nhận'}</span></div>`).join('')||'<div class="empty-card">Chưa có dữ liệu.</div>';
  const cam=d?.camera||{},st=d?.storage||{};
  const online=!!cam.opened&&String(cam.state||'').toLowerCase()==='online',quality=String(cam.camera_quality||'UNKNOWN').toUpperCase();
  if($('#v6CameraResolution'))$('#v6CameraResolution').textContent=`${cam.actual_width||0} × ${cam.actual_height||0}`;
  if($('#v6CameraFps'))$('#v6CameraFps').textContent=`${Math.round(Number(cam.capture_fps||0))} FPS`;
  if($('#v6CameraQuality'))$('#v6CameraQuality').textContent=quality;
  if($('#v6CameraSharpness'))$('#v6CameraSharpness').textContent=Number(cam.sharpness_score||0).toFixed(0);
  if($('#v6CameraBrightness'))$('#v6CameraBrightness').textContent=Number(cam.brightness||0).toFixed(0);
  if($('#v6CameraLatency'))$('#v6CameraLatency').textContent=`${Number(cam.p95_ai_ms||0).toFixed(0)} ms`;
  if($('#v6CameraStateText'))$('#v6CameraStateText').textContent=cameraUiStatus(cam);
  if($('#v6CameraWarning'))$('#v6CameraWarning').textContent=online?'Camera đang hoạt động':'Kiểm tra nguồn điện và kết nối camera nếu trạng thái chưa phục hồi.';
  if($('#v6SharpnessBar'))$('#v6SharpnessBar').style.width=`${Math.min(100,Math.max(0,Number(cam.sharpness_score||0)/1.4))}%`;
  if($('#v6BrightnessBar'))$('#v6BrightnessBar').style.width=`${Math.min(100,Math.max(0,Number(cam.brightness||0)/2.55))}%`;
  if($('#v6SystemCamera'))$('#v6SystemCamera').textContent=cameraUiStatus(cam);
  if($('#v6SystemCameraMeta'))$('#v6SystemCameraMeta').textContent=online?'Đang hoạt động':'Chưa sẵn sàng';
  if($('#v6SystemStorage'))$('#v6SystemStorage').textContent=formatBytes(st.free_bytes||0);
  if($('#v6SystemStorageMeta'))$('#v6SystemStorageMeta').textContent=`${st.backup_count||0} backup · ảnh ${formatBytes(st.photos_size||0)}`;
  if($('#v6DataRoot'))$('#v6DataRoot').textContent=st.data_root||'—';
}
function productionCardState(el,value,warn,bad){
  if(!el)return;el.classList.remove('ok','warn','bad');el.classList.add(value>=bad?'bad':value>=warn?'warn':'ok');
}
function renderProductionStatus(d={}){
  state.productionStatus=d;
  const r=d.resources||{},g=d.gpu||{},db=d.database||{},cam=d.camera||{},wd=d.watchdog||{},bk=d.backup||{},cfg=d.config||{};
  const cpu=Number(r.cpu_percent||0),ram=Number(r.ram_percent||0),gpu=Number(g.utilization_percent||0),rss=Number(r.process_rss_bytes||0);
  if($('#v210Cpu'))$('#v210Cpu').textContent=`${cpu.toFixed(0)}%`;if($('#v210ProcessRam'))$('#v210ProcessRam').textContent=`CampusFace ${formatBytes(rss)}`;productionCardState($('#v210CpuCard'),cpu,80,94);
  if($('#v210Ram'))$('#v210Ram').textContent=`${ram.toFixed(0)}%`;if($('#v210RamMeta'))$('#v210RamMeta').textContent=`${formatBytes(r.ram_used_bytes||0)} / ${formatBytes(r.ram_total_bytes||0)}`;productionCardState($('#v210RamCard'),ram,82,93);
  if($('#v210Gpu'))$('#v210Gpu').textContent=g.available?`${gpu.toFixed(0)}%`:'CPU';if($('#v210GpuMeta'))$('#v210GpuMeta').textContent=g.available?`${g.name||'GPU'} · VRAM ${Math.round(Number(g.memory_used_mb||0))}/${Math.round(Number(g.memory_total_mb||0))} MB`:'Không có GPU tăng tốc';productionCardState($('#v210GpuCard'),gpu,85,96);
  const watchdogOn=!!wd.enabled;if($('#v210Watchdog'))$('#v210Watchdog').textContent=watchdogOn?'ACTIVE':'OFF';if($('#v210RecoveryMeta'))$('#v210RecoveryMeta').textContent=`${Number(wd.recovery_count||0)} lần phục hồi`;const wc=$('#v210WatchdogCard');if(wc){wc.classList.remove('ok','warn','bad');wc.classList.add(watchdogOn?'ok':'warn')}
  if($('#v210DbLatency'))$('#v210DbLatency').textContent=db.ok===true?'Đã kết nối':db.ok===false?'Mất kết nối':'Chưa ghi nhận';
  if($('#v210FrameAge'))$('#v210FrameAge').textContent=`${Math.round(Number(cam.last_frame_age_ms||0))} ms`;
  if($('#v210RecoveryCount'))$('#v210RecoveryCount').textContent=`${Number(wd.recovery_count||0)} lần`;
  const lastBk=Number(bk.last_auto_backup_at||0);if($('#v210BackupState'))$('#v210BackupState').textContent=bk.enabled?(lastBk?`Gần nhất ${formatDate(new Date(lastBk*1000).toISOString())}`:`Mỗi ${Number(bk.interval_hours||24)} giờ`):'ĐÃ TẮT';
  const stateBadge=$('#v210ProdState');if(stateBadge){stateBadge.textContent=d.status==='WARNING'?'CẦN KIỂM TRA':'ỔN ĐỊNH';stateBadge.className=`v210-watchdog-state ${d.status==='WARNING'?'warn':''}`;}
  if($('#v210WatchdogEnabled'))$('#v210WatchdogEnabled').checked=!!cfg.watchdog_enabled;if($('#v210AutoRecovery'))$('#v210AutoRecovery').checked=!!cfg.camera_auto_recovery;if($('#v210AutoBackup'))$('#v210AutoBackup').checked=!!cfg.auto_backup_enabled;if($('#v210BackupHours'))$('#v210BackupHours').value=Number(cfg.auto_backup_interval_hours||24);if($('#v210BackupRetention'))$('#v210BackupRetention').value=Number(cfg.auto_backup_retention||14);
}
async function loadProductionStatus(force=false){
  if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.manage'))return;
  return BTMHRuntime.once(force?'system-production-check':'system-production-status',async()=>{
    if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.manage'))return;
    const controller=new AbortController(),epoch=state.systemDiagEpoch;
    const field=force?'systemProductionCheckController':'systemProductionController';state[field]=controller;
    try{
      const d=await api(force?'/api/v1/production/check':'/api/v1/production/status',{method:force?'POST':'GET',signal:controller.signal,timeoutMs:8000});
      if(controller.signal.aborted||epoch!==state.systemDiagEpoch||!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.manage'))return;
      renderProductionStatus(d);return d;
    }catch(e){if(!controller.signal.aborted&&epoch===state.systemDiagEpoch&&appPresentationActive()){const b=$('#v210ProdState');if(b){b.textContent='LỖI';b.className='v210-watchdog-state bad';}throw e;}}
    finally{if(state[field]===controller)state[field]=null;}
  }).catch(e=>{if(e.name!=='AbortError')throw e;});
}
async function saveProductionPolicy(ev){
  ev.preventDefault();
  const prev=state.productionStatus?.config||{};
  const payload={...prev,watchdog_enabled:!!$('#v210WatchdogEnabled')?.checked,camera_auto_recovery:!!$('#v210AutoRecovery')?.checked,auto_backup_enabled:!!$('#v210AutoBackup')?.checked,auto_backup_interval_hours:Number($('#v210BackupHours')?.value||24),auto_backup_retention:Number($('#v210BackupRetention')?.value||14)};
  try{const d=await api('/api/v1/production/config',{method:'PUT',body:JSON.stringify(payload)});renderProductionStatus({...d.status,config:d.config});toast('Đã lưu chính sách vận hành 24/7.');}catch(e){toast(e.message,true)}
}
async function recoverProductionCamera(){
  if(!confirm('Yêu cầu hệ thống phục hồi camera hiện tại?'))return;
  try{toast('Đang phục hồi camera...');const d=await api('/api/v1/production/recover-camera',{method:'POST'});renderProductionStatus(d);setTimeout(()=>{loadHealth().catch(()=>{});loadProductionStatus().catch(()=>{})},900);}catch(e){toast(e.message,true)}
}
async function runSelfTest(){try{const d=await api('/api/v1/system/self-test',{method:'POST'});renderDiagnostics(d);toast(d.ok?'Hệ thống sẵn sàng.':'Có hạng mục cần kiểm tra.',!d.ok);}catch(e){toast(e.message,true)}}
async function reconnectCamera(){
  try{const d=await api('/api/v1/camera/reconnect',{method:'POST'});toast('Đã yêu cầu kết nối lại camera.');mountSystemCameraPreview();setTimeout(()=>loadSystemPage(false),700);}catch(e){toast(e.message,true)}
}
async function testCurrentCamera(){
  try{const d=await api('/api/v1/camera/test-current',{method:'POST'});const msg=d.ok?'Camera đã phản hồi.':'Camera chưa ổn định. Kiểm tra nguồn điện và kết nối.';toast(msg,!d.ok);if($('#cameraRuntimeInfo'))$('#cameraRuntimeInfo').textContent=msg;await loadSystemAudit();}catch(e){toast('Không kiểm tra được camera. Vui lòng thử lại.',true)}
}
async function loadSystemAudit(){
  const host=$('#systemAuditList');if(!host)return;
  try{const d=await api('/api/v1/system/audit?limit=35'),rows=d.items||[];host.innerHTML=rows.length?rows.map(x=>`<div class="v6-audit-row"><time>${escapeHtml(formatDate(x.event_at))}</time><strong>${escapeHtml(x.category||'SYSTEM')}</strong><b>${escapeHtml(x.event_type||'—')}</b><span>${escapeHtml(x.full_name||x.status||'')}</span></div>`).join(''):'<div class="empty-card">Chưa có nhật ký hệ thống.</div>';}catch(e){host.innerHTML=`<div class="empty-card">${escapeHtml(e.message)}</div>`;}
}
async function loadTechnicalHistory(){
  const host=$('#systemTechnicalList');if(!host||!$('#systemTechnicalDetails')?.open||!hasUiPermission('system.diagnostics')||!appPresentationActive()||state.activePage!=='system')return;
  if(state.systemTechnicalController)return;const controller=new AbortController(),actor=state.authUser,epoch=state.presentationEpoch;state.systemTechnicalController=controller;
  try{const d=await api('/api/v1/history/technical?limit=80',{signal:controller.signal,timeoutMs:6000});if(controller.signal.aborted||state.systemTechnicalController!==controller||actor!==state.authUser||epoch!==state.presentationEpoch||!$('#systemTechnicalDetails')?.open||!appPresentationActive()||state.activePage!=='system')return;
    const rows=d.items||[];state.historyTechnicalFeed=rows;host.innerHTML=rows.length?rows.map(x=>{const detail=x.detail||{},label=({TRACK_TEMPORARILY_LOST:'Tạm mất theo dõi',TRACK_REACQUIRED:'Đã nối lại theo dõi'})[String(x.event_type||'').toUpperCase()]||'Mốc kỹ thuật';const who=cameraUiName(x.full_name||x.student_code||'Hệ thống');const extra=detail.absence_sec!=null?`${Math.round(Number(detail.absence_sec||0))} giây`:cameraUiName(detail.message||'');return `<div class="v6-audit-row technical"><time>${escapeHtml(formatDate(x.event_at))}</time><b>${label}</b><span>${escapeHtml(who)}${extra?` · ${escapeHtml(extra)}`:''}</span></div>`}).join(''):'<div class="empty-card">Chưa có mốc kỹ thuật được lưu.</div>';
  }catch(e){if(!controller.signal.aborted&&actor===state.authUser&&$('#systemTechnicalDetails')?.open&&appPresentationActive())host.innerHTML='<div class="empty-card">Không tải được nhật ký kỹ thuật. Đóng và mở lại để thử.</div>';}
  finally{if(state.systemTechnicalController===controller)state.systemTechnicalController=null;}
}
async function loadSystemSummary(){
  const d=await loadProfessionalSummary(true);if(!d)return;
  const st=d.students||{},db=d.database||{};
  if($('#v6SystemFace'))$('#v6SystemFace').textContent=`${Math.round(Number(st.faceid_coverage||0))}%`;
  if($('#v6SystemFaceMeta'))$('#v6SystemFaceMeta').textContent=`${st.faceid||0}/${st.total||0} nhân viên`;
  const configured=['postgres','sqlite'].includes(String(db.mode||'').toLowerCase());
  if($('#v6SystemDb'))$('#v6SystemDb').textContent=configured?'Đã cấu hình':'Chưa ghi nhận';
  if($('#v6SystemDbMeta'))$('#v6SystemDbMeta').textContent=configured?'Dữ liệu hệ thống':'Cần kiểm tra kết nối dữ liệu';
}
async function exportStudents(){try{await downloadAuthed('/api/v1/exports/students.csv','BTMH-Employees.csv')}catch(e){toast(e.message,true)}}
async function downloadStudentTemplate(){try{await downloadAuthed('/api/v1/exports/student-template.csv','BTMH-Employee-Template.csv')}catch(e){toast(e.message,true)}}

async function loadCameraSettings(){
  const details=$('#cameraConnectionDetails');if(!details?.open||!hasUiPermission('camera.configure')||!appPresentationActive()||state.activePage!=='system')return;
  if(state.systemSettingsController)return;const controller=new AbortController(),actor=state.authUser,epoch=state.presentationEpoch;state.systemSettingsController=controller;
  try{const data=await api('/api/v1/settings/camera',{signal:controller.signal,timeoutMs:6000});if(controller.signal.aborted||state.systemSettingsController!==controller||!details.open||actor!==state.authUser||epoch!==state.presentationEpoch||!appPresentationActive()||state.activePage!=='system')return;
    const v=data.settings||{},r=data.runtime||{};if($('#camSource'))$('#camSource').value=v.source??'0';if($('#camBackend'))$('#camBackend').value=v.backend||'auto';const res=`${v.width||1920}x${v.height||1080}`;if($('#camResolution'))$('#camResolution').value=[...$('#camResolution').options].some(o=>o.value===res)?res:'1920x1080';if($('#camFps'))$('#camFps').value=v.fps||30;if($('#camFourcc'))$('#camFourcc').value=String(v.fourcc||'AUTO').toUpperCase();if($('#camPreviewFps'))$('#camPreviewFps').value=v.preview_fps||25;if($('#camObservationPreviewFps'))$('#camObservationPreviewFps').value=v.observation_preview_fps||v.classroom_preview_fps||25;
    syncCameraPresetUi(cameraPresetFromSource(r.source??v.source??'0'));const online=String(r.state||'')==='online';if($('#cameraRuntimeState')){$('#cameraRuntimeState').textContent=cameraUiStatus(r);$('#cameraRuntimeState').className='pr-state '+(online?'ok':'warn')}if($('#cameraRuntimeInfo'))$('#cameraRuntimeInfo').textContent=`Camera · ${cameraUiStatus(r)}`;
  }catch(e){if(!controller.signal.aborted&&details.open&&actor===state.authUser&&appPresentationActive())toast('Không tải được cấu hình kết nối camera. Vui lòng thử lại.',true);}
  finally{if(state.systemSettingsController===controller)state.systemSettingsController=null;}
}
async function saveCameraSettingsUi(ev){ev.preventDefault();const [w,h]=($('#camResolution').value||'1920x1080').split('x').map(Number);try{const out=await api('/api/v1/settings/camera',{method:'PUT',body:JSON.stringify({source:$('#camSource').value.trim(),backend:$('#camBackend').value,width:w,height:h,fps:Number($('#camFps').value||30),fourcc:$('#camFourcc').value,preview_fps:Number($('#camPreviewFps').value||25),observation_preview_fps:Number($('#camObservationPreviewFps').value||25)})});toast(out.restart_required?'Đã lưu. Khởi động lại CampusFace để áp dụng.':'Đã lưu cấu hình.');}catch(e){toast(e.message,true)}}
async function loadBackups(){const host=$('#backupList');try{const data=await api('/api/v1/backups'),rows=data.items||[];if(host)host.innerHTML=rows.length?rows.map(x=>`<div class="pr-backup-item"><div><b>${escapeHtml(x.name)}</b><small>${formatDate(x.created_at)} · ${formatBytes(x.size)}</small></div><div class="pr-backup-actions"><button type="button" onclick="downloadBackup('${escapeHtml(x.name)}')">Tải</button><button class="danger" type="button" onclick="restoreBackup('${escapeHtml(x.name)}')">Khôi phục</button></div></div>`).join(''):'<div class="empty-card">Chưa có backup.</div>';}catch(e){if(host)host.innerHTML=`<div class="empty-card">${escapeHtml(e.message)}</div>`;}}
async function createBackupUi(){try{await api('/api/v1/backups',{method:'POST'});toast('Đã tạo bản sao lưu.');await loadBackups();await runSelfTest();}catch(e){toast(e.message,true)}}
async function downloadBackup(name){try{await downloadAuthed(`/api/v1/backups/${encodeURIComponent(name)}`,name)}catch(e){toast(e.message,true)}}window.downloadBackup=downloadBackup;
async function restoreBackup(name){if(!confirm(`Khôi phục ${name}? Hệ thống sẽ tạo backup an toàn trước khi thay dữ liệu và yêu cầu khởi động lại.`))return;try{const out=await api(`/api/v1/backups/${encodeURIComponent(name)}/restore`,{method:'POST'});toast(`Đã khôi phục. Hãy khởi động lại hệ thống. Backup an toàn: ${out.emergency_backup}`);await runSelfTest();}catch(e){toast(e.message,true)}}window.restoreBackup=restoreBackup;
async function importBackupUi(){const f=$('#backupImportFile')?.files?.[0];if(!f){toast('Chọn file .zip backup trước.',true);return}const token=localStorage.getItem('campusface_token')||'';try{const r=await fetch(`/api/v1/backups/import/${encodeURIComponent(f.name)}`,{method:'POST',headers:token?{'Authorization':`Bearer ${token}`}:{},body:await f.arrayBuffer()});let data={};try{data=await r.json()}catch(_){}if(!r.ok)throw new Error(data.detail||'Không nhập được backup');toast('Đã nhập file backup.');await loadBackups();}catch(e){toast(e.message,true)}}
async function loadMobileViewerAccess(){
  const badge=$('#mobileViewerState');
  try{
    const d=await api('/api/v1/admin/mobile-access');
    if($('#mobileViewerEnabled'))$('#mobileViewerEnabled').checked=!!d.enabled;
    if($('#mobileViewerPassword'))$('#mobileViewerPassword').value='';
    if($('#mobileViewerUrl'))$('#mobileViewerUrl').textContent=d.preferred_url||`${location.origin}${d.url||'/mobile'}`;
    if(badge){badge.textContent=d.enabled?'ĐANG BẬT':d.configured?'ĐÃ CẤU HÌNH':'CHƯA BẬT';badge.className='pr-state '+(d.enabled?'ok':d.configured?'warn':'');}
    return d;
  }catch(e){if(badge){badge.textContent='LỖI';badge.className='pr-state bad';}throw e;}
}
async function saveMobileViewerAccess(ev){
  ev.preventDefault();
  try{
    const d=await api('/api/v1/admin/mobile-access',{method:'PUT',body:JSON.stringify({enabled:!!$('#mobileViewerEnabled')?.checked,password:$('#mobileViewerPassword')?.value||''})});
    toast(d.enabled?'Đã bật Mobile Viewer (chỉ xem).':'Đã tắt Mobile Viewer.');
    await loadMobileViewerAccess();
  }catch(e){toast(e.message,true)}
}
async function copyMobileViewerUrl(){
  const value=$('#mobileViewerUrl')?.textContent||`${location.origin}/mobile`;
  try{await navigator.clipboard.writeText(value);toast('Đã sao chép địa chỉ Mobile.');}catch(_){toast(value);}
}
async function loadRecordingStatus(){
  if(!hasUiPermission('camera.playback'))return;
  try{const d=await api('/api/v1/recordings/status');if($('#recordingIndexState')){$('#recordingIndexState').textContent=d.segment_count?'ĐÃ INDEX':'SẴN SÀNG';$('#recordingIndexState').className='pr-state '+(d.segment_count?'ok':'warn')}if($('#recordingIndexMode'))$('#recordingIndexMode').textContent=d.mode||'—';if($('#recordingIndexSegments'))$('#recordingIndexSegments').textContent=String(d.segment_count||0);if($('#recordingIndexProtected'))$('#recordingIndexProtected').textContent=String(d.protected_segments||0);if($('#recordingIndexRetention'))$('#recordingIndexRetention').textContent=`${d.retention_days_default||30} ngày`;if($('#recordingIndexRoot'))$('#recordingIndexRoot').textContent=`Storage index: ${d.recording_root||'—'} · ${d.note||''}`;}catch(e){if($('#recordingIndexState')){$('#recordingIndexState').textContent='KHÔNG KHẢ DỤNG';$('#recordingIndexState').className='pr-state bad';}}
}

// --------------------------- BTMH V5.3 Chain / Edge Admin ---------------------------
function edgeFreshnessText(seconds){
  if(seconds===null||seconds===undefined||Number.isNaN(Number(seconds)))return 'Chưa có heartbeat';
  const s=Math.max(0,Number(seconds));
  if(s<60)return `${Math.round(s)} giây trước`;
  if(s<3600)return `${Math.round(s/60)} phút trước`;
  if(s<86400)return `${Math.round(s/3600)} giờ trước`;
  return `${Math.round(s/86400)} ngày trước`;
}
async function loadEdgeChainAdmin(){
  const host=$('#v53EdgeNodeList');if(!host||!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.manage'))return;
  return BTMHRuntime.once('system-edge-nodes',async()=>{
  if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.manage'))return;
  const controller=new AbortController(),epoch=state.systemDiagEpoch;state.systemEdgeController=controller;
  try{
    const d=await api('/api/v1/sync/nodes',{signal:controller.signal,timeoutMs:8000});
    if(controller.signal.aborted||epoch!==state.systemDiagEpoch||!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.manage'))return;
    const rows=d.items||[],stores=d.stores||[];
    const storeSel=$('#v53EdgeStore'),current=storeSel?.value||'';
    if(storeSel){storeSel.innerHTML='<option value="">Chọn chi nhánh</option>'+stores.map(s=>`<option value="${Number(s.id)}">${escapeHtml(s.store_code||'')} · ${escapeHtml(s.store_name||'Chi nhánh')}</option>`).join('');if(current&&[...storeSel.options].some(o=>o.value===current))storeSel.value=current;}
    const active=rows.filter(x=>String(x.status||'').toUpperCase()==='ACTIVE'),online=active.filter(x=>x.online),pending=rows.reduce((n,x)=>n+Number(x.pending_count||0),0);
    if($('#v53EdgeTotal'))$('#v53EdgeTotal').textContent=String(rows.length);
    if($('#v53EdgeOnline'))$('#v53EdgeOnline').textContent=String(online.length);
    if($('#v53EdgeOffline'))$('#v53EdgeOffline').textContent=String(rows.length-online.length);
    if($('#v53EdgePending'))$('#v53EdgePending').textContent=String(pending);
    host.innerHTML=rows.length?rows.map(x=>{
      const revoked=String(x.status||'').toUpperCase()==='REVOKED'||String(x.key_status||'').toUpperCase()==='REVOKED',isOnline=!!x.online&&!revoked;
      const badge=revoked?'<span class="pr-state v53-edge-revoked">REVOKED</span>':isOnline?'<span class="pr-state v53-edge-online">ONLINE</span>':'<span class="pr-state v53-edge-offline">OFFLINE</span>';
      const worker=x.worker_running?'<span class="pr-state ok">SYNC RUNNING</span>':'<span class="pr-state warn">SYNC STOPPED</span>';
      return `<article class="v53-edge-node"><div class="v53-edge-node-top"><div><h3>${escapeHtml(x.node_name||x.node_id)}</h3><div class="meta">${escapeHtml(x.node_id||'')} · ${escapeHtml(x.store_code||'Store')} ${escapeHtml(x.store_name||'Chưa gán chi nhánh')}</div><div class="meta">Fingerprint: ${escapeHtml(x.key_fingerprint||'Chưa có public key')}</div></div><div class="v53-edge-badges">${badge}${revoked?'':worker}</div></div><div class="v53-edge-node-grid"><div><span>Heartbeat</span><b>${escapeHtml(edgeFreshnessText(x.heartbeat_age_sec))}</b></div><div><span>Sync gần nhất</span><b>${x.last_sync_at?escapeHtml(formatDate(x.last_sync_at)):'Chưa có'}</b></div><div><span>Đang chờ</span><b>${Number(x.pending_count||0)} event</b></div><div><span>Phiên bản</span><b>${escapeHtml(x.app_version||'—')}</b></div></div>${x.worker_last_error?`<div class="v53-edge-error">${escapeHtml(x.worker_last_error)}</div>`:''}${revoked?'':`<div class="v53-edge-actions"><button type="button" class="btn ghost danger" data-v53-revoke-node="${escapeHtml(x.node_id||'')}">Thu hồi thiết bị</button></div>`}</article>`;
    }).join(''):'<div class="empty-card">Chưa có Edge PC nào. Hãy import pairing file từ PC cửa hàng để duyệt thiết bị đầu tiên.</div>';
    $$('[data-v53-revoke-node]').forEach(btn=>btn.addEventListener('click',()=>revokeEdgeNodeAdmin(btn.dataset.v53RevokeNode||'')));
  }catch(e){if(!controller.signal.aborted&&epoch===state.systemDiagEpoch&&appPresentationActive())host.innerHTML=`<div class="empty-card">${escapeHtml(e.message||'Không tải được danh sách Edge PC.')}</div>`;}
  finally{if(state.systemEdgeController===controller)state.systemEdgeController=null;}
  }).catch(e=>{if(e.name!=='AbortError')throw e;});
}
async function readEdgePairingFile(ev){
  const file=ev.target?.files?.[0];if(!file)return;
  try{const d=JSON.parse(await file.text());if(!d.node_id||!d.public_key_b64)throw new Error('Pairing file thiếu node_id hoặc public_key_b64.');if(d.private_key_exported===true)throw new Error('Từ chối pairing file có dấu hiệu chứa private key.');$('#v53EdgeNodeId').value=d.node_id||'';$('#v53EdgeNodeName').value=d.node_name||d.node_id||'';$('#v53EdgePublicKey').value=d.public_key_b64||'';if(d.store_id&&$('#v53EdgeStore'))$('#v53EdgeStore').value=String(d.store_id);if($('#v53EdgePairingHint'))$('#v53EdgePairingHint').textContent=`Đã đọc pairing ${d.key_fingerprint||''}. Private key exported: NO.`;toast('Đã đọc public pairing file. Kiểm tra chi nhánh rồi bấm Duyệt.');}catch(e){toast(e.message||'Pairing file không hợp lệ.',true);ev.target.value='';}
}
async function registerEdgeNodeAdmin(ev){
  ev.preventDefault();try{const payload={node_id:$('#v53EdgeNodeId')?.value?.trim()||'',node_name:$('#v53EdgeNodeName')?.value?.trim()||'',store_id:Number($('#v53EdgeStore')?.value||0)||null,public_key_b64:$('#v53EdgePublicKey')?.value?.trim()||''};if(!payload.node_id||!payload.node_name||!payload.store_id||!payload.public_key_b64)throw new Error('Hãy nhập đủ Node ID, tên thiết bị, chi nhánh và public key.');await api('/api/v1/sync/nodes',{method:'POST',body:JSON.stringify(payload)});toast('Đã duyệt Edge PC và gắn với chi nhánh.');ev.target.reset();if($('#v53EdgePairingHint'))$('#v53EdgePairingHint').textContent='Central chỉ lưu public key/fingerprint. Private key vẫn ở PC cửa hàng và được bảo vệ bằng DPAPI.';await loadEdgeChainAdmin();}catch(e){toast(e.message,true)}
}
async function revokeEdgeNodeAdmin(nodeId){
  if(!nodeId||!confirm(`Thu hồi Edge PC ${nodeId}? Thiết bị sẽ không thể đồng bộ tiếp cho tới khi được duyệt lại bằng pairing file.`))return;
  try{await api(`/api/v1/sync/nodes/${encodeURIComponent(nodeId)}/revoke`,{method:'POST'});toast('Đã thu hồi thiết bị Edge.');await loadEdgeChainAdmin();}catch(e){toast(e.message,true)}
}

function updateOtpProviderFieldVisibility(){
  const smsProvider=String($('#otpSmsProvider')?.value||'DEMO').toUpperCase();
  const emailProvider=String($('#otpEmailProvider')?.value||'DEMO').toUpperCase();
  $('#otpSmsWebhookFields')?.classList.toggle('hidden',smsProvider!=='WEBHOOK');
  $('#otpSmsTwilioFields')?.classList.toggle('hidden',smsProvider!=='TWILIO');
  $('#otpEmailSmtpFields')?.classList.toggle('hidden',emailProvider!=='SMTP');
}

function renderOtpProviderConfig(data={}){
  const panel=$('#otpProviderPanel');if(!panel)return;
  const role=String((data.user||state.authUser||{}).role||'').toUpperCase();
  const allowed=role==='SUPER_ADMIN';panel.classList.toggle('hidden',!allowed);if(!allowed)return;
  const cfg=data.provider_config||{},sms=cfg.sms||{},email=cfg.email||{},delivery=data.delivery||{};
  if($('#otpSmsEnabled'))$('#otpSmsEnabled').checked=sms.enabled!==false;
  if($('#otpSmsProvider'))$('#otpSmsProvider').value=String(sms.provider||'DEMO').toUpperCase();
  if($('#otpSmsWebhookUrl'))$('#otpSmsWebhookUrl').value=sms.webhook_url||'';
  if($('#otpSmsAccountSid'))$('#otpSmsAccountSid').value=sms.account_sid||'';
  if($('#otpSmsSender'))$('#otpSmsSender').value=sms.sender||'';
  if($('#otpSmsSecret'))$('#otpSmsSecret').value='';
  if($('#otpSmsSecretState')){$('#otpSmsSecretState').textContent=sms.secret_configured?'✓ Secret đã lưu bằng DPAPI':'Chưa lưu secret';$('#otpSmsSecretState').classList.toggle('ok',!!sms.secret_configured);}
  if($('#otpEmailEnabled'))$('#otpEmailEnabled').checked=email.enabled!==false;
  if($('#otpEmailProvider'))$('#otpEmailProvider').value=String(email.provider||'DEMO').toUpperCase();
  if($('#otpSmtpHost'))$('#otpSmtpHost').value=email.host||'';
  if($('#otpSmtpPort'))$('#otpSmtpPort').value=Number(email.port||587);
  if($('#otpSmtpUsername'))$('#otpSmtpUsername').value=email.username||'';
  if($('#otpSmtpFrom'))$('#otpSmtpFrom').value=email.from_email||'';
  if($('#otpSmtpPassword'))$('#otpSmtpPassword').value='';
  if($('#otpSmtpPasswordState')){$('#otpSmtpPasswordState').textContent=email.password_configured?'✓ Mật khẩu SMTP đã lưu bằng DPAPI':'Chưa lưu mật khẩu SMTP';$('#otpSmtpPasswordState').classList.toggle('ok',!!email.password_configured);}
  if($('#otpSmtpSsl'))$('#otpSmtpSsl').checked=!!email.ssl;
  if($('#otpSmtpStarttls'))$('#otpSmtpStarttls').checked=email.starttls!==false;
  const smsReal=!!delivery?.sms?.real_delivery,emailReal=!!delivery?.email?.real_delivery;
  if($('#otpSmsState'))$('#otpSmsState').textContent=smsReal?`Gửi thật · ${delivery.sms.provider}`:`${delivery?.sms?.enabled===false?'ĐANG TẮT':String(delivery?.sms?.provider||'DEMO')} · chưa xác nhận gửi thật`;
  if($('#otpEmailState'))$('#otpEmailState').textContent=emailReal?`Gửi thật · ${delivery.email.provider}`:`${delivery?.email?.enabled===false?'ĐANG TẮT':String(delivery?.email?.provider||'DEMO')} · chưa xác nhận gửi thật`;
  if($('#otpProviderOverall')){$('#otpProviderOverall').textContent=(smsReal||emailReal)?'REAL DELIVERY':'DEMO';$('#otpProviderOverall').className='pr-state '+((smsReal||emailReal)?'ok':'warn');}
  if($('#otpProviderWarning')){$('#otpProviderWarning').classList.toggle('ready',smsReal||emailReal);$('#otpProviderWarning').textContent=(smsReal||emailReal)?`Đã sẵn sàng gửi thật: ${smsReal?'SMS ':''}${smsReal&&emailReal?'· ':''}${emailReal?'Email':''}. Hãy dùng nút Gửi thử để kiểm tra credential và đường truyền.`:'Chưa có kênh OTP thật sẵn sàng. DEMO chỉ dùng để kiểm thử nội bộ; hãy cấu hình SMTP hoặc SMS Gateway/Twilio.';}
  updateOtpProviderFieldVisibility();
}

function renderAdminSecurity(data={}){
  window.btmhSms?.loadSecurity();
}

async function loadAdminSecurityModule(){
  const auth=await loadAuthStatus();
  if(!auth?.authenticated)return;
  const role=String(state.authUser?.role||'').toUpperCase();
  if(!['ADMIN','SUPER_ADMIN'].includes(role)){toast('Bạn không có quyền quản lý tài khoản.',true);navigate('dashboard');return;}
  renderAdminSecurity({user:state.authUser});
  await loadRbacAdmin();
}

async function requestAdminSecurityOtp(method){
  const mode=String(method||'').toUpperCase();
  const destination=mode==='SMS'?($('#adminSecurityPhone')?.value?.trim()||''):($('#adminSecurityEmail')?.value?.trim()||'');
  const display_name=$('#adminSecurityDisplayName')?.value?.trim()||state.authUser?.display_name||'';
  if(!destination){toast(mode==='SMS'?'Hãy nhập số điện thoại.':'Hãy nhập Email.',true);return;}
  const button=mode==='SMS'?$('#adminSecurityVerifyPhone'):$('#adminSecurityVerifyEmail');if(button)button.disabled=true;
  try{
    const out=await api('/api/v1/auth/admin-security/request-otp',{method:'POST',body:JSON.stringify({method:mode,destination,display_name})});
    state.adminSecurityChallenge=String(out.challenge_id||'');state.adminSecurityMethod=mode;
    if(!state.adminSecurityChallenge)throw new Error('Không nhận được phiên OTP.');
    $('#adminSecurityOtpBox')?.classList.remove('hidden');
    if($('#adminSecurityOtpTitle'))$('#adminSecurityOtpTitle').textContent=`Xác minh ${mode==='SMS'?'số điện thoại':'Email'}`;
    if($('#adminSecurityOtpHint'))$('#adminSecurityOtpHint').textContent=out?.demo_otp?`CHẾ ĐỘ DEMO — chưa gửi ra ngoài. OTP test: ${out.demo_otp}`:`OTP đã gửi tới ${out.destination_hint||destination}. Mã có hiệu lực 5 phút.`;
    if($('#adminSecurityOtp')){$('#adminSecurityOtp').value='';$('#adminSecurityOtp').focus();}
    if(out?.demo_otp)toast(`DEMO: OTP chưa được gửi qua ${mode==='SMS'?'SMS':'Email'}. Dùng mã hiển thị trên màn hình để test.`,true);else toast(`OTP đã được gửi qua ${mode==='SMS'?'SMS':'Email'}.`);
  }catch(e){toast(e.message||'Không thể gửi OTP.',true);}
  finally{if(button)button.disabled=false;}
}
async function verifyAdminSecurityOtp(){
  const btn=$('#adminSecurityOtpVerify');if(btn)btn.disabled=true;
  try{
    if(!state.adminSecurityChallenge)throw new Error('Hãy gửi OTP trước.');
    const otp=$('#adminSecurityOtp')?.value?.trim()||'';if(!/^\d{6}$/.test(otp))throw new Error('Hãy nhập mã OTP 6 số.');
    const out=await api('/api/v1/auth/admin-security/verify-otp',{method:'POST',body:JSON.stringify({challenge_id:state.adminSecurityChallenge,otp})});
    state.adminSecurityChallenge='';state.adminSecurityMethod='';$('#adminSecurityOtpBox')?.classList.add('hidden');
    if(out?.user){state.authUser={...(state.authUser||{}),...out.user};applyRoleUi(state.authUser);}
    await loadAdminSecurityProfile();toast('Đã xác minh. OTP hai lớp sẽ áp dụng từ lần đăng nhập tiếp theo.');
    const status=await api('/api/v1/auth/status');if(status?.user){state.authUser=status.user;applyRoleUi(state.authUser);}
  }catch(e){toast(e.message||'OTP không hợp lệ.',true);}
  finally{if(btn)btn.disabled=false;}
}
function cancelAdminSecurityOtp(){state.adminSecurityChallenge='';state.adminSecurityMethod='';$('#adminSecurityOtpBox')?.classList.add('hidden');if($('#adminSecurityOtp'))$('#adminSecurityOtp').value='';}

function otpProviderPayload(){
  return {
    sms:{
      enabled:!!$('#otpSmsEnabled')?.checked,
      provider:String($('#otpSmsProvider')?.value||'DEMO').toUpperCase(),
      webhook_url:$('#otpSmsWebhookUrl')?.value?.trim()||'',
      account_sid:$('#otpSmsAccountSid')?.value?.trim()||'',
      sender:$('#otpSmsSender')?.value?.trim()||'',
      secret:$('#otpSmsSecret')?.value||'',
    },
    email:{
      enabled:!!$('#otpEmailEnabled')?.checked,
      provider:String($('#otpEmailProvider')?.value||'DEMO').toUpperCase(),
      host:$('#otpSmtpHost')?.value?.trim()||'',
      port:Number($('#otpSmtpPort')?.value||587),
      username:$('#otpSmtpUsername')?.value?.trim()||'',
      from_email:$('#otpSmtpFrom')?.value?.trim()||'',
      password:$('#otpSmtpPassword')?.value||'',
      ssl:!!$('#otpSmtpSsl')?.checked,
      starttls:!!$('#otpSmtpStarttls')?.checked,
    }
  };
}
async function saveOtpProviderConfig(silent=false){
  const btn=$('#otpProviderSave');if(btn)btn.disabled=true;
  try{
    const out=await api('/api/v1/auth/admin-security/otp-provider',{method:'PUT',body:JSON.stringify(otpProviderPayload())});
    renderOtpProviderConfig({...out,user:state.authUser});
    if(!silent)toast('Đã lưu cấu hình nhà cung cấp OTP.');
    return out;
  }catch(e){if(!silent)toast(e.message||'Không lưu được cấu hình OTP.',true);throw e;}
  finally{if(btn)btn.disabled=false;}
}
async function testOtpProvider(method){
  const mode=String(method||'').toUpperCase();
  const btn=mode==='SMS'?$('#otpSmsTestBtn'):$('#otpEmailTestBtn');if(btn)btn.disabled=true;
  try{
    await saveOtpProviderConfig(true);
    const destination=mode==='SMS'?($('#otpSmsTestDestination')?.value?.trim()||''):($('#otpEmailTestDestination')?.value?.trim()||'');
    if(!destination)throw new Error(mode==='SMS'?'Hãy nhập số điện thoại test.':'Hãy nhập Email test.');
    const out=await api('/api/v1/auth/admin-security/otp-provider/test',{method:'POST',body:JSON.stringify({method:mode,destination})});
    if(out?.demo_otp)toast(`Provider đang DEMO. OTP test: ${out.demo_otp}`,true);else toast(`Đã gửi OTP thử qua ${mode==='SMS'?'SMS':'Email'} tới ${out.destination_hint||destination}.`);
    await loadAdminSecurityProfile();
  }catch(e){toast(e.message||'Gửi thử OTP thất bại.',true);}
  finally{if(btn)btn.disabled=false;}
}

async function refreshSystemDiagnostics(){
  if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.diagnostics')||state.systemDiagController)return;
  const controller=new AbortController(),epoch=state.systemDiagEpoch;state.systemDiagController=controller;
  try{
    const data=await api('/api/v1/system/diagnostics',{signal:controller.signal,timeoutMs:8000});
    if(controller.signal.aborted||epoch!==state.systemDiagEpoch||state.activePage!=='system'||!appPresentationActive()||!hasUiPermission('system.diagnostics'))return;
    renderDiagnostics(data);return data;
  }finally{if(state.systemDiagController===controller)state.systemDiagController=null;}
}
async function loadSystemPage(startTimer=true){
  if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.health'))return;
  return BTMHRuntime.once('system-page-load',async()=>{
  if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.health'))return;
  const epoch=state.systemDiagEpoch;
  const auth=await loadAuthStatus();
  if(epoch!==state.systemDiagEpoch||!appPresentationActive()||state.activePage!=='system')return;
  await Promise.all([loadCameraSettings(),BTMHRuntime.once('system-summary',loadSystemSummary),loadSystemAudit(),loadTechnicalHistory(),loadProductionStatus(),loadRecordingStatus()]);
  if(epoch!==state.systemDiagEpoch||!appPresentationActive()||state.activePage!=='system')return;
  try{await refreshSystemDiagnostics()}catch(e){if(e.name!=='AbortError')toast('Không tải được sức khỏe hệ thống.',true)}
  if(auth?.authenticated){await Promise.all([loadBackups(),loadMobileViewerAccess(),hasUiPermission('system.manage')?loadEdgeChainAdmin():Promise.resolve()]);if(hasUiPermission('account.approve'))await loadRbacAdmin();}
  else{if($('#backupList'))$('#backupList').innerHTML='<div class="empty-card">Đăng nhập Admin để quản lý backup.</div>';}
  if(startTimer&&appPresentationActive()&&state.activePage==='system'&&!state.systemTimer){state.systemTimer=setInterval(()=>{
    if(!appPresentationActive()||state.activePage!=='system'||!hasUiPermission('system.diagnostics'))return;
    void BTMHRuntime.once('system-health-refresh',async()=>{
      const epoch=state.systemDiagEpoch;await refreshSystemDiagnostics();
      if(epoch!==state.systemDiagEpoch||!appPresentationActive()||state.activePage!=='system')return;
      await Promise.all([BTMHRuntime.once('system-summary',loadSystemSummary),hasUiPermission('system.manage')?loadProductionStatus():Promise.resolve(),hasUiPermission('system.manage')?loadEdgeChainAdmin():Promise.resolve()]);
    }).catch(()=>{});
  },10000);}
  }).catch(e=>{if(e.name!=='AbortError')throw e;});
}

function hrReportParams(){
  const anchor=$('#hrReportAnchor')?.value||localDateInput();
  const period=state.hrReportPeriod||'day';
  return {period,anchor,query:`period=${encodeURIComponent(period)}&anchor=${encodeURIComponent(anchor)}`};
}
function hrReportStatusClass(status=''){
  const s=String(status||'').toLowerCase();
  if(s.includes('đúng giờ')||s==='có mặt')return 'good';
  if(s.includes('muộn')||s.includes('sớm'))return 'warn';
  if(s.includes('vắng'))return 'bad';
  return 'muted';
}
function applyHrShiftPolicy(policy={}){
  if($('#hrShiftEnabled'))$('#hrShiftEnabled').checked=!!policy.enabled;
  if($('#hrShiftName'))$('#hrShiftName').value=policy.name||'Ca hành chính';
  if($('#hrShiftStart'))$('#hrShiftStart').value=policy.start_time||'08:00';
  if($('#hrShiftEnd'))$('#hrShiftEnd').value=policy.end_time||'17:30';
  if($('#hrShiftBreakStart'))$('#hrShiftBreakStart').value=policy.break_start||'12:00';
  if($('#hrShiftBreakEnd'))$('#hrShiftBreakEnd').value=policy.break_end||'13:30';
  if($('#hrShiftLateGrace'))$('#hrShiftLateGrace').value=Number(policy.late_grace_minutes??10);
  if($('#hrShiftEarlyGrace'))$('#hrShiftEarlyGrace').value=Number(policy.early_leave_grace_minutes??10);
  const workdays=new Set((policy.workdays||[0,1,2,3,4]).map(Number));
  $$('[data-workday]').forEach(el=>el.checked=workdays.has(Number(el.dataset.workday)));
  const info=$('#hrShiftState');if(info){info.classList.toggle('active',!!policy.enabled);info.textContent=policy.enabled?`${policy.name||'Ca làm việc'} · ${policy.start_time||'08:00'}–${policy.end_time||'17:30'} · cho phép muộn ${Number(policy.late_grace_minutes||0)} phút`:'Chưa bật quy tắc ca làm việc. Báo cáo vẫn tổng hợp hiện diện nhưng không kết luận đi muộn/rời sớm.';}
}
function renderHrReportRows(){
  const body=$('#hrReportBody');if(!body)return;const rows=state.hrReportData?.rows||[],q=String($('#hrReportSearch')?.value||'').trim().toLowerCase();
  const filtered=rows.filter(r=>!q||`${r.full_name||''} ${r.employee_code||''} ${r.department||''}`.toLowerCase().includes(q));
  if(!filtered.length){body.innerHTML='<tr><td colspan="9" class="empty-card">Không có dữ liệu phù hợp.</td></tr>';return;}
  body.innerHTML=filtered.map(r=>`<tr><td><div class="hr-report-person"><b>${escapeHtml(r.full_name||'—')}</b><small>${escapeHtml(r.employee_code||'—')} · ${escapeHtml(r.department||'Chưa có phòng ban')}</small></div></td><td>${escapeHtml(r.first_seen||'—')}</td><td>${escapeHtml(r.last_seen||'—')}</td><td><b>${escapeHtml(r.presence_text||'0h 00p')}</b></td><td>${escapeHtml(r.outside_text||'0h 00p')}</td><td>${Number(r.session_count||0)}</td><td>${Number(r.out_count||0)}</td><td>${Number(r.late_days||0)}</td><td><span class="hr-report-status ${hrReportStatusClass(r.status)}">${escapeHtml(r.status||'—')}</span></td></tr>`).join('');
}
async function loadHrReport(){
  if(!$('#hrReportAnchor')?.value&&$('#hrReportAnchor'))$('#hrReportAnchor').value=localDateInput();
  const {query}=hrReportParams();const body=$('#hrReportBody');if(body)body.innerHTML='<tr><td colspan="9" class="empty-card">Đang tải báo cáo...</td></tr>';
  try{const data=await api(`/api/v1/hr-report/summary?${query}`);state.hrReportData=data;const t=data.totals||{};
    if($('#hrReportRange'))$('#hrReportRange').textContent=data.label||'—';if($('#hrReportEmployeeCount'))$('#hrReportEmployeeCount').textContent=Number(t.employee_count||0);if($('#hrReportPresentCount'))$('#hrReportPresentCount').textContent=`${Number(t.present_employees||0)} có mặt · ${Number(t.absent_employees||0)} chưa ghi nhận`;if($('#hrReportPresence'))$('#hrReportPresence').textContent=t.presence_text||'0h 00p';if($('#hrReportOutside'))$('#hrReportOutside').textContent=t.outside_text||'0h 00p';if($('#hrReportOutCount'))$('#hrReportOutCount').textContent=`${Number(t.out_events||0)} lượt OUT`;if($('#hrReportLate'))$('#hrReportLate').textContent=Number(t.late_cases||0);if($('#hrReportEarly'))$('#hrReportEarly').textContent=`${Number(t.early_leave_cases||0)} rời sớm`;
    applyHrShiftPolicy(data.shift_policy||{});renderHrReportRows();
  }catch(e){if(body)body.innerHTML=`<tr><td colspan="9" class="empty-card">${escapeHtml(e.message)}</td></tr>`;toast(e.message,true);}
}
async function saveHrShiftPolicy(ev){
  ev?.preventDefault();const workdays=$$('[data-workday]').filter(x=>x.checked).map(x=>Number(x.dataset.workday));const payload={enabled:!!$('#hrShiftEnabled')?.checked,name:$('#hrShiftName')?.value||'Ca hành chính',start_time:$('#hrShiftStart')?.value||'08:00',end_time:$('#hrShiftEnd')?.value||'17:30',break_start:$('#hrShiftBreakStart')?.value||'12:00',break_end:$('#hrShiftBreakEnd')?.value||'13:30',late_grace_minutes:Number($('#hrShiftLateGrace')?.value||0),early_leave_grace_minutes:Number($('#hrShiftEarlyGrace')?.value||0),workdays};
  try{const out=await api('/api/v1/hr-report/shift',{method:'PUT',body:JSON.stringify(payload)});applyHrShiftPolicy(out.policy||payload);toast('Đã lưu quy tắc ca làm việc.');await loadHrReport();}catch(e){toast(e.message,true);}
}
async function exportHrReportXlsx(){
  const {query,period,anchor}=hrReportParams(),token=localStorage.getItem('campusface_token')||'';try{const res=await fetch(`/api/v1/hr-report/export.xlsx?${query}`,{headers:token?{'Authorization':`Bearer ${token}`}:{}});if(!res.ok)throw new Error(`Không xuất được Excel (HTTP ${res.status})`);const blob=await res.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`CampusFace_HR_${period}_${anchor}.xlsx`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1500);}catch(e){toast(e.message,true);}
}
function exportHrReportPdf(){const {query}=hrReportParams();window.open(`/api/v1/hr-report/print?${query}`,'_blank','noopener');}

let authUiBound=false;
function bindAuthUI(){
  if(authUiBound)return;authUiBound=true;
  bindAccountMenuUI();
  const remembered=localStorage.getItem('btmh_remembered_username')||'';
  if(remembered&&$('#gateLoginUsername')){$('#gateLoginUsername').value=remembered;if($('#gateRememberUsername'))$('#gateRememberUsername').checked=true;}
  $('#gateLoginForm')?.addEventListener('submit',gateLogin);
  $('#gateSetupForm')?.addEventListener('submit',gateBootstrap);
  $('#gateOpenLoginBtn')?.addEventListener('click',()=>setGateAuthMode('login'));
  $('#gateOpenRegistrationBtn')?.addEventListener('click',()=>setGateAuthMode('registration'));
  $('#gateOpenSetupBtn')?.addEventListener('click',()=>setGateAuthMode('setup'));
  $('#gateEnrollmentForm')?.addEventListener('submit',gateOpenEnrollment);
  $('#openForgotBtn')?.addEventListener('click',()=>setGateAuthMode('forgot'));
  $('#forgotBackLoginBtn')?.addEventListener('click',()=>setGateAuthMode('login'));
  $('#forgotReturnBtn')?.addEventListener('click',()=>setGateAuthMode('login'));
  $('#gateMfaVerifyBtn')?.addEventListener('click',gateMfaVerify);
  $('#gateMfaCode')?.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();gateMfaVerify();}});
  $('#gateMfaCancelBtn')?.addEventListener('click',gateMfaCancel);
  $('#gateMfaCopySecret')?.addEventListener('click',()=>copyTextValue($('#gateMfaSecret')?.textContent||'','Đã sao chép khóa thiết lập.'));
  $('#gateMfaCopyRecovery')?.addEventListener('click',()=>copyTextValue((state.mfaRecoveryCodes||[]).join('\n'),'Đã sao chép mã khôi phục.'));
  $('#gateMfaContinueBtn')?.addEventListener('click',finishMfaLogin);
}

function bindUI(){
  $('#cameraConnectionDetails')?.addEventListener('toggle',()=>{if($('#cameraConnectionDetails').open)void loadCameraSettings();else{state.systemSettingsController?.abort();state.systemSettingsController=null;if($('#camSource'))$('#camSource').value='';}});
  $('#systemTechnicalDetails')?.addEventListener('toggle',()=>{if($('#systemTechnicalDetails').open)void loadTechnicalHistory();else{state.systemTechnicalController?.abort();state.systemTechnicalController=null;$('#systemTechnicalList')?.replaceChildren();}});
  if($('#hrReportAnchor'))$('#hrReportAnchor').value=localDateInput();
  $$('#hrReportPeriodTabs [data-period]').forEach(btn=>btn.addEventListener('click',()=>{state.hrReportPeriod=btn.dataset.period||'day';$$('#hrReportPeriodTabs [data-period]').forEach(x=>x.classList.toggle('active',x===btn));loadHrReport();}));
  $('#hrReportAnchor')?.addEventListener('change',loadHrReport);$('#hrReportRefresh')?.addEventListener('click',loadHrReport);$('#hrReportSearch')?.addEventListener('input',renderHrReportRows);$('#hrShiftForm')?.addEventListener('submit',saveHrShiftPolicy);$('#hrReportExportXlsx')?.addEventListener('click',exportHrReportXlsx);$('#hrReportExportPdf')?.addEventListener('click',exportHrReportPdf);
  bindNavigation();startClock();setupCameraPresetUi();
  $('#attendanceSessionForm')?.addEventListener('submit',createAttendanceSession);$('#attendanceAdjustForm')?.addEventListener('submit',submitAttendanceAdjust);$('#attendanceAdjustClose')?.addEventListener('click',closeAttendanceAdjust);$('#attendanceAdjustCancel')?.addEventListener('click',closeAttendanceAdjust);$('#attendanceAdjustBackdrop')?.addEventListener('click',closeAttendanceAdjust);$('#attendanceRefresh')?.addEventListener('click',loadAttendancePage);$('#attendanceExport')?.addEventListener('click',exportAttendanceSession);$('#attendanceClose')?.addEventListener('click',closeAttendanceSession);$('#attendanceNewToggle')?.addEventListener('click',()=>$('#attendanceCreateCard')?.scrollIntoView({behavior:'smooth',block:'start'}));
  bindAuthUI();$('#v5ShiftForm')?.addEventListener('submit',saveV5Shift);$('#v5ShiftAssignForm')?.addEventListener('submit',assignV5Shift);$('#v5ShiftRefresh')?.addEventListener('click',loadV5ShiftWorkspace);$('#v5AttendanceCorrectionForm')?.addEventListener('submit',saveV5AttendanceCorrection);$('#v5IncidentRefresh')?.addEventListener('click',loadV5Incidents);$('#v5NewIncidentBtn')?.addEventListener('click',openV5IncidentModal);$('#v5IncidentForm')?.addEventListener('submit',createV5Incident);$('#v5IncidentClose')?.addEventListener('click',closeV5IncidentModal);$('#v5IncidentCancel')?.addEventListener('click',closeV5IncidentModal);$('#v5IncidentBackdrop')?.addEventListener('click',closeV5IncidentModal);$('#systemSelfTest')?.addEventListener('click',runSelfTest);$('#runtimeRefresh')?.addEventListener('click',runSelfTest);$('#cameraSettingsForm')?.addEventListener('submit',saveCameraSettingsUi);$('#authSetupBtn')?.addEventListener('click',setupAdmin);$('#authLoginBtn')?.addEventListener('click',loginSystem);$('#authLogoutBtn')?.addEventListener('click',logoutSystem);$('#adminSecurityVerifyPhone')?.addEventListener('click',()=>requestAdminSecurityOtp('SMS'));$('#adminSecurityVerifyEmail')?.addEventListener('click',()=>requestAdminSecurityOtp('EMAIL'));$('#adminSecurityOtpVerify')?.addEventListener('click',verifyAdminSecurityOtp);$('#adminSecurityOtpCancel')?.addEventListener('click',cancelAdminSecurityOtp);$('#otpProviderSave')?.addEventListener('click',()=>saveOtpProviderConfig(false));$('#otpSmsTestBtn')?.addEventListener('click',()=>testOtpProvider('SMS'));$('#otpEmailTestBtn')?.addEventListener('click',()=>testOtpProvider('EMAIL'));$('#otpSmsProvider')?.addEventListener('change',updateOtpProviderFieldVisibility);$('#otpEmailProvider')?.addEventListener('change',updateOtpProviderFieldVisibility);$('#otpSmtpSsl')?.addEventListener('change',()=>{if($('#otpSmtpSsl')?.checked&&$('#otpSmtpStarttls'))$('#otpSmtpStarttls').checked=false;});$('#otpSmtpStarttls')?.addEventListener('change',()=>{if($('#otpSmtpStarttls')?.checked&&$('#otpSmtpSsl'))$('#otpSmtpSsl').checked=false;});$('#backupCreate')?.addEventListener('click',createBackupUi);$('#backupImportBtn')?.addEventListener('click',importBackupUi);$('#mobileViewerForm')?.addEventListener('submit',saveMobileViewerAccess);$('#mobileCopyUrl')?.addEventListener('click',copyMobileViewerUrl);$('#v210ProductionForm')?.addEventListener('submit',saveProductionPolicy);$('#v210CheckNow')?.addEventListener('click',()=>loadProductionStatus(true).then(()=>toast('Đã kiểm tra trạng thái vận hành.')).catch(e=>toast(e.message,true)));$('#v210RecoverCamera')?.addEventListener('click',recoverProductionCamera);
  $('#v53EdgeRefresh')?.addEventListener('click',loadEdgeChainAdmin);$('#v53EdgePairingForm')?.addEventListener('submit',registerEdgeNodeAdmin);$('#v53EdgePairingFile')?.addEventListener('change',readEdgePairingFile);
  $('#visitorRefresh')?.addEventListener('click',loadVisitors);$('#visitorStatusFilter')?.addEventListener('change',loadVisitors);$('#rbacRefresh')?.addEventListener('click',loadRbacAdmin);$('#rbacCreateForm')?.addEventListener('submit',createRbacUser);
  $('#cameraTestCurrent')?.addEventListener('click',testCurrentCamera);$('#cameraReconnect')?.addEventListener('click',reconnectCamera);$('#v13MonitorRefresh')?.addEventListener('click',()=>{loadV13MonitorDevices();loadV13Performance();});$('#v12OpsRefresh')?.addEventListener('click',loadOpsCenter);$('#v12CameraDeviceForm')?.addEventListener('submit',createOpsCamera);$('#v12RulesForm')?.addEventListener('submit',saveOpsRules);$('#v12ExceptionRefresh')?.addEventListener('click',loadOpsExceptions);$('#v12ExceptionFilter')?.addEventListener('change',loadOpsExceptions);$('#studentExportBtn')?.addEventListener('click',exportStudents);$('#studentTemplateBtn')?.addEventListener('click',downloadStudentTemplate);$('#camSource')?.addEventListener('input',()=>syncCameraPresetUi(cameraPresetFromSource($('#camSource').value)));
  $$('[data-ptz]').forEach(btn=>btn.addEventListener('click',()=>sendCameraControl(btn.dataset.ptz)));$('#cameraControlSpeed')?.addEventListener('input',e=>{if($('#cameraControlSpeedLabel'))$('#cameraControlSpeedLabel').textContent=`${e.target.value}%`;});
  $('#faculty')?.addEventListener('change',e=>fillMajorOptions('#major',e.target.value));$('#newStudentFaculty')?.addEventListener('change',e=>fillMajorOptions('#newStudentMajor',e.target.value));
  $('#studentForm')?.addEventListener('submit',async e=>{
    e.preventDefault();const btn=e.currentTarget?.querySelector('button[type="submit"]');const oldText=btn?.textContent||'';if(btn){btn.disabled=true;btn.textContent='Đang lưu hồ sơ...';}
    try{
      if(!Number($('#enrollmentStoreSelect')?.value||0))throw new Error('Chọn cửa hàng đăng ký trước khi lưu và quét.');
      const s=await api('/api/v1/students',{method:'POST',body:JSON.stringify({student_code:$('#studentCode').value.trim(),full_name:$('#fullName').value.trim(),class_name:$('#className').value.trim(),faculty:$('#faculty').value||'',email:$('#email').value.trim(),phone:$('#phone').value.trim(),consent:$('#consent').checked})});
      state.enrollStudentId=Number(s.id);state.enrollStudentProfile=s;toast('Đã lưu hồ sơ nhân viên · đang mở quét FaceID.');
      // Do not wait for a full employee-list refresh before opening STEP 02. The POST
      // response is the authoritative newly-created profile and carries the new id.
      await beginFaceIdSetup(s);
      loadStudents().then(()=>{const sel=$('#enrollStudentSelect');if(sel)sel.value=String(s.id);}).catch(console.warn);
    }catch(e2){toast(e2.message,true)}finally{if(btn){btn.disabled=false;btn.textContent=oldText||'Lưu hồ sơ & chuyển sang quét FaceID →';}}
  });
  $('#enrollStudentSelect')?.addEventListener('change',e=>{state.enrollStudentId=Number(e.target.value)||null;state.enrollStudentProfile=state.students.find(s=>Number(s.id)===Number(state.enrollStudentId))||null;if($('#startExistingFaceBtn'))$('#startExistingFaceBtn').disabled=!state.enrollStudentId||!canManageEnrollment();syncQREnrollmentPanel();});
  $('#reviewEnrollmentBtn')?.addEventListener('click',()=>{setEnrollPhase(false);syncQREnrollmentPanel();$('#qrEnrollmentPanel')?.scrollIntoView({behavior:'smooth',block:'start'});});
  $('#startExistingFaceBtn')?.addEventListener('click',beginFaceIdSetup);$('#backToProfileBtn')?.addEventListener('click',()=>{clearInterval(state.enrollTimer);state.enrollTimer=null;setEnrollPhase(false)});$('#resetEnrollBtn')?.addEventListener('click',resetEnrollment);$('#finalizeEnrollBtn')?.addEventListener('click',()=>finalizeEnrollment(false));$('#scanAnotherBtn')?.addEventListener('click',()=>{clearInterval(state.enrollTimer);state.enrollTimer=null;state.enrollStudentId=null;state.enrollStudentProfile=null;setEnrollPhase(false);resetFaceIdUI();refreshEnrollSelect()});$('#goRecognitionBtn')?.addEventListener('click',()=>navigate('recognition'));$('#v5ValidateStoreCameraBtn')?.addEventListener('click',validateEnrollmentOnStoreCamera);$('#v5DuplicateFaceConfirm')?.addEventListener('click',confirmFaceDuplicateEnrollment);$('#v5DuplicateFaceCancel')?.addEventListener('click',()=>closeFaceDuplicateReview(true));$('#v5DuplicateFaceBackdrop')?.addEventListener('click',()=>closeFaceDuplicateReview(true));
  $('#studentSearch')?.addEventListener('input',()=>{state.studentPage=1;renderStudents()});$('#studentSearchButton')?.addEventListener('click',()=>renderStudents());$('#studentFacultyFilter')?.addEventListener('change',()=>renderStudents());$('#studentClassFilter')?.addEventListener('change',()=>renderStudents());$('#studentFaceFilter')?.addEventListener('change',()=>renderStudents());$('#studentFilterToggle')?.addEventListener('click',()=>$('#studentFilterPanel')?.classList.toggle('hidden'));$('#studentClearFilter')?.addEventListener('click',()=>{['#studentSearch','#studentFacultyFilter','#studentClassFilter','#studentFaceFilter'].forEach(s=>{if($(s))$(s).value=''});renderStudents()});$('#studentPrevPage')?.addEventListener('click',()=>{state.studentPage--;renderStudents()});$('#studentNextPage')?.addEventListener('click',()=>{state.studentPage++;renderStudents()});$('#studentLmsRefreshBtn')?.addEventListener('click',loadStudents);$('#studentAddBtn')?.addEventListener('click',()=>$('#studentCreateModal')?.classList.remove('hidden'));$('#studentCreateClose')?.addEventListener('click',closeStudentCreate);$('#studentCreateCancel')?.addEventListener('click',closeStudentCreate);$('#studentCreateBackdrop')?.addEventListener('click',closeStudentCreate);$('#studentCreateForm')?.addEventListener('submit',createStudentFromModal);$('#studentBackBtn')?.addEventListener('click',showStudentList);$$('#studentProfileTabs [data-student-tab]').forEach(b=>b.addEventListener('click',()=>setStudentProfileTab(b.dataset.studentTab||'detail')));
  $$('.student-menu-item').forEach(b=>b.addEventListener('click',()=>{state.studentScope=b.dataset.studentScope||'ALL';state.studentPage=1;$$('.student-menu-item').forEach(x=>x.classList.toggle('active',x===b));renderStudents()}));
  $('#recognitionHistoryRefresh')?.addEventListener('click',loadRecognitionHistory);$('#v20HistoryRefresh')?.addEventListener('click',loadHistory);$('#v20DashboardRefresh')?.addEventListener('click',loadDashboard);
  $$('.prod-history-quick button').forEach(b=>b.addEventListener('click',()=>{const days=Number(b.dataset.days||0);const end=new Date(),start=new Date();start.setDate(end.getDate()-days);if($('#v22HistoryStart'))$('#v22HistoryStart').value=localDateInput(start);if($('#v22HistoryEnd'))$('#v22HistoryEnd').value=localDateInput(end);$$('.prod-history-quick button').forEach(x=>x.classList.toggle('active',x===b));renderHistoryDashboard()}));
  $$('#historyModeTabs [data-history-mode]').forEach(b=>b.addEventListener('click',()=>{state.historyMode=b.dataset.historyMode||'RECOGNITION';renderHistoryDashboard();}));
  $$('#historyRecognitionTabs [data-history-tab]').forEach(b=>b.addEventListener('click',()=>{state.historyRecognitionTab=b.dataset.historyTab||'ALL';$$('#historyRecognitionTabs [data-history-tab]').forEach(x=>x.classList.toggle('active',x===b));renderRecognitionHistory();}));
  $$('#historyHrTabs [data-history-tab]').forEach(b=>b.addEventListener('click',()=>{state.historyHrTab=b.dataset.historyTab||'ALL';$$('#historyHrTabs [data-history-tab]').forEach(x=>x.classList.toggle('active',x===b));renderHrHistory();}));
  $('#historyDetailClose')?.addEventListener('click',closeHistoryDetail);$('#historyDetailBackdrop')?.addEventListener('click',closeHistoryDetail);$('#v21HistoryExport')?.addEventListener('click',exportHistoryCsv);
  ['#v22HistoryStart','#v22HistoryEnd','#v20HistoryClass','#v22HistorySearch'].forEach(sel=>$(sel)?.addEventListener(sel==='#v22HistorySearch'?'input':'change',()=>renderHistoryDashboard()));
  if($('#v22HistoryStart'))$('#v22HistoryStart').value=localDateInput();if($('#v22HistoryEnd'))$('#v22HistoryEnd').value=localDateInput();
}

let professionalRuntimeStarted=false;
async function bootAuthenticated(){
  if(!appPresentationActive())return;
  if(professionalRuntimeStarted){startAppPolling();navigate('dashboard');return;}professionalRuntimeStarted=true;
  startAppPolling();
  navigate('dashboard');
  const tasks=[loadHealth(),loadDashboard()];
  if(hasUiPermission('employee.view'))tasks.push(loadStudents(),loadRecognitionHistory());
  const results=await Promise.allSettled(tasks);
  if(!appPresentationActive())return;
  const rejected=results.find(x=>x.status==='rejected');
  if(rejected)console.warn('[BTMH] optional authenticated preload failed:',rejected.reason);
}
async function boot(){
  bindAuthUI();
  try{buildScanTicks();bindUI();resetFaceIdUI();}catch(e){console.error('[BTMH] non-auth UI bootstrap error:',e);}
  const auth=await ensureProfessionalAuth();
  if(auth?.authenticated)await bootAuthenticated();
}
boot();

function appPresentationActive(){
  return !!state.authUser&&!document.hidden&&!state.presentationSuspended&&state.pagePresented!==false;
}
function appCurrentPageAllowed(){
  const permissions={dashboard:'dashboard.view',students:'employee.view','work-shifts':'attendance.manage',
    incidents:'incident.view',visitors:'visitor.view',register:'employee.enroll',recognition:'camera.live',
    history:'history.view',operations:'attendance.view','hr-report':'hr.report','live-grid':'camera.live',
    'live-monitor':'camera.live',playback:'camera.playback','camera-control':'camera.live',
    'ops-center':'camera.live',system:'system.health'};
  if(state.activePage==='admin-security')return ['ADMIN','SUPER_ADMIN'].includes(String(state.authUser?.role||'').toUpperCase());
  return !!permissions[state.activePage]&&hasUiPermission(permissions[state.activePage]);
}
function pauseAppPresentation(reason='hidden'){
  stopQREnrollmentPanels();
  if(!state.presentationSuspended){
    state.suspendedEnrollment=!!state.authUser&&state.activePage==='register'&&state.enrollTimer
      &&state.enrollSession&&state.enrollStudentId&&hasUiPermission('employee.enroll')
      &&$('#registrationFacePhase')?.classList.contains('active')
      ?{session:state.enrollSession,student:state.enrollStudentId}:null;
  }
  state.presentationSuspended=true;state.presentationEpoch++;
  window.BTMHManagement?.stop?.();
  window.BTMHRecentRecognition?.stop?.();
  window.BTMHDemoReports?.stop?.();
  window.BTMHCameraConfiguration?.stop?.();
  clearInterval(state.enrollTimer);state.enrollTimer=null;state.enrollRequestController?.abort();state.enrollRequestController=null;state.enrollBusy=false;
  stopAppPolling();
  stopV13OpsSocket();stopV13LiveMonitor();stopV13DashboardPreview();pauseSystemCameraPreview();stopCameraControlView();
  pauseCameraPreview('enroll');pauseCameraPreview('recognition');BTMHRuntime.stopAll();window.BTMHMedia?.stopAll?.();
  window.BTMHV4?.leavePage?.(reason);window.BTMHV4?.stopEnrollmentBrowserCamera?.();
}
async function resumeAppPresentation(){
  if(!state.presentationSuspended||document.hidden||state.pagePresented===false||!state.authUser)return;
  state.presentationSuspended=false;state.presentationEpoch++;
  if(!appCurrentPageAllowed()){state.suspendedEnrollment=null;return;}
  if(!professionalRuntimeStarted){await bootAuthenticated();return;}
  startAppPolling();
  const page=state.activePage,epoch=state.presentationEpoch,proof=state.suspendedEnrollment;
  if(page!=='register'){state.suspendedEnrollment=null;navigate(page);return;}
  syncQREnrollmentPanel();
  const ready=await prepareEnrollmentLaptopCamera();
  if(!ready||!appPresentationActive()||epoch!==state.presentationEpoch||state.activePage!==page||!hasUiPermission('employee.enroll'))return;
  if(proof&&proof.session===state.enrollSession&&proof.student===state.enrollStudentId
      &&$('#registrationFacePhase')?.classList.contains('active')&&!state.enrollCompleted&&!state.enrollFinalizing){state.suspendedEnrollment=null;startEnrollLoop();}
}
// Stop every page-owned presentation owner, including BFCache where hidden may
// remain false. Background attendance/recording services are independent.
document.addEventListener('visibilitychange',()=>{
  if(document.hidden)pauseAppPresentation('hidden');else void Promise.resolve().then(resumeAppPresentation).catch(()=>{});
});
window.addEventListener('pagehide',()=>{state.pagePresented=false;pauseAppPresentation('closed');});
window.addEventListener('pageshow',()=>{state.pagePresented=true;void Promise.resolve().then(resumeAppPresentation).catch(()=>{});});

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const runtimeSource = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_runtime_v543.js'), 'utf8');
const v4Source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_v4.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve(); };
function productFunction(w,name) {
  const match=source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\{[\\s\\S]*?\n\\}`));
  assert.ok(match,`missing product function ${name}`);vm.runInContext(match[0],w.context);
}
function realRuntime(w) {
  vm.runInContext(runtimeSource,w.context);w.context.BTMHRuntime=w.context.window.BTMHRuntime;
}
function environment() {
  const state = {authUser: {}, activePage: 'system', systemDiagEpoch: 0, systemDiagController: null,
    systemTimer: 1, presentationSuspended: false, presentationEpoch: 0};
  const requests = [], rendered = [], cleared = [], image = {dataset: {started: '1'},removeAttribute(){}};
  const jobs = new Map(), timers = new Map(), calls = [], elements = new Map([
    ['#systemCameraPreview', image], ['#v53EdgeNodeList', {innerHTML: ''}],
    ['#registrationFacePhase', {classList: {contains: () => true}}],
  ]);
  let timerId = 10;
  const context = {state, document: Object.assign(new EventTarget(), {hidden: false}),
    window: Object.assign(new EventTarget(), {BTMHMedia: {stopAll: () => calls.push('media')},
      BTMHV4: {leavePage: reason => calls.push(reason), stopEnrollmentBrowserCamera: () => calls.push('webcam')}}),
    Event, AbortController, DOMException, permitted: true, professionalRuntimeStarted: true,
    hasUiPermission: () => context.permitted,
    $: selector => elements.get(selector) || null, $$: () => [],
    BTMHRuntime: {stopPreview() {}, stopAll: () => calls.push('preview'),
      once(key, work) {if(jobs.has(key))return jobs.get(key);const promise=Promise.resolve().then(work).finally(()=>{if(jobs.get(key)===promise)jobs.delete(key)});jobs.set(key,promise);return promise;},
      cancel: key => jobs.delete(key)},
    clearInterval: id => {cleared.push(id);timers.delete(id)},
    setInterval: callback => {const id=timerId++;timers.set(id,callback);return id},
    stopV13OpsSocket: () => calls.push('socket'), stopV13LiveMonitor: () => calls.push('monitor'),
    stopV13DashboardPreview: () => calls.push('dashboard'), stopCameraControlView: () => calls.push('ptz'),
    pauseCameraPreview: kind => calls.push(kind),
    navigate: page => calls.push(`navigate:${page}`),
    prepareEnrollmentLaptopCamera: async () => true, startEnrollLoop: () => calls.push('enroll-start'),
    renderProductionStatus: data => rendered.push(data), escapeHtml: value => String(value),
    drawEnrollBiometricOverlay: () => calls.push('enroll-render'), updateEnrollLock: () => calls.push('enroll-lock'),
    finalizeEnrollment: () => calls.push('enroll-finalize'), setSignal: () => {},
    renderDiagnostics: data => rendered.push(data),
    api: (url, options) => new Promise(resolve => requests.push({url, options, resolve})),
  };
  vm.createContext(context);
  // Load the production QR panel helpers used by presentation pause/resume.
  state.qrAdminViews = [{stop: () => calls.push('qr-admin')}];
  state.students = [];
  const qrHelpersStart = source.indexOf('function canManageEnrollment(){');
  const qrHelpersEnd = source.indexOf('async function loadEnrollmentStores(){');
  assert.ok(qrHelpersStart >= 0 && qrHelpersEnd > qrHelpersStart, 'missing production QR panel helpers');
  vm.runInContext(source.slice(qrHelpersStart, qrHelpersEnd), context);
  productFunction({context}, 'selectedEnrollStudent');
  for (const name of ['appPresentationActive','appCurrentPageAllowed','pauseAppPresentation','resumeAppPresentation',
    'refreshSystemDiagnostics', 'pauseSystemCameraPreview', 'loadProductionStatus', 'loadEdgeChainAdmin',
    'startClock','stopAppPolling','startAppPolling']) {
    const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\{[\\s\\S]*?\n\\}`));
    assert.ok(match, `missing product function ${name}`); vm.runInContext(match[0], context);
  }
  const lifecycle=source.slice(source.indexOf('// Stop every page-owned presentation owner'));
  vm.runInContext(lifecycle, context);
  return {context, state, requests, rendered, cleared, calls, timers, jobs, elements};
}
test('system health polling is authorized, visible and page scoped', async () => {
  for (const mutate of [w => w.context.permitted = false, w => w.context.document.hidden = true,
    w => w.state.authUser = null, w => w.state.activePage = 'dashboard']) {
    const w = environment(); mutate(w); await w.context.refreshSystemDiagnostics();
    assert.equal(w.requests.length, 0);
  }
});
test('slow system health requests have one owner and a bounded deadline', async () => {
  const w = environment(), first = w.context.refreshSystemDiagnostics();
  await w.context.refreshSystemDiagnostics(); await w.context.refreshSystemDiagnostics();
  assert.equal(w.requests.length, 1); assert.equal(w.requests[0].options.timeoutMs, 8000);
  w.requests[0].resolve({sample: 1}); await first;
  assert.deepEqual(w.rendered, [{sample: 1}]); assert.equal(w.state.systemDiagController, null);
});
test('navigation aborts old health owner without releasing or rendering the replacement', async () => {
  const w = environment(), old = w.context.refreshSystemDiagnostics();
  w.context.pauseSystemCameraPreview();
  assert.equal(w.requests[0].options.signal.aborted, true); assert.deepEqual(w.cleared, [1]);
  const current = w.context.refreshSystemDiagnostics(), owner = w.state.systemDiagController;
  w.requests[0].resolve({old: true}); await old; await flush();
  assert.equal(w.rendered.length, 0); assert.equal(w.state.systemDiagController, owner);
  w.requests[1].resolve({current: true}); await current;
  assert.deepEqual(w.rendered, [{current: true}]);
});

test('missing system preview markup cannot retain its polling timer', () => {
  const w=environment();w.elements.delete('#systemCameraPreview');w.context.pauseSystemCameraPreview();
  assert.equal(w.state.systemTimer,null);assert.deepEqual(w.cleared,[1]);
});

test('pagehide stops every presentation owner even when document.hidden remains false', () => {
  const w=environment();w.state.enrollTimer=2;const controller=new AbortController();w.state.enrollRequestController=controller;
  w.context.window.dispatchEvent(new Event('pagehide'));
  assert.equal(w.state.presentationSuspended,true);assert.equal(w.state.enrollTimer,null);
  assert.equal(w.state.systemTimer,null);assert.equal(controller.signal.aborted,true);
  for(const name of ['qr-admin','socket','monitor','dashboard','ptz','enroll','recognition','preview','media','closed','webcam'])assert.ok(w.calls.includes(name),name);
  assert.equal(w.state.qrAdminViews.length, 0);
});

test('pageshow resumes one authorized current page and repeated events do not duplicate navigation', async () => {
  const w=environment();w.context.window.dispatchEvent(new Event('pagehide'));
  w.context.window.dispatchEvent(new Event('pageshow'));w.context.window.dispatchEvent(new Event('pageshow'));await flush();
  assert.equal(w.calls.filter(x=>x==='navigate:system').length,1);assert.equal(w.state.presentationSuspended,false);
});

test('pageshow cannot restart unauthorized, signed out or still hidden presentation', async () => {
  for(const change of [w=>w.context.permitted=false,w=>w.state.authUser=null,w=>w.context.document.hidden=true]){
    const w=environment();w.context.window.dispatchEvent(new Event('pagehide'));change(w);
    w.context.window.dispatchEvent(new Event('pageshow'));await flush();
    assert.equal(w.calls.some(x=>x.startsWith('navigate:')),false);
  }
});

test('late authenticated status cannot clear a pagehide suspension or start runtime', async () => {
  const w=environment();w.context.window.dispatchEvent(new Event('pagehide'));
  w.context.applyRoleUi=()=>{};w.context.CustomEvent=class extends Event{constructor(type,init){super(type);this.detail=init.detail}};
  w.context.$=selector=>selector==='#authGate'?{classList:{toggle(){}}}:null;
  const match=source.match(/function setAuthGate\([^)]*\)\{[\s\S]*?\n\}/);vm.runInContext(match[0],w.context);
  w.context.setAuthGate({authenticated:true,user:{role:'ADMIN'}});
  assert.equal(w.state.presentationSuspended,true);assert.equal(w.context.appPresentationActive(),false);
  await w.context.resumeAppPresentation();assert.equal(w.calls.some(x=>x.startsWith('navigate:')),false);
});

test('production reads share one request owner and late hidden results cannot render', async () => {
  const w=environment(),first=w.context.loadProductionStatus(),second=w.context.loadProductionStatus();await flush();
  assert.equal(w.requests.length,1);assert.equal(w.requests[0].options.timeoutMs,8000);
  w.context.window.dispatchEvent(new Event('pagehide'));assert.equal(w.requests[0].options.signal.aborted,true);
  w.requests[0].resolve({hidden:true});await Promise.all([first,second]);
  assert.equal(w.rendered.length,0);
});

test('old production completion cannot release or render a newer BFCache owner', async () => {
  const w=environment(),old=w.context.loadProductionStatus();await flush();w.context.pauseSystemCameraPreview();
  const current=w.context.loadProductionStatus();await flush();const owner=w.state.systemProductionController;
  assert.equal(w.requests.length,2);w.requests[0].resolve({old:true});await old;
  assert.equal(w.state.systemProductionController,owner);assert.equal(w.rendered.length,0);
  w.requests[1].resolve({current:true});await current;assert.deepEqual(w.rendered,[{current:true}]);
});

test('manual check and periodic production owners are both aborted on pause', async () => {
  const w=environment(),read=w.context.loadProductionStatus(),check=w.context.loadProductionStatus(true);await flush();
  assert.equal(w.requests.length,2);assert.equal(w.requests[1].options.method,'POST');
  w.context.pauseSystemCameraPreview();assert.ok(w.requests.every(item=>item.options.signal.aborted));
  w.requests.forEach(item=>item.resolve({late:true}));await Promise.all([read,check]);assert.equal(w.rendered.length,0);
});

test('edge refreshes share one request and cannot retain privileged late markup after signout', async () => {
  const w=environment(),first=w.context.loadEdgeChainAdmin(),second=w.context.loadEdgeChainAdmin();await flush();
  assert.equal(w.requests.length,1);const host=w.elements.get('#v53EdgeNodeList');
  w.state.authUser=null;w.context.pauseAppPresentation('signed-out');w.requests[0].resolve({items:[{node_name:'late secret'}]});
  await Promise.all([first,second]);assert.equal(host.innerHTML,'');
});

test('paused work cancelled before its microtask cannot issue production or edge I/O', async () => {
  const w=environment(),production=w.context.loadProductionStatus(),edge=w.context.loadEdgeChainAdmin();
  w.context.pauseAppPresentation('closed');await Promise.all([production,edge]);assert.equal(w.requests.length,0);
});

test('legacy hidden metrics are never constructed, queried or rendered', () => {
  const w=environment(),original=w.context.$;
  w.context.$=selector=>{assert.notEqual(selector,'#runtimeMetrics');return original(selector)};
  const match=source.match(/function renderDiagnostics\([^)]*\)\{[\s\S]*?\n\}/);vm.runInContext(match[0],w.context);
  w.context.renderDiagnostics({camera:{},storage:{},checks:[]});assert.equal(w.state.systemDiag.checks.length,0);
});

test('enrollment resume requires same active session and prepared current camera', async () => {
  const w=environment();Object.assign(w.state,{activePage:'register',enrollTimer:2,enrollSession:'active-session',enrollStudentId:7});
  // Visibility is already hidden when its event runs; proof must still be retained.
  w.context.document.hidden=true;w.context.document.dispatchEvent(new Event('visibilitychange'));
  assert.equal(w.state.suspendedEnrollment.session,'active-session');
  w.context.document.hidden=false;await w.context.resumeAppPresentation();assert.equal(w.calls.filter(x=>x==='enroll-start').length,1);
});

test('changed enrollment session or late camera readiness cannot resume sample collection', async () => {
  for(const change of [w=>w.state.enrollSession='replaced',w=>w.state.enrollStudentId=8,w=>w.context.permitted=false]){
    const w=environment();Object.assign(w.state,{activePage:'register',enrollTimer:2,enrollSession:'session',enrollStudentId:7});
    w.context.pauseAppPresentation();change(w);await w.context.resumeAppPresentation();assert.equal(w.calls.includes('enroll-start'),false);
  }
  const w=environment();Object.assign(w.state,{activePage:'register',enrollTimer:2,enrollSession:'session',enrollStudentId:7});
  w.context.pauseAppPresentation();let ready;w.context.prepareEnrollmentLaptopCamera=()=>new Promise(resolve=>ready=resolve);
  const resume=w.context.resumeAppPresentation();w.context.pauseAppPresentation('closed');ready(true);await resume;
  assert.equal(w.calls.includes('enroll-start'),false);
});

test('late enrollment frame after pagehide cannot render or finalize identity enrollment', async () => {
  const w=environment();Object.assign(w.state,{activePage:'register',enrollSession:'session',enrollStudentId:7,enrollmentSourceMode:'browser'});
  const match=source.match(/function startEnrollLoop\([^)]*\)\{[\s\S]*?\n\}/);vm.runInContext(match[0],w.context);
  w.context.startEnrollLoop();const pull=w.timers.get(w.state.enrollTimer)();await flush();assert.equal(w.requests.length,1);
  w.context.pauseAppPresentation('closed');assert.equal(w.requests[0].options.signal.aborted,true);
  w.requests[0].resolve({ok:true,progress:1,ready_to_finalize:true});await pull;
  assert.equal(w.calls.includes('enroll-render'),false);assert.equal(w.calls.includes('enroll-finalize'),false);
  assert.equal(w.state.enrollBusy,false);
});

test('cancelled real runtime production and edge owners settle without leaking AbortError and resume fresh', async () => {
  const w=environment();realRuntime(w);
  const oldProduction=w.context.loadProductionStatus(),oldEdge=w.context.loadEdgeChainAdmin();await flush();
  assert.equal(w.requests.length,2);w.context.pauseSystemCameraPreview();
  await Promise.all([oldProduction,oldEdge]);
  const current=w.context.loadProductionStatus();await flush();assert.equal(w.requests.length,3);
  const owner=w.state.systemProductionController;
  w.requests[0].resolve({old:true});w.requests[1].resolve({items:[{node_name:'stale'}]});await flush();
  assert.equal(w.state.systemProductionController,owner);assert.equal(w.rendered.length,0);
  assert.equal(w.elements.get('#v53EdgeNodeList').innerHTML,'');
  w.requests[2].resolve({current:true});await current;assert.deepEqual(w.rendered,[{current:true}]);
});

test('system page loader handles expected read cancellation while genuine failures remain observable', async () => {
  const w=environment();realRuntime(w);productFunction(w,'loadSystemPage');
  w.context.loadAuthStatus=async()=>({authenticated:true});
  for(const name of ['loadCameraSettings','loadSystemSummary','loadSystemAudit','loadTechnicalHistory','loadRecordingStatus',
    'loadBackups','loadMobileViewerAccess','loadRbacAdmin'])w.context[name]=async()=>{};
  w.context.toast=()=>{};w.state.systemTimer=null;
  const page=w.context.loadSystemPage();await flush();assert.equal(w.requests.length,1);
  w.context.pauseAppPresentation('closed');await page;
  assert.equal(w.state.systemTimer,null);w.requests[0].resolve({old:true});await flush();assert.equal(w.rendered.length,0);
  w.state.presentationSuspended=false;
  w.context.BTMHRuntime.once=()=>Promise.reject(new Error('actual failure'));
  await assert.rejects(w.context.loadProductionStatus(),/actual failure/);
});

test('delayed first authenticated boot can pause and restore exactly one polling owner set', async () => {
  const w=environment();productFunction(w,'bootAuthenticated');w.context.professionalRuntimeStarted=false;
  w.state.activePage='dashboard';const preloads=[];
  w.context.loadHealth=w.context.loadDashboard=()=>new Promise(resolve=>preloads.push(resolve));
  w.context.loadStudents=w.context.loadRecognitionHistory=async()=>{};w.context.console=console;
  const boot=w.context.bootAuthenticated();assert.equal(w.timers.size,4);
  w.context.window.dispatchEvent(new Event('pagehide'));assert.equal(w.timers.size,0);
  w.context.window.dispatchEvent(new Event('pageshow'));await flush();assert.equal(w.timers.size,4);
  preloads.forEach(resolve=>resolve({}));await boot;assert.equal(w.timers.size,4);
  w.context.startAppPolling();assert.equal(w.timers.size,4);
  w.context.pauseAppPresentation();assert.equal(w.timers.size,0);
});

test('old enrollment completion cannot clear replacement busy owner or finalize its session', async () => {
  const w=environment();productFunction(w,'startEnrollLoop');
  Object.assign(w.state,{activePage:'register',enrollSession:'old-session',enrollStudentId:7,enrollmentSourceMode:'browser'});
  w.context.startEnrollLoop();const old=w.timers.get(w.state.enrollTimer)();await flush();
  w.context.pauseAppPresentation();assert.equal(w.state.enrollBusy,false);assert.equal(w.state.enrollRequestController,null);
  Object.assign(w.state,{presentationSuspended:false,enrollSession:'current-session'});
  w.context.startEnrollLoop();const current=w.timers.get(w.state.enrollTimer)();await flush();
  const owner=w.state.enrollRequestController;assert.equal(w.requests.length,2);assert.equal(w.state.enrollBusy,true);
  w.requests[0].resolve({ok:true,progress:1,ready_to_finalize:true});await old;
  assert.equal(w.state.enrollRequestController,owner);assert.equal(w.state.enrollBusy,true);
  assert.equal(w.calls.includes('enroll-render'),false);assert.equal(w.calls.includes('enroll-finalize'),false);
  w.requests[1].resolve({ok:false});await current;assert.equal(w.state.enrollBusy,false);assert.equal(w.state.enrollRequestController,null);
});

test('app-first pageshow waits for later V4 presented listener before restoring same enrollment loop', async () => {
  const w=environment();Object.assign(w.state,{activePage:'register',enrollTimer:2,enrollSession:'session',enrollStudentId:7});
  let v4Presented=true;
  w.context.window.addEventListener('pagehide',()=>{v4Presented=false});
  w.context.window.addEventListener('pageshow',()=>{v4Presented=true});
  w.context.prepareEnrollmentLaptopCamera=async()=>v4Presented;
  w.context.window.dispatchEvent(new Event('pagehide'));w.context.window.dispatchEvent(new Event('pageshow'));await flush();
  assert.equal(w.calls.filter(x=>x==='enroll-start').length,1);
});

test('actual V4 pageshow and deferred app preparation share one getUserMedia owner before resuming proof', async () => {
  const w=environment();Object.assign(w.state,{activePage:'register',enrollTimer:2,enrollSession:'session',enrollStudentId:7});
  const gum=[],stopped=[];const video={style:{},play:async()=>{}};
  w.elements.set('#enrollVideo',video);w.elements.set('#page-register.active',{});
  w.context.document.querySelector=selector=>w.elements.get(selector)||null;
  w.context.document.querySelectorAll=()=>[];
  w.context.navigator={mediaDevices:{getUserMedia:()=>new Promise(resolve=>gum.push(resolve))}};
  w.context.localStorage={getItem:()=>''};w.context.Date=Date;
  w.context.BTMHRuntime.request=async()=>({ok:true,json:async()=>({items:[]})});
  w.context.window.BTMHV4=undefined;
  // environment installed actual app listeners first, matching index.html script order.
  vm.runInContext(v4Source,w.context);productFunction(w,'prepareEnrollmentLaptopCamera');
  const auth=new Event('btmh:auth');auth.detail={authenticated:true};w.context.document.dispatchEvent(auth);
  const stream=label=>({active:true,getTracks:()=>[{stop:()=>stopped.push(label)}]});
  assert.equal(gum.length,1);gum[0](stream('first'));await flush();
  w.context.window.dispatchEvent(new Event('pagehide'));assert.equal(video.srcObject,null);
  w.context.window.dispatchEvent(new Event('pageshow'));await flush();assert.equal(gum.length,2);
  assert.equal(w.calls.includes('enroll-start'),false);gum[1](stream('second'));await flush();await flush();
  assert.equal(gum.length,2);assert.equal(w.calls.filter(x=>x==='enroll-start').length,1);
  assert.ok(stopped.includes('first'));assert.ok(video.srcObject?.active);
});

test('late recognition second response cannot paint events or request history after pause or permission change', async () => {
  for(const change of [w=>w.context.pauseAppPresentation('closed'),w=>w.context.permitted=false,w=>{w.state.presentationEpoch++;w.state.activePage='system'}]){
    const w=environment();productFunction(w,'pollRecognition');w.state.activePage='dashboard';w.state.lastEventId=0;
    w.context.renderLatestRecognition=()=>w.calls.push('event-render');w.context.loadRecognitionHistory=async()=>w.calls.push('history-load');
    const poll=w.context.pollRecognition();w.requests[0].resolve({tracks:[]});await flush();assert.equal(w.requests.length,2);
    change(w);w.requests[1].resolve({event:{id:33}});await poll;
    assert.equal(w.state.lastEventId,0);assert.equal(w.calls.includes('event-render'),false);assert.equal(w.calls.includes('history-load'),false);
  }
});

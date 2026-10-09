'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };
function environment(names) {
  const elements = new Map(), requests = [], toasts = [], document = {hidden: false}, state = {authUser: {}, activePage: 'system', presentationEpoch: 0};
  const element = (id, options = {}) => { const node = Object.assign(new EventTarget(), {textContent: '', innerHTML: '', value: '', style: {}, options: [{value: '1920x1080'}], classList: {add() {}, remove() {}, toggle() {}}, replaceChildren() { this.innerHTML = ''; }}); Object.assign(node, options); elements.set(id, node); return node; };
  const context = {state, document, AbortController, Event, window: {}, $: id => elements.get(id) || null, $$: () => [], escapeHtml: String, formatBytes: value => String(value), formatDate: String, api: (url, init) => new Promise((resolve, reject) => requests.push({url, init, resolve, reject})), appPresentationActive: () => !!state.authUser && !document.hidden, hasUiPermission: () => true, toast: (...args) => toasts.push(args), syncCameraPresetUi() {}, cameraPresetFromSource() { return 'configured'; }, loadSystemAudit: async () => {}, BTMHRuntime: {cancel() {}, stopPreview() {}}, clearInterval() {}};
  vm.createContext(context);
  for (const name of ['cameraUiName', 'cameraUiStatus', ...names]) { let match = source.match(new RegExp(`(?:async )?function ${name}\\([^\\n]*\\)\\s*\\{[\\s\\S]*?\\n\\}`)); if (name === 'loadV13Performance') match = source.match(/^async function loadV13Performance[^\n]+$/m); assert.ok(match, name); vm.runInContext(match[0], context); }
  return {context, elements, requests, toasts, state, document, element};
}

test('ordinary camera markup contains no FPS/quality/performance overlays or telemetry panels', () => {
  const monitor = html.slice(html.indexOf('id="page-live-monitor"'), html.indexOf('id="page-students"'));
  assert.equal(/id="v13Monitor(?:Fps|Resolution|Quality|PerfState|P95|Drop|Target|Actual)"/.test(monitor), false);
  assert.equal(/id="v6Camera(?:Fps|Resolution|Quality|Sharpness|Brightness|Latency)"/.test(html), false);
  assert.equal(/id="v210(?:Cpu|Ram|Gpu)"/.test(html), false);
  assert.match(html, /<details[^>]*id="cameraConnectionDetails"[^>]*data-permission="camera.configure"/);
  assert.match(html, /<details[^>]*id="systemTechnicalDetails"[^>]*data-permission="system.diagnostics"/);
  assert.equal(/<details[^>]*\bopen[^>]*id="(?:cameraConnectionDetails|systemTechnicalDetails)"/.test(html), false);
});

test('normal system diagnostics use allowlisted component/status labels and never print source/error details', () => {
  const w = environment(['renderDiagnostics']), host = w.element('#systemHealthList'); for (const id of ['#v6CameraStateText', '#v6CameraWarning', '#v6SystemCamera', '#v6SystemCameraMeta']) w.element(id);
  w.context.renderDiagnostics({ok: false, checks: [{key: 'camera', label: 'rtsp://private.invalid', ok: false, detail: '192.168.1.9 decoder failed'}, {key: 'passive_pad', ok: true, detail: 'MiniFASNet secret diagnostic'}, {key: 'private', label: 'SECRET_KEY', ok: true}], camera: {state: 'error', error: 'PRIVATE_REASON', quality_warning: 'decoder RAW', source_label: 'rtsp://private.invalid'}});
  assert.equal(/rtsp|192\.168|decoder|PRIVATE|MiniFAS|SECRET/.test(host.innerHTML), false); assert.match(host.innerHTML, /Camera.*Cần kiểm tra.*Chống giả mạo.*Sẵn sàng/); assert.equal(w.elements.get('#v6CameraStateText').textContent, 'Mất kết nối'); assert.equal(w.elements.get('#v6CameraWarning').textContent.includes('PRIVATE'), false);
  assert.equal(w.context.cameraUiStatus({state: 'MADE_UP'}), 'Chưa ghi nhận');
});

test('media badge never prints transport, FPS, frame size or fallback codes', () => {
  const w = environment(['renderMediaPlayback']), badge = w.element('#v13MonitorLive'); const fps = w.element('#v13MonitorFps'), size = w.element('#v13MonitorResolution');
  w.context.renderMediaPlayback({key: 'live-monitor', state: 'live', transport: 'WEBSOCKET_ACK_BITMAP', fallbackReason: 'SECRET', renderedFps: 25, videoWidth: 640, videoHeight: 480}); assert.match(badge.innerHTML, /LIVE/); assert.equal(badge.title, 'LIVE'); assert.equal(fps.textContent, ''); assert.equal(size.textContent, '');
});

test('monitor loads public registry context only and never offers an AI source takeover', async () => {
  const w = environment(['loadV13MonitorDevices']), host = w.element('#v13MonitorDevices'); w.state.activePage = 'live-monitor'; const pending = w.context.loadV13MonitorDevices(); assert.equal(w.requests[0].url, '/api/v1/recognition/cameras');
  w.requests[0].resolve({items: [{camera_id: 5, name: 'Camera cửa vào', store_name: 'Hà Đông', zone_name: 'Sảnh', source: 'rtsp://hidden.invalid', source_display: '192.168.1.5', connection_state: 'PRIVATE_ERROR'}]}); await pending;
  assert.equal(/rtsp|192\.168|PRIVATE_ERROR|v13ActivateCamera|onclick=/.test(host.innerHTML), false); assert.match(host.innerHTML, /Camera cửa vào.*Hà Đông.*Chưa ghi nhận/);
  const late = w.context.loadV13MonitorDevices(); w.state.activePage = 'history'; w.state.presentationEpoch++; w.requests[1].resolve({items: [{camera_id: 99, name: 'Late old camera'}]}); await late; assert.equal(host.innerHTML.includes('Late old camera'), false);
});

test('normal monitor does not query developer performance when telemetry panels are absent', async () => {
  const w = environment(['loadV13Performance']); await w.context.loadV13Performance(); assert.equal(w.requests.length, 0);
});

test('camera test result gives a useful connection message without raw backend/source diagnostics', async () => {
  const w = environment(['testCurrentCamera']), info = w.element('#cameraRuntimeInfo'); const pending = w.context.testCurrentCamera(); w.requests[0].resolve({ok: false, source_label: '192.168.1.5', capture_fps: 2, frame_age_ms: 10000, error: 'decoder internal failure'}); await pending; assert.equal(/192\.168|decoder|FPS|10000/.test(info.textContent + JSON.stringify(w.toasts)), false); assert.match(info.textContent, /Kiểm tra nguồn điện/);
});

test('advanced connection and technical history load only when open/authorized; close retires late responses', async () => {
  const w = environment(['loadCameraSettings', 'loadTechnicalHistory']), connection = w.element('#cameraConnectionDetails', {open: false}), technical = w.element('#systemTechnicalDetails', {open: false}), sourceField = w.element('#camSource'), log = w.element('#systemTechnicalList');
  await w.context.loadCameraSettings(); await w.context.loadTechnicalHistory(); assert.equal(w.requests.length, 0);
  for (const id of ['cameraConnectionDetails', 'systemTechnicalDetails']) { const line = source.split('\n').find(line => line.trim().startsWith(`$('#${id}')?.addEventListener('toggle'`)); assert.ok(line); vm.runInContext(line, w.context); }
  connection.open = true; connection.dispatchEvent(new Event('toggle')); await flush(); const cameraRequest = w.requests[0]; connection.open = false; connection.dispatchEvent(new Event('toggle')); assert.equal(cameraRequest.init.signal.aborted, true); cameraRequest.resolve({settings: {source: 'Private closed source'}, runtime: {state: 'online'}}); await flush(); assert.equal(sourceField.value, '');
  technical.open = true; technical.dispatchEvent(new Event('toggle')); await flush(); const technicalRequest = w.requests[1]; technical.open = false; technical.dispatchEvent(new Event('toggle')); assert.equal(technicalRequest.init.signal.aborted, true); technicalRequest.resolve({items: [{full_name: 'Private late name'}]}); await flush(); assert.equal(log.innerHTML, '');
});

test('database summary hides host/port/schema while keeping configuration truth', async () => {
  const w = environment(['loadSystemSummary']), mode = w.element('#v6SystemDb'), meta = w.element('#v6SystemDbMeta'); w.context.loadProfessionalSummary = async () => ({database: {mode: 'postgres', host: '192.168.1.5', port: 5432, database: 'private_db'}}); await w.context.loadSystemSummary(); assert.equal(mode.textContent, 'Đã cấu hình'); assert.equal(/192\.168|5432|private_db|Postgres/i.test(meta.textContent), false);
});
test('system video is opt-in, permission-gated, native-media owned and mounted once',()=>{
  const w=environment(['mountSystemCameraPreview']),calls=[];
  const details=w.element('#systemCameraDetails',{open:false}),image=w.element('#systemCameraPreview',{dataset:{},parentElement:{}});w.element('#systemCameraEmpty');
  w.context.window.BTMHMedia={mount:(key,options)=>calls.push({key,options})};
  w.context.mountSystemCameraPreview();assert.equal(calls.length,0);
  details.open=true;w.context.hasUiPermission=key=>key!=='system.diagnostics';w.context.mountSystemCameraPreview();assert.equal(calls.length,0);
  w.context.hasUiPermission=()=>true;w.context.mountSystemCameraPreview();w.context.mountSystemCameraPreview();assert.equal(calls.length,1);assert.equal(calls[0].key,'system-preview');assert.equal(calls[0].options.quality,'main');assert.equal(calls[0].options.image,image);
  w.state.activePage='dashboard';image.dataset={};w.context.mountSystemCameraPreview();assert.equal(calls.length,1);
});
test('system native-video availability controls placeholder without printing transport or metrics',()=>{
  const w=environment(['renderMediaPlayback']),states=[];w.element('#systemCameraEmpty',{classList:{toggle:(name,value)=>states.push({name,value})}});
  w.context.renderMediaPlayback({key:'system-preview',state:'live',renderedFps:25,transport:'NATIVE_GATEWAY_WEBRTC'});w.context.renderMediaPlayback({key:'system-preview',state:'offline'});assert.deepEqual(states,[{name:'hidden',value:true},{name:'hidden',value:false}]);
});

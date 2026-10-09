'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_camera_configuration.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
const app = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const gate = {enabled: true, name: 'Cửa chính', x1: .15, y1: .55, x2: .85, y2: .55, inside_side: 'positive', anchor: 'person_center', roi: null, deadband: .025, cooldown_sec: 2.5, reacquire_sec: 2, max_distance: .12};
const camera = (id = 5, extra = {}) => ({id, camera_id: id, name: `Camera ${id}`, camera_name: `Camera ${id}`, store_id: 2, store_name: 'Hà Đông', zone_name: 'Cửa vào', ai_enabled: true, attendance_enabled: true, visitor_counting_enabled: true, entrance_config: gate, connection_state: 'ONLINE', ai_state: 'RUNNING', pad_state: 'ENABLED', recording_active: false, ...extra});
const stores = [{id: 2, store_name: 'Hà Đông'}, {id: 3, store_name: 'Cầu Giấy'}];
function browser(config = {}) {
  const w = {requests: [], pending: [], items: [camera(5), camera(9)], permissions: new Set(['camera.live', 'camera.configure', 'dashboard.view']), authenticated: true, mounts: [], stops: [], rafs: new Map(), nextRaf: 0, observers: [], ...config};
  const document = new EventTarget(); document.hidden = !!w.hidden; document.activeElement = null;
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.style = {}; this.value = ''; this.checked = false; this.className = ''; this.hidden = false; this.disabled = false; this._text = ''; this.clientWidth = 640; this.clientHeight = 360; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    get classList() { return {contains: value => this.className.split(/\s+/).includes(value), add: value => this.classList.toggle(value, true), remove: value => this.classList.toggle(value, false), toggle: (value, on) => { const names = new Set(this.className.split(/\s+/).filter(Boolean)); if (on ?? !names.has(value)) names.add(value); else names.delete(value); this.className = [...names].join(' '); }}; }
    append(...children) { for (const child of children) { child.remove(); child.parentElement = this; this.children.push(child); } }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
    replaceChildren(...children) { for (const child of this.children) child.parentElement = null; this.children = []; this._text = ''; this.append(...children); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(selector === 'img' && child.tagName === 'IMG' ? [child] : []), ...child.querySelectorAll(selector)]); }
    get options() { return this.children.filter(child => child.tagName === 'OPTION'); }
    focus() { document.activeElement = this; }
    reset() { for (const [id, element] of roots) if (id.startsWith('cameraConfig') && ['INPUT', 'SELECT'].includes(element.tagName)) { element.value = ''; element.checked = false; } }
  }
  const roots = new Map(), register = (id, tag = 'div') => { const element = new Element(tag); element.id = id; roots.set(id, element); return element; };
  const page = register('page-ops-center'); page.className = w.offPage ? 'page' : 'page active';
  for (const match of html.matchAll(/<(\w+)[^>]*\bid="(cameraConfig[^\"]+)"[^>]*>/g)) { const element = register(match[2], match[1]); if (/\bhidden\b/.test(match[0])) element.hidden = true; page.append(element); }
  document.getElementById = id => roots.get(id) || null; document.createElement = tag => new Element(tag); document.createElementNS = (_, tag) => new Element(tag);
  const window = new EventTarget(); window.BTMHMedia = {mount: (key, options) => { w.mounts.push({key, options}); }, stop: key => w.stops.push(key), geometry: {fitRect: (cw, ch, sw, sh) => { const scale = Math.min(cw / sw, ch / sh), width = sw * scale, height = sh * scale; return {x: (cw - width) / 2, y: (ch - height) / 2, w: width, h: height}; }}};
  const state = {authUser: w.authenticated ? {id: 1} : null};
  const api = async (url, init) => {
    const request = {url, init}; w.requests.push(request); if (w.hold?.(url, init)) return new Promise((resolve, reject) => w.pending.push({...request, resolve, reject}));
    const error = typeof w.error === 'function' ? w.error(url, init) : w.error; if (error) throw error;
    if (url === '/api/v1/recognition/cameras') return {items: w.items, capacity: 4}; if (url === '/api/v1/stores') return {items: stores};
    const id = Number(url.match(/devices\/(\d+)\//)?.[1]), item = w.items.find(item => item.camera_id === id);
    if (['PUT','PATCH'].includes(init?.method)) {
      const payload = JSON.parse(init.body), saved = {...item, ...payload, name: payload.camera_name, camera_name: payload.camera_name};
      w.items = w.items.map(camera => camera.camera_id === id ? {...saved, ai_state: w.savedAiState || (payload.ai_enabled ? 'STARTING' : 'DISABLED')} : camera);
      const {ai_state, reason_code, ai_error_code, ...configuration} = saved;
      return {ok: true, item: configuration};
    }
    return {item};
  };
  class Observer { constructor(callback) { this.callback = callback; this.disconnected = false; w.observers.push(this); } observe(element) { this.element = element; } disconnect() { this.disconnected = true; } }
  const context = {window, document, state, api, appPresentationActive: () => w.authenticated && !w.suspended && !document.hidden, hasUiPermission: key => w.permissions.has(key), AbortController, Event, CustomEvent, ResizeObserver: Observer, requestAnimationFrame: callback => { const id = ++w.nextRaf; w.rafs.set(id, callback); return id; }, cancelAnimationFrame: id => w.rafs.delete(id)};
  vm.createContext(context); vm.runInContext(source, context); Object.assign(w, {context, api: window.BTMHCameraConfiguration, document, window, state, roots, page});
  w.get = id => roots.get(id); w.fire = (type, detail, target = document) => target.dispatchEvent(new CustomEvent(type, {detail})); w.click = id => w.get(id).dispatchEvent(new Event('click')); w.submit = () => w.get('cameraConfigurationForm').dispatchEvent(new Event('submit', {cancelable: true}));
  w.input = (field, value) => { const element = w.get('cameraConfig' + field); if (typeof value === 'boolean') element.checked = value; else element.value = value; element.dispatchEvent(new Event('input')); };
  w.cards = () => w.get('cameraConfigurationList').children.filter(element => element.tagName === 'BUTTON'); w.tick = () => { const callbacks = [...w.rafs.values()]; w.rafs.clear(); for (const callback of callbacks) callback(); }; w.writes = () => w.requests.filter(request => ['PUT','PATCH'].includes(request.init?.method));
  return w;
}

test('dirty camera draft survives tab and navigation suspension while preview and requests stop', async () => {
  const w = browser(); await flush(); await w.api.select(9); w.input('Name', 'Tên đang sửa'); w.input('X1', '25'); w.click('cameraConfigurationPreview');
  w.document.hidden = true; w.fire('visibilitychange'); assert.equal(w.get('cameraConfigName').value, ''); assert.equal(w.get('cameraConfigPreviewWrap').hidden, true); assert.equal(w.stops.length, 1);
  w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.get('cameraConfigName').value, 'Tên đang sửa'); assert.equal(w.get('cameraConfigX1').value, '25'); assert.equal(w.get('cameraConfigurationCancel').disabled, false); assert.match(w.get('cameraConfigurationNote').textContent, /khôi phục bản nháp/); assert.equal(w.writes().length, 0);
  w.page.classList.remove('active'); w.fire('btmh:navigate', {page: 'history'}); w.page.classList.add('active'); w.fire('btmh:navigate', {page: 'ops-center'}); await flush(); assert.equal(w.get('cameraConfigName').value, 'Tên đang sửa');
  w.click('cameraConfigurationCancel'); await flush(); assert.equal(w.get('cameraConfigName').value, 'Camera 9');
});

test('suspended camera draft cannot cross logout, actor or permission/camera revocation', async () => {
  for (const change of [w => { w.authenticated = false; w.state.authUser = null; w.fire('btmh:auth', {authenticated: false}); w.authenticated = true; w.state.authUser = {id: 2}; }, w => { w.state.authUser = {id: 2}; }, w => { w.permissions.delete('camera.configure'); }, w => { w.items = [camera(5)]; }]) {
    const w = browser(); await flush(); await w.api.select(9); w.input('Name', 'Private draft'); w.document.hidden = true; w.fire('visibilitychange'); change(w); w.document.hidden = false; w.fire('visibilitychange'); await flush();
    assert.equal(w.get('cameraConfigName').value.includes('Private draft'), false); assert.equal(w.writes().length, 0);
  }
});

test('loads allowlisted source-free registry/store options and configuration by real ID', async () => {
  const w = browser(); await flush(); assert.deepEqual(w.requests.map(request => request.url), ['/api/v1/recognition/cameras', '/api/v1/stores', '/api/v1/cameras/devices/5/configuration']); assert.equal(w.cards().length, 2); assert.equal(w.get('cameraConfigName').value, 'Camera 5'); assert.equal(w.get('cameraConfigX1').value, '15'); assert.equal(w.get('cameraConfigStore').value, '2'); assert.equal(w.get('cameraConfigurationSave').disabled, false); assert.equal(w.writes().length, 0); assert.match(w.cards()[0].textContent, /Trực tuyến.*AI đang hoạt động.*Chống giả mạo bật.*Chưa ghi hình/);
  await w.api.select(999); await flush(); assert.equal(w.requests.length, 3);
});

test('camera AI badges distinguish actual availability from an enabled flag and keep reasons private', async () => {
  for (const [extra, label] of [
    [{ai_enabled: false, ai_state: 'ACTIVE'}, 'AI đã tắt'],
    [{store_id: null, ai_state: 'OFFLINE'}, 'AI cần cấu hình'],
    [{zone_name: '', ai_state: 'OFFLINE'}, 'AI cần cấu hình'],
    [{ai_state: 'WAITING_FOR_CAPACITY'}, 'AI chờ lượt xử lý'],
    [{ai_state: 'OFFLINE'}, 'AI mất kết nối'],
    [{ai_state: 'ERROR', reason_code: 'AI_PROCESS_FAILED'}, 'AI gặp lỗi xử lý'],
    [{ai_state: 'PAUSED'}, 'AI đang tạm dừng'],
    [{ai_state: 'STARTING'}, 'AI đang khởi động'],
    [{ai_state: 'OFFLINE', reason_code: 'AI_WORKER_START_FAILED'}, 'AI chưa khả dụng'],
  ]) {
    const w = browser({items: [camera(5, extra)]}); await flush();
    assert.ok(w.cards()[0].textContent.includes(label));
    assert.equal(/AI_PROCESS_FAILED|AI_WORKER_START_FAILED/.test(w.cards()[0].textContent), false);
    assert.equal(w.writes().length, 0);
  }
});

test('enabling AI requires explicit checkbox and save with store and zone, never a presentation action', async () => {
  const w = browser({items: [camera(5, {ai_enabled: false, ai_state: 'DISABLED', visitor_counting_enabled: false})]}); await flush();
  assert.equal(w.get('cameraConfigAi').checked, false);
  w.click('cameraConfigurationPreview'); assert.equal(w.writes().length, 0);
  w.input('Ai', true); assert.equal(w.writes().length, 0); w.submit(); await flush();
  assert.equal(w.writes().length, 1);
  const payload = JSON.parse(w.writes()[0].init.body);
  assert.equal(payload.ai_enabled, true); assert.equal(payload.store_id, 2); assert.equal(payload.zone_name, 'Cửa vào');
  assert.equal(w.requests.some(request => /\/ai\/|activate|\/start/.test(request.url)), false);
  assert.equal(w.requests.filter(request => request.url === '/api/v1/recognition/cameras').length, 2);
  assert.ok(w.cards()[0].textContent.includes('AI đang khởi động'));
});

test('successful save reads actual AI state without another mutation and a readback failure keeps the acknowledgment', async () => {
  const w = browser({savedAiState: 'ERROR'}); await flush(); w.input('Name', 'Tên đã lưu'); w.submit(); await flush();
  assert.ok(w.cards()[0].textContent.includes('AI gặp lỗi xử lý')); assert.equal(w.get('cameraConfigName').value, 'Tên đã lưu');
  assert.equal(w.writes().length, 1); assert.match(w.get('cameraConfigurationNote').textContent, /Đã lưu/);
  let failing = null;
  failing = browser({error: (url) => url === '/api/v1/recognition/cameras' && failing?.requests.some(request => ['PUT','PATCH'].includes(request.init?.method)) ? new Error('readback offline') : null});
  await flush(); failing.input('Name', 'Vẫn đã lưu'); failing.submit(); await flush();
  assert.equal(failing.writes().length, 1); assert.equal(failing.get('cameraConfigName').value, 'Vẫn đã lưu');
  assert.match(failing.get('cameraConfigurationNote').textContent, /Đã lưu.*Chưa cập nhật.*Tải lại/);
  assert.ok(failing.cards()[0].textContent.includes('Chưa có trạng thái AI'));
  assert.equal(failing.get('cameraConfigurationSave').disabled, false);
});

test('late runtime readback is aborted and cannot cross an authentication reset', async () => {
  let holdReadback = false;
  const w = browser({hold: url => holdReadback && url === '/api/v1/recognition/cameras'}); await flush();
  holdReadback = true; w.input('Name', 'Saved by previous actor'); w.submit(); await flush();
  const pending = w.pending[0]; assert.ok(pending); assert.equal(w.writes().length, 1);
  w.authenticated = false; w.state.authUser = null; w.fire('btmh:auth', {authenticated: false});
  assert.equal(pending.init.signal.aborted, true);
  pending.resolve({items: [camera(5, {ai_state: 'ACTIVE', camera_name: 'Old actor identity'})]}); await flush();
  assert.equal(w.cards().length, 0); assert.equal(w.get('cameraConfigName').value, '');
  assert.equal(w.get('cameraConfigurationNote').textContent.includes('Đã lưu'), false);
});

test('explicit save sends only name/location/flags/gate settings and preserves stable ID', async () => {
  const w = browser(); await flush(); w.input('Name', 'Hà Đông - Cửa vào'); w.input('Zone', 'Sảnh'); w.input('X1', '20'); w.input('Inside', 'negative'); w.input('Roi', true); w.submit(); await flush(); const request = w.writes()[0], payload = JSON.parse(request.init.body);
  assert.equal(request.url, '/api/v1/cameras/devices/5/configuration'); assert.deepEqual(Object.keys(payload).sort(), ['ai_enabled', 'attendance_enabled', 'camera_name', 'entrance_config', 'store_id', 'visitor_counting_enabled', 'zone_name']); assert.equal(payload.camera_name, 'Hà Đông - Cửa vào'); assert.equal(payload.entrance_config.x1, .2); assert.equal(payload.entrance_config.inside_side, 'negative'); assert.equal(payload.entrance_config.reacquire_sec, 2); assert.equal(payload.entrance_config.max_distance, .12); assert.deepEqual(payload.entrance_config.roi, {x1: 0, y1: 0, x2: 1, y2: 1}); assert.equal(/source|password|token|rtsp|activate|start|stop/i.test(request.init.body), false); assert.match(w.get('cameraConfigurationNote').textContent, /Đã lưu/); assert.equal(w.get('cameraConfigurationCancel').disabled, true);
});

test('invalid business prerequisites/line/ROI/name are rejected before any write', async () => {
  for (const changes of [[['Store', '']], [['Zone', '']], [['Gate', false]], [['X2', '15'], ['Y2', '55']], [['Roi', true], ['RoiX1', '30']], [['Name', 'rtsp://secret.invalid']], [['Name', '192.168.1.5']], [['X1', '101']]]) {
    const w = browser(); await flush(); for (const [field, value] of changes) w.input(field, value); w.submit(); await flush(); assert.equal(w.writes().length, 0); assert.equal(w.get('cameraConfigurationNote').classList.contains('error'), true);
  }
});

test('saving is single-flight and failure preserves draft for retry', async () => {
  const w = browser({hold: (_, init) => ['PUT','PATCH'].includes(init?.method)}); await flush(); w.input('Name', 'Bản nháp'); w.submit(); w.submit(); await flush(); assert.equal(w.writes().length, 1); assert.equal(w.get('cameraConfigurationSave').disabled, true); assert.equal(w.get('cameraConfigName').disabled, true);
  w.pending[0].reject({status: 409}); await flush(); assert.match(w.get('cameraConfigurationNote').textContent, /Giữ thay đổi/); assert.equal(w.get('cameraConfigName').value, 'Bản nháp'); assert.equal(w.get('cameraConfigurationSave').disabled, false); w.hold = null; w.submit(); await flush(); assert.equal(w.writes().length, 2); assert.match(w.get('cameraConfigurationNote').textContent, /Đã lưu/);
});

test('unsaved change blocks switching, reload preserves draft and cancel reloads canonical configuration', async () => {
  const w = browser(); await flush(); w.input('Name', 'Tên chưa lưu'); w.cards()[1].dispatchEvent(new Event('click')); await flush(); assert.equal(w.get('cameraConfigName').value, 'Tên chưa lưu'); assert.match(w.get('cameraConfigurationNote').textContent, /Lưu hoặc Hủy/);
  await w.api.refresh(); assert.equal(w.get('cameraConfigName').value, 'Tên chưa lưu'); w.click('cameraConfigurationCancel'); await flush(); assert.equal(w.get('cameraConfigName').value, 'Camera 5'); w.cards()[1].dispatchEvent(new Event('click')); await flush(); assert.equal(w.get('cameraConfigName').value, 'Camera 9');
});

test('camera selection aborts old configuration and ignores late camera data', async () => {
  const w = browser({hold: url => url.includes('/5/configuration')}); await flush(); const old = w.pending[0]; w.hold = null; await w.api.select(9); assert.equal(old.init.signal.aborted, true); old.resolve({item: camera(5, {camera_name: 'Stale old name'})}); await flush(); assert.equal(w.get('cameraConfigName').value, 'Camera 9');
});

test('revoking a camera aborts its pending configuration and clears editor/preview', async () => {
  const w = browser({hold: url => url.includes('/configuration')}); await flush(); const old = w.pending[0]; w.items = []; await w.api.refresh(); old.resolve({item: camera(5, {camera_name: 'Revoked name'})}); await flush(); assert.equal(old.init.signal.aborted, true); assert.equal(w.get('cameraConfigName').value, ''); assert.equal(w.get('cameraConfigurationForm').hidden, true); assert.match(w.get('cameraConfigurationList').textContent, /Chưa có camera/);
});

test('live-only role reads safe status but never loads business configuration/stores or writes', async () => {
  const w = browser({permissions: new Set(['camera.live'])}); await flush(); assert.deepEqual(w.requests.map(request => request.url), ['/api/v1/recognition/cameras']); assert.equal(w.get('cameraConfigurationForm').hidden, true); assert.equal(w.get('cameraConfigurationPermission').hidden, false); w.submit(); await flush(); assert.equal(w.writes().length, 0);
});

test('store/options failures disable saving and have an explicit retry', async () => {
  const w = browser({error: url => url.endsWith('/stores') ? new Error('offline') : null}); await flush(); assert.equal(w.get('cameraConfigurationSave').disabled, true); assert.match(w.get('cameraConfigurationNote').textContent, /Chưa tải được danh sách cửa hàng/); w.error = null; await w.api.refresh(); await flush(); assert.equal(w.get('cameraConfigurationSave').disabled, false);
});

test('viewing/closing preview preserves native media architecture and never mutates AI settings', async () => {
  const w = browser(); await flush(); w.click('cameraConfigurationPreview'); const mount = w.mounts[0]; assert.equal(mount.key, 'camera-configuration-preview'); assert.equal(mount.options.cameraId, 5); assert.equal(mount.options.quality, 'main'); assert.equal(mount.options.mjpegUrl, '/api/v1/cameras/5/stream.mjpg'); assert.equal(mount.options.pollUrl, '/api/v1/cameras/5/frame.jpg'); assert.equal(w.get('cameraConfigPreviewWrap').hidden, false); assert.equal(w.writes().length, 0); assert.equal(w.requests.some(request => /activate|\/ai\//.test(request.url)), false);
  w.click('cameraConfigurationPreview'); assert.deepEqual(w.stops, ['camera-configuration-preview']); assert.equal(w.observers[0].disconnected, true); assert.equal(w.rafs.size, 0);
});

test('line overlay fits actual preview content, resize is coalesced and reverse inside changes arrow', async () => {
  const w = browser(); await flush(); w.click('cameraConfigurationPreview'); const video = w.get('cameraConfigVideo'); video.videoWidth = 640; video.videoHeight = 480; w.fire('loadedmetadata', {}, video); w.observers[0].callback(); w.observers[0].callback(); assert.equal(w.rafs.size, 1); w.tick();
  assert.equal(w.get('cameraConfigPreviewLine').style.left, '80px'); assert.equal(w.get('cameraConfigPreviewLine').style.width, '480px'); assert.equal(w.get('cameraConfigPreviewLine').hidden, false); const svg = w.get('cameraConfigDiagram'), before = svg.children.find(element => element.tagName === 'POLYLINE').attributes.points; w.input('Inside', 'negative'); const after = svg.children.find(element => element.tagName === 'POLYLINE').attributes.points; assert.notEqual(after, before);
  w.fire('btmh:media-state', {key: 'camera-configuration-preview', cameraId: 9, state: 'live'}); assert.notEqual(w.get('cameraConfigPreviewState').textContent, 'LIVE'); w.fire('btmh:media-state', {key: 'camera-configuration-preview', cameraId: 5, state: 'live'}); assert.equal(w.get('cameraConfigPreviewState').textContent, 'LIVE');
});

test('registry display never prints source/IP/reason codes and status copies stay allowlisted', async () => {
  const w = browser({items: [camera(5, {camera_name: 'rtsp://hidden.invalid/path', zone_name: '192.168.1.5', source: 'rtsp://never.invalid', ai_state: 'PRIVATE_REASON', connection_state: 'SECRET', pad_state: 'PRIVATE_REASON'})]}); await flush(); const text = w.get('cameraConfigurationList').textContent; assert.equal(/rtsp|192\.168|never\.invalid|PRIVATE_REASON|SECRET/.test(text), false); assert.match(text, /Chưa ghi nhận/); assert.equal(source.includes('camera.source'), false);
});

test('auth/navigation/visibility stop all request owners and preview; late saves cannot claim success', async () => {
  const w = browser({hold: (_, init) => ['PUT','PATCH'].includes(init?.method)}); await flush(); w.click('cameraConfigurationPreview'); w.input('Name', 'Private draft'); w.submit(); await flush(); const pending = w.pending[0]; w.authenticated = false; w.state.authUser = null; w.fire('btmh:auth', {authenticated: false}); assert.equal(pending.init.signal.aborted, true); assert.equal(w.get('cameraConfigName').value, ''); assert.equal(w.cards().length, 0); assert.equal(w.get('cameraConfigPreviewWrap').hidden, true); pending.resolve({ok: true, item: camera(5, {camera_name: 'Private saved'})}); await flush(); assert.equal(w.get('cameraConfigurationNote').textContent.includes('Đã lưu'), false);
  w.authenticated = true; w.state.authUser = {id: 2}; w.hold = null; w.fire('btmh:auth', {authenticated: true}); await flush(); w.document.hidden = true; w.fire('visibilitychange'); assert.equal(w.cards().length, 0); const count = w.requests.length; w.api.start(); assert.equal(w.requests.length, count); w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.ok(w.requests.length > count);
  w.fire('pagehide', {}, w.window); const after = w.requests.length; w.api.start(); assert.equal(w.requests.length, after); w.page.classList.remove('active'); w.fire('btmh:navigate', {page: 'history'}); assert.equal(w.cards().length, 0);
});

test('off-page/auth/permission guard starts no requests', async () => {
  for (const config of [{offPage: true}, {hidden: true}, {authenticated: false}, {permissions: new Set()}]) { const w = browser(config); await flush(); assert.equal(w.requests.length, 0); }
});

test('ops hooks delegate to the new owner and legacy connection form stays collapsed and permission gated', async () => {
  let starts = 0, refreshes = 0, old = 0; const context = {window: {BTMHCameraConfiguration: {start: () => starts++, refresh: () => refreshes++}}, api: () => old++}; vm.createContext(context);
  for (const name of ['loadOpsDevices', 'loadOpsCenter']) { const match = app.match(new RegExp(`async function ${name}\\([^\\n]*\\)\\s*\\{[\\s\\S]*?\\n\\}`)); assert.ok(match); vm.runInContext(match[0], context); }
  await context.loadOpsDevices(); await context.loadOpsCenter(); assert.equal(starts, 1); assert.equal(refreshes, 1); assert.equal(old, 0); assert.match(html, /<details[^>]*data-permission="camera.configure"><summary>Kết nối nâng cao/); assert.equal(/<details[^>]*\bopen[^>]*data-permission="camera.configure"/.test(html), false);
});
test('name-only save uses a metadata PATCH and never sends source or configuration flags',async()=>{const w=browser();await flush();w.input('Name','Tên mới');w.submit();await flush();const writes=w.requests.filter(row=>['PUT','PATCH'].includes(row.init?.method));assert.equal(writes.length,1);assert.equal(writes[0].init.method,'PATCH');assert.equal(writes[0].url,'/api/v1/cameras/devices/5/name');assert.deepEqual(JSON.parse(writes[0].init.body),{camera_name:'Tên mới'});assert.equal(/readonly/.test(html.match(/<input[^>]*id="cameraConfigName"[^>]*>/)[0]),false);});

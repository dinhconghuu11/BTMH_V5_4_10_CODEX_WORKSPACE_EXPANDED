'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_recognition_slots.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const flush = async () => { for (let n = 0; n < 12; n++) await Promise.resolve(); };
const camera = (id, extra = {}) => ({id, camera_id: id, camera_name: `Camera ${id}`, store_id: 1, store_name: 'Hà Đông', zone_name: 'Cửa vào', enabled: true, ai_enabled: true, ai_state: 'ACTIVE', recording_active: false, ...extra});

function browser(options = {}) {
  const w = {authenticated: true, permission: true, cameras: [1, 2, 3, 4, 5].map(id => camera(id)), requests: [], mounts: [], stops: [], selections: [], timers: new Map(), next: 0, ...options};
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.dataset = {}; this.attributes = {}; this._className = ''; this.textContent = ''; }
    get className() { return this._className; }
    set className(value) { this._className = value; }
    get classList() { return {contains: value => this._className.split(/\s+/).includes(value), add: (...values) => values.forEach(value => this.classList.toggle(value, true)), remove: value => this.classList.toggle(value, false), toggle: (value, on) => { const names = new Set(this._className.split(/\s+/).filter(Boolean)); if (on ?? !names.has(value)) names.add(value); else names.delete(value); this._className = [...names].join(' '); }}; }
    append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
    querySelector(selector) { return this.children.find(child => child.classList.contains(selector.slice(1))) || this.children.map(child => child.querySelector(selector)).find(Boolean) || null; }
    getContext() { return {clearRect() {}, drawImage: (...args) => { if (w.drawError) throw new Error('unavailable frame'); (w.previewDraws ||= []).push(args); }}; }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; }
    async requestFullscreen() { w.fullscreenRequests = (w.fullscreenRequests || 0) + 1; document.fullscreenElement = this; }
  }
  const document = new EventTarget(); document.hidden = !!w.hidden; document.fullscreenElement = null;
  const roots = new Map();
  const register = (id, tag = 'div') => { const element = new Element(tag); element.id = id; roots.set(id, element); return element; };
  const page = register('page-recognition'); page.className = w.offPage ? 'page' : 'page active';
  register('recognitionSlots'); register('recognitionSlotsNote'); register('recognitionSlotsRefresh', 'button');
  if (w.single) { register('recognitionCameraStrip'); register('recognitionCameraPrevious', 'button'); register('recognitionCameraNext', 'button'); }
  const find = (element, id) => element.id === id ? element : element.children.map(child => find(child, id)).find(Boolean);
  document.getElementById = id => roots.get(id) || [...roots.values()].map(root => find(root, id)).find(Boolean) || null;
  document.createElement = tag => new Element(tag);
  document.exitFullscreen = async () => { document.fullscreenElement = null; };
  const window = new EventTarget();
  window.BTMHMedia = {mount: (key, config) => w.mounts.push({key, config}), stop: key => w.stops.push(key)};
  const api = async (url, init = {}) => {
    w.requests.push({url, init});
    if (w.hold) return new Promise((resolve, reject) => { w.pending = {resolve, reject, init}; });
    if (w.error) throw w.error;
    return {items: w.cameras};
  };
  if (w.single) document.getElementById('recognitionSlots').dataset.layout = 'single';
  const context = {window, document, Event, CustomEvent, AbortController, api, console,
    appPresentationActive: () => w.authenticated && !document.hidden,
    hasUiPermission: () => w.permission,
    setInterval: callback => { const id = ++w.next; w.timers.set(id, callback); return id; }, clearInterval: id => w.timers.delete(id)};
  document.addEventListener('btmh:recognition-selection', event => w.selections.push(event.detail));
  vm.createContext(context); vm.runInContext(source, context);
  w.api = window.BTMHRecognitionSlots; w.document = document; w.window = window; w.context = context; w.register = register; w.page = page;
  w.fire = (name, detail, target = document) => target.dispatchEvent(new CustomEvent(name, {detail}));
  w.cards = () => document.getElementById('recognitionSlots').children;
  w.metadata = (slot, id, extra = {}) => w.fire('btmh:media-metadata', {key: `recognition-slot-${slot}`, cameraId: id, meta: {camera_id: id, updated_at: 1700000000, tracks: [], ...extra}});
  return w;
}

test('four independent main-quality slots use allowlisted IDs, source-free context and scoped fallbacks', async () => {
  const w = browser({cameras: [1, 2, 3, 4, 5].map(id => camera(id, {source: 'must-never-reach-presentation'}))}); await flush();
  assert.equal(w.cards().length, 4); assert.equal(w.mounts.length, 4);
  assert.deepEqual(w.mounts.map(item => item.key), [0, 1, 2, 3].map(index => `recognition-slot-${index}`));
  for (const [index, mount] of w.mounts.entries()) {
    assert.equal(mount.config.cameraId, index + 1); assert.equal(mount.config.quality, 'main'); assert.equal(mount.config.fit, 'contain');
    assert.equal(mount.config.pollUrl, `/api/v1/cameras/${index + 1}/frame.jpg`);
    assert.equal(mount.config.mjpegUrl, `/api/v1/cameras/${index + 1}/stream.mjpg`);
    assert.ok(mount.config.overlay); assert.ok(mount.config.video); assert.ok(mount.config.image);
  }
  assert.equal(w.document.getElementById('recognitionSlotCamera0').children.length, 6, 'registry can exceed four display slots');
  assert.equal('source' in w.api.getSelection().camera, false);
  assert.deepEqual(w.requests.map(item => item.url), ['/api/v1/recognition/cameras']);
  assert.equal(w.requests[0].init.method, undefined, 'display never mutates AI or active source');
});

test('single recognition view mounts one owner and camera switching only replaces presentation', async () => {
  const w = browser({single: true}); await flush();
  assert.equal(w.cards().length, 1); assert.equal(w.mounts.length, 1);
  assert.equal(w.document.getElementById('recognitionSlotCamera0').children.length, 6);
  w.metadata(0, 1, {tracks: [{recognized: true}]});
  w.api.selectCamera(0, 2);
  assert.equal(w.mounts.length, 2); assert.deepEqual(w.stops, ['recognition-slot-0']);
  assert.equal(w.api.getSelection().camera.id, 2); assert.equal(w.api.getSelection().metadata, null);
  w.metadata(0, 1, {tracks: [{recognized: true}]});
  assert.equal(w.api.getSelection().metadata, null);
  w.api.selectCamera(0, 1);
  assert.equal(w.mounts.length, 3);
  assert.equal(w.requests.some(request => request.init.method), false, 'no source, AI, appearance or recording mutation');
  w.document.hidden = true; w.fire('visibilitychange'); assert.equal(w.timers.size, 0);
  w.document.hidden = false; w.fire('visibilitychange'); await flush();
  assert.equal(w.mounts.length, 4); assert.equal(w.timers.size, 1);
});

test('single view initially prefers configured AI but never overrides an explicit camera choice', async () => {
  const w = browser({single:true, cameras:[camera(1,{ai_enabled:false,ai_state:'DISABLED'}),camera(2)]}); await flush();
  assert.equal(w.mounts[0].config.cameraId,2);
  w.api.selectCamera(0,1); await w.api.refresh();
  assert.equal(w.api.getSelection().camera.id,1);
  assert.equal(w.requests.some(request=>request.init.method),false);
});

test('camera switch cards and arrows use only permitted enabled cameras without extra streams or requests', async () => {
  const w = browser({single: true, cameras: [camera(1), camera(2, {enabled: false}), camera(3), camera(4)]}); await flush();
  const strip = w.document.getElementById('recognitionCameraStrip');
  assert.equal(strip.children.length, 3); assert.equal(w.mounts.length, 1);
  assert.equal(strip.children[0].attributes['aria-pressed'], 'true');
  strip.children[1].dispatchEvent(new Event('click')); assert.equal(w.api.getSelection().camera.id, 3);
  assert.equal(strip.children[1].attributes['aria-pressed'], 'true'); assert.equal(strip.children[0].attributes['aria-pressed'], 'false');
  w.document.getElementById('recognitionCameraNext').dispatchEvent(new Event('click')); assert.equal(w.api.getSelection().camera.id, 4);
  w.document.getElementById('recognitionCameraNext').dispatchEvent(new Event('click')); assert.equal(w.api.getSelection().camera.id, 1);
  w.document.getElementById('recognitionCameraPrevious').dispatchEvent(new Event('click')); assert.equal(w.api.getSelection().camera.id, 4);
  assert.equal(w.mounts.length - w.stops.length, 1, 'one presentation owner remains');
  assert.deepEqual(w.requests.map(request => request.url), ['/api/v1/recognition/cameras'], 'no thumbnail or AI API');
});

test('thumbnail copies only the current displayed frame and clears on switch, failure and scope suspension', async () => {
  const w = browser({single: true, cameras: [camera(1), camera(2)]}); await flush();
  const strip = w.document.getElementById('recognitionCameraStrip'), preview = index => strip.children[index].children[0].children[1];
  const first = preview(0), video = w.mounts[0].config.video;
  video.classList.add('btmh-media-active'); video.videoWidth = 640; video.videoHeight = 360;
  assert.equal(first.hidden, true);
  w.fire('btmh:media-state', {key: 'recognition-slot-0', cameraId: 1, state: 'live'});
  assert.equal(first.hidden, false); assert.equal(w.previewDraws[0][0], video);
  assert.deepEqual(w.previewDraws[0].slice(1).map(value => Math.round(value * 1000) / 1000 || 0), [0, 0, 176, 99], 'thumbnail preserves source aspect ratio');
  w.api.selectCamera(0, 2); assert.equal(first.hidden, true); assert.equal(first.width, 176);
  w.fire('btmh:media-stats', {key: 'recognition-slot-0', cameraId: 1, state: 'live'});
  assert.equal(w.previewDraws.length, 1, 'late previous-camera frame ignored'); assert.equal(preview(1).hidden, true);
  const second = preview(1), frame = w.mounts.at(-1).config.image;
  video.classList.remove('btmh-media-active'); // The media owner retires this layer before its fallback becomes active.
  frame.classList.add('btmh-media-active'); frame.naturalWidth = 640; frame.naturalHeight = 480;
  w.fire('btmh:media-stats', {key: 'recognition-slot-0', cameraId: 2, state: 'live'});
  assert.equal(second.hidden, false); assert.equal(w.previewDraws.at(-1)[0], frame);
  assert.deepEqual(w.previewDraws.at(-1).slice(1), [22, 0, 132, 99], 'letterboxed thumbnail');
  w.drawError = true; w.fire('btmh:media-stats', {key: 'recognition-slot-0', cameraId: 2, state: 'live'}); assert.equal(second.hidden, true);
  w.drawError = false; w.fire('btmh:media-stats', {key: 'recognition-slot-0', cameraId: 2, state: 'live'}); assert.equal(second.hidden, false);
  w.fire('btmh:media-state', {key: 'recognition-slot-0', cameraId: 2, state: 'failed'}); assert.equal(second.hidden, true);
  w.document.hidden = true; w.fire('visibilitychange'); assert.equal(strip.children.length, 0); assert.equal(second.hidden, true);
  assert.equal(w.requests.length, 1); assert.equal(w.timers.size, 0);
});

test('camera switch cards release revoked scopes and cannot act after logout', async () => {
  const w = browser({single: true, cameras: [camera(1), camera(2)]}); await flush();
  const strip = w.document.getElementById('recognitionCameraStrip'), revokedButton = strip.children[1];
  const preview = strip.children[0].children[0].children[1]; preview.hidden = false;
  w.cameras = [camera(1, {camera_name: 'Tên mới', store_id: 2})]; await w.api.refresh();
  assert.equal(preview.hidden, true, 'store reassignment clears the previous thumbnail');
  assert.equal(strip.children.length, 1); assert.equal(strip.children[0].children[1].textContent, 'Tên mới');
  assert.equal(w.document.getElementById('recognitionCameraNext').disabled, true);
  revokedButton.dispatchEvent(new Event('click')); assert.equal(w.api.getSelection().camera.id, 1);
  const oldButton = strip.children[0], mounts = w.mounts.length;
  w.authenticated = false; w.fire('btmh:auth', {authenticated: false}); assert.equal(strip.children.length, 0);
  oldButton.dispatchEvent(new Event('click')); assert.equal(w.mounts.length, mounts); assert.equal(w.api.getSelection().camera, null);
});

test('switching a slot retires only its owner, rejects non-registry IDs and discards previous metadata', async () => {
  const w = browser(); await flush(); w.metadata(1, 2, {tracks: [{track_id: 'same', recognized: true}]});
  w.mounts[1].config.empty.classList.add('hidden');
  w.api.selectSlot(1); assert.equal(w.api.getSelection().metadata.camera_id, 2);
  w.api.selectCamera(1, 5); assert.deepEqual(w.stops, ['recognition-slot-1']); assert.equal(w.mounts.length, 5);
  assert.equal(w.mounts[1].config.empty.classList.contains('hidden'), false, 'switch clears the previous live empty-state suppression');
  assert.equal(w.mounts.at(-1).config.cameraId, 5); assert.equal(w.api.getSelection().metadata, null);
  w.metadata(1, 2); assert.equal(w.api.getSelection().metadata, null, 'stale old camera cannot overwrite selection');
  w.fire('btmh:media-metadata', {key: 'recognition-slot-1', cameraId: 5, meta: {camera_id: 2, tracks: []}});
  assert.equal(w.api.getSelection().metadata, null, 'payload camera must also match');
  w.api.selectCamera(1, 999); assert.equal(w.mounts.length, 5); assert.equal(w.api.getSelection().camera.id, 5);
  w.metadata(0, 1); assert.equal(w.api.getSelection().metadata, null, 'unselected result stays local');
  w.metadata(1, 5, {tracks: [{track_id: 'same'}]}); assert.equal(w.api.getSelection().metadata.camera_id, 5);
});

test('registry refresh renames without remounting, preserves intentional empty slots and revokes removed cameras', async () => {
  const w = browser(); await flush(); w.api.selectCamera(2, '');
  w.cameras = [camera(1, {camera_name: 'Hà Đông - Cửa vào'}), camera(3), camera(4), camera(5)]; await w.api.refresh();
  assert.equal(w.mounts.length, 4); assert.ok(w.stops.includes('recognition-slot-1'));
  assert.equal(w.document.getElementById('recognitionSlotCamera1').value, '');
  assert.equal(w.document.getElementById('recognitionSlotCamera2').value, '', 'refresh does not silently reassign an empty slot');
  assert.equal(w.cards()[0].children[0].children[0].children[1].textContent, 'Hà Đông - Cửa vào');
});

test('hidden page, pagehide and navigation stop presentation, reject late metadata and resume only once', async () => {
  const w = browser(); await flush();
  w.document.hidden = true; w.fire('visibilitychange'); assert.equal(w.stops.length, 4); assert.equal(w.timers.size, 0);
  const before = w.selections.length; w.metadata(0, 1); assert.equal(w.selections.length, before);
  w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.mounts.length, 8);
  w.fire('visibilitychange'); assert.equal(w.mounts.length, 8); assert.equal(w.timers.size, 1);
  w.fire('pagehide', {}, w.window); assert.equal(w.timers.size, 0); w.api.start(); assert.equal(w.mounts.length, 8);
  w.fire('pageshow', {}, w.window); await flush(); assert.equal(w.mounts.length, 12);
  w.page.classList.remove('active'); w.fire('btmh:navigate', {page: 'history'}); assert.equal(w.timers.size, 0);
  assert.equal(w.requests.some(item => /(?:start|stop|select|configuration)/.test(item.url)), false);
});

test('auth scope reset clears all choices and late list responses cannot mount after logout', async () => {
  const w = browser({hold: true}); await flush(); const pending = w.pending;
  w.authenticated = false; w.fire('btmh:auth', {authenticated: false}); assert.equal(pending.init.signal.aborted, true);
  pending.resolve({items: [camera(99)]}); await flush(); assert.equal(w.mounts.length, 0); assert.equal(w.api.getSelection().camera, null);
  w.hold = false; w.cameras = [camera(7)]; w.authenticated = true; w.fire('btmh:auth', {authenticated: true}); await flush();
  assert.equal(w.mounts.length, 1); assert.equal(w.api.getSelection().camera.id, 7);
  assert.equal(w.document.getElementById('recognitionSlotCamera0').children.length, 2);
});

test('no work starts without permission/current page and refresh is single-flight', async () => {
  for (const options of [{permission: false}, {authenticated: false}, {hidden: true}, {offPage: true}]) {
    const w = browser(options); await flush(); assert.equal(w.requests.length, 0); assert.equal(w.mounts.length, 0); assert.equal(w.timers.size, 0);
  }
  const w = browser({hold: true}); await flush(); await w.api.refresh(); w.api.start();
  assert.equal(w.requests.length, 1); w.pending.resolve({items: [camera(1)]}); await flush(); assert.equal(w.mounts.length, 1);
});

test('video/AI/recording states remain separate and fullscreen preserves the same main media owner', async () => {
  const w = browser({cameras: [camera(1, {ai_state: 'WAITING_FOR_CAPACITY', recording_active: true}), camera(2, {ai_state: 'DISABLED', recording_active: null})]}); await flush();
  const statuses = index => w.cards()[index].children.at(-1).children;
  assert.equal(statuses(0)[0].textContent, 'Đang kết nối'); assert.equal(statuses(0)[1].textContent, 'AI chờ lượt xử lý'); assert.equal(statuses(0)[2].textContent, 'Đang ghi hình');
  assert.equal(statuses(1)[1].textContent, 'AI chưa bật'); assert.equal(statuses(1)[2].textContent, 'Chưa có trạng thái ghi hình');
  w.fire('btmh:media-state', {key: 'recognition-slot-0', cameraId: 1, state: 'live', transport: 'internal-transport', fallbackReason: 'internal-error'});
  assert.equal(statuses(0)[0].textContent, 'LIVE'); assert.equal(statuses(0)[1].textContent, 'AI chờ lượt xử lý');
  w.cards()[0].children[0].children[1].dispatchEvent(new Event('click')); await flush();
  assert.equal(w.fullscreenRequests, 1); assert.equal(w.mounts.length, 2); assert.equal(w.stops.length, 0);
  w.api.stop(); await flush(); assert.equal(w.document.fullscreenElement, null);
});

test('few/disabled cameras leave empty slots and list failure keeps retry available', async () => {
  const w = browser({cameras: [camera(1), camera(2, {enabled: false})]}); await flush(); assert.equal(w.mounts.length, 1);
  assert.equal(w.document.getElementById('recognitionSlotCamera1').value, '');
  w.error = new Error('offline'); await w.api.refresh(); assert.match(w.document.getElementById('recognitionSlotsNote').textContent, /Tải lại/);
  w.error = null; await w.api.refresh(); assert.equal(w.mounts.length, 1);
});

function productFunction(name) {
  const expression = new RegExp(`(?:async )?function ${name}\\([^\\n]*\\)\\s*\\{[\\s\\S]*?\\n\\}`);
  const match = appSource.match(expression); assert.ok(match, `missing ${name}`); return match[0];
}

function selectedPanel(w) {
  for (const id of ['recognitionSelectedContext', 'profileName', 'profileCode', 'profileAvatar', 'profileConfidence', 'profileCamera', 'profileSubject', 'profileClass', 'profileFaculty', 'profileLiveness', 'profileTime', 'profileDirection', 'recognitionSnapshot', 'recognitionSnapshotEmpty', 'recognitionAlert']) w.register(id);
  Object.assign(w.context, {$: selector => w.document.getElementById(selector.slice(1)), state: {recognitionProfileKey: ''},
    initials: name => name.slice(0, 1), pct: value => Math.round(value * 100), formatTime: value => value,
    setEntryBadge: (...args) => {w.badge = args;}, setRecognitionProgress: (...args) => {w.progress = args;}});
  vm.runInContext(productFunction('renderRecognitionSlotSelection'), w.context);
  return detail => w.context.renderRecognitionSlotSelection(detail);
}

test('selected result hides unverified identity and old snapshots and never invents entrance direction', async () => {
  const w = browser(); await flush(); selectedPanel(w);
  const snapshot = w.document.getElementById('recognitionSnapshot'); snapshot.src = 'old-camera-photo';
  const invoke = metadata => w.context.renderRecognitionSlotSelection({camera: camera(2), metadata});
  invoke({camera_id: 2, updated_at: 1700000000, tracks: [{track_id: 'same', full_name: 'Candidate identity', student_code: 'private', recognized: false, status: 'CHECKING', pad_status: 'PENDING'}]});
  assert.equal(w.document.getElementById('profileName').textContent, 'Đang xác minh'); assert.equal(w.document.getElementById('profileCode').textContent, 'Kết quả từ camera đang chọn');
  assert.equal(snapshot.src, ''); assert.equal(snapshot.style.display, 'none'); assert.equal(w.document.getElementById('profileDirection').textContent, 'Chưa ghi nhận');
  assert.equal(w.document.getElementById('profileSubject').textContent, 'Chưa xác định'); assert.equal(w.document.getElementById('profileCamera').textContent, 'Camera 2');
  invoke({camera_id: 2, updated_at: 1700000000, tracks: [{track_id: 'same', full_name: 'Verified employee', student_code: 'EMP-2', recognized: true, confidence: .93, status: 'RECOGNIZED', pad_status: 'PASS'}]});
  assert.equal(w.document.getElementById('profileName').textContent, 'Verified employee'); assert.equal(w.document.getElementById('profileConfidence').textContent, '93%');
  assert.match(w.context.state.recognitionProfileKey, /^2:same:/); assert.equal(w.document.getElementById('profileDirection').textContent, 'Chưa ghi nhận');
  assert.equal(w.document.getElementById('profileSubject').textContent, 'Nhân viên');
  invoke({camera_id: 1, tracks: [{recognized: true, full_name: 'Wrong camera'}]}); assert.equal(w.document.getElementById('profileName').textContent, 'Đang chờ dữ liệu nhận diện');
  invoke({camera_id: 2, tracks: [{recognized: true, spoof_blocked: true, full_name: 'Blocked identity'}]}); assert.equal(w.document.getElementById('profileName').textContent, 'Không qua xác minh');
});

test('unavailable AI states replace cached identity with precise guidance and no invented verification progress', async () => {
  const w = browser(); await flush(); const render = selectedPanel(w);
  const cases = [
    [{ai_enabled: false, ai_state: 'DISABLED'}, 'AI chưa bật', /Quản lý camera.*Nhận diện AI.*Lưu cấu hình/],
    [{store_id: null, ai_state: 'OFFLINE'}, 'AI chưa được gán cửa hàng', /gán cửa hàng và khu vực/],
    [{zone_name: '', ai_state: 'OFFLINE'}, 'AI chưa được đặt khu vực', /gán cửa hàng và khu vực/],
    [{ai_state: 'ERROR', ai_error_code: 'AI_PROCESS_FAILED'}, 'AI gặp lỗi xử lý', /Chưa có kết quả nhận diện mới/],
    [{ai_state: 'PAUSED'}, 'AI đang tạm dừng', /tạm dừng/],
    [{ai_state: 'STARTING'}, 'AI đang khởi động', /khung hình đầu tiên/],
    [{ai_state: 'WAITING_FOR_CAPACITY'}, 'AI chờ lượt xử lý', /chờ dung lượng xử lý/],
    [{ai_state: 'STOPPING'}, 'AI đang chuyển trạng thái', /dừng để áp dụng/],
    [{ai_state: 'OFFLINE'}, 'AI mất kết nối', /khung hình cho AI/],
    [{ai_state: 'OFFLINE', reason_code: 'AI_WORKER_START_FAILED'}, 'AI chưa khả dụng', /Không khởi động được/],
    [{ai_state: 'PRIVATE_INTERNAL_REASON'}, 'Chưa có trạng thái AI', /Tải lại/],
  ];
  for (const [extra, title, guidance] of cases) {
    render({camera: camera(2, extra), metadata: {camera_id: 2, ai_state: 'ACTIVE', updated_at: 1700000000, tracks: [{recognized: true, full_name: 'Old authorized identity', student_code: 'EMP-2', confidence: .99, pad_status: 'PASS'}]}});
    assert.equal(w.document.getElementById('profileName').textContent, title);
    assert.match(w.document.getElementById('profileCode').textContent, guidance);
    assert.equal(w.document.getElementById('profileConfidence').textContent, '—');
    assert.equal(w.document.getElementById('profileLiveness').textContent, '—');
    assert.equal(w.document.getElementById('profileTime').textContent, '—');
    assert.deepEqual(w.progress, [0, title]); assert.deepEqual(w.badge, [title, 'neutral']);
    assert.equal(w.context.state.recognitionProfileKey, '');
    assert.equal(/Old authorized identity|AI_PROCESS_FAILED|PRIVATE_INTERNAL_REASON/.test(w.document.getElementById('recognitionAlert').textContent), false);
  }
  w.permission = false;
  render({camera: camera(2, {ai_enabled: false, ai_state: 'DISABLED'})});
  assert.match(w.document.getElementById('profileCode').textContent, /Liên hệ người quản lý/);
});

test('active AI waiting or checking preserves zero verification fraction without claiming ready or verified', async () => {
  const w = browser(); await flush(); const render = selectedPanel(w);
  render({camera: camera(2)}); assert.deepEqual(w.progress, [0, 'Chờ dữ liệu nhận diện']);
  render({camera: camera(2), metadata: {camera_id: 2, tracks: []}}); assert.deepEqual(w.progress, [0, 'Chờ khuôn mặt']);
  for (const status of ['CHECKING', 'VERIFYING_PASSIVE', 'OBSERVING_QUALITY', 'UNREGISTERED']) {
    render({camera: camera(2), metadata: {camera_id: 2, tracks: [{status, recognized: false, full_name: 'Unverified candidate', confidence: .99}]}});
    assert.deepEqual(w.progress, [0, 'Đang quan sát']); assert.equal(w.document.getElementById('profileConfidence').textContent, '—');
    assert.notEqual(w.document.getElementById('profileName').textContent, 'Unverified candidate');
  }
});

test('expired current-camera metadata hides the former verified identity and progress', async () => {
  const w = browser(); await flush(); const render = selectedPanel(w);
  render({camera: camera(2), metadata: {camera_id:2, metadata_stale:true, updated_at:1700000000,
    tracks:[{recognized:true,full_name:'Former identity',confidence:.99,pad_status:'PASS'}]}});
  assert.equal(w.document.getElementById('profileName').textContent, 'Chờ dữ liệu nhận diện mới');
  assert.equal(w.document.getElementById('profileConfidence').textContent, '—');
  assert.equal(w.document.getElementById('profileTime').textContent, '—');
  assert.equal(w.context.state.recognitionProfileKey, '');
  assert.deepEqual(w.progress, [0, 'Chờ dữ liệu nhận diện mới']);
});

test('selected panel explains quality and PAD waits without promoting an employee identity', async () => {
  const w = browser(); await flush(); const render = selectedPanel(w);
  for (const [code, message] of [['FACE_POSE', /Góc mặt/], ['FACE_BLUR', /chưa đủ nét/], ['PAD_CHECKING', /Passive PAD/], ['PAD_BLOCKED', /danh tính vẫn bị chặn/]]) {
    render({camera: camera(2), metadata: {camera_id: 2, tracks: [{verification_reason_code: code, status: 'VERIFYING_PASSIVE', recognized: false, full_name: 'Private candidate'}]}});
    assert.match(w.document.getElementById('profileCode').textContent, message);
    assert.notEqual(w.document.getElementById('profileName').textContent, 'Private candidate');
    assert.deepEqual(w.progress, [0, 'Đang quan sát']);
  }
});

test('latest registry and metadata AI states win over cached state without changing video or AI configuration', async () => {
  const w = browser({cameras: [camera(1)]}); await flush();
  const badge = () => w.cards()[0].children.at(-1).children[1].textContent;
  w.metadata(0, 1, {ai_state: 'DISABLED'}); assert.equal(badge(), 'AI chưa bật');
  w.cameras = [camera(1)]; await w.api.refresh(); assert.equal(badge(), 'AI đang hoạt động');
  w.metadata(0, 1, {ai_state: 'ACTIVE', tracks: [{recognized: true, full_name: 'Previous identity'}]});
  w.cameras = [camera(1, {ai_state: 'ERROR', reason_code: 'AI_PROCESS_FAILED'})]; await w.api.refresh();
  assert.equal(badge(), 'AI gặp lỗi xử lý'); assert.equal(w.api.getSelection().metadata, null);
  w.metadata(0, 1, {ai_state: 'PAUSED', reason_code: 'AI_PAUSED'}); assert.equal(badge(), 'AI đang tạm dừng');
  assert.equal(w.api.getSelection().camera.reason_code, 'AI_PAUSED');
  w.metadata(0, 1, {ai_state: 'PRIVATE_INTERNAL_REASON', reason_code: 'private diagnostic'}); assert.equal(badge(), 'AI đang tạm dừng');
  assert.equal(w.mounts.length, 1); assert.equal(w.stops.length, 0); assert.ok(w.requests.every(request => request.init.method === undefined));
  w.cameras = [camera(1, {store_id: 2})]; await w.api.refresh(); assert.equal(w.api.getSelection().metadata, null);
});

test('legacy global recognition polling cannot overwrite slots; dashboard still uses its existing endpoint', async () => {
  const requests = [], context = {window: {BTMHRecognitionSlots: {}}, appPresentationActive: () => true, hasUiPermission: () => true,
    state: {activePage: 'recognition', presentationEpoch: 1}, api: async url => {requests.push(url); return {tracks: []};},
    $: () => null, setSignal() {}, renderDashboardPeople() {}, console};
  vm.createContext(context); vm.runInContext(productFunction('pollRecognition'), context);
  await context.pollRecognition(); assert.equal(requests.length, 0);
  context.state.activePage = 'dashboard'; await context.pollRecognition(); assert.deepEqual(requests, ['/api/v1/camera/latest-result', '/api/v1/camera/latest-event']);
});

test('existing video badge never reveals transport or fallback diagnostics', () => {
  const badge = {classList: {toggle() {}}, innerHTML: '', title: ''};
  const context = {$: selector => selector === '#v13DashboardLive' ? badge : null};
  vm.createContext(context); vm.runInContext(productFunction('renderMediaPlayback'), context);
  context.renderMediaPlayback({key: 'dashboard', state: 'live', transport: 'secret-internal-transport', fallbackReason: 'secret-internal-error'});
  assert.equal(badge.innerHTML, '<i></i> LIVE'); assert.equal(badge.title, 'LIVE');
  context.renderMediaPlayback({key: 'dashboard', state: 'failed', transport: 'internal'}); assert.equal(badge.title, 'Mất kết nối');
});

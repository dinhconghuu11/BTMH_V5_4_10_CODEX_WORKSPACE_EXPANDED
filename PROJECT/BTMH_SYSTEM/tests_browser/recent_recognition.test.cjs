'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_recent_recognition.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
const selected = id => ({camera_id: id, camera_name: `Camera ${id}`, store_name: 'Hà Đông', zone_name: 'Cửa vào', store_id: 1, ai_enabled: true, ai_state: 'ACTIVE'});
const row = (id = 1, extra = {}) => ({id, event_id: id, appearance_id: `appearance-${id}`, daily_sequence: id, business_date: '2026-10-08',
  camera_id: 1, camera_name: 'Cửa vào', store_name: 'Hà Đông', zone_name: 'Sảnh', event_at: '2026-10-08T01:02:03Z', subject_type: 'EMPLOYEE',
  recognized: true, faceid_status: 'VERIFIED', pad_status: 'PASS', status: 'RECOGNIZED', full_name: `Nhân viên ${id}`, student_code: `EMP-${id}`, department: 'Tư vấn', ...extra});

function browser(options = {}) {
  const photoRequests = [], pendingPhotos = [], createdUrls = [], revokedUrls = [];
  const w = {authenticated: true, permission: true, camera: selected(1), items: [row()], requests: [], images: [], timers: new Map(), next: 0, ...options};
  const document = new EventTarget(); document.hidden = !!w.hidden; document.activeElement = null;
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.style = {}; this.attributes = {}; this.className = ''; this.hidden = false; this._text = ''; if (tag === 'img') w.images.push(this); }
    set textContent(value) { this.textWrites = (this.textWrites || 0) + 1; this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    get classList() { return {contains: value => this.className.split(/\s+/).includes(value), add: value => this.classList.toggle(value, true), remove: value => this.classList.toggle(value, false), toggle: (value, on) => { const names = new Set(this.className.split(/\s+/).filter(Boolean)); if (on ?? !names.has(value)) names.add(value); else names.delete(value); this.className = [...names].join(' '); }}; }
    append(...children) { for (const child of children) { child.remove(); child.parentElement = this; this.children.push(child); } }
    insertBefore(child, next) { child.remove(); const index = next ? this.children.indexOf(next) : this.children.length; assert.ok(index >= 0); child.parentElement = this; this.children.splice(index, 0, child); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
    replaceChildren(...children) { for (const child of this.children) child.parentElement = null; this.children = []; this._text = ''; this.append(...children); }
    querySelectorAll(selector) { const matches = child => selector === 'img' ? child.tagName === 'IMG' : selector.startsWith('.') && child.classList.contains(selector.slice(1)); return this.children.flatMap(child => [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; }
    focus() { document.activeElement = this; }
  }
  const roots = new Map();
  const register = (id, tag = 'div') => { const node = new Element(tag); node.id = id; roots.set(id, node); return node; };
  for (const id of ['recentRecognitionItems', 'recentRecognitionNote', 'recentRecognitionCount', 'recentRecognitionDetail', 'recentRecognitionDetailContent', 'recentRecognitionDetailClose', 'recentRecognitionDetailBackdrop', 'recentRecognitionRefresh', 'recentRecognitionContext', 'recentRecognitionDetailTitle', 'profileName']) register(id);
  roots.get('recentRecognitionDetail').hidden = true; roots.get('profileName').textContent = 'Live selected-camera identity';
  const page = register('page-recognition'); page.className = w.offPage ? 'page' : 'page active';
  document.getElementById = id => roots.get(id) || null; document.createElement = tag => new Element(tag);
  const window = new EventTarget(); window.BTMHRecognitionSlots = {getSelection: () => ({camera: w.camera})};
  const api = async (url, init) => {
    const request = {url, init};
    if (init?.rawResponse) {
      photoRequests.push(request);
      if (w.photoHold) return new Promise((resolve, reject) => pendingPhotos.push({resolve, reject, ...request}));
      if (w.photoError) throw w.photoError;
      return {blob: async () => ({size: 100, type: 'image/jpeg'})};
    }
    w.requests.push(request); if (w.hold) return new Promise((resolve, reject) => { w.pending = {resolve, reject, ...request}; }); if (w.error) throw w.error; return {items: w.items};
  };
  class ImageURL extends URL {
    static createObjectURL(blob) { const value = `blob:btmh-${createdUrls.length + 1}`; createdUrls.push({value, blob}); return value; }
    static revokeObjectURL(value) { revokedUrls.push(value); }
  }
  w.now = 1000000; class Clock extends Date { static now() { return w.now; } }
  const context = {window, document, location: {origin: 'https://btmh.local'}, Event, CustomEvent, AbortController, URL: ImageURL, api, Date: Clock, state: {authUser: {id: 1}},
    appPresentationActive: () => w.authenticated && !document.hidden, hasUiPermission: key => w.permission && (key !== 'evidence.view' || w.evidencePermission !== false),
    setInterval: callback => { const id = ++w.next; w.timers.set(id, callback); return id; }, clearInterval: id => w.timers.delete(id)};
  vm.createContext(context); vm.runInContext(source, context);
  w.context = context; w.api = window.BTMHRecentRecognition; w.document = document; w.window = window; w.roots = roots; w.page = page;
  Object.assign(w, {photoRequests, pendingPhotos, createdUrls, revokedUrls});
  w.fire = (name, detail, target = document) => target.dispatchEvent(new CustomEvent(name, {detail}));
  w.host = () => roots.get('recentRecognitionItems');
  w.cards = () => w.host().children.filter(node => node.className === 'recent-recognition-item');
  w.select = (camera, metadata) => { w.camera = camera; w.fire('btmh:recognition-selection', {camera, metadata}); };
  w.tick = async (advance = 30000) => { w.now += advance; for (const callback of [...w.timers.values()]) callback(); await flush(); };
  return w;
}

test('only the selected camera is queried, results are bounded20 and wrong-camera rows are rejected', async () => {
  const w = browser({items: [row(99, {camera_id: 99}), ...Array.from({length: 30}, (_, index) => row(index + 1))]}); await flush();
  assert.equal(w.requests[0].url, '/api/v1/recognition/recent?limit=20&camera_id=1');
  assert.equal(w.cards().length, 20); assert.equal(w.roots.get('recentRecognitionCount').textContent, '20');
  assert.equal(w.host().textContent.includes('Nhân viên 99'), false);
  assert.equal(w.requests[0].init.method, undefined, 'read-only display query');
  assert.equal(w.host().attributes['aria-busy'], 'false');
});

test('idle history does not refetch every 2.5 seconds and reconciles after thirty seconds', async () => {
  const w = browser(); await flush();
  await w.tick(2500); await w.tick(2500); assert.equal(w.requests.length, 1);
  await w.tick(25000); assert.equal(w.requests.length, 2);
});

test('unchanged history retains card content and list order without DOM rewrites', async () => {
  const w = browser(); await flush(); const card = w.cards()[0];
  const name = card.querySelector('.recent-recognition-heading').children[1], writes = name.textWrites;
  const count = w.roots.get('recentRecognitionCount'), countWrites = count.textWrites;
  await w.tick(); await w.tick();
  assert.equal(w.cards()[0], card); assert.equal(name.textWrites, writes); assert.equal(count.textWrites, countWrites);
});

test('pending selected tracks never request an evidence image before classification', async () => {
  const w = browser(); await flush(); const {image} = panel(w);
  for (let i = 0; i < 100; i++) {
    w.select(selected(1), {camera_id:1, tracks:[{event_id:100+i,status:'VERIFYING_PASSIVE',pad_status:'PENDING'}]});
    await flush();
  }
  assert.equal(w.photoRequests.length, 0); assert.equal(image.src || '', '');
});

test('unknown to verified upserts one appearance card despite a different event ID', async () => {
  const w = browser({items: [row(1, {recognized: false, faceid_status: 'UNKNOWN', status: 'UNREGISTERED', subject_type: 'VISITOR', full_name: 'Private candidate'})]}); await flush();
  const card = w.cards()[0]; assert.match(card.textContent, /Chưa xác định/); assert.equal(card.textContent.includes('Private candidate'), false);
  w.items = [row(2, {appearance_id: 'appearance-1', daily_sequence: 1, full_name: 'Đã xác minh A'})]; await w.api.refresh();
  assert.equal(w.cards().length, 1); assert.equal(w.cards()[0], card); assert.match(card.textContent, /Đã xác minh A/); assert.match(card.textContent, /#0001/);
});

test('unverified/blocked identity is hidden and missing sequence never falls back to event ID', async () => {
  const w = browser({items: [row(9188, {daily_sequence: null, recognized: false, faceid_status: 'CHECKING', status: 'ANALYZING', full_name: 'Candidate secret'}),
    row(2, {recognized: true, pad_status: 'FAIL', status: 'SPOOF_BLOCKED', full_name: 'Blocked secret'}),
    row(3, {recognized: true, faceid_status: 'VERIFIED', pad_status: 'PENDING', full_name: 'Waiting PAD secret'})]}); await flush();
  const text = w.host().textContent; assert.equal(/Candidate secret|Blocked secret|Waiting PAD secret|#9188/.test(text), false);
  assert.match(w.cards()[0].textContent, /Đang kiểm tra/); assert.match(w.cards()[1].textContent, /Không qua xác minh/);
  assert.equal(w.cards()[1].querySelector('.recent-recognition-state').classList.contains('blocked'), true);
});

test('unchanged automatic polls and repeated failures do not rewrite the live status', async () => {
  const w = browser(); await flush(); const note = w.roots.get('recentRecognitionNote'), settled = note.textWrites;
  await w.tick(); await w.tick(); assert.equal(note.textWrites, settled);
  w.error = new Error('offline'); await w.tick(); const failed = note.textWrites; await w.tick(); assert.equal(note.textWrites, failed);
  w.error = null; w.items = [row(1, {recognized: false, faceid_status: 'UNKNOWN', status: 'UNREGISTERED'})]; await w.tick(60000);
  assert.match(note.textContent, /#0001.*Chưa xác định/); assert.ok(note.textWrites > failed);
  assert.equal(w.cards()[0].querySelector('.recent-recognition-state').classList.contains('unknown'), true);
});

test('same appearance duplicates do not inflate count and new authoritative page retires old cards', async () => {
  const w = browser({items: [row(1), row(2, {appearance_id: 'appearance-1'}), row(3)]}); await flush(); assert.equal(w.cards().length, 2);
  w.items = [row(4)]; await w.api.refresh(); assert.equal(w.cards().length, 1); assert.equal(w.roots.get('recentRecognitionCount').textContent, '1');
});

test('camera change aborts old owner, clears old names and ignores a late response', async () => {
  const w = browser({hold: true}); await flush(); const old = w.pending;
  w.hold = false; w.items = [row(7, {camera_id: 2, camera_name: 'Camera 2', full_name: 'New scope'})]; w.select(selected(2)); await flush();
  assert.equal(old.init.signal.aborted, true); assert.match(w.requests.at(-1).url, /camera_id=2$/); assert.match(w.host().textContent, /New scope/);
  old.resolve({items: [row(1, {full_name: 'Old scope'})]}); await flush(); assert.equal(w.host().textContent.includes('Old scope'), false); assert.equal(w.cards().length, 1);
});

test('refresh and repeated selection notifications are single-flight, with one visible-page timer', async () => {
  const w = browser({hold: true}); await flush(); w.select(selected(1)); await w.api.refresh(); await w.tick();
  assert.equal(w.requests.length, 1); assert.equal(w.timers.size, 1);
  w.pending.resolve({items: [row()]}); await flush(); w.hold = false; await w.tick(); assert.equal(w.requests.length, 2);
});

test('auth/visibility/navigation/pagehide release requests, photos and modal; late metadata cannot restart hidden work', async () => {
  const w = browser({items: [row(1, {snapshot_url: '/api/v1/history/recognition/1/evidence.jpg'})]}); await flush();
  const button = w.cards()[0].children[0]; button.dispatchEvent(new Event('click'));
  assert.equal(w.roots.get('recentRecognitionDetail').hidden, false);
  w.document.hidden = true; w.fire('visibilitychange'); assert.equal(w.cards().length, 0); assert.equal(w.timers.size, 0); assert.equal(w.roots.get('recentRecognitionDetail').hidden, true);
  assert.ok(w.images.every(image => !image.src)); const count = w.requests.length; w.select(selected(1)); await flush(); assert.equal(w.requests.length, count);
  w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.timers.size, 1);
  w.fire('pagehide', {}, w.window); w.api.start(); assert.equal(w.timers.size, 0);
  w.fire('pageshow', {}, w.window); await flush(); assert.equal(w.timers.size, 1);
  w.page.classList.remove('active'); w.fire('btmh:navigate', {page: 'history'}); assert.equal(w.timers.size, 0);
  w.authenticated = false; w.fire('btmh:auth', {authenticated: false}); assert.equal(w.roots.get('recentRecognitionContext').textContent, 'Chưa chọn camera');
});

test('no selected camera/permission/auth/presentation produces no request and truthful empty state', async () => {
  for (const options of [{camera: null}, {permission: false}, {authenticated: false}, {hidden: true}, {offPage: true}]) {
    const w = browser(options); await flush(); assert.equal(w.requests.length, 0); assert.equal(w.timers.size, 0);
    if (!w.camera) assert.match(w.host().textContent, /Chọn camera/);
  }
});

test('snapshot permission absence, foreign URLs and load failures show honest placeholders; local protected crops can retry', async () => {
  const w = browser({items: [row(1), row(2, {snapshot_url: 'https://other.invalid/photo'}), row(3, {snapshot_url: '/api/v1/evidence/photo?token=secret'}), row(4, {snapshot_url: '/api/v1/history/recognition/4/evidence.jpg'})]}); await flush();
  assert.equal(w.images.filter(image => image.src).length, 1);
  const image = w.images.find(image => image.src); image.onload(); assert.equal(image.hidden, false);
  image.onerror(); assert.equal(image.hidden, true); assert.equal(image.src, '');
  w.now += 6000; await w.api.refresh(); await flush(); assert.match(image.src, /^blob:/);
});

function panel(w) {
  const image = w.document.createElement('img'), empty = w.document.createElement('span');
  w.roots.set('recognitionSnapshot', image); w.roots.set('recognitionSnapshotEmpty', empty); return {image, empty};
}

test('protected recent photo uses the authenticated API and releases object URLs when retired', async () => {
  const w = browser({items: [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg'})]}); await flush();
  assert.equal(w.photoRequests.length, 1); const request = w.photoRequests[0];
  assert.equal(request.init.rawResponse, true); assert.equal(request.init.credentials, 'same-origin'); assert.equal(request.init.cache, 'no-store');
  assert.equal(/token|password|secret/.test(request.url), false);
  const image = w.images.find(image => image.src); assert.match(image.src, /^blob:/); image.onload(); assert.equal(image.hidden, false);
  const url = image.src; w.items = []; await w.api.refresh(); assert.equal(image.src, ''); assert.ok(w.revokedUrls.includes(url));
});

test('hidden recent and detail photos load eagerly before onload reveals them', async () => {
  const w = browser({items: [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg'})]}); await flush();
  const image = w.cards()[0].querySelector('img');
  assert.equal(image.hidden, true); assert.equal(image.loading, 'eager', 'hidden lazy images never trigger the onload that reveals them');
  w.cards()[0].children[0].dispatchEvent(new Event('click')); await flush();
  assert.equal(w.roots.get('recentRecognitionDetailContent').querySelector('img').loading, 'eager');
});

test('unchanged automatic recent polls preserve an open evidence image and its in-flight owner', async () => {
  const w = browser({photoHold: true, items: [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg'})]}); await flush();
  w.cards()[0].children[0].dispatchEvent(new Event('click')); await flush();
  const image = w.roots.get('recentRecognitionDetailContent').querySelector('img'), request = w.pendingPhotos[1];
  await w.api.refresh(); await w.api.refresh();
  assert.equal(request.init.signal.aborted, false, 'automatic polls must not restart a saved image download');
  assert.equal(w.roots.get('recentRecognitionDetailContent').querySelector('img'), image);
  assert.equal(w.photoRequests.length, 2, 'one card photo and one detail photo');
  request.resolve({blob: async () => ({size: 100, type: 'image/jpeg'})}); await flush(); image.onload();
  const url = image.src; await w.api.refresh();
  assert.equal(image.src, url); assert.equal(image.hidden, false); assert.equal(w.revokedUrls.includes(url), false);
});

test('manual refresh retries a failed detail photo and actual row changes still update its identity', async () => {
  const w = browser({photoError: new Error('HTTP 404'), items: [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg'})]}); await flush();
  w.cards()[0].children[0].dispatchEvent(new Event('click')); await flush();
  const content = w.roots.get('recentRecognitionDetailContent'), failedImage = content.querySelector('img');
  assert.equal(failedImage.src || '', '');
  w.photoError = null; w.roots.get('recentRecognitionRefresh').dispatchEvent(new Event('click')); await flush();
  const retriedImage = content.querySelector('img'); assert.notEqual(retriedImage, failedImage); assert.match(retriedImage.src, /^blob:/);
  w.items = [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg',recognized:false,pad_status:'FAIL',status:'SPOOF_BLOCKED'})];
  await w.api.refresh();
  assert.match(content.textContent, /Không qua xác minh/);
  assert.equal(content.textContent.includes('EMP-1'), false);
  assert.equal(w.roots.get('recentRecognitionDetailTitle').textContent.includes('Nhân viên 1'), false);
  assert.equal(retriedImage.src, '');
});

test('evidence requests are bounded to three in flight and retired queued photos never start', async () => {
  const w = browser({photoHold: true, items: Array.from({length: 20}, (_, i) => row(i + 1, {snapshot_url: `/api/v1/events/${i + 1}/evidence.jpg`}))}); await flush();
  assert.equal(w.photoRequests.length, 3);
  w.authenticated = false; w.fire('btmh:auth', {authenticated: false});
  for (const pending of w.pendingPhotos) { assert.equal(pending.init.signal.aborted, true); pending.resolve({blob: async () => ({size: 100, type: 'image/jpeg'})}); }
  await flush(); assert.equal(w.photoRequests.length, 3); assert.equal(w.createdUrls.length, 0);
});

test('saved-photo responses cannot cross camera change, logout, permission revocation or card removal', async () => {
  for (const change of [
    w => { w.items = []; w.select(selected(2)); },
    w => { w.authenticated = false; w.fire('btmh:auth', {authenticated: false}); },
    w => { w.evidencePermission = false; w.select(selected(1)); },
    async w => { w.items = []; await w.api.refresh(); },
  ]) {
    const w = browser({photoHold: true, items: [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg'})]}); await flush();
    const pending = w.pendingPhotos[0]; assert.ok(pending); await change(w);
    pending.resolve({blob: async () => ({size: 100, type: 'image/jpeg'})}); await flush();
    assert.equal(w.images.some(image => image.src), false); assert.equal(w.createdUrls.length, 0);
  }
});

test('selected live track loads only its own saved event photo, coalesces metadata and clears on no track', async () => {
  const w = browser(); await flush(); const {image, empty} = panel(w);
  const metadata = {camera_id: 1, tracks: [{event_id: 23, recognized: true, pad_status: 'PASS'}]};
  w.select(selected(1), metadata); await flush(); assert.equal(w.photoRequests.at(-1).url, '/api/v1/events/23/evidence.jpg');
  const url = image.src; image.onload(); assert.equal(empty.hidden, true);
  w.select(selected(1), metadata); await flush(); assert.equal(image.src, url); assert.equal(w.photoRequests.length, 1);
  w.select(selected(1), {camera_id: 2, tracks: metadata.tracks}); assert.equal(image.src, ''); assert.ok(w.revokedUrls.includes(url));
  for (const camera of [{...selected(1), ai_enabled: false}, {...selected(1), ai_state: 'ERROR'}]) {
    w.select(camera, metadata); await flush(); assert.equal(image.src, '');
  }
  assert.equal(w.photoRequests.length, 1);
});

test('selected image does not reuse recent history and respects evidence permission and source changes', async () => {
  const w = browser({photoHold: true}); await flush(); const {image} = panel(w);
  w.select(selected(1), {camera_id: 1, tracks: [{event_id: 8, recognized: true}]}); await flush(); const pending = w.pendingPhotos[0];
  w.select(selected(2), {camera_id: 2, tracks: []}); assert.equal(pending.init.signal.aborted, true);
  pending.resolve({blob: async () => ({size: 100, type: 'image/jpeg'})}); await flush(); assert.equal(image.src, '');
  w.evidencePermission = false; w.select(selected(2), {camera_id: 2, tracks: [{event_id: 9, recognized: true}]}); await flush(); assert.equal(w.photoRequests.length, 1);
});

test('expired metadata releases the selected photo even when a stale caller retains a track', async () => {
  const w = browser({photoHold: true}); await flush(); const {image} = panel(w);
  const metadata = {camera_id: 1, tracks: [{event_id: 23, recognized: true}]};
  w.select(selected(1), metadata); await flush(); const pending = w.pendingPhotos[0];
  w.select(selected(1), {...metadata, metadata_stale: true});
  assert.equal(pending.init.signal.aborted, true);
  pending.resolve({blob: async () => ({size: 100, type: 'image/jpeg'})}); await flush();
  assert.equal(image.src, ''); assert.equal(w.photoRequests.length, 1);
});

test('store reassignment and evidence permission revocation abort and hide existing photos immediately', async () => {
  for (const change of [w => w.select({...selected(1), store_id: 2}), w => { w.evidencePermission = false; w.select(selected(1)); }]) {
    const w = browser({items: [row(1, {snapshot_url: '/api/v1/events/1/evidence.jpg'})]}); await flush();
    const image = w.images.find(image => image.src), url = image.src; image.onload();
    change(w); assert.equal(image.src, ''); assert.ok(w.revokedUrls.includes(url));
  }
});

test('missing/forbidden/non-image evidence stays empty and retries are bounded', async () => {
  for (const [status, message] of [[403, /Không có quyền/], [404, /chưa có ảnh đã lưu/]]) {
    const w = browser({photoError: {status}}); await flush(); const {image, empty} = panel(w);
    const detail = {camera: selected(1), metadata: {camera_id: 1, tracks: [{event_id: 8, recognized: true}]}};
    w.api.renderSelectedPhoto(detail); await flush(); assert.equal(image.src, ''); assert.match(empty.textContent, message);
    w.api.renderSelectedPhoto(detail); await flush(); assert.equal(w.photoRequests.length, 1);
    w.now += 6000; w.photoError = null;
    if (status === 403) { w.api.renderSelectedPhoto(detail); await flush(); assert.equal(w.photoRequests.length, 1); await w.api.refresh(true); }
    w.api.renderSelectedPhoto(detail); await flush(); assert.match(image.src, /^blob:/);
  }
  const w = browser({photoHold: true}); await flush(); const {image} = panel(w);
  w.select(selected(1), {camera_id: 1, tracks: [{event_id: 8, recognized: true}]}); await flush();
  w.pendingPhotos[0].resolve({blob: async () => ({size: 100, type: 'text/html'})}); await flush();
  assert.equal(image.src, ''); assert.equal(w.createdUrls.length, 0);
});

test('selected panel delegates evidence ownership without clearing a reused authenticated photo', async () => {
  let calls = 0;
  const context = {window: {BTMHRecentRecognition: {renderSelectedPhoto: () => calls++}}, state: {},
    $: () => null, hasUiPermission: () => false, setEntryBadge: () => {}, setRecognitionProgress: () => {}};
  vm.createContext(context); vm.runInContext(productFunction('renderRecognitionSlotSelection'), context);
  context.renderRecognitionSlotSelection({camera: {...selected(1), ai_state: 'DISABLED'}}); assert.equal(calls, 1);
});

test('detail uses its own dialog with recorded location, safe identity and keyboard focus, preserving live current result', async () => {
  const w = browser(); await flush(); const button = w.cards()[0].children[0]; button.focus(); button.dispatchEvent(new Event('click'));
  assert.match(w.roots.get('recentRecognitionDetailContent').textContent, /Hà Đông/);
  assert.equal(w.roots.get('profileName').textContent, 'Live selected-camera identity');
  assert.equal(w.document.activeElement, w.roots.get('recentRecognitionDetailClose'));
  const escape = new Event('keydown', {cancelable: true}); Object.defineProperty(escape, 'key', {value: 'Escape'}); w.roots.get('recentRecognitionDetail').dispatchEvent(escape);
  assert.equal(escape.defaultPrevented, true); assert.equal(w.roots.get('recentRecognitionDetail').hidden, true); assert.equal(w.document.activeElement, button);
});

test('empty/error/retry are explicit and late logout response cannot restore names', async () => {
  const w = browser({items: []}); await flush(); assert.match(w.host().textContent, /Chưa có nhận diện/);
  w.error = new Error('offline'); await w.api.refresh(); assert.match(w.host().textContent, /Không tải được/); assert.match(w.roots.get('recentRecognitionNote').textContent, /Tải lại/);
  w.error = null; w.items = [row()]; await w.api.refresh(); assert.equal(w.cards().length, 1);
  w.hold = true; void w.api.refresh(); await flush(); const pending = w.pending;
  w.authenticated = false; w.fire('btmh:auth', {authenticated: false}); assert.equal(pending.init.signal.aborted, true);
  pending.resolve({items: [row()]}); await flush(); assert.equal(w.cards().length, 0); assert.equal(w.timers.size, 0);
});

function productFunction(name) { const match = appSource.match(new RegExp(`(?:async )?function ${name}\\([^\\n]*\\)\\s*\\{[\\s\\S]*?\\n\\}`)); assert.ok(match); return match[0]; }
test('legacy history and latest-result renderer delegate or stop when scoped recognition owns the page', async () => {
  let refreshes = 0, legacyRequests = 0;
  const context = {state: {activePage: 'recognition'}, window: {BTMHRecentRecognition: {requestRefresh: () => {refreshes++;}}, BTMHRecognitionSlots: {}}, api: () => {legacyRequests++;}, console};
  vm.createContext(context); vm.runInContext(productFunction('loadRecognitionHistory') + '\n' + productFunction('renderLatestRecognition'), context);
  await context.loadRecognitionHistory(); context.renderLatestRecognition({full_name: 'Unscoped wrong result'});
  assert.equal(refreshes, 1); assert.equal(legacyRequests, 0);
});

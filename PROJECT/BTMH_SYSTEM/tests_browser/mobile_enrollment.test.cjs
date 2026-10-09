'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_mobile_enrollment.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../frontend/enroll.html'), 'utf8');
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
const secret = 'A'.repeat(43), prefix = '/api/v1/qr-enrollment/';
const initialTime = Date.parse('2026-10-08T03:00:00Z');
const row = (extra = {}) => ({id: 'a'.repeat(32), full_name: 'Nguyễn An', student_code: 'NV17', store_name: 'Cửa hàng thử', status: 'CAPTURING', consent_status: 'GRANTED', capture_allowed: true, can_consent: false, expires_at: new Date(initialTime + 1800000).toISOString(), ...extra});
const status = (extra = {}) => ({request: row(extra), session_expires_at: new Date(initialTime + 1800000).toISOString()});
const frame = (extra = {}) => ({capture_phase: 'CENTER', capture_phase_index: 0, guide: 'center', progress: .2, scan_pass: 1, capture_ready: false, ready_to_finalize: false, pad: {status: 'PASS'}, ...extra});
function browser(config = {}) {
  const w = {now: initialTime, requests: [], pending: [], timers: new Map(), nextTimer: 0, cameraCalls: [], cameraPending: [], streams: [], frames: [], binding: status(), ...config};
  const document = new EventTarget(); document.hidden = !!w.hidden;
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {}; this.className = ''; this.hidden = false; this.disabled = false; this.checked = false; this.value = ''; this._text = ''; }
    set textContent(value) { this.textWrites = (this.textWrites || 0) + 1; this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    get classList() { return {contains: value => this.className.split(/\s+/).includes(value), remove: value => this.classList.toggle(value, false), toggle: (value, on) => { const names = new Set(this.className.split(/\s+/).filter(Boolean)); if (on ?? !names.has(value)) names.add(value); else names.delete(value); this.className = [...names].join(' '); }}; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    removeAttribute(name) { delete this.attributes[name]; }
    pause() { this.pauses = (this.pauses || 0) + 1; }
    play() { return w.play ? w.play(this) : Promise.resolve(); }
  }
  const roots = new Map();
  for (const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)) { const element = new Element(match[1]); element.id = match[2]; element.hidden = /\bhidden\b/.test(match[0]); roots.set(element.id, element); }
  roots.get('mobileEnrollmentPhases').children = Array.from({length: 5}, () => new Element('li'));
  roots.get('mobileEnrollmentVideo').videoWidth = w.videoWidth ?? 1280; roots.get('mobileEnrollmentVideo').videoHeight = w.videoHeight ?? 720;
  const canvas = new Element('canvas'); canvas.getContext = () => ({drawImage: (...args) => { w.drawn = args; }}); canvas.toDataURL = () => w.image ?? 'data:image/jpeg;base64,/9j/AA==';
  document.getElementById = id => roots.get(id) || null; document.createElement = tag => tag === 'canvas' ? canvas : new Element(tag);
  const window = new EventTarget(); window.isSecureContext = w.secure !== false;
  const location = {protocol: w.protocol || 'https:', hash: w.hash ?? '#invite=' + secret, pathname: '/enroll', search: '', origin: 'https://enroll.test'};
  const history = {replaceState: (_, __, url) => { w.cleared = url; location.hash = ''; }};
  const makeStream = () => { const track = {stopped: 0, stop() { this.stopped++; }}, stream = {track, getTracks: () => [track]}; w.streams.push(stream); return stream; };
  const navigator = {mediaDevices: {getUserMedia: async options => { w.cameraCalls.push(options); if (w.holdCamera) return new Promise((resolve, reject) => w.cameraPending.push({resolve, reject})); if (w.cameraError) throw w.cameraError; return makeStream(); }}};
  const response = (data, code = 200) => ({ok: code >= 200 && code < 300, status: code, json: async () => data});
  const fetch = async (url, init) => {
    const request = {url, init, hash: location.hash}; w.requests.push(request);
    if (w.hold?.(url, init)) return new Promise((resolve, reject) => w.pending.push({...request, resolve: (data, code) => resolve(response(data, code)), reject}));
    const error = w.error?.(url, init); if (error) return response({detail: {code: 'SAFE_CODE'}}, error);
    if (url.endsWith('/status')) return response(w.binding);
    if (url.endsWith('/frame')) return response(w.frames.shift() || frame());
    if (url.endsWith('/consent')) { w.binding = status(); return response(w.binding); }
    if (url.endsWith('/submit')) { w.binding = {request: row({status: 'PENDING_REVIEW', capture_allowed: false})}; return response(w.submitResult || w.binding); }
    return response(w.binding);
  };
  class ClockDate extends Date { constructor(...args) { super(...(args.length ? args : [w.now])); } static now() { return w.now; } }
  const forbiddenStorage = {getItem() { throw new Error('Unexpected storage read'); }, setItem() { throw new Error('Unexpected secret storage'); }};
  const context = {document, window, location, history, navigator, fetch, URLSearchParams, AbortController, DOMException, Date: ClockDate, localStorage: forbiddenStorage, sessionStorage: forbiddenStorage, setTimeout: (callback, delay) => { const id = ++w.nextTimer; w.timers.set(id, {callback, at: w.now + delay}); return id; }, clearTimeout: id => w.timers.delete(id)};
  vm.createContext(context); vm.runInContext(source, context);
  Object.assign(w, {roots, document, window, location, canvas, makeStream});
  w.get = id => roots.get(id); w.click = id => w.get(id).dispatchEvent(new Event('click')); w.fire = (type, target = document) => target.dispatchEvent(new Event(type));
  w.advance = async ms => { w.now += ms; const due = [...w.timers.entries()].filter(([, timer]) => timer.at <= w.now).sort((a, b) => a[1].at - b[1].at); for (const [id, timer] of due) if (w.timers.delete(id)) timer.callback(); await flush(); };
  w.calls = action => w.requests.filter(request => request.url === prefix + action);
  return w;
}
async function scanning(config = {}) { const w = browser(config); await flush(); w.click('mobileEnrollmentStart'); await flush(); return w; }

test('consumes fragment before redeem and uses only narrow same-origin capability requests', async () => {
  const w = browser(); await flush(); assert.equal(w.cleared, '/enroll'); assert.equal(w.location.hash, ''); assert.deepEqual(w.requests.map(request => request.url), [prefix + 'redeem', prefix + 'status']); assert.deepEqual(JSON.parse(w.calls('redeem')[0].init.body), {invite_secret: secret}); assert.equal(w.requests.every(request => request.hash === '' && request.init.credentials === 'same-origin' && request.init.cache === 'no-store'), true); assert.equal(w.get('mobileEnrollmentName').textContent, 'Nguyễn An'); assert.equal(w.get('mobileEnrollmentSubmit').disabled, true);
});
test('insecure or malformed invitations never redeem or open a camera', async () => {
  for (const config of [{protocol: 'http:'}, {secure: false}, {hash: '#invite=bad'}]) { const w = browser(config); await flush(); w.click('mobileEnrollmentStart'); await flush(); assert.equal(w.requests.length, 0); assert.equal(w.cameraCalls.length, 0); assert.equal(w.location.hash, ''); assert.equal(w.get('mobileEnrollmentFeedback').classList.contains('error'), true); }
});
test('absent fragment restores only the existing cookie session without redeeming', async () => {
  const w = browser({hash: ''}); await flush(); assert.deepEqual(w.requests.map(request => request.url), [prefix + 'status']); assert.equal(w.get('mobileEnrollmentCapture').hidden, false);
});
test('redeem is one-flight and retry never resends the one-time secret', async () => {
  const w = browser({hold: url => url.endsWith('/redeem')}); await flush(); w.click('mobileEnrollmentRetry'); w.fire('pageshow', w.window); await flush(); assert.equal(w.calls('redeem').length, 1); assert.equal(w.calls('status').length, 0); w.pending[0].resolve({request: row()}); await flush(); assert.equal(w.calls('status').length, 1); w.click('mobileEnrollmentRetry'); await flush(); assert.equal(w.calls('redeem').length, 1);
});
test('capture guidance and PAD live regions change only with authoritative instructions', async () => {
  const w = browser({frames: [frame({guide: 'left', capture_phase: 'LEFT', capture_phase_index: 1}), frame({guide: 'left', capture_phase: 'LEFT', capture_phase_index: 1}), frame({guide: 'right', capture_phase: 'RIGHT', capture_phase_index: 2})]}); await flush(); w.click('mobileEnrollmentStart'); await flush(); await w.advance(350);
  const guidance = w.get('mobileEnrollmentGuidance'), pad = w.get('mobileEnrollmentPad'); assert.match(guidance.textContent, /trái/); const writes = guidance.textWrites, padWrites = pad.textWrites;
  await w.advance(350); assert.equal(guidance.textWrites, writes); assert.equal(pad.textWrites, padWrites); await w.advance(350); assert.match(guidance.textContent, /phải/); assert.equal(guidance.textWrites, writes + 1);
});

test('consent is explicit and sends granted only, followed by authoritative status', async () => {
  const w = browser({binding: status({consent_status: 'NOT_GRANTED', capture_allowed: false, can_consent: true})}); await flush(); w.click('mobileConsentButton'); await flush(); assert.equal(w.calls('consent').length, 0); w.get('mobileConsentCheck').checked = true; w.fire('change', w.get('mobileConsentCheck')); assert.equal(w.get('mobileConsentButton').disabled, false); w.click('mobileConsentButton'); w.click('mobileConsentButton'); await flush(); assert.equal(w.calls('consent').length, 1); assert.deepEqual(JSON.parse(w.calls('consent')[0].init.body), {granted: true}); assert.equal(w.get('mobileEnrollmentConsent').hidden, true); assert.equal(w.get('mobileEnrollmentStart').disabled, false);
});
test('withdrawn consent cannot be regranted and no capture begins', async () => {
  const w = browser({binding: status({consent_status: 'WITHDRAWN', capture_allowed: false, can_consent: false})}); await flush(); w.get('mobileConsentCheck').checked = true; w.click('mobileConsentButton'); w.click('mobileEnrollmentStart'); await flush(); assert.equal(w.calls('consent').length, 0); assert.equal(w.cameraCalls.length, 0); assert.match(w.get('mobileEnrollmentFeedback').textContent, /rút lại/);
});
test('uploads scaled JPEG only, one frame in flight and resumes latest frame after completion', async () => {
  const w = await scanning({hold: url => url.endsWith('/frame')}); await w.advance(350); await w.advance(350); w.click('mobileEnrollmentStart'); await flush(); assert.equal(w.calls('frame').length, 1); assert.equal(w.cameraCalls.length, 1); assert.equal(w.canvas.width, 960); assert.equal(w.canvas.height, 540); assert.deepEqual(JSON.parse(w.calls('frame')[0].init.body), {image: 'data:image/jpeg;base64,/9j/AA=='}); w.pending[0].resolve(frame({capture_phase: 'LEFT', capture_phase_index: 1, guide: 'left'})); await flush(); assert.match(w.get('mobileEnrollmentGuidance').textContent, /sang trái/); await w.advance(350); assert.equal(w.calls('frame').length, 2);
});
test('two completed passes plus current server PAD PASS are all required to enable submission', async () => {
  const bad = [frame({capture_ready: true, ready_to_finalize: true, scan_pass: 1}), frame({capture_ready: true, ready_to_finalize: false, scan_pass: 2}), frame({capture_ready: false, ready_to_finalize: true, scan_pass: 2}), frame({capture_ready: true, ready_to_finalize: true, scan_pass: 2, pad: {status: 'CHECKING'}})];
  const w = await scanning({frames: [...bad, frame({capture_ready: true, ready_to_finalize: true, scan_pass: 2, capture_phase_index: 4})]}); for (const ignored of bad) { await w.advance(350); assert.equal(w.get('mobileEnrollmentSubmit').disabled, true); w.click('mobileEnrollmentSubmit'); await flush(); assert.equal(w.calls('submit').length, 0); } await w.advance(350); assert.equal(w.get('mobileEnrollmentSubmit').disabled, false); assert.match(w.get('mobileEnrollmentProgressLabel').textContent, /Vòng 2\/2/); assert.equal(w.get('mobileEnrollmentPhases').children[4].attributes['aria-current'], 'step');
});
test('PAD unavailable/blocked stops tracks and refuses finalization', async () => {
  for (const padStatus of ['MODEL_UNAVAILABLE', 'BLOCKED']) { const w = await scanning({frames: [frame({scan_pass: 2, capture_ready: true, ready_to_finalize: true, pad: {status: padStatus}})]}); await w.advance(350); assert.equal(w.streams[0].track.stopped, 1); assert.equal(w.get('mobileEnrollmentVideo').srcObject, null); assert.equal(w.get('mobileEnrollmentSubmit').disabled, true); w.click('mobileEnrollmentSubmit'); await flush(); assert.equal(w.calls('submit').length, 0); }
});
test('submit stops camera, uses empty body and reports PENDING without claiming activation', async () => {
  const w = await scanning({frames: [frame({scan_pass: 2, capture_ready: true, ready_to_finalize: true})], hold: url => url.endsWith('/submit')}); await w.advance(350); w.click('mobileEnrollmentSubmit'); w.click('mobileEnrollmentSubmit'); await flush(); assert.equal(w.streams[0].track.stopped, 1); assert.equal(w.calls('submit').length, 1); assert.deepEqual(JSON.parse(w.calls('submit')[0].init.body), {}); w.pending[0].resolve({request: row({status: 'PENDING_REVIEW', capture_allowed: false})}); await flush(); assert.equal(w.get('mobileEnrollmentCapture').hidden, true); assert.match(w.get('mobileEnrollmentResultTitle').textContent, /chờ duyệt/); assert.match(w.get('mobileEnrollmentResultText').textContent, /chưa kích hoạt FaceID/); assert.equal(w.requests.some(request => /approve|activate|admin|students|cameras/.test(request.url)), false);
});
test('non-pending submit result cannot become a success claim', async () => {
  const w = await scanning({frames: [frame({scan_pass: 2, capture_ready: true, ready_to_finalize: true})], submitResult: {request: row({status: 'APPROVED'})}}); await w.advance(350); w.click('mobileEnrollmentSubmit'); await flush(); assert.equal(w.get('mobileEnrollmentResult').hidden, true); assert.equal(w.get('mobileEnrollmentFeedback').classList.contains('error'), true);
});
test('reset stops camera, sends empty body and clears stale readiness before reopening', async () => {
  const w = await scanning({frames: [frame({scan_pass: 2, capture_ready: true, ready_to_finalize: true})]}); await w.advance(350); w.click('mobileEnrollmentReset'); w.click('mobileEnrollmentReset'); await flush(); assert.equal(w.streams[0].track.stopped, 1); assert.equal(w.calls('reset').length, 1); assert.deepEqual(JSON.parse(w.calls('reset')[0].init.body), {}); assert.equal(w.get('mobileEnrollmentProgress').value, 0); assert.equal(w.get('mobileEnrollmentSubmit').disabled, true); assert.equal(w.get('mobileEnrollmentStart').disabled, false);
});
test('hidden/pagehide aborts an upload and ignores late guidance; foreground never starts camera automatically', async () => {
  const w = await scanning({hold: url => url.endsWith('/frame')}); await w.advance(350); const old = w.pending[0]; w.document.hidden = true; w.fire('visibilitychange'); assert.equal(old.init.signal.aborted, true); assert.equal(w.streams[0].track.stopped, 1); assert.equal(w.get('mobileEnrollmentIdentity').hidden, true); old.resolve(frame({scan_pass: 2, capture_ready: true, ready_to_finalize: true, message: 'Stale guidance'})); await flush(); assert.equal(w.get('mobileEnrollmentSubmit').disabled, true); assert.equal(w.get('mobileEnrollmentHint').textContent.includes('Stale'), false); w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.cameraCalls.length, 1); assert.equal(w.get('mobileEnrollmentIdentity').hidden, false); w.fire('pagehide', w.window); w.click('mobileEnrollmentRetry'); await flush(); const count = w.requests.length; await w.advance(10000); assert.equal(w.requests.length, count);
});
test('late camera permission and late play completion release every acquired track after leaving', async () => {
  const w = await scanning({holdCamera: true}); w.document.hidden = true; w.fire('visibilitychange'); const opened = w.makeStream(); w.cameraPending[0].resolve(opened); await flush(); assert.equal(opened.track.stopped, 1); assert.equal(w.get('mobileEnrollmentVideo').srcObject, null);
  let resolvePlay; const p = await scanning({play: () => new Promise(resolve => { resolvePlay = resolve; })}); p.fire('pagehide', p.window); resolvePlay(); await flush(); assert.ok(p.streams[0].track.stopped >= 1); assert.equal(p.get('mobileEnrollmentVideo').srcObject, null); assert.equal(p.calls('frame').length, 0);
});
test('session expiry stops camera and disables consent and capture; malformed expiry fails closed', async () => {
  const w = await scanning({binding: {...status(), session_expires_at: new Date(initialTime + 1000).toISOString()}}); await w.advance(1000); assert.equal(w.streams[0].track.stopped, 1); assert.equal(w.get('mobileEnrollmentStart').disabled, true); assert.match(w.get('mobileEnrollmentFeedback').textContent, /hết hạn/);
  const c = browser({binding: status({can_consent: true, capture_allowed: false, consent_status: 'NOT_GRANTED', expires_at: new Date(initialTime + 500).toISOString()})}); await flush(); c.get('mobileConsentCheck').checked = true; c.fire('change', c.get('mobileConsentCheck')); await c.advance(500); c.click('mobileConsentButton'); await flush(); assert.equal(c.get('mobileConsentButton').disabled, true); assert.equal(c.calls('consent').length, 0);
  const m = browser({binding: {request: row({expires_at: 'bad'})}}); await flush(); m.click('mobileEnrollmentStart'); await flush(); assert.equal(m.cameraCalls.length, 0);
});
test('network timeout/forbidden/expiry expose safe retry states and never server details', async () => {
  for (const code of [403, 410, 429, 503]) { const w = browser({hash: '', error: () => code}); await flush(); assert.equal(w.get('mobileEnrollmentIdentity').hidden, true); assert.equal(w.get('mobileEnrollmentRetry').hidden, false); assert.equal(w.get('mobileEnrollmentFeedback').classList.contains('error'), true); assert.equal(w.get('mobileEnrollmentFeedback').textContent.includes('SAFE_CODE'), false); }
  const w = browser({hash: '', hold: () => true}); await flush(); await w.advance(8000); assert.equal(w.pending[0].init.signal.aborted, true); w.pending[0].reject(new DOMException('aborted', 'AbortError')); await flush(); assert.equal(w.get('mobileEnrollmentRetry').hidden, false);
});
test('camera refusal and oversized/invalid uploads fail safely without publishing', async () => {
  const w = await scanning({cameraError: {name: 'NotAllowedError'}}); assert.match(w.get('mobileEnrollmentFeedback').textContent, /chưa được cho phép/); assert.equal(w.calls('frame').length, 0);
  for (const image of ['x'.repeat(2796248), 'data:image/png;base64,AA==']) { const p = await scanning({image}); await p.advance(350); assert.equal(p.calls('frame').length, 0); assert.equal(p.streams[0].track.stopped, 1); assert.equal(p.get('mobileEnrollmentFeedback').classList.contains('error'), true); }
});
test('identity/guidance redact network addresses and terminal states offer no capture authority', async () => {
  for (const state of ['PENDING_REVIEW', 'NEEDS_DUPLICATE_REVIEW', 'APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED']) { const w = browser({binding: status({status: state, full_name: 'rtsp://secret.invalid', store_name: '192.168.1.10', capture_allowed: false})}); await flush(); w.click('mobileEnrollmentStart'); await flush(); assert.equal(w.cameraCalls.length, 0); assert.equal(w.get('mobileEnrollmentCapture').hidden, true); assert.equal(/rtsp|192\.168/.test(w.get('mobileEnrollmentName').textContent + w.get('mobileEnrollmentStore').textContent), false); }
});
test('a status refresh during capture does not lose the scheduled upload loop', async () => {
  const w = await scanning({hold: url => url.endsWith('/status')});
  // Boot status was held, so bind it before exercising a deliberate refresh.
  w.hold = null; w.pending[0].resolve(status()); await flush(); w.click('mobileEnrollmentStart'); await flush();
  w.hold = url => url.endsWith('/status'); w.click('mobileEnrollmentRetry'); await flush(); const refresh = w.pending.at(-1); await w.advance(350); assert.equal(w.calls('frame').length, 0); refresh.resolve(status()); await flush(); await w.advance(350); assert.equal(w.calls('frame').length, 1); assert.equal(w.streams[0].track.stopped, 0);
});
test('a stale ordinary network failure cannot erase a newer foreground binding', async () => {
  const w = browser({hash: '', hold: url => url.endsWith('/status')}); await flush(); const old = w.pending[0]; w.document.hidden = true; w.fire('visibilitychange'); w.hold = null; w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.get('mobileEnrollmentName').textContent, 'Nguyễn An'); old.reject(new Error('late offline')); await flush(); assert.equal(w.get('mobileEnrollmentIdentity').hidden, false); assert.equal(w.get('mobileEnrollmentName').textContent, 'Nguyễn An'); assert.equal(w.get('mobileEnrollmentFeedback').classList.contains('error'), false);
});
test('confirmed submission retains an honest memory receipt when capture authority later ends', async () => {
  const w = await scanning({frames: [frame({scan_pass: 2, capture_ready: true, ready_to_finalize: true})], submitResult: {request: row({status: 'PENDING_REVIEW', capture_allowed: false, expires_at: new Date(initialTime + 72 * 3600000).toISOString()})}}); await w.advance(350); w.click('mobileEnrollmentSubmit'); await flush(); assert.match(w.get('mobileEnrollmentExpiry').textContent, /Thời hạn xem xét mẫu/); assert.equal(w.get('mobileEnrollmentExpiry').textContent.includes('Phiên có hiệu lực'), false); w.document.hidden = true; w.fire('visibilitychange'); w.error = url => url.endsWith('/status') ? 410 : null; w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.get('mobileEnrollmentResultTitle').textContent, 'Đã gửi mẫu để duyệt'); assert.match(w.get('mobileEnrollmentResultText').textContent, /chưa xác nhận quyết định duyệt/); assert.equal(w.get('mobileEnrollmentCapture').hidden, true); assert.equal(w.get('mobileEnrollmentFeedback').textContent.includes('lời mời mới'), false); assert.equal(w.calls('submit').length, 1); assert.equal(w.calls('redeem').length, 1);
});

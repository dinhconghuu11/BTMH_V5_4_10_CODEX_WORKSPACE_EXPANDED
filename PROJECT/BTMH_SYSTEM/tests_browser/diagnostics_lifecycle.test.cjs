'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_diagnostics_v550.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };

function browser(options = {}) {
  const w = {now: 0, next: 0, timers: new Map(), requests: [], allowed: true, active: true, holdFetch: false, holdBody: false, payload: {}, stats: {}, ...options};
  w.later = (fn, ms) => { const id = ++w.next; w.timers.set(id, {fn, at: w.now + ms}); return id; };
  w.advance = async ms => {
    const target = w.now + ms;
    while (true) {
      const next = [...w.timers].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      const [id, timer] = next; w.now = timer.at; w.timers.delete(id); timer.fn(); await flush();
    }
    w.now = target; await flush();
  };
  class Element extends EventTarget {
    constructor() { super(); this.children = []; this._text = ''; this.open = false; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; this._text = ''; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    set innerHTML(_) { assert.fail('diagnostics must never render HTML'); }
  }
  w.details = new Element(); w.metrics = new Element(); w.status = new Element();
  const document = new EventTarget(); document.hidden = !!w.hidden; document.readyState = w.loading ? 'loading' : 'complete';
  document.createElement = () => new Element();
  document.querySelector = selector => ({'#btmhPerformanceDetails': w.missingDom ? null : w.details, '#btmhPerformanceMetrics': w.metrics,
    '#btmhPerformanceStatus': w.status, '#page-system.active': w.active ? new Element() : null})[selector] || null;
  const window = new EventTarget(); window.BTMHMedia = {stats: () => w.stats};
  const fetch = (url, init) => {
    const request = {url, init}; w.requests.push(request);
    const response = () => ({ok: !w.httpStatus || w.httpStatus < 400, status: w.httpStatus || 200,
      json: () => w.holdBody ? new Promise(resolve => { request.finishBody = data => { request.completed = true; resolve(data); }; }) : (request.completed = true, Promise.resolve(w.payload))});
    if (w.rejectFetch) return Promise.reject(new Error(w.rejectFetch));
    if (!w.holdFetch) return Promise.resolve(response());
    return new Promise((resolve, reject) => {
      request.finishFetch = data => resolve(data === undefined ? response() : {ok: true, status: 200, json: async () => data});
      if (!w.ignoreAbort) init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true});
    });
  };
  const context = {window, document, Event, DOMException, AbortController, localStorage: {getItem: () => 'test-session-token'}, fetch,
    hasUiPermission: permission => { assert.equal(permission, 'system.diagnostics'); return w.allowed; },
    setTimeout: w.later, clearTimeout: id => w.timers.delete(id)};
  w.run = () => vm.runInNewContext(source, context, {filename: 'btmh_diagnostics_v550.js'});
  w.run(); w.document = document; w.window = window;
  w.event = (type, detail, target = document) => { const event = new Event(type); event.detail = detail; target.dispatchEvent(event); };
  w.auth = authenticated => w.event('btmh:auth', {authenticated});
  w.open = value => { w.details.open = value; w.event('toggle', undefined, w.details); };
  w.navigate = active => { w.active = active; w.event('btmh:navigate', {page: active ? 'system' : 'dashboard'}); };
  w.visibility = hidden => { document.hidden = hidden; w.event('visibilitychange'); };
  w.row = label => w.metrics.children.flatMap(group => group.children[1]?.children || []).find(row => row.children[0].textContent === label)?.children[1].textContent;
  w.start = async () => { w.auth(true); w.open(true); await flush(); };
  return w;
}

test('details stay collapsed and issue no request before an authorized open', async () => {
  const w = browser(); assert.equal(w.details.open, false);
  w.auth(true); await w.advance(30000); assert.equal(w.requests.length, 0);
  w.open(true); await flush(); assert.equal(w.requests.length, 1);
  assert.equal(w.requests[0].url, '/api/v1/system/diagnostics/performance');
  assert.equal(w.requests[0].init.credentials, 'same-origin');
  assert.equal(w.requests[0].init.cache, 'no-store');
  assert.equal(w.requests[0].init.headers.Authorization, 'Bearer test-session-token');
});

for (const [name, options, authenticated] of [
  ['signed out', {}, false], ['wrong permission', {allowed: false}, true], ['another page', {active: false}, true], ['hidden document', {hidden: true}, true],
]) test(`no polling while ${name}`, async () => {
  const w = browser(options); w.auth(authenticated); w.open(true); await w.advance(30000);
  assert.equal(w.requests.length, 0); assert.equal(w.timers.size, 0);
});

test('polling schedules ten seconds after completion and never overlaps a request', async () => {
  const w = browser({holdFetch: true}); await w.start();
  await w.advance(7000); assert.equal(w.requests.length, 1);
  w.requests[0].finishFetch(); await flush();
  await w.advance(9999); assert.equal(w.requests.length, 1);
  await w.advance(1); assert.equal(w.requests.length, 2);
  assert.equal(w.requests.filter(request => !request.completed && !request.init.signal.aborted).length, 1);
  w.open(false); await flush(); assert.equal(w.timers.size, 0);
});

test('duplicate toggle events and script initialization keep one request and one timer', async () => {
  const w = browser({holdFetch: true}); await w.start();
  w.run(); for (let i = 0; i < 10; i++) w.open(true);
  await flush(); assert.equal(w.requests.length, 1); assert.equal(w.timers.size, 1);
  w.requests[0].finishFetch(); await flush(); assert.equal(w.timers.size, 1);
  w.open(false); await flush(); assert.equal(w.timers.size, 0);
});

test('closing aborts request and rejects a late response without retaining data', async () => {
  const w = browser({holdFetch: true, ignoreAbort: true}); await w.start();
  const old = w.requests[0]; w.open(false); await flush();
  assert.equal(old.init.signal.aborted, true); assert.equal(w.timers.size, 0);
  old.finishFetch({camera: {capture_fps: 999}}); await flush();
  assert.equal(w.metrics.children.length, 0); await w.advance(30000); assert.equal(w.requests.length, 1);
});

test('rapid close/reopen creates one new owner and ignores the preceding response', async () => {
  const w = browser({holdFetch: true, ignoreAbort: true}); await w.start();
  w.open(false); w.open(true); await flush(); assert.equal(w.requests.length, 2);
  assert.equal(w.requests.filter(request => !request.init.signal.aborted).length, 1);
  w.requests[1].finishFetch({camera: {capture_fps: 25}}); await flush();
  w.requests[0].finishFetch({camera: {capture_fps: 999}}); await flush();
  assert.equal(w.row('FPS capture'), '25 FPS'); assert.equal(w.timers.size, 1);
});

for (const [name, stop] of [
  ['navigation', w => w.navigate(false)], ['tab hiding', w => w.visibility(true)], ['logout', w => w.auth(false)],
  ['pagehide', w => w.event('pagehide', undefined, w.window)],
]) test(`${name} aborts request, clears metrics and cancels the polling timer`, async () => {
  const w = browser({holdFetch: true, ignoreAbort: true}); await w.start(); stop(w); await flush();
  assert.equal(w.requests[0].init.signal.aborted, true); assert.equal(w.timers.size, 0);
  w.requests[0].finishFetch({camera: {capture_fps: 99}}); await w.advance(30000);
  assert.equal(w.requests.length, 1); assert.equal(w.metrics.children.length, 0);
});

for (const [name, stop, resume] of [
  ['navigation', w => w.navigate(false), w => w.navigate(true)], ['visibility', w => w.visibility(true), w => w.visibility(false)],
  ['authentication', w => w.auth(false), w => w.auth(true)], ['pageshow', w => w.event('pagehide', undefined, w.window), w => w.event('pageshow', undefined, w.window)],
]) test(`${name} resumes with one fresh request after cleanup`, async () => {
  const w = browser(); await w.start(); stop(w); await flush(); resume(w); await flush();
  assert.equal(w.requests.length, 2); assert.equal(w.timers.size, 1);
});

for (const part of ['fetch', 'body']) test(`eight-second deadline bounds a stalled ${part}`, async () => {
  const w = browser({holdFetch: part === 'fetch', holdBody: part === 'body', ignoreAbort: true}); await w.start();
  await w.advance(7999); assert.equal(w.requests[0].init.signal.aborted, false);
  await w.advance(1); assert.equal(w.requests[0].init.signal.aborted, true);
  assert.match(w.status.textContent, /quá hạn/); assert.equal(w.timers.size, 1);
  await w.advance(9999); assert.equal(w.requests.length, 1);
  await w.advance(1); assert.equal(w.requests.length, 2);
  w.open(false); await flush(); assert.equal(w.timers.size, 0);
});

test('rendering accepts numbers and known enums only, keeping zero distinct from unknown', async () => {
  const secret = 'rtsp://private-user:private-password@camera.example.test/stream';
  const w = browser({payload: {camera: {state: secret, capture_fps: null, preview_fps: 0, actual_width: secret, reconnect_count: -1},
    ai: {load_state: '<img onerror=alert(1)>', detector_ms: null, tracker_ms: secret, p95_ms: Infinity, faceid: {last_ms: 0}},
    resources: {cpu_percent: secret, ram_percent: 101, gpu_mode: 'GPU_ASSISTED', gpu_utilization_percent: null},
    source: secret, detail: '<script>alert(1)</script>'}});
  await w.start();
  assert.equal(w.row('FPS capture'), 'Chưa đo'); assert.equal(w.row('FPS preview'), '0 FPS');
  assert.equal(w.row('Chiều rộng nguồn'), 'Chưa đo'); assert.equal(w.row('Camera kết nối lại'), 'Chưa đo');
  assert.equal(w.row('Camera'), 'Chưa đo'); assert.equal(w.row('Tải AI'), 'Chưa đo');
  assert.equal(w.row('FaceID xử lý'), '0 ms'); assert.equal(w.row('CPU'), 'Chưa đo'); assert.equal(w.row('RAM'), 'Chưa đo');
  assert.equal(w.row('Chế độ GPU'), 'GPU hỗ trợ');
  assert.doesNotMatch(w.metrics.textContent + w.status.textContent, /private|rtsp|<img|<script/);
});

test('browser aggregates numeric FPS while network latency remains explicitly unmeasured', async () => {
  const w = browser({stats: {first: {renderedFps: 20, receivedFps: 22, decodedFps: null, videoLatencyMs: 55},
    second: {renderedFps: 10, receivedFps: null, decodedFps: 19}, poisoned: {renderedFps: 'password-secret', receivedFps: Infinity, decodedFps: -3, source: 'private-secret'}}});
  await w.start();
  assert.equal(w.row('Views đang mở trong trình duyệt'), '3');
  assert.equal(w.row('FPS hiển thị trung bình'), '15 FPS'); assert.equal(w.row('FPS nhận trung bình'), '22 FPS');
  assert.equal(w.row('FPS giải mã trung bình'), '19 FPS'); assert.equal(w.row('Độ trễ mạng trình duyệt'), 'Chưa đo');
  assert.doesNotMatch(w.metrics.textContent, /secret|55 ms/);
});

test('absent media API yields unknown measurements and does not start media work', async () => {
  const w = browser(); delete w.window.BTMHMedia; await w.start();
  assert.equal(w.row('Views đang mở trong trình duyệt'), 'Chưa đo'); assert.equal(w.row('FPS hiển thị trung bình'), 'Chưa đo');
});

test('fetch failures use a fixed message and never display raw error details', async () => {
  const w = browser({rejectFetch: 'rtsp://private:secret@camera.example.test/stream <script>evil</script>'}); await w.start();
  assert.match(w.status.textContent, /Chưa tải được/); assert.doesNotMatch(w.status.textContent, /private|secret|script|rtsp/);
  assert.equal(w.metrics.children.length, 0); assert.equal(w.timers.size, 1);
});

for (const httpStatus of [401, 403]) test(`HTTP ${httpStatus} stops polling until authentication is refreshed`, async () => {
  const w = browser({httpStatus, payload: {detail: 'password-secret'}}); await w.start();
  assert.match(w.status.textContent, /không có quyền/); assert.equal(w.timers.size, 0);
  await w.advance(30000); w.open(true); await flush(); assert.equal(w.requests.length, 1);
  w.httpStatus = 200; w.auth(true); await flush(); assert.equal(w.requests.length, 2); assert.equal(w.timers.size, 1);
});

test('permission change revokes a pending request and drops the prior authorized result', async () => {
  const w = browser({holdFetch: true, ignoreAbort: true}); await w.start();
  w.allowed = false; w.auth(true); await flush();
  assert.equal(w.requests[0].init.signal.aborted, true);
  w.requests[0].finishFetch({camera: {capture_fps: 25}}); await flush();
  assert.equal(w.metrics.children.length, 0); assert.equal(w.timers.size, 0);
});

test('DOM-ready initialization is idempotent and missing technical markup is harmless', async () => {
  const w = browser({loading: true}); w.auth(true); w.open(true); await flush(); assert.equal(w.requests.length, 0);
  w.event('DOMContentLoaded'); w.event('DOMContentLoaded'); await flush(); assert.equal(w.requests.length, 1);
  const missing = browser({missingDom: true}); await missing.start(); assert.equal(missing.requests.length, 0);
});

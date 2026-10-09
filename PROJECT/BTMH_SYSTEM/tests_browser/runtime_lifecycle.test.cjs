const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_runtime_v543.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const outcome = promise => promise.then(value => ({value}), error => ({error}));

function environment() {
  let now = 0, timerId = 0, urlId = 0;
  const timers = new Map(), requests = [], controllers = [], created = [], revoked = [], liveUrls = new Set();
  class OwnedController extends AbortController {
    constructor() {
      super(); controllers.push(this);
      const listeners = new Set(), add = this.signal.addEventListener.bind(this.signal), remove = this.signal.removeEventListener.bind(this.signal);
      this.signal.listenerCount = () => listeners.size;
      this.signal.addEventListener = (name, listener, options) => {
        if (name === 'abort') listeners.add(listener); add(name, listener, options);
      };
      this.signal.removeEventListener = (name, listener, options) => {
        if (name === 'abort') listeners.delete(listener); remove(name, listener, options);
      };
    }
  }
  const schedule = (fn, delay, repeat) => {
    const id = ++timerId; timers.set(id, {fn, at: now + Number(delay), repeat}); return id;
  };
  const window = new EventTarget(), document = new EventTarget();
  document.hidden = false; document.authVisible = false;
  document.querySelector = selector => selector === '#authGate:not(.hidden)' && document.authVisible ? {} : null;
  document.createElement = () => ({hidden: false, setAttribute() {}});
  const fetch = (url, init) => {
    const pending = deferred(); requests.push({url, init, ...pending}); return pending.promise;
  };
  const context = {window, document, fetch, AbortController: OwnedController, DOMException, Response,
    performance: {now: () => now}, Date: class extends Date { static now() { return now; } },
    setTimeout: (fn, delay) => schedule(fn, delay, 0), clearTimeout: id => timers.delete(id),
    setInterval: (fn, delay) => schedule(fn, delay, Number(delay)), clearInterval: id => timers.delete(id),
    URL: {createObjectURL(blob) { const url = `blob:test-${++urlId}`; created.push({url, blob}); liveUrls.add(url); return url; },
      revokeObjectURL(url) { revoked.push(url); liveUrls.delete(url); }},
  };
  vm.runInNewContext(source, context);
  const image = () => {
    const page = {active: true, classList: {contains: name => name === 'active' && page.active}};
    const wrap = {badge: null, querySelector() { return this.badge; }, append(badge) { this.badge = badge; }};
    const img = {dataset: {}, parentElement: wrap, page, isConnected: true, hidden: false, writes: [],
      closest: selector => selector === '.page' ? page : selector === '.hidden' && img.hidden ? {} : null,
      removeAttribute(name) { if (name === 'src') this._src = undefined; },
      set src(value) { this.writes.push(value); this._src = value; }, get src() { return this._src; }};
    return img;
  };
  const advance = async elapsed => {
    const end = now + elapsed;
    await flush();
    while (true) {
      let nextId, next;
      for (const [id, task] of timers) if (task.at <= end && (!next || task.at < next.at)) { nextId = id; next = task; }
      if (!next) break;
      now = next.at;
      if (next.repeat) next.at += next.repeat; else timers.delete(nextId);
      next.fn(); await flush();
    }
    now = end; await flush();
  };
  const reply = ({body = {}, buffer, blob, status = 200, seq = '1', age = '0', type = 'image/jpeg'} = {}) => {
    const response = {body, status, statusText: 'OK', ok: status >= 200 && status < 300,
      headers: new Headers({'X-Camera-Seq': seq, 'X-Frame-Age-Ms': age}),
      arrayBuffer: () => buffer ? buffer.promise : Promise.resolve(new TextEncoder().encode('{}').buffer),
      blob: () => blob ? blob.promise : Promise.resolve(new Blob(['frame'], {type}))};
    response.cancellations = 0;
    if (body) body.cancel = () => { response.cancellations++; return Promise.resolve(); };
    return response;
  };
  return {runtime: window.BTMHRuntime, window, document, timers, requests, controllers, created, revoked, liveUrls,
    Controller: OwnedController, image, advance, reply,
    noListeners() { assert.ok(controllers.every(controller => controller.signal.listenerCount() === 0)); }};
}

test('idle runtime allocates no timers, requests or owners', () => {
  const w = environment(); assert.equal(w.timers.size, 0); assert.equal(w.requests.length, 0);
  assert.equal(w.runtime.stats().jobs, 0); assert.equal(w.runtime.stats().previews, 0);
});

test('hidden, inactive, detached and auth-gated preview mounts allocate no work', async () => {
  for (const scope of ['hidden', 'page', 'detached', 'auth']) {
    const w = environment(), img = w.image();
    if (scope === 'hidden') w.document.hidden = true;
    if (scope === 'page') img.page.active = false;
    if (scope === 'detached') img.isConnected = false;
    if (scope === 'auth') w.document.authVisible = true;
    w.runtime.preview(img, '/preview'); await flush();
    assert.equal(w.requests.length, 0); assert.equal(w.timers.size, 0); assert.equal(w.runtime.stats().previews, 0);
    assert.equal(img.parentElement.badge, null); assert.equal(img.dataset.started, undefined);
  }
});

test('pagehide blocks new mounts even when document remains visible; pageshow waits for explicit mount', async () => {
  const w = environment(), img = w.image(); w.runtime.preview(img, '/preview'); await flush();
  assert.equal(w.document.hidden, false); w.window.dispatchEvent(new Event('pagehide')); await flush();
  w.runtime.preview(img, '/preview'); await flush(); assert.equal(w.requests.length, 1); assert.equal(w.timers.size, 0);
  assert.equal(w.runtime.stats().previews, 0); assert.equal(w.runtime.stats().inFlight, 0);
  w.window.dispatchEvent(new Event('pageshow')); await w.advance(10000);
  assert.equal(w.requests.length, 1); assert.equal(w.timers.size, 0);
  w.runtime.preview(img, '/preview'); await flush(); assert.equal(w.requests.length, 2);
  w.runtime.stopAll(); await flush(); assert.equal(w.timers.size, 0); w.noListeners();
});

test('request preserves status, headers and body and releases its deadline', async () => {
  const w = environment(), pending = w.runtime.request('/api/test'); await flush();
  w.requests[0].resolve(new Response('{"ready":true}', {status: 202, statusText: 'Accepted', headers: {'Cache-Control': 'no-store'}}));
  const response = await pending;
  assert.equal(response.status, 202); assert.equal(response.statusText, 'Accepted');
  assert.equal(response.headers.get('Cache-Control'), 'no-store'); assert.deepEqual(await response.json(), {ready: true});
  assert.equal(w.timers.size, 0); w.noListeners();
});

test('bodyless responses keep their original identity', async () => {
  const w = environment(), response = new Response(null, {status: 204}), pending = w.runtime.request('/api/test');
  await flush(); w.requests[0].resolve(response); assert.equal(await pending, response);
  assert.equal(w.timers.size, 0); w.noListeners();
});

test('request timeout rejects even when native fetch ignores abort and cancels late headers', async () => {
  const w = environment(), result = outcome(w.runtime.request('/api/test', {timeoutMs: 100})); await flush();
  await w.advance(100); assert.equal((await result).error.name, 'AbortError');
  assert.equal(w.timers.size, 0); assert.equal(w.requests[0].init.signal.aborted, true); w.noListeners();
  const response = w.reply(); w.requests[0].resolve(response); await flush();
  assert.equal(response.cancellations, 1); assert.equal(w.timers.size, 0);
});

test('request deadline includes a body that ignores abort', async () => {
  const w = environment(), body = deferred(), result = outcome(w.runtime.request('/api/test', {timeoutMs: 100}));
  await flush(); await w.advance(60); const response = w.reply({buffer: body}); w.requests[0].resolve(response); await flush();
  let finished = false; result.then(() => { finished = true; });
  await w.advance(39); assert.equal(finished, false);
  await w.advance(1); assert.equal((await result).error.name, 'AbortError');
  assert.equal(response.cancellations, 1); assert.equal(w.timers.size, 0); w.noListeners();
  body.resolve(new ArrayBuffer(0)); await flush(); assert.equal(w.timers.size, 0);
});

for (const phase of ['headers', 'body']) test(`caller abort retires a request waiting for ${phase}`, async () => {
  const w = environment(), caller = new w.Controller(), body = deferred();
  const result = outcome(w.runtime.request('/api/test', {signal: caller.signal, timeoutMs: 1000})); await flush();
  const response = w.reply({buffer: body});
  if (phase === 'body') { w.requests[0].resolve(response); await flush(); }
  caller.abort(); await flush(); assert.equal((await result).error.name, 'AbortError');
  assert.equal(w.timers.size, 0); w.noListeners();
  if (phase === 'headers') w.requests[0].resolve(response); else body.resolve(new ArrayBuffer(0));
  await flush(); assert.equal(response.cancellations, 1); assert.equal(w.timers.size, 0);
});

test('pre-aborted request never starts native fetch or a deadline', async () => {
  const w = environment(), caller = new w.Controller(); caller.abort();
  assert.equal((await outcome(w.runtime.request('/api/test', {signal: caller.signal}))).error.name, 'AbortError');
  assert.equal(w.requests.length, 0); assert.equal(w.timers.size, 0); w.noListeners();
});

test('native fetch and body rejection release listeners and timeout', async () => {
  for (const phase of ['headers', 'body']) {
    const w = environment(), caller = new w.Controller(), body = deferred();
    const result = outcome(w.runtime.request('/api/test', {signal: caller.signal})); await flush();
    const error = new Error('network failed');
    if (phase === 'headers') w.requests[0].reject(error);
    else { w.requests[0].resolve(w.reply({buffer: body})); await flush(); body.reject(error); }
    assert.equal((await result).error, error); assert.equal(w.timers.size, 0); w.noListeners();
  }
});

test('non-finite timeout falls back to the finite default', async () => {
  const w = environment(), result = outcome(w.runtime.request('/api/test', {timeoutMs: Infinity})); await flush();
  await w.advance(15000); assert.equal((await result).error.name, 'AbortError'); assert.equal(w.timers.size, 0); w.noListeners();
});

test('single-flight shares one promise and has no idle timer', async () => {
  const w = environment(), work = deferred(); let calls = 0;
  const first = w.runtime.once('health', () => { calls++; return work.promise; });
  assert.equal(w.runtime.once('health', () => { throw new Error('duplicate'); }), first);
  await flush(); assert.equal(calls, 1); assert.equal(w.runtime.stats().jobs, 1); assert.equal(w.timers.size, 0);
  work.resolve('done'); assert.equal(await first, 'done'); assert.equal(w.runtime.stats().jobs, 0); w.noListeners();
});

test('failed single-flight releases its key for a later successful owner', async () => {
  const w = environment(), error = new Error('failed');
  assert.equal((await outcome(w.runtime.once('health', () => { throw error; }))).error, error);
  assert.equal(w.runtime.stats().jobs, 0); assert.equal(await w.runtime.once('health', () => 7), 7);
  assert.equal(w.runtime.stats().jobs, 0); assert.equal(w.timers.size, 0); w.noListeners();
});

test('single-flight caller abort cancels its owned request and releases all resources', async () => {
  const w = environment(), caller = new w.Controller();
  const result = outcome(w.runtime.once('health', signal => w.runtime.request('/api/test', {signal}), {signal: caller.signal}));
  await flush(); assert.equal(w.requests.length, 1); caller.abort(); await flush();
  assert.equal((await result).error.name, 'AbortError'); assert.equal(w.runtime.stats().jobs, 0);
  assert.equal(w.requests[0].init.signal.aborted, true); assert.equal(w.timers.size, 0); w.noListeners();
});

test('cancel retires a started single-flight request before an ignored transport settles', async () => {
  const w = environment();
  const result = outcome(w.runtime.once('health', signal => w.runtime.request('/api/test', {signal})));
  await flush(); assert.equal(w.runtime.cancel('health'), true); await flush();
  assert.equal((await result).error.name, 'AbortError'); assert.equal(w.requests[0].init.signal.aborted, true);
  assert.equal(w.runtime.stats().jobs, 0); assert.equal(w.timers.size, 0); w.noListeners();
  const response = w.reply(); w.requests[0].resolve(response); await flush(); assert.equal(response.cancellations, 1);
});

test('single-flight success detaches its caller; a duplicate caller cannot cancel the first owner', async () => {
  const w = environment(), caller = new w.Controller(), duplicate = new w.Controller(), work = deferred();
  const first = w.runtime.once('health', () => work.promise, {signal: caller.signal});
  assert.equal(w.runtime.once('health', () => 'duplicate', {signal: duplicate.signal}), first);
  duplicate.abort(); await flush(); assert.equal(w.runtime.stats().jobs, 1);
  work.resolve('done'); assert.equal(await first, 'done'); assert.equal(w.runtime.stats().jobs, 0); w.noListeners();
});

test('cancel before work starts creates no native request', async () => {
  const w = environment(); let calls = 0;
  const result = outcome(w.runtime.once('health', () => { calls++; }));
  assert.equal(w.runtime.cancel('health'), true); assert.equal(w.runtime.cancel('health'), false);
  assert.equal((await result).error.name, 'AbortError'); assert.equal(calls, 0);
  assert.equal(w.runtime.stats().jobs, 0); assert.equal(w.timers.size, 0); w.noListeners();
});

test('canceled late single-flight completion cannot delete a replacement owner', async () => {
  const w = environment(), old = deferred(), current = deferred();
  const first = outcome(w.runtime.once('health', () => old.promise)); await flush();
  w.runtime.cancel('health');
  const replacement = w.runtime.once('health', () => current.promise); await flush();
  assert.equal((await first).error.name, 'AbortError'); old.resolve('old'); await flush();
  assert.equal(w.runtime.stats().jobs, 1); assert.equal(w.runtime.once('health', () => 'duplicate'), replacement);
  current.resolve('new'); assert.equal(await replacement, 'new'); assert.equal(w.runtime.stats().jobs, 0); w.noListeners();
});

test('pre-aborted single-flight does not claim the key or start work', async () => {
  const w = environment(), caller = new w.Controller(); caller.abort(); let calls = 0;
  const result = outcome(w.runtime.once('health', () => { calls++; }, {signal: caller.signal}));
  assert.equal((await result).error.name, 'AbortError'); assert.equal(calls, 0);
  assert.equal(w.runtime.stats().jobs, 0); assert.equal(w.timers.size, 0); w.noListeners();
});

test('preview cap and repeated same-source attachment have only one pump owner', async () => {
  const w = environment(), images = Array.from({length: 5}, () => w.image());
  for (const img of images) { w.runtime.preview(img, '/preview'); w.runtime.preview(img, '/preview'); }
  await flush(); assert.equal(w.requests.length, 3); assert.equal(w.runtime.stats().inFlight, 3); assert.equal(w.timers.size, 4);
  w.runtime.stopAll(); await flush(); assert.equal(w.runtime.stats().previews, 0); assert.equal(w.runtime.stats().inFlight, 0);
  assert.equal(w.timers.size, 0); assert.equal(w.liveUrls.size, 0); w.noListeners();
});

test('preview body timeout frees its network slot and retries with bounded backoff', async () => {
  const w = environment(), img = w.image(), body = deferred(); w.runtime.preview(img, '/preview'); await flush();
  const response = w.reply({blob: body}); w.requests[0].resolve(response); await flush();
  await w.advance(4000); assert.equal(w.runtime.stats().inFlight, 0); assert.equal(response.cancellations, 1);
  assert.equal(img.dataset.previewState, 'stale'); assert.equal(w.requests.length, 1);
  await w.advance(1499); assert.equal(w.requests.length, 1);
  await w.advance(101); assert.equal(w.requests.length, 2); assert.equal(w.runtime.stats().inFlight, 1);
  w.runtime.stopAll(); await flush(); body.resolve(new Blob(['late'], {type: 'image/jpeg'})); await flush();
  assert.equal(w.timers.size, 0); assert.equal(w.created.length, 0); assert.equal(w.runtime.stats().inFlight, 0); w.noListeners();
});

test('preview replacement revokes the previous object URL and stop retires the current URL', async () => {
  const w = environment(), img = w.image(); w.runtime.preview(img, '/preview', 100); await flush();
  w.requests[0].resolve(w.reply()); await flush(); const first = img.src; assert.equal(w.liveUrls.size, 1);
  await w.advance(135); assert.equal(w.requests.length, 2); w.requests[1].resolve(w.reply({seq: '2'})); await flush();
  assert.notEqual(img.src, first); assert.deepEqual(w.revoked, [first]); assert.equal(w.liveUrls.size, 1);
  w.runtime.stopPreview(img); await flush(); assert.equal(w.liveUrls.size, 0); assert.equal(w.timers.size, 0); w.noListeners();
});

test('replaced preview cannot paint late old body over the new source', async () => {
  const w = environment(), img = w.image(), oldBody = deferred(); w.runtime.preview(img, '/old'); await flush();
  w.requests[0].resolve(w.reply({blob: oldBody})); await flush(); w.runtime.preview(img, '/new'); await flush();
  assert.equal(w.requests.length, 2); w.requests[1].resolve(w.reply()); await flush(); const current = img.src;
  oldBody.resolve(new Blob(['old'], {type: 'image/jpeg'})); await flush();
  assert.equal(img.src, current); assert.equal(w.created.length, 1); assert.equal(w.liveUrls.size, 1);
  assert.equal(w.runtime.stats().inFlight, 0); w.runtime.stopAll(); await flush(); assert.equal(w.timers.size, 0); w.noListeners();
});

test('stopped preview cancels a late response body and creates no URL', async () => {
  const w = environment(), img = w.image(); w.runtime.preview(img, '/preview'); await flush();
  w.runtime.stopPreview(img); await flush(); const response = w.reply(); w.requests[0].resolve(response); await flush();
  assert.equal(response.cancellations, 1); assert.equal(w.created.length, 0);
  assert.equal(w.timers.size, 0); assert.equal(w.runtime.stats().inFlight, 0); w.noListeners();
});

for (const event of ['visibilitychange', 'pagehide']) test(`${event} stops pending preview body and idle pump`, async () => {
  const w = environment(), img = w.image(), body = deferred(); w.runtime.preview(img, '/preview'); await flush();
  w.requests[0].resolve(w.reply({blob: body})); await flush();
  if (event === 'visibilitychange') { w.document.hidden = true; w.document.dispatchEvent(new Event(event)); }
  else w.window.dispatchEvent(new Event(event));
  await flush(); assert.equal(w.runtime.stats().inFlight, 0); assert.equal(w.runtime.stats().previews, 0); assert.equal(w.timers.size, 0);
  body.resolve(new Blob(['late'], {type: 'image/jpeg'})); await flush(); assert.equal(w.created.length, 0); w.noListeners();
});

for (const scope of ['page', 'detached', 'hidden', 'auth']) test(`preview rechecks ${scope} visibility before committing a body`, async () => {
  const w = environment(), img = w.image(), body = deferred(); w.runtime.preview(img, '/preview'); await flush();
  w.requests[0].resolve(w.reply({blob: body})); await flush();
  if (scope === 'page') img.page.active = false;
  if (scope === 'detached') img.isConnected = false;
  if (scope === 'hidden') img.hidden = true;
  if (scope === 'auth') w.document.authVisible = true;
  body.resolve(new Blob(['late'], {type: 'image/jpeg'})); await flush();
  assert.equal(w.created.length, 0); assert.equal(img.writes.length, 0); assert.equal(w.runtime.stats().previews, 0);
  assert.equal(w.runtime.stats().inFlight, 0); assert.equal(w.timers.size, 0); w.noListeners();
});

test('repeated navigation with abort-ignoring producers does not grow timers, URLs or network owners', async () => {
  const w = environment(), img = w.image();
  for (let i = 0; i < 30; i++) {
    w.runtime.preview(img, `/preview/${i}`); await flush(); const request = w.requests.at(-1), body = deferred();
    if (i % 3 === 0) { request.resolve(w.reply()); await flush(); }
    else if (i % 3 === 1) { request.resolve(w.reply({blob: body})); await flush(); }
    w.runtime.stopAll(); await flush();
    if (i % 3 === 1) body.resolve(new Blob(['late'], {type: 'image/jpeg'}));
    else if (i % 3 === 2) request.resolve(w.reply());
    await flush(); assert.equal(w.runtime.stats().previews, 0); assert.equal(w.runtime.stats().inFlight, 0);
    assert.equal(w.timers.size, 0); assert.equal(w.liveUrls.size, 0); w.noListeners();
  }
  assert.equal(w.requests.length, 30); await w.advance(60000); assert.equal(w.requests.length, 30); assert.equal(w.timers.size, 0);
});

test('invalid preview format never creates an object URL and backs off', async () => {
  const w = environment(), img = w.image(); w.runtime.preview(img, '/preview'); await flush();
  w.requests[0].resolve(w.reply({type: 'text/html'})); await flush();
  assert.equal(w.created.length, 0); assert.equal(img.dataset.previewState, 'reconnecting'); assert.equal(w.runtime.stats().inFlight, 0);
  await w.advance(1499); assert.equal(w.requests.length, 1); w.runtime.stopAll(); await flush(); assert.equal(w.timers.size, 0); w.noListeners();
});

test('HTTP preview failure cancels its unread response body before backoff', async () => {
  const w = environment(), img = w.image(); w.runtime.preview(img, '/preview'); await flush();
  const response = w.reply({status: 503}); w.requests[0].resolve(response); await flush();
  assert.equal(response.cancellations, 1); assert.equal(w.created.length, 0); assert.equal(w.runtime.stats().inFlight, 0);
  w.runtime.stopAll(); await flush(); assert.equal(w.timers.size, 0); w.noListeners();
});

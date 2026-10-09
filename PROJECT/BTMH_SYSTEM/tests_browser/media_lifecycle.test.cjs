'use strict';
// Browser contracts exercised without a camera/browser install: real controller,
// deterministic DOM/media/network adapters, cancellable requests and fake time.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_media_v5410.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 80; i++) await Promise.resolve(); };

function browser(options = {}) {
  const w = {now: 0, timers: new Map(), next: 0, requests: [], peers: [], sockets: [], warnings: [], events: [], frameCallbacks: new Map(), imagePreviews: new Map(), ...options};
  w.later = (fn, delay, repeat = 0) => { const id = ++w.next; w.timers.set(id, {fn, at: w.now + delay, repeat}); return id; };
  w.clear = id => w.timers.delete(id);
  w.advance = async ms => {
    const target = w.now + ms;
    while (true) {
      const next = [...w.timers.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
      if (!next) break;
      const [id, timer] = next; w.now = timer.at;
      if (timer.repeat) timer.at += timer.repeat; else w.timers.delete(id);
      timer.fn(); await flush();
    }
    w.now = target; await flush();
  };
  class Element extends EventTarget {
    constructor(tag) {
      super(); this.tagName = tag.toUpperCase(); this.dataset = {}; this.style = {}; this.children = [];
      this.clientWidth = 640; this.clientHeight = 360; this.readyState = 0; this.videoWidth = 0; this.videoHeight = 0;
      this.classes = new Set();
      this.classList = {add: (...names) => names.forEach(n => this.classes.add(n)), remove: n => this.classes.delete(n), contains: n => this.classes.has(n),
        toggle: (n, on) => { if (on ?? !this.classes.has(n)) this.classes.add(n); else this.classes.delete(n); }};
    }
    prepend(child) { child.parentElement = this; this.children.unshift(child); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(e => e !== this); }
    removeAttribute(name) { if (name === 'src') this._src = ''; }
    querySelector(selector) {
      if (selector === 'p,span') return this.children[0] || null;
      const match = /^(video|canvas)\[data-btmh-media-(key|canvas)="(.+)"\]$/.exec(selector);
      return match ? this.children.find(e => e.tagName === match[1].toUpperCase() && e.dataset[match[2] === 'key' ? 'btmhMediaKey' : 'btmhMediaCanvas'] === match[3]) || null : null;
    }
    set srcObject(value) { this._stream = value; this.readyState = value && !w.noVideo && !(w.smallNoVideo && w.currentQuality === 'small') ? 2 : 0; this.videoWidth = this.readyState ? 1920 : 0; this.videoHeight = this.readyState ? 1080 : 0; }
    get srcObject() { return this._stream; }
    set src(value) { this._src = value; if (value && !w.noImage) queueMicrotask(() => this.onload?.()); }
    get src() { return this._src; }
    play() { if (this.readyState >= 2) this.dispatchEvent(new Event('playing')); return Promise.resolve(); }
    pause() {}
    requestVideoFrameCallback(fn) { const id = ++w.next; w.frameCallbacks.set(id, {element: this, fn}); return id; }
    cancelVideoFrameCallback(id) { w.frameCallbacks.delete(id); }
    getVideoPlaybackQuality() { return {totalVideoFrames: w.freezeRendering ? 0 : Math.floor(w.now * 25 / 1000), droppedVideoFrames: 0}; }
    getContext() { return {setTransform() {}, clearRect() { w.overlayOps?.push('clear'); }, fillRect() {}, drawImage() {}, strokeRect() { w.overlayOps?.push('box'); }, measureText: () => ({width: 20}), fillText() {}}; }
  }
  if (w.noFrameCallbacks) Element.prototype.requestVideoFrameCallback = undefined;
  if (w.noPlaybackQuality) Element.prototype.getVideoPlaybackQuality = undefined;
  class Peer extends EventTarget {
    constructor() { super(); if (w.assertOnePeer) assert.equal(w.peers.filter(p => !p.closed).length, 0, 'second peer opened before previous owner retired'); this.iceGatheringState = 'complete'; this.connectionState = 'new'; this.closed = false; w.peers.push(this); }
    addTransceiver() {}
    async createOffer() { if (w.holdOffer && w.peers.length === 1) await new Promise(resolve => { w.releaseOffer = resolve; }); return {type: 'offer', sdp: 'offer'}; }
    async setLocalDescription(offer) { this.localDescription = offer; }
    async setRemoteDescription() {
      if (this.closed) throw new Error('Peer closed');
      w.currentQuality = this.nativeQuality || 'main';
      this.connectionState = 'connected'; this.onconnectionstatechange?.();
      this.ontrack?.({streams: [{}], track: {}});
    }
    async getStats() {
      const frames = w.freezeStats ? 0 : Math.floor(w.now * 25 / 1000);
      return new Map([['in', {type: 'inbound-rtp', kind: 'video', framesReceived: frames, framesDecoded: frames, codecId: 'codec', jitter: .002,
        packetsLost: 0, jitterBufferDelay: frames * .04, jitterBufferEmittedCount: frames}], ['codec', {mimeType: 'video/H264', sdpFmtpLine: 'packetization-mode=1'}],
        ['pair', {type: 'candidate-pair', state: 'succeeded', nominated: true, currentRoundTripTime: .003}]]);
    }
    fail(state = 'failed') { this.connectionState = state; this.onconnectionstatechange?.(); }
    close() { this.closed = true; this.connectionState = 'closed'; }
  }
  class Socket {
    static OPEN = 1;
    constructor(url) { this.url = url; this.readyState = 1; this.sent = []; w.sockets.push(this);
      if (url.includes('/preview/ws')) {
        if (w.wsRejectCamera) queueMicrotask(() => { this.readyState = 3; this.onclose?.({code: 4409}); });
        else if (!w.noWsFrames) queueMicrotask(() => this.onmessage?.({data: new Uint8Array([1])}));
      }
    }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; }
  }
  const response = (body, status = 200, location, quality, qualityFallback) => ({ok: status >= 200 && status < 300, status, headers: {get: name => ({Location: location, 'X-BTMH-Quality': quality, 'X-BTMH-Quality-Fallback': qualityFallback})[name] || null}, text: async () => typeof body === 'string' ? body : JSON.stringify(body)});
  const caps = () => w.caps || {native_gateway: {available: true, running: true, source_healthy: true, whep_url: '/api/v1/media/gateway/whep'}, webrtc: {available: false}, camera_matches_active: true};
  const fetch = async (url, init) => {
    const request = {url: String(url), init}; w.requests.push(request);
    if (request.url.includes('/capabilities')) return response(caps());
    if (new URL(request.url, 'http://localhost:8100').pathname.endsWith('/gateway/whep') && init.method === 'POST') {
      const requestedQuality = new URL(request.url).searchParams.get('quality') || 'main';
      if (requestedQuality === 'small' && w.smallFailure) return response({code: w.smallFailure}, 502);
      const nativeResponse = sessionNumber => {
        const quality = w.nativeQuality || (w.smallRaceFallback && requestedQuality === 'small' ? 'main' : requestedQuality);
        w.peers[sessionNumber - 1].nativeQuality = quality;
        return response('answer', 201, `/api/v1/media/gateway/whep/session/session-${sessionNumber}`, quality,
          w.smallRaceFallback && requestedQuality === 'small' ? w.smallRaceFallback : null);
      };
      if (w.holdLateNative) { w.holdLateNative = false; const sessionNumber = w.peers.length;
        return await new Promise(resolve => { w.releaseNative = () => resolve(nativeResponse(sessionNumber)); }); }
      if (w.holdNative) { w.holdNative = false; return await new Promise((resolve, reject) => { w.pendingRequest = request; init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true}); }); }
      if (w.nativeFailure) return response({code: w.nativeFailure}, 502);
      if (w.nativeDelayMs) {
        const sessionNumber = w.peers.length;
        w.delayedNativePending = true;
        return await new Promise((resolve, reject) => {
          const cancel = () => { w.clear(timer); w.delayedNativePending = false; init.signal.removeEventListener('abort', cancel); reject(new DOMException('Aborted', 'AbortError')); };
          const timer = w.later(() => { w.delayedNativePending = false; init.signal.removeEventListener('abort', cancel); resolve(nativeResponse(sessionNumber)); }, w.nativeDelayMs);
          init.signal.addEventListener('abort', cancel, {once: true});
        });
      }
      if(w.holdNativeBody){w.holdNativeBody=false;const result=nativeResponse(w.peers.length);result.text=()=>new Promise((resolve,reject)=>{init.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')),{once:true});});return result;}
      return nativeResponse(w.peers.length);
    }
    if (request.url.includes('/webrtc/offer')) return response({session_id: `python-${w.peers.length}`, sdp: 'answer', type: 'answer'});
    return response({ok: true});
  };
  const document = new EventTarget(); document.hidden = false; document.querySelector = () => null; document.createElement = tag => new Element(tag);
  ['btmh:media-state', 'btmh:media-stats', 'btmh:media-fallback', 'btmh:media-quality-fallback'].forEach(name => document.addEventListener(name, e => w.events.push({name, ...e.detail})));
  const window = new EventTarget(); window.devicePixelRatio = 1; window.RTCPeerConnection = Peer; window.WebSocket = Socket;
  window.BTMHRuntime = {preview: (image, url) => { w.imagePreviews.set(image, url); if (!w.noImage) queueMicrotask(() => image.onload?.()); }, stopPreview: image => w.imagePreviews.delete(image)};
  class FakeDate extends Date { constructor(...args) { super(...(args.length ? args : [1700000000000 + w.now])); } static now() { return 1700000000000 + w.now; } }
  const context = {window, document, Event, CustomEvent, DOMException, AbortController, URL, Blob, Image: Element, Date: FakeDate,
    location: {href: 'http://localhost:8100/', origin: 'http://localhost:8100', host: 'localhost:8100', protocol: 'http:', hostname: 'localhost'},
    performance: {now: () => w.now}, localStorage: {getItem: () => 'test-user-token'}, console: {warn: (...args) => w.warnings.push(args)},
    RTCPeerConnection: Peer, WebSocket: Socket, MediaStream: class {}, fetch, getComputedStyle: () => ({position: 'relative'}),
    setTimeout: (fn, ms) => w.later(fn, ms), clearTimeout: w.clear, setInterval: (fn, ms) => w.later(fn, ms, ms), clearInterval: w.clear,
    createImageBitmap: async () => ({width: 1920, height: 1080, close() {}})};
  window.createImageBitmap = context.createImageBitmap;
  Object.defineProperty(context, 'BTMHRuntime', {get: () => window.BTMHRuntime});
  vm.runInNewContext(source, context, {filename: 'btmh_media_v5410.js'});
  w.api = window.BTMHMedia; w.document = document; w.window = window;
  w.elements = () => { const wrap = new Element('div'), video = new Element('video'), image = new Element('img'); wrap.prepend(video); wrap.prepend(image); return {wrap, video, image}; };
  w.mount = (key = 'live', config = {}) => { const elements = w.elements(); w.api.mount(key, {...elements, ...config}); return elements; };
  w.frame = (metadata = {}) => { for (const [id, callback] of [...w.frameCallbacks]) { w.frameCallbacks.delete(id); callback.fn(w.now, metadata); } };
  w.clean = async () => { w.api.stopAll(); await flush(); assert.equal(w.peers.filter(p => !p.closed).length, 0); assert.equal(w.sockets.filter(s => s.readyState !== 3).length, 0); assert.equal(w.frameCallbacks.size, 0); assert.equal(w.timers.size, 0); };
  return w;
}

test('native video is authenticated same-origin; stop removes peer, session and callbacks', async () => {
  const w = browser(); w.mount(); await flush();
  assert.equal(w.api.stats().live.transport, 'NATIVE_GATEWAY_WEBRTC');
  assert.equal(w.api.stats().live.state, 'live'); assert.equal(w.sockets.length, 0);
  const post = w.requests.find(r => r.init.method === 'POST');
  assert.equal(post.init.credentials, 'same-origin'); assert.equal(post.init.headers.Authorization, 'Bearer test-user-token');
  await w.clean(); assert.ok(w.requests.some(r => r.init.method === 'DELETE' && r.url.includes('/gateway/whep/session/')));
});

test('tracking boxes expire without another metadata packet while live video continues', async () => {
  const w = browser({overlayOps: []});
  const overlay = w.document.createElement('canvas');
  w.mount('recognition', {cameraId: 2, overlay}); await flush();
  const socket = w.sockets.find(item => item.url.includes('/metadata/ws'));
  const meta = {camera_id: 2, source_epoch: 0, ai_state: 'ACTIVE', sent_at: 1700000000,
    updated_at: 1700000000, tracking_age_ms: 0, frame_width: 640, frame_height: 360,
    tracks: [{bbox: [100, 80, 60, 90], recognized: true, full_name: 'Test verified', daily_sequence: 2}]};
  socket.onmessage({data: JSON.stringify(meta)}); await w.advance(20);
  assert.equal(w.overlayOps.at(-1), 'box');
  await w.advance(1100);
  assert.equal(w.overlayOps.at(-1), 'clear', 'silent metadata must not leave a verified box indefinitely');
  assert.equal(w.api.stats().recognition.state, 'live');
  await w.clean();
});

test('old metadata source epochs cannot revive boxes after expiry or overwrite current camera', async () => {
  const w = browser({overlayOps: []}), received = [];
  w.document.addEventListener('btmh:media-metadata', event => received.push(event.detail.meta));
  w.mount('recognition', {cameraId: 2, overlay: w.document.createElement('canvas')}); await flush();
  const socket = w.sockets.find(item => item.url.includes('/metadata/ws'));
  const fresh = {camera_id: 2, source_epoch: 3, ai_state: 'ACTIVE', sent_at: 1700000000, updated_at: 1700000000,
    tracking_age_ms: 0, frame_width: 640, frame_height: 360, tracks: [{bbox: [100, 80, 60, 90]}]};
  socket.onmessage({data: JSON.stringify(fresh)}); await w.advance(20);
  const count = received.length;
  socket.onmessage({data: JSON.stringify({...fresh, camera_id: 1})});
  socket.onmessage({data: JSON.stringify({...fresh, updated_at: 1699999999.9})});
  assert.equal(received.length, count);
  await w.advance(1100);
  assert.equal(received.at(-1).metadata_stale, true); assert.equal(received.at(-1).tracks.length, 0);
  const afterExpiry = received.length;
  socket.onmessage({data: JSON.stringify({...fresh, source_epoch: 2, sent_at: 1700000001.12, updated_at: 1700000001.12})});
  await w.advance(20); assert.equal(received.length, afterExpiry); assert.equal(w.overlayOps.at(-1), 'clear');
  await w.clean();
});

test('repeated packets do not extend the lifetime of an old inference result', async () => {
  const w = browser({overlayOps: []});
  w.mount('recognition', {cameraId: 2, overlay: w.document.createElement('canvas')}); await flush();
  const socket = w.sockets.find(item => item.url.includes('/metadata/ws'));
  const meta = {camera_id: 2, source_epoch: 0, ai_state: 'ACTIVE', sent_at: 1700000000.9, updated_at: 1700000000,
    tracking_age_ms: 900, frame_width: 640, frame_height: 360, tracks: [{bbox: [100, 80, 60, 90]}]};
  socket.onmessage({data: JSON.stringify(meta)}); await w.advance(50);
  socket.onmessage({data: JSON.stringify({...meta, sent_at: 1700000000.95, tracking_age_ms: 950})});
  await w.advance(70); assert.equal(w.overlayOps.at(-1), 'clear');
  socket.onmessage({data: JSON.stringify({...meta, sent_at: 1700000001.1, tracking_age_ms: 1100})});
  await w.advance(20); assert.equal(w.overlayOps.at(-1), 'clear');
  await w.clean();
});

test('navigation aborts pending WHEP; old cleanup cannot close remounted video', async () => {
  const w = browser({holdNative: true}), elements = w.mount(); await flush();
  assert.ok(w.pendingRequest); w.api.mount('live', elements); await flush();
  assert.equal(w.pendingRequest.init.signal.aborted, true); assert.equal(w.peers[0].closed, true);
  assert.equal(w.api.stats().live.state, 'live'); assert.equal(w.peers.filter(p => !p.closed).length, 1); assert.ok(elements.video.srcObject);
  await w.clean();
});

test('late createOffer continuation is ignored after a new owner mounts', async () => {
  const w = browser({holdOffer: true}), elements = w.mount(); await flush();
  w.api.mount('live', elements); await flush(); const current = w.peers[1];
  w.releaseOffer(); await flush(); assert.equal(current.closed, false); assert.equal(w.api.stats().live.state, 'live');
  assert.equal(w.requests.filter(r => new URL(r.url, 'http://localhost:8100').pathname.endsWith('/gateway/whep') && r.init.method === 'POST').length, 1); await w.clean();
});

test('an unresolved browser offer times out and advances to the next transport', async () => {
  const w = browser({holdOffer: true}); w.mount(); await flush();
  assert.equal(w.api.stats().live.state, 'connecting'); await w.advance(25001);
  assert.equal(w.api.stats().live.transport, 'WEBSOCKET');
  assert.match(w.api.stats().live.fallbackReason, /NATIVE_GATEWAY_WEBRTC_NEGOTIATION_TIMEOUT/);
  assert.equal(w.peers[0].closed, true); w.releaseOffer(); await flush();
  assert.equal(w.requests.filter(r => new URL(r.url, 'http://localhost:8100').pathname.endsWith('/gateway/whep') && r.init.method === 'POST').length, 0); await w.clean();
});

test('WHEP Location is released even when navigation aborts a pending SDP body', async () => {
  const w=browser({holdNativeBody:true}),elements=w.mount();await flush();
  w.api.mount('live',elements);await flush();
  assert.ok(w.requests.some(r=>r.init.method==='DELETE'&&r.url.endsWith('/session/session-1')));
  assert.equal(w.api.stats().live.state,'live');assert.equal(w.peers.filter(p=>!p.closed).length,1);await w.clean();
});

test('late WHEP headers after abort release their session without touching the new owner', async () => {
  const w = browser({holdLateNative: true}), elements = w.mount(); await flush();
  w.api.mount('live', elements); await flush(); const owner = elements.video.srcObject;
  w.releaseNative(); await flush();
  assert.ok(w.requests.some(r => r.init.method === 'DELETE' && r.url.endsWith('/session/session-1')));
  assert.equal(w.api.stats().live.state, 'live'); assert.equal(elements.video.srcObject, owner);
  assert.equal(w.peers.filter(p => !p.closed).length, 1); await w.clean();
});

test('native timeout falls back explicitly with original reason retained', async () => {
  const w = browser({holdNative: true}); w.mount(); await flush(); await w.advance(11001);
  assert.equal(w.api.stats().live.transport, 'WEBSOCKET'); assert.match(w.api.stats().live.fallbackReason, /REQUEST_TIMEOUT/);
  assert.ok(w.warnings.some(entry => entry[1].reason === 'REQUEST_TIMEOUT')); assert.equal(w.peers[0].closed, true); await w.clean();
});

test('Python WebRTC disconnect reconnects without duplicate peers', async () => {
  const w = browser({caps: {native_gateway: {available: false, reason_code: 'GATEWAY_NOT_INSTALLED'}, webrtc: {available: true}, camera_matches_active: true}});
  w.mount(); await flush(); assert.equal(w.api.stats().live.transport, 'PYTHON_WEBRTC'); w.peers[0].fail(); await flush();
  assert.equal(w.api.stats().live.state, 'reconnecting'); await w.advance(351);
  assert.equal(w.api.stats().live.state, 'live'); assert.equal(w.api.stats().live.reconnectCount, 1); assert.equal(w.peers.filter(p => !p.closed).length, 1); await w.clean();
});

test('missing MediaMTX retains unavailable diagnostics without overlaying live Python fallback video', async () => {
  const w = browser({caps: {native_gateway: {available: false, state: 'UNAVAILABLE', reason: 'MEDIAMTX_NOT_INSTALLED', native_webrtc: false}, webrtc: {available: true}, camera_matches_active: true}});
  const elements = w.mount(); await flush(); const stats = w.api.stats().live;
  assert.equal(stats.state, 'live'); assert.equal(stats.transport, 'PYTHON_WEBRTC'); assert.equal(stats.currentTransport, 'PYTHON_WEBRTC');
  assert.equal(stats.nativeGatewayAvailable, false); assert.equal(stats.nativeGatewayState, 'UNAVAILABLE'); assert.equal(stats.nativeGatewayReason, 'MEDIAMTX_NOT_INSTALLED');
  assert.match(stats.fallbackReason, /NATIVE_GATEWAY_WEBRTC: MEDIAMTX_NOT_INSTALLED/);
  assert.ok(w.events.some(e => e.name === 'btmh:media-fallback' && e.transport === 'NATIVE_GATEWAY_WEBRTC' && e.reason === 'MEDIAMTX_NOT_INSTALLED'));
  assert.ok(!w.events.some(e => ['btmh:media-state', 'btmh:media-stats'].includes(e.name) && e.transport === 'NATIVE_GATEWAY_WEBRTC'));
  assert.ok(!w.requests.some(r => r.url.includes('/gateway/whep')));
  assert.ok(!elements.wrap.children.some(e => e.className === 'btmh-media-transport-status'));
  assert.equal(elements.wrap.dataset.btmhCurrentTransport, 'PYTHON_WEBRTC'); await w.clean();
});

test('missing native reason is retained when the browser has no WebRTC and bitmap fallback is used', async () => {
  const w = browser({caps: {native_gateway: {available: false, reason_code: 'MEDIAMTX_NOT_INSTALLED'}, webrtc: {available: true}, camera_matches_active: true}});
  w.window.RTCPeerConnection = undefined; const elements = w.mount(); await flush(); const stats = w.api.stats().live;
  assert.equal(stats.state, 'live'); assert.equal(stats.transport, 'WEBSOCKET'); assert.equal(stats.currentTransport, 'WEBSOCKET_ACK_BITMAP');
  assert.match(stats.fallbackReason, /MEDIAMTX_NOT_INSTALLED/); assert.match(stats.fallbackReason, /PYTHON_WEBRTC_UNAVAILABLE/);
  assert.ok(!elements.wrap.children.some(e => e.className === 'btmh-media-transport-status'));
  assert.equal(stats.nativeGatewayReason, 'MEDIAMTX_NOT_INSTALLED'); assert.equal(w.peers.length, 0); await w.clean();
});

test('working native video retains transport diagnostics without a debug overlay', async () => {
  const w = browser({caps: {native_gateway: {available: true, state: 'AVAILABLE', running: true, source_healthy: true, whep_url: '/api/v1/media/gateway/whep'}, webrtc: {available: false}, camera_matches_active: true}}), elements = w.mount(); await flush(); const stats = w.api.stats().live;
  assert.equal(stats.nativeGatewayAvailable, true); assert.equal(stats.currentTransport, 'NATIVE_GATEWAY_WEBRTC');
  assert.equal(stats.nativeGatewayState, 'AVAILABLE');
  assert.ok(!elements.wrap.children.some(e => e.className === 'btmh-media-transport-status'));
  assert.equal(elements.wrap.dataset.btmhCurrentTransport, 'NATIVE_GATEWAY_WEBRTC'); await w.clean();
});

test('gateway source errors never leak credentials into video elements, events or fallback logs', async () => {
  const secret = 'DevCameraPrivatePassword', source = `rtsp://operator:${secret}@camera.example/Streaming/Channels/101`;
  const w = browser({caps: {native_gateway: {available: false, state: source, reason: source, last_error: source}, webrtc: {available: true}, camera_matches_active: true}});
  const elements = w.mount(); await flush();
  const published = JSON.stringify({stats: w.api.stats(), events: w.events, warnings: w.warnings, visible: elements.wrap.children.map(e => e.textContent || ''), dataset: elements.wrap.dataset});
  assert.ok(!published.includes(secret)); assert.ok(!published.includes('rtsp://')); assert.ok(!published.includes('test-user-token'));
  assert.equal(w.api.stats().live.nativeGatewayReason, 'NATIVE_GATEWAY_UNAVAILABLE'); await w.clean();
});

test('a nonprimary camera never opens active-camera Python/WS/native video', async () => {
  const w = browser({caps: {native_gateway: {available: false, reason_code: 'NON_PRIMARY_CAMERA'}, webrtc: {available: false}, camera_matches_active: false}});
  w.mount('grid-9', {cameraId: 9, pollUrl: '/api/v1/cameras/9/frame.jpg', mjpegUrl: '/api/v1/cameras/9/stream.mjpg', allowMjpeg: false}); await flush();
  assert.equal(w.api.stats()['grid-9'].transport, 'POLLING'); assert.match(w.api.stats()['grid-9'].fallbackReason, /NON_PRIMARY_CAMERA/);
  assert.equal(w.peers.length, 0); assert.equal(w.sockets.length, 0); assert.ok(w.requests[0].url.endsWith('?camera_id=9')); assert.ok([...w.imagePreviews.values()].every(url => url === '/api/v1/cameras/9/frame.jpg')); await w.clean();
});

test('camera-scoped native, Python and JPEG websocket requests bind their camera identity', async () => {
  const native = browser(); native.mount('grid-9', {cameraId: 9}); await flush();
  const nativePost = native.requests.find(r => r.init.method === 'POST');
  assert.equal(new URL(nativePost.url).searchParams.get('camera_id'), '9'); assert.equal(native.api.stats()['grid-9'].state, 'live'); await native.clean();
  const python = browser({caps: {native_gateway: {available: false}, webrtc: {available: true}, camera_matches_active: true}});
  python.mount('grid-9', {cameraId: 9}); await flush();
  assert.ok(python.requests.some(r => r.url === '/api/v1/media/webrtc/offer?camera_id=9'));
  assert.equal(python.api.stats()['grid-9'].transport, 'PYTHON_WEBRTC'); await python.clean();
  const websocket = browser({caps: {native_gateway: {available: false}, webrtc: {available: false}, camera_matches_active: true}});
  websocket.mount('grid-9', {cameraId: 9}); await flush();
  assert.equal(new URL(websocket.sockets[0].url).searchParams.get('camera_id'), '9'); await websocket.clean();
});

test('a camera change during negotiation falls through to the requested camera image', async () => {
  const w = browser({nativeFailure: 'NON_PRIMARY_CAMERA', wsRejectCamera: true});
  w.mount('grid-9', {cameraId: 9, pollUrl: '/api/v1/cameras/9/frame.jpg', allowMjpeg: false}); await flush();
  assert.equal(w.api.stats()['grid-9'].transport, 'POLLING'); assert.match(w.api.stats()['grid-9'].fallbackReason, /NON_PRIMARY_CAMERA/);
  assert.equal(w.peers.filter(p => !p.closed).length, 0);
  assert.deepEqual([...w.imagePreviews.values()], ['/api/v1/cameras/9/frame.jpg']); await w.clean();
});

test('JPEG websocket camera-change closure refreshes identity before reconnecting', async () => {
  const w = browser({caps: {native_gateway: {available: false}, webrtc: {available: false}, camera_matches_active: true}});
  w.mount('grid-9', {cameraId: 9, pollUrl: '/api/v1/cameras/9/frame.jpg', allowMjpeg: false}); await flush();
  assert.equal(w.api.stats()['grid-9'].transport, 'WEBSOCKET');
  w.caps = {native_gateway: {available: false, reason_code: 'NON_PRIMARY_CAMERA'}, webrtc: {available: false}, camera_matches_active: false};
  w.sockets[0].onclose({code: 4409}); await flush(); assert.equal(w.api.stats()['grid-9'].reconnectReason, 'NON_PRIMARY_CAMERA');
  await w.advance(351); assert.equal(w.api.stats()['grid-9'].transport, 'POLLING');
  assert.equal(w.requests.filter(r => r.url.includes('/capabilities')).length, 2); await w.clean();
});

test('identity probes close active-camera transports when their scoped camera becomes nonprimary', async () => {
  for (const transport of ['native', 'python', 'websocket']) {
    const w = browser(transport === 'native' ? {} : {caps: {native_gateway: {available: false}, webrtc: {available: transport === 'python'}, camera_matches_active: true}});
    w.mount('grid-9', {cameraId: 9, pollUrl: '/api/v1/cameras/9/frame.jpg', allowMjpeg: false}); await flush();
    w.caps = {native_gateway: {available: false, reason_code: 'NON_PRIMARY_CAMERA'}, webrtc: {available: false}, camera_matches_active: false};
    for (let second = 0; second < 12; second++) {
      w.frame(); const ws = w.sockets.find(s => s.readyState === 1); ws?.onmessage?.({data: new Uint8Array([1])}); await flush(); await w.advance(1000);
    }
    assert.equal(w.api.stats()['grid-9'].state, 'reconnecting');
    assert.equal(w.api.stats()['grid-9'].reconnectReason, 'NON_PRIMARY_CAMERA'); await w.advance(351);
    assert.equal(w.api.stats()['grid-9'].transport, 'POLLING');
    assert.equal(w.peers.filter(p => !p.closed).length, 0); assert.equal(w.sockets.filter(s => s.readyState === 1).length, 0);
    assert.deepEqual([...w.imagePreviews.values()], ['/api/v1/cameras/9/frame.jpg']); await w.clean();
  }
});

test('WebRTC connected without a decoded image remains connecting, then reports failure', async () => {
  const w = browser({noVideo: true}); w.mount(); await flush();
  assert.equal(w.api.stats().live.state, 'connecting'); assert.equal(w.api.stats().live.webRTCConnected, true);
  await w.advance(8001); assert.equal(w.api.stats().live.transport, 'WEBSOCKET'); assert.match(w.api.stats().live.fallbackReason, /NATIVE_GATEWAY_NO_VIDEO/); await w.clean();
});

test('metrics use browser frames, retain unknown latency, and distinguish playout buffer', async () => {
  const w = browser(); w.mount(); await flush();
  for (let second = 0; second < 2; second++) { for (let i = 0; i < 25; i++) { await w.advance(39); w.frame(); } await w.advance(25); }
  const stats = w.api.stats().live; assert.equal(stats.receivedFps, 25); assert.equal(stats.decodedFps, 25); assert.equal(stats.renderedFps, 25);
  assert.equal(stats.videoLatencyMs, null); assert.equal(stats.frameAgeMs, null); assert.equal(stats.playoutBufferMs, 40); assert.match(stats.codec, /video\/H264/); await w.clean();
});

test('capture time estimates clear when the next rendered frame has no capture time', async () => {
  const w = browser(); w.mount(); await flush(); await w.advance(300);
  w.frame({captureTime: 100}); assert.equal(w.api.stats().live.videoLatencyMs, 200);
  w.frame(); assert.equal(w.api.stats().live.videoLatencyMs, null); assert.equal(w.api.stats().live.frameAgeMs, null); await w.clean();
});

test('playback quality measures and watches rendered frames when callbacks are unavailable', async () => {
  const w = browser({noFrameCallbacks: true}); w.mount(); await flush(); await w.advance(2001);
  assert.equal(w.api.stats().live.renderedFps, 25); assert.equal(w.api.stats().live.lastRenderedAgoMs, 0);
  await w.clean();
  const stalled = browser({noFrameCallbacks: true, freezeRendering: true}); stalled.mount(); await flush(); await stalled.advance(7001);
  assert.equal(stalled.api.stats().live.state, 'reconnecting');
  assert.equal(stalled.api.stats().live.reconnectReason, 'NATIVE_GATEWAY_WEBRTC_VIDEO_STALLED'); await stalled.clean();
});

test('browsers without rendering metrics retain unknown rendered FPS and use inbound watchdog', async () => {
  const w = browser({noFrameCallbacks: true, noPlaybackQuality: true, freezeStats: true}); w.mount(); await flush(); await w.advance(2001);
  assert.equal(w.api.stats().live.renderedFps, null); assert.equal(w.api.stats().live.lastRenderedAgoMs, null);
  await w.advance(5000); assert.equal(w.api.stats().live.state, 'reconnecting'); await w.clean();
});

test('stalled rendering reconnects even while inbound RTP continues decoding', async () => {
  const w = browser(); w.mount(); await flush(); await w.advance(7001);
  assert.equal(w.api.stats().live.state, 'reconnecting'); assert.equal(w.api.stats().live.reconnectReason, 'NATIVE_GATEWAY_WEBRTC_VIDEO_STALLED'); await w.advance(351);
  assert.equal(w.peers.filter(p => !p.closed).length, 1); await w.clean();
});

test('JPEG fallback discovers recovered native gateway without waiting for JPEG failure', async () => {
  const w = browser({caps: {native_gateway: {available: false, reason_code: 'GATEWAY_STARTING'}, webrtc: {available: false}, camera_matches_active: true}});
  const elements = w.mount(); await flush(); assert.equal(w.api.stats().live.transport, 'WEBSOCKET');
  w.caps = {native_gateway: {available: true, running: true, source_healthy: true, whep_url: '/api/v1/media/gateway/whep'}, webrtc: {available: false}, camera_matches_active: true};
  // ACK JPEG frames keep fallback alive while capability probes run.
  for (let i = 0; i < 12; i++) { const ws = w.sockets.find(s => s.readyState === 1); ws?.onmessage?.({data: new Uint8Array([1])}); await flush(); await w.advance(1000); }
  await w.advance(351); assert.equal(w.api.stats().live.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(w.api.stats().live.fallbackReason, null);
  assert.equal(w.api.stats().live.currentTransport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(w.api.stats().live.nativeGatewayReason, null);
  assert.ok(!elements.wrap.children.some(e => e.className === 'btmh-media-transport-status')); await w.clean();
});

test('hidden/logout/camera source changes release old resources and invalidate capabilities', async () => {
  const w = browser(); w.mount(); await flush(); w.document.dispatchEvent(new CustomEvent('btmh:camera-source-changed')); await w.advance(351);
  assert.equal(w.requests.filter(r => r.url.includes('/capabilities')).length, 2); assert.equal(w.api.stats().live.reconnectCount, 1);
  w.document.hidden = true; w.document.dispatchEvent(new Event('visibilitychange')); await flush();
  assert.equal(Object.keys(w.api.stats()).length, 0); w.mount(); await flush(); assert.equal(Object.keys(w.api.stats()).length, 0);
  w.document.hidden = false; w.mount(); await flush(); assert.equal(w.api.stats().live.state, 'live');
  w.document.dispatchEvent(new CustomEvent('btmh:auth', {detail: {authenticated: false}})); await flush();
  assert.equal(Object.keys(w.api.stats()).length, 0); w.mount(); await flush(); assert.equal(Object.keys(w.api.stats()).length, 0); await w.clean();
});

test('repeated navigation does not grow timers, DOM layers or native sessions', async () => {
  const w = browser(), elements = w.elements();
  for (let i = 0; i < 20; i++) { w.api.mount('live', elements); await flush(); w.api.stop('live'); await flush(); assert.equal(elements.wrap.children.filter(e => e.tagName === 'CANVAS').length, 0); assert.equal(elements.wrap.children.filter(e => e.className === 'btmh-media-transport-status').length, 0); assert.equal(w.timers.size, 0); }
  assert.equal(w.requests.filter(r => r.init.method === 'POST').length, 20); assert.equal(w.requests.filter(r => r.init.method === 'DELETE').length, 20); await w.clean();
});

const adaptiveCaps = (small = true, reason = '') => ({native_gateway: {available: true, running: true, source_healthy: true,
  whep_url: '/api/v1/media/gateway/whep', small_available: small, small_fallback_reason: reason}, webrtc: {available: false}, camera_matches_active: true});
const nativePosts = w => w.requests.filter(r => r.init.method === 'POST' && new URL(r.url, 'http://localhost:8100').pathname.endsWith('/gateway/whep'));

test('default and explicit single views request main even when small is available', async () => {
  for (const quality of [undefined, 'main', 'invalid']) {
    const w = browser({caps: adaptiveCaps()}); w.mount('single', {quality}); await flush();
    assert.equal(new URL(nativePosts(w)[0].url).searchParams.get('quality'), 'main');
    assert.equal(w.api.stats().single.requestedQuality, 'main'); assert.equal(w.api.stats().single.quality, 'main');
    assert.equal(w.api.stats().single.qualityFallbackReason, null); await w.clean();
  }
});

test('an explicitly small tile requests validated native small quality with camera scope', async () => {
  const w = browser({caps: adaptiveCaps()}), elements = w.mount('grid-9', {cameraId: 9, quality: 'small'}); await flush();
  const url = new URL(nativePosts(w)[0].url), stats = w.api.stats()['grid-9'];
  assert.equal(url.searchParams.get('quality'), 'small'); assert.equal(url.searchParams.get('camera_id'), '9');
  assert.equal(stats.requestedQuality, 'small'); assert.equal(stats.quality, 'small'); assert.equal(stats.qualityFallbackReason, null);
  assert.equal(stats.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(elements.wrap.dataset.btmhQuality, 'small');
  assert.equal(w.peers.length, 1); await w.clean();
});

test('unvalidated small keeps native main and exposes a separate quality fallback', async () => {
  const w = browser({caps: adaptiveCaps(false, 'SMALL_NOT_VALIDATED')}), elements = w.mount('grid-9', {cameraId: 9, quality: 'small'}); await flush();
  const stats = w.api.stats()['grid-9'];
  assert.equal(new URL(nativePosts(w)[0].url).searchParams.get('quality'), 'main'); assert.equal(nativePosts(w).length, 1);
  assert.equal(stats.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(stats.quality, 'main'); assert.equal(stats.requestedQuality, 'small');
  assert.equal(stats.qualityFallbackReason, 'SMALL_NOT_VALIDATED'); assert.equal(stats.fallbackReason, null);
  assert.equal(elements.wrap.dataset.btmhQualityFallback, 'SMALL_NOT_VALIDATED'); assert.equal(w.peers.length, 1);
  assert.ok(w.events.some(e => e.name === 'btmh:media-quality-fallback' && e.reason === 'SMALL_NOT_VALIDATED')); await w.clean();
});

test('older capabilities still allow native main with explicit unavailable small', async () => {
  const w = browser(); w.mount('tile', {quality: 'small'}); await flush();
  assert.equal(w.api.stats().tile.qualityFallbackReason, 'SMALL_UNAVAILABLE');
  assert.equal(w.api.stats().tile.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(nativePosts(w).length, 1); await w.clean();
});

test('backend small readiness race resolves to main without a second negotiation', async () => {
  const w = browser({caps: adaptiveCaps(), smallRaceFallback: 'SMALL_NOT_VALIDATED'}); w.mount('tile', {quality: 'small'}); await flush();
  assert.equal(new URL(nativePosts(w)[0].url).searchParams.get('quality'), 'small');
  assert.equal(w.api.stats().tile.quality, 'main'); assert.equal(w.api.stats().tile.qualityFallbackReason, 'SMALL_NOT_VALIDATED');
  assert.equal(w.api.stats().tile.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(nativePosts(w).length, 1); assert.equal(w.peers.length, 1); await w.clean();
});

test('delayed backend small-to-main retry stays one negotiation beyond the main request deadline', async () => {
  const w = browser({caps: adaptiveCaps(), nativeDelayMs: 15000, smallRaceFallback: 'SMALL_NEGOTIATION_FAILED', assertOnePeer: true});
  w.mount('tile', {quality: 'small'}); await flush(); await w.advance(11001);
  assert.equal(w.delayedNativePending, true); assert.equal(w.api.stats().tile.state, 'connecting'); assert.equal(nativePosts(w).length, 1);
  assert.equal(w.peers.filter(p => !p.closed).length, 1); assert.equal(w.sockets.length, 0);
  await w.advance(4000);
  const stats = w.api.stats().tile; assert.equal(stats.state, 'live'); assert.equal(stats.transport, 'NATIVE_GATEWAY_WEBRTC');
  assert.equal(stats.quality, 'main'); assert.equal(stats.qualityFallbackReason, 'SMALL_NEGOTIATION_FAILED');
  assert.equal(nativePosts(w).length, 1); assert.equal(w.peers.length, 1); await w.clean();
});

test('navigation cancels delayed backend small/main retry and releases every owned timer', async () => {
  const w = browser({caps: adaptiveCaps(), nativeDelayMs: 15000, smallRaceFallback: 'SMALL_NEGOTIATION_FAILED'});
  w.mount('tile', {quality: 'small'}); await flush(); await w.advance(11001);
  assert.equal(w.delayedNativePending, true); await w.clean();
  assert.equal(w.delayedNativePending, false); assert.equal(nativePosts(w).length, 1);
  await w.advance(30000); assert.equal(nativePosts(w).length, 1); assert.equal(w.timers.size, 0);
});

test('unresolved small browser offer has a bounded deadline before one main retry', async () => {
  const w = browser({caps: adaptiveCaps(), holdOffer: true}); w.mount('tile', {quality: 'small'}); await flush();
  await w.advance(25001); assert.equal(w.peers.length, 1); assert.equal(w.api.stats().tile.state, 'connecting');
  await w.advance(13000); assert.equal(w.peers[0].closed, true); assert.equal(w.peers.filter(p => !p.closed).length, 1);
  assert.equal(w.api.stats().tile.state, 'live'); assert.equal(w.api.stats().tile.quality, 'main'); assert.equal(nativePosts(w).length, 1);
  w.releaseOffer(); await flush(); assert.equal(nativePosts(w).length, 1); await w.clean();
});

test('a failed small negotiation retires its owner before one native main retry', async () => {
  const w = browser({caps: adaptiveCaps(), smallFailure: 'SMALL_UNAVAILABLE', assertOnePeer: true}); w.mount('tile', {quality: 'small'}); await flush();
  assert.deepEqual(nativePosts(w).map(r => new URL(r.url).searchParams.get('quality')), ['small', 'main']);
  assert.equal(w.peers[0].closed, true); assert.equal(w.peers.filter(p => !p.closed).length, 1);
  const stats = w.api.stats().tile; assert.equal(stats.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(stats.quality, 'main');
  assert.equal(stats.qualityFallbackReason, 'SMALL_UNAVAILABLE'); assert.equal(stats.fallbackReason, null); await w.clean();
});

test('backend exhausted small/main fallback skips a duplicate frontend main negotiation', async () => {
  const w = browser({caps: adaptiveCaps(), smallFailure: 'SMALL_AND_MAIN_UNAVAILABLE', assertOnePeer: true}); w.mount('tile', {quality: 'small'}); await flush();
  const stats = w.api.stats().tile; assert.equal(stats.transport, 'WEBSOCKET');
  assert.equal(stats.qualityFallbackReason, 'SMALL_AND_MAIN_UNAVAILABLE'); assert.match(stats.fallbackReason, /SMALL_AND_MAIN_UNAVAILABLE/);
  assert.equal(nativePosts(w).length, 1); assert.equal(w.peers.filter(p => !p.closed).length, 0); await w.clean();
});

test('browser small decode failure releases its session and retries main once', async () => {
  const w = browser({caps: adaptiveCaps(), smallNoVideo: true, assertOnePeer: true}); w.mount('tile', {quality: 'small'}); await flush();
  assert.equal(w.api.stats().tile.state, 'connecting'); await w.advance(8001);
  assert.equal(w.api.stats().tile.transport, 'NATIVE_GATEWAY_WEBRTC'); assert.equal(w.api.stats().tile.state, 'live');
  assert.equal(w.api.stats().tile.quality, 'main'); assert.equal(w.api.stats().tile.qualityFallbackReason, 'SMALL_NEGOTIATION_FAILED');
  assert.deepEqual(nativePosts(w).map(r => new URL(r.url).searchParams.get('quality')), ['small', 'main']);
  const closed = w.requests.findIndex(r => r.init.method === 'DELETE'), main = w.requests.findIndex(r => r.init.method === 'POST' && new URL(r.url, 'http://localhost:8100').searchParams.get('quality') === 'main');
  assert.ok(closed >= 0 && closed < main); await w.clean();
});

test('a rejected small codec keeps working main continuous while decoder proof remains available', async () => {
  const w = browser({caps: adaptiveCaps(), smallNoVideo: true, assertOnePeer: true}); w.mount('tile', {quality: 'small'}); await flush(); await w.advance(8001);
  const main = w.peers[1];
  for (let i = 0; i < 25; i++) { w.frame(); await w.advance(1000); }
  assert.equal(main.closed, false); assert.equal(nativePosts(w).length, 2); assert.equal(w.api.stats().tile.quality, 'main');
  assert.equal(w.api.stats().tile.qualityFallbackReason, 'SMALL_NEGOTIATION_FAILED');
  w.smallNoVideo = false; w.document.dispatchEvent(new Event('btmh:camera-source-changed')); await w.advance(351);
  assert.equal(w.api.stats().tile.quality, 'small'); assert.equal(nativePosts(w).length, 3); await w.clean();
});

test('browser failure after backend resolves small request to main skips another main negotiation', async () => {
  const w = browser({caps: adaptiveCaps(), smallRaceFallback: 'SMALL_NOT_VALIDATED', noVideo: true, assertOnePeer: true}); w.mount('tile', {quality: 'small'}); await flush(); await w.advance(8001);
  assert.equal(w.api.stats().tile.transport, 'WEBSOCKET'); assert.match(w.api.stats().tile.fallbackReason, /NATIVE_GATEWAY_NO_VIDEO/);
  assert.equal(nativePosts(w).length, 1); assert.ok(w.requests.some(r => r.init.method === 'DELETE')); await w.clean();
});

test('small and main negotiation failure retain distinct quality and transport fallback reasons', async () => {
  const w = browser({caps: adaptiveCaps(), smallFailure: 'SMALL_UNAVAILABLE', nativeFailure: 'GATEWAY_DOWN'}); w.mount('tile', {quality: 'small'}); await flush();
  const stats = w.api.stats().tile; assert.equal(stats.transport, 'WEBSOCKET'); assert.equal(stats.quality, 'main');
  assert.equal(stats.qualityFallbackReason, 'SMALL_UNAVAILABLE'); assert.match(stats.fallbackReason, /GATEWAY_DOWN/);
  assert.equal(nativePosts(w).length, 2); assert.equal(w.peers.filter(p => !p.closed).length, 0); await w.clean();
});

test('late small negotiation cannot overwrite a fullscreen main owner', async () => {
  const w = browser({caps: adaptiveCaps(), holdLateNative: true}), elements = w.mount('camera', {quality: 'small'}); await flush();
  w.api.mount('camera', {...elements, quality: 'main'}); await flush(); const owner = elements.video.srcObject;
  w.releaseNative(); await flush();
  assert.equal(w.api.stats().camera.requestedQuality, 'main'); assert.equal(w.api.stats().camera.quality, 'main');
  assert.equal(w.api.stats().camera.qualityFallbackReason, null); assert.equal(elements.video.srcObject, owner);
  assert.equal(w.peers.filter(p => !p.closed).length, 1);
  assert.ok(w.requests.some(r => r.init.method === 'DELETE' && r.url.endsWith('/session/session-1'))); await w.clean();
});

test('existing capability monitor changes small quality through one reconnect owner', async () => {
  const w = browser({caps: adaptiveCaps()}); w.mount('tile', {quality: 'small'}); await flush();
  const runProbe = async () => { for (let i = 0; i < 12; i++) { w.frame(); await w.advance(1000); } await w.advance(351); };
  w.caps = adaptiveCaps(false, 'SMALL_NOT_VALIDATED'); await runProbe();
  assert.equal(w.api.stats().tile.quality, 'main'); assert.equal(w.api.stats().tile.qualityFallbackReason, 'SMALL_NOT_VALIDATED');
  assert.equal(w.peers.filter(p => !p.closed).length, 1); assert.equal(nativePosts(w).length, 2);
  w.caps = adaptiveCaps(); await runProbe();
  assert.equal(w.api.stats().tile.quality, 'small'); assert.equal(w.api.stats().tile.qualityFallbackReason, null);
  assert.equal(w.peers.filter(p => !p.closed).length, 1); assert.equal(nativePosts(w).length, 3); await w.clean();
});

test('quality fallback messages expose only known codes and never raw source secrets', async () => {
  for (const reason of ['RTSP_SECRET_TEST', 'rtsp://operator:private@camera.test/Streaming/Channels/102']) {
    const w = browser({caps: adaptiveCaps(false, reason)}); w.mount('tile', {quality: 'small'}); await flush();
    assert.equal(w.api.stats().tile.qualityFallbackReason, 'SMALL_UNAVAILABLE');
    assert.ok(!JSON.stringify(w.events).includes(reason)); await w.clean();
  }
});

test('a main view refuses backend downgrade to small and releases the returned session', async () => {
  const w = browser({caps: adaptiveCaps(), nativeQuality: 'small'}); w.mount('single', {quality: 'main'}); await flush();
  assert.equal(w.api.stats().single.quality, 'main'); assert.match(w.api.stats().single.fallbackReason, /MAIN_QUALITY_REQUIRED/);
  assert.equal(w.peers[0].closed, true); assert.ok(w.requests.some(r => r.init.method === 'DELETE')); await w.clean();
});

test('grid tiles request small; fullscreen and one-column views request main without duplicate mounts', async () => {
  // Share the actual-script logical DOM adapter used by keyed-grid regressions.
  const {browser: gridBrowser, flush: gridFlush} = require('./v4_frontend_lifecycle.test.cjs');
  const w = gridBrowser(); await w.start();
  assert.deepEqual(w.mounts.map(item => item.quality), ['small', 'small']);
  await w.refresh(); assert.equal(w.mounts.length, 2);
  Object.assign(w.active.get('grid-1'), {quality: 'main', qualityFallbackReason: 'SMALL_NOT_VALIDATED'});
  w.event('btmh:media-stats', {key: 'grid-1', state: 'live', quality: 'main', qualityFallbackReason: 'SMALL_NOT_VALIDATED', renderedFps: 25});
  const badge = w.card(1).querySelector('.flags span');
  // Customer status reflects playback; quality diagnostics stay in media state.
  assert.equal(badge.textContent, 'LIVE'); assert.equal(badge.title, '');
  assert.equal(w.active.get('grid-1').quality, 'main'); assert.equal(w.active.get('grid-1').requestedQuality, 'small');
  assert.equal(w.active.get('grid-1').qualityFallbackReason, 'SMALL_NOT_VALIDATED'); assert.equal(w.mounts.length, 2);
  for (const [state, label] of [['reconnecting', 'Đang kết nối'], ['offline', 'Mất kết nối'], ['unavailable', 'Camera không khả dụng'], ['live', 'LIVE']]) {
    w.event('btmh:media-state', {key: 'grid-1', state, quality: 'main', qualityFallbackReason: 'SMALL_NOT_VALIDATED'});
    assert.equal(badge.textContent, label); assert.equal(badge.title, ''); assert.equal(w.mounts.length, 2);
  }
  w.card(1).dispatchEvent(new Event('click'));
  assert.equal(w.mounts.at(-1).key, 'grid-modal'); assert.equal(w.mounts.at(-1).quality, 'main');
  assert.equal(w.active.has('grid-1'), false); assert.ok(w.stops.includes('grid-1'));
  w.ids.get('#v4CameraModalClose').dispatchEvent(new Event('click'));
  assert.equal(w.mounts.at(-1).key, 'grid-1'); assert.equal(w.mounts.at(-1).quality, 'small');
  w.layouts[0].dispatchEvent(new Event('click'));
  assert.deepEqual(w.mounts.slice(-2).map(item => item.quality), ['main', 'main']);
  w.rejectFleet = 'FLEET_UNAVAILABLE'; await w.refresh(); await gridFlush();
  assert.equal(w.active.size, 0, 'failed grid refresh must retire detached media owners');
  w.api.leavePage('signed-out'); assert.equal(w.active.size, 0);
});

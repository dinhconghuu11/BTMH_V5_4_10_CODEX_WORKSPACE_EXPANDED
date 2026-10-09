'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_v4.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 80; i++) await Promise.resolve(); };

// Logical DOM/network/media adapters for the actual script, not rendered CSS QA.
function browser(options = {}) {
  const w = {page: 'live-grid', cameraAllowed: true, enrollmentAllowed: true, presenceAllowed: true, playbackAllowed: true, holdFleet: false, holdSources: false, holdPresence: false, holdPlayback: false, ignoreAbort: true,
    fleetItems: [{id: 1, name: 'One', enabled: true, online: false}, {id: 2, name: 'Two', enabled: true, online: true}],
    requests: [], gumRequests: [], mounts: [], stops: [], removals: [], previews: new Map(), active: new Map(), statsReads: 0, intervals: new Map(), ...options};
  const dataKey = key => key.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
  function matches(el, selector) {
    if (selector.startsWith('.')) return el.classList.contains(selector.slice(1));
    const attribute = /^\[data-([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
    if (attribute) return Object.hasOwn(el.dataset, dataKey(attribute[1])) && (attribute[2] === undefined || String(el.dataset[dataKey(attribute[1])]) === attribute[2]);
    return el.tagName.toLowerCase() === selector;
  }
  class Element extends EventTarget {
    constructor(tag = 'div', id = '') {
      super(); this.tagName = tag.toUpperCase(); this.id = id; this.dataset = {}; this.style = {}; this.children = []; this.parentElement = null;
      this.attributes = {}; this.classes = new Set(); this._text = ''; this.hidden = false; this.videoWidth = 640; this.videoHeight = 480;
      this.classList = {add: (...names) => names.forEach(name => this.classes.add(name)), remove: (...names) => names.forEach(name => this.classes.delete(name)),
        contains: name => this.classes.has(name), toggle: (name, on) => (on ?? !this.classes.has(name)) ? this.classes.add(name) : this.classes.delete(name)};
    }
    set className(value) { this.classes = new Set(value.split(/\s+/).filter(Boolean)); }
    get className() { return [...this.classes].join(' '); }
    set textContent(value) { this._text = String(value); this.children.forEach(child => child.parentElement = null); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    set innerHTML(value) { this._text = value; this.children = []; for(const match of value.matchAll(/<button[^>]*data-v4-segment="(\d+)"[^>]*>(.*?)<\/button>/g)){const child=new Element('button');child.dataset.v4Segment=match[1];child.textContent=match[2];this.append(child);} }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    get options() { return this.children.filter(child => child.tagName === 'OPTION'); }
    append(...children) { children.forEach(child => this.insertBefore(child, null)); }
    insertBefore(child, reference) {
      if (child === reference) return child;
      if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(item => item !== child);
      const index = reference === null ? this.children.length : this.children.indexOf(reference);
      assert.ok(index >= 0, 'DOM reference must belong to the parent');
      this.children.splice(index, 0, child); child.parentElement = this; return child;
    }
    remove() {
      w.removals.push({element: this, owners: [...w.active.keys()], previews: [...w.previews.keys()]});
      if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this);
      this.parentElement = null;
    }
    querySelectorAll(selector) {
      const parts = selector.split(' '), results = [];
      const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
      if (parts.length === 1) return descendants(this).filter(el => matches(el, selector));
      for (const el of this.querySelectorAll(parts[0])) results.push(...el.querySelectorAll(parts.slice(1).join(' ')));
      return results;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    closest(selector) { for (let el = this; el; el = el.parentElement) if (matches(el, selector)) return el; return null; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; }
    play() { return Promise.resolve(); }
    pause() { this.pauses = (this.pauses || 0) + 1; }
    load() {}
    getContext() { return {drawImage() {}}; }
    toDataURL() { return 'data:image/jpeg;base64,test'; }
  }
  const ids = new Map(['v4CameraGrid','v4CameraModal','v4CameraModalTitle','v4CameraModalMeta','v4CameraModalClose','v4CameraModalViewport','v4CameraModalStream',
    'v4EnrollmentCameraName','v4SurveillanceCameraName','v4SurveillanceCameraState','enrollVideo','enrollEmpty','v4PlaybackVideo','v4PlaybackCamera','v4PlaybackDate','v4PlaybackResults','v4PlaybackEmpty','v4PlaybackSearch',
    'v4PresenceList','v4PresenceNow','v4PresenceTotal','v4PresenceAway','v4PresenceVisitors',
    'page-live-grid','page-register','page-playback','page-operations'].map(id => ['#' + id, new Element(id === 'enrollVideo' ? 'video' : 'div', id)]));
  const host = ids.get('#v4CameraGrid'), initialEmpty = new Element(); initialEmpty.className = 'v4-empty'; host.append(initialEmpty);
  ids.get('#v4CameraModal').classList.add('hidden');
  const layouts = [1,2,3,4].map(layout => { const el = new Element('button'); el.dataset.v4Layout = layout; return el; });
  const note = new Element(); note.dataset.sourceNote = '';
  const document = new EventTarget(); document.hidden = !!w.hidden;
  document.createElement = tag => new Element(tag);
  document.querySelector = selector => {
    if (/^#page-.+\.active$/.test(selector)) return selector === `#page-${w.page}.active` ? ids.get(selector.slice(0, -7)) : null;
    return ids.get(selector) || host.querySelector(selector);
  };
  document.querySelectorAll = selector => selector === '[data-v4-layout]' ? layouts : selector === '[data-source-note]' ? [note] : selector === '[data-v4-segment]' ? ids.get('#v4PlaybackResults').querySelectorAll(selector) : [];
  const window = new EventTarget();
  const media = {
    mount(key, init) { assert.equal(w.active.has(key), false, 'a previous media owner must retire before replacement'); const owner = {};
      const entry = {key, ...init, owner, requestedQuality: init.quality, state: 'live', transport: 'NATIVE_GATEWAY_WEBRTC', quality: init.quality, renderedFps: 25};
      w.mounts.push(entry); w.active.set(key, entry); return entry; },
    stop(key) { w.stops.push(key); w.active.delete(key); },
    stats() { w.statsReads++; return Object.fromEntries(w.active); },
  };
  const runtime = {
    once: (_, work) => work(),
    preview: (image, url) => { if (w.previews.get(image)?.url !== url) w.previews.set(image, {url, owner: {}}); },
    stopPreview: image => w.previews.delete(image),
    request(url, init = {}) {
      const request = {url, init}; w.requests.push(request);
      if (url.includes('/fleet/') && w.rejectFleet) return Promise.reject(new Error(w.rejectFleet));
      const payload = {items: url.includes('/fleet/') ? w.fleetItems.map(item => ({...item})) : url.includes('/presence/') ? (w.presenceItems || []) : url.includes('/recordings/segments') ? (w.playbackItems || []) : (w.sourceItems || [])};
      const response = data => ({ok: true, json: async () => data});
      if ((url.includes('/fleet/') && w.holdFleet) || (url.includes('/sources') && w.holdSources) || (url.includes('/presence/') && w.holdPresence) || (url.includes('/recordings/') && w.holdPlayback)) return new Promise((resolve, reject) => {
        request.finish = (data = payload) => { request.completed = true; resolve(response(data)); };
        request.fail = message => { request.completed = true; reject(new Error(message)); };
        if (!w.ignoreAbort) init.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), {once: true});
      });
      request.completed = true; return Promise.resolve(response(payload));
    },
  };
  const navigator = {mediaDevices: {getUserMedia: constraints => new Promise((resolve, reject) => { w.gumRequests.push({constraints, resolve, reject}); })}};
  const context = {window, document, Event, AbortController, Date, localStorage: {getItem: () => 'test-token'}, navigator, BTMHMedia: media, BTMHRuntime: runtime,
    hasUiPermission: permission => permission === 'camera.live' ? w.cameraAllowed : permission === 'employee.enroll' ? w.enrollmentAllowed : permission === 'attendance.view' ? w.presenceAllowed : permission === 'camera.playback' ? w.playbackAllowed : false,
    setInterval: (fn, ms) => { const id = w.intervals.size + 1; w.intervals.set(id, {fn, ms}); return id; }, console};
  if (w.noMedia) delete context.BTMHMedia; else window.BTMHMedia = media;
  w.run = () => vm.runInNewContext(source, context, {filename: 'btmh_v4.js'}); w.run();
  w.api = window.BTMHV4; w.document = document; w.window = window; w.host = host; w.ids = ids; w.layouts = layouts; w.note = note; w.media = media; w.runtime = runtime;
  w.event = (type, detail, target = document) => { const event = new Event(type); event.detail = detail; target.dispatchEvent(event); };
  w.auth = authenticated => w.event('btmh:auth', {authenticated});
  w.navigate = page => { w.api.leavePage(page); w.page = page; w.event('btmh:navigate', {page}); };
  w.visibility = hidden => { document.hidden = hidden; w.event('visibilitychange'); };
  w.fleetRequests = () => w.requests.filter(request => request.url.includes('/fleet/'));
  w.sourceRequests = () => w.requests.filter(request => request.url.includes('/sources'));
  w.cards = () => host.querySelectorAll('.v4-camera-card');
  w.card = id => w.cards().find(card => Number(card.dataset.cameraId) === id);
  w.start = async () => { w.auth(true); await flush(); };
  w.refresh = async items => { if (items) w.fleetItems = items; await w.api.loadFleet(); await flush(); };
  w.stream = name => { const tracks = [{name, stops: 0, stop() { this.stops++; }}]; return {name, tracks, get active() { return tracks.some(track => !track.stops); }, getTracks: () => tracks}; };
  w.event('DOMContentLoaded'); return w;
}

module.exports = {browser, flush};
if (require.main === module) {
  const {test} = require('node:test');
  test('metadata-only refresh preserves keyed cards, images and every peer owner', async () => {
    const w = browser(); await w.start(); const cards = w.cards(), images = cards.map(card => card.querySelector('img'));
    const owners = [...w.active.values()].map(entry => entry.owner);
    await w.refresh([{id: 1, name: 'Renamed <safe>', enabled: true, zone_name: 'New zone', online: true, recording_active: true}, {id: 2, name: 'Two', enabled: true, online: false}]);
    assert.deepEqual(w.cards(), cards); assert.deepEqual(w.cards().map(card => card.querySelector('img')), images);
    assert.deepEqual([...w.active.values()].map(entry => entry.owner), owners); assert.equal(w.mounts.length, 2);
    assert.equal(cards[0].querySelector('b').textContent, 'Renamed <safe>'); assert.equal(cards[0].querySelector('small').textContent, 'New zone');
    assert.equal(cards[0].querySelector('.rec').hidden, false); assert.equal(cards[0].getAttribute('aria-label'), 'Renamed <safe>');
  });
  test('one media stats snapshot per render avoids per-tile full-map reads', async () => {
    const w = browser({fleetItems: Array.from({length: 80}, (_, i) => ({id: i + 1, name: 'Camera', enabled: true}))}); await w.start();
    const before = w.statsReads; await w.refresh(); assert.equal(w.statsReads - before, 1); assert.equal(w.mounts.length, 80);
  });
  test('reordering and new camera insertion preserve existing tiles and peers', async () => {
    const w = browser(); await w.start(); const one = w.card(1), two = w.card(2), owner = w.active.get('grid-1').owner;
    await w.refresh([{id: 2, enabled: true}, {id: 3, enabled: true}, {id: 1, enabled: true}]);
    assert.deepEqual(w.cards().map(card => Number(card.dataset.cameraId)), [2,3,1]);
    assert.equal(w.card(1), one); assert.equal(w.card(2), two); assert.equal(w.active.get('grid-1').owner, owner); assert.equal(w.mounts.length, 3);
  });
  test('disabled and removed readers retire before their image/card is detached', async () => {
    const w = browser(); await w.start(); const removed = w.card(2), disabledImage = w.card(1).querySelector('img');
    await w.refresh([{id: 1, name: 'Disabled', enabled: false}]);
    assert.equal(w.active.size, 0); assert.equal(w.card(1).querySelector('img'), null); assert.equal(w.card(1).getAttribute('aria-disabled'), 'true');
    for (const removal of w.removals.filter(item => item.element === removed || item.element === disabledImage)) assert.equal(removal.owners.includes(removal.element === removed ? 'grid-2' : 'grid-1'), false);
    const card = w.card(1); await w.refresh([{id: 1, enabled: true, online: false}]);
    assert.equal(w.card(1), card); assert.equal(w.mounts.length, 3); assert.equal(w.active.size, 1);
  });
  test('small layouts share peers and intended quality remains small after main fallback', async () => {
    const w = browser(); await w.start(); const one = w.card(1), owner = w.active.get('grid-1').owner;
    w.active.get('grid-1').quality = 'main'; w.active.get('grid-1').qualityFallbackReason = 'SMALL_NOT_VALIDATED';
    w.layouts[2].dispatchEvent(new Event('click')); await w.refresh(); assert.equal(w.mounts.length, 2); assert.equal(w.active.get('grid-1').owner, owner);
    w.layouts[0].dispatchEvent(new Event('click')); assert.equal(w.mounts.length, 4); assert.equal(w.card(1), one);
    assert.deepEqual(w.mounts.slice(-2).map(entry => entry.quality), ['main','main']);
  });
  test('modal is main, metadata updates preserve its peer and invalidation closes it', async () => {
    const w = browser(); await w.start(); w.card(1).dispatchEvent(new Event('click'));
    const modalOwner = w.active.get('grid-modal').owner; assert.equal(w.active.has('grid-1'), false); assert.equal(w.active.get('grid-modal').quality, 'main');
    await w.refresh([{id: 1, name: 'New modal title', zone_name: 'Counter', enabled: true}, {id: 2, enabled: true}]);
    assert.equal(w.active.get('grid-modal').owner, modalOwner); assert.equal(w.ids.get('#v4CameraModalTitle').textContent, 'New modal title');
    assert.match(w.ids.get('#v4CameraModalMeta').textContent, /Counter/);
    await w.refresh([{id: 1, enabled: false}, {id: 2, enabled: true}]);
    assert.equal(w.active.has('grid-modal'), false); assert.equal(w.ids.get('#v4CameraModal').classList.contains('hidden'), true);
  });
  test('deleting the selected modal retires its owner and preserves other grid owners', async () => {
    const w = browser(); await w.start(); const other = w.active.get('grid-2').owner; w.card(1).dispatchEvent(new Event('click'));
    await w.refresh([{id: 2, enabled: true}]); assert.equal(w.active.has('grid-modal'), false); assert.equal(w.active.get('grid-2').owner, other);
  });
  test('stale detached card events cannot reopen modal after logout or disable', async () => {
    const w = browser(); await w.start(); const card = w.card(1); await w.refresh([{id: 1, enabled: false}]);
    card.dispatchEvent(new Event('click')); assert.equal(w.active.has('grid-modal'), false);
    w.auth(false); card.dispatchEvent(new Event('click')); assert.equal(w.active.size, 0);
  });
  test('keyed cards support keyboard activation without duplicating handlers', async () => {
    const w = browser(); await w.start(); await w.refresh(); const event = new Event('keydown', {cancelable: true}); event.key = ' ';
    w.card(1).dispatchEvent(event); assert.equal(event.defaultPrevented, true); assert.equal(w.mounts.filter(entry => entry.key === 'grid-modal').length, 1);
  });
  test('registry response cannot revive a removed tile from an older request', async () => {
    const w = browser({holdFleet: true}); await w.start(); const old = w.fleetRequests()[0];
    w.event('btmh:camera-registry-changed'); await flush(); const latest = w.fleetRequests()[1];
    latest.finish({items: [{id: 2, enabled: true}]}); await flush(); old.finish({items: [{id: 1, enabled: true}]}); await flush();
    assert.deepEqual(w.cards().map(card => Number(card.dataset.cameraId)), [2]); assert.equal(old.init.signal.aborted, true);
  });
  test('fleet is single flight; late finally cannot clear a newer request owner', async () => {
    const w = browser({holdFleet: true}); await w.start(); void w.api.loadFleet(); await flush(); assert.equal(w.fleetRequests().length, 1);
    const old = w.fleetRequests()[0]; w.navigate('dashboard'); w.navigate('live-grid'); await flush(); const latest = w.fleetRequests()[1];
    old.finish({items: [{id: 99, enabled: true}]}); await flush(); void w.api.loadFleet(); await flush();
    assert.equal(w.fleetRequests().length, 2); latest.finish({items: [{id: 2, enabled: true}]}); await flush();
    assert.equal(w.card(99), undefined); assert.ok(w.card(2));
  });
  for (const [name, stop] of [['hidden', w => w.visibility(true)], ['logout', w => w.auth(false)], ['pagehide', w => w.event('pagehide', undefined, w.window)]]) {
    test(`${name} cancels pending fleet and ignores stale success/error rendering`, async () => {
      const w = browser({holdFleet: true}); await w.start(); const request = w.fleetRequests()[0]; stop(w); await flush();
      request.fail('rtsp://private:secret@camera.test/source'); await flush(); assert.equal(request.init.signal.aborted, true);
      assert.equal(w.mounts.length, 0); assert.doesNotMatch(w.host.textContent, /private|secret|rtsp/);
    });
  }
  test('fleet failure retires all media before displaying a fixed error', async () => {
    const w = browser(); await w.start(); w.rejectFleet = 'rtsp://private:secret@camera.test/source'; await w.refresh();
    assert.equal(w.active.size, 0); assert.equal(w.cards().length, 0); assert.doesNotMatch(w.host.textContent, /private|secret|rtsp/);
  });
  test('source request/error ownership is canceled across authentication generations', async () => {
    const w = browser({page: 'dashboard', holdSources: true}); await w.start(); const old = w.sourceRequests()[0];
    w.auth(false); w.auth(true); await flush(); const latest = w.sourceRequests()[1];
    old.fail('private-source-error'); await flush(); void w.api.loadSources(); await flush(); assert.equal(w.sourceRequests().length, 2);
    assert.equal(w.note.textContent, ''); latest.finish({items: []}); await flush(); assert.match(w.note.textContent, /Chưa khai báo/);
  });
  test('JPEG fallback also preserves polling owner and retires before removal', async () => {
    const w = browser({noMedia: true}); await w.start(); const card = w.card(1), image = card.querySelector('img'), owner = w.previews.get(image).owner;
    await w.refresh(); assert.equal(w.previews.get(image).owner, owner); await w.refresh([{id: 2, enabled: true}]);
    const removal = w.removals.find(item => item.element === card); assert.equal(removal.previews.includes(image), false);
  });
  test('duplicate/invalid registry IDs create no duplicate camera owners', async () => {
    const w = browser({fleetItems: [{id: 1, enabled: true}, {id: 1, enabled: true}, {id: -1, enabled: true}, {id: 'bad', enabled: true}]}); await w.start();
    assert.equal(w.mounts.length, 1); assert.equal(w.cards().length, 1);
  });
  test('enrollment permission and visible registration page gate browser camera work', async () => {
    for (const options of [{page: 'dashboard'}, {page: 'register', hidden: true}, {page: 'register', enrollmentAllowed: false}]) {
      const w = browser(options); await w.start(); assert.equal(await w.api.startEnrollmentBrowserCamera(), false); assert.equal(w.gumRequests.length, 0);
    }
  });
  test('getUserMedia is single flight within its generation and attaches one stream', async () => {
    const w = browser({page: 'register'}); await w.start(); const first = w.api.startEnrollmentBrowserCamera(), same = w.api.startEnrollmentBrowserCamera();
    assert.equal(first, same); assert.equal(w.gumRequests.length, 1); const stream = w.stream('current'); w.gumRequests[0].resolve(stream);
    assert.equal(await first, true); assert.equal(w.ids.get('#enrollVideo').srcObject, stream);
    assert.equal(await w.api.startEnrollmentBrowserCamera(), true); assert.equal(w.gumRequests.length, 1);
  });
  test('late permission stream is stopped locally and cannot attach or stop a new owner', async () => {
    const w = browser({page: 'register'}); await w.start(); const oldResult = w.api.startEnrollmentBrowserCamera();
    w.api.stopEnrollmentBrowserCamera(); const nextResult = w.api.startEnrollmentBrowserCamera(); const old = w.stream('old'), current = w.stream('current');
    w.gumRequests[1].resolve(current); assert.equal(await nextResult, true); w.gumRequests[0].resolve(old); assert.equal(await oldResult, false);
    assert.equal(old.tracks[0].stops, 1); assert.equal(current.tracks[0].stops, 0); assert.equal(w.ids.get('#enrollVideo').srcObject, current);
  });
  test('late webcam failure cannot clear a new pending permission owner', async () => {
    const w = browser({page: 'register'}); await w.start(); const oldResult = w.api.startEnrollmentBrowserCamera();
    w.api.stopEnrollmentBrowserCamera(); const nextResult = w.api.startEnrollmentBrowserCamera(); w.gumRequests[0].reject(new Error('permission denied'));
    assert.equal(await oldResult, false); assert.equal(w.api.startEnrollmentBrowserCamera(), nextResult); assert.equal(w.gumRequests.length, 2);
    w.gumRequests[1].resolve(w.stream('current')); assert.equal(await nextResult, true);
  });
  for (const [name, stop] of [['hidden', w => w.visibility(true)], ['navigation', w => w.navigate('dashboard')], ['logout', w => w.auth(false)], ['pagehide', w => w.event('pagehide', undefined, w.window)]]) {
    test(`${name} invalidates an unresolved webcam permission request`, async () => {
      const w = browser({page: 'register'}); await w.start(); const result = w.api.startEnrollmentBrowserCamera(), stream = w.stream('stale');
      stop(w); w.gumRequests[0].resolve(stream); assert.equal(await result, false); assert.equal(stream.tracks[0].stops, 1); assert.equal(w.ids.get('#enrollVideo').srcObject, null);
    });
  }
  test('BFCache pagehide prevents visible resumption until pageshow, then one owner resumes', async () => {
    const w = browser({page: 'register'}); await w.start(); const stream = w.stream('first'); w.gumRequests[0].resolve(stream); await flush();
    w.event('pagehide', undefined, w.window); w.visibility(false); await flush(); assert.equal(w.gumRequests.length, 1); assert.equal(stream.tracks[0].stops, 1);
    w.event('pageshow', undefined, w.window); await flush(); assert.equal(w.gumRequests.length, 2); w.visibility(false); await flush(); assert.equal(w.gumRequests.length, 2);
  });
  test('repeated refresh/navigation and duplicate initialization keep handlers/resources bounded', async () => {
    const w = browser(); await w.start(); w.run(); w.event('DOMContentLoaded'); assert.equal(w.intervals.size, 1);
    for (let i = 0; i < 20; i++) { await w.refresh(); w.navigate('dashboard'); w.navigate('live-grid'); await flush(); }
    assert.equal(w.cards().length, 2); assert.equal(w.active.size, 2); assert.equal(w.intervals.size, 1);
    w.auth(false); assert.equal(w.active.size, 0); assert.equal(w.cards().length, 0);
  });
  test('auth refresh retires old media while its fresh fleet owner is pending', async () => {
    const w=browser();await w.start();const card=w.card(1);w.holdFleet=true;w.auth(true);await flush();
    assert.equal(w.active.size,0);card.dispatchEvent(new Event('click'));assert.equal(w.active.has('grid-modal'),false);
    w.fleetRequests().at(-1).finish();await flush();assert.equal(w.active.size,2);
    w.cameraAllowed=false;w.auth(true);await flush();assert.equal(w.active.size,0);card.dispatchEvent(new Event('click'));assert.equal(w.active.size,0);
  });
  test('fleet error detaches cards whose stale clicks cannot create a modal', async () => {
    const w=browser();await w.start();const card=w.card(1);w.rejectFleet='offline';await w.refresh();card.dispatchEvent(new Event('click'));assert.equal(w.active.size,0);
  });
  test('pagehide suppresses the visible operations interval until pageshow', async () => {
    const w=browser({page:'operations'});await w.start();w.event('pagehide',undefined,w.window);w.intervals.values().next().value.fn();await flush();
    assert.equal(w.requests.filter(request=>request.url.includes('/presence/')).length,0);
    w.event('pageshow',undefined,w.window);w.intervals.values().next().value.fn();await flush();assert.equal(w.requests.filter(request=>request.url.includes('/presence/')).length,1);
  });
  test('presence permission gate and same-generation single flight bound polling', async () => {
    const denied=browser({page:'operations',presenceAllowed:false});await denied.start();await denied.api.loadPresence();assert.equal(denied.requests.some(request=>request.url.includes('/presence/')),false);
    const w=browser({page:'operations',holdPresence:true});await w.start();void w.api.loadPresence();void w.api.loadPresence();await flush();assert.equal(w.requests.filter(request=>request.url.includes('/presence/')).length,1);
    w.requests.find(request=>request.url.includes('/presence/')).finish({items:[{full_name:'Current'}],employee_total:3});await flush();assert.match(w.ids.get('#v4PresenceList').textContent,/Current/);
  });
  for(const [name,stop]of[['navigation',w=>w.navigate('dashboard')],['logout',w=>w.auth(false)],['hidden',w=>w.visibility(true)],['pagehide',w=>w.event('pagehide',undefined,w.window)]]){
    test(`late presence success/error is ignored after ${name}`,async()=>{
      const w=browser({page:'operations',holdPresence:true});await w.start();void w.api.loadPresence();await flush();const request=w.requests.find(request=>request.url.includes('/presence/'));stop(w);
      request.finish({items:[{full_name:'Stale'}],employee_total:1});await flush();assert.equal(request.init.signal.aborted,true);assert.doesNotMatch(w.ids.get('#v4PresenceList').textContent,/Stale/);
      w.navigate('operations');if(name==='logout')w.auth(true);if(name==='hidden')w.visibility(false);if(name==='pagehide')w.event('pageshow',undefined,w.window);void w.api.loadPresence();await flush();
      const next=w.requests.filter(request=>request.url.includes('/presence/')).at(-1);w.navigate('dashboard');next.fail('rtsp://secret@private');await flush();assert.doesNotMatch(w.ids.get('#v4PresenceList').textContent,/secret|private/);
    });
  }
  test('presence late finally cannot clear the new current owner',async()=>{
    const w=browser({page:'operations',holdPresence:true});await w.start();void w.api.loadPresence();await flush();const old=w.requests.find(request=>request.url.includes('/presence/'));
    w.navigate('dashboard');w.navigate('operations');void w.api.loadPresence();await flush();const latest=w.requests.filter(request=>request.url.includes('/presence/')).at(-1);
    old.fail('old');await flush();void w.api.loadPresence();await flush();assert.equal(w.requests.filter(request=>request.url.includes('/presence/')).length,2);
    latest.finish({items:[]});await flush();assert.match(w.ids.get('#v4PresenceList').textContent,/Chưa ghi nhận/);
  });
  const search=async w=>{w.ids.get('#v4PlaybackCamera').value='camera-1';w.ids.get('#v4PlaybackDate').value='2026-10-07';w.ids.get('#v4PlaybackSearch').dispatchEvent(new Event('click'));await flush();};
  const segment={segment_id:'valid',media_uri:'/api/v1/recordings/media?segment=valid',start_at:'2026-10-07T00:00:00Z',end_at:'2026-10-07T00:01:00Z'};
  for(const [name,stop]of[['navigation',w=>w.navigate('dashboard')],['logout',w=>w.auth(false)],['hidden',w=>w.visibility(true)],['pagehide',w=>w.event('pagehide',undefined,w.window)]]){
    test(`late playback search cannot render after ${name}`,async()=>{
      const w=browser({page:'playback',holdPlayback:true});await w.start();await search(w);const request=w.requests.find(request=>request.url.includes('/recordings/segments'));stop(w);request.finish({items:[segment]});await flush();
      assert.equal(request.init.signal.aborted,true);assert.equal(w.ids.get('#v4PlaybackResults').children.length,0);assert.equal(w.ids.get('#v4PlaybackVideo').src||'', '');
    });
  }
  test('new playback search cancels old owner and its late result cannot replace current rows',async()=>{
    const w=browser({page:'playback',holdPlayback:true});await w.start();await search(w);const old=w.requests.find(request=>request.url.includes('/recordings/segments'));await search(w);const latest=w.requests.filter(request=>request.url.includes('/recordings/segments')).at(-1);
    latest.finish({items:[segment]});await flush();const button=w.ids.get('#v4PlaybackResults').children[0];old.fail('secret-source');await flush();assert.equal(old.init.signal.aborted,true);assert.equal(w.ids.get('#v4PlaybackResults').children[0],button);
    button.dispatchEvent(new Event('click'));assert.equal(w.ids.get('#v4PlaybackVideo').src,segment.media_uri);
  });
  test('segment click checks playback permission, page and rendered generation before attach',async()=>{
    const w=browser({page:'playback',playbackItems:[segment]});await w.start();await search(w);const button=w.ids.get('#v4PlaybackResults').children[0];
    w.playbackAllowed=false;button.dispatchEvent(new Event('click'));assert.equal(w.ids.get('#v4PlaybackVideo').src||'','');w.playbackAllowed=true;button.dispatchEvent(new Event('click'));assert.equal(w.ids.get('#v4PlaybackVideo').src,segment.media_uri);
    w.navigate('dashboard');button.dispatchEvent(new Event('click'));assert.equal(w.ids.get('#v4PlaybackVideo').src||'','');
    w.navigate('playback');w.holdPlayback=true;await search(w);button.dispatchEvent(new Event('click'));assert.equal(w.ids.get('#v4PlaybackVideo').src||'','');
  });
  test('playback search is permission gated and active errors use a fixed message',async()=>{
    const w=browser({page:'playback',holdPlayback:true,playbackAllowed:false});await w.start();await search(w);assert.equal(w.requests.some(request=>request.url.includes('/recordings/segments')),false);
    w.playbackAllowed=true;await search(w);w.requests.find(request=>request.url.includes('/recordings/segments')).fail('rtsp://secret@private');await flush();assert.match(w.ids.get('#v4PlaybackResults').textContent,/Không tải được/);assert.doesNotMatch(w.ids.get('#v4PlaybackResults').textContent,/secret|private/);
  });
}

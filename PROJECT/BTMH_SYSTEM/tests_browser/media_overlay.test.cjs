'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Reuse the deterministic transport adapter without registering its test suite.
const adapter = fs.readFileSync(path.join(__dirname, 'media_lifecycle.test.cjs'), 'utf8').split("\ntest('native video is authenticated")[0];
const sandbox = {module: {exports: {}}, require, __dirname, console, EventTarget, Event, CustomEvent,
  DOMException, AbortController, URL, Blob, queueMicrotask};
vm.runInNewContext(adapter + '\nmodule.exports = {browser, flush};', sandbox);
const {browser, flush} = sandbox.module.exports;
const plain = value => JSON.parse(JSON.stringify(value));

test('xywh box at the right edge remains visible instead of being rejected as xyxy', () => {
  const geometry = browser().api.geometry;
  assert.deepEqual(plain(geometry.mapOverlayBox(640, 360, 640, 360, [512, 80, 100, 120])), {x: 512, y: 80, w: 100, h: 120});
});

test('contain mapping includes letterbox offsets for portrait and landscape layouts', () => {
  const geometry = browser().api.geometry;
  assert.deepEqual(plain(geometry.mapOverlayBox(640, 480, 1280, 720, [100, 40, 200, 120])), {x: 50, y: 80, w: 100, h: 60});
  assert.deepEqual(plain(geometry.mapOverlayBox(360, 640, 1280, 720, [640, 360, 128, 72])), {x: 180, y: 320, w: 36, h: 20.25});
});

test('fullscreen, cover and mirrored layouts use the same source coordinate contract', () => {
  const geometry = browser().api.geometry;
  assert.deepEqual(plain(geometry.mapOverlayBox(1920, 1080, 640, 360, [100, 40, 200, 120])), {x: 300, y: 120, w: 600, h: 360});
  assert.deepEqual(plain(geometry.mapOverlayBox(640, 360, 640, 360, [100, 40, 200, 120], 'xywh', true)), {x: 340, y: 40, w: 200, h: 120});
  const rect = geometry.fitRect(640, 480, 1280, 720, 'cover');
  assert.equal(rect.h, 480);
  assert.ok(rect.x < 0);
});

test('explicit legacy xyxy, clipping and invalid source/box dimensions are handled', () => {
  const geometry = browser().api.geometry;
  assert.deepEqual(plain(geometry.mapOverlayBox(640, 360, 640, 360, [100, 40, 300, 160], 'xyxy')), {x: 100, y: 40, w: 200, h: 120});
  assert.deepEqual(plain(geometry.mapOverlayBox(640, 360, 640, 360, [-10, -20, 30, 40])), {x: 0, y: 0, w: 20, h: 20});
  for (const box of [[10, 10, -1, 5], [10, 10, 0, 5], [NaN, 10, 20, 20], [700, 10, 20, 20]])
    assert.equal(geometry.mapOverlayBox(640, 360, 640, 360, box), null);
  assert.equal(geometry.mapOverlayBox(640, 360, 0, 360, [10, 10, 20, 20]), null);
});

test('metadata socket is scoped; mismatched camera metadata does not paint or publish identity', async () => {
  const w = browser();
  const elements = w.elements();
  const overlay = w.document.createElement('canvas');
  elements.wrap.prepend(overlay);
  let paints = 0;
  const ctx = overlay.getContext(); ctx.strokeRect = () => paints++;
  overlay.getContext = () => ctx;
  const metadata = [];
  w.document.addEventListener('btmh:media-metadata', e => metadata.push(e.detail));
  w.api.mount('recognition-slot-0', {...elements, overlay, cameraId: 11});
  await flush();
  const socket = w.sockets.find(s => s.url.includes('/metadata/ws'));
  assert.ok(socket.url.endsWith('?camera_id=11'));
  socket.onmessage({data: JSON.stringify({camera_id: 12, frame_width: 640, frame_height: 360, tracks: [{bbox: [512, 80, 100, 120], recognized: true}]})});
  await w.advance(20);
  assert.equal(paints, 0); assert.equal(metadata.length, 0);
  socket.onmessage({data: JSON.stringify({camera_id: 11, sent_at: 1700000000, updated_at: 1700000000, bbox_format: 'xywh', frame_width: 640, frame_height: 360, tracks: [{bbox: [512, 80, 100, 120], recognized: true}]})});
  await w.advance(20);
  assert.equal(paints, 1); assert.equal(metadata.length, 1);
  await w.clean();
});

test('resize/fullscreen repaint is coalesced and stop cancels pending redraw', async () => {
  const w = browser(), elements = w.elements(), overlay = w.document.createElement('canvas');
  const boxes = []; const ctx = overlay.getContext(); ctx.strokeRect = (...args) => boxes.push(args); overlay.getContext = () => ctx;
  elements.wrap.prepend(overlay);
  w.api.mount('recognition-slot-0', {...elements, overlay, cameraId: 1}); await flush();
  const socket = w.sockets.find(s => s.url.includes('/metadata/ws'));
  socket.onmessage({data: JSON.stringify({camera_id: 1, sent_at: 1700000000, updated_at: 1700000000, bbox_format: 'xywh', frame_width: 640, frame_height: 360, tracks: [{bbox: [100, 40, 200, 120]}]})});
  await w.advance(20);
  elements.wrap.clientWidth = 1280; elements.wrap.clientHeight = 720;
  w.window.dispatchEvent(new Event('resize')); w.document.dispatchEvent(new Event('fullscreenchange'));
  await w.advance(20);
  assert.equal(boxes.length, 2); assert.deepEqual(boxes[1], [200, 80, 400, 240]);
  w.window.dispatchEvent(new Event('resize'));
  w.api.stopAll(); await w.advance(20);
  assert.equal(boxes.length, 2);
  w.window.dispatchEvent(new Event('resize')); w.document.dispatchEvent(new Event('fullscreenchange'));
  assert.equal(w.timers.size, 0);
  await w.clean();
});

test('late metadata from a replaced owner cannot restore boxes after a slot switch', async () => {
  const w = browser(), elements = w.elements(), overlay = w.document.createElement('canvas');
  elements.wrap.prepend(overlay);
  const received = []; w.document.addEventListener('btmh:media-metadata', e => received.push(e.detail.cameraId));
  w.api.mount('recognition-slot-0', {...elements, overlay, cameraId: 1}); await flush();
  const old = w.sockets.find(s => s.url.endsWith('?camera_id=1')), late = old.onmessage;
  w.api.mount('recognition-slot-0', {...elements, overlay, cameraId: 2}); await flush();
  late({data: JSON.stringify({camera_id: 1, tracks: []})});
  assert.deepEqual(received, []); assert.equal(old.readyState, 3);
  await w.clean();
});

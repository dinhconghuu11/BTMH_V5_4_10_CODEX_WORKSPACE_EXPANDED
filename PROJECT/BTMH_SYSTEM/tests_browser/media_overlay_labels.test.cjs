'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const adapter = fs.readFileSync(path.join(__dirname, 'media_lifecycle.test.cjs'), 'utf8').split("\ntest('native video is authenticated")[0];
const sandbox = {module: {exports: {}}, require, __dirname, console, EventTarget, Event, CustomEvent, DOMException, AbortController, URL, Blob, queueMicrotask};
vm.runInNewContext(adapter + '\nmodule.exports = {browser, flush};', sandbox);
const {browser, flush} = sandbox.module.exports;

async function paint(tracks, width = 640, height = 360) {
  const w = browser(), elements = w.elements(), overlay = w.document.createElement('canvas');
  elements.wrap.clientWidth = width; elements.wrap.clientHeight = height;
  const labels = [], boxes = [], backgrounds = [], ctx = overlay.getContext();
  ctx.measureText = value => ({width: String(value).length * 7});
  ctx.strokeRect = (...args) => boxes.push({args, color: ctx.strokeStyle});
  ctx.fillText = (...args) => labels.push(args);
  ctx.fillRect = (...args) => backgrounds.push(args);
  overlay.getContext = () => ctx; elements.wrap.prepend(overlay);
  w.api.mount('recognition-slot-0', {...elements, overlay, cameraId: 1}); await flush();
  w.sockets.find(socket => socket.url.includes('/metadata/ws')).onmessage({data: JSON.stringify({camera_id: 1, sent_at: 1700000000, updated_at: 1700000000, bbox_format: 'xywh', frame_width: 640, frame_height: 360, tracks})});
  await w.advance(20); await w.clean(); return {labels, boxes, backgrounds};
}

test('multiple physical tracks paint separate server sequence/name/state labels and truthful colors', async () => {
  const result = await paint([
    {bbox: [20, 90, 80, 100], daily_sequence: 7, track_id: 'private-111', recognized: true, full_name: 'Nhân viên A', status: 'RECOGNIZED'},
    {bbox: [220, 90, 80, 100], daily_sequence: 8, track_id: 'private-222', identity_verified: true, recognized: false, full_name: 'Candidate B', status: 'VERIFYING_PASSIVE'},
    {bbox: [420, 90, 80, 100], daily_sequence: 9, track_id: 'private-333', unregistered: true, full_name: 'Private visitor name', status: 'UNREGISTERED'}
  ]);
  assert.deepEqual(result.labels.map(args => args[0]), ['#0007', 'Nhân viên A', 'Đã xác minh', '#0008', 'Đang kiểm tra', '#0009', 'Chưa xác định']);
  assert.deepEqual(result.boxes.map(box => box.color), ['#44d397', '#e4b451', '#f16a75']);
  assert.equal(result.boxes.length, 3);
  assert.equal(result.labels.some(args => /private|Candidate|visitor/.test(args[0])), false);
});

test('spoof/unknown cannot expose a remembered verified identity and identity-only candidate stays pending', async () => {
  const result = await paint([
    {bbox: [10, 90, 80, 100], daily_sequence: 12, recognized: true, spoof_blocked: true, full_name: 'Remembered employee'},
    {bbox: [210, 90, 80, 100], daily_sequence: 13, recognized: true, status: 'UNREGISTERED', full_name: 'Contradictory candidate'},
    {bbox: [410, 90, 80, 100], daily_sequence: 14, identity_verified: true, recognized: false, status: 'CHECKING', full_name: 'Identity before PAD'}
  ]);
  assert.deepEqual(result.labels.map(args => args[0]), ['#0012', 'Chưa xác định', '#0013', 'Chưa xác định', '#0014', 'Đang kiểm tra']);
  assert.deepEqual(result.boxes.map(box => box.color), ['#f16a75', '#f16a75', '#e4b451']);
});

test('missing/invalid sequence is omitted without using raw track/event IDs or invented row numbers', async () => {
  for (const daily_sequence of [undefined, null, 0, -1, 1.25, true, '12', 'not-a-number', Number.MAX_SAFE_INTEGER + 1]) {
    const result = await paint([{bbox: [40, 90, 80, 100], daily_sequence, track_id: 9381, event_id: 8890, recognized: true, full_name: 'Tên đã xác minh'}]);
    assert.deepEqual(result.labels.map(args => args[0]), ['Tên đã xác minh', 'Đã xác minh']);
  }
});

test('three-line label for a long verified name stays inside a small video without changing bbox mapping', async () => {
  const result = await paint([{bbox: [512, 4, 100, 120], daily_sequence: 12345, recognized: true, full_name: 'Tên nhân viên rất dài để kiểm tra giới hạn khung chữ'}], 320, 180);
  assert.deepEqual(result.boxes[0].args, [256, 2, 50, 60]);
  assert.equal(result.labels[0][0], '#12345');
  for (const [x, y, width, height] of result.backgrounds) { assert.ok(x >= 4); assert.ok(y >= 4); assert.ok(x + width <= 316); assert.ok(y + height <= 176); }
});

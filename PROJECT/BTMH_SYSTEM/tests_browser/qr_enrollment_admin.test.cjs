'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_qr_enrollment_admin.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
const prefix = '/api/v1/admin/face-enrollment', initialTime = Date.parse('2026-10-08T03:00:00Z');
const rid = number => number.toString(16).padStart(32, '0');
const row = (number = 1, extra = {}) => ({id: rid(number), student_id: 17, store_id: 2, store_name: 'Cửa hàng thử', full_name: 'Nguyễn An', student_code: 'NV17', source_kind: 'QR_MOBILE', status: 'PENDING_REVIEW', revision: 4, consent_status: 'GRANTED', quality: {ready: true, scan_passes: 2}, pad: {status: 'PASS'}, duplicate: {}, has_preview: false, created_at: new Date(initialTime - 1000).toISOString(), expires_at: new Date(initialTime + 3600000).toISOString(), ...extra});
function browser(config = {}) {
  const w = {now: initialTime, requests: [], previewRequests: [], pending: [], previewsPending: [], items: [row()], stores: [{id: 2, store_name: 'Cửa hàng thử', status: 'ACTIVE'}, {id: 3, store_name: 'Cửa hàng khác', status: 'ACTIVE'}], actor: {id: 1, role: 'ADMIN'}, permission: true, toasts: [], copied: [], urls: [], revoked: [], timers: new Map(), nextTimer: 0, actionResults: {}, ...config};
  const document = new EventTarget(); document.hidden = !!w.hidden; document.activeElement = null;
  const matches = (element, selector) => selector.split(',').some(part => {
    part = part.trim(); if (/^\w+$/.test(part)) return element.tagName === part.toUpperCase();
    const attr = part.match(/^\[data-([a-z-]+)(?:="([^"]*)")?\]$/); if (!attr) return false; const key = attr[1].replace(/-([a-z])/g, (_, character) => character.toUpperCase()); return attr[2] === undefined ? Object.hasOwn(element.dataset, key) : element.dataset[key] === attr[2];
  });
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.className = ''; this.hidden = false; this.disabled = false; this.checked = false; this.value = ''; this._text = ''; }
    set textContent(value) { this._text = String(value); this.replaceChildren(); }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    get classList() { return {contains: value => this.className.split(/\s+/).includes(value), toggle: (value, on) => { const names = new Set(this.className.split(/\s+/).filter(Boolean)); if (on ?? !names.has(value)) names.add(value); else names.delete(value); this.className = [...names].join(' '); }}; }
    append(...children) { for (const child of children) { child.remove(); child.parentElement = this; this.children.push(child); } }
    replaceChildren(...children) { for (const child of this.children) child.parentElement = null; this.children = []; this.append(...children); }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; }
    querySelectorAll(selector) { return this.children.flatMap(child => [...(matches(child, selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    focus() { document.activeElement = this; }
    select() { this.selected = true; }
  }
  document.createElement = tag => new Element(tag); const window = new EventTarget(), host = new Element('div');
  const api = async (url, init = {}) => {
    const request = {url, init}; w.requests.push(request);
    if (w.hold?.(url, init)) return new Promise((resolve, reject) => w.pending.push({...request, resolve, reject}));
    const error = w.error?.(url, init); if (error) throw error;
    if (url === '/api/v1/stores') return {items: w.stores};
    if (url.startsWith(prefix + '/requests?')) { const query = new URL('https://local.test' + url).searchParams; const matching = w.items.filter(item => Number(item.student_id) === Number(query.get('student_id')) && (!query.get('status') || item.status === query.get('status'))); const offset = Number(query.get('offset')); return {items: w.listItems || matching.slice(offset, offset + Number(query.get('limit'))), total: w.total ?? matching.length}; }
    if (url === prefix + '/invitations') { const result = w.invitationResult || invitation(row(90, {status: 'CAPTURING', quality: {}, pad: {}})); if (result?.request) w.items = [result.request, ...w.items]; return result; }
    const action = url.match(/\/requests\/([a-f0-9]{32})\/(approve|reject|cancel|reenroll)$/);
    if (action) { const item = w.items.find(item => item.id === action[1]); const next = row(action[2] === 'reenroll' ? 91 : parseInt(item.id, 16), {...item, id: action[2] === 'reenroll' ? rid(91) : item.id, status: {approve: 'APPROVED', reject: 'REJECTED', cancel: 'CANCELLED', reenroll: 'CAPTURING'}[action[2]], revision: item.revision + 1, has_preview: false}); const result = w.actionResults[action[2]] || (action[2] === 'reenroll' ? invitation(next) : {request: next}); if (w.actionResults[action[2]] === undefined) w.items = action[2] === 'reenroll' ? [next, {...item, status: 'REJECTED'}] : w.items.map(item => item.id === next.id ? next : item); if (w.afterAction) w.afterAction(action[2]); return result; }
    const selected = url.match(/\/requests\/([a-f0-9]{32})$/)?.[1]; return {request: w.details?.[selected] || w.items.find(item => item.id === selected)};
  };
  const getPreview = async (url, init) => { const request = {url, init}; w.previewRequests.push(request); if (w.holdPreview) return new Promise((resolve, reject) => w.previewsPending.push({...request, resolve, reject})); if (w.previewError) throw w.previewError; return w.blob || new Blob(['JPEG fixture'], {type: 'image/jpeg'}); };
  class BrowserURL extends URL { static createObjectURL(blob) { const url = 'blob:preview/' + (w.urls.length + 1); w.urls.push({url, blob}); return url; } static revokeObjectURL(url) { w.revoked.push(url); } }
  class ClockDate extends Date { constructor(...args) { super(...(args.length ? args : [w.now])); } static now() { return w.now; } }
  const storage = {getItem() { throw new Error('Unexpected storage read'); }, setItem() { throw new Error('Unexpected secret storage'); }};
  const navigator = {clipboard: {writeText: async value => { w.copied.push(value); if (w.copyError) throw new Error('Clipboard unavailable'); }}};
  const context = {window, document, location: {origin: w.origin || 'https://local.test'}, navigator, URL: BrowserURL, URLSearchParams, AbortController, DOMException, Date: ClockDate, localStorage: storage, sessionStorage: storage, setTimeout: (callback, delay) => { const id = ++w.nextTimer; w.timers.set(id, {callback, at: w.now + delay}); return id; }, clearTimeout: id => w.timers.delete(id)};
  vm.createContext(context); vm.runInContext(source, context); w.controller = window.BTMHQREnrollmentAdmin.mount(host, {student: w.student || {id: 17, full_name: 'Nguyễn An', student_code: 'NV17'}, api, getUser: () => w.actor, getPermission: () => w.permission, toast: text => w.toasts.push(text), getPreview});
  Object.assign(w, {host, document, window}); w.find = selector => host.querySelector(selector); w.all = selector => host.querySelectorAll(selector); w.action = name => w.find(`[data-qr-action="${name}"]`); w.decision = name => w.find(`[data-qr-decision="${name}"]`); w.field = name => w.find(`[data-qr-field="${name}"]`); w.click = element => element?.dispatchEvent(new Event('click')); w.fire = (type, target = document) => target.dispatchEvent(new Event(type));
  w.change = (name, value) => { const element = w.field(name); if (typeof value === 'boolean') element.checked = value; else element.value = value; element.dispatchEvent(new Event(name === 'reason' ? 'input' : 'change')); };
  w.writes = () => w.requests.filter(request => request.init.method === 'POST'); w.listCalls = () => w.requests.filter(request => request.url.startsWith(prefix + '/requests?')); w.note = () => host.children[0]?.children.find(element => element.className.includes('qr-enrollment-note'))?.textContent || '';
  w.advance = async ms => { w.now += ms; const due = [...w.timers.entries()].filter(([, timer]) => timer.at <= w.now).sort((a, b) => a[1].at - b[1].at); for (const [id, timer] of due) if (w.timers.delete(id)) timer.callback(); await flush(); };
  return w;
}
function invitation(item, extra = {}) { return {request: item, qr_url: 'https://local.test/enroll#invite=' + 'A'.repeat(43), qr_data_url: 'data:image/png;base64,AA==', invite_expires_at: new Date(initialTime + 900000).toISOString(), capture_https_ready: true, ...extra}; }
async function ready(config = {}) { const w = browser(config); await flush(); return w; }

test('loads only selected employee with explicit server filter/pagination and safe wrapper detail', async () => {
  const w = await ready({items: [row(), row(2, {student_id: 99})]}); const query = new URL('https://local.test' + w.listCalls()[0].url).searchParams; assert.equal(query.get('student_id'), '17'); assert.equal(query.get('limit'), '20'); assert.equal(query.get('offset'), '0'); assert.equal(w.all('[data-qr-request]').length, 1); assert.equal(w.requests.some(request => request.url === prefix + '/requests/' + rid(1)), true); assert.match(w.host.textContent, /Đủ hai vòng.*Đã qua xác minh/); assert.equal(w.writes().length, 0);
});
test('rejects wrong employee or malformed request rows before loading details', async () => {
  const w = await ready({listItems: [row(1, {student_id: 99}), row(2, {id: 'invalid'}), row(3, {status: 'PRIVATE_STATUS'})]}); assert.equal(w.all('[data-qr-request]').length, 0); assert.equal(w.requests.some(request => /\/requests\/[a-f0-9]+$/.test(request.url)), false); assert.match(w.host.textContent, /Chưa có yêu cầu/);
});
test('filter and next/previous send canonical server query instead of browser-only trimming', async () => {
  const w = await ready({items: Array.from({length: 25}, (_, index) => row(index + 1))}); assert.equal(w.all('[data-qr-request]').length, 20); assert.equal(w.action('next').disabled, false); w.click(w.action('next')); await flush(); assert.equal(new URL('https://local.test' + w.listCalls().at(-1).url).searchParams.get('offset'), '20'); assert.equal(w.all('[data-qr-request]').length, 5); w.click(w.action('previous')); await flush(); assert.equal(new URL('https://local.test' + w.listCalls().at(-1).url).searchParams.get('offset'), '0'); w.change('status', 'REJECTED'); await flush(); const query = new URL('https://local.test' + w.listCalls().at(-1).url).searchParams; assert.equal(query.get('status'), 'REJECTED'); assert.equal(query.get('offset'), '0'); assert.equal(w.all('[data-qr-request]').length, 0);
});
test('issue requires an explicit active store and is one-flight through its refresh', async () => {
  const w = await ready({hold: (url, init) => init.method === 'POST'}); assert.equal(w.field('store').value, ''); assert.equal(w.action('issue').disabled, true); w.click(w.action('issue')); await flush(); assert.equal(w.writes().length, 0); w.change('store', '2'); w.click(w.action('issue')); w.click(w.action('issue')); await flush(); assert.equal(w.writes().length, 1); assert.deepEqual(JSON.parse(w.writes()[0].init.body), {student_id: 17, store_id: 2}); const created = row(90, {status: 'CAPTURING'}); w.items = [created]; w.hold = url => url.startsWith(prefix + '/requests?'); w.pending[0].resolve(invitation(created)); await flush(); w.click(w.action('issue')); await flush(); assert.equal(w.writes().length, 1); assert.equal(w.action('issue').disabled, true); w.pending[1].resolve({items: w.items, total: 1}); await flush(); assert.equal(w.action('issue').disabled, false);
});
test('inactive/unavailable stores never silently choose another store or enable issue', async () => {
  const w = await ready({stores: [{id: 8, store_name: 'Closed', status: 'INACTIVE'}]}); w.change('store', '8'); assert.equal(w.action('issue').disabled, true); w.click(w.action('issue')); await flush(); assert.equal(w.writes().length, 0);
  const f = await ready({error: url => url === '/api/v1/stores' ? new Error('offline') : null}); assert.equal(f.action('issue').disabled, true); assert.match(f.note(), /Chưa tải được cửa hàng/); f.error = null; await f.controller.refresh(); await flush(); f.change('store', '2'); assert.equal(f.action('issue').disabled, false);
});
test('approve requires revision, consent, two passes and PAD PASS plus a decision reason', async () => {
  for (const extra of [{revision: null}, {revision: -1}, {revision: true}, {consent_status: 'NOT_GRANTED'}, {quality: {ready: false, scan_passes: 2}}, {quality: {ready: true, scan_passes: 1}}, {pad: {status: 'CHECKING'}}]) { const w = await ready({items: [row(1, extra)]}); w.change('reason', 'Đã kiểm tra'); assert.equal(w.decision('approve').disabled, true); w.click(w.decision('approve')); await flush(); assert.equal(w.writes().length, 0); }
  const w = await ready(); for (const reason of ['', 'x'.repeat(501), 'unsafe\nreason']) { w.change('reason', reason); w.click(w.decision('approve')); await flush(); assert.equal(w.writes().length, 0); } w.change('reason', 'Đã kiểm tra nhân viên'); w.click(w.decision('approve')); await flush(); assert.deepEqual(JSON.parse(w.writes()[0].init.body), {expected_revision: 4, reason: 'Đã kiểm tra nhân viên', duplicate_override: false}); assert.match(w.toasts[0], /đã được duyệt và kích hoạt/);
});
test('duplicate override is explicit and appears only on the approval decision', async () => {
  const w = await ready({items: [row(1, {status: 'NEEDS_DUPLICATE_REVIEW', duplicate: {student_id: 9, full_name: 'Hồ sơ trùng', student_code: 'NV9'}})]}); w.change('reason', 'Đã đối chiếu hồ sơ'); assert.equal(w.decision('approve').disabled, true); w.change('override', true); assert.equal(w.decision('approve').disabled, false); w.click(w.decision('approve')); await flush(); assert.equal(JSON.parse(w.writes()[0].init.body).duplicate_override, true);
  for (const action of ['reject', 'reenroll']) { const p = await ready({items: [row(1, {duplicate: {student_id: 9}})]}); p.change('reason', 'Cần thu mẫu lại'); p.change('override', true); p.click(p.decision(action)); await flush(); assert.deepEqual(Object.keys(JSON.parse(p.writes()[0].init.body)).sort(), ['expected_revision', 'reason']); assert.equal(p.writes().some(request => request.url.endsWith('/approve')), false); }
});
test('decision is one-flight while the result refresh remains pending', async () => {
  const w = await ready({hold: (url, init) => init.method === 'POST'}); w.change('reason', 'Đã kiểm tra'); w.click(w.decision('approve')); w.click(w.decision('reject')); await flush(); assert.equal(w.writes().length, 1); assert.equal(w.field('reason').disabled, true); w.items = [row(1, {status: 'APPROVED'})]; w.hold = url => url.startsWith(prefix + '/requests?'); w.pending[0].resolve({request: w.items[0]}); await flush(); w.click(w.decision('approve')); w.click(w.decision('reject')); await flush(); assert.equal(w.writes().length, 1); assert.equal(w.action('issue').disabled, true); w.pending[1].resolve({items: w.items, total: 1}); await flush(); assert.equal(w.decision('approve'), null);
});
test('revision conflict reloads canonical detail and clears old reason/override before retry', async () => {
  const w = await ready({error: (url, init) => init.method === 'POST' ? {status: 409} : null}); w.change('reason', 'Old decision'); w.details = {[rid(1)]: row(1, {revision: 5, duplicate: {student_id: 9}})}; w.click(w.decision('approve')); await flush(); assert.equal(w.field('reason').value, ''); assert.equal(w.field('override').checked, false); assert.equal(w.decision('approve').disabled, true); assert.match(w.note(), /Hồ sơ đã thay đổi/); assert.equal(w.toasts.length, 0);
});
test('an action cannot claim success for a contradictory or different server state', async () => {
  for (const action of ['approve', 'reject', 'reenroll']) { const wrong = action === 'reenroll' ? row(1, {status: 'CAPTURING'}) : row(2, {status: action === 'approve' ? 'APPROVED' : 'REJECTED'}); const w = await ready({actionResults: {[action]: {request: wrong}}}); w.change('reason', 'Reviewed'); w.click(w.decision(action)); await flush(); assert.equal(w.toasts.length, 0); assert.match(w.note(), /Chưa xác nhận được quyết định/); }
  const w = await ready({actionResults: {approve: {request: row()}}}); w.change('reason', 'Reviewed'); w.click(w.decision('approve')); await flush(); assert.equal(w.toasts.length, 0); assert.equal(w.note().includes('kích hoạt'), false);
});
test('reenrollment issues one new QR and preserves truthful old FaceID copy', async () => {
  const w = await ready(); w.change('reason', 'Cần quét lại'); w.click(w.decision('reenroll')); w.click(w.decision('reenroll')); await flush(); assert.equal(w.writes().length, 1); assert.equal(w.writes()[0].url, prefix + '/requests/' + rid(1) + '/reenroll'); assert.equal(w.find('[data-qr-request="' + rid(91) + '"]') !== null, true); assert.match(w.toasts[0], /FaceID đang có được giữ nguyên/); assert.equal(w.all('input').find(input => input.readOnly)?.value, 'https://local.test/enroll#invite=' + 'A'.repeat(43));
});
test('capturing request supports only revision/reason cancellation and terminal requests have no decisions', async () => {
  const w = await ready({items: [row(1, {status: 'CAPTURING'})]}); assert.equal(w.decision('approve'), null); w.change('reason', 'Hủy lời mời cũ'); w.click(w.decision('cancel')); await flush(); assert.deepEqual(JSON.parse(w.writes()[0].init.body), {expected_revision: 4, reason: 'Hủy lời mời cũ'}); assert.match(w.toasts[0], /đã được hủy.*giữ nguyên/);
  for (const state of ['APPROVED', 'REJECTED', 'CANCELLED', 'EXPIRED']) { const p = await ready({items: [row(1, {status: state, review_reason: 'Đã xử lý'})]}); assert.equal(p.all('[data-qr-decision]').length, 0); assert.match(p.host.textContent, /Đã xử lý/); }
});
test('server index refresh pending is reported without claiming active recognition synchronization', async () => {
  const w = await ready({actionResults: {approve: {request: row(1, {status: 'APPROVED'}), index_refresh_pending: true}}}); w.change('reason', 'Reviewed'); w.click(w.decision('approve')); await flush(); assert.match(w.toasts[0], /chờ đồng bộ/); assert.equal(w.toasts[0].includes('kích hoạt'), false);
});
test('QR uses only local server image/link, clipboard copy, and clears the raw token on expiry', async () => {
  const w = await ready(); w.change('store', '2'); w.click(w.action('issue')); await flush(); const input = w.all('input').find(input => input.readOnly), qr = w.all('img').find(image => image.className === 'qr-enrollment-code'); assert.match(qr.src, /^data:image\/png/); assert.equal(input.value.includes('#invite='), true); w.click(w.action('copy')); await flush(); assert.deepEqual(w.copied, [input.value]); await w.advance(900000); assert.equal(input.value, ''); assert.equal(qr.src, ''); assert.equal(w.action('copy'), null); assert.equal(w.requests.some(request => /invite=/.test(request.url)), false);
});
test('rejects external/query-bearing/malformed QR links and reports unavailable HTTPS truthfully', async () => {
  for (const qr_url of ['https://external.test/enroll#invite=' + 'A'.repeat(43), 'https://local.test/enroll?invite=token', 'https://local.test/enroll#invite=short', 'javascript:alert(1)']) { const w = await ready({invitationResult: invitation(row(90, {status: 'CAPTURING'}), {qr_url})}); w.change('store', '2'); w.click(w.action('issue')); await flush(); assert.equal(w.all('input').some(input => input.readOnly && input.value), false); assert.equal(w.all('img').length, 0); assert.match(w.note(), /chưa có liên kết hợp lệ/i); }
  const w = await ready({origin: 'http://local.test', invitationResult: invitation(row(90, {status: 'CAPTURING'}), {qr_url: 'http://local.test/enroll#invite=' + 'A'.repeat(43), capture_https_ready: false, qr_data_url: undefined})}); w.change('store', '2'); w.click(w.action('issue')); await flush(); assert.match(w.host.textContent, /Chưa sẵn sàng.*HTTPS/); assert.match(w.host.textContent, /Mã QR chưa khả dụng/);
});
test('clipboard fallback selects the visible link and never sends to a third party', async () => {
  const w = await ready({copyError: true}); w.change('store', '2'); w.click(w.action('issue')); await flush(); const input = w.all('input').find(input => input.readOnly); w.click(w.action('copy')); await flush(); assert.equal(w.document.activeElement, input); assert.equal(input.selected, true); assert.match(w.note(), /Chọn và sao chép/);
});
test('preview is protected binary, size/type checked and object URLs revoked on selection/stop', async () => {
  const w = await ready({items: [row(1, {has_preview: true}), row(2, {has_preview: true})]}); assert.equal(w.previewRequests[0].url, prefix + '/requests/' + rid(1) + '/preview.jpg'); assert.ok(w.previewRequests[0].init.signal); assert.equal(w.all('img')[0].src, 'blob:preview/1'); w.click(w.find('[data-qr-request="' + rid(2) + '"]')); await flush(); assert.deepEqual(w.revoked, ['blob:preview/1']); assert.equal(w.all('img')[0].src, 'blob:preview/2'); w.controller.stop(); assert.deepEqual(w.revoked, ['blob:preview/1', 'blob:preview/2']); assert.equal(w.host.children.length, 0);
  for (const blob of [new Blob(['x'], {type: 'text/html'}), {type: 'image/jpeg', size: 0}, {type: 'image/jpeg', size: 2 * 1024 * 1024 + 1}]) { const p = await ready({items: [row(1, {has_preview: true})], blob}); assert.equal(p.urls.length, 0); assert.match(p.host.textContent, /Ảnh xem trước chưa tải được/); }
});
test('late/stale previews cannot attach images or allocate an object URL', async () => {
  const w = await ready({items: [row(1, {has_preview: true}), row(2)], holdPreview: true}); const old = w.previewsPending[0]; w.click(w.find('[data-qr-request="' + rid(2) + '"]')); await flush(); assert.equal(old.init.signal.aborted, true); old.resolve(new Blob(['JPEG'], {type: 'image/jpeg'})); await flush(); assert.equal(w.urls.length, 0); assert.equal(w.all('img').length, 0);
});
test('stale list/detail failures do not clear the newer canonical result', async () => {
  const w = await ready({hold: url => url === prefix + '/requests/' + rid(1)}); const old = w.pending[0]; w.items = [row(2)]; w.hold = null; await w.controller.refresh(); await flush(); old.reject(new Error('late offline')); await flush(); assert.equal(w.find('[data-qr-request="' + rid(2) + '"]').getAttribute('aria-pressed'), 'true'); assert.equal(w.decision('approve') !== null, true); assert.equal(w.note().includes('Chưa tải'), false);
  w.hold = url => url.startsWith(prefix + '/requests?'); const oldRefresh = w.controller.refresh(); await flush(); const oldList = w.pending.at(-1); w.hold = null; await w.controller.refresh(); oldList.reject(new Error('late list offline')); await oldRefresh; await flush(); assert.equal(w.find('[data-qr-request="' + rid(2) + '"]').getAttribute('aria-pressed'), 'true'); assert.equal(w.note().includes('Chưa tải'), false);
});
test('expiry disables all decisions and refreshes authoritative request state without writing', async () => {
  const w = await ready({items: [row(1, {expires_at: new Date(initialTime + 1000).toISOString()})]}); w.change('reason', 'Reviewed'); assert.equal(w.decision('approve').disabled, false); w.items = [row(1, {status: 'EXPIRED'})]; await w.advance(1000); assert.equal(w.decision('approve'), null); assert.equal(w.writes().length, 0); assert.ok(w.listCalls().length > 1);
  const p = await ready({items: [row(1, {expires_at: 'bad'})]}); p.change('reason', 'Reviewed'); p.click(p.decision('approve')); await flush(); assert.equal(p.writes().length, 0); assert.equal(p.decision('approve').disabled, true);
});
test('hiding aborts current work and clears invitation/preview; visible page reloads without reissue', async () => {
  const w = await ready(); w.change('store', '2'); w.click(w.action('issue')); await flush(); const input = w.all('input').find(input => input.readOnly); w.hold = url => url.startsWith(prefix + '/requests?'); const refresh = w.controller.refresh(); await flush(); const old = w.pending[0]; w.document.hidden = true; w.fire('visibilitychange'); assert.equal(old.init.signal.aborted, true); assert.equal(input.value, ''); assert.equal(w.all('[data-qr-request]').length, 0); old.reject(new Error('late offline')); await refresh; await flush(); assert.equal(w.note().includes('Chưa tải'), false); w.hold = null; w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.all('[data-qr-request]').length > 0, true); assert.equal(w.writes().length, 1); assert.equal(w.all('input').some(input => input.readOnly && input.value), false);
});
test('auth/navigation/pagehide stop owners and reject late action successes', async () => {
  for (const type of ['btmh:auth', 'btmh:navigate', 'pagehide']) { const w = await ready({hold: (_, init) => init.method === 'POST'}); w.change('reason', 'Reviewed'); w.click(w.decision('approve')); await flush(); const old = w.pending[0]; w.fire(type, type === 'pagehide' ? w.window : w.document); assert.equal(old.init.signal.aborted, true); assert.equal(w.host.children.length, 0); old.resolve({request: row(1, {status: 'APPROVED'})}); await flush(); assert.equal(w.toasts.length, 0); const count = w.requests.length; await w.controller.refresh(); assert.equal(w.requests.length, count); }
});
test('only current Owner/Admin with permission can load or mutate', async () => {
  for (const config of [{actor: null}, {actor: {id: 1, role: 'HR'}}, {actor: {id: 1, role: 'MANAGER'}}, {permission: false}, {student: {id: true}}, {hidden: true}]) { const w = await ready(config); assert.equal(w.requests.length, 0); assert.equal(w.writes().length, 0); }
  const w = await ready(); w.change('reason', 'Reviewed'); w.actor = {id: 2, role: 'ADMIN'}; w.click(w.decision('approve')); await flush(); assert.equal(w.writes().length, 0);
});
test('native buttons/fields are keyboard-addressable with accessible status and current selection', async () => {
  const w = await ready(); for (const button of w.all('button')) assert.equal(button.type, 'button'); assert.equal(w.field('store').getAttribute('aria-label'), 'Cửa hàng đăng ký qua QR'); assert.equal(w.field('status').getAttribute('aria-label'), 'Trạng thái yêu cầu đăng ký'); assert.equal(w.field('reason').getAttribute('aria-label'), 'Lý do quyết định duyệt FaceID'); w.field('reason').focus(); assert.equal(w.document.activeElement, w.field('reason')); assert.equal(w.find('[data-qr-request="' + rid(1) + '"]').getAttribute('aria-pressed'), 'true'); const note = w.host.children[0].children.find(element => element.className.includes('qr-enrollment-note')); assert.equal(note.getAttribute('role'), 'status'); assert.equal(note.getAttribute('aria-live'), 'polite');
});
test('rendered text excludes raw network sources and private diagnostics', async () => {
  const w = await ready({student: {id: 17, full_name: 'rtsp://secret.invalid', student_code: '192.168.1.2'}, items: [row(1, {store_name: 'https://private.invalid', duplicate: {student_id: 2, full_name: 'rtsp://duplicate.invalid', student_code: '192.168.1.3'}})]}); assert.equal(/rtsp:|https:\/\/private|192\.168|secret\.invalid|duplicate\.invalid/.test(w.host.textContent), false); assert.equal(w.requests.some(request => /camera|activate|finalize/.test(request.url)), false);
});

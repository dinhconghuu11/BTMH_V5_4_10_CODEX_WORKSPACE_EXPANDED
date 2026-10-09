'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_demo_reports.js'), 'utf8');
const appSource = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../frontend/index.html'), 'utf8');
const management = require('../frontend/js/btmh_management.js');
const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const recognized = (extra = {}) => ({id: 9188, event_id: 9188, appearance_id: 'a1', daily_sequence: 7, business_date: '2026-10-08', occurred_at: '2026-10-08T01:00:00Z', timezone_name: 'Asia/Ho_Chi_Minh', recognized: true, faceid_status: 'VERIFIED', pad_status: 'PASS', status: 'RECOGNIZED', full_name: 'Nguyễn A', student_code: 'NV01', department: 'Tư vấn', store_name: 'Hà Đông', zone_name: 'Cửa vào', camera_name: 'Camera cũ', ...extra});
const attendance = (extra = {}) => ({employee_id: 11, store_id: 2, business_date: '2026-10-08', full_name: 'Nguyễn A', employee_code: 'NV01', department: 'Tư vấn', store_name: 'Hà Đông', shift_name: 'Ca sáng', schedule_state: 'ASSIGNED', status: 'MISSING_OUT', first_in_at: '2026-10-08T01:00:00Z', checkin_at: '2026-10-08T01:00:00Z', last_seen_at: '2026-10-08T08:00:00Z', checkout_at: null, checkout_source: null, ...extra});
const filters = {stores: [{id: 2, store_name: 'Hà Đông'}, {id: 3, store_name: 'Cầu Giấy'}], zones: [{store_id: 2, zone_name: 'Cửa vào'}, {store_id: 3, zone_name: 'Cửa vào'}, {store_id: 3, zone_name: 'Kho'}], cameras: [{camera_id: 5, store_id: 2, zone_name: 'Cửa vào', camera_name: 'Camera 5'}, {camera_id: 9, store_id: 3, zone_name: 'Kho', camera_name: 'Camera 9'}], employees: [{id: 11, student_code: 'NV01', full_name: 'Nguyễn A', department: 'Tư vấn'}, {id: 12, full_name: 'Nguyễn B', department: 'Kế toán'}], departments: [{department: 'Tư vấn'}, {department: 'Kế toán'}]};

function browser(config = {}) {
  const w = {requests: [], pending: [], items: [recognized()], attendanceItems: [attendance()], total: 123, images: [], permissions: new Set(['history.view', 'hr.report', 'visitor.view']), authenticated: true, totals: {scheduled_shifts: 40, present_shifts: 31, late_cases: 4, absent_days: 3, missing_out: 6}, timeline: {items: []}, ...config};
  const document = new EventTarget(); document.hidden = !!w.hidden; document.activeElement = null;
  class Element extends EventTarget {
    constructor(tag) { super(); this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {}; this.attributes = {}; this.style = {}; this.value = ''; this.className = ''; this.hidden = false; this.disabled = false; this._text = ''; if (tag === 'img') w.images.push(this); }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    get classList() { return {contains: value => this.className.split(/\s+/).includes(value), add: value => this.classList.toggle(value, true), remove: value => this.classList.toggle(value, false), toggle: (value, on) => { const names = new Set(this.className.split(/\s+/).filter(Boolean)); if (on ?? !names.has(value)) names.add(value); else names.delete(value); this.className = [...names].join(' '); }}; }
    append(...children) { for (const child of children) { child.remove(); child.parentElement = this; this.children.push(child); } }
    prepend(...children) { for (const child of children.reverse()) { child.remove(); child.parentElement = this; this.children.unshift(child); } }
    remove() { if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; }
    replaceChildren(...children) { for (const child of this.children) child.parentElement = null; this.children = []; this._text = ''; this.append(...children); }
    querySelectorAll(selector) { const matches = child => { if (selector === 'img') return child.tagName === 'IMG'; if (selector.startsWith('.')) return child.classList.contains(selector.slice(1)); const match = selector.match(/^\[data-([\w-]+)(?:="([^"]*)")?\]$/); if (!match) return false; const key = match[1].replace(/-([a-z])/g, (_, x) => x.toUpperCase()); return key in child.dataset && (match[2] === undefined || child.dataset[key] === match[2]); }; return this.children.flatMap(child => [...(matches(child) ? [child] : []), ...child.querySelectorAll(selector)]); }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    getAttribute(name) { return this.attributes[name] ?? null; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'src') this.src = ''; if (name === 'href') this.href = ''; }
    focus() { document.activeElement = this; }
  }
  const roots = new Map(), register = (id, tag = 'div') => { const node = new Element(tag); node.id = id; roots.set(id, node); return node; };
  const page = register('page-history'); page.className = w.offPage ? 'page' : 'page active';
  for (const id of [...html.matchAll(/\bid="(demo(?:Report|Total|Visits)[^"]+)"/g)].map(match => match[1])) { const tag = /(?:Period|Store|Zone|Camera|Employee|Department|Subject|Result)$/.test(id) ? 'select' : /(?:Start|End|Month|Year|Search|Date)$/.test(id) ? 'input' : id === 'demoReportBody' ? 'tbody' : id === 'demoReportHead' ? 'thead' : id === 'demoReportFilters' ? 'form' : id === 'demoReportExport' ? 'a' : /(?:Tab|Close|Refresh|Previous|Next|Today|Yesterday)$/.test(id) ? 'button' : 'div'; page.append(register(id, tag)); }
  const tabs = ['recognition', 'attendance', 'visits'].map(mode => { const tab = roots.get(`demoReport${mode[0].toUpperCase() + mode.slice(1)}Tab`); tab.dataset.demoReport = mode; roots.get('demoReportTabs').append(tab); return tab; });
  for (const period of ['DAY RANGE', 'RANGE', 'MONTH', 'YEAR']) { const label = new Element('label'); label.dataset.demoPeriod = period; page.append(label); }
  for (const scope of ['recognition', 'attendance']) { const label = new Element('label'); label.dataset.demoScope = scope; page.append(label); }
  roots.get('demoReportDetail').hidden = true;
  document.getElementById = id => roots.get(id) || null; document.createElement = tag => new Element(tag);
  const window = new EventTarget(), state = {authUser: w.authenticated ? {id: 1} : null}; window.BTMHManagement = management;
  const api = async (url, init) => {
    const request = {url, init}; w.requests.push(request);
    if (w.hold?.(url)) return new Promise((resolve, reject) => w.pending.push({...request, resolve, reject}));
    const error = typeof w.error === 'function' ? w.error(url) : w.error; if (error) throw error;
    if (url === '/api/v1/history/filters') return filters;
    if (url.startsWith('/api/v1/history/attendance/timeline?')) return w.timeline;
    const query = new URL(url, 'https://btmh.local').searchParams;
    if (url.startsWith('/api/v1/history/visits?')) { const day = query.get('date'), previous = new Date(day + 'T00:00:00Z'); previous.setUTCDate(previous.getUTCDate() - 1); return {date: day, comparison_date: previous.toISOString().slice(0, 10), configuration_state: 'READY', totals: {selected: 12, previous: 10, delta: 2, percent: 20, change_state: 'CHANGED'}, stores: [{store_id: 2, store_name: 'Hà Đông', selected: 12, previous: 10, delta: 2, percent: 20, configuration_state: 'READY'}], hourly: [{hour: 8, selected: 2, previous: 1}], ...w.visits}; }
    return {items: url.startsWith('/api/v1/history/attendance?') ? w.attendanceItems : w.items, total: w.total, limit: Number(query.get('limit')), offset: Number(query.get('offset')), totals: w.totals};
  };
  const context = {window, document, state, location: {origin: 'https://btmh.local'}, api, appPresentationActive: () => w.authenticated && !w.suspended && !document.hidden, hasUiPermission: key => w.permissions.has(key), AbortController, URL, URLSearchParams, Intl, Date, Event, CustomEvent};
  vm.createContext(context); vm.runInContext(source, context);
  Object.assign(w, {context, api: window.BTMHDemoReports, document, window, state, roots, page, tabs});
  w.get = id => roots.get(id); w.fire = (type, detail, target = document) => target.dispatchEvent(new CustomEvent(type, {detail}));
  w.click = id => w.get(id).dispatchEvent(new Event('click')); w.change = (id, value) => { w.get(id).value = value; w.get(id).dispatchEvent(new Event('change')); };
  w.submit = () => w.get('demoReportFilters').dispatchEvent(new Event('submit', {cancelable: true})); w.text = () => w.get('demoReportBody').textContent; w.reportRequests = () => w.requests.filter(request => /\/(recognition|attendance)\?/.test(request.url));
  return w;
}

test('reset clears restrictive filters and stale query then exports only the restored current-day filter', async () => {
  const w = browser(); await flush(); w.change('demoReportStore', '2'); await flush(); w.change('demoReportSubject', 'UNKNOWN'); await flush(); w.get('demoReportSearch').value = 'Không tìm thấy'; w.submit(); await flush();
  w.click('demoReportReset'); await flush(); const request = w.reportRequests().at(-1), query = new URL(request.url, 'https://btmh.local').searchParams;
  assert.equal(query.get('start_date'), query.get('end_date')); assert.equal(query.get('offset'), '0'); assert.equal(query.has('store_id'), false); assert.equal(query.has('subject_type'), false); assert.equal(query.has('search'), false); assert.equal(w.get('demoReportSearch').value, ''); assert.equal(w.get('demoReportPeriod').value, 'DAY');
  const exported = new URL(w.get('demoReportExport').href, 'https://btmh.local').searchParams; assert.equal(exported.get('start_date'), query.get('start_date')); assert.equal(exported.has('store_id'), false);
});

test('starts one scoped server query after options, uses server totals and immutable camera metadata', async () => {
  const w = browser(); await flush(); assert.equal(w.requests.length, 2); assert.equal(w.requests[0].url, '/api/v1/history/filters');
  const q = new URL(w.requests[1].url, 'https://btmh.local').searchParams; assert.equal(q.get('start_date'), q.get('end_date')); assert.equal(q.get('limit'), '50'); assert.equal(q.get('offset'), '0');
  assert.equal(w.get('demoReportCount').textContent, '123'); assert.match(w.text(), /#0007/); assert.match(w.text(), /Camera cũ/); assert.match(w.get('demoReportPageInfo').textContent, /1–1 \/ 123/);
  assert.equal(w.get('demoReportZone').children.filter(item => item.value === 'Cửa vào').length, 1, 'same zone name across stores appears once');
});

test('recognition filter query and CSV carry exact filters, CSV excludes pagination', async () => {
  const w = browser(); await flush(); const values = {Period: 'RANGE', Start: '2026-10-01', End: '2026-10-08', Store: '2', Zone: 'Cửa vào', Camera: '5', Employee: '11', Subject: 'EMPLOYEE', Result: 'RECOGNIZED', Search: 'Nguyễn & A'};
  for (const [key, value] of Object.entries(values)) w.get('demoReport' + key).value = value; w.submit(); await flush();
  const q = new URL(w.requests.at(-1).url, 'https://btmh.local').searchParams;
  for (const [key, value] of Object.entries({start_date: '2026-10-01', end_date: '2026-10-08', store_id: '2', zone_name: 'Cửa vào', camera_id: '5', employee_id: '11', subject_type: 'EMPLOYEE', result: 'RECOGNIZED', search: 'Nguyễn & A'})) assert.equal(q.get(key), value);
  const link = w.get('demoReportExport'), csv = new URL(link.href, 'https://btmh.local'); assert.equal(csv.pathname, '/api/v1/history/recognition/export.csv'); assert.equal(csv.searchParams.has('limit'), false); assert.equal(csv.searchParams.has('offset'), false); assert.equal(csv.searchParams.get('search'), 'Nguyễn & A'); assert.equal(link.attributes['aria-disabled'], 'false');
});

test('month/year ranges include leap dates and invalid or excessive ranges issue no query', async () => {
  const w = browser(); await flush(); w.get('demoReportPeriod').value = 'MONTH'; w.get('demoReportMonth').value = '2024-02'; w.submit(); await flush(); assert.match(w.requests.at(-1).url, /end_date=2024-02-29/);
  w.get('demoReportPeriod').value = 'YEAR'; w.get('demoReportYear').value = '2024'; w.submit(); await flush(); assert.match(w.requests.at(-1).url, /start_date=2024-01-01&end_date=2024-12-31/);
  const count = w.requests.length; w.get('demoReportPeriod').value = 'RANGE'; w.get('demoReportStart').value = '2026-02-30'; w.get('demoReportEnd').value = '2026-03-01'; w.submit(); await flush(); assert.equal(w.requests.length, count); assert.match(w.get('demoReportStatus').textContent, /hợp lệ/);
  w.get('demoReportStart').value = '2024-01-01'; w.get('demoReportEnd').value = '2026-01-01'; w.submit(); await flush(); assert.equal(w.requests.length, count); assert.equal(w.get('demoReportExport').href, '');
});

test('server pagination does not download a client-side1200 feed and changed filters reset offset', async () => {
  const w = browser(); await flush(); w.click('demoReportNext'); await flush(); assert.match(w.requests.at(-1).url, /offset=50$/); assert.equal(w.get('demoReportPrevious').disabled, false);
  w.click('demoReportPrevious'); await flush(); assert.match(w.requests.at(-1).url, /offset=0$/); w.click('demoReportNext'); await flush(); w.change('demoReportSubject', 'VISITOR'); await flush(); assert.match(w.requests.at(-1).url, /offset=0$/); assert.ok(w.requests.every(request => !request.url.includes('1200')));
});

test('dependent store/zone/department options discard out-of-scope selections', async () => {
  const w = browser(); await flush(); w.get('demoReportZone').value = 'Cửa vào'; w.get('demoReportCamera').value = '5'; w.get('demoReportEmployee').value = '11'; w.change('demoReportStore', '3'); await flush();
  assert.equal(w.get('demoReportCamera').value, ''); assert.equal(w.get('demoReportEmployee').value, ''); assert.deepEqual(w.get('demoReportCamera').children.map(item => item.value), ['', '9']);
  w.api.selectMode('attendance'); await flush(); w.get('demoReportEmployee').value = '11'; w.change('demoReportDepartment', 'Kế toán'); await flush(); assert.equal(w.get('demoReportEmployee').value, ''); assert.deepEqual(w.get('demoReportEmployee').children.map(item => item.value), ['', '12']); assert.match(w.requests.at(-1).url, /department=/); assert.equal(new URL(w.requests.at(-1).url, 'https://btmh.local').searchParams.has('zone_name'), false);
});

test('changing date while options load retains the single request and queries the latest filters', async () => {
  const w = browser({hold: url => url.endsWith('/filters')}); await flush(); w.change('demoReportStart', '2026-10-01'); await flush(); assert.equal(w.requests.length, 1); w.pending[0].resolve(filters); await flush(); assert.equal(w.requests.length, 2); assert.match(w.requests.at(-1).url, /start_date=2026-10-01&end_date=2026-10-01/);
});

test('changing filters aborts previous query and rejects late response names/totals', async () => {
  const w = browser({hold: url => /recognition\?/.test(url)}); await flush(); const old = w.pending[0]; w.hold = null; w.items = [recognized({full_name: 'Scope mới'})]; w.change('demoReportStore', '2'); await flush(); assert.equal(old.init.signal.aborted, true); assert.match(w.text(), /Scope mới/);
  old.resolve({items: [recognized({full_name: 'Scope cũ'})], total: 999, limit: 50, offset: 0}); await flush(); assert.equal(w.text().includes('Scope cũ'), false); assert.equal(w.get('demoReportCount').textContent, '123');
});

test('verified identity only, no invented sequence or current-location attribution, safe detail crop', async () => {
  const w = browser({items: [recognized({recognized: false, daily_sequence: null, full_name: 'Private candidate', student_code: 'Secret', faceid_status: 'UNKNOWN', status: 'UNREGISTERED', camera_name: null, store_name: null, zone_name: null, snapshot_url: 'https://foreign.invalid/p.jpg'})]}); await flush(); assert.equal(/Private candidate|Secret|9188|#0000/.test(w.text()), false); assert.match(w.text(), /Chưa ghi nhận/);
  w.get('demoReportBody').children[0].children.at(-1).children[0].dispatchEvent(new Event('click')); assert.equal(w.get('demoReportDetail').hidden, false); assert.equal(w.get('demoReportDetailContent').textContent.includes('Private candidate'), false); assert.equal(w.images.some(image => image.src), false); assert.equal(w.document.activeElement, w.get('demoReportDetailClose'));
});

test('attendance displays real OUT/correction only, last seen separately and no inferred worked time', async () => {
  const w = browser({attendanceItems: [attendance({checkout_at: '2026-10-08T09:00:00Z', checkout_source: null}), attendance({checkout_at: '2026-10-08T10:00:00Z', checkout_source: 'GATE_OUT'}), attendance({checkout_at: '2026-10-08T11:00:00Z', checkout_source: 'APPROVED_CORRECTION'}), attendance({status: 'ABSENT', schedule_state: 'UNCONFIGURED', shift_name: null})]}); await flush(); w.api.selectMode('attendance'); await flush(); const rows = w.get('demoReportBody').children;
  assert.match(rows[0].children[5].textContent, /Chưa ghi nhận ra/); assert.match(rows[0].children[6].textContent, /15:00:00/); assert.match(rows[1].children[5].textContent, /17:00:00/); assert.match(rows[2].children[5].textContent, /Điều chỉnh đã duyệt/); assert.equal(rows[3].children[7].textContent, 'Chưa cấu hình ca'); assert.ok(rows.every(row => row.children[8].textContent === 'Chưa đủ dữ liệu'));
  assert.equal(w.get('demoTotalShifts').textContent, '40'); assert.equal(w.get('demoTotalPresent').textContent, '31'); assert.equal(w.get('demoTotalMissingOut').textContent, '6'); assert.match(w.get('demoReportExport').href, /attendance\/export.csv/);
});

test('attendance timeline queries exact employee/business date/store and shows real event sources/corrections', async () => {
  const w = browser({timeline: {schedule_state: 'UNCONFIGURED', recognition_limit_reached: true, items: [{event_type: 'VALID_IN', source: 'ATTENDANCE', occurred_at: '2026-10-08T01:00:00Z', camera_name: 'Cửa vào'}, {event_type: 'VALID_OUT', source: 'ATTENDANCE', occurred_at: '2026-10-08T02:00:00Z'}, {event_type: 'LAST_OBSERVATION', source: 'ATTENDANCE', occurred_at: '2026-10-08T03:00:00Z'}, {event_type: 'RECOGNITION', source: 'RECOGNITION', occurred_at: '2026-10-08T04:00:00Z'}, {event_type: 'APPROVED_CHECKOUT_CORRECTION', source: 'ATTENDANCE', occurred_at: '2026-10-08T05:00:00Z'}]}}); await flush(); w.api.selectMode('attendance'); await flush(); w.get('demoReportBody').children[0].children.at(-1).children[0].dispatchEvent(new Event('click')); await flush();
  assert.equal(w.requests.at(-1).url, '/api/v1/history/attendance/timeline?employee_id=11&business_date=2026-10-08&store_id=2'); const timeline = w.get('demoReportDetailContent').querySelector('.demo-report-timeline'); assert.match(timeline.textContent, /Vào.*Chấm công.*Ra.*Quan sát lần cuối.*Nhận diện.*Điều chỉnh giờ ra đã duyệt/); assert.match(timeline.textContent, /Chưa cấu hình ca/); assert.match(timeline.textContent, /gần nhất/);
});

test('closing or changing tab aborts timeline and ignores late details, Escape restores focus', async () => {
  const w = browser({hold: url => url.includes('/timeline?')}); await flush(); w.api.selectMode('attendance'); await flush(); const button = w.get('demoReportBody').children[0].children.at(-1).children[0]; button.focus(); button.dispatchEvent(new Event('click')); await flush(); const pending = w.pending[0];
  const escape = new Event('keydown', {cancelable: true}); Object.defineProperty(escape, 'key', {value: 'Escape'}); w.get('demoReportDetail').dispatchEvent(escape); assert.equal(pending.init.signal.aborted, true); assert.equal(w.document.activeElement, button); pending.resolve({items: [{event_type: 'VALID_OUT', occurred_at: '2026-10-08T07:00:00Z'}]}); await flush(); assert.equal(w.get('demoReportDetailContent').textContent, ''); assert.equal(w.get('demoReportDetail').hidden, true);
});

test('attendance permission is enforced before queries; keyboard selects permitted visits independently', async () => {
  const w = browser({permissions: new Set(['history.view', 'visitor.view'])}); await flush(); assert.equal(w.tabs[1].disabled, true); w.api.selectMode('attendance'); await flush(); assert.equal(w.requests.some(request => request.url.includes('/attendance')), false);
  w.tabs[0].focus(); const right = new Event('keydown', {cancelable: true}); Object.defineProperty(right, 'key', {value: 'ArrowRight'}); w.get('demoReportTabs').dispatchEvent(right); await flush(); assert.equal(w.document.activeElement, w.tabs[2]); assert.equal(w.get('demoReportVisits').hidden, false); assert.equal(w.get('demoReportFilters').hidden, true); assert.equal(w.get('demoReportContent').attributes['aria-labelledby'], 'demoReportVisitsTab'); assert.equal(w.requests.filter(request => request.url.includes('visits')).length, 1);
});

test('switching to visits while options load queries only the active report', async () => {
  const w = browser({hold: url => url.endsWith('/filters')}); await flush(); w.api.selectMode('visits'); w.pending[0].resolve(filters); await flush(); assert.equal(w.requests.length, 2); assert.match(w.requests.at(-1).url, /history\/visits\?date=/); assert.equal(w.get('demoReportVisits').hidden, false);
});

test('visits use independently selected day/store with no recognition/camera/employee filters', async () => {
  const w = browser(); await flush(); w.get('demoReportStart').value = '2025-01-01'; w.get('demoReportStore').value = '3'; w.get('demoReportCamera').value = '9'; w.get('demoReportEmployee').value = '12'; w.get('demoVisitsDate').value = '2026-10-01'; w.get('demoVisitsStore').value = '2'; w.api.selectMode('visits'); await flush();
  assert.equal(w.requests.at(-1).url, '/api/v1/history/visits?date=2026-10-01&store_id=2'); assert.match(w.get('demoVisitsContent').textContent, /2026-10-01.*12.*2026-09-30.*10/); assert.equal(w.get('demoVisitsContent').textContent.includes('Hôm nay'), false); assert.match(w.get('demoVisitsContent').textContent, /Hà Đông/); assert.equal(w.get('demoReportExport').hidden, true);
});

test('visits Today/Yesterday buttons query server and preserve a selected store', async () => {
  const w = browser(); await flush(); w.api.selectMode('visits'); await flush(); w.get('demoVisitsStore').value = '2'; w.click('demoVisitsYesterday'); await flush(); const yesterday = w.get('demoVisitsDate').value; assert.match(w.requests.at(-1).url, new RegExp('date=' + yesterday + '&store_id=2'));
  w.click('demoVisitsToday'); await flush(); const today = w.get('demoVisitsDate').value; const difference = (new Date(today) - new Date(yesterday)) / 86400000; assert.equal(difference, 1); assert.equal(w.get('demoVisitsStore').value, '2'); assert.match(w.get('demoVisitsContent').textContent, /Hôm nay/);
});

test('visits missing configuration is explained without invented counts; zero baseline is never Infinity', async () => {
  const w = browser({visits: {configuration_state: 'UNCONFIGURED', totals: {selected: 0, previous: 0, change_state: 'UNCHANGED'}, stores: [], hourly: []}}); await flush(); w.api.selectMode('visits'); await flush(); assert.match(w.get('demoVisitsContent').textContent, /Chưa cấu hình/); assert.equal(w.get('demoVisitsContent').textContent.includes('Hôm nay 0'), false);
  w.visits = {totals: {selected: 3, previous: 0, percent: null, change_state: 'NEW_ACTIVITY'}}; await w.api.refresh(); assert.match(w.get('demoVisitsContent').textContent, /Có lượt ghé mới/); assert.equal(/Infinity|NaN/.test(w.get('demoVisitsContent').textContent), false);
});

test('visits permission blocks tab/query and report failures support explicit retry', async () => {
  const denied = browser({permissions: new Set(['history.view', 'hr.report'])}); await flush(); denied.api.selectMode('visits'); await flush(); assert.equal(denied.tabs[2].disabled, true); assert.equal(denied.requests.some(request => request.url.includes('visits')), false);
  const w = browser({error: url => url.includes('/visits?') ? {status: 403} : null}); await flush(); w.api.selectMode('visits'); await flush(); assert.match(w.get('demoReportStatus').textContent, /chưa có quyền xem lượt khách/); assert.equal(w.get('demoVisitsContent').textContent, ''); w.error = null; w.click('demoVisitsRefresh'); await flush(); assert.match(w.get('demoVisitsContent').textContent, /Hà Đông/);
});

test('visits requests are single-flight and old date/auth responses cannot restore stale data', async () => {
  const w = browser({hold: url => url.includes('/visits?')}); await flush(); w.api.selectMode('visits'); await flush(); const old = w.pending[0]; w.click('demoVisitsRefresh'); await flush(); assert.equal(w.pending.length, 1); w.hold = null; w.change('demoVisitsDate', '2026-10-01'); await flush(); assert.equal(old.init.signal.aborted, true); old.resolve({date: '2026-10-08', configuration_state: 'READY', totals: {selected: 999, previous: 999}, stores: [], hourly: []}); await flush(); assert.equal(w.get('demoVisitsContent').textContent.includes('999'), false);
  w.hold = url => url.includes('/visits?'); void w.api.refresh(); await flush(); const current = w.pending[1]; w.authenticated = false; w.state.authUser = null; w.fire('btmh:auth', {authenticated: false}); assert.equal(current.init.signal.aborted, true); assert.equal(w.get('demoVisitsContent').textContent, '');
});

test('visits invalid date or non-scoped store never sends a query', async () => {
  const w = browser(); await flush(); w.get('demoVisitsDate').value = '2026-02-30'; w.api.selectMode('visits'); await flush(); assert.equal(w.requests.some(request => request.url.includes('/visits?')), false); assert.match(w.get('demoReportStatus').textContent, /ngày hợp lệ/);
  w.get('demoVisitsDate').value = '2026-10-01'; w.get('demoVisitsStore').value = '999'; await w.api.refresh(); assert.equal(w.requests.some(request => request.url.includes('/visits?')), false); assert.match(w.get('demoReportStatus').textContent, /không thuộc/);
});

test('logout aborts options/report/timeline, clears private rows/export and ignores stale user responses', async () => {
  const w = browser({hold: url => /recognition\?/.test(url)}); await flush(); const pending = w.pending[0]; w.authenticated = false; w.state.authUser = null; w.fire('btmh:auth', {authenticated: false}); assert.equal(pending.init.signal.aborted, true); assert.equal(w.get('demoReportExport').href, '');
  pending.resolve({items: [recognized({full_name: 'Stale name'})], total: 1, limit: 50, offset: 0}); await flush(); assert.equal(w.text().includes('Stale name'), false);
  w.authenticated = true; w.state.authUser = {id: 2}; w.hold = null; w.fire('btmh:auth', {authenticated: true}); await flush(); assert.equal(w.requests.filter(request => request.url.endsWith('/filters')).length, 2, 'auth scoped options are reloaded');
});

test('visibility/navigation/pagehide stop requests and resume only an allowed active page', async () => {
  const w = browser(); await flush(); w.document.hidden = true; w.fire('visibilitychange'); assert.equal(w.text(), ''); const count = w.requests.length; await w.api.refresh(); assert.equal(w.requests.length, count);
  w.document.hidden = false; w.fire('visibilitychange'); await flush(); assert.equal(w.requests.length, count + 1); w.fire('pagehide', {}, w.window); w.api.start(); await flush(); assert.equal(w.requests.length, count + 1); w.fire('pageshow', {}, w.window); await flush(); assert.equal(w.requests.length, count + 2);
  w.page.classList.remove('active'); w.fire('btmh:navigate', {page: 'students'}); w.api.start(); await flush(); assert.equal(w.requests.length, count + 2);
});

test('options/query errors and empty results expose retry without fake counts or CSV', async () => {
  const w = browser({error: url => url.endsWith('/filters') ? new Error('offline') : null}); await flush(); assert.equal(w.requests.length, 1); assert.match(w.get('demoReportStatus').textContent, /Không tải được bộ lọc/); assert.equal(w.get('demoReportCount').textContent, '—');
  w.error = null; await w.api.refresh(); assert.match(w.text(), /Nguyễn A/); w.error = {status: 403}; await w.api.refresh(); assert.match(w.get('demoReportStatus').textContent, /chưa có quyền/); assert.equal(w.get('demoReportExport').href, '');
  w.error = null; w.items = []; w.total = 0; await w.api.refresh(); assert.equal(w.get('demoReportCount').textContent, '0'); assert.match(w.text(), /Không có sự kiện/); assert.equal(w.get('demoReportNext').disabled, true);
});

test('permission/auth/off-page guard stops all initial work', async () => {
  for (const config of [{authenticated: false}, {permissions: new Set()}, {offPage: true}, {hidden: true}]) { const w = browser(config); await flush(); assert.equal(w.requests.length, 0); }
});

test('app history hook delegates to the scoped module, preserving legacy fallback and auth navigation', async () => {
  const match = appSource.match(/async function loadHistory\([^\n]*\)\s*\{[\s\S]*?\n\}/); assert.ok(match); let starts = 0, legacy = 0; const context = {window: {BTMHDemoReports: {start: () => starts++}}, api: () => legacy++}; vm.createContext(context); vm.runInContext(match[0], context); await context.loadHistory(); assert.equal(starts, 1); assert.equal(legacy, 0);
  assert.match(html, /data-page="history" data-permission="history.view"/); assert.match(appSource, /history:'history.view'/); assert.match(appSource, /previousPage==='history'\)window.BTMHDemoReports\?\.stop/);
});

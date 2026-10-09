/* Business reports use scoped server filters, totals, pagination and exports. */
(function () {
  'use strict';
  const page = document.getElementById('page-history'), form = document.getElementById('demoReportFilters');
  if (!page || !form) return;
  const get = id => document.getElementById(id), body = get('demoReportBody'), head = get('demoReportHead');
  const fields = {period: get('demoReportPeriod'), start: get('demoReportStart'), end: get('demoReportEnd'), month: get('demoReportMonth'), year: get('demoReportYear'),
    store: get('demoReportStore'), zone: get('demoReportZone'), camera: get('demoReportCamera'), employee: get('demoReportEmployee'), department: get('demoReportDepartment'),
    subject: get('demoReportSubject'), result: get('demoReportResult'), search: get('demoReportSearch')};
  const tabs = [...page.querySelectorAll('[data-demo-report]')], dialog = get('demoReportDetail'), detail = get('demoReportDetailContent'), closeButton = get('demoReportDetailClose');
  const visitDate = get('demoVisitsDate'), visitStore = get('demoVisitsStore'), visitContent = get('demoVisitsContent');
  const emptyOptions = () => ({stores: [], zones: [], cameras: [], employees: [], departments: []});
  let mode = 'recognition', options = emptyOptions(), optionsLoaded = false, optionsPromise = null, optionsController = null;
  let running = false, presented = true, epoch = 0, controller = null, detailController = null, offset = 0, limit = 50, total = null, currentRows = [], returnFocus = null;
  const user = () => typeof state === 'object' ? state.authUser : null;
  const permitted = () => typeof hasUiPermission === 'function' && hasUiPermission('history.view');
  const canAttend = () => typeof hasUiPermission === 'function' && hasUiPermission('hr.report');
  const canVisit = () => typeof hasUiPermission === 'function' && hasUiPermission('visitor.view');
  const eligible = () => presented && !document.hidden && page.classList.contains('active') && typeof appPresentationActive === 'function' && appPresentationActive() && permitted();
  const positive = value => { const n = Number(value); return Number.isSafeInteger(n) && n > 0 ? n : null; };
  const node = (tag, className = '', text = '') => { const element = document.createElement(tag); element.className = className; element.textContent = text; return element; };
  const value = element => String(element?.value || '').trim();
  const today = () => { const parts = new Intl.DateTimeFormat('en', {timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date()); const part = type => parts.find(item => item.type === type)?.value; return `${part('year')}-${part('month')}-${part('day')}`; };
  function setStatus(message, tone = '') { const status = get('demoReportStatus'); if (status) { status.textContent = message; status.className = `demo-report-status ${tone}`; } }
  function clearImages(root) { for (const image of root?.querySelectorAll('img') || []) { image.onload = null; image.onerror = null; image.removeAttribute('src'); } }
  function closeDetail(focus = true) { detailController?.abort(); detailController = null; clearImages(detail); detail?.replaceChildren(); if (dialog) dialog.hidden = true; if (focus) returnFocus?.focus?.(); returnFocus = null; }
  function retireQuery() { epoch++; controller?.abort(); controller = null; closeDetail(false); }
  const validDate = stamp => /^\d{4}-\d{2}-\d{2}$/.test(stamp) && Number.isFinite(new Date(stamp + 'T00:00:00Z').getTime()) && new Date(stamp + 'T00:00:00Z').toISOString().slice(0, 10) === stamp;
  function dateRange() {
    let start = value(fields.start), end = value(fields.end);
    if (value(fields.period) === 'DAY') end = start;
    if (value(fields.period) === 'MONTH') {
      const month = value(fields.month); if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) throw new Error('Chọn tháng cần tra cứu.');
      start = month + '-01'; end = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).toISOString().slice(0, 10);
    }
    if (value(fields.period) === 'YEAR') { const year = value(fields.year); if (!/^\d{4}$/.test(year) || Number(year) < 2000 || Number(year) > 2100) throw new Error('Chọn năm hợp lệ từ 2000 đến 2100.'); start = year + '-01-01'; end = year + '-12-31'; }
    if (!validDate(start) || !validDate(end) || end < start || (new Date(end) - new Date(start)) / 86400000 > 365) throw new Error('Chọn khoảng ngày hợp lệ, tối đa 366 ngày.');
    return {start, end};
  }
  function params(paged = true) {
    const range = dateRange(), query = new URLSearchParams({start_date: range.start, end_date: range.end});
    for (const [name, field] of [['store_id', 'store'], ['employee_id', 'employee']]) { const id = positive(value(fields[field])); if (id) query.set(name, String(id)); }
    if (value(fields.result)) query.set('result', value(fields.result));
    if (mode === 'recognition') {
      if (value(fields.zone)) query.set('zone_name', value(fields.zone));
      const cameraId = positive(value(fields.camera)); if (cameraId) query.set('camera_id', String(cameraId));
      if (value(fields.subject)) query.set('subject_type', value(fields.subject));
      if (value(fields.search)) query.set('search', value(fields.search).slice(0, 100));
    } else if (mode === 'attendance' && value(fields.department)) query.set('department', value(fields.department));
    if (paged) { query.set('limit', String(limit)); query.set('offset', String(offset)); }
    return query;
  }
  function populate(select, entries, all) {
    if (!select) return; const previous = value(select); select.replaceChildren();
    const option = node('option', '', all); option.value = ''; select.append(option);
    const seen = new Set();
    for (const [key, label] of entries) { if (seen.has(String(key))) continue; seen.add(String(key)); const item = node('option', '', String(label)); item.value = String(key); select.append(item); }
    select.value = entries.some(([key]) => String(key) === previous) ? previous : '';
  }
  function populateOptions() {
    populate(fields.store, options.stores.map(store => [store.id, store.store_name || 'Cửa hàng']), 'Tất cả cửa hàng');
    populate(visitStore, options.stores.map(store => [store.id, store.store_name || 'Cửa hàng']), 'Tất cả cửa hàng');
    const storeId = positive(value(fields.store));
    populate(fields.zone, options.zones.filter(item => !storeId || positive(item.store_id) === storeId).map(item => [item.zone_name, item.zone_name]), 'Tất cả khu vực');
    populate(fields.camera, options.cameras.filter(item => (!storeId || positive(item.store_id) === storeId) && (!value(fields.zone) || item.zone_name === value(fields.zone))).map(item => [item.camera_id ?? item.id, item.camera_name || 'Camera']), 'Tất cả camera');
    populate(fields.department, options.departments.map(item => [item.department, item.department]), 'Tất cả bộ phận');
    const department = mode === 'attendance' ? value(fields.department) : '';
    populate(fields.employee, options.employees.filter(item => !department || String(item.department ?? item.faculty ?? '') === department).map(item => [item.id, [item.student_code, item.full_name].filter(Boolean).join(' · ')]), 'Tất cả nhân viên');
  }
  function resultOptions() {
    const entries = mode === 'attendance' ? [['PRESENT', 'Đã ghi nhận'], ['LATE', 'Đi muộn'], ['ABSENT', 'Vắng'], ['NOT_YET_DUE', 'Chưa đến hạn kết luận'], ['IN_PROGRESS', 'Ca đang diễn ra'], ['MISSING_OUT', 'Thiếu ghi nhận ra']] :
      [['RECOGNIZED', 'Đã xác minh'], ['UNREGISTERED', 'Chưa xác định'], ['SPOOF_BLOCKED', 'Không qua xác minh'], ['ANALYZING', 'Đang kiểm tra']];
    populate(fields.result, entries, 'Tất cả kết quả');
  }
  function updateControls() {
    const period = value(fields.period), attendance = mode === 'attendance', visits = mode === 'visits';
    const extraCount = (attendance ? ['employee', 'department', 'result'] : ['zone', 'employee', 'subject', 'result']).filter(name => value(fields[name])).length;
    get('demoReportMoreSummary').textContent = extraCount ? `Bộ lọc bổ sung (${extraCount} đang dùng)` : 'Bộ lọc bổ sung';
    for (const tab of tabs) { const active = tab.dataset.demoReport === mode; tab.classList.toggle('active', active); tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1; if (tab.dataset.demoReport === 'attendance') tab.disabled = !canAttend(); if (tab.dataset.demoReport === 'visits') tab.disabled = !canVisit(); }
    for (const element of page.querySelectorAll('[data-demo-period]')) element.hidden = !element.dataset.demoPeriod.split(' ').includes(period);
    for (const element of page.querySelectorAll('[data-demo-scope="recognition"]')) element.hidden = attendance || visits;
    for (const element of page.querySelectorAll('[data-demo-scope="attendance"]')) element.hidden = !attendance;
    form.hidden = visits; get('demoReportTablePanel').hidden = visits; get('demoReportVisits').hidden = !visits;
    get('demoReportTotals').hidden = !attendance; get('demoReportExport').hidden = visits;
    get('demoReportTitle').textContent = attendance ? 'Chấm công theo ca' : visits ? 'Lượt khách' : 'Lịch sử nhận diện';
    get('demoReportContent').setAttribute('aria-labelledby', tabs.find(tab => tab.dataset.demoReport === mode)?.id || 'demoReportRecognitionTab');
    updateExport(); pagination();
  }
  function updateExport() {
    const link = get('demoReportExport'); if (!link) return;
    const allowed = running && eligible() && mode !== 'visits' && (mode !== 'attendance' || canAttend()) && total !== null;
    try { if (!allowed) throw new Error(); link.href = `/api/v1/history/${mode}/export.csv?${params(false)}`; link.setAttribute('aria-disabled', 'false'); link.tabIndex = 0; }
    catch (_) { link.removeAttribute('href'); link.setAttribute('aria-disabled', 'true'); link.tabIndex = -1; }
  }
  function pagination() {
    get('demoReportPrevious').disabled = !running || !!controller || !total || offset <= 0;
    get('demoReportNext').disabled = !running || !!controller || total === null || offset + limit >= total;
    get('demoReportPageInfo').textContent = total === null ? 'Chưa tải dữ liệu' : total === 0 ? '0 bản ghi' : `${Math.min(offset + 1, total)}–${Math.min(offset + currentRows.length, total)} / ${total} bản ghi`;
    get('demoReportCount').textContent = total === null ? '—' : String(total);
  }
  async function loadOptions() {
    if (optionsLoaded) return true; if (optionsPromise) return optionsPromise;
    const request = new AbortController(), actor = user(); optionsController = request;
    optionsPromise = (async () => {
      try {
        const result = await api('/api/v1/history/filters', {signal: request.signal, timeoutMs: 6000});
        if (request.signal.aborted || !running || !eligible() || actor !== user()) return false;
        options = emptyOptions(); for (const key of Object.keys(options)) options[key] = Array.isArray(result?.[key]) ? result[key] : [];
        populateOptions(); optionsLoaded = true; return true;
      } catch (error) { if (!request.signal.aborted && eligible() && actor === user()) setStatus('Không tải được bộ lọc. Chọn Tải lại để thử lại.', 'error'); return false; }
      finally { if (optionsController === request) { optionsController = null; optionsPromise = null; } }
    })(); return optionsPromise;
  }
  function time(value, timezone) { if (!value) return 'Chưa ghi nhận'; const date = new Date(value); if (!Number.isFinite(date.getTime())) return 'Chưa ghi nhận'; try { return date.toLocaleString('vi-VN', {timeZone: timezone || 'Asia/Ho_Chi_Minh', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'}); } catch (_) { return date.toISOString(); } }
  function sequence(value) { return Number.isSafeInteger(value) && value > 0 ? '#' + String(value).padStart(4, '0') : '—'; }
  function recognitionState(row) {
    const pad = String(row.pad_status || '').toUpperCase(), face = String(row.faceid_status || '').toUpperCase(), status = String(row.status || '').toUpperCase();
    const blocked = ['FAIL', 'BLOCKED'].includes(pad) || face === 'REJECTED' || status === 'SPOOF_BLOCKED';
    const verified = row.recognized === true && face === 'VERIFIED' && pad === 'PASS' && !blocked;
    return {verified, label: verified ? 'Đã xác minh' : blocked ? 'Không qua xác minh' : face === 'UNKNOWN' || ['UNREGISTERED', 'UNKNOWN'].includes(status) ? 'Chưa xác định' : 'Đang kiểm tra', tone: verified ? 'good' : blocked ? 'bad' : 'pending'};
  }
  const attendanceLabel = row => row.schedule_state === 'UNCONFIGURED' ? 'Chưa cấu hình ca' : ({PRESENT: 'Đã ghi nhận', LATE: 'Đi muộn', ABSENT: 'Vắng', NOT_YET_DUE: 'Chưa đến hạn kết luận', IN_PROGRESS: 'Ca đang diễn ra', MISSING_OUT: 'Thiếu ghi nhận ra', UNSCHEDULED: 'Chưa cấu hình ca'})[row.status] || 'Chưa đủ dữ liệu';
  function checkout(row) { return ['GATE_OUT', 'APPROVED_CORRECTION'].includes(row.checkout_source) && row.checkout_at ? time(row.checkout_at, row.timezone_name) : 'Chưa ghi nhận ra'; }
  function cell(row, text, small = '') { const td = node('td'); td.append(node('span', '', text)); if (small) td.append(node('small', 'demo-report-cell-note', small)); row.append(td); return td; }
  function fieldsDetail(entries) { for (const [label, text] of entries) { const field = node('div', 'demo-report-detail-field'); field.append(node('span', '', label), node('strong', '', String(text))); detail.append(field); } }
  function safeSnapshot(value) { if (typeof value !== 'string' || !value.startsWith('/api/v1/') || /[\u0000-\u0020\\]/.test(value)) return ''; try { const url = new URL(value, location.origin); return url.origin === location.origin && ![...url.searchParams.keys()].some(key => /token|secret|password|credential/i.test(key)) ? value : ''; } catch (_) { return ''; } }
  function showRecognition(row) {
    const result = recognitionState(row); get('demoReportDetailTitle').textContent = `${sequence(row.daily_sequence)} · ${result.verified ? row.full_name || 'Đã xác minh' : result.label}`;
    const crop = node('div', 'demo-report-detail-photo'), image = node('img'), placeholder = node('span', '', 'Chưa có ảnh được lưu cho sự kiện này.'); image.hidden = true; image.alt = 'Ảnh được lưu cho sự kiện'; crop.append(image, placeholder); detail.append(crop);
    const source = safeSnapshot(row.snapshot_url); if (source) { image.onload = () => { image.hidden = false; placeholder.hidden = true; }; image.onerror = () => { image.onload = null; image.onerror = null; image.hidden = true; placeholder.hidden = false; image.removeAttribute('src'); }; image.src = source; }
    fieldsDetail([['Trạng thái', result.label], ['Thời gian', time(row.occurred_at || row.event_at, row.timezone_name)], ['Ngày ghi nhận', row.business_date || 'Chưa ghi nhận'], ['Cửa hàng', row.store_name || 'Chưa ghi nhận'], ['Khu vực', row.zone_name || 'Chưa ghi nhận'], ['Camera', row.camera_name || 'Chưa ghi nhận'], ['Múi giờ', row.timezone_name || 'Chưa ghi nhận'], ['Nhân viên', result.verified ? row.full_name || '—' : 'Chưa xác định'], ['Mã nhân viên', result.verified ? row.student_code || '—' : '—'], ['Bộ phận', result.verified ? row.department || '—' : '—'], ['Chống giả mạo', row.pad_status === 'PASS' ? 'Đã qua kiểm tra' : ['FAIL', 'BLOCKED'].includes(row.pad_status) ? 'Không qua kiểm tra' : 'Đang kiểm tra']]);
  }
  async function showAttendance(row) {
    get('demoReportDetailTitle').textContent = [row.full_name || 'Nhân viên', row.business_date].filter(Boolean).join(' · ');
    fieldsDetail([['Cửa hàng', row.store_name || 'Chưa ghi nhận'], ['Bộ phận', row.department || 'Chưa ghi nhận'], ['Ca', row.shift_name || 'Chưa cấu hình ca'], ['Ngày làm việc', row.business_date || 'Chưa ghi nhận'], ['Trạng thái', attendanceLabel(row)], ['Vào lần đầu', time(row.checkin_at || row.first_in_at, row.timezone_name)], ['Ra gần nhất', checkout(row)], ['Căn cứ giờ ra', row.checkout_source === 'APPROVED_CORRECTION' ? 'Điều chỉnh đã duyệt' : row.checkout_source === 'GATE_OUT' ? 'Sự kiện qua cổng' : 'Chưa ghi nhận'], ['Quan sát lần cuối', time(row.last_seen_at, row.timezone_name)], ['Giờ làm', 'Chưa đủ dữ liệu']]);
    const timeline = node('ol', 'demo-report-timeline'); timeline.append(node('li', '', 'Đang tải các mốc ghi nhận…')); detail.append(node('h4', '', 'Các mốc trong ngày làm việc'), timeline);
    const employee = positive(row.employee_id ?? row.student_id), store = positive(row.store_id); if (!employee || !store || !row.business_date) { timeline.replaceChildren(node('li', '', 'Chưa đủ dữ liệu để tra cứu các mốc.')); return; }
    const request = new AbortController(), owner = epoch, actor = user(); detailController = request;
    try {
      const query = new URLSearchParams({employee_id: String(employee), business_date: String(row.business_date), store_id: String(store)});
      const result = await api(`/api/v1/history/attendance/timeline?${query}`, {signal: request.signal, timeoutMs: 6000});
      if (request.signal.aborted || detailController !== request || owner !== epoch || actor !== user() || !eligible() || dialog.hidden) return;
      timeline.replaceChildren();
      for (const item of Array.isArray(result?.items) ? result.items : []) {
        const type = String(item.event_type || item.type || '').toUpperCase();
        const label = ({VALID_IN: 'Vào', IN: 'Vào', VALID_OUT: 'Ra', OUT: 'Ra', RECOGNITION: 'Nhận diện', LAST_OBSERVATION: 'Quan sát lần cuối', APPROVED_CHECKIN_CORRECTION: 'Điều chỉnh giờ vào đã duyệt', APPROVED_CHECKOUT_CORRECTION: 'Điều chỉnh giờ ra đã duyệt'})[type] || 'Mốc được ghi nhận';
        const sourceLabel = item.source === 'ATTENDANCE' ? 'Chấm công' : item.source === 'RECOGNITION' ? 'Nhận diện' : 'Chưa ghi nhận nguồn';
        const entry = node('li'); entry.append(node('strong', '', label), node('time', '', time(item.occurred_at || item.event_at || item.time, item.timezone_name || row.timezone_name)), node('span', '', sourceLabel), node('span', '', [item.store_name, item.zone_name, item.camera_name].filter(Boolean).join(' · ') || 'Chưa ghi nhận vị trí')); timeline.append(entry);
      }
      if (!timeline.children.length) timeline.append(node('li', '', 'Chưa có mốc được lưu cho ngày làm việc này.'));
      if (result.schedule_state === 'UNCONFIGURED') timeline.prepend(node('li', '', 'Chưa cấu hình ca cho ngày làm việc này.'));
      if (result.recognition_limit_reached) timeline.append(node('li', '', 'Danh sách hiện chỉ hiển thị các mốc nhận diện gần nhất.'));
    } catch (error) { if (!request.signal.aborted && detailController === request && eligible()) timeline.replaceChildren(node('li', '', 'Không tải được các mốc. Đóng và mở lại để thử.')); }
    finally { if (detailController === request) detailController = null; }
  }
  function openDetail(row, button) { if (!running || !eligible()) return; closeDetail(false); returnFocus = button; dialog.hidden = false; closeButton.focus(); if (mode === 'attendance') void showAttendance(row); else showRecognition(row); }
  function render(items) {
    closeDetail(false); currentRows = items; head.replaceChildren(); body.replaceChildren();
    const headings = mode === 'attendance' ? ['Ngày làm việc', 'Nhân viên', 'Bộ phận', 'Cửa hàng / ca', 'Vào lần đầu', 'Ra gần nhất', 'Quan sát lần cuối', 'Trạng thái', 'Giờ làm', 'Chi tiết'] : ['Số thứ tự', 'Thời gian', 'Người / đối tượng', 'Cửa hàng', 'Khu vực', 'Camera', 'Kết quả', 'Chi tiết'];
    const header = node('tr'); for (const title of headings) { const th = node('th', '', title); th.scope = 'col'; header.append(th); } head.append(header);
    for (const item of items) {
      const tr = node('tr');
      if (mode === 'attendance') {
        cell(tr, item.business_date || 'Chưa ghi nhận'); cell(tr, item.full_name || 'Nhân viên', item.employee_code || item.student_code || ''); cell(tr, item.department || 'Chưa ghi nhận'); cell(tr, item.store_name || 'Chưa ghi nhận', item.shift_name || 'Chưa cấu hình ca');
        cell(tr, time(item.checkin_at || item.first_in_at, item.timezone_name), item.attendance_adjusted && item.checkin_at !== item.raw_checkin_at ? 'Điều chỉnh đã duyệt' : ''); cell(tr, checkout(item), item.checkout_source === 'APPROVED_CORRECTION' ? 'Điều chỉnh đã duyệt' : '');
        cell(tr, time(item.last_seen_at, item.timezone_name)); cell(tr, attendanceLabel(item)); cell(tr, 'Chưa đủ dữ liệu');
      } else {
        const result = recognitionState(item); cell(tr, sequence(item.daily_sequence)); cell(tr, time(item.occurred_at || item.event_at, item.timezone_name)); cell(tr, result.verified ? item.full_name || 'Đã xác minh' : result.label, result.verified ? item.student_code || '' : '');
        cell(tr, item.store_name || 'Chưa ghi nhận'); cell(tr, item.zone_name || 'Chưa ghi nhận'); cell(tr, item.camera_name || 'Chưa ghi nhận'); const status = cell(tr, result.label); status.className = `demo-report-result ${result.tone}`;
      }
      const action = node('td'), button = node('button', 'demo-report-detail-button', 'Chi tiết'); button.type = 'button'; button.addEventListener('click', () => openDetail(item, button)); action.append(button); tr.append(action); body.append(tr);
    }
    if (!items.length) { const tr = node('tr'), td = node('td', 'demo-report-empty', mode === 'attendance' ? 'Chưa cấu hình ca hoặc không có ca phù hợp bộ lọc.' : 'Không có sự kiện nhận diện phù hợp bộ lọc.'); td.colSpan = headings.length; tr.append(td); body.append(tr); }
  }
  function renderTotals(totals = {}) { for (const [id, key] of [['demoTotalShifts', 'scheduled_shifts'], ['demoTotalPresent', 'present_shifts'], ['demoTotalLate', 'late_cases'], ['demoTotalAbsent', 'absent_days'], ['demoTotalMissingOut', 'missing_out']]) { const number = totals[key]; get(id).textContent = Number.isSafeInteger(number) && number >= 0 ? String(number) : '—'; } }
  async function refreshVisits() {
    if (!running || !eligible() || !canVisit() || controller || mode !== 'visits') return;
    const ready = await loadOptions(); if (!ready || !running || !eligible() || !canVisit() || controller || mode !== 'visits') return;
    const day = value(visitDate); if (!validDate(day)) { setStatus('Chọn ngày hợp lệ để tra cứu lượt khách.', 'error'); return; }
    const storeId = positive(value(visitStore)); if (storeId && !options.stores.some(store => positive(store.id) === storeId)) { setStatus('Cửa hàng không thuộc danh sách được cấp quyền.', 'error'); return; }
    const query = new URLSearchParams({date: day}); if (storeId) query.set('store_id', String(storeId));
    const request = new AbortController(), owner = epoch, actor = user(); controller = request; visitContent.setAttribute('aria-busy', 'true'); setStatus('Đang tải lượt khách…');
    try {
      const report = await api(`/api/v1/history/visits?${query}`, {signal: request.signal, timeoutMs: 8000});
      if (request.signal.aborted || owner !== epoch || !running || !eligible() || !canVisit() || actor !== user() || mode !== 'visits') return;
      if (report?.date !== day || !Array.isArray(report.stores) || !Array.isArray(report.hourly) || !['READY', 'PARTIAL', 'UNCONFIGURED'].includes(report.configuration_state) || ![report.totals?.selected, report.totals?.previous].every(number => Number.isSafeInteger(number) && number >= 0) || typeof window.BTMHManagement?.renderVisitComparison !== 'function') throw new Error('INVALID_VISIT_REPORT');
      window.BTMHManagement.renderVisitComparison(visitContent, report, document); setStatus(`Lượt khách ghi nhận qua lối vào · ${day}.`);
    } catch (error) { if (!request.signal.aborted && owner === epoch && running && eligible() && actor === user()) { visitContent.replaceChildren(); setStatus(error.status === 403 ? 'Tài khoản chưa có quyền xem lượt khách trong phạm vi này.' : 'Không tải được lượt khách. Chọn Tải lại để thử lại.', 'error'); } }
    finally { if (controller === request) { controller = null; visitContent.setAttribute('aria-busy', 'false'); } }
  }
  async function refresh() {
    if (mode === 'visits') return refreshVisits();
    if (!running || !eligible() || mode === 'visits' || (mode === 'attendance' && !canAttend()) || controller) return;
    const optionsReady = await loadOptions(); if (!optionsReady || !running || !eligible() || controller || mode === 'visits' || (mode === 'attendance' && !canAttend())) return;
    let query; try { query = params(); } catch (error) { setStatus(error.message, 'error'); total = null; updateExport(); pagination(); return; }
    const request = new AbortController(), owner = epoch, actor = user(), enteredMode = mode; controller = request;
    get('demoReportTablePanel').setAttribute('aria-busy', 'true'); setStatus('Đang tải dữ liệu…'); pagination();
    try {
      const result = await api(`/api/v1/history/${enteredMode}?${query}`, {signal: request.signal, timeoutMs: 8000});
      if (request.signal.aborted || owner !== epoch || !running || !eligible() || actor !== user() || mode !== enteredMode) return;
      if (!Array.isArray(result?.items) || !Number.isSafeInteger(result.total) || result.total < 0 || !Number.isSafeInteger(result.limit) || result.limit <= 0 || !Number.isSafeInteger(result.offset) || result.offset < 0) throw new Error('Dữ liệu báo cáo không hợp lệ.');
      total = result.total; limit = result.limit; offset = result.offset; render(result.items); if (enteredMode === 'attendance') renderTotals(result.totals);
      setStatus(total ? `${total} bản ghi phù hợp bộ lọc.` : enteredMode === 'attendance' ? 'Chưa cấu hình ca hoặc chưa có ca phù hợp bộ lọc.' : 'Không có sự kiện nhận diện phù hợp bộ lọc.'); updateExport();
    } catch (error) {
      if (!request.signal.aborted && owner === epoch && running && eligible() && actor === user()) { currentRows = []; total = null; body.replaceChildren(); renderTotals(); setStatus(error.status === 403 ? 'Tài khoản chưa có quyền xem báo cáo này.' : 'Không tải được dữ liệu. Chọn Tải lại để thử lại.', 'error'); updateExport(); }
    } finally { if (controller === request) { controller = null; get('demoReportTablePanel').setAttribute('aria-busy', 'false'); pagination(); } }
  }
  function change() { retireQuery(); offset = 0; total = null; currentRows = []; body.replaceChildren(); populateOptions(); updateControls(); void refresh(); }
  function selectMode(next) {
    if (!['recognition', 'attendance', 'visits'].includes(next) || (next === 'attendance' && !canAttend()) || (next === 'visits' && !canVisit()) || mode === next) return;
    retireQuery(); mode = next; offset = 0; total = null; currentRows = []; fields.result.value = ''; resultOptions(); populateOptions(); body.replaceChildren(); renderTotals(); updateControls();
    visitContent.replaceChildren(); void refresh();
  }
  function start() { if (running || !eligible()) return; running = true; if ((mode === 'attendance' && !canAttend()) || (mode === 'visits' && !canVisit())) mode = 'recognition'; updateControls(); void refresh(); }
  function stop(reset = false) {
    running = false; retireQuery(); optionsController?.abort(); optionsController = null; optionsPromise = null; currentRows = []; total = null; body.replaceChildren(); visitContent.replaceChildren(); visitContent.setAttribute('aria-busy', 'false'); get('demoReportTablePanel').setAttribute('aria-busy', 'false'); renderTotals();
    if (reset) { options = emptyOptions(); optionsLoaded = false; mode = 'recognition'; offset = 0; fields.store.value = ''; fields.zone.value = ''; fields.camera.value = ''; fields.employee.value = ''; fields.department.value = ''; fields.subject.value = ''; fields.result.value = ''; fields.search.value = ''; visitStore.value = ''; visitDate.value = today(); populateOptions(); resultOptions(); }
    updateControls(); setStatus('Chọn bộ lọc để tra cứu báo cáo.');
  }
  const initialDay = today(); fields.period.value = 'DAY'; fields.start.value = initialDay; fields.end.value = initialDay; fields.month.value = initialDay.slice(0, 7); fields.year.value = initialDay.slice(0, 4);
  visitDate.value = initialDay;
  resultOptions(); populateOptions(); updateControls();
  for (const tab of tabs) tab.addEventListener('click', () => selectMode(tab.dataset.demoReport));
  get('demoReportTabs').addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; const available = tabs.filter(tab => !tab.disabled), current = available.indexOf(document.activeElement);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? available.length - 1 : event.key === 'ArrowRight' ? (current + 1) % available.length : (current <= 0 ? available.length : current) - 1;
    event.preventDefault(); const tab = available[index]; if (tab) { selectMode(tab.dataset.demoReport); tab.focus(); }
  });
  form.addEventListener('submit', event => { event.preventDefault(); change(); });
  fields.search.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); change(); } });
  for (const field of Object.values(fields)) field?.addEventListener('change', () => { if (field === fields.store) { fields.zone.value = ''; fields.camera.value = ''; fields.employee.value = ''; } if (field === fields.zone) fields.camera.value = ''; change(); });
  get('demoReportReset').addEventListener('click', () => {
    const day = today(); fields.period.value = 'DAY'; fields.start.value = fields.end.value = day; fields.month.value = day.slice(0, 7); fields.year.value = day.slice(0, 4);
    for (const name of ['store', 'zone', 'camera', 'employee', 'department', 'subject', 'result', 'search']) fields[name].value = '';
    change();
  });
  get('demoReportRefresh').addEventListener('click', () => { void refresh(); });
  const changeVisits = () => { retireQuery(); visitContent.replaceChildren(); visitContent.setAttribute('aria-busy', 'false'); void refresh(); };
  visitDate.addEventListener('change', changeVisits); visitStore.addEventListener('change', changeVisits); get('demoVisitsRefresh').addEventListener('click', () => { void refresh(); });
  for (const [id, days] of [['demoVisitsToday', 0], ['demoVisitsYesterday', 1]]) get(id).addEventListener('click', () => { const day = new Date(today() + 'T00:00:00Z'); day.setUTCDate(day.getUTCDate() - days); visitDate.value = day.toISOString().slice(0, 10); changeVisits(); });
  get('demoReportPrevious').addEventListener('click', () => { if (controller || offset <= 0) return; retireQuery(); offset = Math.max(0, offset - limit); void refresh(); });
  get('demoReportNext').addEventListener('click', () => { if (controller || total === null || offset + limit >= total) return; retireQuery(); offset += limit; void refresh(); });
  closeButton.addEventListener('click', () => closeDetail()); get('demoReportDetailBackdrop').addEventListener('click', () => closeDetail());
  dialog.addEventListener('keydown', event => { if (event.key === 'Escape') { event.preventDefault(); closeDetail(); } if (event.key === 'Tab') { event.preventDefault(); closeButton.focus(); } });
  document.addEventListener('btmh:navigate', event => { if (event.detail?.page === 'history') start(); else stop(); });
  document.addEventListener('btmh:auth', event => { stop(true); if (event.detail?.authenticated) start(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else start(); });
  window.addEventListener('pagehide', () => { presented = false; stop(); }); window.addEventListener('pageshow', () => { presented = true; start(); });
  window.BTMHDemoReports = {start, stop, refresh, selectMode}; start();
})();

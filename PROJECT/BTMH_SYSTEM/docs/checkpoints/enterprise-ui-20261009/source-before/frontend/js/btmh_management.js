/* Management presentation: scoped persisted facts, no media or AI ownership. */
(function (root, factory) {
  'use strict';
  const tools = factory();
  if (typeof module === 'object' && module.exports) module.exports = tools;
  if (!root.document) return;
  const host = root.document.getElementById('managementDashboard');
  if (!host) return;
  const byId = id => root.document.getElementById(id);
  const put = (id, value) => { const element = byId(id); if (element) element.textContent = value; };
  const eligible = () => !root.document.hidden && typeof appPresentationActive === 'function' && appPresentationActive() &&
    typeof hasUiPermission === 'function' && hasUiPermission('dashboard.view') && byId('page-dashboard')?.classList.contains('active');
  const store = byId('managementStore');
  const make = (tag, text, className = '') => { const element = root.document.createElement(tag); element.textContent = text; element.className = className; return element; };
  const clock = value => value ? new Date(value).toLocaleTimeString('vi-VN', {timeZone: 'Asia/Ho_Chi_Minh', hour: '2-digit', minute: '2-digit'}) : '—';
  const controller = tools.createController({eligible, request: options => api('/api/v1/dashboard/summary' +
    (store.value ? '?store_id=' + encodeURIComponent(store.value) : ''), options),
    loading: () => { host.setAttribute('aria-busy', 'true'); put('managementFeedback', 'Đang cập nhật dữ liệu…'); },
    success: render, error: () => { host.setAttribute('aria-busy', 'false'); clear(); put('managementFeedback', 'Không tải được tổng quan. Kiểm tra kết nối và chọn Làm mới.'); }});
  function clear() {
    for (const id of ['managementPresent', 'managementLate', 'managementAbsent', 'managementPending', 'managementMissingOut', 'managementCamera', 'managementIncidents']) put(id, '—');
    put('managementAttendanceNote', 'Chưa có dữ liệu cho lựa chọn hiện tại.');
    byId('managementRecent').replaceChildren(make('p', 'Chưa có dữ liệu nhận diện.', 'empty-card'));
    byId('managementVisits').replaceChildren(make('p', 'Chưa có dữ liệu lượt ghé.', 'empty-card'));
  }
  function render(data) {
    host.setAttribute('aria-busy', 'false');
    const attendance = data.attendance || {}, cameras = data.cameras || {};
    put('managementPresent', String(data.employee_with_valid_data_today ?? 0));
    put('managementLate', attendance.configured ? String(attendance.late_cases ?? 0) : '—');
    put('managementAbsent', attendance.configured ? String(attendance.absent_days ?? 0) : '—');
    put('managementPending', attendance.configured ? String(attendance.pending_shifts ?? 0) : '—');
    put('managementMissingOut', attendance.configured ? String(attendance.missing_out ?? 0) : '—');
    put('managementAttendanceNote', attendance.configured ? 'Đi muộn và vắng dựa trên ca đã phân công. Vắng chỉ được xác định sau giờ kết thúc ca.' : 'Chưa cấu hình ca cho ngày này. Chưa có kết luận đi muộn hoặc vắng.');
    put('managementCamera', `${cameras.online ?? 0} / ${cameras.total ?? 0}`);
    put('managementIncidents', data.incidents?.count_known ? String(data.incidents.open ?? 0) : 'Chưa có dữ liệu');
    put('managementFeedback', `Cập nhật ${clock(data.generated_at)} · Dữ liệu hôm nay`);
    const recent = byId('managementRecent'); recent.replaceChildren();
    for (const row of tools.publicRecent(data.latest).slice(0, 12)) {
      const line = make('li', '', 'btmh-management-event');
      const identity = make('div', ''); identity.append(make('b', row.name), make('small', row.location));
      line.append(identity, make('span', row.state, 'btmh-management-state'), make('time', clock(row.time)));
      recent.append(line);
    }
    if (!recent.children.length) recent.append(make('li', 'Chưa có nhận diện trong phạm vi đã chọn.', 'empty-card'));
    tools.renderVisitComparison(byId('managementVisits'), data.visits, root.document);
  }
  let optionEpoch = 0, optionController = null;
  async function loadStores() {
    if (!eligible() || optionController) return;
    const owner = ++optionEpoch, request = new AbortController(); optionController = request;
    try {
      const result = await api('/api/v1/stores', {signal: request.signal, timeoutMs: 6000});
      if (owner !== optionEpoch || request.signal.aborted || !eligible()) return;
      const selected = store.value; store.replaceChildren(make('option', 'Tất cả cửa hàng')); store.firstChild.value = '';
      for (const row of result.items || []) { const option = make('option', String(row.store_name || 'Cửa hàng')); option.value = String(row.id); store.append(option); }
      store.value = [...store.options].some(option => option.value === selected) ? selected : '';
      store.disabled = false;
    } catch (error) { if (!request.signal.aborted && eligible()) { store.disabled = true; put('managementFeedback', 'Không tải được danh sách cửa hàng. Chọn Làm mới để thử lại.'); } }
    finally { if (optionController === request) optionController = null; }
  }
  function stop(clearData = false) { optionEpoch++; optionController?.abort(); optionController = null; controller.stop(); if (clearData) { store.replaceChildren(make('option', 'Tất cả cửa hàng')); store.firstChild.value = ''; clear(); } }
  function start() { if (!eligible()) return; void loadStores(); controller.start(); }
  store.addEventListener('change', () => { clear(); controller.refresh(true); });
  byId('managementRefresh').addEventListener('click', () => { void loadStores(); controller.refresh(true); });
  root.document.addEventListener('btmh:navigate', event => event.detail?.page === 'dashboard' ? start() : stop());
  root.document.addEventListener('btmh:auth', event => event.detail?.authenticated ? start() : stop(true));
  root.document.addEventListener('visibilitychange', () => root.document.hidden ? stop() : start());
  root.addEventListener('pagehide', () => stop());
  root.addEventListener('pageshow', start);
  root.BTMHManagement = {...tools, start, stop, refresh: () => controller.refresh()};
  start();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  function createController({eligible, request, success, error, loading = () => {}, setTimer = setInterval, clearTimer = clearInterval}) {
    let generation = 0, pending = null, timer = null, running = false;
    async function refresh(replace = false) {
      if (!running || !eligible()) return;
      if (pending && !replace) return;
      if (replace) { generation++; pending?.abort(); pending = null; }
      const owner = generation, controller = new AbortController(); pending = controller; loading();
      try { const data = await request({signal: controller.signal, timeoutMs: 8000});
        if (owner === generation && !controller.signal.aborted && running && eligible()) success(data);
      } catch (reason) { if (owner === generation && !controller.signal.aborted && running && eligible()) error(reason); }
      finally { if (pending === controller) pending = null; }
    }
    return {refresh, start() { if (!eligible()) return; running = true; if (timer === null) timer = setTimer(refresh, 15000); void refresh(); },
      stop() { running = false; generation++; pending?.abort(); pending = null; if (timer !== null) clearTimer(timer); timer = null; }};
  }
  function comparisonText(row = {}) {
    if (row.change_state === 'NEW_ACTIVITY') return 'Có lượt ghé mới';
    if (row.change_state === 'UNCHANGED') return 'Không đổi';
    if (!Number.isFinite(row.percent)) return 'Chưa đủ dữ liệu so sánh';
    return `${row.percent > 0 ? '+' : ''}${row.percent.toLocaleString('vi-VN', {maximumFractionDigits: 1})}%`;
  }
  function publicRecent(input) {
    return (Array.isArray(input) ? input : []).map(row => ({
      name: row.faceid_status === 'VERIFIED' && row.recognized === true ? String(row.full_name || 'Nhân viên') : row.subject_type === 'VISITOR' ? 'Khách' : 'Chưa xác định',
      state: row.faceid_status === 'VERIFIED' ? 'Đã xác minh' : row.faceid_status === 'REJECTED' ? 'Bị chặn' : row.faceid_status === 'CHECKING' ? 'Đang kiểm tra' : 'Chưa đăng ký',
      location: [row.store_name || 'Chưa có cửa hàng', row.zone_name || '', row.camera_name || 'Chưa có camera'].filter(Boolean).join(' · '),
      time: row.occurred_at || row.event_at || null}));
  }
  function visitLabels(report, today) {
    if (!today) { const parts = new Intl.DateTimeFormat('en', {timeZone: 'Asia/Ho_Chi_Minh', year: 'numeric', month: '2-digit', day: '2-digit'}).formatToParts(new Date()); const part = name => parts.find(row => row.type === name).value; today = `${part('year')}-${part('month')}-${part('day')}`; }
    return report.date === today ? ['Hôm nay', 'Hôm qua'] : [report.date || 'Ngày chọn', report.comparison_date || 'Ngày trước'];
  }
  function renderVisitComparison(host, report, document) {
    const make = (tag, text, className = '') => { const element = document.createElement(tag); element.textContent = text; element.className = className; return element; };
    host.replaceChildren();
    if (!report) { host.append(make('p', 'Chưa có dữ liệu lượt ghé.', 'empty-card')); return; }
    const configured = report.configuration_state === 'READY' || report.configuration_state === 'PARTIAL' || (report.stores || []).some(row => row.configuration_state !== 'UNCONFIGURED');
    host.append(make('p', configured ? 'Mỗi IN hợp lệ được tính một lượt ghé. Ra rồi vào lại được tính lượt mới.' : 'Chưa cấu hình đếm lượt ghé. Liên hệ quản trị viên để thiết lập camera cửa vào.', 'btmh-management-note'));
    const total = report.totals || {};
    const [selectedLabel, previousLabel] = visitLabels(report);
    if (!configured && !(total.selected > 0 || total.previous > 0)) return;
    const summary = make('p', `${selectedLabel} ${total.selected ?? 0} · ${previousLabel} ${total.previous ?? 0} · ${comparisonText(total)}`, 'btmh-visit-comparison'); host.append(summary);
    if (report.selected_day_in_progress) host.append(make('p', 'Ngày hiện tại chưa kết thúc; dữ liệu phụ thuộc thời gian camera hoạt động.', 'btmh-management-note'));
    if (report.configuration_state === 'PARTIAL') host.append(make('p', 'Một số camera chưa sẵn sàng. Số lượt dưới đây là các IN đã ghi nhận.', 'btmh-management-note'));
    const wrapper = make('div', '', 'table-wrap');
    const table = make('table', '', 'btmh-management-table');
    const head = make('thead', ''), heading = make('tr', '');
    for (const label of ['Cửa hàng', selectedLabel, previousLabel, 'Thay đổi']) { const cell = make('th', label); cell.scope = 'col'; heading.append(cell); } head.append(heading); table.append(head);
    const body = make('tbody', '');
    for (const row of report.stores || []) { const line = make('tr', '');
      line.append(make('td', row.store_name || 'Cửa hàng'), make('td', String(row.selected ?? 0)), make('td', String(row.previous ?? 0)), make('td', row.configuration_state === 'UNCONFIGURED' && !row.selected && !row.previous ? 'Chưa cấu hình' : comparisonText(row))); body.append(line); }
    table.append(body); wrapper.append(table); host.append(wrapper);
    const hours = report.hourly || [];
    if (hours.length) {
      const details = make('details', '', 'btmh-visit-hours'); details.append(make('summary', 'Theo giờ trong ngày'));
      const labels = make('p', 'Số lượt IN đã ghi nhận theo giờ địa phương của từng cửa hàng.', 'btmh-management-note'); details.append(labels);
      const chart = make('div', '', 'btmh-visit-hour-chart'); chart.setAttribute('role', 'list');
      chart.setAttribute('tabindex', '0'); chart.setAttribute('aria-label', 'Lượt ghé theo giờ, cuộn để xem đủ 24 giờ');
      const max = Math.max(1, ...hours.flatMap(row => [Number(row.selected) || 0, Number(row.previous) || 0]));
      hours.forEach((row, index) => { const column = make('div', '', 'btmh-visit-hour'); column.setAttribute('role', 'listitem');
        column.setAttribute('aria-label', `${row.hour ?? index} giờ: ${selectedLabel} ${row.selected || 0}, ${previousLabel} ${row.previous || 0}`);
        const bars = make('div', '', 'btmh-visit-hour-bars'); for (const key of ['previous', 'selected']) { const bar = make('i', '', key); bar.style.height = `${Math.max(0, Number(row[key]) || 0) / max * 100}%`; bar.title = `${row.hour ?? index}h · ${key === 'selected' ? selectedLabel : previousLabel}: ${row[key] || 0}`; bars.append(bar); }
        column.append(bars, make('small', `${row.hour ?? index}h`)); chart.append(column); });
      details.append(chart, make('p', `Cột đậm: ${selectedLabel} · Cột nhạt: ${previousLabel}`, 'btmh-management-note')); host.append(details);
    }
  }
  return {createController, comparisonText, publicRecent, visitLabels, renderVisitComparison};
});

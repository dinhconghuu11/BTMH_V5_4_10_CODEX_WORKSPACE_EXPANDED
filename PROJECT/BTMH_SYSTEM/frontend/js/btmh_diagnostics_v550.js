/* Passive, permission-gated technical details with one cancellable request owner. */
(() => {
  'use strict';
  if (window.BTMHDiagnosticsV550) return;
  const endpoint = '/api/v1/system/diagnostics/performance';
  const unknown = 'Chưa đo';
  let details, status, metrics, authReady = false, presented = true, denied = false;
  let epoch = 0, owner = null, timer = null, initialized = false;
  const number = (value, maximum = 1e15) => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= maximum ? value : null;
  const formatted = (value, unit = '', maximum) => {
    const safe = number(value, maximum);
    return safe === null ? unknown : `${Math.round(safe * 10) / 10}${unit}`;
  };
  const enumLabel = (value, labels) => typeof value === 'string' && Object.hasOwn(labels, value) ? labels[value] : unknown;
  const permission = () => authReady && typeof hasUiPermission === 'function' && hasUiPermission('system.diagnostics');
  const eligible = () => initialized && presented && !denied && permission() && details.open && !document.hidden && !!document.querySelector('#page-system.active');
  function setStatus(message) { if (status) status.textContent = message; }
  function halt() {
    epoch += 1;
    clearTimeout(timer); timer = null;
    owner?.controller.abort();
    metrics?.replaceChildren();
  }
  function browserMetrics() {
    let values = null;
    try {
      const snapshot = window.BTMHMedia?.stats?.();
      if (snapshot && typeof snapshot === 'object') values = Object.values(snapshot).slice(0, 64).filter(value => value && typeof value === 'object');
    } catch (_) {}
    const average = key => {
      const measured = (values || []).map(value => number(value[key], 10000)).filter(value => value !== null);
      return measured.length ? measured.reduce((sum, value) => sum + value, 0) / measured.length : null;
    };
    return {views: values?.length ?? null, rendered: average('renderedFps'), received: average('receivedFps'), decoded: average('decodedFps'), networkLatency: null};
  }
  function render(data) {
    const camera = data?.camera || {}, ai = data?.ai || {}, capture = data?.ai_capture || {};
    const gateway = data?.native_gateway || {}, fleet = data?.fleet || {}, recorder = data?.recorder || {}, resources = data?.resources || {};
    const faceid = ai.faceid || {}, pad = ai.pad || {}, browser = browserMetrics();
    const mib = value => number(value) === null ? null : value / 1048576;
    const row = (label, value) => {
      const item = document.createElement('div'), name = document.createElement('span'), measurement = document.createElement('strong');
      item.className = 'btmh-performance-metric'; name.textContent = label; measurement.textContent = value;
      item.append(name, measurement); return item;
    };
    const numeric = (label, value, unit = '', maximum) => row(label, formatted(value, unit, maximum));
    const items = [
      row('Camera', enumLabel(camera.state, {STOPPED: 'Đã dừng', STOPPING: 'Đang dừng', OPENING: 'Đang mở', ONLINE: 'Trực tuyến', RECONNECTING: 'Đang kết nối lại', ERROR: 'Lỗi kết nối'})),
      numeric('FPS capture', camera.capture_fps, ' FPS', 1000), numeric('FPS preview', camera.preview_fps, ' FPS', 1000),
      numeric('Chiều rộng nguồn', camera.actual_width, ' px', 32768), numeric('Chiều cao nguồn', camera.actual_height, ' px', 32768),
      numeric('Tuổi khung hình nguồn', camera.last_frame_age_ms, ' ms'), numeric('Camera kết nối lại', camera.reconnect_count),
      row('Tải AI', enumLabel(ai.load_state, {FIXED: 'Cố định', NORMAL: 'Bình thường', BUSY: 'Bận', HIGH: 'Cao', RECOVERING: 'Đang phục hồi'})),
      numeric('Tuổi mẫu AI', ai.sample_age_ms, ' ms'), numeric('FPS AI thực tế', ai.actual_fps, ' FPS', 1000), numeric('FPS AI mục tiêu', ai.target_fps, ' FPS', 1000),
      numeric('Detector', ai.detector_ms, ' ms'), numeric('Tracker', ai.tracker_ms, ' ms'), numeric('AI p95', ai.p95_ms, ' ms'),
      numeric('FPS FaceID', faceid.fps, ' FPS', 1000), numeric('FaceID xử lý', faceid.last_ms, ' ms'), numeric('FaceID độ trễ', faceid.last_latency_ms, ' ms'),
      numeric('FaceID tuổi kết quả', faceid.last_result_age_ms, ' ms'), numeric('FaceID chờ', faceid.pending), numeric('FaceID bỏ qua', faceid.dropped),
      numeric('FPS Passive PAD', pad.fps, ' FPS', 1000), numeric('PAD xử lý', pad.last_ms, ' ms'), numeric('PAD độ trễ', pad.last_latency_ms, ' ms'),
      numeric('PAD tuổi kết quả', pad.last_result_age_ms, ' ms'), numeric('PAD chờ', pad.pending), numeric('PAD bỏ qua', pad.dropped),
      numeric('Hàng đợi AI', ai.queue_depth), numeric('Khung AI bỏ qua', ai.dropped_frames),
      row('Luồng AI', enumLabel(capture.mode, {HIKVISION_SUBSTREAM: 'Luồng phụ Hikvision', MAIN_FALLBACK: 'Luồng chính dự phòng'})),
      numeric('FPS luồng AI', capture.capture_fps, ' FPS', 1000), numeric('Tuổi khung luồng AI', capture.frame_age_ms, ' ms'),
      numeric('Gateway session', gateway.app_session_count), numeric('Gateway session đang chờ', gateway.pending_session_count), numeric('Gateway khởi động lại', gateway.restart_count),
      numeric('Fleet reader leases', fleet.reader_count), numeric('Fleet readers trực tuyến', fleet.online_count), numeric('Recorder đang ghi', recorder.active_count),
      numeric('CPU', resources.cpu_percent, '%', 100), numeric('RAM', resources.ram_percent, '%', 100), numeric('RAM tiến trình', mib(resources.process_rss_bytes), ' MiB'),
      row('Chế độ GPU', enumLabel(resources.gpu_mode, {CPU: 'CPU', GPU_DETECTED: 'Đã phát hiện GPU', GPU_ASSISTED: 'GPU hỗ trợ'})),
      numeric('GPU', resources.gpu_utilization_percent, '%', 100), numeric('Bộ nhớ GPU', resources.gpu_memory_used_mb, ' MiB'),
      numeric('Views đang mở trong trình duyệt', browser.views), numeric('FPS hiển thị trung bình', browser.rendered, ' FPS', 1000),
      numeric('FPS nhận trung bình', browser.received, ' FPS', 1000), numeric('FPS giải mã trung bình', browser.decoded, ' FPS', 1000),
      numeric('Độ trễ mạng trình duyệt', browser.networkLatency, ' ms'),
    ];
    const group = (title, rows) => {
      const section = document.createElement('section'), heading = document.createElement('h3'), grid = document.createElement('div');
      section.className = 'btmh-diagnostic-group'; heading.textContent = title; grid.className = 'pr-metrics'; grid.append(...rows); section.append(heading,grid); return section;
    };
    metrics.replaceChildren(
      group('Tình trạng hệ thống', [items[0],...items.slice(31,37)]),
      group('Hiệu năng AI', items.slice(7,28)),
      group('Camera & luồng video', [...items.slice(1,7),...items.slice(28,31),...items.slice(43)]),
      group('Máy chủ & tài nguyên', items.slice(37,43)));
    setStatus('Đã cập nhật. Các chỉ số chưa có phép đo hiển thị “Chưa đo”.');
  }
  async function refresh() {
    if (!eligible() || owner) return;
    const current = {epoch, controller: new AbortController(), timedOut: false}; owner = current;
    setStatus('Đang tải chỉ số…');
    const deadline = setTimeout(() => { current.timedOut = true; current.controller.abort(); }, 8000);
    let onAbort;
    const aborted = new Promise((_, reject) => {
      onAbort = () => reject(new DOMException('Cancelled', 'AbortError'));
      current.controller.signal.addEventListener('abort', onAbort, {once: true});
    });
    try {
      const request = (async () => {
        const token = localStorage.getItem('campusface_token') || '';
        const response = await fetch(endpoint, {method: 'GET', credentials: 'same-origin', cache: 'no-store', signal: current.controller.signal,
          headers: token ? {Authorization: `Bearer ${token}`} : {}});
        if (response.status === 401 || response.status === 403) current.denied = true;
        if (!response.ok) throw new Error('DIAGNOSTICS_UNAVAILABLE');
        return response.json();
      })();
      const data = await Promise.race([request, aborted]);
      if (owner !== current || current.epoch !== epoch || current.controller.signal.aborted || !eligible()) return;
      render(data);
    } catch (_) {
      if (owner === current && current.epoch === epoch && eligible()) {
        metrics.replaceChildren();
        if (current.denied) { denied = true; setStatus('Tài khoản không có quyền xem chẩn đoán hệ thống.'); }
        else setStatus(current.timedOut ? 'Yêu cầu quá hạn. Sẽ thử lại khi chi tiết còn mở.' : 'Chưa tải được chỉ số. Sẽ thử lại khi chi tiết còn mở.');
      }
    } finally {
      clearTimeout(deadline);
      current.controller.signal.removeEventListener('abort', onAbort);
      if (owner === current) {
        owner = null;
        if (eligible()) {
          if (current.epoch !== epoch) sync();
          else timer = setTimeout(() => { timer = null; void refresh(); }, 10000);
        }
      }
    }
  }
  function sync() {
    if (!eligible()) {
      halt();
      setStatus(denied ? 'Tài khoản không có quyền xem chẩn đoán hệ thống.' : permission() ? 'Mở chi tiết kỹ thuật để xem chỉ số.' : 'Cần quyền chẩn đoán hệ thống.');
      return;
    }
    if (!owner && timer === null) void refresh();
  }
  function initialize() {
    if (initialized) return;
    details = document.querySelector('#btmhPerformanceDetails'); status = document.querySelector('#btmhPerformanceStatus'); metrics = document.querySelector('#btmhPerformanceMetrics');
    if (!details || !status || !metrics) return;
    initialized = true; details.addEventListener('toggle', sync); sync();
  }
  document.addEventListener('btmh:auth', event => { authReady = !!event.detail?.authenticated; denied = false; halt(); sync(); });
  document.addEventListener('btmh:navigate', () => { halt(); sync(); });
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('pagehide', () => { presented = false; halt(); });
  window.addEventListener('pageshow', () => { presented = true; sync(); });
  window.BTMHDiagnosticsV550 = {sync, stop: halt};
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, {once: true}); else initialize();
})();

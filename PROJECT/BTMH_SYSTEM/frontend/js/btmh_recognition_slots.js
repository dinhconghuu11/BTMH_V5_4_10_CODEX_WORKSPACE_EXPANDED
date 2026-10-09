/* Recognition presentation. Selecting a camera never changes background AI. */
(function () {
  'use strict';
  const host = document.getElementById('recognitionSlots');
  if (!host) return;
  const singleView = host.dataset.layout === 'single';
  const slots = [];
  const strip = singleView ? document.getElementById('recognitionCameraStrip') : null;
  const previousCamera = document.getElementById('recognitionCameraPrevious'), nextCamera = document.getElementById('recognitionCameraNext');
  const switchCards = new Map();
  let cameras = new Map(), selected = 0, initialized = false, running = false;
  let epoch = 0, controller = null, refreshTimer = null, presented = true;
  const idOf = value => { const n = Number(value); return Number.isSafeInteger(n) && n > 0 ? n : null; };
  const text = (element, value) => { if (element && element.textContent !== value) element.textContent = value; };
  const eligible = () => presented && !document.hidden && document.getElementById('page-recognition')?.classList.contains('active') &&
    typeof appPresentationActive === 'function' && appPresentationActive() && typeof hasUiPermission === 'function' && hasUiPermission('camera.live');
  const create = (tag, className = '', value = '') => {
    const element = document.createElement(tag); element.className = className; element.textContent = value; return element;
  };
  const aiStates = {ACTIVE: 'AI đang hoạt động', WAITING_FOR_CAPACITY: 'AI chờ lượt xử lý', DISABLED: 'AI chưa bật', OFFLINE: 'AI mất kết nối', STOPPING: 'AI đang chuyển trạng thái', ERROR: 'AI gặp lỗi xử lý', PAUSED: 'AI đang tạm dừng', STARTING: 'AI đang khởi động'};
  const reasonCode = value => ['CAMERA_NOT_READY', 'AI_WORKER_START_FAILED', 'RETIREMENT_PENDING', 'CAPACITY_WAIT', 'AI_PROCESS_FAILED', 'AI_PAUSED', 'AI_STARTING'].includes(value) ? value : '';
  const aiText = camera => camera.ai_state === 'DISABLED' || camera.ai_enabled === false ? aiStates.DISABLED : !camera.store_id || !camera.zone_name.trim() ? 'AI cần cấu hình' : camera.reason_code === 'AI_WORKER_START_FAILED' ? 'AI chưa khả dụng' : aiStates[camera.ai_state] || 'Chưa có trạng thái AI';
  function context(raw) {
    const id = idOf(raw.camera_id ?? raw.id); if (!id) return null;
    // Only public context crosses into DOM/events. Connection sources stay on the server.
    return {id, camera_id: id, camera_name: String(raw.camera_name || raw.name || 'Camera'),
      store_id: idOf(raw.store_id), store_name: String(raw.store_name || ''), zone_name: String(raw.zone_name || ''),
      enabled: raw.enabled !== false, ai_enabled: raw.ai_enabled === true,
      ai_state: String(raw.ai_state || '').toUpperCase(), reason_code: reasonCode(raw.reason_code),
      ai_error_code: raw.ai_error_code === 'AI_PROCESS_FAILED' ? raw.ai_error_code : '', recording_active: raw.recording_active};
  }
  function notify() {
    renderSwitchStrip();
    const slot = slots[selected];
    document.dispatchEvent(new CustomEvent('btmh:recognition-selection', {detail: {
      slot: selected, camera: cameras.get(slot?.cameraId) || null, metadata: slot?.metadata || null
    }}));
  }
  function clearThumbnail(card) {
    card.preview.hidden = true;
    // Reset the bitmap as well as visibility so an old scope cannot retain camera pixels.
    card.preview.width = 176; card.preview.height = 99;
  }
  function renderSwitchStrip() {
    if (!strip) return;
    const visible = running && eligible(), selectedId = slots[selected]?.cameraId;
    const enabled = [...cameras.values()].filter(camera => camera.enabled);
    if (previousCamera) previousCamera.disabled = !visible || enabled.length < 2;
    if (nextCamera) nextCamera.disabled = !visible || enabled.length < 2;
    for (const [id, card] of switchCards) if (!visible || !cameras.get(id)?.enabled) {
      clearThumbnail(card); card.button.remove(); switchCards.delete(id);
    }
    if (!visible) return;
    for (const camera of enabled) {
      let card = switchCards.get(camera.id);
      if (!card) {
        const button = create('button', 'recognition-camera-choice'); button.type = 'button';
        const picture = create('span', 'recognition-camera-thumbnail'); picture.setAttribute('aria-hidden', 'true');
        const icon = create('span', 'recognition-camera-placeholder', '▣'), preview = create('canvas');
        picture.append(icon, preview);
        const name = create('strong'), location = create('span', 'recognition-camera-choice-location'), status = create('span', 'recognition-camera-choice-status');
        button.append(picture, name, location, status);
        card = {button, preview, name, location, status, selected: false, storeId: camera.store_id}; clearThumbnail(card); switchCards.set(camera.id, card);
        button.addEventListener('click', () => {
          if (running && eligible() && cameras.get(camera.id)?.enabled) selectCamera(0, camera.id);
        });
        strip.append(button);
      }
      const active = camera.id === selectedId;
      if (card.selected !== active || card.storeId !== camera.store_id) clearThumbnail(card);
      card.selected = active; card.storeId = camera.store_id;
      card.button.classList.toggle('is-selected', active); card.button.setAttribute('aria-pressed', String(active));
      card.button.setAttribute('aria-label', [camera.camera_name, camera.store_name, camera.zone_name, active ? 'Đang xem' : 'Xem camera'].filter(Boolean).join(' · '));
      text(card.name, camera.camera_name); text(card.location, camera.zone_name || 'Chưa gán khu vực');
      text(card.status, active ? 'Đang xem · ' + aiText(camera) : aiText(camera));
    }
  }
  function updateThumbnail(slot) {
    const card = switchCards.get(slot.cameraId);
    if (!card?.selected || !running || !eligible() || !slot.mounted) return;
    // Copy only the already displayed media layer. No extra reader, stream or frame API.
    const source = slot.wrap.querySelector?.('.btmh-media-active');
    const width = source?.videoWidth || source?.naturalWidth || source?.width;
    const height = source?.videoHeight || source?.naturalHeight || source?.height;
    if (!(width > 0 && height > 0)) return;
    try {
      const context = card.preview.getContext('2d'); if (!context) return;
      context.clearRect(0, 0, 176, 99);
      const scale = Math.min(176 / width, 99 / height), w = width * scale, h = height * scale;
      context.drawImage(source, (176 - w) / 2, (99 - h) / 2, w, h); card.preview.hidden = false;
    } catch (_) { clearThumbnail(card); }
  }
  function moveCamera(step) {
    if (!running || !eligible()) return;
    const enabled = [...cameras.values()].filter(camera => camera.enabled);
    if (enabled.length < 2) return;
    const current = enabled.findIndex(camera => camera.id === slots[selected]?.cameraId);
    selectCamera(0, enabled[(Math.max(0, current) + step + enabled.length) % enabled.length].id);
  }
  function selectSlot(index) {
    if (!slots[index]) return;
    selected = index;
    for (const slot of slots) {
      slot.card.classList.toggle('is-selected', slot.index === selected);
      slot.choose.setAttribute('aria-pressed', String(slot.index === selected));
    }
    notify();
  }
  function labels(slot) {
    const camera = cameras.get(slot.cameraId);
    text(slot.name, camera?.camera_name || `Ô camera ${slot.index + 1}`);
    text(slot.location, camera ? [camera.store_name || 'Chưa gán cửa hàng', camera.zone_name || 'Chưa gán khu vực'].join(' · ') : 'Chọn camera để xem');
    text(slot.ai, camera ? aiText(camera) : 'Chưa chọn camera');
    text(slot.recording, !camera ? '—' : camera.recording_active === true ? 'Đang ghi hình' : camera.recording_active === false ? 'Chưa ghi hình' : 'Chưa có trạng thái ghi hình');
    slot.fullscreen.disabled = !camera || !slot.card.requestFullscreen;
  }
  function stopSlot(slot) {
    const preview = switchCards.get(slot.cameraId); if (preview) clearThumbnail(preview);
    if (slot.mounted) window.BTMHMedia?.stop?.(slot.key);
    slot.mounted = false; slot.metadata = null;
    text(slot.live, 'Chưa kết nối'); slot.live.classList.remove('is-live');
    slot.empty.classList.remove('hidden');
    slot.empty.style.display = 'grid';
    text(slot.emptyText, slot.cameraId ? 'Đang chờ kết nối camera' : 'Chọn camera cho ô này');
  }
  function mount(slot) {
    const camera = cameras.get(slot.cameraId);
    labels(slot);
    if (!running || !eligible() || slot.mounted || !camera?.enabled || !window.BTMHMedia) return;
    text(slot.live, 'Đang kết nối'); text(slot.emptyText, 'Đang kết nối camera');
    slot.mounted = true;
    window.BTMHMedia.mount(slot.key, {cameraId: camera.id, quality: 'main',
      wrap: slot.wrap, video: slot.video, image: slot.image, overlay: slot.overlay, empty: slot.empty,
      fit: 'contain', mirror: false, mjpegUrl: `/api/v1/cameras/${camera.id}/stream.mjpg`, pollUrl: `/api/v1/cameras/${camera.id}/frame.jpg`});
  }
  function selectCamera(index, value) {
    const slot = slots[index]; if (!slot) return;
    const cameraId = idOf(value);
    if (cameraId && !cameras.has(cameraId)) return;
    if (slot.cameraId !== cameraId) { stopSlot(slot); slot.cameraId = cameraId; slot.select.value = cameraId ? String(cameraId) : ''; }
    selectSlot(index); mount(slot); labels(slot); notify();
  }
  function populate(slot) {
    slot.select.replaceChildren();
    const empty = create('option', '', 'Chưa chọn camera'); empty.value = ''; slot.select.append(empty);
    for (const camera of cameras.values()) {
      const option = create('option', '', [camera.camera_name, camera.store_name, camera.zone_name].filter(Boolean).join(' · '));
      option.value = String(camera.id); option.disabled = !camera.enabled; slot.select.append(option);
    }
    slot.select.value = slot.cameraId ? String(slot.cameraId) : '';
  }
  async function refresh() {
    if (!running || !eligible() || controller) return;
    const owner = ++epoch, request = new AbortController(); controller = request;
    try {
      const result = await api('/api/v1/recognition/cameras', {signal: request.signal, timeoutMs: 6000});
      if (owner !== epoch || request.signal.aborted || !running || !eligible()) return;
      const next = new Map();
      for (const raw of Array.isArray(result?.items) ? result.items : []) { const camera = context(raw); if (camera) next.set(camera.id, camera); }
      for (const slot of slots) {
        const previous = cameras.get(slot.cameraId), current = next.get(slot.cameraId);
        if (!current || current.ai_state !== 'ACTIVE' || previous?.ai_state !== current.ai_state || previous?.store_id !== current.store_id || previous?.zone_name !== current.zone_name || previous?.ai_enabled !== current.ai_enabled) slot.metadata = null;
      }
      cameras = next;
      const defaults = [...cameras.values()].filter(camera => camera.enabled);
      if (singleView) defaults.sort((a, b) => (b.ai_enabled ? b.ai_state === 'ACTIVE' ? 2 : 1 : 0) - (a.ai_enabled ? a.ai_state === 'ACTIVE' ? 2 : 1 : 0));
      for (const slot of slots) {
        if (!initialized) slot.cameraId = defaults[slot.index]?.id || null;
        if (slot.cameraId && (!cameras.has(slot.cameraId) || !cameras.get(slot.cameraId).enabled)) { stopSlot(slot); slot.cameraId = null; }
        populate(slot); mount(slot); labels(slot);
      }
      initialized = true;
      text(document.getElementById('recognitionSlotsNote'), cameras.size ? singleView ? 'Đổi camera đang xem không thay đổi AI nền hoặc ghi hình. Xem nhiều camera trong Camera & giám sát.' : 'Chọn một ô để xem kết quả. Đổi ô hiển thị không thay đổi AI hoặc ghi hình.' : 'Chưa có camera trong phạm vi tài khoản. Liên hệ người quản lý để cấu hình.');
      notify();
    } catch (error) {
      if (owner === epoch && !request.signal.aborted && running && eligible()) {
        text(document.getElementById('recognitionSlotsNote'), error.status === 403 ? 'Tài khoản chưa có quyền xem camera.' : 'Không tải được danh sách camera. Chọn Tải lại để thử lại.');
      }
    } finally { if (controller === request) controller = null; }
  }
  function start() {
    if (!eligible()) return;
    if (running) return;
    running = true;
    for (const slot of slots) mount(slot);
    void refresh();
    refreshTimer = setInterval(() => { void refresh(); }, 10000);
  }
  function stop(reset = false) {
    running = false; epoch++; controller?.abort(); controller = null;
    clearInterval(refreshTimer); refreshTimer = null;
    for (const slot of slots) { stopSlot(slot); if (reset) { slot.cameraId = null; populate(slot); } labels(slot); }
    if (reset) { cameras.clear(); initialized = false; for (const slot of slots) { populate(slot); labels(slot); } }
    const fullscreen = document.fullscreenElement;
    if (slots.some(slot => slot.card === fullscreen)) document.exitFullscreen?.().catch?.(() => {});
    notify();
  }
  host.replaceChildren();
  for (let index = 0; index < (singleView ? 1 : 4); index++) {
    const card = create('article', 'recognition-slot'), head = create('div', 'recognition-slot-head');
    const choose = create('button', 'recognition-slot-choose'), number = create('span', 'recognition-slot-number', String(index + 1));
    choose.type = 'button'; choose.setAttribute('aria-label', `Xem kết quả ô camera ${index + 1}`); choose.append(number);
    const name = create('strong', '', `Ô camera ${index + 1}`); choose.append(name); head.append(choose);
    const fullscreen = create('button', 'recognition-slot-fullscreen', 'Toàn màn hình'); fullscreen.type = 'button'; head.append(fullscreen);
    const location = create('p', 'recognition-slot-location', 'Chọn camera để xem');
    const label = create('label', 'recognition-slot-picker', 'Camera hiển thị'); const select = create('select');
    select.id = `recognitionSlotCamera${index}`; label.htmlFor = select.id; label.append(select);
    const wrap = create('div', 'camera-wrap entry-camera-wrap recognition-slot-viewport');
    const video = create('video'), image = create('img'), overlay = create('canvas');
    video.autoplay = true; video.playsInline = true; video.muted = true; image.alt = 'Hình ảnh camera';
    video.id = index === 0 ? 'recognitionVideo' : `recognitionVideo${index}`;
    overlay.id = index === 0 ? 'recognitionOverlay' : `recognitionOverlay${index}`;
    const empty = create('div', 'camera-empty'), emptyText = create('p', '', 'Chọn camera cho ô này');
    empty.id = index === 0 ? 'recognitionEmpty' : `recognitionEmpty${index}`; empty.append(emptyText);
    wrap.append(video, image, overlay, empty);
    const statuses = create('div', 'recognition-slot-status'), live = create('span', 'recognition-slot-live', 'Chưa kết nối');
    const ai = create('span', 'recognition-slot-ai', 'Chưa chọn camera'), recording = create('span', 'recognition-slot-recording', '—');
    statuses.append(live, ai, recording); card.append(head, location, label, wrap, statuses); host.append(card);
    const slot = {index, key: `recognition-slot-${index}`, card, choose, name, location, fullscreen, select, wrap, video, image, overlay, empty, emptyText, live, ai, recording, cameraId: null, metadata: null, mounted: false}; slots.push(slot);
    choose.addEventListener('click', () => selectSlot(index));
    wrap.addEventListener('click', () => selectSlot(index));
    select.addEventListener('change', () => selectCamera(index, select.value));
    fullscreen.addEventListener('click', async () => {
      if (!running || !eligible() || !slot.mounted || !card.requestFullscreen) return;
      selectSlot(index); const owner = epoch;
      try { await card.requestFullscreen(); if ((owner !== epoch || !eligible()) && document.fullscreenElement === card) await document.exitFullscreen?.(); }
      catch (_) { text(document.getElementById('recognitionSlotsNote'), 'Không mở được toàn màn hình. Vui lòng thử lại.'); }
    });
    populate(slot);
  }
  selectSlot(0);
  previousCamera?.addEventListener('click', () => moveCamera(-1));
  nextCamera?.addEventListener('click', () => moveCamera(1));
  document.getElementById('recognitionSlotsRefresh')?.addEventListener('click', () => { void refresh(); });
  document.addEventListener('btmh:media-metadata', event => {
    if (!running || !eligible()) return;
    const detail = event.detail || {}, slot = slots.find(item => item.key === detail.key), metadata = detail.meta;
    if (!slot?.mounted || !metadata || idOf(detail.cameraId) !== slot.cameraId || idOf(metadata.camera_id) !== slot.cameraId || !cameras.has(slot.cameraId)) return;
    const camera = cameras.get(slot.cameraId), state = String(metadata.ai_state || '').toUpperCase();
    if (Object.hasOwn(aiStates, state)) cameras.set(slot.cameraId, {...camera, ai_state: state, reason_code: reasonCode(metadata.reason_code), ai_error_code: metadata.ai_error_code === 'AI_PROCESS_FAILED' ? metadata.ai_error_code : ''});
    slot.metadata = metadata; labels(slot); if (slot.index === selected) notify();
  });
  const playback = event => {
    if (!running || !eligible()) return;
    const detail = event.detail || {}, slot = slots.find(item => item.key === detail.key);
    if (!slot?.mounted || (detail.cameraId != null && idOf(detail.cameraId) !== slot.cameraId)) return;
    const live = detail.state === 'live'; text(slot.live, live ? 'LIVE' : ['failed', 'offline', 'stopped'].includes(detail.state) ? 'Mất kết nối' : 'Đang kết nối');
    slot.live.classList.toggle('is-live', live);
    if (live) updateThumbnail(slot);
    else { const preview = switchCards.get(slot.cameraId); if (preview) clearThumbnail(preview); }
  };
  document.addEventListener('btmh:media-state', playback);
  document.addEventListener('btmh:media-stats', playback);
  document.addEventListener('btmh:navigate', event => { if (event.detail?.page === 'recognition') start(); else stop(); });
  document.addEventListener('btmh:auth', event => { stop(true); if (event.detail?.authenticated) start(); });
  document.addEventListener('btmh:camera-registry-changed', () => { void refresh(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else start(); });
  window.addEventListener('pagehide', () => { presented = false; stop(); });
  window.addEventListener('pageshow', () => { presented = true; start(); });
  window.BTMHRecognitionSlots = {start, stop, refresh, selectSlot, selectCamera,
    getSelection: () => ({slot: selected, camera: cameras.get(slots[selected]?.cameraId) || null, metadata: slots[selected]?.metadata || null})};
  start();
})();

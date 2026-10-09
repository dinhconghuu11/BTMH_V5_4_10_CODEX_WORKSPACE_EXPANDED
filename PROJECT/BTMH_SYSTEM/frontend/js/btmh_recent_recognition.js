/* Server-owned recent appearances for the selected recognition camera. */
(function () {
  'use strict';
  const host = document.getElementById('recentRecognitionItems');
  if (!host) return;
  const note = document.getElementById('recentRecognitionNote'), count = document.getElementById('recentRecognitionCount');
  const dialog = document.getElementById('recentRecognitionDetail'), detailContent = document.getElementById('recentRecognitionDetailContent');
  const closeButton = document.getElementById('recentRecognitionDetailClose');
  let camera = null, running = false, presented = true, epoch = 0, controller = null, timer = null;
  let rows = new Map(), cards = new Map(), detailKey = null, returnFocus = null, loaded = false;
  const MIN_REFRESH_MS = 10000, RECONCILE_MS = 30000;
  let dirty = false, dirtyAt = 0, lastRequestAt = 0, nextRefreshAt = 0, failures = 0, forbidden = false;
  const observations = new Map();
  const photoOwners = new Map();
  let photoQueue = [], photoInFlight = 0;
  const actor = () => typeof state === 'object' ? state.authUser : null;
  const say = text => { if (note && note.textContent !== text) note.textContent = text; };
  const idOf = value => { const n = Number(value); return Number.isSafeInteger(n) && n > 0 ? n : null; };
  const eligible = () => presented && !document.hidden && document.getElementById('page-recognition')?.classList.contains('active') &&
    typeof appPresentationActive === 'function' && appPresentationActive() && typeof hasUiPermission === 'function' && hasUiPermission('camera.live');
  const element = (tag, className = '', value = '') => { const node = document.createElement(tag); node.className = className; node.textContent = value; return node; };
  function sequence(value) { return Number.isSafeInteger(value) && value > 0 ? '#' + String(value).padStart(4, '0') : ''; }
  function stamp(value) { const date = new Date(value || ''); return Number.isFinite(date.getTime()) ? date.toLocaleString('vi-VN', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'}) : 'Chưa ghi nhận thời gian'; }
  function snapshot(value) {
    if (typeof value !== 'string' || !value.startsWith('/api/v1/') || /[\u0000-\u0020\\]/.test(value)) return '';
    try { const url = new URL(value, location.origin); return url.origin === location.origin && !url.username && !url.password && ![...url.searchParams.keys()].some(key => /token|secret|password|credential/i.test(key)) ? value : ''; }
    catch (_) { return ''; }
  }
  function normalize(raw) {
    if (idOf(raw.camera_id) !== idOf(camera?.camera_id)) return null;
    const appearance = raw.appearance_id == null ? '' : String(raw.appearance_id), eventId = raw.event_id ?? raw.id;
    const key = appearance ? `appearance:${appearance}` : idOf(eventId) ? `event:${eventId}` : '';
    if (!key) return null;
    const status = String(raw.status || '').toUpperCase(), pad = String(raw.pad_status || '').toUpperCase(), faceid = String(raw.faceid_status || '').toUpperCase();
    const blocked = status === 'SPOOF_BLOCKED' || faceid === 'REJECTED' || ['FAIL', 'BLOCKED'].includes(pad);
    const unknown = ['UNREGISTERED', 'UNKNOWN', 'UNKNOWN_PERSON'].includes(status) || faceid === 'UNKNOWN';
    const verified = raw.recognized === true && faceid === 'VERIFIED' && pad === 'PASS' && !unknown && !blocked;
    return {key, appearanceId: appearance, eventId, cameraId: idOf(raw.camera_id), sequence: sequence(raw.daily_sequence), businessDate: String(raw.business_date || ''),
      time: raw.occurred_at || raw.event_at || '', store: String(raw.store_name || ''), zone: String(raw.zone_name || ''), camera: String(raw.camera_name || ''),
      name: verified ? String(raw.full_name || 'Đã xác minh danh tính') : blocked ? 'Không qua xác minh' : unknown ? 'Chưa xác định' : 'Đang kiểm tra',
      code: verified ? String(raw.student_code || '') : '', department: verified ? String(raw.department || '') : '',
      subject: verified ? 'Nhân viên' : String(raw.subject_type || '').toUpperCase() === 'VISITOR' ? 'Người chưa có FaceID nhân viên' : 'Chưa xác định',
      state: verified ? 'Đã xác minh' : blocked ? 'Không qua xác minh' : unknown ? 'Chưa xác định' : 'Đang kiểm tra', tone: verified ? 'verified' : blocked ? 'blocked' : unknown ? 'unknown' : 'pending',
      pad: pad === 'PASS' ? 'Đã qua kiểm tra' : ['FAIL', 'BLOCKED'].includes(pad) ? 'Không qua kiểm tra' : 'Đang kiểm tra', snapshot: snapshot(raw.snapshot_url)};
  }
  function emptyPhoto(image, empty, message = 'Chưa có ảnh') {
    image.hidden = true; image.style.display = 'none';
    if (empty) { empty.hidden = false; empty.classList.remove('hidden'); empty.textContent = message; }
  }
  function releasePhoto(image) {
    const owner = photoOwners.get(image); photoOwners.delete(image); owner?.request.abort();
    photoQueue = photoQueue.filter(job => job.owner !== owner);
    if (owner?.objectUrl) URL.revokeObjectURL(owner.objectUrl);
    image.onload = null; image.onerror = null; image.removeAttribute('src');
  }
  function clearImages(root) { for (const image of root?.querySelectorAll('img') || []) releasePhoto(image); }
  function pumpPhotos() {
    while (photoInFlight < 3 && photoQueue.length) {
      const job = photoQueue.shift();
      if (job.owner.request.signal.aborted || photoOwners.get(job.owner.image) !== job.owner) continue;
      photoInFlight++;
      void job.run().finally(() => { photoInFlight--; pumpPhotos(); });
    }
  }
  function loadPhoto(image, empty, value, priority = false) {
    if (!image) return;
    const url = snapshot(value), allowed = eligible() && hasUiPermission('evidence.view');
    if (!url || !allowed) {
      releasePhoto(image); emptyPhoto(image, empty, allowed ? 'Chưa có ảnh' : 'Cần quyền xem ảnh bằng chứng'); return;
    }
    const previous = photoOwners.get(image);
    if (previous?.url === url && previous.actor === actor() && (!previous.failedAt || previous.permanentFailure || previous.attempts >= 3 || Date.now() - previous.failedAt < 5000)) return;
    releasePhoto(image); emptyPhoto(image, empty, 'Đang tải ảnh…');
    const owner = {image, url, empty, cameraId: idOf(camera?.camera_id), storeId: idOf(camera?.store_id), actor: actor(), request: new AbortController(), objectUrl: '', failedAt: 0,
      attempts: previous?.url === url && previous.actor === actor() ? previous.attempts + 1 : 1, permanentFailure: false};
    photoOwners.set(image, owner);
    const current = () => photoOwners.get(image) === owner && !owner.request.signal.aborted &&
      owner.actor === actor() && owner.cameraId === idOf(camera?.camera_id) && owner.storeId === idOf(camera?.store_id) && eligible() && hasUiPermission('evidence.view');
    const fail = (message, permanent = false) => {
      if (!current()) return;
      if (owner.objectUrl) URL.revokeObjectURL(owner.objectUrl); owner.objectUrl = '';
      image.onload = null; image.onerror = null; image.removeAttribute('src'); owner.failedAt = Date.now(); owner.permanentFailure = permanent; emptyPhoto(image, empty, message);
    };
    const job = {owner, run: async () => {
      try {
        if (!current()) return;
        // Use the same authenticated API path as the JSON, without credentials in image URLs.
        const response = await api(url, {rawResponse: true, signal: owner.request.signal, timeoutMs: 6000, credentials: 'same-origin', cache: 'no-store'});
        if (!current()) return;
        const blob = await response.blob();
        if (!current()) return;
        if (!blob.size || blob.size > 8 * 1024 * 1024 || !/^image\/(jpeg|png)$/i.test(blob.type)) throw new Error('INVALID_EVIDENCE_IMAGE');
        owner.objectUrl = URL.createObjectURL(blob);
        image.onload = () => { if (current()) { image.hidden = false; image.style.display = 'block'; if (empty) { empty.hidden = true; empty.classList.add('hidden'); } } };
        image.onerror = () => fail('Không mở được ảnh đã lưu');
        image.src = owner.objectUrl;
      } catch (error) {
        fail(error.status === 403 ? 'Không có quyền xem ảnh này' : error.status === 404 ? 'Lần xuất hiện chưa có ảnh đã lưu' : 'Chưa tải được ảnh; chọn Tải lại để thử', error.status === 403 || error.message === 'INVALID_EVIDENCE_IMAGE');
      }
    }};
    if (priority) photoQueue.unshift(job); else photoQueue.push(job); pumpPhotos();
  }
  function renderSelectedPhoto(detail = {}) {
    const image = document.getElementById('recognitionSnapshot'), empty = document.getElementById('recognitionSnapshotEmpty');
    if (!image) return;
    const selected = detail.camera, meta = detail.metadata;
    const active = selected?.ai_enabled !== false && !!idOf(selected?.store_id) && !!String(selected?.zone_name || '').trim() && String(selected?.ai_state || meta?.ai_state || '').toUpperCase() === 'ACTIVE';
    const tracks = active && !meta?.metadata_stale && idOf(selected?.camera_id) === idOf(camera?.camera_id) && idOf(selected?.store_id) === idOf(camera?.store_id) && idOf(meta?.camera_id) === idOf(camera?.camera_id) && Array.isArray(meta?.tracks) ? meta.tracks : [];
    const track = tracks.find(item => item.recognized && !item.spoof_blocked) || tracks[0];
    const classified = track && (track.recognized === true || track.spoof_blocked === true || track.unregistered === true || ['RECOGNIZED', 'UNREGISTERED', 'SPOOF_BLOCKED'].includes(track.status));
    const eventId = classified ? idOf(track.event_id) : null;
    image.alt = 'Ảnh đã lưu của lần xuất hiện đang chọn';
    loadPhoto(image, empty, eventId ? `/api/v1/events/${eventId}/evidence.jpg` : '', true);
  }
  function closeDetail(focus = true) {
    clearImages(detailContent); detailContent?.replaceChildren(); if (dialog) dialog.hidden = true;
    if (focus) returnFocus?.focus?.(); returnFocus = null; detailKey = null;
  }
  function photo(row, className = '') {
    const wrap = element('span', `recent-recognition-photo ${className}`), image = element('img'), empty = element('span', 'recent-recognition-photo-empty', 'Chưa có ảnh');
    // The image stays hidden until onload. Lazy-loading a hidden image defers the
    // very load event that reveals it; authenticated downloads are already bounded.
    image.alt = 'Ảnh được lưu cho lần xuất hiện'; image.hidden = true; image.loading = 'eager'; image.decoding = 'async'; wrap.append(image, empty);
    const update = value => loadPhoto(image, empty, value);
    update(row.snapshot); return {wrap, update};
  }
  function renderDetail(row) {
    if (!dialog || !detailContent) return;
    clearImages(detailContent); detailContent.replaceChildren();
    const title = document.getElementById('recentRecognitionDetailTitle'); if (title) title.textContent = [row.sequence, row.name].filter(Boolean).join(' · ');
    detailContent.append(photo(row, 'is-detail').wrap);
    const fields = [['Trạng thái', row.state], ['Thời gian', stamp(row.time)], ['Ngày ghi nhận', row.businessDate || 'Chưa ghi nhận'],
      ['Cửa hàng', row.store || 'Chưa ghi nhận'], ['Khu vực', row.zone || 'Chưa ghi nhận'], ['Camera', row.camera || 'Chưa ghi nhận'],
      ['Đối tượng', row.subject], ['Mã nhân viên', row.code || '—'], ['Bộ phận', row.department || '—'], ['Chống giả mạo', row.pad]];
    for (const [label, value] of fields) { const field = element('div', 'recent-recognition-detail-field'); field.append(element('span', '', label), element('strong', '', value)); detailContent.append(field); }
  }
  function openDetail(key, trigger) {
    const row = rows.get(key); if (!row || !running || !eligible() || !dialog) return;
    detailKey = key; returnFocus = trigger; renderDetail(row); dialog.hidden = false; closeButton?.focus();
  }
  function makeCard(row) {
    const li = element('li', 'recent-recognition-item'), button = element('button', 'recent-recognition-card'); button.type = 'button';
    const crop = photo(row), body = element('span', 'recent-recognition-copy'), name = element('strong'), seq = element('span', 'recent-recognition-sequence');
    const heading = element('span', 'recent-recognition-heading'); heading.append(seq, name);
    const state = element('span', 'recent-recognition-state'), when = element('time'), where = element('span', 'recent-recognition-location');
    body.append(heading, state, when, where); button.append(crop.wrap, body); li.append(button);
    button.addEventListener('click', () => openDetail(row.key, button));
    return {li, button, crop, name, seq, state, when, where};
  }
  function render(next, refreshDetail = false) {
    const detailChanged = detailKey && (refreshDetail || JSON.stringify(rows.get(detailKey)) !== JSON.stringify(next.get(detailKey)));
    for (const [key, card] of cards) if (!next.has(key)) { clearImages(card.li); card.li.remove(); cards.delete(key); }
    const empty = host.querySelector('.recent-recognition-empty'); if (next.size) empty?.remove();
    let index = 0;
    for (const row of next.values()) {
      const card = cards.get(row.key) || makeCard(row); cards.set(row.key, card);
      if (JSON.stringify(rows.get(row.key)) !== JSON.stringify(row)) {
      card.name.textContent = row.name; card.seq.textContent = row.sequence; card.seq.hidden = !row.sequence;
      card.state.textContent = row.state; card.state.className = `recent-recognition-state ${row.tone}`;
      card.when.textContent = stamp(row.time); card.where.textContent = [row.store, row.zone, row.camera].filter(Boolean).join(' · ') || 'Chưa ghi nhận vị trí';
      card.button.setAttribute('aria-label', [row.sequence, row.name, row.state, stamp(row.time)].filter(Boolean).join(' · '));
      }
      card.crop.update(row.snapshot);
      if (host.children[index] !== card.li) host.insertBefore(card.li, host.children[index] || null);
      index++;
      if (!observations.has(row.eventId)) remember(row.eventId, row.tone);
    }
    rows = next; if (count && count.textContent !== String(rows.size)) count.textContent = String(rows.size);
    if (!rows.size && !empty) host.append(element('li', 'recent-recognition-empty', camera ? 'Chưa có nhận diện được ghi nhận cho camera này.' : 'Chọn camera để xem nhận diện gần nhất.'));
    if (detailKey) {
      if (!rows.has(detailKey)) closeDetail(false);
      else if (detailChanged) renderDetail(rows.get(detailKey));
    }
  }
  function clear() { closeDetail(false); clearImages(host); host.replaceChildren(); cards.clear(); rows.clear(); if (count) count.textContent = '0'; }
  function remember(eventId, phase) {
    if (!idOf(eventId)) return;
    observations.set(eventId, phase);
    while (observations.size > 80) observations.delete(observations.keys().next().value);
  }
  function requestRefresh() {
    if (!running || !eligible()) return;
    if (!dirty) dirtyAt = Date.now() + 1000;
    dirty = true;
  }
  function observeMetadata(meta) {
    if (!meta || meta.metadata_stale || idOf(meta.camera_id) !== idOf(camera?.camera_id)) return;
    for (const track of Array.isArray(meta.tracks) ? meta.tracks : []) {
      const eventId = idOf(track.event_id); if (!eventId) continue;
      const phase = track.spoof_blocked || track.status === 'SPOOF_BLOCKED' ? 'blocked' : track.recognized ? 'verified' : track.unregistered || track.status === 'UNREGISTERED' ? 'unknown' : 'pending';
      if (observations.get(eventId) !== phase) { remember(eventId, phase); requestRefresh(); }
    }
  }
  function automaticRefresh() {
    if (!running || !eligible() || controller || forbidden) return;
    const now = Date.now(); if (failures && now < nextRefreshAt) return;
    if (now >= nextRefreshAt || (dirty && now >= dirtyAt && now - lastRequestAt >= MIN_REFRESH_MS)) void refresh();
  }
  async function refresh(announce = false) {
    const cameraId = idOf(camera?.camera_id); if (!running || !eligible() || !cameraId || controller) return;
    const owner = ++epoch, request = new AbortController(); controller = request;
    lastRequestAt = Date.now(); dirty = false; nextRefreshAt = lastRequestAt + RECONCILE_MS;
    host.setAttribute('aria-busy', 'true'); if (!loaded || announce) say(rows.size ? 'Đang cập nhật…' : 'Đang tải nhận diện gần nhất…'); loaded = true;
    if (announce) for (const [image, owner] of photoOwners) if (owner.failedAt) releasePhoto(image);
    try {
      const result = await api(`/api/v1/recognition/recent?limit=20&camera_id=${cameraId}`, {signal: request.signal, timeoutMs: 6000});
      if (request.signal.aborted || owner !== epoch || !running || !eligible() || cameraId !== idOf(camera?.camera_id)) return;
      const next = new Map();
      for (const raw of Array.isArray(result?.items) ? result.items : []) {
        const row = normalize(raw); if (!row || next.has(row.key)) continue;
        next.set(row.key, row); if (next.size === 20) break;
      }
      const first = next.values().next().value;
      render(next, announce);
      failures = 0; forbidden = false; nextRefreshAt = Date.now() + RECONCILE_MS;
      say(rows.size ? `Tối đa 20 lần xuất hiện gần nhất từ camera đang chọn.${first?.sequence ? ` Mới nhất: ${first.sequence} · ${first.state}.` : ''}` : 'Chưa có nhận diện được ghi nhận. Đổi camera hoặc thử tải lại.');
    } catch (error) {
      if (!request.signal.aborted && owner === epoch && running && eligible()) {
        failures++; forbidden = error.status === 403;
        nextRefreshAt = Date.now() + Math.min(120000, RECONCILE_MS * 2 ** Math.min(failures - 1, 2));
        if (!rows.size) { clear(); host.append(element('li', 'recent-recognition-empty', 'Không tải được nhận diện gần nhất.')); }
        say(error.status === 403 ? 'Tài khoản chưa có quyền xem dữ liệu này.' : 'Chưa cập nhật được dữ liệu. Chọn Tải lại để thử lại.');
      }
    } finally { if (controller === request) { controller = null; host.setAttribute('aria-busy', 'false'); } }
  }
  function start() {
    if (running || !eligible() || !idOf(camera?.camera_id)) return;
    running = true; void refresh(); timer = setInterval(automaticRefresh, 1000);
  }
  function stop(reset = false) {
    running = false; epoch++; controller?.abort(); controller = null; clearInterval(timer); timer = null;
    dirty = false; lastRequestAt = nextRefreshAt = failures = 0; forbidden = false; observations.clear();
    clear(); for (const image of [...photoOwners.keys()]) releasePhoto(image);
    const selectedImage = document.getElementById('recognitionSnapshot'); if (selectedImage) emptyPhoto(selectedImage, document.getElementById('recognitionSnapshotEmpty'));
    loaded = false; host.setAttribute('aria-busy', 'false'); if (reset) { camera = null; const heading = document.getElementById('recentRecognitionContext'); if (heading) heading.textContent = 'Chưa chọn camera'; }
    say(camera ? 'Nhận diện gần nhất theo camera đang chọn.' : 'Chọn camera để xem nhận diện gần nhất.');
  }
  function selection(detail = {}) {
    const next = detail.camera || null;
    if (idOf(next?.camera_id) !== idOf(camera?.camera_id) || idOf(next?.store_id) !== idOf(camera?.store_id)) { stop(); camera = next; render(new Map()); }
    else camera = next;
    if (!hasUiPermission('evidence.view')) for (const [image, owner] of photoOwners) { releasePhoto(image); emptyPhoto(image, owner.empty, 'Cần quyền xem ảnh bằng chứng'); }
    const heading = document.getElementById('recentRecognitionContext'); if (heading) heading.textContent = camera ? [camera.store_name, camera.zone_name, camera.camera_name].filter(Boolean).join(' · ') : 'Chưa chọn camera';
    if (!camera && !host.children.length) render(new Map());
    start(); observeMetadata(detail.metadata); renderSelectedPhoto(detail);
  }
  closeButton?.addEventListener('click', () => closeDetail());
  document.getElementById('recentRecognitionDetailBackdrop')?.addEventListener('click', () => closeDetail());
  dialog?.addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.preventDefault(); closeDetail(); }
    if (event.key === 'Tab') { event.preventDefault(); closeButton?.focus(); }
  });
  document.getElementById('recentRecognitionRefresh')?.addEventListener('click', () => { void refresh(true); });
  document.addEventListener('btmh:recognition-selection', event => selection(event.detail));
  document.addEventListener('btmh:navigate', event => { if (event.detail?.page === 'recognition') selection(window.BTMHRecognitionSlots?.getSelection?.()); else stop(); });
  document.addEventListener('btmh:auth', event => { stop(true); if (event.detail?.authenticated) selection(window.BTMHRecognitionSlots?.getSelection?.()); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else selection(window.BTMHRecognitionSlots?.getSelection?.()); });
  window.addEventListener('pagehide', () => { presented = false; stop(); });
  window.addEventListener('pageshow', () => { presented = true; selection(window.BTMHRecognitionSlots?.getSelection?.()); });
  window.BTMHRecentRecognition = {start, stop, refresh, requestRefresh, renderSelectedPhoto};
  selection(window.BTMHRecognitionSlots?.getSelection?.());
})();

/* Camera business configuration uses registry IDs and never reads or resends connection sources. */
(() => {
  'use strict';
  const get = id => document.getElementById(id), page = get('page-ops-center'), form = get('cameraConfigurationForm');
  if (!page || !form) return;
  const fields = Object.fromEntries(['Name', 'Store', 'Zone', 'ZoneId', 'Ai', 'Attendance', 'Visitors', 'Gate', 'GateName', 'X1', 'Y1', 'X2', 'Y2', 'Inside', 'Anchor', 'Roi', 'RoiX1', 'RoiY1', 'RoiX2', 'RoiY2', 'Deadband', 'Cooldown', 'Reacquire', 'Distance'].map(name => [name, get('cameraConfig' + name)]));
  const defaults = {enabled: false, name: '', x1: .15, y1: .55, x2: .85, y2: .55, inside_side: 'positive', anchor: 'person_center', roi: null, deadband: .025, cooldown_sec: 2.5, reacquire_sec: 2, max_distance: .12};
  let running = false, presented = true, epoch = 0, selected = null, cameras = new Map(), stores = [], listOwner = null, readOwner = null, saveOwner = null, loaded = false, storesLoaded = false, dirty = false, preview = false, observer = null, frame = null;
  let draft = null, editorActor = null;
  let zones = [], zonesLoaded = false, baseConfiguration = null;
  const idOf = value => { const number = Number(value); return typeof value !== 'boolean' && Number.isSafeInteger(number) && number > 0 ? number : null; };
  const user = () => typeof state === 'object' ? state.authUser : null;
  const permission = key => typeof hasUiPermission === 'function' && hasUiPermission(key);
  const editable = () => permission('camera.configure');
  const eligible = () => running && presented && !document.hidden && get('catalogCameraPanel')?.hidden !== true && page.classList.contains('active') && typeof appPresentationActive === 'function' && appPresentationActive() && permission('camera.live');
  const node = (tag, className = '', text = '') => { const element = document.createElement(tag); element.className = className; element.textContent = text; return element; };
  const value = field => String(field?.value || '').trim();
  const status = (text, error = false) => { get('cameraConfigurationNote').textContent = text; get('cameraConfigurationNote').classList.toggle('error', error); };
  const human = text => String(text || '').replace(/[\x00-\x1f\x7f]/g, ' ').replace(/(?:rtsps?|https?):\/\/\S+/gi, '[ẩn]').replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[ẩn]').slice(0, 120);
  const connection = camera => ({ONLINE: 'Trực tuyến', OFFLINE: 'Mất kết nối', UNKNOWN: 'Chưa ghi nhận'})[camera.connection_state] || 'Chưa ghi nhận';
  const aiLabel = camera => !camera.ai_enabled || camera.ai_state === 'DISABLED' ? 'AI đã tắt' : !camera.store_id || !String(camera.zone_name || '').trim() ? 'AI cần cấu hình' : camera.reason_code === 'AI_WORKER_START_FAILED' ? 'AI chưa khả dụng' : ({RUNNING: 'AI đang hoạt động', ACTIVE: 'AI đang hoạt động', STARTING: 'AI đang khởi động', STOPPING: 'AI đang dừng', ERROR: 'AI gặp lỗi xử lý', PAUSED: 'AI đang tạm dừng', OFFLINE: 'AI mất kết nối', WAITING_FOR_CAPACITY: 'AI chờ lượt xử lý', CAPACITY_BLOCKED: 'AI chờ lượt xử lý', WAITING: 'AI đang chờ'})[camera.ai_state] || 'Chưa có trạng thái AI';
  function controls() {
    const busy = !!readOwner || !!saveOwner, allowed = eligible() && editable() && loaded && storesLoaded && cameras.has(selected);
    for (const field of Object.values(fields)) field.disabled = !allowed || busy;
    fields.Zone.disabled = !allowed || busy || !!idOf(value(fields.ZoneId));
    get('cameraConfigZoneIdLabel').hidden = !zonesLoaded;
    get('cameraConfigurationSave').disabled = !allowed || busy; get('cameraConfigurationSave').textContent = saveOwner ? 'Đang lưu…' : 'Lưu cấu hình';
    get('cameraConfigurationCancel').disabled = !allowed || busy || !dirty;
    get('cameraConfigurationForm').hidden = !editable() || selected === null;
    get('cameraConfigurationPermission').hidden = editable();
    get('cameraConfigLineFields').hidden = !fields.Gate.checked;
    get('cameraConfigRoiFields').hidden = !fields.Gate.checked || !fields.Roi.checked;
    get('cameraConfigTuning').hidden = !fields.Gate.checked;
    get('cameraConfigurationPreview').disabled = !eligible() || !cameras.has(selected) || !!saveOwner;
    get('cameraConfigurationPreview').textContent = preview ? 'Dừng xem camera' : 'Xem camera để đặt lối vào';
  }
  function populateStores() {
    const previous = value(fields.Store); fields.Store.replaceChildren(); const empty = node('option', '', 'Chưa gán cửa hàng'); empty.value = ''; fields.Store.append(empty);
    for (const store of stores) { const option = node('option', '', human(store.store_name) || 'Cửa hàng'); option.value = String(store.id); fields.Store.append(option); }
    fields.Store.value = stores.some(store => String(store.id) === previous) ? previous : '';
    const filter = get('cameraConfigurationStoreFilter');
    if (filter) { const selected = filter.value, first = node('option','','Tất cả cửa hàng được cấp quyền'); first.value = ''; filter.replaceChildren(first); for (const store of stores) { const option = node('option','',human(store.store_name)||'Cửa hàng'); option.value = String(store.id); filter.append(option); } filter.value = [...filter.options].some(option => option.value === selected) ? selected : ''; }
  }
  function renderList() {
    const host = get('cameraConfigurationList'); host.replaceChildren(); get('cameraConfigurationCount').textContent = String(cameras.size);
    const query = String(get('cameraConfigurationSearch')?.value || '').trim().toLocaleLowerCase('vi-VN'), storeId = get('cameraConfigurationStoreFilter')?.value || '';
    for (const camera of cameras.values()) {
      if (storeId && String(camera.store_id) !== storeId || query && ![human(camera.camera_name||camera.name),human(camera.zone_name)].join(' ').toLocaleLowerCase('vi-VN').includes(query)) continue;
      const card = node('button', 'camera-config-card'); card.type = 'button'; card.dataset.cameraId = String(camera.camera_id); card.classList.toggle('selected', camera.camera_id === selected); card.setAttribute('aria-pressed', String(camera.camera_id === selected));
      card.append(node('strong', '', human(camera.camera_name || camera.name) || 'Camera'), node('span', 'camera-config-location', [human(camera.store_name) || 'Chưa gán cửa hàng', human(camera.zone_name) || 'Chưa đặt khu vực'].join(' · ')));
      const badges = node('div', 'camera-config-badges'); for (const text of [connection(camera), aiLabel(camera), camera.pad_state === 'ENABLED' ? 'Chống giả mạo bật' : 'Chống giả mạo chưa khả dụng', camera.recording_active === true ? 'Đang ghi hình' : 'Chưa ghi hình']) badges.append(node('span', '', text)); card.append(badges);
      card.addEventListener('click', () => { if (saveOwner || selected === camera.camera_id) return; if (dirty) { status('Cấu hình đang có thay đổi. Lưu hoặc Hủy thay đổi trước khi chọn camera khác.', true); return; } void select(camera.camera_id); }); host.append(card);
    }
    if (!cameras.size) host.append(node('p', 'camera-config-empty', 'Chưa có camera trong phạm vi được cấp quyền.'));
    else if (!host.children.length) host.append(node('p','camera-config-empty','Không có camera phù hợp với bộ lọc.'));
    get('cameraConfigurationEmpty').hidden = selected !== null;
  }
  function clearForm() { loaded = false; dirty = false; editorActor = null; baseConfiguration=null; form.reset(); fields.Name.value = ''; fields.Zone.value = ''; fields.Store.value = ''; get('cameraConfigurationTitle').textContent = 'Chọn camera'; controls(); diagram(); }
  function populateZones(current = null) {
    fields.ZoneId.replaceChildren();const empty=node('option','','Khu vực hiện tại / nhập tên');empty.value='';fields.ZoneId.append(empty);
    for(const zone of zones){if(String(zone.store_id)!==value(fields.Store)||zone.status!=='ACTIVE'&&idOf(zone.id)!==current)continue;const option=node('option','',human(zone.zone_name));option.value=String(zone.id);fields.ZoneId.append(option);}
    fields.ZoneId.value=[...fields.ZoneId.options].some(option=>idOf(option.value)===current)&&current?String(current):'';
  }
  function populate(camera) {
    const gate = {...defaults, ...(camera.entrance_config || {})}; fields.Name.value = human(camera.camera_name || camera.name); fields.Store.value = stores.some(store => idOf(store.id) === idOf(camera.store_id)) ? String(camera.store_id) : ''; fields.Zone.value = human(camera.zone_name);
    populateZones(idOf(camera.zone_id));
    fields.Ai.checked = camera.ai_enabled === true; fields.Attendance.checked = camera.attendance_enabled === true; fields.Visitors.checked = camera.visitor_counting_enabled === true; fields.Gate.checked = gate.enabled === true; fields.GateName.value = human(gate.name);
    for (const key of ['X1', 'Y1', 'X2', 'Y2']) fields[key].value = String(Number(gate[key.toLowerCase()]) * 100);
    fields.Inside.value = ['positive', 'negative'].includes(gate.inside_side) ? gate.inside_side : 'positive'; fields.Anchor.value = ['person_center', 'person_bottom', 'face_center'].includes(gate.anchor) ? gate.anchor : 'person_center'; fields.Roi.checked = !!gate.roi;
    for (const key of ['RoiX1', 'RoiY1', 'RoiX2', 'RoiY2']) { const roiKey = key.slice(3).toLowerCase(); fields[key].value = String(Number(gate.roi?.[roiKey] ?? (roiKey.endsWith('1') ? 0 : 1)) * 100); }
    for (const [field, key] of [['Deadband', 'deadband'], ['Cooldown', 'cooldown_sec'], ['Reacquire', 'reacquire_sec'], ['Distance', 'max_distance']]) fields[field].value = String(gate[key]);
    get('cameraConfigurationTitle').textContent = human(camera.camera_name || camera.name) || 'Camera'; loaded = true; dirty = false; editorActor = user(); controls(); diagram();
    try {baseConfiguration=configuration();}catch(_){baseConfiguration=null;}
  }
  function stopPreview() {
    if (preview) window.BTMHMedia?.stop?.('camera-configuration-preview'); preview = false; observer?.disconnect(); observer = null; if (frame !== null) cancelAnimationFrame(frame); frame = null;
    get('cameraConfigPreviewWrap').hidden = true; get('cameraConfigPreviewLine').hidden = true; get('cameraConfigPreviewState').textContent = 'Chưa mở camera'; controls();
  }
  function previewLayout() {
    frame = null; if (!preview || !eligible()) return; const wrap = get('cameraConfigPreviewWrap'), video = get('cameraConfigVideo'), image = get('cameraConfigImage'), svg = get('cameraConfigPreviewLine');
    const sw = !video.hidden && video.videoWidth ? video.videoWidth : image.naturalWidth, sh = !video.hidden && video.videoHeight ? video.videoHeight : image.naturalHeight;
    if (!sw || !sh) { svg.hidden = true; return; } const rect = window.BTMHMedia?.geometry?.fitRect?.(wrap.clientWidth, wrap.clientHeight, sw, sh, 'contain'); if (!rect) { svg.hidden = true; return; }
    Object.assign(svg.style, {left: rect.x + 'px', top: rect.y + 'px', width: rect.w + 'px', height: rect.h + 'px'}); svg.hidden = !fields.Gate.checked; diagram();
  }
  function scheduleLayout() { if (preview && frame === null) frame = requestAnimationFrame(previewLayout); }
  function togglePreview() {
    if (preview) { stopPreview(); return; } if (!eligible() || !cameras.has(selected) || !window.BTMHMedia?.mount) return;
    preview = true; const wrap = get('cameraConfigPreviewWrap'); wrap.hidden = false;
    window.BTMHMedia.mount('camera-configuration-preview', {cameraId: selected, quality: 'main', wrap, video: get('cameraConfigVideo'), image: get('cameraConfigImage'), empty: get('cameraConfigPreviewEmpty'), fit: 'contain', mirror: false, mjpegUrl: `/api/v1/cameras/${selected}/stream.mjpg`, pollUrl: `/api/v1/cameras/${selected}/frame.jpg`});
    if (typeof ResizeObserver === 'function') { observer = new ResizeObserver(scheduleLayout); observer.observe(wrap); } controls(); scheduleLayout();
  }
  function svgPart(svg, tag, attributes, text = '') { const element = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value)); element.textContent = text; svg.append(element); }
  function diagram() {
    const points = ['X1', 'Y1', 'X2', 'Y2'].map(key => Number(value(fields[key])) * 10), valid = points.every(number => Number.isFinite(number) && number >= 0 && number <= 1000);
    for (const id of ['cameraConfigDiagram', 'cameraConfigPreviewLine']) {
      const svg = get(id); svg.replaceChildren(); if (!valid) continue; const [x1, y1, x2, y2] = points, length = Math.hypot(x2 - x1, y2 - y1); if (length < 10) continue;
      if (fields.Roi.checked) { const roi = ['RoiX1', 'RoiY1', 'RoiX2', 'RoiY2'].map(key => Number(value(fields[key])) * 10); if (roi.every(Number.isFinite) && roi[2] > roi[0] && roi[3] > roi[1]) svgPart(svg, 'rect', {x: roi[0], y: roi[1], width: roi[2] - roi[0], height: roi[3] - roi[1], fill: '#ba94541a', stroke: '#ba9454', 'stroke-width': 4, 'stroke-dasharray': '12 10'}); }
      svgPart(svg, 'line', {x1, y1, x2, y2, stroke: '#f5cf83', 'stroke-width': 6}); for (const [x, y, label] of [[x1, y1, 'A'], [x2, y2, 'B']]) { svgPart(svg, 'circle', {cx: x, cy: y, r: 14, fill: '#f5cf83'}); svgPart(svg, 'text', {x: x + 20, y: y - 20, fill: '#fff', 'font-size': 34}, label); }
      const sign = value(fields.Inside) === 'negative' ? -1 : 1, cx = (x1 + x2) / 2, cy = (y1 + y2) / 2, dx = -(y2 - y1) / length * sign, dy = (x2 - x1) / length * sign;
      const tipX = cx + dx * 100, tipY = cy + dy * 100; svgPart(svg, 'line', {x1: cx - dx * 70, y1: cy - dy * 70, x2: tipX, y2: tipY, stroke: '#56d4a3', 'stroke-width': 8}); svgPart(svg, 'polyline', {points: `${tipX - dx * 25 - dy * 18},${tipY - dy * 25 + dx * 18} ${tipX},${tipY} ${tipX - dx * 25 + dy * 18},${tipY - dy * 25 - dx * 18}`, fill: 'none', stroke: '#56d4a3', 'stroke-width': 8}); svgPart(svg, 'text', {x: tipX + 15, y: tipY + 20, fill: '#83ecc4', 'font-size': 34}, 'Trong');
    }
  }
  function configuration() {
    const name = value(fields.Name), zone = value(fields.Zone), store = idOf(value(fields.Store));
    if (!name || name.length > 120 || /[\x00-\x1f\x7f]|(?:rtsps?|https?):\/\/|\b(?:\d{1,3}\.){3}\d{1,3}\b/i.test(name)) throw new Error('Tên camera phải từ 1 đến 120 ký tự và không chứa thông tin kết nối.');
    if ((fields.Ai.checked || fields.Visitors.checked) && (!store || !zone)) throw new Error('Chọn cửa hàng và khu vực trước khi bật AI hoặc đếm lượt khách.');
    if (fields.Visitors.checked && !fields.Gate.checked) throw new Error('Bật và cấu hình đường lối vào trước khi đếm lượt khách.');
    if (store && !stores.some(item => idOf(item.id) === store)) throw new Error('Cửa hàng không thuộc danh sách được cấp quyền.');
    const number = (field, low, high, scale = 1) => { const raw = value(fields[field]), result = Number(raw) / scale; if (!raw || !Number.isFinite(result) || result < low || result > high) throw new Error('Kiểm tra tọa độ và các giá trị cấu hình lối vào.'); return result; };
    const gate = {enabled: fields.Gate.checked, name: value(fields.GateName), x1: number('X1', 0, 1, 100), y1: number('Y1', 0, 1, 100), x2: number('X2', 0, 1, 100), y2: number('Y2', 0, 1, 100), inside_side: value(fields.Inside), anchor: value(fields.Anchor), deadband: number('Deadband', .001, .2), cooldown_sec: number('Cooldown', .1, 60), reacquire_sec: number('Reacquire', 0, 10), max_distance: number('Distance', .01, .5), roi: null};
    if (Math.hypot(gate.x2 - gate.x1, gate.y2 - gate.y1) < .01) throw new Error('Hai điểm A và B phải tạo thành một đường lối vào.');
    if (!['positive', 'negative'].includes(gate.inside_side) || !['person_center', 'person_bottom', 'face_center'].includes(gate.anchor)) throw new Error('Chọn phía trong và điểm theo dõi hợp lệ.');
    if (fields.Roi.checked) { gate.roi = Object.fromEntries(['X1', 'Y1', 'X2', 'Y2'].map(key => [key.toLowerCase(), number('Roi' + key, 0, 1, 100)])); const roi = gate.roi; if (roi.x1 >= roi.x2 || roi.y1 >= roi.y2 || ![[gate.x1, gate.y1], [gate.x2, gate.y2]].every(([x, y]) => x >= roi.x1 && x <= roi.x2 && y >= roi.y1 && y <= roi.y2)) throw new Error('Vùng theo dõi phải bao quanh toàn bộ đường A–B.'); }
    return {camera_name: name, store_id: store, zone_name: zone, ...(idOf(value(fields.ZoneId))?{zone_id:idOf(value(fields.ZoneId))}:{}), ai_enabled: fields.Ai.checked, attendance_enabled: fields.Attendance.checked, visitor_counting_enabled: fields.Visitors.checked, entrance_config: gate};
  }
  async function select(cameraId) {
    const id = idOf(cameraId); if (!eligible() || !cameras.has(id) || saveOwner) return; epoch++; readOwner?.controller.abort(); readOwner = null; stopPreview(); selected = id; clearForm(); renderList();
    if (!editable()) { status('Chọn camera để xem trạng thái. Cấu hình cần quyền quản lý camera.'); return; }
    if (!storesLoaded) { status('Chưa tải được danh sách cửa hàng. Chọn Tải lại để thử.', true); return; }
    const owner = {id, epoch, actor: user(), controller: new AbortController()}; readOwner = owner; controls(); status('Đang tải cấu hình camera…');
    try {
      const result = await api(`/api/v1/cameras/devices/${id}/configuration`, {signal: owner.controller.signal, timeoutMs: 6000}); if (readOwner !== owner || owner.controller.signal.aborted || owner.epoch !== epoch || owner.actor !== user() || !eligible()) return; if (idOf(result?.item?.camera_id ?? result?.item?.id) !== id) throw new Error('INVALID_CAMERA_CONTEXT'); populate(result.item);
      if (draft?.id === id && draft.actor === user() && editable()) {
        for (const [name, entry] of Object.entries(draft.fields)) { fields[name].value = entry.value; fields[name].checked = entry.checked; }
        if (!stores.some(store => idOf(store.id) === idOf(value(fields.Store)))) fields.Store.value = '';
        draft = null; dirty = true; controls(); diagram(); status('Đã khôi phục bản nháp của phiên này. Kiểm tra rồi Lưu cấu hình hoặc Hủy thay đổi.');
      } else status('Thay đổi chỉ được áp dụng khi bấm Lưu cấu hình.');
    }
    catch (_) { if (readOwner === owner && !owner.controller.signal.aborted && eligible()) status('Không tải được cấu hình camera. Chọn Tải lại để thử.', true); }
    finally { if (readOwner === owner) { readOwner = null; controls(); } }
  }
  async function refresh() {
    if (!eligible() || listOwner || saveOwner) return; const owner = {actor: user(), controller: new AbortController()}; listOwner = owner; get('cameraConfigurationList').setAttribute('aria-busy', 'true');
    try {
      const results = await Promise.allSettled([api('/api/v1/recognition/cameras', {signal: owner.controller.signal, timeoutMs: 6000}), editable() && permission('dashboard.view') ? api('/api/v1/stores', {signal: owner.controller.signal, timeoutMs: 6000}) : Promise.resolve(null),editable()&&window.BTMHCatalogs?api('/api/v1/zones',{signal:owner.controller.signal,timeoutMs:6000}):Promise.resolve(null)]);
      if (listOwner !== owner || owner.controller.signal.aborted || owner.actor !== user() || !eligible()) return;
      if (results[0].status !== 'fulfilled' || !Array.isArray(results[0].value?.items)) throw new Error('CAMERAS_UNAVAILABLE');
      cameras = new Map(); for (const camera of results[0].value.items) { const id = idOf(camera.camera_id ?? camera.id); if (id && !cameras.has(id)) cameras.set(id, {...camera, camera_id: id}); }
      storesLoaded = results[1].status === 'fulfilled' && Array.isArray(results[1].value?.items); stores = storesLoaded ? results[1].value.items.filter(item => idOf(item.id)) : []; populateStores();
      zonesLoaded=results[2].status==='fulfilled'&&results[2].value?.available===true&&Array.isArray(results[2].value?.items);zones=zonesLoaded?results[2].value.items:[];
      if (draft && (draft.actor !== user() || !editable() || !cameras.has(draft.id))) draft = null;
      if (draft && selected === null) selected = draft.id;
      if (!cameras.has(selected)) { epoch++; readOwner?.controller.abort(); readOwner = null; stopPreview(); selected = null; clearForm(); }
      renderList(); if (selected === null && cameras.size) void select(cameras.keys().next().value); else if (!dirty && selected !== null && editable()) void select(selected); else controls();
      if (!cameras.size) status('Chưa có camera trong phạm vi được cấp quyền.');
    } catch (_) { if (listOwner === owner && !owner.controller.signal.aborted && eligible()) status('Không tải được danh sách camera. Chọn Tải lại để thử.', true); }
    finally { if (listOwner === owner) { listOwner = null; get('cameraConfigurationList').setAttribute('aria-busy', 'false'); } }
  }
  async function save(event) {
    event?.preventDefault(); if (!eligible() || !editable() || !loaded || !storesLoaded || !cameras.has(selected) || readOwner || saveOwner) return;
    let payload; try { payload = configuration(); } catch (error) { status(error.message, true); return; }
    const owner = {id: selected, epoch, actor: user(), controller: new AbortController()}; saveOwner = owner; controls(); status('Đang lưu cấu hình…');
    try {
      const behavior=value=>JSON.stringify({...value,camera_name:undefined}), nameOnly=baseConfiguration&&behavior(payload)===behavior(baseConfiguration);
      const result = await api(`/api/v1/cameras/devices/${owner.id}/${nameOnly?'name':'configuration'}`, {method: nameOnly?'PATCH':'PUT', body: JSON.stringify(nameOnly?{camera_name:payload.camera_name}:payload), signal: owner.controller.signal, timeoutMs: 10000});
      if (saveOwner !== owner || owner.controller.signal.aborted || owner.epoch !== epoch || owner.actor !== user() || !eligible()) return;
      if (result?.ok !== true || idOf(result.item?.camera_id ?? result.item?.id) !== owner.id) throw new Error('SAVE_NOT_CONFIRMED');
      cameras.set(owner.id, {...cameras.get(owner.id), ...result.item, camera_id: owner.id, ai_state: result.item.ai_state || '', reason_code: result.item.reason_code || ''}); populate(result.item); renderList(); status('Đã lưu cấu hình camera. Các lần ghi nhận tiếp theo dùng cấu hình mới.'); document.dispatchEvent(new CustomEvent('btmh:camera-registry-changed'));
      // A configuration acknowledgment is not a runtime state. Read it back under the same request owner.
      try {
        const runtime = await api('/api/v1/recognition/cameras', {signal: owner.controller.signal, timeoutMs: 6000});
        if (saveOwner !== owner || owner.controller.signal.aborted || owner.epoch !== epoch || owner.actor !== user() || !eligible()) return;
        const camera = Array.isArray(runtime?.items) ? runtime.items.find(item => idOf(item.camera_id ?? item.id) === owner.id) : null;
        if (!camera) throw new Error('CAMERA_STATE_UNAVAILABLE');
        cameras.set(owner.id, {...cameras.get(owner.id), ...camera, camera_id: owner.id}); renderList();
      } catch (_) {
        if (saveOwner === owner && !owner.controller.signal.aborted && owner.epoch === epoch && owner.actor === user() && eligible()) status('Đã lưu cấu hình camera. Chưa cập nhật được trạng thái AI; chọn Tải lại để kiểm tra.');
      }
    } catch (error) { if (saveOwner === owner && !owner.controller.signal.aborted && eligible()) status(error.status === 403 ? 'Tài khoản không có quyền lưu cấu hình camera này.' : error.status === 409 ? 'Camera đang cập nhật. Giữ thay đổi và bấm Lưu để thử lại.' : 'Không lưu được cấu hình. Giữ thay đổi và kiểm tra cửa hàng, khu vực hoặc dung lượng AI trước khi thử lại.', true); }
    finally { if (saveOwner === owner) { saveOwner = null; controls(); } }
  }
  function start() { if (!presented || document.hidden || get('catalogCameraPanel')?.hidden === true || !page.classList.contains('active') || !appPresentationActive() || !permission('camera.live')) return; running = true; void refresh(); }
  function stop(reset = false) {
    if (reset || !user() || !editable() || !permission('camera.live') || (draft && draft.actor !== user())) draft = null;
    else if (loaded && dirty && editorActor === user() && selected !== null) draft = {id: selected, actor: editorActor, fields: Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, {value: field.value, checked: field.checked}]))};
    running = false; epoch++; listOwner?.controller.abort(); readOwner?.controller.abort(); saveOwner?.controller.abort(); listOwner = readOwner = saveOwner = null; stopPreview(); selected = null; cameras.clear(); clearForm(); renderList(); get('cameraConfigurationList').setAttribute('aria-busy', 'false');
    if (reset) { stores = []; storesLoaded = false; populateStores(); } status(draft ? 'Bản nháp được giữ trong phiên này; trở lại để lưu hoặc hủy.' : 'Chọn camera để quản lý cấu hình.');
  }
  form.addEventListener('submit', save); for (const field of Object.values(fields)) field.addEventListener('input', () => { if (!loaded || saveOwner) return; dirty = true; controls(); diagram(); scheduleLayout(); });
  fields.Store.addEventListener('change',()=>{populateZones();dirty=true;controls();});fields.ZoneId.addEventListener('change',()=>{const zone=zones.find(zone=>idOf(zone.id)===idOf(value(fields.ZoneId)));if(zone)fields.Zone.value=human(zone.zone_name);dirty=true;controls();});
  get('cameraConfigurationSearch')?.addEventListener('input',renderList); get('cameraConfigurationStoreFilter')?.addEventListener('change',renderList);
  get('cameraConfigurationCancel').addEventListener('click', () => { if (!saveOwner && selected !== null) void select(selected); }); get('cameraConfigurationRefresh').addEventListener('click', () => { void refresh(); }); get('cameraConfigurationPreview').addEventListener('click', togglePreview);
  for (const [id, type] of [['cameraConfigVideo', 'loadedmetadata'], ['cameraConfigImage', 'load']]) get(id).addEventListener(type, scheduleLayout); window.addEventListener('resize', scheduleLayout);
  document.addEventListener('btmh:media-state', event => { if (!preview || !eligible() || event.detail?.key !== 'camera-configuration-preview' || idOf(event.detail.cameraId) !== selected) return; get('cameraConfigPreviewState').textContent = event.detail.state === 'live' ? 'LIVE' : ['offline', 'failed', 'stopped'].includes(event.detail.state) ? 'Mất kết nối' : 'Đang kết nối'; scheduleLayout(); });
  document.addEventListener('btmh:navigate', event => { if (event.detail?.page === 'ops-center') start(); else stop(); }); document.addEventListener('btmh:auth', event => { stop(true); if (event.detail?.authenticated) start(); }); document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); else start(); });
  window.addEventListener('pagehide', () => { presented = false; stop(); }); window.addEventListener('pageshow', () => { presented = true; start(); }); window.BTMHCameraConfiguration = {start, stop, refresh, select}; controls(); start();
})();

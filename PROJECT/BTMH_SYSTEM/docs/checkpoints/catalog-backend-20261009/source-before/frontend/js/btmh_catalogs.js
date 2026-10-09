/* Scoped catalogs over existing APIs. No source credentials, schema or media ownership. */
(function (root, factory) {
  'use strict';
  const tools = factory();
  if (typeof module === 'object' && module.exports) module.exports = tools;
  if (!root.document) return;
  const doc = root.document, get = id => doc.getElementById(id), page = get('page-ops-center');
  if (!page || !get('catalogTabStores')) return;
  const permission = key => typeof hasUiPermission === 'function' && hasUiPermission(key);
  const actor = () => typeof state === 'object' ? state.authUser : null;
  let tab = 'stores', presented = true, stores = null, cameras = null, saving = null;
  const eligible = () => presented && !doc.hidden && page.classList.contains('active') && typeof appPresentationActive === 'function' && appPresentationActive() && permission('camera.live');
  const make = (tag, text = '', className = '') => { const el = doc.createElement(tag); el.textContent = text; el.className = className; return el; };
  const feedback = text => { get('catalogFeedback').textContent = text; };
  function table(host, headings, rows, empty) {
    host.replaceChildren();
    if (!rows.length) { host.append(make('p', empty, 'empty-card')); return; }
    const el = make('table', '', 'btmh-catalog-table'), head = make('thead'), line = make('tr'), body = make('tbody');
    headings.forEach(label => { const cell = make('th', label); cell.scope = 'col'; line.append(cell); }); head.append(line);
    rows.forEach(values => { const row = make('tr'); values.forEach(value => row.append(make('td', String(value)))); body.append(row); });
    el.append(head, body); host.append(el);
  }
  function render() {
    const query = get('catalogStoreSearch').value.trim().toLocaleLowerCase('vi-VN');
    const storeRows = tools.storeRows(stores, cameras).filter(row => !query || [row.code,row.name].join(' ').toLocaleLowerCase('vi-VN').includes(query));
    table(get('catalogStoreList'), ['Cửa hàng', 'Mã', 'Trạng thái', 'Múi giờ', 'Camera'], storeRows.map(row => [row.name,row.code,row.status,row.timezone,row.cameras]), stores === null ? 'Chưa tải được cửa hàng. Chọn Làm mới danh mục để thử lại.' : query ? 'Không có cửa hàng phù hợp.' : 'Chưa có cửa hàng trong phạm vi được cấp quyền.');
    const zoneQuery = get('catalogZoneSearch').value.trim().toLocaleLowerCase('vi-VN'), wanted = get('catalogZoneStore').value;
    const zones = tools.zoneRows(cameras).filter(row => (!wanted || String(row.storeId) === wanted) && (!zoneQuery || [row.name,row.store,row.cameras.join(' ')].join(' ').toLocaleLowerCase('vi-VN').includes(zoneQuery)));
    table(get('catalogZoneList'), ['Khu vực', 'Cửa hàng', 'Số camera', 'Camera được gán'], zones.map(row => [row.name,row.store,row.cameras.length,row.cameras.join(' · ')]), cameras === null ? 'Chưa tải được khu vực. Chọn Làm mới danh mục để thử lại.' : 'Chưa có khu vực phù hợp trong danh sách camera.');
    const select = get('catalogZoneStore'), selected = select.value, first = make('option', 'Tất cả cửa hàng được cấp quyền'); first.value = ''; select.replaceChildren(first);
    const known = new Map(tools.zoneRows(cameras).filter(row => row.storeId).map(row => [row.storeId,row.store]));
    for (const [id, name] of known) { const option = make('option', name); option.value = String(id); select.append(option); }
    select.value = [...select.options].some(option => option.value === selected) ? selected : '';
  }
  const reader = tools.createReader({eligible: () => eligible() && tab !== 'cameras', actor,
    request: async signal => {
      const result = await Promise.allSettled([
        permission('dashboard.view') ? api('/api/v1/stores', {signal,timeoutMs:6000}) : Promise.reject(new Error('STORES_DENIED')),
        api('/api/v1/recognition/cameras', {signal,timeoutMs:6000})]);
      return result.map(item => item.status === 'fulfilled' && Array.isArray(item.value?.items) ? item.value.items : null);
    }, loading: () => { get('catalogStoreList').setAttribute('aria-busy','true'); get('catalogZoneList').setAttribute('aria-busy','true'); feedback('Đang cập nhật danh mục…'); },
    success: result => { [stores,cameras] = result; render(); feedback(stores !== null && cameras !== null ? 'Danh mục đã cập nhật.' : 'Một phần danh mục chưa tải được hoặc tài khoản chưa có quyền xem. Chọn Làm mới để thử lại.'); },
    error: () => { stores = cameras = null; render(); feedback('Không tải được danh mục. Chọn Làm mới để thử lại.'); },
    settled: () => { get('catalogStoreList').setAttribute('aria-busy','false'); get('catalogZoneList').setAttribute('aria-busy','false'); }});
  function controls() {
    const allowed = eligible() && permission('system.manage');
    get('catalogAddStore').hidden = !allowed; get('catalogAddStore').disabled = !!saving;
    if (!allowed) get('catalogStoreForm').hidden = true;
    for (const id of ['catalogStoreSave','catalogStoreCancel','catalogStoreCode','catalogStoreName','catalogStoreTimezone','catalogRefresh']) get(id).disabled = !!saving || !eligible();
    get('catalogStoreSave').textContent = saving ? 'Đang lưu…' : 'Lưu cửa hàng';
    for (const button of doc.querySelectorAll('[data-catalog-tab]')) button.disabled = !!saving;
  }
  function selectTab(next, focus = false) {
    if (!['stores','zones','cameras'].includes(next) || saving) return;
    tab = next; reader.stop();
    for (const button of doc.querySelectorAll('[data-catalog-tab]')) { const active = button.dataset.catalogTab === tab; button.setAttribute('aria-selected',String(active)); button.tabIndex = active ? 0 : -1; if (active && focus) button.focus(); }
    for (const [name,id] of [['stores','catalogStorePanel'],['zones','catalogZonePanel'],['cameras','catalogCameraPanel']]) get(id).hidden = name !== tab;
    if (!eligible()) return;
    if (tab === 'cameras') { feedback('Chọn camera để xem hoặc thay đổi cấu hình.'); root.BTMHCameraConfiguration?.start?.(); }
    else { root.BTMHCameraConfiguration?.stop?.(); void reader.refresh(); }
    controls();
  }
  async function save(event) {
    event.preventDefault(); if (!eligible() || tab !== 'stores' || !permission('system.manage') || saving) return;
    const note = get('catalogStoreSaveNote'); let payload;
    try { payload = tools.storePayload(get('catalogStoreCode').value,get('catalogStoreName').value,get('catalogStoreTimezone').value); }
    catch (error) { note.textContent = error.message; return; }
    const owner = {actor:actor(),controller:new AbortController()}; saving = owner; controls(); note.textContent = 'Đang lưu cửa hàng…';
    try {
      const result = await api('/api/v1/stores', {method:'POST',body:JSON.stringify(payload),signal:owner.controller.signal,timeoutMs:8000});
      if (saving !== owner || owner.actor !== actor() || owner.controller.signal.aborted || !eligible() || !permission('system.manage')) return;
      if (!tools.saveConfirmed(result)) throw new Error('SAVE_UNCONFIRMED');
      get('catalogStoreForm').reset(); get('catalogStoreForm').hidden = true; note.textContent = ''; feedback('Đã tạo cửa hàng.');
      doc.dispatchEvent(new CustomEvent('btmh:stores-changed')); await reader.refresh();
      get('catalogAddStore').focus();
    } catch (error) {
      if (saving === owner && owner.actor === actor() && !owner.controller.signal.aborted && eligible()) note.textContent = error.status === 403 ? 'Tài khoản không có quyền thêm cửa hàng.' : 'Chưa xác nhận lưu thành công. Kiểm tra lại danh sách và mã cửa hàng trước khi thử lại.';
    } finally { if (saving === owner) { saving = null; controls(); } }
  }
  function start() { if (!eligible()) return; controls(); selectTab(tab); }
  function stop(reset = false) {
    reader.stop(); const pending = saving; saving?.controller.abort(); saving = null;
    if (pending) get('catalogStoreSaveNote').textContent = 'Lượt lưu chưa được xác nhận. Làm mới danh mục trước khi thử lại.';
    if (reset) { stores = cameras = null; get('catalogStoreForm').reset(); get('catalogStoreForm').hidden = true; get('catalogStoreSearch').value = ''; get('catalogZoneSearch').value = ''; get('catalogZoneStore').value = ''; render(); }
    controls();
  }
  for (const button of doc.querySelectorAll('[data-catalog-tab]')) {
    button.addEventListener('click', () => selectTab(button.dataset.catalogTab));
    button.addEventListener('keydown', event => { const tabs = [...doc.querySelectorAll('[data-catalog-tab]')], index = tabs.indexOf(button), next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : event.key === 'ArrowRight' ? (index+1)%tabs.length : event.key === 'ArrowLeft' ? (index+tabs.length-1)%tabs.length : null; if (next !== null) { event.preventDefault(); selectTab(tabs[next].dataset.catalogTab,true); } });
  }
  for (const id of ['catalogStoreSearch','catalogZoneSearch']) get(id).addEventListener('input',render);
  get('catalogZoneStore').addEventListener('change',render);
  get('catalogRefresh').addEventListener('click', () => tab === 'cameras' ? root.BTMHCameraConfiguration?.refresh?.() : void reader.refresh());
  get('catalogAddStore').addEventListener('click', () => { if (!eligible() || !permission('system.manage') || saving) return; get('catalogStoreForm').hidden = false; get('catalogStoreSaveNote').textContent = ''; get('catalogStoreCode').focus(); });
  get('catalogStoreCancel').addEventListener('click', () => { if (saving) return; get('catalogStoreForm').reset(); get('catalogStoreForm').hidden = true; get('catalogAddStore').focus(); }); get('catalogStoreForm').addEventListener('submit',save);
  doc.addEventListener('btmh:navigate', event => event.detail?.page === 'ops-center' ? start() : stop());
  doc.addEventListener('btmh:auth', event => { stop(true); if (event.detail?.authenticated) start(); });
  doc.addEventListener('visibilitychange', () => doc.hidden ? stop() : start());
  doc.addEventListener('btmh:camera-registry-changed', () => { cameras = null; if (eligible() && tab !== 'cameras') void reader.refresh(); });
  root.addEventListener('pagehide', () => { presented = false; stop(); }); root.addEventListener('pageshow', () => { presented = true; start(); });
  root.BTMHCatalogs = {start,stop,selectTab}; controls(); start();
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  const id = value => typeof value !== 'boolean' && Number.isSafeInteger(Number(value)) && Number(value)>0 ? Number(value) : null;
  const human = value => String(value || '').replace(/[\x00-\x1f\x7f]/g,' ').replace(/(?:rtsps?|https?):\/\/\S+/gi,'[ẩn]').slice(0,120);
  function storeRows(stores, cameras) { return (Array.isArray(stores) ? stores : []).filter(row => id(row.id)).map(row => ({id:id(row.id),code:human(row.store_code),name:human(row.store_name)||'Cửa hàng',status:row.status==='ACTIVE'?'Hoạt động':row.status==='INACTIVE'?'Ngừng hoạt động':'Chưa ghi nhận',timezone:human(row.timezone_name)||'—',cameras:Array.isArray(cameras)?cameras.filter(camera=>id(camera.store_id)===id(row.id)).length:'—'})); }
  function zoneRows(cameras) {
    const groups = new Map();
    for (const camera of Array.isArray(cameras) ? cameras : []) {
      const cameraId=id(camera.camera_id ?? camera.id), storeId=id(camera.store_id), name=human(camera.zone_name).trim(); if (!cameraId || !name) continue;
      const key=JSON.stringify([storeId,name]); if (!groups.has(key)) groups.set(key,{name,storeId,store:human(camera.store_name)||'Chưa gán cửa hàng',cameraIds:new Set(),cameras:[]});
      const row=groups.get(key); if (!row.cameraIds.has(cameraId)) {row.cameraIds.add(cameraId);row.cameras.push(human(camera.camera_name||camera.name)||'Camera');}
    }
    return [...groups.values()].map(({cameraIds,...row})=>row).sort((a,b)=>[a.store,a.name].join(' ').localeCompare([b.store,b.name].join(' '),'vi'));
  }
  function storePayload(code,name,timezone) {
    const store_code=String(code||'').trim().toUpperCase(), store_name=String(name||'').trim(), timezone_name=String(timezone||'').trim();
    if (store_code.length<2||store_code.length>80||!store_name||store_name.length>120) throw new Error('Nhập mã từ 2 ký tự và tên cửa hàng từ 1 đến 120 ký tự.');
    if (/[\x00-\x1f\x7f]|(?:rtsps?|https?):\/\//i.test(store_code+' '+store_name)) throw new Error('Mã và tên cửa hàng không được chứa địa chỉ kết nối.');
    try { new Intl.DateTimeFormat('vi-VN',{timeZone:timezone_name}); } catch (_) { throw new Error('Múi giờ chưa hợp lệ. Ví dụ: Asia/Ho_Chi_Minh.'); }
    return {store_code,store_name,timezone_name};
  }
  function saveConfirmed(result) { return result?.ok === true && id(result.store?.id) !== null; }
  function createReader({eligible,actor,request,success,error,loading=()=>{},settled=()=>{}}) {
    let epoch=0,owner=null;
    return {async refresh() {
      if (!eligible()) return; owner?.controller.abort(); const current={epoch:++epoch,actor:actor(),controller:new AbortController()}; owner=current; loading();
      try {const data=await request(current.controller.signal);if(owner===current&&current.epoch===epoch&&current.actor===actor()&&!current.controller.signal.aborted&&eligible())success(data);}
      catch(reason){if(owner===current&&current.epoch===epoch&&current.actor===actor()&&!current.controller.signal.aborted&&eligible())error(reason);}
      finally{if(owner===current){owner=null;settled();}}
    },stop(){epoch++;owner?.controller.abort();owner=null;settled();}};
  }
  return {storeRows,zoneRows,storePayload,saveConfirmed,createReader};
});

/* Scoped catalog APIs. Database migration is explicitly administered outside the UI. */
(function (root, factory) {
  'use strict';
  const tools = factory();
  if (typeof module === 'object' && module.exports) module.exports = tools;
  if (!root.document) return;
  const doc = root.document, get = id => doc.getElementById(id), page = get('page-ops-center');
  if (!page || !get('catalogTabStores')) return;
  const permission = key => typeof hasUiPermission === 'function' && hasUiPermission(key);
  const actor = () => typeof state === 'object' ? state.authUser : null;
  let tab = 'stores', presented = true, stores = null, cameras = null, zoneData = null, saving = null, editingStore = null, editingZone = null;
  const eligible = () => presented && !doc.hidden && page.classList.contains('active') && typeof appPresentationActive === 'function' && appPresentationActive() && permission('camera.live');
  const make = (tag, text = '', className = '') => { const el = doc.createElement(tag); el.textContent = text; el.className = className; return el; };
  const feedback = text => { get('catalogFeedback').textContent = text; };
  function table(host, headings, rows, empty) {
    host.replaceChildren();
    if (!rows.length) { host.append(make('p', empty, 'empty-card')); return; }
    const el = make('table', '', 'btmh-catalog-table'), head = make('thead'), line = make('tr'), body = make('tbody');
    headings.forEach(label => { const cell = make('th', label); cell.scope = 'col'; line.append(cell); }); head.append(line);
    rows.forEach(values => { const row = make('tr'); values.forEach(value => { const cell = make('td'); if (value && typeof value === 'object') cell.append(value); else cell.textContent = String(value); row.append(cell); }); body.append(row); });
    el.append(head, body); host.append(el);
  }
  function render() {
    const query = get('catalogStoreSearch').value.trim().toLocaleLowerCase('vi-VN');
    const storeRows = tools.storeRows(stores, cameras).filter(row => !query || [row.code,row.name].join(' ').toLocaleLowerCase('vi-VN').includes(query));
    table(get('catalogStoreList'), ['Cửa hàng', 'Mã', 'Trạng thái', 'Múi giờ', 'Camera', 'Thao tác'], storeRows.map(row => [row.name,row.code,row.status,row.timezone,row.cameras,actions([['Sửa',()=>openStore(row.id)]])]), stores === null ? 'Chưa tải được cửa hàng. Chọn Làm mới danh mục để thử lại.' : query ? 'Không có cửa hàng phù hợp.' : 'Chưa có cửa hàng trong phạm vi được cấp quyền.');
    const zoneQuery = get('catalogZoneSearch').value.trim().toLocaleLowerCase('vi-VN'), wanted = get('catalogZoneStore').value;
    const entities = tools.entityZones(zoneData?.items, cameras);
    const legacy = tools.zoneRows(Array.isArray(cameras) ? cameras.filter(camera=>!camera.zone_id) : null).map(row=>({...row,status:'Từ camera',count:row.cameras.length}));
    const zones = [...entities,...legacy].filter(row => (!wanted || String(row.storeId) === wanted) && (!zoneQuery || [row.name,row.store,row.cameras.join(' ')].join(' ').toLocaleLowerCase('vi-VN').includes(zoneQuery)));
    table(get('catalogZoneList'), ['Khu vực', 'Cửa hàng', 'Trạng thái', 'Số camera', 'Thao tác'], zones.map(row => [row.name,row.store,row.status,row.count,row.id?actions([['Sửa',()=>openZone(row.id)],...(!row.everAssigned&&row.count===0?[['Xóa',()=>removeZone(row.id)]]:[])]):'Quản lý trên camera']), cameras === null && zoneData === null ? 'Chưa tải được khu vực. Chọn Làm mới danh mục để thử lại.' : 'Chưa có khu vực phù hợp.');
    get('catalogZoneCapability').textContent = zoneData?.available === true ? 'Sửa hoặc lưu trữ khi khu vực không còn gắn camera. Chỉ xóa khu vực chưa từng được gán; lịch sử giữ nguyên.' : zoneData?.available === false ? 'Danh mục khu vực chưa được kích hoạt. Các khu vực hiện có vẫn quản lý trên camera.' : 'Chưa tải được danh mục khu vực. Các khu vực hiện có trên camera được hiển thị khi có dữ liệu.';
    const select = get('catalogZoneStore'), selected = select.value, first = make('option', 'Tất cả cửa hàng được cấp quyền'); first.value = ''; select.replaceChildren(first);
    const known = new Map([...tools.storeRows(stores,cameras).map(row=>[row.id,row.name]),...zones.filter(row=>row.storeId).map(row=>[row.storeId,row.store])]);
    for (const [id, name] of known) { const option = make('option', name); option.value = String(id); select.append(option); }
    select.value = [...select.options].some(option => option.value === selected) ? selected : '';
    controls();
  }
  function actions(items) {
    const host = make('div','','btmh-catalog-actions');
    if (!eligible() || !permission('system.manage')) return host;
    for (const [label,callback] of items) { const button=make('button',label,'btn ghost'); button.type='button'; button.disabled=!!saving; button.addEventListener('click',callback); host.append(button); }
    return host;
  }
  function openStore(id = null) {
    if (!eligible() || !permission('system.manage') || saving) return;
    const row = id === null ? null : stores?.find(row=>Number(row.id)===id); if (id !== null && !row) return;
    editingStore=id; get('catalogStoreForm').reset();
    get('catalogStoreFormTitle').textContent=row?'Sửa cửa hàng':'Thêm cửa hàng'; get('catalogStoreStatusLabel').hidden=!row;
    if (row) { get('catalogStoreCode').value=row.store_code; get('catalogStoreName').value=row.store_name; get('catalogStoreTimezone').value=row.timezone_name; get('catalogStoreStatus').value=row.status; }
    get('catalogStoreSaveNote').textContent=''; get('catalogStoreForm').hidden=false; get('catalogStoreCode').focus(); controls();
  }
  function openZone(id = null) {
    if (!eligible() || !permission('system.manage') || saving || zoneData?.available!==true) return;
    const row=id===null?null:zoneData.items.find(row=>Number(row.id)===id); if(id!==null&&!row)return;
    editingZone=id; get('catalogZoneForm').reset(); const select=get('catalogZoneFormStore'); select.replaceChildren();
    for(const store of stores||[]) {if(store.status!=='ACTIVE'&&Number(store.id)!==Number(row?.store_id))continue;const option=make('option',tools.human(store.store_name));option.value=String(store.id);select.append(option);}
    if(row) {select.value=String(row.store_id);get('catalogZoneName').value=row.zone_name;get('catalogZoneStatus').value=row.status;}
    get('catalogZoneFormTitle').textContent=row?'Sửa khu vực':'Thêm khu vực'; get('catalogZoneStatusLabel').hidden=!row; get('catalogZoneSaveNote').textContent='';get('catalogZoneForm').hidden=false;controls();get('catalogZoneName').focus();
  }
  const reader = tools.createReader({eligible: () => eligible() && tab !== 'cameras', actor,
    request: async signal => {
      const result = await Promise.allSettled([
        permission('dashboard.view') ? api('/api/v1/stores', {signal,timeoutMs:6000}) : Promise.reject(new Error('STORES_DENIED')),
        api('/api/v1/recognition/cameras', {signal,timeoutMs:6000}),api('/api/v1/zones',{signal,timeoutMs:6000})]);
      return [...result.slice(0,2).map(item => item.status === 'fulfilled' && Array.isArray(item.value?.items) ? item.value.items : null),result[2].status==='fulfilled'&&typeof result[2].value?.available==='boolean'&&Array.isArray(result[2].value?.items)?result[2].value:null];
    }, loading: () => { get('catalogStoreList').setAttribute('aria-busy','true'); get('catalogZoneList').setAttribute('aria-busy','true'); feedback('Đang cập nhật danh mục…'); },
    success: result => { [stores,cameras,zoneData] = result; render(); feedback(stores !== null && cameras !== null && zoneData !== null ? 'Danh mục đã cập nhật.' : 'Một phần danh mục chưa tải được hoặc tài khoản chưa có quyền xem. Chọn Làm mới để thử lại.'); },
    error: () => { stores = cameras = zoneData = null; render(); feedback('Không tải được danh mục. Chọn Làm mới để thử lại.'); },
    settled: () => { get('catalogStoreList').setAttribute('aria-busy','false'); get('catalogZoneList').setAttribute('aria-busy','false'); }});
  function controls() {
    const allowed = eligible() && permission('system.manage');
    get('catalogAddStore').hidden = !allowed; get('catalogAddStore').disabled = !!saving;
    get('catalogAddZone').hidden = !allowed || zoneData?.available!==true || stores===null; get('catalogAddZone').disabled=!!saving;
    if (!allowed) {get('catalogStoreForm').hidden = true;get('catalogZoneForm').hidden=true;}
    for (const id of ['catalogStoreSave','catalogStoreCancel','catalogStoreCode','catalogStoreName','catalogStoreTimezone','catalogStoreStatus','catalogZoneSave','catalogZoneCancel','catalogZoneName','catalogZoneStatus','catalogRefresh']) get(id).disabled = !!saving || !eligible();
    get('catalogZoneFormStore').disabled=!!saving||!eligible()||editingZone!==null;
    get('catalogStoreSave').textContent = saving ? 'Đang lưu…' : 'Lưu cửa hàng';
    get('catalogZoneSave').textContent = saving ? 'Đang lưu…' : 'Lưu khu vực';
    for (const button of doc.querySelectorAll('[data-catalog-tab]')) button.disabled = !!saving;
    for (const button of doc.querySelectorAll('.btmh-catalog-actions button')) button.disabled=!!saving||!allowed;
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
      if(editingStore!==null)payload.status=get('catalogStoreStatus').value;
      const result = await api(editingStore===null?'/api/v1/stores':`/api/v1/stores/${editingStore}`, {method:editingStore===null?'POST':'PATCH',body:JSON.stringify(payload),signal:owner.controller.signal,timeoutMs:8000});
      if (saving !== owner || owner.actor !== actor() || owner.controller.signal.aborted || !eligible() || !permission('system.manage')) return;
      if (!tools.saveConfirmed(result) || editingStore!==null&&Number(result.store.id)!==editingStore) throw new Error('SAVE_UNCONFIRMED');
      get('catalogStoreForm').reset(); get('catalogStoreForm').hidden = true; editingStore=null; note.textContent = ''; feedback('Đã lưu cửa hàng.');
      doc.dispatchEvent(new CustomEvent('btmh:stores-changed')); await reader.refresh();
      get('catalogAddStore').focus();
    } catch (error) {
      if (saving === owner && owner.actor === actor() && !owner.controller.signal.aborted && eligible()) note.textContent = tools.errorMessage(error);
    } finally { if (saving === owner) { saving = null; controls(); } }
  }
  async function saveZone(event) {
    event.preventDefault(); if(!eligible()||tab!=='zones'||!permission('system.manage')||saving||zoneData?.available!==true)return;
    const name=get('catalogZoneName').value.trim(), sid=Number(get('catalogZoneFormStore').value), note=get('catalogZoneSaveNote');
    if(!name||name.length>120||name!==tools.human(name)||!Number.isSafeInteger(sid)||sid<=0){note.textContent='Chọn cửa hàng và nhập tên khu vực hợp lệ.';return;}
    const id=editingZone, owner={actor:actor(),controller:new AbortController(),kind:'zones'};saving=owner;controls();note.textContent='Đang lưu khu vực…';
    try {
      const result=await api(id===null?'/api/v1/zones':`/api/v1/zones/${id}`,{method:id===null?'POST':'PATCH',body:JSON.stringify(id===null?{store_id:sid,zone_name:name}:{zone_name:name,status:get('catalogZoneStatus').value}),signal:owner.controller.signal,timeoutMs:8000});
      if(saving!==owner||owner.actor!==actor()||owner.controller.signal.aborted||!eligible()||!permission('system.manage'))return;
      if(!tools.itemConfirmed(result,id))throw new Error('SAVE_UNCONFIRMED');
      editingZone=null;get('catalogZoneForm').reset();get('catalogZoneForm').hidden=true;note.textContent='';feedback('Đã lưu khu vực.');doc.dispatchEvent(new CustomEvent('btmh:zones-changed'));await reader.refresh();get('catalogAddZone').focus();
    } catch(error){if(saving===owner&&owner.actor===actor()&&!owner.controller.signal.aborted&&eligible())note.textContent=tools.errorMessage(error);}
    finally{if(saving===owner){saving=null;controls();}}
  }
  async function removeZone(id) {
    if(!eligible()||tab!=='zones'||!permission('system.manage')||saving||!root.confirm('Xóa khu vực chưa từng được gán camera?'))return;
    const owner={actor:actor(),controller:new AbortController(),kind:'zones'};saving=owner;controls();
    try {const result=await api(`/api/v1/zones/${id}`,{method:'DELETE',signal:owner.controller.signal,timeoutMs:8000});if(saving!==owner||owner.actor!==actor()||owner.controller.signal.aborted||!eligible()||!permission('system.manage'))return;if(!tools.itemConfirmed(result,id))throw new Error('SAVE_UNCONFIRMED');doc.dispatchEvent(new CustomEvent('btmh:zones-changed'));await reader.refresh();}
    catch(error){if(saving===owner&&owner.actor===actor()&&!owner.controller.signal.aborted&&eligible())feedback(tools.errorMessage(error));}
    finally{if(saving===owner){saving=null;controls();}}
  }
  function start() { if (!eligible()) return; controls(); selectTab(tab); }
  function stop(reset = false) {
    reader.stop(); const pending = saving; saving?.controller.abort(); saving = null;
    if (pending) get(pending.kind==='zones'?'catalogZoneSaveNote':'catalogStoreSaveNote').textContent = 'Lượt lưu chưa được xác nhận. Làm mới danh mục trước khi thử lại.';
    if (reset) { stores = cameras = zoneData = null; editingStore=editingZone=null; get('catalogStoreForm').reset(); get('catalogStoreForm').hidden = true;get('catalogZoneForm').reset();get('catalogZoneForm').hidden=true; get('catalogStoreSearch').value = ''; get('catalogZoneSearch').value = ''; get('catalogZoneStore').value = ''; render(); }
    controls();
  }
  for (const button of doc.querySelectorAll('[data-catalog-tab]')) {
    button.addEventListener('click', () => selectTab(button.dataset.catalogTab));
    button.addEventListener('keydown', event => { const tabs = [...doc.querySelectorAll('[data-catalog-tab]')], index = tabs.indexOf(button), next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : event.key === 'ArrowRight' ? (index+1)%tabs.length : event.key === 'ArrowLeft' ? (index+tabs.length-1)%tabs.length : null; if (next !== null) { event.preventDefault(); selectTab(tabs[next].dataset.catalogTab,true); } });
  }
  for (const id of ['catalogStoreSearch','catalogZoneSearch']) get(id).addEventListener('input',render);
  get('catalogZoneStore').addEventListener('change',render);
  get('catalogRefresh').addEventListener('click', () => tab === 'cameras' ? root.BTMHCameraConfiguration?.refresh?.() : void reader.refresh());
  get('catalogAddStore').addEventListener('click', () => openStore());get('catalogAddZone').addEventListener('click',()=>openZone());
  get('catalogStoreCancel').addEventListener('click', () => { if (saving) return; get('catalogStoreForm').reset(); get('catalogStoreForm').hidden = true; get('catalogAddStore').focus(); }); get('catalogStoreForm').addEventListener('submit',save);
  get('catalogZoneCancel').addEventListener('click',()=>{if(saving)return;editingZone=null;get('catalogZoneForm').reset();get('catalogZoneForm').hidden=true;get('catalogAddZone').focus();});get('catalogZoneForm').addEventListener('submit',saveZone);
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
  function storeRows(stores, cameras) { return (Array.isArray(stores) ? stores : []).filter(row => id(row.id)).map(row => ({id:id(row.id),code:human(row.store_code),name:human(row.store_name)||'Cửa hàng',status:row.status==='ACTIVE'?'Hoạt động':row.status==='INACTIVE'?'Ngừng hoạt động':row.status==='ARCHIVED'?'Lưu trữ':'Chưa ghi nhận',timezone:human(row.timezone_name)||'—',cameras:Array.isArray(cameras)?cameras.filter(camera=>id(camera.store_id)===id(row.id)).length:'—'})); }
  function entityZones(zones,cameras){return(Array.isArray(zones)?zones:[]).filter(row=>id(row.id)&&id(row.store_id)).map(row=>({id:id(row.id),storeId:id(row.store_id),name:human(row.zone_name),store:human(row.store_name),status:({ACTIVE:'Hoạt động',INACTIVE:'Ngừng hoạt động',ARCHIVED:'Lưu trữ'})[row.status]||'Chưa ghi nhận',count:Number.isSafeInteger(row.camera_count)&&row.camera_count>=0?row.camera_count:'—',everAssigned:row.ever_assigned===1,cameras:(Array.isArray(cameras)?cameras:[]).filter(camera=>id(camera.zone_id)===id(row.id)).map(camera=>human(camera.camera_name||camera.name))}));}
  function itemConfirmed(result,expected=null){return result?.ok===true&&id(result.item?.id)!==null&&(expected===null||id(result.item.id)===expected);}
  function errorMessage(error){if(error.status===403)return'Tài khoản không có quyền thực hiện thao tác này.';if(error.status===409)return'Danh mục đang có liên kết sử dụng hoặc tên/mã đã tồn tại. Giữ thay đổi và kiểm tra lại danh sách.';if(error.status===503)return'Danh mục chưa được kích hoạt. Liên hệ quản trị hệ thống.';return'Chưa xác nhận lưu thành công. Kiểm tra lại danh sách và thông tin trước khi thử lại.';}
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
  return {storeRows,zoneRows,storePayload,saveConfirmed,createReader,entityZones,itemConfirmed,errorMessage,human};
});

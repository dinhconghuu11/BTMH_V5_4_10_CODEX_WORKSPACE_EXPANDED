/* Owner/Admin review adapter. Enrollment drafts never activate FaceID in this client. */
(() => {
  'use strict';
  const prefix = '/api/v1/admin/face-enrollment', pending = new Set(['PENDING_REVIEW', 'NEEDS_DUPLICATE_REVIEW']);
  const labels = {CAPTURING: 'Đang thu mẫu', PENDING_REVIEW: 'Chờ duyệt', NEEDS_DUPLICATE_REVIEW: 'Cần kiểm tra trùng', APPROVED: 'Đã duyệt', REJECTED: 'Đã từ chối', EXPIRED: 'Hết hạn', CANCELLED: 'Đã hủy'};
  const id = value => typeof value !== 'boolean' && Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : null;
  const requestId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value) ? value : null;
  const human = value => String(value || '').replace(/[\x00-\x1f\x7f]/g, ' ').replace(/(?:rtsps?|https?):\/\/\S+/gi, '[ẩn]').replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[ẩn]').slice(0, 500);
  const node = (tag, className = '', text = '') => { const element = document.createElement(tag); element.className = className; element.textContent = text; return element; };
  function mount(host, options = {}) {
    if (!host) return null;
    const {student, api, getUser, getPermission, toast, getPreview} = options, studentId = id(student?.id), actor = getUser?.();
    const section = node('section', 'qr-enrollment-admin'); host.replaceChildren(section);
    const heading = node('div', 'qr-enrollment-heading'); heading.append(node('h3', '', 'Thu mẫu qua điện thoại · duyệt hồ sơ')); section.append(heading);
    const principle = node('p', 'qr-enrollment-principle', 'Mẫu mới chỉ kích hoạt sau khi Chủ sở hữu hoặc Quản trị viên duyệt. FaceID đang có được giữ nguyên trong thời gian chờ duyệt, từ chối hoặc yêu cầu quét lại.'); section.append(principle);
    let live = true, epoch = 0, stores = [], storesLoaded = false, items = [], total = 0, offset = 0, selected = null, detail = null, invitationTimer = null, detailExpiryTimer = null, previewUrl = '', actionOwner = null, changing = null;
    const owners = new Map(), events = [], limit = 20;
    const permitted = () => !!actor && actor === getUser?.() && ['SUPER_ADMIN', 'ADMIN'].includes(String(actor.role || '').toUpperCase()) && getPermission?.('employee.enroll') === true;
    const eligible = () => live && !document.hidden && permitted();
    const on = (target, type, handler) => { target.addEventListener(type, handler); if (target === document || target === window) events.push([target, type, handler]); };
    const note = node('p', 'qr-enrollment-note'); note.setAttribute('role', 'status'); note.setAttribute('aria-live', 'polite'); section.append(note);
    const say = (text, error = false) => { note.textContent = text; note.classList.toggle('error', error); };
    if (!studentId || !permitted() || typeof api !== 'function') { say(!studentId ? 'Chọn nhân viên để tạo lời mời hoặc xem hồ sơ chờ duyệt.' : 'Chỉ Chủ sở hữu hoặc Quản trị viên được quản lý duyệt FaceID.'); return {refresh: async () => {}, stop: () => { live = false; host.replaceChildren(); }}; }
    const identity = node('p', 'qr-enrollment-employee'); identity.append(node('strong', '', human(student.full_name) || 'Nhân viên được chọn'), node('span', '', human(student.student_code))); section.append(identity);
    const issueForm = node('div', 'qr-enrollment-issue'), storeLabel = node('label', '', 'Cửa hàng đăng ký'), storeSelect = node('select'); storeSelect.setAttribute('aria-label', 'Cửa hàng đăng ký qua QR'); storeSelect.dataset.qrField = 'store'; storeLabel.append(storeSelect);
    const issue = node('button', 'btn primary', 'Tạo lời mời QR'), refreshButton = node('button', 'btn secondary', 'Tải lại'); issue.type = refreshButton.type = 'button'; issue.dataset.qrAction = 'issue'; refreshButton.dataset.qrAction = 'refresh'; issueForm.append(storeLabel, issue, refreshButton); section.append(issueForm);
    const invitation = node('div', 'qr-enrollment-invitation'); invitation.hidden = true; section.append(invitation);
    const toolbar = node('div', 'qr-enrollment-toolbar'), filter = node('select'); filter.setAttribute('aria-label', 'Trạng thái yêu cầu đăng ký'); filter.dataset.qrField = 'status'; const all = node('option', '', 'Tất cả trạng thái'); all.value = ''; filter.append(all); for (const [value, text] of Object.entries(labels)) { const option = node('option', '', text); option.value = value; filter.append(option); }
    const pageText = node('span', 'qr-enrollment-page'), previous = node('button', 'btn secondary', 'Trước'), next = node('button', 'btn secondary', 'Sau'); previous.type = next.type = 'button'; previous.dataset.qrAction = 'previous'; next.dataset.qrAction = 'next'; toolbar.append(filter, pageText, previous, next); section.append(toolbar);
    const layout = node('div', 'qr-enrollment-review-layout'), list = node('div', 'qr-enrollment-list'), review = node('section', 'qr-enrollment-review'); list.setAttribute('aria-label', 'Yêu cầu đăng ký của nhân viên'); layout.append(list, review); section.append(layout);
    function clearPreview() { owners.get('preview')?.controller.abort(); owners.delete('preview'); if (previewUrl) URL.revokeObjectURL(previewUrl); previewUrl = ''; for (const image of review.querySelectorAll('img')) image.removeAttribute('src'); }
    function clearInvitation() { clearTimeout(invitationTimer); invitationTimer = null; for (const image of invitation.querySelectorAll('img')) image.removeAttribute('src'); for (const input of invitation.querySelectorAll('input')) input.value = ''; invitation.replaceChildren(); invitation.hidden = true; }
    function suspend() { epoch++; for (const owner of owners.values()) owner.controller.abort(); owners.clear(); actionOwner = null; changing = null; clearTimeout(detailExpiryTimer); detailExpiryTimer = null; clearPreview(); clearInvitation(); items = []; total = 0; selected = null; detail = null; drawList(); drawReview(); say('Thông tin đăng ký đã được ẩn khi rời trang.'); }
    function stop() { if (!live) return; live = false; suspend(); for (const [target, type, handler] of events) target.removeEventListener(type, handler); events.length = 0; host.replaceChildren(); }
    function valid(item) { return requestId(item?.id) && id(item.student_id) === studentId && Object.hasOwn(labels, item.status); }
    function controls() {
      const busy = !!changing || !!actionOwner, available = eligible(); issue.disabled = !available || busy || !storesLoaded || !stores.some(store => id(store.id) === id(storeSelect.value)); storeSelect.disabled = !available || busy || !storesLoaded; refreshButton.disabled = !available || busy || owners.has('list'); filter.disabled = !available || busy; previous.disabled = !available || busy || owners.has('list') || offset === 0; next.disabled = !available || busy || owners.has('list') || offset + limit >= total;
      for (const button of list.querySelectorAll('button')) button.disabled = !available || busy;
      for (const field of review.querySelectorAll('textarea,input')) field.disabled = !available || busy;
      const reason = review.querySelector('[data-qr-field="reason"]'), override = review.querySelector('[data-qr-field="override"]'), reasonValid = reason && reason.value.trim().length > 0 && reason.value.trim().length <= 500 && !/[\x00-\x1f\x7f]/.test(reason.value), revisionValid = Number.isInteger(detail?.revision) && detail.revision >= 0, deadline = Date.parse(detail?.expires_at), unexpired = Number.isFinite(deadline) && deadline > Date.now();
      for (const button of review.querySelectorAll('[data-qr-decision]')) {
        const decision = button.dataset.qrDecision, inPending = pending.has(detail?.status), active = inPending || detail?.status === 'CAPTURING';
        const canApprove = inPending && detail?.consent_status === 'GRANTED' && detail?.quality?.ready === true && detail?.quality?.scan_passes === 2 && detail?.pad?.status === 'PASS' && (!detail?.duplicate?.student_id || override?.checked === true);
        button.disabled = !available || busy || owners.has('detail') || !reasonValid || !revisionValid || !unexpired || (decision === 'approve' ? !canApprove : decision === 'cancel' ? !active : !inPending);
      }
      const help = review.querySelector('[data-qr-review-help]');
      if (help) {
        const message = busy ? 'Đang xử lý. Vui lòng chờ xác nhận từ hệ thống.' : !unexpired ? 'Hồ sơ đã hết hạn. Tải lại để xem trạng thái hoặc cấp lời mời mới.' : !reasonValid ? 'Nhập lý do quyết định (1–500 ký tự) để tiếp tục.' : detail?.status === 'CAPTURING' ? 'Có thể hủy lời mời; chỉ duyệt sau khi nhân viên gửi đủ mẫu.' : detail?.consent_status !== 'GRANTED' ? 'Chưa thể duyệt: chưa có sự đồng ý thu mẫu còn hiệu lực.' : detail?.quality?.ready !== true || detail?.quality?.scan_passes !== 2 ? 'Chưa thể duyệt: mẫu chưa đủ hai vòng theo yêu cầu.' : detail?.pad?.status !== 'PASS' ? 'Chưa thể duyệt: mẫu chưa qua xác minh người thật.' : detail?.duplicate?.student_id && override?.checked !== true ? 'Kiểm tra hồ sơ có thể trùng và xác nhận trước khi duyệt.' : 'Chọn quyết định phù hợp. Chỉ Duyệt mới kích hoạt FaceID.';
        if (help.textContent !== message) help.textContent = message;
      }
    }
    async function call(kind, url, payload, binary = false) {
      if (!eligible()) throw new DOMException('Cancelled', 'AbortError'); owners.get(kind)?.controller.abort(); const owner = {epoch, controller: new AbortController()}; owners.set(kind, owner); if (kind === 'action') actionOwner = owner; controls();
      const timeout = setTimeout(() => { owner.timedOut = true; owner.controller.abort(); }, 8000);
      try {
        const result = binary ? await getPreview(url, {signal: owner.controller.signal}) : await api(url, {signal: owner.controller.signal, timeoutMs: 8000, ...(payload === undefined ? {} : {method: 'POST', body: JSON.stringify(payload)})});
        if (owner.controller.signal.aborted || owner.epoch !== epoch || owners.get(kind) !== owner || !eligible()) throw new DOMException('Cancelled', 'AbortError'); return result;
      } catch (error) { if (owner.epoch !== epoch || owners.get(kind) !== owner || !eligible()) throw new DOMException('Cancelled', 'AbortError'); if (owner.timedOut) throw new Error('REVIEW_TIMEOUT'); if (owner.controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError'); throw error;
      } finally { clearTimeout(timeout); if (owners.get(kind) === owner) owners.delete(kind); if (actionOwner === owner) actionOwner = null; controls(); }
    }
    function drawList() {
      list.replaceChildren(); pageText.textContent = total ? `${offset + 1}–${Math.min(offset + items.length, total)} / ${total}` : '0 yêu cầu';
      for (const item of items) {
        const button = node('button', 'qr-enrollment-request'); button.type = 'button'; button.dataset.qrRequest = item.id; button.setAttribute('aria-pressed', String(item.id === selected)); button.classList.toggle('selected', item.id === selected); button.append(node('b', '', labels[item.status]), node('span', '', human(item.store_name) || 'Cửa hàng được chỉ định'), node('small', '', item.source_kind === 'QR_MOBILE' ? 'Thu mẫu qua điện thoại' : 'Thu mẫu tại máy tính'));
        const time = Date.parse(item.submitted_at || item.created_at); if (Number.isFinite(time)) button.append(node('small', '', new Date(time).toLocaleString('vi-VN'))); on(button, 'click', () => { if (!actionOwner && !changing) void select(item.id); }); list.append(button);
      }
      if (!items.length) list.append(node('p', 'qr-enrollment-empty', 'Chưa có yêu cầu đăng ký trong bộ lọc này.')); controls();
    }
    async function preview(item, hostPreview) {
      if (!item.has_preview || typeof getPreview !== 'function') { hostPreview.textContent = item.has_preview ? 'Ảnh xem trước chưa tải được.' : 'Chưa có ảnh xem trước.'; return; }
      try {
        const blob = await call('preview', `${prefix}/requests/${item.id}/preview.jpg`, undefined, true); if (selected !== item.id || detail !== item) return;
        if (!blob || blob.type !== 'image/jpeg' || blob.size <= 0 || blob.size > 2 * 1024 * 1024) throw new Error('INVALID_PREVIEW'); previewUrl = URL.createObjectURL(blob); const image = node('img'); image.alt = 'Mẫu khuôn mặt đang chờ duyệt'; image.src = previewUrl; hostPreview.replaceChildren(image);
      } catch (error) { if (error.name !== 'AbortError' && eligible() && detail === item) hostPreview.textContent = 'Ảnh xem trước chưa tải được. Tải lại để thử lại.'; }
    }
    function drawReview() {
      clearTimeout(detailExpiryTimer); detailExpiryTimer = null; clearPreview(); review.replaceChildren(); if (!detail) { review.append(node('p', 'qr-enrollment-empty', 'Chọn yêu cầu để xem và quyết định.')); controls(); return; }
      const item = detail; review.append(node('h4', '', labels[item.status]), node('p', 'qr-enrollment-review-location', human(item.store_name) || 'Cửa hàng được chỉ định'));
      const previewHost = node('div', 'qr-enrollment-preview', 'Đang tải ảnh xem trước…'); review.append(previewHost); void preview(item, previewHost);
      const summaries = node('div', 'qr-enrollment-summary'); summaries.append(node('span', '', item.consent_status === 'GRANTED' ? 'Đã đồng ý thu mẫu' : item.consent_status === 'WITHDRAWN' ? 'Đã rút lại sự đồng ý' : 'Chưa đồng ý thu mẫu'), node('span', '', item.quality?.ready === true && item.quality?.scan_passes === 2 ? 'Đủ hai vòng thu mẫu' : 'Chưa đủ mẫu'), node('span', '', item.pad?.status === 'PASS' ? 'Đã qua xác minh người thật' : 'Chưa qua xác minh người thật')); review.append(summaries);
      if (!pending.has(item.status) && item.status !== 'CAPTURING') { if (item.review_reason) review.append(node('p', 'qr-enrollment-review-reason', `Lý do: ${human(item.review_reason)}`)); controls(); return; }
      if (item.duplicate?.student_id) { const warning = node('div', 'qr-enrollment-duplicate'); warning.append(node('strong', '', 'Có hồ sơ có thể trùng khuôn mặt'), node('p', '', [human(item.duplicate.full_name), human(item.duplicate.student_code)].filter(Boolean).join(' · ') || 'Kiểm tra hồ sơ trùng trước khi quyết định.')); const label = node('label'), checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.dataset.qrField = 'override'; label.append(checkbox, node('span', '', 'Tôi đã kiểm tra hồ sơ có thể trùng và đồng ý ghi đè kèm lý do.')); warning.append(label); review.append(warning); on(checkbox, 'change', controls); }
      const reasonLabel = node('label', 'qr-enrollment-reason', 'Lý do quyết định (bắt buộc)'), reason = node('textarea'); reason.maxLength = 500; reason.rows = 3; reason.required = true; reason.setAttribute('aria-required', 'true'); reason.setAttribute('aria-label', 'Lý do quyết định duyệt FaceID'); reason.dataset.qrField = 'reason'; reasonLabel.append(reason); review.append(reasonLabel); on(reason, 'input', controls);
      const help = node('p', 'qr-enrollment-principle'); help.dataset.qrReviewHelp = ''; help.setAttribute('role', 'status'); help.setAttribute('aria-live', 'polite'); review.append(help);
      const buttons = node('div', 'qr-enrollment-decisions'); const decisions = pending.has(item.status) ? [['approve', 'Duyệt & kích hoạt FaceID'], ['reject', 'Từ chối'], ['reenroll', 'Yêu cầu quét lại']] : [['cancel', 'Hủy lời mời']];
      for (const [action, label] of decisions) { const button = node('button', action === 'approve' ? 'btn primary' : 'btn secondary', label); button.type = 'button'; button.dataset.qrDecision = action; on(button, 'click', () => { void decide(action); }); buttons.append(button); } review.append(buttons); controls();
      const deadline = Date.parse(item.expires_at); if (Number.isFinite(deadline) && deadline > Date.now()) detailExpiryTimer = setTimeout(() => { detailExpiryTimer = null; controls(); if (eligible() && detail === item) { say('Hồ sơ đã đến thời hạn kết thúc. Tải lại để xem trạng thái hiện tại.', true); if (!changing && !actionOwner) void refresh(); } }, Math.min(deadline - Date.now(), 2147483647));
    }
    async function select(value) {
      if (!eligible() || actionOwner || !items.some(item => item.id === value) || !requestId(value)) return; selected = value; detail = null; clearTimeout(detailExpiryTimer); detailExpiryTimer = null; clearPreview(); review.replaceChildren(node('p', '', 'Đang tải hồ sơ…')); drawList();
      try { const result = await call('detail', `${prefix}/requests/${value}`); if (selected !== value || !valid(result?.request)) return; detail = result.request; drawReview(); }
      catch (error) { if (error.name !== 'AbortError' && eligible() && selected === value) { review.replaceChildren(node('p', 'qr-enrollment-empty', 'Chưa tải được hồ sơ. Tải lại để thử lại.')); say('Chưa tải được hồ sơ duyệt.', true); } }
    }
    async function loadStores() {
      try { const result = await call('stores', '/api/v1/stores'); stores = (result.items || []).filter(store => id(store.id) && store.status === 'ACTIVE'); storesLoaded = true; const previousValue = storeSelect.value; storeSelect.replaceChildren(); const placeholder = node('option', '', '— Chọn cửa hàng —'); placeholder.value = ''; storeSelect.append(placeholder); for (const store of stores) { const option = node('option', '', human(store.store_name) || 'Cửa hàng'); option.value = String(store.id); storeSelect.append(option); } storeSelect.value = stores.some(store => String(store.id) === previousValue) ? previousValue : ''; controls(); }
      catch (error) { if (error.name !== 'AbortError' && eligible()) { storesLoaded = false; controls(); say('Chưa tải được cửa hàng được cấp quyền. Tải lại để thử lại.', true); } }
    }
    async function refresh() {
      if (!eligible() || actionOwner) return; const query = new URLSearchParams({student_id: String(studentId), limit: String(limit), offset: String(offset)}); if (filter.value) query.set('status', filter.value); say('Đang tải yêu cầu đăng ký…');
      const storeJob = storesLoaded ? Promise.resolve() : loadStores();
      try { const result = await call('list', `${prefix}/requests?${query}`); items = (result.items || []).filter(valid); total = Number.isSafeInteger(result.total) && result.total >= 0 ? result.total : items.length; if (offset > 0 && !items.length && total <= offset) { offset = Math.max(0, Math.floor(Math.max(0, total - 1) / limit) * limit); await refresh(); return; } const choice = items.find(item => item.id === selected) || items.find(item => pending.has(item.status)) || items[0]; drawList(); if (choice) await select(choice.id); else { selected = null; detail = null; drawReview(); } if (eligible()) say(storesLoaded ? 'Chọn hồ sơ để xem, hoặc tạo lời mời cho cửa hàng được chỉ định.' : 'Chưa tải được cửa hàng được cấp quyền. Tải lại để thử lại.', !storesLoaded); }
      catch (error) { if (error.name !== 'AbortError' && eligible()) { items = []; total = 0; selected = null; detail = null; drawList(); drawReview(); say('Chưa tải được yêu cầu đăng ký. Tải lại để thử lại.', true); } }
      finally { await storeJob; }
    }
    function showInvitation(result) {
      clearInvitation(); let url; try { url = new URL(result.qr_url, location.origin); } catch (_) { say('Lời mời đã được tạo, nhưng chưa nhận được liên kết hợp lệ. Tải lại để kiểm tra hồ sơ.', true); return false; }
      if (url.origin !== location.origin || !['http:', 'https:'].includes(url.protocol) || url.pathname !== '/enroll' || url.search || url.username || url.password || !/^#invite=[A-Za-z0-9_-]{40,128}$/.test(url.hash) || !valid(result.request)) { say('Lời mời đã được tạo, nhưng chưa nhận được liên kết hợp lệ. Tải lại để kiểm tra hồ sơ.', true); return false; }
      const expires = Date.parse(result.invite_expires_at); if (!Number.isFinite(expires) || expires <= Date.now()) { say('Lời mời đã hết hạn. Tải lại để xem trạng thái hồ sơ.', true); return false; }
      invitation.hidden = false; invitation.append(node('h4', '', 'Lời mời dùng một lần'), node('p', '', `${human(result.request.full_name) || human(student.full_name)} · ${human(result.request.store_name) || 'Cửa hàng được chỉ định'}`));
      if (typeof result.qr_data_url === 'string' && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(result.qr_data_url) && result.qr_data_url.length <= 4 * 1024 * 1024) { const image = node('img', 'qr-enrollment-code'); image.alt = 'Mã QR lời mời đăng ký riêng của nhân viên'; image.src = result.qr_data_url; invitation.append(image); } else invitation.append(node('p', 'qr-enrollment-empty', 'Mã QR chưa khả dụng. Dùng liên kết lời mời bên dưới.'));
      const input = node('input', 'qr-enrollment-link'); input.type = 'text'; input.readOnly = true; input.value = url.href; input.setAttribute('aria-label', 'Liên kết lời mời đăng ký dùng một lần'); invitation.append(input);
      const copy = node('button', 'btn secondary', 'Sao chép liên kết'); copy.type = 'button'; copy.dataset.qrAction = 'copy'; invitation.append(copy); on(copy, 'click', async () => { if (!eligible() || invitation.hidden) return; const value = input.value; try { if (!navigator.clipboard?.writeText) throw new Error(); await navigator.clipboard.writeText(value); if (eligible() && input.value === value) say('Đã sao chép lời mời. Chỉ gửi cho nhân viên được chỉ định.'); } catch (_) { if (eligible()) { input.focus(); input.select(); say('Chọn và sao chép liên kết lời mời đang hiển thị.'); } } });
      invitation.append(node('small', '', `Lời mời hết hạn lúc ${new Date(expires).toLocaleTimeString('vi-VN', {hour: '2-digit', minute: '2-digit'})}. Liên kết chỉ hiển thị lần này; không chia sẻ cho người khác.`));
      if (result.capture_https_ready !== true || url.protocol !== 'https:') invitation.append(node('p', 'qr-enrollment-https-warning', 'Chưa sẵn sàng thu mẫu trên điện thoại. Cần địa chỉ HTTPS được điện thoại tin cậy trên Wi-Fi cửa hàng. Không bỏ qua cảnh báo chứng chỉ.'));
      invitationTimer = setTimeout(() => { clearInvitation(); if (eligible()) say('Lời mời đã hết hạn. Tải lại để xem trạng thái hồ sơ.'); }, Math.min(expires - Date.now(), 2147483647));
      return true;
    }
    async function issueInvitation() {
      if (!eligible() || actionOwner || changing || issue.disabled) return; const store = id(storeSelect.value); if (!stores.some(item => id(item.id) === store)) return; const operation = {epoch}; changing = operation; controls(); clearInvitation(); say('Đang tạo lời mời…');
      try { const result = await call('action', `${prefix}/invitations`, {student_id: studentId, store_id: store}); if (!valid(result?.request) || result.request.status !== 'CAPTURING' || id(result.request.store_id) !== store) throw new Error('INVALID_INVITATION'); const invitationShown = showInvitation(result); selected = result.request.id; offset = 0; filter.value = ''; await refresh(); if (eligible() && operation.epoch === epoch && !invitationShown) say('Lời mời đã được tạo, nhưng chưa có liên kết hợp lệ còn hiệu lực. Tải lại để kiểm tra hồ sơ.', true); }
      catch (error) { if (error.name !== 'AbortError' && eligible()) { say(error.status === 409 ? 'Nhân viên đang có yêu cầu đăng ký chưa kết thúc. Tải lại để xem hồ sơ.' : 'Chưa xác nhận được lời mời. Tải lại để kiểm tra trước khi tạo lại.', true); } }
      finally { if (changing === operation) changing = null; controls(); }
    }
    async function decide(action) {
      if (!eligible() || actionOwner || changing || !detail || !requestId(detail.id)) return; const button = review.querySelector(`[data-qr-decision="${action}"]`); controls(); if (!button || button.disabled) return;
      const item = detail, reason = review.querySelector('[data-qr-field="reason"]').value.trim(), payload = {expected_revision: item.revision, reason}; if (action === 'approve') payload.duplicate_override = !!review.querySelector('[data-qr-field="override"]')?.checked;
      const operation = {epoch}; changing = operation; controls(); say('Đang ghi nhận quyết định…');
      try { const result = await call('action', `${prefix}/requests/${item.id}/${action}`, payload); const expectedStatus = {approve: 'APPROVED', reject: 'REJECTED', cancel: 'CANCELLED', reenroll: 'CAPTURING'}[action]; if (!valid(result?.request) || result.request.status !== expectedStatus || (action === 'reenroll' ? result.request.id === item.id : result.request.id !== item.id)) throw new Error('INVALID_DECISION'); const invitationShown = action !== 'reenroll' || showInvitation(result); if (action !== 'reenroll') clearInvitation(); const text = action === 'approve' ? (result.index_refresh_pending ? 'Hồ sơ đã được duyệt. Nhận diện đang chờ đồng bộ.' : 'Hồ sơ đã được duyệt và kích hoạt FaceID.') : action === 'reject' ? 'Đã từ chối mẫu. FaceID đang có được giữ nguyên.' : action === 'reenroll' ? 'Đã yêu cầu quét lại. FaceID đang có được giữ nguyên.' : 'Lời mời đã được hủy. FaceID đang có được giữ nguyên.'; toast?.(text); selected = result.request.id; offset = 0; filter.value = ''; await refresh(); if (eligible() && operation.epoch === epoch) say(invitationShown ? text : `${text} Chưa có liên kết hợp lệ còn hiệu lực. Tải lại để kiểm tra hồ sơ.`, !invitationShown); }
      catch (error) { if (error.name !== 'AbortError' && eligible() && operation.epoch === epoch) { if (error.status === 409) { await select(item.id); if (eligible() && operation.epoch === epoch) say('Hồ sơ đã thay đổi hoặc cần kiểm tra trùng. Xem lại hồ sơ và nhập quyết định mới.', true); } else say('Chưa xác nhận được quyết định. Tải lại để kiểm tra trạng thái trước khi thử lại.', true); } }
      finally { if (changing === operation) changing = null; controls(); }
    }
    on(storeSelect, 'change', controls); on(issue, 'click', () => { void issueInvitation(); }); on(refreshButton, 'click', () => { void refresh(); }); on(filter, 'change', () => { offset = 0; selected = null; void refresh(); }); on(previous, 'click', () => { if (!previous.disabled) { offset = Math.max(0, offset - limit); void refresh(); } }); on(next, 'click', () => { if (!next.disabled) { offset += limit; void refresh(); } });
    on(document, 'btmh:auth', stop); on(document, 'btmh:navigate', stop); on(document, 'visibilitychange', () => { if (document.hidden) suspend(); else void refresh(); }); on(window, 'pagehide', stop);
    controls(); void refresh(); return {refresh, stop};
  }
  window.BTMHQREnrollmentAdmin = {mount};
})();

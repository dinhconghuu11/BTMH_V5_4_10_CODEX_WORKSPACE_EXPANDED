/* Dedicated enrollment capability: no portal login, storage, camera registry or activation authority. */
(() => {
  'use strict';
  let invitation = '';
  try { invitation = new URLSearchParams(location.hash.slice(1)).get('invite') || ''; history.replaceState(null, '', location.pathname + location.search); } catch (_) { invitation = ''; }
  const get = id => document.getElementById(id), root = get('mobileEnrollmentRoot'); if (!root) { invitation = ''; return; }
  const video = get('mobileEnrollmentVideo'), canvas = document.createElement('canvas'), phases = [...get('mobileEnrollmentPhases').children];
  const pendingStates = new Set(['PENDING_REVIEW', 'NEEDS_DUPLICATE_REVIEW']), terminalStates = new Set(['APPROVED', 'REJECTED', 'EXPIRED', 'CANCELLED']);
  let epoch = 0, cameraEpoch = 0, requestOwner = null, cameraOwner = null, stream = null, timer = null, expiryTimer = null, presented = true, capturing = false, ready = false, binding = null, receipt = null, uploadCount = 0;
  const safe = text => String(text || '').replace(/[\x00-\x1f\x7f]/g, ' ').replace(/(?:rtsps?|https?):\/\/\S+/gi, '[ẩn]').replace(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g, '[ẩn]').slice(0, 240);
  const secure = () => window.isSecureContext === true && location.protocol === 'https:';
  const shown = () => presented && !document.hidden;
  const row = () => binding?.request || null;
  const expires = () => Math.min(...[row()?.expires_at, binding?.session_expires_at].map(value => Date.parse(value)).filter(Number.isFinite));
  const current = () => shown() && secure() && row()?.status === 'CAPTURING' && row()?.capture_allowed === true && Number.isFinite(expires()) && Date.now() < expires();
  const liveText = (id, text) => { const element = get(id); if (element.textContent !== text) element.textContent = text; };
  function feedback(text, tone = '') { liveText('mobileEnrollmentFeedback', text); get('mobileEnrollmentFeedback').className = `mobile-enrollment-feedback ${tone}`; }
  function controls() {
    const busy = !!requestOwner || !!cameraOwner, allowed = current();
    get('mobileConsentButton').disabled = busy || row()?.can_consent !== true || row()?.status !== 'CAPTURING' || !get('mobileConsentCheck').checked || !shown() || !secure() || !Number.isFinite(expires()) || Date.now() >= expires();
    get('mobileEnrollmentStart').disabled = busy || !allowed || capturing; get('mobileEnrollmentStart').hidden = capturing;
    get('mobileEnrollmentPause').hidden = !capturing; get('mobileEnrollmentPause').disabled = false;
    get('mobileEnrollmentReset').disabled = busy || !allowed; get('mobileEnrollmentSubmit').disabled = busy || !allowed || !ready;
    get('mobileEnrollmentRetry').disabled = busy; get('mobileEnrollmentCancel').hidden = true;
  }
  function clearGuidance() { ready = false; for (const phase of phases) { phase.classList.remove('active', 'complete'); phase.removeAttribute('aria-current'); } get('mobileEnrollmentProgress').value = 0; get('mobileEnrollmentProgressLabel').textContent = 'Chưa ghi nhận'; liveText('mobileEnrollmentGuidance', 'Chờ hướng dẫn từ hệ thống'); liveText('mobileEnrollmentPad', 'Chưa xác minh người thật.'); }
  function stopCamera() {
    cameraEpoch++; capturing = false; cameraOwner = null; clearTimeout(timer); timer = null; ready = false;
    stream?.getTracks().forEach(track => track.stop()); stream = null; video.pause(); video.srcObject = null; get('mobileEnrollmentCameraEmpty').hidden = false; controls();
  }
  function retire(clearIdentity = false) {
    epoch++; requestOwner?.controller.abort(); requestOwner = null; clearTimeout(expiryTimer); expiryTimer = null; stopCamera(); clearGuidance();
    if (clearIdentity) { binding = null; for (const id of ['mobileEnrollmentName', 'mobileEnrollmentCode', 'mobileEnrollmentStore', 'mobileEnrollmentExpiry']) get(id).textContent = ''; get('mobileEnrollmentIdentity').hidden = true; get('mobileEnrollmentConsent').hidden = true; get('mobileEnrollmentCapture').hidden = true; get('mobileEnrollmentResult').hidden = true; }
    controls();
  }
  function errorMessage(error) {
    if (error.status === 410) return 'Lời mời hoặc phiên đăng ký đã kết thúc. Liên hệ quản trị viên để nhận lời mời mới.';
    if (error.status === 403) return 'Phiên đăng ký không còn được phép sử dụng. Kiểm tra địa chỉ HTTPS hoặc liên hệ quản trị viên.';
    if (error.status === 429) return 'Vui lòng chờ một chút rồi chọn Thử lại.';
    return 'Không kết nối được hệ thống đăng ký. Kiểm tra Wi-Fi cửa hàng và chọn Thử lại.';
  }
  function failed(error) {
    retire(true);
    if (error.status === 410 && receipt) { display(receipt); get('mobileEnrollmentResultTitle').textContent = 'Đã gửi mẫu để duyệt'; get('mobileEnrollmentResultText').textContent = 'Phiên thu mẫu đã kết thúc. Mẫu đã được gửi; liên hệ Chủ sở hữu hoặc Quản trị viên để kiểm tra kết quả duyệt. Trang này chưa xác nhận quyết định duyệt hoặc kích hoạt FaceID.'; feedback('Đã gửi mẫu. Liên hệ quản trị viên để kiểm tra kết quả duyệt.'); return; }
    feedback(errorMessage(error), 'error'); get('mobileEnrollmentRetry').hidden = false;
  }
  async function request(action, payload) {
    if (!shown() || !secure() || requestOwner) throw new DOMException('Cancelled', 'AbortError');
    const owner = {epoch, controller: new AbortController()}; requestOwner = owner; controls();
    const deadline = setTimeout(() => { owner.timedOut = true; owner.controller.abort(); }, 8000);
    try {
      const response = await fetch(`/api/v1/qr-enrollment/${action}`, {method: payload === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', signal: owner.controller.signal, headers: payload === undefined ? {} : {'Content-Type': 'application/json'}, ...(payload === undefined ? {} : {body: JSON.stringify(payload)})});
      if (owner.controller.signal.aborted || owner.epoch !== epoch || !shown()) throw new DOMException('Cancelled', 'AbortError');
      const result = await response.json(); if (owner.controller.signal.aborted || owner.epoch !== epoch || !shown()) throw new DOMException('Cancelled', 'AbortError'); if (!response.ok) { const error = new Error('ENROLLMENT_REQUEST_FAILED'); error.status = response.status; error.code = result?.detail?.code || result?.code; throw error; } return result;
    } catch (error) { if (owner.epoch !== epoch || requestOwner !== owner || !shown()) throw new DOMException('Cancelled', 'AbortError'); if (owner.timedOut) throw new Error('ENROLLMENT_TIMEOUT'); if (owner.controller.signal.aborted) throw new DOMException('Cancelled', 'AbortError'); throw error;
    } finally { clearTimeout(deadline); if (requestOwner === owner) { requestOwner = null; controls(); } }
  }
  function display(data) {
    const item = data?.request; if (!item?.id || !['CAPTURING', ...pendingStates, ...terminalStates].includes(item.status)) throw new Error('INVALID_ENROLLMENT_STATUS');
    binding = data; get('mobileEnrollmentIdentity').hidden = false; get('mobileEnrollmentName').textContent = safe(item.full_name) || 'Nhân viên được chỉ định'; get('mobileEnrollmentCode').textContent = safe(item.student_code); get('mobileEnrollmentStore').textContent = safe(item.store_name) || 'Cửa hàng được chỉ định';
    const deadline = item.status === 'CAPTURING' ? expires() : Date.parse(item.expires_at);
    get('mobileEnrollmentExpiry').textContent = Number.isFinite(deadline) ? (item.status === 'CAPTURING' ? `Phiên có hiệu lực đến ${new Date(deadline).toLocaleTimeString('vi-VN', {hour: '2-digit', minute: '2-digit'})}.` : pendingStates.has(item.status) ? `Thời hạn xem xét mẫu: ${new Date(deadline).toLocaleString('vi-VN')}.` : 'Yêu cầu đã kết thúc.') : 'Chưa xác định thời hạn phiên.';
    get('mobileEnrollmentConsent').hidden = item.status !== 'CAPTURING' || item.can_consent !== true; get('mobileEnrollmentCapture').hidden = item.status !== 'CAPTURING' || item.capture_allowed !== true; get('mobileEnrollmentResult').hidden = item.status === 'CAPTURING'; get('mobileEnrollmentRetry').hidden = true;
    clearTimeout(expiryTimer); expiryTimer = null;
    if (item.status === 'CAPTURING') {
      get('mobileEnrollmentTitle').textContent = 'Đăng ký khuôn mặt'; feedback(item.consent_status === 'WITHDRAWN' ? 'Sự đồng ý thu mẫu đã được rút lại. Liên hệ quản trị viên để được hướng dẫn.' : item.can_consent ? 'Xác nhận hồ sơ và đồng ý trước khi mở camera.' : item.capture_allowed ? 'Mở camera và làm theo hướng dẫn để thu mẫu.' : 'Phiên chưa được phép thu mẫu. Liên hệ quản trị viên để được hướng dẫn.');
      if (Number.isFinite(expires()) && expires() > Date.now()) expiryTimer = setTimeout(() => { retire(); feedback('Phiên đăng ký đã hết hạn. Liên hệ quản trị viên để nhận lời mời mới.', 'error'); get('mobileEnrollmentCapture').hidden = true; }, Math.min(expires() - Date.now(), 2147483647));
      else { stopCamera(); feedback('Phiên đăng ký đã hết hạn hoặc chưa xác định được thời hạn.', 'error'); }
    } else {
      stopCamera(); clearGuidance(); if (pendingStates.has(item.status)) receipt = data; get('mobileEnrollmentTitle').textContent = 'Trạng thái đăng ký';
      const title = pendingStates.has(item.status) ? 'Mẫu đang chờ duyệt' : ({APPROVED: 'Đăng ký đã được duyệt', REJECTED: 'Mẫu chưa được duyệt', EXPIRED: 'Phiên đã hết hạn', CANCELLED: 'Yêu cầu đã kết thúc'})[item.status];
      get('mobileEnrollmentResultTitle').textContent = title;
      get('mobileEnrollmentResultText').textContent = pendingStates.has(item.status) ? 'Chủ sở hữu hoặc Quản trị viên sẽ xem xét mẫu. Việc gửi mẫu chưa kích hoạt FaceID. Hồ sơ FaceID đang có, nếu có, được giữ nguyên trong thời gian chờ duyệt.' : item.status === 'APPROVED' ? 'Chủ sở hữu hoặc Quản trị viên đã xác nhận hồ sơ này.' : 'Liên hệ quản trị viên để được hướng dẫn hoặc cấp lời mời đăng ký lại. Hồ sơ FaceID đang có được giữ nguyên.';
      feedback(title, pendingStates.has(item.status) || item.status === 'APPROVED' ? 'success' : '');
    }
    controls();
  }
  async function status() {
    if (!shown() || !secure()) return;
    try { display(await request('status')); } catch (error) { if (error.name !== 'AbortError') failed(error); }
  }
  function frame(data) {
    const index = data.capture_phase_index; for (let i = 0; i < phases.length; i++) { const known = Number.isInteger(index) && index >= 0 && index <= 4; phases[i].classList.toggle('active', known && i === index); phases[i].classList.toggle('complete', known && i < index); if (known && i === index) phases[i].setAttribute('aria-current', 'step'); else phases[i].removeAttribute('aria-current'); }
    const guide = String(data.guide || '').toLowerCase(), labels = {center: 'Nhìn thẳng vào camera', left: 'Nghiêng nhẹ sang trái', right: 'Nghiêng nhẹ sang phải', up: 'Ngẩng nhẹ theo hướng dẫn', down: 'Cúi nhẹ theo hướng dẫn'};
    liveText('mobileEnrollmentGuidance', labels[guide] || ({CENTER: 'Nhìn thẳng vào camera', LEFT: 'Nghiêng nhẹ sang trái', RIGHT: 'Nghiêng nhẹ sang phải', LIVENESS: 'Hoàn tất xác minh người thật'})[data.capture_phase] || 'Làm theo hướng dẫn của hệ thống');
    get('mobileEnrollmentHint').textContent = safe(data.message) || 'Di chuyển chậm, giữ khuôn mặt đủ sáng.';
    const progress = typeof data.progress === 'number' && Number.isFinite(data.progress) && data.progress >= 0 && data.progress <= 1 ? data.progress : null;
    get('mobileEnrollmentProgress').value = progress === null ? 0 : Math.round(progress * 100); get('mobileEnrollmentProgressLabel').textContent = progress === null ? 'Chưa ghi nhận' : `${Math.round(progress * 100)}% · Vòng ${data.scan_pass === 2 ? 2 : 1}/2`;
    const pad = data.pad?.status; liveText('mobileEnrollmentPad', ({PASS: 'Đã qua xác minh người thật.', CHECKING: 'Đang xác minh người thật.', BLOCKED: 'Chưa vượt qua xác minh người thật.', MODEL_UNAVAILABLE: 'Xác minh người thật chưa khả dụng.'})[pad] || 'Chưa xác minh người thật.');
    ready = data.capture_ready === true && data.ready_to_finalize === true && data.scan_pass === 2 && pad === 'PASS'; controls(); if (ready) feedback('Mẫu đã đủ. Bấm Gửi mẫu để chờ duyệt.', 'success');
    if (['BLOCKED', 'MODEL_UNAVAILABLE'].includes(pad)) { stopCamera(); feedback('Chưa thể gửi mẫu. Chọn Quét lại hoặc liên hệ quản trị viên.', 'error'); }
  }
  function captureImage() {
    if (!video.videoWidth || !video.videoHeight) return ''; const scale = Math.min(1, 960 / video.videoWidth, 960 / video.videoHeight); canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale); canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height); const image = canvas.toDataURL('image/jpeg', .86); if (image.length > 2796247 || !image.startsWith('data:image/jpeg;base64,')) throw new Error('IMAGE_TOO_LARGE'); return image;
  }
  function schedule() { clearTimeout(timer); timer = null; if (capturing && current()) timer = setTimeout(() => { timer = null; void upload(); }, 350); }
  async function upload() {
    if (!capturing || !current()) return; if (requestOwner) { schedule(); return; } if (++uploadCount > 600) { stopCamera(); feedback('Đã tạm dừng quét. Kiểm tra ánh sáng và mở camera để tiếp tục nếu phiên còn hiệu lực.', 'error'); return; }
    try { const image = captureImage(); if (!image) { schedule(); return; } const owner = cameraEpoch, result = await request('frame', {image}); if (owner === cameraEpoch && capturing && current()) frame(result); }
    catch (error) { if (error.name !== 'AbortError') failed(error); }
    finally { schedule(); }
  }
  async function startCamera() {
    if (!current() || cameraOwner || stream || requestOwner) return;
    if (!navigator.mediaDevices?.getUserMedia) { feedback('Trình duyệt chưa hỗ trợ mở camera. Dùng trình duyệt phù hợp tại địa chỉ HTTPS do quản trị viên cấp.', 'error'); return; }
    const owner = {epoch: cameraEpoch}; cameraOwner = owner; controls(); feedback('Đang xin quyền mở camera…');
    try { const opened = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'user', width: {ideal: 1280}, height: {ideal: 720}}, audio: false}); if (cameraOwner !== owner || owner.epoch !== cameraEpoch || !current()) { opened.getTracks().forEach(track => track.stop()); return; } stream = opened; video.srcObject = stream; await video.play(); if (cameraOwner !== owner || owner.epoch !== cameraEpoch || !current()) { opened.getTracks().forEach(track => track.stop()); return; } capturing = true; uploadCount = 0; get('mobileEnrollmentCameraEmpty').hidden = true; feedback('Di chuyển chậm theo hướng dẫn. Hệ thống xác nhận từng mẫu và xác minh người thật.'); schedule(); }
    catch (error) { if (cameraOwner === owner && owner.epoch === cameraEpoch && shown()) { stopCamera(); feedback(error.name === 'NotAllowedError' ? 'Camera chưa được cho phép. Cho phép camera trong cài đặt trình duyệt rồi bấm Mở camera để thử lại.' : 'Không mở được camera. Đóng ứng dụng đang dùng camera rồi thử lại.', 'error'); } }
    finally { if (cameraOwner === owner) cameraOwner = null; controls(); }
  }
  async function consent() { controls(); if (get('mobileConsentButton').disabled) return; try { await request('consent', {granted: true}); await status(); } catch (error) { if (error.name !== 'AbortError') failed(error); } }
  async function submit() {
    if (!ready || !current() || requestOwner) return; stopCamera(); feedback('Đang gửi mẫu để chờ duyệt…');
    try { const result = await request('submit', {}); if (!pendingStates.has(result?.request?.status)) throw new Error('INVALID_PENDING_RESULT'); display(result); }
    catch (error) { if (error.name !== 'AbortError') { if (error.status === 403 || error.status === 410) failed(error); else { feedback(error.status === 400 || error.status === 409 ? 'Mẫu chưa thể gửi. Mở camera và hoàn tất hướng dẫn hoặc Quét lại.' : errorMessage(error), 'error'); get('mobileEnrollmentRetry').hidden = false; } } }
  }
  async function reset() { if (!current() || requestOwner) return; stopCamera(); clearGuidance(); try { await request('reset', {}); await status(); } catch (error) { if (error.name !== 'AbortError') failed(error); } }
  get('mobileConsentCheck').addEventListener('change', controls); get('mobileConsentButton').addEventListener('click', () => { void consent(); }); get('mobileEnrollmentStart').addEventListener('click', () => { void startCamera(); }); get('mobileEnrollmentPause').addEventListener('click', () => { retire(); feedback('Camera đã dừng. Phiên đăng ký vẫn có hiệu lực đến thời hạn đã cấp.'); void status(); }); get('mobileEnrollmentCancel').textContent = 'Dừng camera'; get('mobileEnrollmentCancel').addEventListener('click', () => { retire(); void status(); }); get('mobileEnrollmentReset').addEventListener('click', () => { void reset(); }); get('mobileEnrollmentSubmit').addEventListener('click', () => { void submit(); }); get('mobileEnrollmentRetry').addEventListener('click', () => { void status(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) { retire(true); feedback('Camera đã dừng khi rời trang.'); } else void status(); }); window.addEventListener('pagehide', () => { presented = false; retire(true); }); window.addEventListener('pageshow', () => { presented = true; if (!binding) void status(); });
  async function boot() {
    if (!secure()) { invitation = ''; feedback('Đăng ký cần địa chỉ HTTPS được điện thoại tin cậy. Kết nối Wi-Fi cửa hàng và dùng địa chỉ quản trị viên cấp; không bỏ qua cảnh báo chứng chỉ.', 'error'); controls(); return; }
    if (!invitation) { await status(); return; } const secret = invitation; invitation = '';
    if (!/^[A-Za-z0-9_-]{40,128}$/.test(secret)) { feedback('Lời mời không hợp lệ. Liên hệ quản trị viên để nhận lời mời mới.', 'error'); controls(); return; }
    try { await request('redeem', {invite_secret: secret}); await status(); } catch (error) { if (error.name !== 'AbortError') { feedback(errorMessage(error), 'error'); get('mobileEnrollmentRetry').hidden = false; } }
  }
  controls(); void boot();
})();

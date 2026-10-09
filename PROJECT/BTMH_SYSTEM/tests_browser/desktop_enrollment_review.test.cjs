const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

function productFunction(context, name) {
  const first = source.match(new RegExp(`(?:async )?function ${name}\\([^\\n]*`));
  assert.ok(first, `missing product function ${name}`);
  if (first[0].trim().endsWith('}')) vm.runInContext(first[0], context);
  else {
    const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\n\\}`));
    assert.ok(match, `missing product function body ${name}`);
    vm.runInContext(match[0], context);
  }
}

function element(classes = []) {
  const names = new Set(classes);
  return {textContent: '', innerHTML: '', value: '', dataset: {}, disabled: false,
    classList: {contains: n => names.has(n), add: (...ns) => ns.forEach(n => names.add(n)),
      remove: (...ns) => ns.forEach(n => names.delete(n)),
      toggle: (n, force) => { if (force === undefined ? !names.has(n) : force) names.add(n); else names.delete(n); }},
    scrollIntoView() {}, querySelector() { return null; }};
}

function environment() {
  const nodes = new Map(), requests = [], calls = [], messages = [], intervals = new Map();
  for (const id of ['enrollmentStoreSelect', 'faceidTitle', 'faceidInstruction', 'enrollHint', 'faceidSuccess',
    'faceidScanner', 'registrationFacePhase', 'registrationProfilePhase', 'finalizeEnrollBtn',
    'enrollFaceSignal', 'enrollQualitySignal', 'enrollLiveSignal', 'qSharp', 'qLight', 'qPose', 'qScore',
    'v5FaceValidationBadge', 'v5FaceValidationNote', 'v5ValidateStoreCameraBtn']) nodes.set('#' + id, element());
  nodes.get('#enrollmentStoreSelect').value = '3';
  nodes.get('#registrationFacePhase').classList.add('active');
  const oldEmployee = {id: 7, full_name: 'Employee', student_code: 'EMP7', enrolled: true,
    biometric_consent_status: 'GRANTED', pose_count: 10};
  const state = {authUser: {id: 1, role: 'ADMIN', permissions: ['*']}, activePage: 'register', presentationEpoch: 1,
    presentationSuspended: false, pagePresented: true, students: [oldEmployee], enrollStudentId: 7,
    enrollStudentProfile: oldEmployee, enrollSession: 'server-original', enrollmentSourceMode: 'browser',
    enrollStarting: false, enrollFinalizing: false, enrollCompleted: false, enrollDuplicatePending: false,
    enrollBusy: false, enrollTimer: null, enrollRequestController: null};
  let timerId = 0;
  const context = {state, AbortController, console, window: {BTMHV4: {
    stopEnrollmentBrowserCamera: () => calls.push('camera:stop'), enrollmentDataUrl: () => 'data:image/jpeg;base64,FRAME'}},
    $: selector => nodes.get(selector) || null,
    hasUiPermission: perm => !!state.authUser && (state.authUser.permissions.includes('*') || state.authUser.permissions.includes(perm)),
    appPresentationActive: () => !!state.authUser && state.pagePresented && !state.presentationSuspended,
    api: (url, options) => new Promise((resolve, reject) => requests.push({url, options, body: JSON.parse(options?.body || '{}'), resolve, reject})),
    toast: (...args) => messages.push(args),
    ensureConsent: async () => true,
    prepareEnrollmentLaptopCamera: async () => { calls.push('camera:prepare'); return true; },
    updateEnrollPerson: () => calls.push('person:update'), resetFaceIdUI: () => {
      calls.push('ui:reset'); state.enrollCompleted = false; state.enrollFinalizing = false; state.enrollDuplicatePending = false;
    },
    loadStudents: async () => calls.push('students:load'),
    syncQREnrollmentPanel: () => calls.push('review:sync'), mountCameraPreview: mode => calls.push(`preview:mount:${mode}`),
    pauseCameraPreview: mode => calls.push(`preview:pause:${mode}`), clearEnrollBiometricOverlay: () => calls.push('overlay:clear'),
    drawEnrollBiometricOverlay: response => calls.push(['overlay:draw', response]), updateEnrollLock: response => calls.push(['lock', response]),
    updateFaceIdProgress: (...args) => calls.push(['progress', ...args]), renderEnrollPoseProgress: (...args) => calls.push(['poses', ...args]),
    flashAcceptedSample: () => calls.push('sample:flash'),
    setSignal: (selector, mode = 'idle') => { nodes.get(selector).dataset.signal = mode; calls.push(['signal', selector, mode]); },
    faceIdGuideText: guide => `guide:${guide}`, faceIdMissingHint: () => '',
    escapeHtml: value => String(value).replaceAll('<', '&lt;'), ENROLL_POSE_LABEL: {center: 'Center'},
    requestAnimationFrame: fn => { fn(); return 1; },
    setInterval: fn => { const id = ++timerId; intervals.set(id, fn); calls.push(['timer:start', id]); return id; },
    clearInterval: id => { intervals.delete(id); if (id) calls.push(['timer:stop', id]); },
    crypto: {randomUUID() { throw new Error('UI must not fabricate server request ID'); }},
  };
  vm.createContext(context);
  for (const name of ['canManageEnrollment', 'selectedEnrollStudent', 'setEnrollPhase', 'beginFaceIdSetup',
    'finalizeEnrollment', 'updateFaceValidationUi', 'startEnrollLoop', 'resetEnrollment']) productFunction(context, name);
  const tick = () => {
    assert.ok(state.enrollTimer, 'scan timer is active');
    return intervals.get(state.enrollTimer)();
  };
  const invalidate = kind => {
    if (kind === 'auth') state.authUser = null;
    else if (kind === 'nav') { state.presentationEpoch++; state.activePage = 'dashboard'; }
    else if (kind === 'student') state.enrollStudentId = 8;
    else if (kind === 'session') state.enrollSession = 'server-new-request';
  };
  return {context, state, nodes, requests, calls, messages, intervals, oldEmployee, tick, invalidate};
}

test('Owner/Admin and a selected store are required before opening a desktop request', async () => {
  for (const role of ['VIEWER', 'HR', 'TECHNICIAN']) {
    const w = environment(); w.state.authUser.role = role;
    assert.equal(await w.context.beginFaceIdSetup(), false);
    assert.equal(w.requests.length, 0); assert.equal(w.calls.includes('camera:prepare'), false);
  }
  const w = environment(); w.nodes.get('#enrollmentStoreSelect').value = '';
  assert.equal(await w.context.beginFaceIdSetup(), false);
  assert.equal(w.requests.length, 0); assert.equal(w.calls.includes('ui:reset'), false);
});

test('server request ID is reused for frame, reset and finalize with no client override', async () => {
  const w = environment(), started = w.context.beginFaceIdSetup(); await flush();
  assert.equal(w.requests[0].url, '/api/v1/admin/face-enrollment/requests');
  assert.deepEqual(w.requests[0].body, {student_id: 7, store_id: 3});
  w.requests[0].resolve({request: {id: 'server-issued-uuid', status: 'CAPTURING'}}); assert.equal(await started, true);
  assert.equal(w.state.enrollSession, 'server-issued-uuid');
  const frame = w.tick();
  assert.deepEqual(w.requests[1].body, {request_id: 'server-issued-uuid', student_id: 7, image: 'data:image/jpeg;base64,FRAME'});
  w.requests[1].resolve({ok: false, pad: {status: 'CHECKING'}, message: 'Checking'}); await frame;
  const reset = w.context.resetEnrollment(); await flush();
  assert.equal(w.requests[2].url, '/api/v1/enrollment/reset');
  assert.deepEqual(w.requests[2].body, {request_id: 'server-issued-uuid', student_id: 7});
  w.requests[2].resolve({request: {id: 'server-issued-uuid', revision: 1}}); assert.equal(await reset, true);
  const finalize = w.context.finalizeEnrollment(false, true);
  assert.equal(w.requests[3].url, '/api/v1/enrollment/finalize');
  assert.deepEqual(w.requests[3].body, {request_id: 'server-issued-uuid', student_id: 7});
  assert.equal('confirm_duplicate' in w.requests[3].body, false);
  w.requests[3].resolve({request: {status: 'PENDING_REVIEW'}}); await finalize;
  assert.equal(w.state.enrollSession, 'server-issued-uuid');
});

test('staging pending or duplicate review stops capture and preserves the previous active FaceID', async () => {
  for (const status of ['PENDING_REVIEW', 'NEEDS_DUPLICATE_REVIEW']) {
    const w = environment(); w.context.startEnrollLoop();
    const original = JSON.stringify(w.oldEmployee), pending = w.context.finalizeEnrollment();
    w.requests[0].resolve({request: {status}}); await pending;
    assert.equal(w.state.enrollCompleted, true); assert.equal(w.state.enrollTimer, null);
    assert.ok(w.calls.includes('camera:stop')); assert.ok(w.calls.includes('preview:pause:enroll'));
    assert.equal(JSON.stringify(w.oldEmployee), original);
    assert.equal(w.nodes.get('#v5FaceValidationBadge').textContent, status === 'PENDING_REVIEW' ? 'CHỜ DUYỆT' : 'CẦN KIỂM TRA TRÙNG');
    assert.equal(w.nodes.get('#v5ValidateStoreCameraBtn').disabled, true);
    assert.equal(w.requests.some(r => r.url.includes('/approve')), false);
    assert.equal(w.messages.some(([message]) => message.includes('sau khi được duyệt')), true);
  }
});

test('an unexpected finalize status cannot claim completion or activate the FaceID', async () => {
  const w = environment(), pending = w.context.finalizeEnrollment();
  w.requests[0].resolve({ok: true, request: {status: 'APPROVED'}}); await pending;
  assert.equal(w.state.enrollCompleted, false); assert.equal(w.calls.includes('camera:stop'), false);
  assert.equal(w.nodes.get('#faceidSuccess').classList.contains('show'), false);
  assert.equal(w.state.enrollFinalizing, false);
  assert.ok(w.messages.length > 0);
});

test('stale start/finalize success after auth, navigation or target changes is ignored', async () => {
  for (const kind of ['auth', 'nav', 'student']) {
    const w = environment(), pending = w.context.beginFaceIdSetup(); await flush();
    w.invalidate(kind); w.requests[0].resolve({request: {id: 'late-old-request'}}); await pending;
    assert.notEqual(w.state.enrollSession, 'late-old-request'); assert.equal(w.calls.includes('camera:prepare'), false);
  }
  for (const kind of ['auth', 'nav', 'student', 'session']) {
    const w = environment(), pending = w.context.finalizeEnrollment();
    w.invalidate(kind); w.nodes.get('#enrollHint').textContent = 'New context';
    w.requests[0].resolve({request: {status: 'PENDING_REVIEW'}}); await pending;
    assert.equal(w.state.enrollCompleted, false); assert.equal(w.calls.includes('camera:stop'), false);
    assert.equal(w.nodes.get('#enrollHint').textContent, 'New context'); assert.equal(w.messages.length, 0);
  }
});

test('stale finalization errors do not replace feedback for a different target', async () => {
  for (const kind of ['auth', 'nav', 'student', 'session']) {
    const w = environment(), pending = w.context.finalizeEnrollment();
    w.invalidate(kind); w.nodes.get('#enrollHint').textContent = 'New context';
    w.requests[0].reject(new Error('Old request failed')); await pending;
    assert.equal(w.nodes.get('#enrollHint').textContent, 'New context', kind);
    assert.equal(w.messages.length, 0, kind);
  }
});

test('reset failure preserves scan state and never invents another server request', async () => {
  const w = environment(); w.state.enrollLastResponse = {captured: 6};
  const pending = w.context.resetEnrollment(); await flush();
  w.requests[0].reject(new Error('Reset rejected')); assert.equal(await pending, false);
  assert.equal(w.state.enrollSession, 'server-original'); assert.deepEqual(w.state.enrollLastResponse, {captured: 6});
  assert.equal(w.calls.includes('ui:reset'), false); assert.equal(w.state.enrollTimer, null);
  assert.equal(w.requests.length, 1); assert.equal(w.requests[0].url, '/api/v1/enrollment/reset');
});

test('stale reset success and failure after navigation or auth changes are ignored', async () => {
  for (const kind of ['auth', 'nav', 'student', 'session']) for (const failure of [false, true]) {
    const w = environment(), pending = w.context.resetEnrollment(); await flush();
    w.invalidate(kind); w.nodes.get('#enrollHint').textContent = 'New context';
    if (failure) w.requests[0].reject(new Error('Old reset failed')); else w.requests[0].resolve({request: {revision: 1}});
    await pending;
    assert.equal(w.calls.includes('ui:reset'), false, `${kind}/${failure}`);
    assert.equal(w.state.enrollTimer, null, `${kind}/${failure}`);
    assert.equal(w.messages.length, 0, `${kind}/${failure}`);
    assert.equal(w.nodes.get('#enrollHint').textContent, 'New context');
  }
});

test('stale camera preparation failure cannot show an old enrollment error on a new page', async () => {
  const w = environment(); let rejectCamera;
  w.context.prepareEnrollmentLaptopCamera = () => new Promise(resolve => { rejectCamera = resolve; });
  const pending = w.context.beginFaceIdSetup(); await flush();
  w.requests[0].resolve({request: {id: 'server-created'}}); await flush();
  w.invalidate('nav'); w.nodes.get('#faceidTitle').textContent = 'New page';
  rejectCamera(false); await pending;
  assert.equal(w.nodes.get('#faceidTitle').textContent, 'New page'); assert.equal(w.messages.length, 0);
});

test('scan uses real PAD status and never paints pending as PASS', async () => {
  for (const [status, mode] of [['CHECKING', 'warn'], ['BLOCKED', 'bad'], ['MODEL_UNAVAILABLE', 'bad'], ['PASS', 'ok']]) {
    const w = environment(); w.context.startEnrollLoop(); const pending = w.tick();
    w.requests[0].resolve({ok: true, pad: {status}, quality: {score: .9}, progress: .7, ready_to_finalize: false}); await pending;
    assert.equal(w.nodes.get('#enrollLiveSignal').dataset.signal, mode, status);
    assert.equal(w.requests.length, 1); assert.equal(w.state.enrollCompleted, false);
  }
});

test('scan remains single-flight and only server readiness triggers pending submission', async () => {
  const w = environment(); w.context.startEnrollLoop(); const pending = w.tick(); await w.tick();
  assert.equal(w.requests.length, 1);
  w.requests[0].resolve({ok: true, pad: {status: 'PASS'}, progress: 1, ready_to_finalize: false}); await pending;
  assert.equal(w.requests.length, 1);
  const next = w.tick(); w.requests[1].resolve({ok: true, pad: {status: 'PASS'}, progress: 1, ready_to_finalize: true}); await next;
  assert.equal(w.requests.length, 3); assert.equal(w.requests[2].url, '/api/v1/enrollment/finalize');
  assert.deepEqual(w.requests[2].body, {request_id: 'server-original', student_id: 7});
  w.requests[2].resolve({request: {status: 'PENDING_REVIEW'}}); await flush();
  assert.equal(w.state.enrollCompleted, true);
});

test('expired, revoked or throttled frame responses stop further camera uploads', async () => {
  for (const status of [403, 410, 429]) {
    const w = environment(); w.context.startEnrollLoop(); const pending = w.tick();
    const error = new Error('Capture unavailable'); error.status = status; w.requests[0].reject(error); await pending;
    assert.equal(w.state.enrollTimer, null, status); assert.equal(w.intervals.size, 0);
    assert.ok(w.calls.includes('camera:stop')); assert.ok(w.calls.includes('preview:pause:enroll'));
    assert.equal(w.state.enrollBusy, false);
  }
});

test('stale frame success and errors cannot affect the replacement scan or another page', async () => {
  for (const kind of ['auth', 'nav', 'student', 'session']) for (const failure of [false, true]) {
    const w = environment(); w.context.startEnrollLoop(); const pending = w.tick();
    w.invalidate(kind); w.nodes.get('#enrollHint').textContent = 'New context';
    if (failure) { const error = new Error('Old revoked capture'); error.status = 410; w.requests[0].reject(error); }
    else w.requests[0].resolve({ok: true, message: 'Old result', progress: 1, ready_to_finalize: true, pad: {status: 'PASS'}});
    await pending;
    assert.equal(w.nodes.get('#enrollHint').textContent, 'New context', `${kind}/${failure}`);
    assert.equal(w.calls.includes('camera:stop'), false, `${kind}/${failure}`);
    assert.equal(w.state.enrollLastResponse, undefined, `${kind}/${failure}`);
    assert.equal(w.requests.length, 1);
  }
});

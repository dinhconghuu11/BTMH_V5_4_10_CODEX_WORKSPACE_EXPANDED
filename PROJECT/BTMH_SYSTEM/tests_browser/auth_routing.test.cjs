/* Actual app functions in a DOM/HTTP adapter; no rendered browser/server claim. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const owner = {id: 1, username: 'testowner', display_name: 'Test Owner', role: 'SUPER_ADMIN', permissions: ['*']};

function environment() {
  const nodes = new Map(), requests = [], storage = new Map(), calls = [], destinations = [];
  const state = {authUser: null, pagePresented: true}, document = {hidden: false, dispatchEvent: event => calls.push(event.type)};
  const add = id => {
    const classes = new Set(), attributes = new Map();
    const node = {value: '', checked: false, disabled: false, textContent: '', classList: {
      contains: name => classes.has(name), add: (...names) => names.forEach(name => classes.add(name)),
      remove: (...names) => names.forEach(name => classes.delete(name)),
      toggle: (name, force) => { const show = force === undefined ? !classes.has(name) : !!force; if (show) classes.add(name); else classes.delete(name); return show; },
    }, focus: () => { document.activeElement = node; }, setAttribute: (name, value) => attributes.set(name, value),
      getAttribute: name => attributes.get(name), querySelector: selector => selector === 'span' ? node.label : null};
    nodes.set('#' + id, node); return node;
  };
  const ids = ['authGate', 'authGateSetup', 'authGateLogin', 'gateOpenSetupBtn', 'gateFirstSetupNotice', 'gateEntryActions',
    'gateOpenLoginBtn', 'gateOpenRegistrationBtn', 'gateLoginView', 'gateRegistrationView', 'gateForgotView', 'gateMfaView',
    'gateLoginUsername', 'gateLoginPassword', 'gateLoginBtn', 'gateLoginNote', 'gateRememberUsername', 'gateEnrollmentInvite',
    'gateEnrollmentNote', 'gateSetupBtn', 'gateSetupNote', 'gateSetupDisplay', 'gateSetupUsername', 'gateSetupPassword',
    'gateSetupPassword2', 'forgotReturnBtn', 'gateMfaCode', 'gateMfaNote', 'gateMfaTitle', 'gateMfaDescription',
    'gateMfaSetupBox', 'gateMfaVerifyBox', 'gateMfaRecoveryBox', 'gateMfaSecret', 'gateMfaUri', 'gateSmsActions', 'gateSmsSend', 'gateTrustBrowser'];
  ids.forEach(add); nodes.get('#gateLoginBtn').label = {textContent: 'Đăng nhập'};
  const shell = {inert: false}; nodes.set('.app-shell', shell);
  const context = {state, document, URL, URLSearchParams, encodeURIComponent,
    window: {location: {origin: 'https://btmh.test', assign: value => destinations.push(value)}, scrollTo() {}, btmhSms: {stopLoginTimer() {}}},
    $: selector => nodes.get(selector) || null,
    api: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    localStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)},
    applyRoleUi: user => calls.push(user ? 'role:user' : 'role:none'), pauseAppPresentation: reason => calls.push('pause:' + reason),
    toast() {}, bootAuthenticated: async () => calls.push('boot'),
    CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
    setTimeout: callback => { callback(); return 1; }, escapeHtml: value => value,
  };
  vm.createContext(context);
  for (const name of ['setAuthFeedback', 'setGateAuthMode', 'setAuthGate', 'gateOpenEnrollment', 'verifyBrowserSession',
    'enforceManagementPortalAccess', 'validateStrongPassword', 'enterMfaChallenge', 'gateLogin', 'gateBootstrap']) {
    const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\n\\}`));
    assert.ok(match, name); vm.runInContext(match[0], context);
  }
  return {context, nodes, requests, state, shell, calls, storage, destinations, document};
}
const visible = (w, id) => !w.nodes.get('#' + id).classList.contains('hidden');
const input = (w, id, value) => { w.nodes.get('#' + id).value = value; };

test('an empty isolated database keeps Login and Registration available with explicit first-owner setup', () => {
  const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: true});
  assert.equal(visible(w, 'authGate'), true); assert.equal(visible(w, 'gateLoginView'), true);
  assert.equal(visible(w, 'authGateSetup'), false); assert.equal(visible(w, 'gateOpenSetupBtn'), true);
  assert.equal(visible(w, 'gateFirstSetupNotice'), true); assert.equal(w.shell.inert, true);
  w.context.setGateAuthMode('setup'); assert.equal(visible(w, 'authGateSetup'), true); assert.equal(visible(w, 'authGateLogin'), false);
  w.context.setGateAuthMode('registration'); assert.equal(visible(w, 'gateRegistrationView'), true); assert.equal(visible(w, 'authGateSetup'), false);
  w.context.setGateAuthMode('login'); assert.equal(visible(w, 'gateLoginView'), true); assert.equal(w.document.activeElement, w.nodes.get('#gateLoginUsername'));
});

test('a configured system never exposes first-owner setup, including direct setup mode requests', () => {
  const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: false});
  assert.equal(visible(w, 'gateOpenSetupBtn'), false); assert.equal(visible(w, 'gateFirstSetupNotice'), false);
  w.context.setGateAuthMode('setup'); assert.equal(w.state.gateAuthMode, 'login'); assert.equal(visible(w, 'authGateSetup'), false);
  w.context.setAuthGate({authenticated: true, user: owner, setup_required: false});
  assert.equal(visible(w, 'authGate'), false); assert.equal(w.shell.inert, false); assert.equal(w.state.authUser, owner);
});

test('invited registration uses only the existing enrollment fragment and never public account APIs/storage', () => {
  const secret = 'A'.repeat(43);
  for (const value of [secret, '/enroll#invite=' + secret, 'https://btmh.test/enroll#invite=' + secret]) {
    const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: false});
    w.context.setGateAuthMode('registration'); input(w, 'gateEnrollmentInvite', value); w.context.gateOpenEnrollment();
    assert.deepEqual(w.destinations, ['/enroll#invite=' + secret]); assert.equal(w.nodes.get('#gateEnrollmentInvite').value, '');
    assert.equal(w.requests.length, 0); assert.equal(w.storage.size, 0); assert.equal(w.state.authUser, null);
  }
});

test('registration rejects external, malformed, query-string and duplicate capability URLs without reflecting the token', () => {
  const secret = 'B'.repeat(43);
  for (const value of ['', 'short', 'https://external.invalid/enroll#invite=' + secret, '/wrong#invite=' + secret,
    '/enroll?invite=' + secret, '/enroll#invite=' + secret + '&invite=' + secret, '/enroll#invite=' + secret + '&extra=1',
    'javascript:alert(1)', 'A'.repeat(44)]) {
    const w = environment(); input(w, 'gateEnrollmentInvite', value); w.context.gateOpenEnrollment();
    assert.equal(w.destinations.length, 0, value); assert.equal(w.requests.length, 0, value);
    assert.equal(w.nodes.get('#gateEnrollmentInvite').value, '', value);
    assert.equal(w.nodes.get('#gateEnrollmentNote').classList.contains('error'), true, value);
    assert.equal(w.nodes.get('#gateEnrollmentNote').textContent.includes(secret), false, value);
  }
});

test('switching away from Registration clears an unsubmitted invitation', () => {
  const w = environment(); w.context.setGateAuthMode('registration'); input(w, 'gateEnrollmentInvite', 'C'.repeat(43));
  w.context.setGateAuthMode('login'); assert.equal(w.nodes.get('#gateEnrollmentInvite').value, ''); assert.equal(w.storage.size, 0);
});

test('login validates required credentials and shows a server rejection without opening the app', async () => {
  const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: false});
  await w.context.gateLogin(); assert.equal(w.requests.length, 0); assert.equal(w.nodes.get('#gateLoginNote').classList.contains('error'), true);
  input(w, 'gateLoginUsername', 'testowner'); input(w, 'gateLoginPassword', 'wrong');
  const pending = w.context.gateLogin(); w.requests[0].reject(new Error('Sai tên đăng nhập hoặc mật khẩu')); await pending;
  assert.equal(w.state.authUser, null); assert.equal(w.shell.inert, true); assert.equal(w.calls.includes('boot'), false);
  assert.equal(w.nodes.get('#gateLoginNote').textContent, 'Sai tên đăng nhập hoặc mật khẩu'); assert.equal(w.nodes.get('#gateLoginBtn').disabled, false);
});

test('duplicate Login submissions are single-flight and the server session is verified before app startup', async () => {
  const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: false});
  input(w, 'gateLoginUsername', 'testowner'); input(w, 'gateLoginPassword', 'TestOnlyPassword!550');
  const first = w.context.gateLogin(), duplicate = w.context.gateLogin();
  assert.equal(w.requests.length, 1); assert.equal(w.requests[0].url, '/api/v1/auth/login');
  w.requests[0].resolve({authenticated: true}); await flush();
  assert.equal(w.requests[1].url, '/api/v1/auth/status'); assert.equal(w.calls.includes('boot'), false);
  w.requests[1].resolve({authenticated: true, setup_required: false, user: owner}); await Promise.all([first, duplicate]);
  assert.equal(w.state.authUser, owner); assert.equal(w.shell.inert, false); assert.equal(w.calls.includes('boot'), true);
  assert.equal(w.nodes.get('#gateLoginPassword').value, ''); assert.equal(w.storage.has('campusface_token'), false);
});

test('an MFA challenge keeps the app locked and login/registration entries hidden until cancel or verification', async () => {
  const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: false});
  input(w, 'gateLoginUsername', 'testowner'); input(w, 'gateLoginPassword', 'TestOnlyPassword!550');
  const pending = w.context.gateLogin(); w.requests[0].resolve({mfa_required: true, challenge_id: 'private-challenge', mfa_method: 'TOTP'}); await pending;
  assert.equal(w.state.mfaChallenge, 'private-challenge'); assert.equal(w.state.gateAuthMode, 'mfa');
  assert.equal(visible(w, 'gateMfaView'), true); assert.equal(visible(w, 'gateLoginView'), false); assert.equal(visible(w, 'gateEntryActions'), false);
  assert.equal(w.shell.inert, true); assert.equal(w.state.authUser, null); assert.equal(w.calls.includes('boot'), false); assert.equal(w.requests.length, 1);
});

test('first-owner form validates password confirmation and verifies the created session', async () => {
  const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: true}); w.context.setGateAuthMode('setup');
  input(w, 'gateSetupDisplay', 'Test Owner'); input(w, 'gateSetupUsername', 'testowner');
  input(w, 'gateSetupPassword', 'TestOnlyPassword!550'); input(w, 'gateSetupPassword2', 'mismatch');
  await w.context.gateBootstrap(); assert.equal(w.requests.length, 0); assert.equal(w.nodes.get('#gateSetupNote').classList.contains('error'), true);
  input(w, 'gateSetupPassword2', 'TestOnlyPassword!550'); const first = w.context.gateBootstrap(), duplicate = w.context.gateBootstrap();
  assert.equal(w.requests.length, 1); assert.equal(w.requests[0].url, '/api/v1/auth/bootstrap-local');
  w.requests[0].resolve({authenticated: true}); await flush(); assert.equal(w.calls.includes('boot'), false);
  w.requests[1].resolve({authenticated: true, setup_required: false, user: owner}); await Promise.all([first, duplicate]);
  assert.equal(visible(w, 'gateOpenSetupBtn'), false); assert.equal(w.state.authSetupRequired, false);
  assert.equal(w.nodes.get('#gateSetupPassword').value, ''); assert.equal(w.nodes.get('#gateSetupPassword2').value, '');
  assert.equal(w.calls.includes('boot'), true); assert.equal(w.storage.size, 0);
});

test('Employee portal login is revoked and cannot grant management or enrollment access', async () => {
  const w = environment(); const pending = w.context.enforceManagementPortalAccess({authenticated: true, user: {...owner, role: 'EMPLOYEE', permissions: ['attendance.view.self']}});
  assert.equal(w.requests[0].url, '/api/v1/auth/logout'); w.requests[0].resolve({ok: true}); const result = await pending;
  assert.equal(result.portal_denied, true); assert.equal(w.state.authUser, null); assert.equal(w.shell.inert, true);
  assert.equal(w.nodes.get('#gateLoginNote').classList.contains('error'), true);
});

test('a bootstrap conflict refreshes the server state and closes first-owner setup', async () => {
  for (const status of [400, 409]) {
    const w = environment(); w.context.setAuthGate({authenticated: false, setup_required: true}); w.context.setGateAuthMode('setup');
    input(w, 'gateSetupDisplay', 'Test Owner'); input(w, 'gateSetupUsername', 'testowner');
    input(w, 'gateSetupPassword', 'TestOnlyPassword!550'); input(w, 'gateSetupPassword2', 'TestOnlyPassword!550');
    const pending = w.context.gateBootstrap(); const error = new Error('Hệ thống đã có Chủ sở hữu'); error.status = status;
    w.requests[0].reject(error); await flush(); assert.equal(w.requests[1].url, '/api/v1/auth/status');
    w.requests[1].resolve({authenticated: false, setup_required: false}); await pending;
    assert.equal(visible(w, 'authGateSetup'), false); assert.equal(visible(w, 'gateOpenSetupBtn'), false);
    assert.equal(visible(w, 'gateLoginView'), true); assert.ok(w.nodes.get('#gateLoginNote').textContent.includes('đã được thiết lập'));
  }
});

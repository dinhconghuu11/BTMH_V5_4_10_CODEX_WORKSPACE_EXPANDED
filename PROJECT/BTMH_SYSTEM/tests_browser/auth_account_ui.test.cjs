const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/app.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };

class UiEvent {
  constructor(type, init = {}) { Object.assign(this, init); this.type = type; this.defaultPrevented = false; }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() {}
}
class UiTarget {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, callback) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(callback);
  }
  removeEventListener(type, callback) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter(item => item !== callback));
  }
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    event.currentTarget = this;
    for (const callback of this.listeners.get(event.type) || []) callback(event);
    return !event.defaultPrevented;
  }
}
class UiElement extends UiTarget {
  constructor(id, document, classes = []) {
    super(); this.id = id; this.document = document; this.attributes = new Map();
    this.classes = new Set(classes); this.children = []; this.disabled = false; this.hidden = false;
    this.textContent = ''; this.innerHTML = ''; this.value = ''; this.dataset = {};
    this.classList = {
      contains: name => this.classes.has(name),
      add: (...names) => names.forEach(name => this.classes.add(name)),
      remove: (...names) => names.forEach(name => this.classes.delete(name)),
      toggle: (name, force) => {
        const present = force === undefined ? !this.classes.has(name) : !!force;
        if (present) this.classes.add(name); else this.classes.delete(name);
        return present;
      },
    };
  }
  append(...nodes) { for (const node of nodes) { node.parentElement = this; this.children.push(node); } }
  set textContent(value) { this._textContent = String(value); this._innerHTML = ''; this.children = []; }
  get textContent() { return this._textContent || ''; }
  set innerHTML(value) { this._innerHTML = String(value); this._textContent = ''; this.children = []; }
  get innerHTML() { return this._innerHTML || ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  focus() { this.document.activeElement = this; }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const descendants = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return descendants;
    if (selector === 'span') return descendants.filter(node => node.tagName === 'SPAN');
    if (selector.includes('button') || selector.includes('menuitem')) {
      return descendants.filter(node => node.tagName === 'BUTTON'
        && (!selector.includes('menuitem') || node.getAttribute('role') === 'menuitem')
        && (!selector.includes(':not([hidden])') || !node.hidden)
        && (!selector.includes(':not(.hidden)') || !node.classList.contains('hidden'))
        && (!selector.includes(':not(:disabled)') || !node.disabled)
        && (!selector.includes(':not([disabled])') || !node.disabled));
    }
    return [];
  }
}

function productFunction(context, name) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\n\\}`));
  assert.ok(match, `missing product function ${name}`);
  vm.runInContext(match[0], context);
}
function environment(user = {display_name: 'Người quản lý', username: 'operator', role: 'ADMIN', permissions: ['*']}) {
  const document = Object.assign(new UiTarget(), {hidden: false, activeElement: null});
  const window = new UiTarget(), elements = new Map(), requests = [], calls = [], messages = [];
  const storage = new Map([['campusface_token', 'legacy-test-token'], ['btmh_remembered_username', 'operator']]);
  const add = (id, classes = [], tagName = 'DIV') => {
    const node = new UiElement(id, document, classes); node.tagName = tagName; elements.set(`#${id}`, node); return node;
  };
  const control = add('btmhAccountControl');
  const trigger = add('v23UserChip', [], 'BUTTON'); trigger.setAttribute('aria-expanded', 'false');
  const menu = add('btmhAccountMenu'); menu.hidden = true;
  control.append(trigger, menu);
  for (const id of ['accountMenuName', 'accountMenuUsername', 'accountMenuRole', 'accountMenuNote']) menu.append(add(id));
  const manage = add('accountMenuManageBtn', [], 'BUTTON'), logout = add('accountMenuLogoutBtn', [], 'BUTTON');
  manage.setAttribute('role', 'menuitem'); logout.setAttribute('role', 'menuitem');
  menu.append(manage, logout); logout.textContent = 'Đăng xuất';
  const systemLogout = add('authLogoutBtn', [], 'BUTTON'); systemLogout.textContent = 'Đăng xuất';
  add('v23UserName'); add('v23UserInitial'); add('authGate', ['hidden']); add('authGateSetup', ['hidden']); add('authGateLogin');
  for (const id of ['gateLoginNote', 'gateMfaRecoveryCodes', 'gateMfaSecret', 'gateMfaUri']) add(id);
  for (const id of ['gateLoginPassword', 'gateSetupPassword', 'gateSetupPassword2', 'gateMfaCode']) add(id, [], 'INPUT').value = 'sensitive-test-value';
  elements.get('#gateMfaSecret').textContent = 'sensitive-test-secret';
  elements.get('#gateMfaUri').value = 'sensitive-test-uri';
  elements.get('#gateMfaRecoveryCodes').innerHTML = '<code>sensitive-test-recovery</code>';
  const shell = add('shell'); elements.set('.app-shell', shell);
  const state = {authUser: user, presentationSuspended: false, pagePresented: true, logoutPending: false,
    mfaChallenge: 'test-challenge', mfaSetupRequired: true, mfaRecoveryCodes: ['test-recovery'], pendingMfaStatus: {user}, mfaMethod: 'SMS'};
  const context = {state, document, window, accountMenuUiBound: false,
    $: selector => elements.get(selector) || null,
    $$: selector => selector.includes('logout') ? [logout, systemLogout] : [],
    hasUiPermission: permission => !!state.authUser && (state.authUser.permissions?.includes('*') || state.authUser.permissions?.includes(permission)),
    localStorage: {getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, String(value)), removeItem: key => storage.delete(key)},
    api: (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    toast: (...args) => messages.push(args),
    setAuthFeedback: (selector, message, type) => {
      const node = elements.get(selector); if (!node) return;
      node.textContent = message; node.classList.remove('error', 'success', 'loading'); if (type) node.classList.add(type);
    },
    setGateAuthMode: mode => calls.push(`mode:${mode}`),
    pauseAppPresentation: reason => { state.presentationSuspended = true; calls.push(`pause:${reason}`); },
    applyRoleUi: value => { calls.push(value ? 'role:authenticated' : 'role:signed-out'); context.syncAccountMenu?.(value); },
    navigate: page => calls.push(`navigate:${page}`),
    CustomEvent: UiEvent,
    setTimeout: callback => { callback(); return 1; }, clearTimeout() {},
    requestAnimationFrame: callback => { callback(); return 1; },
  };
  window.btmhSms = {stopLoginTimer: () => calls.push('sms:stop')};
  vm.createContext(context);
  for (const name of ['syncAccountMenu', 'setAccountMenuOpen', 'toggleAccountMenu', 'openCurrentAccountModule', 'bindAccountMenuUI', 'setAuthGate', 'logoutSystem']) productFunction(context, name);
  const event = (target, type, init = {}) => {
    const next = new UiEvent(type, init); target.dispatchEvent(next); return next;
  };
  return {context, state, document, window, elements, requests, calls, messages, storage, control, trigger, menu, manage, logout, systemLogout, shell, event};
}

test('account identity uses text and account navigation respects the current role and permission', () => {
  const cases = [
    ['ADMIN', [], 'admin-security'], ['SUPER_ADMIN', [], 'admin-security'],
    ['TECHNICIAN', ['system.health'], 'system'], ['HR', ['attendance.view'], null],
  ];
  for (const [role, permissions, destination] of cases) {
    const user = {display_name: '<img src=x onerror=alert(1)>', username: 'staff', role, permissions}, w = environment(user);
    w.context.syncAccountMenu(user);
    assert.equal(w.elements.get('#accountMenuName').textContent, user.display_name);
    assert.equal(w.manage.hidden, destination === null);
    w.context.openCurrentAccountModule();
    assert.deepEqual(w.calls.filter(value => value.startsWith('navigate:')), destination ? [`navigate:${destination}`] : []);
  }
});

test('binding once, keyboard movement, Escape and Tab preserve accessible menu behavior', () => {
  const w = environment(); w.context.syncAccountMenu(w.state.authUser); w.context.bindAccountMenuUI(); w.context.bindAccountMenuUI();
  w.event(w.trigger, 'click');
  assert.equal(w.menu.hidden, false); assert.equal(w.trigger.getAttribute('aria-expanded'), 'true');
  w.event(w.trigger, 'keydown', {key: 'ArrowDown'});
  assert.equal(w.document.activeElement, w.manage);
  const down = w.event(w.menu, 'keydown', {key: 'ArrowDown', target: w.manage});
  assert.equal(down.defaultPrevented, true); assert.equal(w.document.activeElement, w.logout);
  w.event(w.menu, 'keydown', {key: 'ArrowDown', target: w.logout}); assert.equal(w.document.activeElement, w.manage);
  w.event(w.menu, 'keydown', {key: 'End', target: w.manage}); assert.equal(w.document.activeElement, w.logout);
  w.event(w.menu, 'keydown', {key: 'Home', target: w.logout}); assert.equal(w.document.activeElement, w.manage);
  w.event(w.menu, 'keydown', {key: 'Escape', target: w.manage});
  assert.equal(w.menu.hidden, true); assert.equal(w.trigger.getAttribute('aria-expanded'), 'false');
  assert.equal(w.document.activeElement, w.trigger);
  w.context.setAccountMenuOpen(true); const tab = w.event(w.menu, 'keydown', {key: 'Tab', target: w.manage});
  assert.equal(w.menu.hidden, true); assert.equal(tab.defaultPrevented, false);
  assert.equal(w.document.activeElement, w.trigger);
});

test('an account without system access can keyboard-focus logout as the only visible action', () => {
  const w = environment({display_name: 'Nhân sự', username: 'hr', role: 'HR', permissions: ['attendance.view']});
  w.context.syncAccountMenu(w.state.authUser); w.context.bindAccountMenuUI();
  w.event(w.trigger, 'keydown', {key: 'ArrowDown'}); assert.equal(w.document.activeElement, w.logout);
});

test('outside interactions and presentation/auth changes close an open menu', () => {
  for (const action of [
    w => w.event(w.document, 'pointerdown', {target: {}}),
    w => w.event(w.document, 'focusin', {target: {}}),
    w => w.event(w.document, 'btmh:navigate', {detail: {page: 'dashboard'}}),
    w => w.event(w.document, 'btmh:auth', {detail: {authenticated: false}}),
    w => { w.document.hidden = true; w.event(w.document, 'visibilitychange'); },
    w => w.event(w.window, 'pagehide'),
  ]) {
    const w = environment(); w.context.syncAccountMenu(w.state.authUser); w.context.bindAccountMenuUI(); w.context.setAccountMenuOpen(true);
    action(w); assert.equal(w.menu.hidden, true); assert.equal(w.trigger.getAttribute('aria-expanded'), 'false');
  }
  const w = environment(); w.context.syncAccountMenu(w.state.authUser); w.context.bindAccountMenuUI(); w.context.setAccountMenuOpen(true);
  w.event(w.document, 'pointerdown', {target: w.logout}); assert.equal(w.menu.hidden, false);
  w.context.syncAccountMenu(null); assert.equal(w.menu.hidden, true);
  w.state.authUser = null; w.context.toggleAccountMenu(); assert.equal(w.menu.hidden, true);
});

test('logout is single-flight and does not claim success when the server cannot revoke the session', async () => {
  const w = environment(), user = w.state.authUser;
  const first = w.context.logoutSystem(), duplicate = w.context.logoutSystem();
  assert.equal(w.requests.length, 1); assert.equal(w.requests[0].url, '/api/v1/auth/logout');
  assert.equal(w.requests[0].options.method, 'POST'); assert.equal(w.requests[0].options.timeoutMs, 8000);
  assert.equal(w.logout.disabled, true); assert.equal(w.systemLogout.disabled, true);
  w.requests[0].reject(new Error('Máy chủ không phản hồi')); await Promise.all([first, duplicate]);
  assert.equal(w.state.authUser, user); assert.equal(w.shell.inert, undefined); assert.equal(w.storage.get('campusface_token'), 'legacy-test-token');
  assert.equal(w.logout.disabled, false); assert.equal(w.systemLogout.disabled, false); assert.equal(w.state.logoutPending, false);
  assert.equal(w.calls.includes('pause:signed-out'), false);
  assert.ok(w.elements.get('#accountMenuNote').textContent.includes('Chưa đăng xuất'));
  assert.equal(w.elements.get('#accountMenuNote').hidden, false);
  assert.equal(w.messages.some(([message]) => message === 'Đã đăng xuất.'), false);
  const retry = w.context.logoutSystem(); assert.equal(w.requests.length, 2); w.requests[1].resolve({ok: true}); await retry;
  assert.equal(w.state.authUser, null);
});

test('successful logout clears gate secrets, broadcasts signout, pauses presentation and preserves remembered username', async () => {
  const w = environment(); w.context.syncAccountMenu(w.state.authUser); w.context.setAccountMenuOpen(true);
  const changes = []; w.document.addEventListener('btmh:auth', event => changes.push(event.detail));
  const pending = w.context.logoutSystem(); assert.notEqual(w.state.authUser, null);
  w.requests[0].resolve({ok: true}); await pending; await flush();
  assert.equal(w.state.authUser, null); assert.equal(w.shell.inert, true); assert.equal(w.storage.has('campusface_token'), false);
  assert.equal(w.storage.get('btmh_remembered_username'), 'operator');
  assert.equal(w.state.mfaChallenge, ''); assert.equal(w.state.mfaSetupRequired, false); assert.equal(w.state.mfaRecoveryCodes.length, 0); assert.equal(w.state.pendingMfaStatus, null);
  for (const id of ['gateLoginPassword', 'gateMfaCode', 'gateMfaUri']) assert.equal(w.elements.get(`#${id}`).value, '', id);
  assert.equal(w.elements.get('#gateMfaRecoveryCodes').innerHTML, '');
  assert.notEqual(w.elements.get('#gateMfaSecret').textContent, 'sensitive-test-secret');
  assert.equal(w.menu.hidden, true); assert.equal(w.elements.get('#authGate').classList.contains('hidden'), false);
  assert.ok(w.calls.includes('pause:signed-out')); assert.ok(w.calls.includes('sms:stop'));
  assert.equal(changes.length, 1); assert.equal(changes[0].authenticated, false); assert.equal(changes[0].user, null);
  assert.equal(w.logout.disabled, false); assert.equal(w.systemLogout.disabled, false);
});

test('an already expired session is signed out locally after HTTP 401', async () => {
  const w = environment(), pending = w.context.logoutSystem();
  const error = new Error('HTTP 401'); error.status = 401; w.requests[0].reject(error); await pending;
  assert.equal(w.state.authUser, null); assert.equal(w.shell.inert, true); assert.equal(w.storage.has('campusface_token'), false);
});

test('api keeps HTTP status on auth errors so logout can distinguish expiration from transport failure', async () => {
  const w = environment();
  w.context.BTMHRuntime = {request: async () => ({ok: false, status: 401, json: async () => ({detail: 'Expired'}), headers: {get: () => null}})};
  productFunction(w.context, 'api');
  await assert.rejects(w.context.api('/api/v1/auth/logout', {method: 'POST'}), error => error.status === 401 && error.message === 'Expired');
  assert.notEqual(w.state.authUser, null);
});

test('duplicate MFA verification events issue one request and recover after rejection', async () => {
  const w = environment(), button = new UiElement('gateMfaVerifyBtn', w.document), trust = new UiElement('gateTrustBrowser', w.document);
  trust.checked = false;
  w.elements.set('#gateMfaVerifyBtn', button); w.elements.set('#gateTrustBrowser', trust);
  w.elements.set('#gateMfaNote', new UiElement('gateMfaNote', w.document));
  w.elements.get('#gateMfaCode').value = '123456';
  productFunction(w.context, 'gateMfaVerify');
  const first = w.context.gateMfaVerify(), duplicate = w.context.gateMfaVerify();
  assert.equal(w.requests.length, 1); assert.equal(button.disabled, true);
  assert.equal(w.requests[0].url, '/api/v1/auth/sms/verify');
  w.requests[0].reject(new Error('Mã xác minh không hợp lệ')); await Promise.all([first, duplicate]);
  assert.equal(button.disabled, false); assert.equal(w.elements.get('#gateMfaNote').classList.contains('error'), true);
});

test('an auth-status response started before logout cannot restore the signed-out session', async () => {
  const w = environment(), user = w.state.authUser;
  productFunction(w.context, 'loadAuthStatus');
  const status = w.context.loadAuthStatus(), logout = w.context.logoutSystem();
  assert.equal(w.requests.length, 2); assert.equal(w.requests[0].url, '/api/v1/auth/status');
  w.requests[1].resolve({ok: true}); await logout;
  assert.equal(w.state.authUser, null); assert.equal(w.shell.inert, true);
  w.requests[0].resolve({authenticated: true, setup_required: false, user}); await status;
  assert.equal(w.state.authUser, null); assert.equal(w.shell.inert, true);
  assert.equal(w.elements.get('#authGate').classList.contains('hidden'), false);
});

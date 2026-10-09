/* Execute with node --test; behavioral DOM/API fixtures, no server/customer data. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/btmh_account_profile.js'), 'utf8');
const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

class Target {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, handler) { if (!this.listeners.has(type)) this.listeners.set(type, []); this.listeners.get(type).push(handler); }
  removeEventListener(type, handler) { this.listeners.set(type, (this.listeners.get(type) || []).filter(fn => fn !== handler)); }
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    for (const handler of this.listeners.get(event.type) || []) handler(event);
    return !event.defaultPrevented;
  }
}
class Element extends Target {
  constructor(tag, document) {
    super(); this.tagName = tag.toUpperCase(); this.document = document; this.attributes = new Map(); this.children = [];
    this.dataset = {}; this.disabled = false; this.value = ''; this.open = false; this.textContent = ''; this.isConnected = true;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  get hidden() { return this.attributes.has('hidden'); }
  set hidden(value) { if (value) this.attributes.set('hidden', ''); else this.attributes.delete('hidden'); }
  get type() { return this.getAttribute('type') || 'text'; }
  set type(value) { this.setAttribute('type', value); }
  append(...children) { for (const child of children) { child.parentElement = this; this.children.push(child); } }
  remove() { this.isConnected = false; if (this.parentElement) this.parentElement.children = this.parentElement.children.filter(child => child !== this); }
  focus() { if (!this.disabled) this.document.activeElement = this; }
  closest(selector) { if (selector === '[hidden]' && this.hidden) return this; return this.parentElement?.closest(selector) || null; }
  querySelectorAll(selector) {
    const children = this.children.flatMap(child => [child, ...child.querySelectorAll('*')]);
    if (selector === '*') return children;
    return children.filter(child => selector.split(',').some(part => part.trim().toUpperCase() === child.tagName)
      || selector.includes('[tabindex]') && child.getAttribute('tabindex') !== null);
  }
  showModal() { this.open = true; this.setAttribute('open', ''); }
  close() { this.open = false; this.removeAttribute('open'); this.dispatchEvent({type: 'close'}); }
}
function fixture(overrides = {}) {
  const document = new Target(), window = new Target();
  document.activeElement = null; document.hidden = false;
  document.createElement = tag => new Element(tag, document);
  document.body = document.createElement('body');
  document.getElementById = id => document.body.querySelectorAll('*').find(node => node.getAttribute('id') === id) || null;
  const state = {authUser: {id: 1, username: 'staff', display_name: 'Người dùng', role: 'HR'}};
  const calls = [], requests = [], toasts = [], changes = [];
  const config = {state,
    api: (url, options = {}) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject})),
    logout: async () => { calls.push('logout'); state.authUser = null; },
    onUserChanged: user => changes.push(user), toast: message => toasts.push(message),
    openSecurity: () => calls.push('security'), ...overrides};
  vm.runInNewContext(source, {window, document});
  const adapter = window.btmhAccountProfile.install(config);
  const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus();
  const find = id => document.getElementById(`btmhAccount_${id}`);
  const all = () => document.body.querySelectorAll('*');
  const dialog = () => all().find(node => node.tagName === 'DIALOG');
  const button = text => all().find(node => node.tagName === 'BUTTON' && node.textContent === text);
  const forms = () => all().filter(node => node.tagName === 'FORM');
  const event = (target, type, values = {}) => {
    const next = {type, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...values};
    target.dispatchEvent(next); return next;
  };
  const profile = security => ({user: {id: 1, username: 'staff', display_name: 'Người dùng', role: 'HR', role_label: 'Nhân sự',
    email: '', phone: '', store_name: 'Store A'}, security: {enabled: false, fresh_verification: false, ...security}, editable_fields: ['display_name']});
  async function opened(mode = 'profile', security) {
    adapter[mode === 'profile' ? 'openProfile' : 'openPassword'](trigger);
    requests.at(-1).resolve(profile(security)); await flush();
  }
  const fill = (password = 'SyntheticTestPassword!550') => {
    find('current_password').value = 'SyntheticCurrentPassword!550';
    find('new_password').value = password; find('confirm_password').value = password;
  };
  return {document, window, state, config, calls, requests, toasts, changes, adapter, trigger, find, all, dialog, button, forms, event, profile, opened, fill};
}

test('profile is mounted once, safely displays user text, read-only contact/store labels and focuses name', async () => {
  const w = fixture(); w.adapter.openProfile(w.trigger);
  assert.equal(w.requests[0].url, '/api/v1/auth/profile');
  assert.equal(w.find('display_name').disabled, true);
  const out = w.profile(); out.user.display_name = '<img src=x onerror=alert(1)>';
  w.requests[0].resolve(out); await flush();
  assert.equal(w.dialog().open, true);
  assert.equal(w.dialog().getAttribute('aria-labelledby'), 'btmhAccountProfileTitle');
  assert.equal(w.find('display_name').value, out.user.display_name);
  assert.equal(w.document.activeElement, w.find('display_name'));
  assert.ok(w.all().some(node => node.tagName === 'DD' && node.textContent === 'Chưa cung cấp'));
  assert.ok(w.all().some(node => node.tagName === 'DD' && node.textContent === 'Store A'));
  assert.equal(w.all().filter(node => node.tagName === 'INPUT').length, 4);
  w.adapter.close(); await w.opened();
  assert.equal(w.all().filter(node => node.tagName === 'DIALOG').length, 1);
});

test('name save is single-flight, payload has only display_name and updates menu state after server success', async () => {
  const w = fixture(); await w.opened();
  w.find('display_name').value = '  New Name  ';
  w.event(w.forms()[0], 'submit'); w.event(w.forms()[0], 'submit');
  assert.equal(w.requests.length, 2);
  assert.equal(w.requests[1].url, '/api/v1/auth/profile');
  assert.equal(w.requests[1].options.method, 'PUT');
  assert.deepEqual(JSON.parse(w.requests[1].options.body), {display_name: 'New Name'});
  assert.equal(w.state.authUser.display_name, 'Người dùng');
  const out = w.profile(); out.user.display_name = 'New Name';
  w.requests[1].resolve(out); await flush();
  assert.equal(w.state.authUser.display_name, 'New Name'); assert.equal(w.changes.length, 1);
  assert.equal(w.button('Lưu thay đổi').disabled, false);
});

test('empty name and password confirmation produce inline focus errors without calling API', async () => {
  const w = fixture(); await w.opened();
  w.find('display_name').value = '   '; w.event(w.forms()[0], 'submit');
  assert.equal(w.requests.length, 1);
  assert.equal(w.find('display_name').getAttribute('aria-invalid'), 'true');
  assert.equal(w.find('display_name_error').hidden, false);
  w.event(w.find('display_name'), 'input'); assert.equal(w.find('display_name_error').hidden, true);
  w.adapter.openPassword(w.trigger); w.requests.at(-1).resolve(w.profile()); await flush();
  w.fill(); w.find('confirm_password').value = 'Different!550'; w.event(w.forms()[1], 'submit');
  assert.equal(w.requests.length, 2);
  assert.equal(w.document.activeElement, w.find('confirm_password'));
  assert.equal(w.find('confirm_password').getAttribute('aria-invalid'), 'true');
});

test('password change sends existing-policy payload once, immediately clears secrets and signs out on success', async () => {
  const w = fixture(); await w.opened('password'); w.fill('Đặngngọcước!12345');
  w.event(w.forms()[1], 'submit'); w.event(w.forms()[1], 'submit');
  assert.equal(w.requests.length, 2);
  const request = w.requests[1]; assert.equal(request.url, '/api/v1/auth/password'); assert.equal(request.options.method, 'PUT');
  assert.equal(JSON.parse(request.options.body).new_password, 'Đặngngọcước!12345');
  for (const name of ['current_password', 'new_password', 'confirm_password']) assert.equal(w.find(name).value, '');
  assert.equal(w.state.authUser.id, 1); assert.equal(w.calls.length, 0);
  request.resolve({ok: true, relogin_required: true}); await flush();
  assert.deepEqual(w.calls, ['logout']); assert.equal(w.state.authUser, null); assert.equal(w.dialog().open, false);
  assert.equal(w.toasts.length, 1);
});

test('server field errors remain inline after secrets clear and network failure keeps authenticated state', async () => {
  const w = fixture(); await w.opened('password'); w.fill(); w.event(w.forms()[1], 'submit');
  w.requests[1].reject(Object.assign(new Error('Mật khẩu hiện tại chưa đúng.'), {status: 400, code: 'CURRENT_PASSWORD_INVALID', field: 'current_password'}));
  await flush();
  assert.equal(w.find('current_password').value, '');
  assert.equal(w.find('current_password_error').hidden, false);
  assert.equal(w.find('current_password').getAttribute('aria-invalid'), 'true');
  assert.equal(w.document.activeElement, w.find('current_password'));
  assert.equal(w.state.authUser.id, 1); assert.equal(w.calls.length, 0);
  w.fill(); w.event(w.forms()[1], 'submit'); w.requests[2].reject(new Error('Máy chủ chưa phản hồi.')); await flush();
  assert.equal(w.state.authUser.id, 1); assert.equal(w.dialog().open, true);
  assert.equal(w.button('Đổi mật khẩu').disabled, false);
});

test('stale second factor gates password fields and uses existing security action; STEP_UP_REQUIRED remains gated', async () => {
  const w = fixture(); await w.opened('password', {enabled: true, method: 'SMS', fresh_verification: false});
  assert.equal(w.find('current_password').disabled, true);
  assert.equal(w.document.activeElement, w.button('Xác minh tài khoản'));
  w.event(w.forms()[1], 'submit'); assert.equal(w.requests.length, 1);
  w.event(w.button('Xác minh tài khoản'), 'click'); assert.deepEqual(w.calls, ['security']); assert.equal(w.dialog().open, false);
  await w.opened('password', {enabled: true, fresh_verification: true}); w.fill(); w.event(w.forms()[1], 'submit');
  w.requests.at(-1).reject(Object.assign(new Error('Cần xác minh lại.'), {status: 403, code: 'STEP_UP_REQUIRED'})); await flush();
  assert.equal(w.find('current_password').disabled, true);
});

test('without a security adapter, revalidation offers logout and does not downgrade enrolled factor', async () => {
  const w = fixture({openSecurity: undefined}); await w.opened('password', {enabled: true, fresh_verification: false});
  assert.equal(w.find('current_password').disabled, true);
  w.event(w.button('Đăng xuất để xác minh'), 'click'); await flush();
  assert.deepEqual(w.calls, ['logout']);
});

test('Escape, reveal toggle, focus loop and return preserve keyboard behavior and clear password controls', async () => {
  const w = fixture(); await w.opened('password'); w.fill();
  const reveal = w.all().find(node => node.getAttribute('aria-controls') === 'btmhAccount_current_password');
  w.event(reveal, 'click'); assert.equal(w.find('current_password').type, 'text'); assert.equal(reveal.getAttribute('aria-pressed'), 'true');
  const close = w.button('Đóng'); close.focus();
  const backward = w.event(w.dialog(), 'keydown', {key: 'Tab', shiftKey: true});
  assert.equal(backward.defaultPrevented, true);
  assert.equal(w.document.activeElement, w.all().filter(node => node.tagName === 'BUTTON' && node.textContent === 'Đổi mật khẩu').at(-1));
  const forward = w.event(w.dialog(), 'keydown', {key: 'Tab'});
  assert.equal(forward.defaultPrevented, true); assert.equal(w.document.activeElement, close);
  w.event(w.dialog(), 'keydown', {key: 'Escape'});
  assert.equal(w.dialog().open, false); assert.equal(w.document.activeElement, w.trigger);
  for (const name of ['current_password', 'new_password', 'confirm_password']) {
    assert.equal(w.find(name).value, ''); assert.equal(w.find(name).type, 'password');
  }
});

test('closed/hidden/signed-out dialogs ignore stale profile responses and clear secrets', async () => {
  for (const action of [w => w.adapter.close(), w => { w.document.hidden = true; w.event(w.document, 'visibilitychange'); },
    w => w.event(w.window, 'pagehide'), w => w.event(w.document, 'btmh:auth', {detail: {authenticated: false}})]) {
    const w = fixture(); w.adapter.openPassword(w.trigger); w.fill(); action(w);
    w.requests[0].resolve(w.profile()); await flush();
    assert.equal(w.dialog().open, false); assert.equal(w.find('current_password').value, '');
    assert.equal(w.changes.length, 0);
  }
});

test('late profile save cannot overwrite a replacement signed-in user, and expired credential response returns login', async () => {
  const w = fixture(); await w.opened(); w.find('display_name').value = 'New Name'; w.event(w.forms()[0], 'submit');
  w.state.authUser = {id: 2, display_name: 'Replacement user'};
  const out = w.profile(); out.user.display_name = 'Old user response'; w.requests[1].resolve(out); await flush();
  assert.equal(w.state.authUser.id, 2); assert.equal(w.state.authUser.display_name, 'Replacement user'); assert.equal(w.changes.length, 0);
  const other = fixture(); await other.opened('password'); other.fill(); other.event(other.forms()[1], 'submit');
  other.requests[1].reject(Object.assign(new Error('Credentials changed.'), {status: 409, code: 'CREDENTIALS_CHANGED'})); await flush();
  assert.deepEqual(other.calls, ['logout']); assert.equal(other.dialog().open, false);
});

test('loading failure can retry, session-expiry closes, and duplicate install/destroy removes listeners', async () => {
  const w = fixture(); w.adapter.openProfile(w.trigger); w.requests[0].reject(new Error('Mất kết nối.')); await flush();
  assert.equal(w.button('Lưu thay đổi').disabled, true); assert.equal(w.button('Thử lại').hidden, false);
  w.event(w.button('Thử lại'), 'click'); w.requests[1].resolve(w.profile()); await flush();
  assert.equal(w.button('Lưu thay đổi').disabled, false);
  const adapter = w.window.btmhAccountProfile.install(w.config);
  assert.equal(w.all().filter(node => node.tagName === 'DIALOG').length, 0);
  assert.equal(w.document.listeners.get('btmh:auth').length, 1);
  adapter.openProfile(w.trigger); w.requests[2].reject(Object.assign(new Error('Expired'), {status: 401})); await flush();
  assert.deepEqual(w.calls, ['logout']); adapter.destroy();
  assert.equal(w.document.listeners.get('btmh:auth').length, 0);
  assert.equal(w.all().filter(node => node.tagName === 'DIALOG').length, 0);
  assert.equal(adapter.openProfile(w.trigger), false);
});

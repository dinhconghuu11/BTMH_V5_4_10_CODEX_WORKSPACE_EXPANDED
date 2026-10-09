/* Account profile/password dialogs; existing application owns auth and cookies. */
(function (window, document) {
  'use strict';
  let installed = null;

  function install(config) {
    if (installed) installed.destroy();
    if (!config || typeof config.api !== 'function' || !config.state) throw new Error('Account adapter required');
    const nodes = {}, cleanups = [];
    let dialog = null, profile = null, mode = 'profile', generation = 0;
    let loaded = false, loading = false, mutating = false, returnFocus = null, userId = null;
    const user = () => config.state.authUser;
    const listen = (target, type, handler) => {
      target.addEventListener(type, handler);
      cleanups.push(() => target.removeEventListener(type, handler));
    };
    function element(tag, attributes = {}, text) {
      const node = document.createElement(tag);
      for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function field(form, name, labelText, type = 'text', autocomplete = '') {
      const wrap = element('div', {class: 'btmh-profile-field'});
      const id = `btmhAccount_${name}`;
      const label = element('label', {for: id}, labelText);
      const input = element('input', {id, name, type, autocomplete, required: '', 'aria-describedby': `${id}_error`});
      input.maxLength = type === 'password' ? 256 : 120;
      const error = element('p', {id: `${id}_error`, class: 'btmh-profile-field-error', hidden: ''});
      const control = element('div', {class: 'btmh-profile-input-row'});
      control.append(input);
      if (type === 'password') {
        const toggle = element('button', {type: 'button', class: 'btmh-profile-reveal', 'aria-controls': id,
          'aria-label': `Hiện ${labelText.toLowerCase()}`, 'aria-pressed': 'false'}, 'Hiện');
        listen(toggle, 'click', () => {
          const visible = input.type === 'password';
          input.type = visible ? 'text' : 'password';
          toggle.textContent = visible ? 'Ẩn' : 'Hiện';
          toggle.setAttribute('aria-label', `${visible ? 'Ẩn' : 'Hiện'} ${labelText.toLowerCase()}`);
          toggle.setAttribute('aria-pressed', String(visible));
          input.focus();
        });
        control.append(toggle);
        nodes[`${name}Toggle`] = toggle;
      }
      wrap.append(label, control, error);
      form.append(wrap);
      nodes[name] = input;
      nodes[`${name}Error`] = error;
      listen(input, 'input', () => {
        input.removeAttribute('aria-invalid');
        error.textContent = '';
        error.hidden = true;
      });
    }
    function note(message = '', kind = '') {
      nodes.note.textContent = message;
      nodes.note.dataset.kind = kind;
      nodes.note.hidden = !message;
    }
    function clearSecrets(clearErrors = true) {
      for (const name of ['current_password', 'new_password', 'confirm_password']) {
        if (!nodes[name]) continue;
        nodes[name].value = '';
        nodes[name].type = 'password';
        if (clearErrors) {
          nodes[name].removeAttribute('aria-invalid');
          nodes[`${name}Error`].textContent = '';
          nodes[`${name}Error`].hidden = true;
        }
        nodes[`${name}Toggle`].textContent = 'Hiện';
        nodes[`${name}Toggle`].setAttribute('aria-pressed', 'false');
        nodes[`${name}Toggle`].setAttribute('aria-label', `Hiện ${name === 'current_password' ? 'mật khẩu hiện tại' : name === 'new_password' ? 'mật khẩu mới' : 'mật khẩu xác nhận'}`);
      }
    }
    function needsVerification() { return !!profile?.security?.enabled && !profile.security.fresh_verification; }
    function busy() {
      const pending = loading || mutating;
      dialog.setAttribute('aria-busy', String(pending));
      nodes.nameSave.disabled = pending || !loaded;
      nodes.display_name.disabled = pending || !loaded;
      nodes.passwordSave.disabled = pending || !loaded || needsVerification();
      nodes.passwordSave.textContent = mutating && mode === 'password' ? 'Đang đổi mật khẩu…' : 'Đổi mật khẩu';
      nodes.nameSave.textContent = mutating && mode === 'profile' ? 'Đang lưu…' : 'Lưu thay đổi';
      nodes.switchPassword.disabled = pending || !loaded;
      nodes.retry.disabled = pending;
      for (const name of ['current_password', 'new_password', 'confirm_password']) {
        nodes[name].disabled = pending || !loaded || needsVerification();
        nodes[`${name}Toggle`].disabled = nodes[name].disabled;
      }
      nodes.verification.hidden = mode !== 'password' || !needsVerification();
      nodes.verify.disabled = pending;
    }
    function renderProfile(value) {
      profile = value;
      const account = value.user || {};
      nodes.identity.textContent = account.username ? `Tên đăng nhập: ${account.username}` : '';
      nodes.display_name.value = account.display_name || '';
      nodes.role.textContent = account.role_label || 'Chưa xác định';
      nodes.email.textContent = account.email || 'Chưa cung cấp';
      nodes.phone.textContent = account.phone || 'Chưa cung cấp';
      nodes.store.textContent = account.store_name || 'Chưa gán cửa hàng';
      nodes.verify.textContent = typeof config.openSecurity === 'function' ? 'Xác minh tài khoản' : 'Đăng xuất để xác minh';
      loaded = true;
      busy();
    }
    function currentFocus() { return mode === 'profile' ? nodes.display_name : needsVerification() ? nodes.verify : nodes.current_password; }
    function close(restore = true) {
      if (!dialog) return;
      generation++;
      loading = false;
      clearSecrets();
      nodes.display_name.value = '';
      note();
      if (dialog.open) {
        if (typeof dialog.close === 'function') dialog.close();
        else dialog.removeAttribute('open');
      }
      if (restore && returnFocus?.isConnected !== false && typeof returnFocus?.focus === 'function' && user()) returnFocus.focus();
      returnFocus = null;
    }
    function errorMessage(error) {
      return typeof error?.message === 'string' && error.message ? error.message : 'Chưa hoàn tất. Kiểm tra kết nối rồi thử lại.';
    }
    async function expire() {
      close(false);
      if (typeof config.logout === 'function') await config.logout();
    }
    function fieldError(name, message) {
      if (!nodes[name] || !nodes[`${name}Error`]) return false;
      nodes[name].setAttribute('aria-invalid', 'true');
      nodes[`${name}Error`].textContent = message;
      nodes[`${name}Error`].hidden = false;
      nodes[name].focus();
      return true;
    }
    async function load() {
      const turn = ++generation, expectedUser = user()?.id;
      loaded = false; loading = true;
      busy(); note('Đang tải thông tin tài khoản…', 'loading'); nodes.retry.hidden = true;
      try {
        const out = await config.api('/api/v1/auth/profile', {timeoutMs: 8000});
        if (turn !== generation || !dialog.open || user()?.id !== expectedUser) return;
        loading = false;
        renderProfile(out);
        note();
        currentFocus().focus();
      } catch (error) {
        if (turn !== generation || !dialog.open) return;
        loading = false;
        if (error?.status === 401 || error?.code === 'SESSION_EXPIRED') { await expire(); return; }
        note(errorMessage(error), 'error'); nodes.retry.hidden = false;
      } finally {
        if (turn === generation && dialog.open) busy();
      }
    }
    function switchMode(next) {
      mode = next;
      clearSecrets(); note();
      nodes.title.textContent = mode === 'profile' ? 'Hồ sơ tài khoản' : 'Đổi mật khẩu';
      nodes.profileForm.hidden = mode !== 'profile';
      nodes.passwordForm.hidden = mode !== 'password';
      nodes.identity.hidden = mode !== 'profile';
      nodes.retry.hidden = true;
      busy();
      if (loaded) currentFocus().focus();
    }
    async function saveName(event) {
      event.preventDefault();
      if (mutating || loading || !loaded) return;
      const displayName = nodes.display_name.value.trim(), expectedUser = user()?.id;
      if (!displayName) { fieldError('display_name', 'Nhập tên hiển thị của bạn.'); return; }
      mutating = true; busy(); note('Đang lưu tên hiển thị…', 'loading');
      try {
        const out = await config.api('/api/v1/auth/profile', {method: 'PUT', body: JSON.stringify({display_name: displayName}), timeoutMs: 8000});
        if (user()?.id === expectedUser && out.user) {
          config.state.authUser = out.user;
          if (typeof config.onUserChanged === 'function') config.onUserChanged(out.user);
          if (dialog.open && mode === 'profile') { renderProfile(out); note('Đã lưu tên hiển thị.', 'success'); }
        }
      } catch (error) {
        if (error?.status === 401) { await expire(); return; }
        if (dialog.open) { note(errorMessage(error), 'error'); fieldError(error?.field || '', errorMessage(error)); }
      } finally { mutating = false; if (dialog.open) busy(); }
    }
    async function savePassword(event) {
      event.preventDefault();
      if (mutating || loading || !loaded || needsVerification()) return;
      const expectedUser = user()?.id;
      const payload = {current_password: nodes.current_password.value, new_password: nodes.new_password.value,
        confirm_password: nodes.confirm_password.value};
      if (!payload.current_password) { fieldError('current_password', 'Nhập mật khẩu hiện tại.'); return; }
      // Character strength remains the existing server policy, which supports
      // Unicode. An ASCII-only browser check would reject valid Vietnamese text.
      if (payload.new_password.length < 12 || payload.new_password.length > 256) {
        fieldError('new_password', 'Dùng ít nhất 12 ký tự, gồm chữ hoa, chữ thường, số và ký tự đặc biệt.'); return;
      }
      if (payload.new_password !== payload.confirm_password) { fieldError('confirm_password', 'Mật khẩu xác nhận chưa khớp.'); return; }
      mutating = true; clearSecrets(); busy(); note('Đang đổi mật khẩu…', 'loading');
      try {
        const out = await config.api('/api/v1/auth/password', {method: 'PUT', body: JSON.stringify(payload), timeoutMs: 8000});
        if (user()?.id !== expectedUser) return;
        if (out.relogin_required) {
          close(false);
          if (typeof config.toast === 'function') config.toast('Đã đổi mật khẩu. Hãy đăng nhập lại.');
          if (typeof config.logout === 'function') await config.logout();
        }
      } catch (error) {
        if (user()?.id !== expectedUser) return;
        if (error?.status === 401 || error?.code === 'CREDENTIALS_CHANGED') { await expire(); return; }
        if (error?.code === 'STEP_UP_REQUIRED' && profile?.security) profile.security.fresh_verification = false;
        if (dialog.open) {
          mutating = false; busy();
          note(errorMessage(error), 'error');
          fieldError(error?.field || '', errorMessage(error));
        }
      } finally {
        payload.current_password = payload.new_password = payload.confirm_password = '';
        mutating = false; clearSecrets(false); if (dialog.open) busy();
      }
    }
    function mount() {
      if (dialog) return;
      dialog = element('dialog', {class: 'btmh-account-dialog', 'aria-labelledby': 'btmhAccountProfileTitle'});
      const header = element('header', {class: 'btmh-profile-header'});
      nodes.title = element('h2', {id: 'btmhAccountProfileTitle'}, 'Hồ sơ tài khoản');
      nodes.close = element('button', {type: 'button', class: 'btmh-profile-close', 'aria-label': 'Đóng hồ sơ tài khoản'}, 'Đóng');
      header.append(nodes.title, nodes.close);
      const content = element('div', {class: 'btmh-profile-content'});
      nodes.identity = element('p', {class: 'btmh-profile-identity'});
      nodes.note = element('p', {class: 'btmh-profile-note', role: 'status', 'aria-live': 'polite', 'aria-atomic': 'true', hidden: ''});
      nodes.retry = element('button', {type: 'button', class: 'btn ghost', hidden: ''}, 'Thử lại');
      nodes.profileForm = element('form', {class: 'btmh-profile-form'});
      field(nodes.profileForm, 'display_name', 'Tên hiển thị', 'text', 'name');
      const details = element('dl', {class: 'btmh-profile-details'});
      for (const [key, label] of [['role', 'Vai trò'], ['email', 'Email'], ['phone', 'Số điện thoại'], ['store', 'Cửa hàng']]) {
        const pair = element('div');
        nodes[key] = element('dd', {}, 'Đang tải…');
        pair.append(element('dt', {}, label), nodes[key]); details.append(pair);
      }
      const actions = element('div', {class: 'btmh-profile-actions'});
      nodes.switchPassword = element('button', {type: 'button', class: 'btn ghost'}, 'Đổi mật khẩu');
      nodes.nameSave = element('button', {type: 'submit', class: 'btn primary'}, 'Lưu thay đổi');
      actions.append(nodes.switchPassword, nodes.nameSave);
      nodes.profileForm.append(details, element('p', {class: 'btmh-profile-help'}, 'Thông tin liên hệ và cửa hàng do quản trị viên quản lý.'), actions);
      nodes.passwordForm = element('form', {class: 'btmh-profile-form', hidden: ''});
      nodes.verification = element('div', {class: 'btmh-profile-verification', hidden: ''});
      nodes.verify = element('button', {type: 'button', class: 'btn ghost'}, 'Xác minh tài khoản');
      nodes.verification.append(element('p', {}, 'Cần xác minh lại tài khoản trước khi đổi mật khẩu.'), nodes.verify);
      nodes.passwordForm.append(nodes.verification);
      field(nodes.passwordForm, 'current_password', 'Mật khẩu hiện tại', 'password', 'current-password');
      field(nodes.passwordForm, 'new_password', 'Mật khẩu mới', 'password', 'new-password');
      field(nodes.passwordForm, 'confirm_password', 'Xác nhận mật khẩu mới', 'password', 'new-password');
      nodes.passwordForm.append(element('p', {class: 'btmh-profile-help'}, 'Ít nhất 12 ký tự, gồm chữ hoa, chữ thường, số và ký tự đặc biệt. Sau khi đổi, hãy đăng nhập lại trên các thiết bị.'));
      const passwordActions = element('div', {class: 'btmh-profile-actions'});
      nodes.back = element('button', {type: 'button', class: 'btn ghost'}, 'Về hồ sơ');
      nodes.passwordSave = element('button', {type: 'submit', class: 'btn primary'}, 'Đổi mật khẩu');
      passwordActions.append(nodes.back, nodes.passwordSave); nodes.passwordForm.append(passwordActions);
      content.append(nodes.identity, nodes.profileForm, nodes.passwordForm, nodes.note, nodes.retry);
      dialog.append(header, content); document.body.append(dialog);
      listen(nodes.close, 'click', () => close());
      listen(dialog, 'cancel', event => { event.preventDefault(); close(); });
      listen(dialog, 'close', () => { clearSecrets(); });
      listen(nodes.retry, 'click', load);
      listen(nodes.switchPassword, 'click', () => switchMode('password'));
      listen(nodes.back, 'click', () => switchMode('profile'));
      listen(nodes.verify, 'click', async () => {
        close();
        if (typeof config.openSecurity === 'function') config.openSecurity();
        else if (typeof config.logout === 'function') await config.logout();
      });
      listen(nodes.profileForm, 'submit', saveName);
      listen(nodes.passwordForm, 'submit', savePassword);
      listen(dialog, 'keydown', event => {
        if (event.key === 'Escape') { event.preventDefault(); close(); return; }
        if (event.key !== 'Tab') return;
        const focusable = Array.from(dialog.querySelectorAll('button,input,[tabindex]')).filter(node => !node.disabled
          && !node.hidden && !node.closest('[hidden]') && node.getAttribute('tabindex') !== '-1');
        if (!focusable.length) { event.preventDefault(); return; }
        const first = focusable[0], last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      });
    }
    function open(next, trigger) {
      if (!user()) return false;
      mount();
      returnFocus = trigger || document.activeElement;
      userId = user().id;
      profile = null; loaded = false;
      switchMode(next);
      if (!dialog.open) {
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else { dialog.setAttribute('open', ''); dialog.setAttribute('role', 'dialog'); dialog.setAttribute('aria-modal', 'true'); }
      }
      nodes.close.focus();
      load();
      return true;
    }
    listen(document, 'btmh:auth', event => {
      if (!event.detail?.authenticated || (event.detail.user?.id !== undefined && event.detail.user.id !== userId)) close(false);
    });
    listen(document, 'visibilitychange', () => { if (document.hidden) close(false); });
    listen(window, 'pagehide', () => close(false));
    installed = {openProfile: trigger => open('profile', trigger), openPassword: trigger => open('password', trigger), close,
      destroy() { close(false); for (const cleanup of cleanups) cleanup(); if (dialog) dialog.remove(); dialog = null; }};
    return installed;
  }
  window.btmhAccountProfile = {install};
})(window, document);

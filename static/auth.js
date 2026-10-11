(() => {
  'use strict';
  const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;
  const USER = /^[A-Za-z0-9_.-]{3,30}$/;   // older accounts made with a plain username can still log in
  const checks = {
    login(v) {
      v = v.trim();
      if (!v) return 'Enter your email.';
      if (v.length > 80) return 'That is too long. Use at most 80 characters.';
      if (v.includes('@')) return EMAIL.test(v) ? '' : 'Enter a valid email address.';
      return USER.test(v) ? '' : 'Enter a valid email address.';
    },
    email(v) {
      v = v.trim();
      if (!v) return 'Enter your email.';
      return v.length <= 80 && EMAIL.test(v) ? '' : 'Enter a valid email address.';
    },
    name(v) {
      v = v.trim().replace(/\s+/g, ' ');
      if (!v) return 'Enter your name.';
      if (v.length < 2) return 'Your name must be at least 2 characters.';
      return v.length > 50 ? 'Your name must be 50 characters or fewer.' : '';
    },
    password(v, form) {
      if (!v) return 'Enter your password.';
      if (form.dataset.mode === 'signup' && v.length < 6) return 'Password must be at least 6 characters.';
      return '';
    },
    confirm(v, form) {
      if (!v) return 'Confirm your password.';
      return v === form.elements.password.value ? '' : 'Passwords do not match.';
    },
  };

  function show(input, msg) {
    const err = document.getElementById(input.id + '-err');
    if (err) err.textContent = msg;
    if (msg) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid');
  }

  document.querySelectorAll('.auth-form').forEach((form) => {
    const fields = ['name', 'login', 'email', 'password', 'confirm'].map((n) => form.elements[n]).filter(Boolean);
    fields.forEach((input) => {
      input.addEventListener('blur', () => { if (input.value) show(input, checks[input.name](input.value, form)); });
      input.addEventListener('input', () => {
        if (input.getAttribute('aria-invalid')) show(input, checks[input.name](input.value, form));
        if (input.name === 'password' && form.elements.confirm && form.elements.confirm.value) show(form.elements.confirm, checks.confirm(form.elements.confirm.value, form));
      });
    });
    form.addEventListener('submit', (e) => {
      let first = null;
      fields.forEach((input) => {
        const msg = checks[input.name](input.value, form);
        show(input, msg);
        if (msg && !first) first = input;
      });
      const fe = document.getElementById(form.id + '-err');
      if (first) { e.preventDefault(); if (fe) fe.textContent = ''; first.focus(); }
    });
  });

  document.querySelectorAll('[data-toggle-pw]').forEach((b) => {
    b.addEventListener('click', () => {
      const input = b.parentElement.querySelector('input');
      const reveal = input.type === 'password';
      input.type = reveal ? 'text' : 'password';
      b.textContent = reveal ? 'Hide' : 'Show';
      b.setAttribute('aria-pressed', String(reveal));
      b.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
    });
  });
})();

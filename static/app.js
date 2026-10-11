(() => {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const NAMES = { amazon: 'Amazon India', flipkart: 'Flipkart' };
  const SHORT = { amazon: 'Amazon', flipkart: 'Flipkart' };
  const form = $('#f'), input = $('#q'), go = $('#go'), results = $('#results'), out = $('#out'),
    notices = $('#notices'), title = $('#results-title'), refresh = $('#refresh');
  let lastQuery = '', timer = null;
  const csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  const jsonHeaders = { 'Content-Type': 'application/json', 'X-Requested-With': 'pricewise', 'X-CSRF-Token': csrf };

  let toastTimer = null;
  function toast(text) {
    let t = document.getElementById('toast');
    if (!t) { t = h('div', { id: 'toast', class: 'toast', role: 'status', 'aria-live': 'polite' }); document.body.append(t); }
    t.textContent = text;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
  }
  const amazonId = (r) => { const m = r.amazon && /\/dp\/([A-Z0-9]{10})/.exec(r.amazon.url); return m ? m[1] : ''; };
  const flipkartId = (r) => { const m = r.flipkart && /[?&]pid=([A-Za-z0-9]+)/.exec(r.flipkart.url); return m ? m[1] : ''; };

  function h(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) if (v != null && v !== false) n.setAttribute(k, v);
    for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(kid));
    return n;
  }
  const rupee = (n) => '\u20B9' + Number(n).toLocaleString('en-IN');

  function note(heading, text, warn) {
    return h('div', { class: 'note' + (warn ? ' warn' : ''), role: warn ? 'alert' : 'status' }, h('strong', null, heading), text);
  }

  async function search(raw, fresh) {
    const q = (raw || '').trim().replace(/\s+/g, ' ');
    if (q.length < 2) { input.focus(); return; }
    lastQuery = q;
    input.value = q;
    results.hidden = false;
    refresh.hidden = true;
    notices.replaceChildren();
    title.textContent = 'Results for "' + q + '"';
    go.disabled = true;
    go.textContent = 'Searching...';
    const wait = h('p', { class: 'loading' }, 'Fetching live prices from Amazon India and Flipkart. This can take up to 30 seconds.');
    out.replaceChildren(wait, h('div', { class: 'skel' }), h('div', { class: 'skel' }));
    results.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const t0 = Date.now();
    clearInterval(timer);
    timer = setInterval(() => {
      wait.textContent = 'Fetching live prices from Amazon India and Flipkart. ' + Math.round((Date.now() - t0) / 1000) + ' seconds so far.';
    }, 1000);
    try {
      history.replaceState(null, '', '?q=' + encodeURIComponent(q));
      const r = await fetch('/api/search?q=' + encodeURIComponent(q) + (fresh ? '&fresh=1' : ''), { credentials: 'same-origin' });
      if (r.status === 401) { location.href = '/login'; return; }
      let d = null;
      try { d = await r.json(); } catch (e) { /* not JSON */ }
      if (!r.ok || !d) {
        out.replaceChildren(note('This search could not run', (d && d.error) || 'The server returned an error. Check the terminal that is running app.py.', true));
        return;
      }
      if (!fresh) saveHistory(q);
      render(d);
    } catch (e) {
      out.replaceChildren(note('Cannot reach PriceWise', 'Make sure the server is still running and your phone is on the same Wi-Fi, then search again.', true));
    } finally {
      clearInterval(timer);
      go.disabled = false;
      go.textContent = 'Search';
    }
  }

  async function saveHistory(q) {   // this user's search history (a repeated search moves to the top)
    try {
      const r = await fetch('/api/history', { method: 'POST', credentials: 'same-origin', headers: jsonHeaders, body: JSON.stringify({ q }) });
      if (!r.ok) console.warn('PriceWise: search history was not saved (HTTP ' + r.status + ')');
    } catch (e) { console.warn('PriceWise: search history was not saved', e); }
  }

  function render(d) {
    refresh.hidden = false;
    const bad = ['amazon', 'flipkart'].filter((k) => ['blocked', 'error'].includes(d.platforms[k].status));
    notices.replaceChildren(...bad.map((k) => note(NAMES[k] + ' data unavailable', d.platforms[k].message || 'The store could not be reached.', true)));
    if (!d.results.length) {
      out.replaceChildren(bad.length
        ? note('Nothing to compare yet', 'A store was unavailable, so no products could be shown. Tap "Refresh prices" to try again.', true)
        : note('No matching electronics found', 'Try the brand, model and storage together, for example "Samsung Galaxy S25 Ultra 256GB". PriceWise shows electronics only and leaves out cases and chargers unless you search for them.', false));
      return;
    }
    // Products found on both stores first, since those are the comparisons.
    const rows = d.results.slice().sort((a, b) => (b.amazon && b.flipkart ? 1 : 0) - (a.amazon && a.flipkart ? 1 : 0));
    out.replaceChildren(...rows.map(card));
    markSaved();
  }

  function ratingLine(item) {
    const bits = [];
    if (item.rating) bits.push(h('span', { class: 'star', 'aria-hidden': 'true' }, '\u2605 '), item.rating.toFixed(1) + ' out of 5');
    if (item.reviews) bits.push((item.rating ? ', ' : '') + item.reviews.toLocaleString('en-IN') + ' ratings');
    return h('p', { class: 'rate' }, bits.length ? bits : 'Rating not available');
  }

  function store(key, item, note_, best) {
    const box = h('div', { class: 'store' + (best ? ' best' : '') },
      h('div', { class: 'store-head' }, h('span', null, SHORT[key]), best ? h('span', { class: 'badge' }, 'Lower price') : null));
    if (!item) {
      box.append(h('p', { class: 'na' }, note_ === 'unavailable' ? 'Data unavailable' : 'No matching listing'),
        h('p', { class: 'na-sub' }, note_ === 'unavailable' ? 'Could not retrieve ' + NAMES[key] + ' data.' : NAMES[key] + ' has no listing for this variant.'));
      return box;
    }
    box.append(h('p', { class: 'price' }, rupee(item.price)), ratingLine(item),
      h('p', { class: 'listed', title: item.name }, item.name),
      h('a', { class: 'view', href: item.url, target: '_blank', rel: 'noopener noreferrer' }, 'View on ' + SHORT[key]));
    return box;
  }

  function diff(r) {
    let amount, text, cls = 'diff';
    if (r.cheaper === 'same') { amount = rupee(0); text = 'Same price on both stores'; }
    else if (r.cheaper) { amount = rupee(r.difference); text = NAMES[r.cheaper] + ' is cheaper'; cls += ' win'; }
    else { amount = 'Not available'; text = 'Only ' + (r.amazon ? 'Amazon' : 'Flipkart') + ' lists this variant'; }
    return h('div', { class: cls }, h('div', { class: 'row' }, h('span', null, 'Price Difference'), h('strong', null, amount)), h('small', null, text));
  }

  function heart(r) {
    const b = h('button', { class: 'heart', type: 'button', 'aria-pressed': 'false', 'aria-label': 'Add ' + r.name + ' to Wishlist',
      'data-aid': amazonId(r), 'data-fid': flipkartId(r) }, h('span', { 'aria-hidden': 'true' }, '\u2661'));
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        const resp = await fetch('/api/wishlist/toggle', { method: 'POST', credentials: 'same-origin',
          headers: jsonHeaders, body: JSON.stringify({ product: r }) });
        if (resp.status === 401) { location.href = '/login'; return; }
        const d = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(d.error || 'failed');
        setHeart(b, d.saved);
        toast(d.saved ? 'Added to Wishlist' : 'Removed from Wishlist');
      } catch (e) {
        toast(e.message && e.message !== 'failed' ? e.message : 'Could not update your Wishlist. Try again.');
      } finally { b.disabled = false; }
    });
    return b;
  }
  function setHeart(b, saved) {
    b.setAttribute('aria-pressed', String(saved));
    b.firstChild.textContent = saved ? '\u2665' : '\u2661';
    b.setAttribute('aria-label', (saved ? 'Remove from Wishlist' : 'Add to Wishlist'));
  }
  async function markSaved() {   // fill the hearts of products this user already saved
    try {
      const r = await fetch('/api/wishlist/keys', { credentials: 'same-origin' });
      if (!r.ok) return;
      const k = await r.json();
      const a = new Set(k.amazon), f = new Set(k.flipkart);
      document.querySelectorAll('.heart').forEach((b) => {
        if ((b.dataset.aid && a.has(b.dataset.aid)) || (b.dataset.fid && f.has(b.dataset.fid))) setHeart(b, true);
      });
    } catch (e) { /* hearts simply stay empty */ }
  }

  function card(r) {
    const imgs = (r.images && r.images.length) ? r.images : (r.image ? [r.image] : []);
    const media = imgs.length
      ? h('div', { class: 'media' }, h('img', { src: imgs[0], 'data-alt': JSON.stringify(imgs.slice(1)), alt: r.name, decoding: 'async', referrerpolicy: 'no-referrer' }))
      : h('div', { class: 'media none' }, 'Image not available');
    return h('article', { class: 'card' },
      media,
      h('div', { class: 'card-head' },
        h('div', { class: 'ch-text' }, h('h3', null, r.name), r.spec ? h('p', { class: 'spec' }, r.spec) : null),
        heart(r)),
      h('div', { class: 'stores' },
        store('amazon', r.amazon, r.amazon_note, r.cheaper === 'amazon'),
        store('flipkart', r.flipkart, r.flipkart_note, r.cheaper === 'flipkart')),
      diff(r));
  }

  form.addEventListener('submit', (e) => { e.preventDefault(); search(input.value, false); });
  document.querySelectorAll('[data-q]').forEach((b) => b.addEventListener('click', () => search(b.dataset.q, false)));
  refresh.addEventListener('click', () => search(lastQuery, true));
  const params = new URLSearchParams(location.search);
  const initial = params.get('q');
  if (initial) search(initial, false);
  else if (params.get('focus')) input.focus();
})();

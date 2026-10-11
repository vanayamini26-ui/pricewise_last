(() => {
  const btn = document.getElementById('menu-btn');
  const menu = document.getElementById('menu');
  if (!btn || !menu) return;
  const set = (open) => {
    menu.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', String(open));
    btn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  };
  btn.addEventListener('click', () => set(!menu.classList.contains('open')));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') set(false); });
  document.addEventListener('click', (e) => { if (!menu.contains(e.target) && !btn.contains(e.target)) set(false); });
})();

/* image-fallback: a product image that fails to load becomes a placeholder, on every page */
(() => {
  function placeholder(img) {
    const box = img.closest('.media');
    if (!box || box.classList.contains('none')) return;
    box.classList.add('none');
    box.replaceChildren(document.createTextNode('Image not available'));
  }
  function fail(img) {                       // try the other store's picture first
    let alts = [];
    try { alts = JSON.parse(img.dataset.alt || '[]'); } catch (e) { alts = []; }
    const next = alts.shift();
    img.dataset.alt = JSON.stringify(alts);
    if (next) img.src = next; else placeholder(img);
  }
  document.addEventListener('error', (e) => {
    if (e.target && e.target.tagName === 'IMG' && e.target.closest && e.target.closest('.media')) fail(e.target);
  }, true);
  const sweep = () => document.querySelectorAll('.media img').forEach((i) => { if (i.complete && i.naturalWidth === 0) fail(i); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sweep); else sweep();
  window.addEventListener('load', sweep);
})();

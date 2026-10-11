"""Flipkart search-results scraper (Playwright, no paid API).

Flipkart's CSS class names are obfuscated and change often, so this scraper does
not use them. It finds product links by their `pid=` query parameter, climbs to the
smallest container holding exactly one product, and reads the card's visible text.
"""
import re
import time
from urllib.parse import parse_qs, quote_plus, urlparse

from .common import (FetchResult, Listing, PWTimeout, dump_debug, open_page,
                     parse_count, parse_price, parse_rating)

PLATFORM = "flipkart"

_JS = r"""
() => {
  const out = []; const seen = new Set();
  const pidOf = (href) => { try { return new URL(href, location.href).searchParams.get('pid'); } catch (e) { return null; } };
  for (const a of Array.from(document.querySelectorAll('a[href*="pid="]'))) {
    const pid = pidOf(a.href);
    if (!pid || seen.has(pid)) continue;
    let card = a;
    while (card.parentElement && card.parentElement !== document.body) {
      const parent = card.parentElement;
      const hasOther = Array.from(parent.querySelectorAll('a[href*="pid="]')).some(x => pidOf(x.href) !== pid);
      if (hasOther) break;
      card = parent;
    }
    seen.add(pid);
    let title = '';
    for (const l of card.querySelectorAll('a[href*="pid="]')) {
      const t = l.getAttribute('title'); if (t) { title = t.trim(); break; }
    }
    const imgs = Array.from(card.querySelectorAll('img'));
    // Flipkart lazy-loads images (placeholder data: URLs until scrolled into view). Look at every
    // attribute that can hold the real address and prefer the largest srcset entry.
    const src = (i) => {
      const set = (i.getAttribute('srcset') || '').split(',').map(x => x.trim().split(/\s+/)[0]).filter(u => u.startsWith('http'));
      if (set.length) return set[set.length - 1];
      return [i.currentSrc, i.src, i.getAttribute('data-src'), i.getAttribute('data-lazy-src')].find(u => u && u.startsWith('http')) || '';
    };
    const img = imgs.find(i => /rukminim|flixcart/.test(src(i))) || imgs.find(i => src(i));
    if (!title && img && img.alt) title = img.alt.trim();
    out.push({ pid, href: a.href, title, image: img ? src(img) : '', text: card.innerText || '' });
  }
  return out;
}
"""

_BLOCK_MARKERS = ("are you a human", "unusual traffic", "recaptcha", "access denied")
_SKIP_LINES = re.compile(r"^(sponsored|add to compare|bestseller|assured|ad|₹.*|\d+% off|.*off$)$", re.I)


def _blocked(page) -> bool:
    try:
        text = page.inner_text("body", timeout=3000).lower()[:3000]
        return any(m in text for m in _BLOCK_MARKERS)
    except Exception:
        return False


def _clean_url(href: str) -> str:
    u = urlparse(href)
    q = parse_qs(u.query)
    keep = "&".join(f"{k}={q[k][0]}" for k in ("pid", "lid") if k in q)
    return f"https://www.flipkart.com{u.path}?{keep}"


def _parse_card(r, rank):
    lines = [l.strip() for l in (r["text"] or "").split("\n") if l.strip()]
    title = r["title"]
    if not title:
        title = next((l for l in lines if len(l) > 12 and not _SKIP_LINES.match(l)), "")
    if not title:
        return None

    # Selling price is the first rupee amount on the card (MRP / EMI come after it).
    price = None
    for l in lines:
        if re.fullmatch(r"₹\s?[\d,]+", l):
            price = parse_price(l)
            break
    if price is None:
        m = re.search(r"₹\s?[\d,]+", " ".join(lines))
        price = parse_price(m.group()) if m else None
    if price is None:
        return None

    rating = next((parse_rating(l) for l in lines if re.fullmatch(r"[1-5](?:\.\d)?", l)), None)
    reviews = None
    joined = " ".join(lines)
    m = re.search(r"([\d,]+)\s+Ratings?", joined, re.I)
    if m:
        reviews = parse_count(m.group(1))
    else:
        m = next((re.fullmatch(r"\(\s*([\d,.]+\s*[KkMm]?)\s*\)", l) for l in lines
                  if re.fullmatch(r"\(\s*[\d,.]+\s*[KkMm]?\s*\)", l)), None)
        if m:
            reviews = parse_count(m.group(1))

    return Listing(platform=PLATFORM, name=title, price=price, url=_clean_url(r["href"]),
                   image=r["image"] or None, rating=rating, reviews=reviews, rank=rank)


def search_flipkart(query: str, max_items: int = 20) -> FetchResult:
    url = f"https://www.flipkart.com/search?q={quote_plus(query)}&marketplace=FLIPKART"
    try:
        with open_page() as page:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=35000)
            if (resp and resp.status in (403, 429, 503)) or _blocked(page):
                dump_debug(page, "flipkart_blocked")
                return FetchResult(PLATFORM, "blocked", message="Flipkart blocked the request.")
            try:
                page.keyboard.press("Escape")            # dismiss login pop-up if shown
            except Exception:
                pass
            try:
                page.wait_for_selector('a[href*="pid="]', timeout=15000)
            except PWTimeout:
                dump_debug(page, "flipkart_empty")
                if _blocked(page):
                    return FetchResult(PLATFORM, "blocked", message="Flipkart blocked the request.")
                return FetchResult(PLATFORM, "no_results", message="Flipkart returned no results.")
            for _ in range(16):                           # scroll the whole page so every card loads its image
                page.mouse.wheel(0, 1300)
                page.wait_for_timeout(300)
                if page.evaluate("window.scrollY + window.innerHeight >= document.body.scrollHeight - 80"):
                    break
            page.wait_for_timeout(700)
            raw = page.evaluate(_JS)
            dump_debug(page, "flipkart_ok")
    except Exception as exc:
        return FetchResult(PLATFORM, "error", message=f"Flipkart fetch failed: {type(exc).__name__}: {exc}")

    listings = []
    for r in raw:
        item = _parse_card(r, len(listings))
        if item:
            listings.append(item)
        if len(listings) >= max_items:
            break
    if not listings:
        return FetchResult(PLATFORM, "no_results", message="Flipkart results had no priced products.")
    return FetchResult(PLATFORM, "ok", listings, fetched_at=time.time())

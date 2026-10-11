"""Amazon India search-results scraper (Playwright, no paid API)."""
import threading
import time
from urllib.parse import quote_plus

from .common import (HEADLESS, SHOW_ON_BLOCK, FetchResult, Listing, PWTimeout, dump_debug, open_page,
                     parse_count, parse_price, parse_rating)

PLATFORM = "amazon"
_LOCK = threading.Lock()          # one Amazon browser at a time (shared profile)
CAPTCHA_WAIT_SECONDS = 150

# Runs inside the page. Uses stable data-* attributes and the canonical /dp/ASIN link,
# not Amazon's generated CSS class names.
_JS = r"""
() => Array.from(document.querySelectorAll('div[data-component-type="s-search-result"][data-asin]'))
  .map(el => {
    const asin = el.getAttribute('data-asin');
    if (!asin) return null;
    // A card can hold several <h2>s (brand line + full title). Collect every candidate
    // and keep the longest, which is the full product title.
    const cands = [];
    el.querySelectorAll('h2').forEach(h => { cands.push(h.getAttribute('aria-label') || ''); cands.push(h.textContent || ''); });
    const imgEl = el.querySelector('img.s-image') || el.querySelector('img[src*="media-amazon"], img[srcset]');
    if (imgEl && imgEl.alt) cands.push(imgEl.alt);
    const title = cands
      .map(t => t.replace(/^Sponsored Ad\s*[-:\u2013]\s*/i, '').replace(/\s+/g, ' ').trim())
      .sort((a, b) => b.length - a.length)[0] || '';
    const priceEl = el.querySelector('.a-price:not(.a-text-price) .a-offscreen');
    // Prefer the largest version in srcset (sharper), then fall back to src / lazy-load attributes.
    let image = '';
    if (imgEl) {
      const set = (imgEl.getAttribute('srcset') || '').split(',').map(x => x.trim().split(/\s+/)[0]).filter(u => u.startsWith('http'));
      image = set.length ? set[set.length - 1]
        : [imgEl.currentSrc, imgEl.src, imgEl.getAttribute('data-src')].find(u => u && u.startsWith('http')) || '';
    }
    const ratingEl = el.querySelector('[aria-label*="out of 5 stars"], .a-icon-alt');
    let ratingText = '';
    if (ratingEl) ratingText = ratingEl.getAttribute('aria-label') || ratingEl.textContent || '';
    let reviewsText = '';
    const rA = el.querySelector('a[aria-label*=" ratings"], span[aria-label*=" ratings"]');
    if (rA) reviewsText = rA.getAttribute('aria-label') || '';
    else { const u = el.querySelector('span.s-underline-text'); if (u) reviewsText = u.textContent || ''; }
    return { asin, title, price: priceEl ? priceEl.textContent : '',
             image, ratingText, reviewsText };
  }).filter(Boolean)
"""

_BLOCK_MARKERS = (
    "enter the characters you see below",
    "type the characters you see in this image",
    "automated access",
    "not a robot",
)


def _blocked(page) -> bool:
    try:
        title = (page.title() or "").lower()
        if "robot check" in title or "captcha" in title:
            return True
        if page.query_selector('form[action*="validateCaptcha"]'):
            return True
        text = page.inner_text("body", timeout=3000).lower()[:3000]
        return any(m in text for m in _BLOCK_MARKERS)
    except Exception:
        return False


def search_amazon(query: str, max_items: int = 20) -> FetchResult:
    with _LOCK:
        result = _search(query, max_items, HEADLESS)
        if result.status == "blocked" and HEADLESS and SHOW_ON_BLOCK:
            # The hidden browser got a CAPTCHA. Open a visible window just this once so it can be solved
            # (the solved state is remembered in profiles/), then everything is hidden again.
            result = _search(query, max_items, False)
        return result


def _search(query: str, max_items: int, headless: bool = True) -> FetchResult:
    url = "https://www.amazon.in/s?k=" + quote_plus(query)
    blocked_msg = ("Amazon showed a bot check (CAPTCHA) that was not solved. Search again and solve it "
                   "in the window that opens.")
    try:
        with open_page(profile="amazon", headless=headless) as page:
            page.goto("https://www.amazon.in/", wait_until="domcontentloaded", timeout=35000)
            page.wait_for_timeout(1200)
            resp = page.goto(url, wait_until="domcontentloaded", timeout=35000)
            blocked = (resp and resp.status in (403, 429, 503)) or _blocked(page)
            if blocked and not headless:
                print("\n*** Amazon is asking for a CAPTCHA. Solve it in the browser window; "
                      f"waiting up to {CAPTCHA_WAIT_SECONDS}s ***")
                waited = 0
                while waited < CAPTCHA_WAIT_SECONDS and _blocked(page):
                    page.wait_for_timeout(2000)
                    waited += 2
                blocked = _blocked(page)
                if not blocked:
                    page.goto(url, wait_until="domcontentloaded", timeout=35000)
                    blocked = _blocked(page)
            if blocked:
                dump_debug(page, "amazon_blocked")
                return FetchResult(PLATFORM, "blocked", message=blocked_msg)
            try:
                page.wait_for_selector('div[data-component-type="s-search-result"]', timeout=12000)
            except PWTimeout:
                dump_debug(page, "amazon_empty")
                if _blocked(page):
                    return FetchResult(PLATFORM, "blocked", message=blocked_msg)
                return FetchResult(PLATFORM, "no_results", message="Amazon returned no results.")
            raw = page.evaluate(_JS)
            dump_debug(page, "amazon_ok")
    except Exception as exc:  # network error, timeout, browser missing...
        return FetchResult(PLATFORM, "error", message=f"Amazon fetch failed: {type(exc).__name__}: {exc}")

    listings = []
    for r in raw:
        price = parse_price(r["price"])
        if not r["title"] or price is None:     # skip unavailable / no-price cards, never guess
            continue
        listings.append(Listing(
            platform=PLATFORM, name=r["title"], price=price,
            url=f"https://www.amazon.in/dp/{r['asin']}",
            image=r["image"] or None,
            rating=parse_rating(r["ratingText"]),
            reviews=parse_count(r["reviewsText"]),
            rank=len(listings),
        ))
        if len(listings) >= max_items:
            break
    if not listings:
        return FetchResult(PLATFORM, "no_results", message="Amazon results had no priced products.")
    return FetchResult(PLATFORM, "ok", listings, fetched_at=time.time())

"""Shared data classes, parsing helpers and the Playwright browser launcher."""
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


try:
    from playwright.sync_api import TimeoutError as PWTimeout
except ImportError:  # lets the pure-Python parts be imported/tested without Playwright
    class PWTimeout(Exception):
        pass

# Browsers run HIDDEN by default. PRICEWISE_HEADLESS=0 makes every window visible.
HEADLESS = os.getenv("PRICEWISE_HEADLESS", "1") != "0"
# If Amazon shows a CAPTCHA to the hidden browser, open ONE visible window so it can be solved,
# then go back to hidden. Set PRICEWISE_SHOW_ON_BLOCK=0 to never show a window.
SHOW_ON_BLOCK = os.getenv("PRICEWISE_SHOW_ON_BLOCK", "1") != "0"
DEBUG = os.getenv("PRICEWISE_DEBUG", "0") == "1"
DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class Listing:
    platform: str
    name: str
    price: int
    url: str
    image: Optional[str] = None
    rating: Optional[float] = None
    reviews: Optional[int] = None
    rank: int = 0


@dataclass
class FetchResult:
    platform: str
    status: str                      # ok | no_results | blocked | error
    listings: List[Listing] = field(default_factory=list)
    message: str = ""
    fetched_at: float = field(default_factory=time.time)


def parse_price(text: str) -> Optional[int]:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    if not m:
        return None
    value = int(round(float(m.group().replace(",", ""))))
    return value if value > 0 else None


def parse_count(text: str) -> Optional[int]:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM]?)", text or "")
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    n *= {"k": 1_000, "m": 1_000_000}.get(m.group(2).lower(), 1)
    return int(n)


def parse_rating(text: str) -> Optional[float]:
    m = re.search(r"\b([0-5](?:\.\d)?)\b", text or "")
    if not m:
        return None
    v = float(m.group(1))
    return v if 0 < v <= 5 else None


PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"


def _launch(p, headless, args, profile_path, opts):
    """Start Chromium. Hidden mode uses Chromium's 'new headless' (the same engine as a normal
    window, so shops detect it far less often); older Playwright versions fall back to the default."""
    kinds = [{"channel": "chromium"}, {}] if headless else [{}]
    last = None
    for extra in kinds:
        try:
            if profile_path:
                return None, p.chromium.launch_persistent_context(str(profile_path), headless=headless, args=args, **opts, **extra)
            browser = p.chromium.launch(headless=headless, args=args, **extra)
            return browser, browser.new_context(**opts)
        except Exception as exc:       # e.g. 'channel' not supported by this Playwright version
            last = exc
    raise last


@contextmanager
def open_page(profile=None, headless=None):
    """Yield a Playwright page that looks like a normal Indian desktop browser.

    headless=None uses the PRICEWISE_HEADLESS setting. With `profile`, cookies/storage persist
    between searches in profiles/<profile>/.
    """
    from playwright.sync_api import sync_playwright
    headless = HEADLESS if headless is None else headless
    opts = dict(
        user_agent=USER_AGENT,
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        viewport={"width": 1366, "height": 900},
        extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
    )
    args = ["--disable-blink-features=AutomationControlled"]
    with sync_playwright() as p:
        path = None
        if profile:
            path = PROFILE_DIR / profile
            path.mkdir(parents=True, exist_ok=True)
        browser, ctx = _launch(p, headless, args, path, opts)
        ctx.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        ctx.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in ("font", "media")
            else route.continue_(),
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            yield page
        finally:
            ctx.close()
            if browser:
                browser.close()


def dump_debug(page, name: str) -> None:
    """With PRICEWISE_DEBUG=1, save a screenshot + HTML so selectors can be fixed."""
    if not DEBUG:
        return
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"))
        (DEBUG_DIR / f"{name}.html").write_text(page.content(), encoding="utf-8")
    except Exception:
        pass

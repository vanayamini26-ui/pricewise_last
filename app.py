"""PriceWise: Amazon India vs Flipkart price comparison for electronics.

Run:  python app.py      (laptop only:  http://127.0.0.1:5000)
Phone demo:  set PRICEWISE_HOST=0.0.0.0 first, then open http://<laptop-ip>:5000 on the phone.
"""
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from comparison import build_comparison
from matching import (_head, is_accessory, is_electronic, is_relevant, parse_title,
                      query_is_allowed)
from scrapers.amazon import search_amazon
from scrapers.flipkart import search_flipkart

BASE = Path(__file__).resolve().parent
DB_PATH = os.getenv("PRICEWISE_DB", str(BASE / "pricewise.db"))


def _secret_key() -> str:
    env = os.getenv("PRICEWISE_SECRET")
    if env:
        return env
    f = BASE / ".secret_key"
    if f.exists():
        return f.read_text().strip()
    key = secrets.token_hex(32)
    f.write_text(key)
    return key


app = Flask(__name__)
app.config.update(
    SECRET_KEY=_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SEND_FILE_MAX_AGE_DEFAULT=0,          # browsers must re-check static files after an update
)


def asset(filename: str) -> str:
    """URL of a static file with its modified-time as a version, so a phone/browser can never
    keep running an old app.js or style.css after the files were replaced."""
    try:
        version = int((BASE / "static" / filename).stat().st_mtime)
    except OSError:
        version = 0
    return url_for("static", filename=filename, v=version)


app.jinja_env.globals["asset"] = asset

# ------------------------------------------------------------------ users
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            login TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at REAL NOT NULL)""")
        if "name" not in [r["name"] for r in con.execute("PRAGMA table_info(users)")]:
            con.execute("ALTER TABLE users ADD COLUMN name TEXT")
        con.execute("""CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_login TEXT NOT NULL,
            amazon_id TEXT,
            flipkart_id TEXT,
            data TEXT NOT NULL,
            created_at REAL NOT NULL)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_user ON wishlist (user_login)")
        con.execute("""CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_login TEXT NOT NULL,
            term TEXT NOT NULL,
            term_key TEXT NOT NULL,
            searched_at REAL NOT NULL,
            UNIQUE (user_login, term_key))""")
        con.commit()
    finally:
        con.close()


def get_user(login):
    con = db()
    try:
        return con.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
    finally:
        con.close()


def create_user(login, password, name=None):
    con = db()
    try:
        con.execute("INSERT INTO users (login, password_hash, created_at, name) VALUES (?, ?, ?, ?)",
                    (login, generate_password_hash(password), time.time(), name))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        con.close()


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")


def validate_login_id(value: str) -> str:
    """Log in with an email. (Accounts made earlier with a plain username can still log in.)"""
    v = value.strip()
    if not v:
        return "Enter your email."
    if len(v) > 80:
        return "That is too long. Use at most 80 characters."
    if "@" in v:
        return "" if EMAIL_RE.match(v) else "Enter a valid email address."
    return "" if USER_RE.match(v) else "Enter a valid email address."


def validate_email(value: str) -> str:
    v = value.strip()
    if not v:
        return "Enter your email."
    if len(v) > 80 or not EMAIL_RE.match(v):
        return "Enter a valid email address."
    return ""


def validate_name(value: str) -> str:
    v = " ".join(value.split())
    if not v:
        return "Enter your name."
    if len(v) < 2:
        return "Your name must be at least 2 characters."
    if len(v) > 50:
        return "Your name must be 50 characters or fewer."
    return ""


def validate_password(pw: str, signup: bool) -> str:
    if not pw:
        return "Enter your password."
    if signup and len(pw) < 6:
        return "Password must be at least 6 characters."
    if len(pw) > 128:
        return "Password is too long (128 characters at most)."
    return ""


# Slow down repeated wrong passwords: 5 failures per 10 minutes per (address, account).
_fails, _fails_lock = {}, threading.Lock()
MAX_FAILS, FAIL_WINDOW = 5, 600


def _fail_key(login):
    return (request.remote_addr, login)


def throttled(login) -> bool:
    now = time.time()
    with _fails_lock:
        recent = [t for t in _fails.get(_fail_key(login), []) if now - t < FAIL_WINDOW]
        _fails[_fail_key(login)] = recent
        return len(recent) >= MAX_FAILS


def record_fail(login):
    with _fails_lock:
        _fails.setdefault(_fail_key(login), []).append(time.time())


def csrf_token() -> str:
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def check_csrf():
    sent = request.form.get("_csrf", "")
    if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
        abort(400, "Your session expired. Reload the page and try again.")


def login_required(view):
    @wraps(view)
    def wrapper(*a, **kw):
        if "user" not in session:
            if request.path.startswith("/api/"):
                return jsonify(error="Please log in again.", login_required=True), 401
            return redirect(url_for("login"))
        return view(*a, **kw)
    return wrapper


def start_session(login, name=None):
    session.clear()
    session["user"] = login
    session["name"] = (name or "").strip() or display_name(login)
    session["_csrf"] = secrets.token_hex(16)
    session.permanent = True


def display_name(login):
    return login.split("@")[0]


@app.after_request
def add_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store"     # back button must not show pages after logout
    return resp


def auth_page(errors=None, login="", status=200, notice=None):
    return render_template("login.html", errors=errors or {}, login=login, notice=notice), status


def signup_page(errors=None, values=None, status=200):
    return render_template("signup.html", errors=errors or {}, values=values or {}), status


@app.get("/login")
def login():
    if "user" in session:
        return redirect(url_for("home"))
    notice, prefill = session.pop("notice", None), session.pop("prefill", "")
    return auth_page(login=prefill, notice=notice)


@app.post("/login")
def login_post():
    check_csrf()
    ident = request.form.get("login", "").strip().lower()
    pw = request.form.get("password", "")
    errors = {}
    if (e := validate_login_id(ident)):
        errors["login"] = e
    if (e := validate_password(pw, signup=False)):
        errors["password"] = e
    if errors:
        return auth_page(errors, ident, 400)
    if throttled(ident):
        return auth_page({"form": "Too many failed attempts. Wait a few minutes and try again."}, ident, 429)
    user = get_user(ident)
    if user and check_password_hash(user["password_hash"], pw):
        start_session(ident, user["name"])
        return redirect(url_for("home"))
    record_fail(ident)
    return auth_page({"form": "Incorrect email or password."}, ident, 401)


@app.get("/signup")
def signup():
    if "user" in session:
        return redirect(url_for("home"))
    return signup_page()


@app.post("/signup")
def signup_post():
    check_csrf()
    name = " ".join(request.form.get("name", "").split())
    email = request.form.get("email", "").strip().lower()
    pw = request.form.get("password", "")
    confirm = request.form.get("confirm", "")
    errors = {}
    if (e := validate_name(name)):
        errors["name"] = e
    if (e := validate_email(email)):
        errors["email"] = e
    if (e := validate_password(pw, signup=True)):
        errors["password"] = e
    elif pw != confirm:
        errors["confirm"] = "Passwords do not match."
    values = {"name": name, "email": email}
    if errors:
        return signup_page(errors, values, 400)
    if not create_user(email, pw, name):
        return signup_page({"email": "An account with this email already exists."}, values, 409)
    # Account created: send the user to the login page (they log in with the email and password).
    session.clear()
    session["notice"] = "Account created successfully. Please log in with your email and password."
    session["prefill"] = email
    return redirect(url_for("login"))


@app.post("/logout")
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------ pages
@app.get("/")
def home():
    if "user" not in session:
        return render_template("welcome.html")           # the starting page with "Get Started"
    return render_template("home.html", name=session.get("name") or display_name(session["user"]),
                           active="search" if request.args.get("focus") else "home")


@app.get("/about")
@login_required
def about():
    return render_template("about.html", name=session.get("name") or display_name(session["user"]), active="about")


# ------------------------------------------------------------------ search API
CACHE_TTL = int(os.getenv("PRICEWISE_CACHE_TTL", "120"))   # seconds; 0 disables caching
_cache, _cache_lock = {}, threading.Lock()
_slots = threading.Semaphore(2)


def fetch_live(query: str, fresh: bool):
    key = " ".join(query.lower().split())
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
    if hit and not fresh and CACHE_TTL and now - hit[0] < CACHE_TTL:
        return hit[1]
    with _slots, ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(search_amazon, query)
        ff = pool.submit(search_flipkart, query)
        data = {"amazon": fa.result(), "flipkart": ff.result()}
    if CACHE_TTL and all(r.status in ("ok", "no_results") for r in data.values()):
        with _cache_lock:
            _cache[key] = (now, data)       # failures are never cached
    return data


@app.get("/api/search")
@login_required
def search():
    q = " ".join(request.args.get("q", "").split())
    if len(q) < 2 or len(q) > 100:
        return jsonify(error="Enter a product name between 2 and 100 characters."), 400
    if not query_is_allowed(q):
        return jsonify(error="PriceWise compares electronic products only "
                             "(phones, laptops, headphones, TVs and similar)."), 400
    data = fetch_live(q, fresh=request.args.get("fresh") == "1")
    payload = build_comparison(q, data)
    payload["server_time"] = time.time()
    return jsonify(payload)


@app.get("/api/debug")
@login_required
def debug():
    """Every listing each site returned and why it was kept or rejected."""
    q = " ".join(request.args.get("q", "").split())
    if len(q) < 2:
        return jsonify(error="Add ?q=your+search to the URL."), 400
    data = fetch_live(q, fresh=False)
    qspec = parse_title(q)
    out = {"query": q, "query_parsed": repr(qspec), "platforms": {}}
    for name, fr in data.items():
        rows = []
        for it in fr.listings:
            spec = parse_title(it.name)
            el, ac, rel = is_electronic(it.name), is_accessory(it.name, q), is_relevant(qspec, spec)
            rows.append({"title": it.name, "price": it.price, "kept": el and not ac and rel,
                         "is_electronic": el, "is_accessory": ac, "is_relevant": rel, "parsed": repr(spec)})
        out["platforms"][name] = {"status": fr.status, "message": fr.message, "listings": rows}
    return app.response_class(json.dumps(out, indent=2, ensure_ascii=False), mimetype="application/json")


# ------------------------------------------------------------------ wishlist + search history
MAX_WISHLIST = 100
MAX_HISTORY = 30
_ALLOWED_URL = {"amazon": "https://www.amazon.in/", "flipkart": "https://www.flipkart.com/"}


def format_inr(n) -> str:
    s = str(int(n))
    head, tail = s[:-3], s[-3:]
    if head:
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head) + ","
    return "\u20b9" + head + tail


app.jinja_env.filters["inr"] = format_inr


def listing_id(store, listing):
    """Amazon ASIN or Flipkart pid taken from the listing's own product link."""
    if not listing:
        return None
    url = listing.get("url", "")
    if store == "amazon":
        m = re.search(r"/dp/([A-Z0-9]{10})", url)
        return m.group(1) if m else None
    pid = parse_qs(urlparse(url).query).get("pid", [""])[0]
    return pid if re.fullmatch(r"[A-Za-z0-9]{6,40}", pid) else None


def _clean_listing(store, raw):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("bad listing")
    price, url = raw.get("price"), raw.get("url")
    if isinstance(price, bool) or not isinstance(price, int) or not 0 < price < 100_000_000:
        raise ValueError("bad price")
    if not isinstance(url, str) or not url.startswith(_ALLOWED_URL[store]) or len(url) > 600:
        raise ValueError("bad link")
    rating, reviews = raw.get("rating"), raw.get("reviews")
    return {
        "price": price, "url": url, "name": str(raw.get("name") or "")[:300],
        "rating": float(rating) if isinstance(rating, (int, float)) and 0 < rating <= 5 else None,
        "reviews": int(reviews) if isinstance(reviews, int) and reviews >= 0 else None,
    }


def clean_product(p):
    """Validate a product row sent by the browser; returns a safe snapshot or None."""
    try:
        if not isinstance(p, dict):
            return None
        name = str(p.get("name") or "").strip()[:300]
        amazon = _clean_listing("amazon", p.get("amazon"))
        flipkart = _clean_listing("flipkart", p.get("flipkart"))
        if not name or not (amazon or flipkart):
            return None
        candidates = [p.get("image")] + (p.get("images") if isinstance(p.get("images"), list) else [])
        images = []
        for u in candidates:
            if isinstance(u, str) and u.startswith("https://") and len(u) < 600 and u not in images:
                images.append(u)
        images = images[:3]
        image = images[0] if images else None
        diff = cheaper = None
        if amazon and flipkart:
            diff = abs(amazon["price"] - flipkart["price"])
            cheaper = "same" if diff == 0 else ("amazon" if amazon["price"] < flipkart["price"] else "flipkart")
        return {"name": name, "spec": (str(p.get("spec"))[:60] if p.get("spec") else None), "image": image, "images": images,
                "amazon": amazon, "flipkart": flipkart, "difference": diff, "cheaper": cheaper}
    except ValueError:
        return None


def csrf_header_ok() -> bool:
    sent = request.headers.get("X-CSRF-Token", "")
    return bool(sent) and secrets.compare_digest(sent, session.get("_csrf", ""))


def api_request_ok() -> bool:
    """JSON calls from our own pages. A custom header plus a JSON body cannot be sent by another
    website (the browser would need CORS permission, which this app never grants); the page token
    is also accepted."""
    if request.is_json and request.headers.get("X-Requested-With") == "pricewise":
        return True
    return csrf_header_ok()


@app.post("/api/wishlist/toggle")
@login_required
def wishlist_toggle():
    """Add the product to the user's wishlist, or remove it if it is already there."""
    if not api_request_ok():
        return jsonify(error="Your session expired. Reload the page and try again."), 400
    snap = clean_product((request.get_json(silent=True) or {}).get("product"))
    if not snap:
        return jsonify(error="That product could not be saved."), 400
    a_id, f_id = listing_id("amazon", snap["amazon"]), listing_id("flipkart", snap["flipkart"])
    user = session["user"]
    con = db()
    try:
        found = con.execute(
            "SELECT id FROM wishlist WHERE user_login = ? AND ((amazon_id IS NOT NULL AND amazon_id = ?) "
            "OR (flipkart_id IS NOT NULL AND flipkart_id = ?))", (user, a_id, f_id)).fetchall()
        if found:
            con.executemany("DELETE FROM wishlist WHERE id = ? AND user_login = ?", [(r["id"], user) for r in found])
            con.commit()
            return jsonify(saved=False)
        count = con.execute("SELECT COUNT(*) FROM wishlist WHERE user_login = ?", (user,)).fetchone()[0]
        if count >= MAX_WISHLIST:
            return jsonify(error="Your Wishlist is full (%d items). Remove something first." % MAX_WISHLIST), 400
        con.execute("INSERT INTO wishlist (user_login, amazon_id, flipkart_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user, a_id, f_id, json.dumps(snap), time.time()))
        con.commit()
        return jsonify(saved=True)
    finally:
        con.close()


@app.get("/api/wishlist/keys")
@login_required
def wishlist_keys():
    """Ids of the current user's saved listings, so result cards can show filled hearts."""
    con = db()
    try:
        rows = con.execute("SELECT amazon_id, flipkart_id FROM wishlist WHERE user_login = ?", (session["user"],)).fetchall()
    finally:
        con.close()
    return jsonify(amazon=[r["amazon_id"] for r in rows if r["amazon_id"]],
                   flipkart=[r["flipkart_id"] for r in rows if r["flipkart_id"]])


@app.get("/wishlist")
@login_required
def wishlist_page():
    con = db()
    try:
        rows = con.execute("SELECT * FROM wishlist WHERE user_login = ? ORDER BY created_at DESC", (session["user"],)).fetchall()
    finally:
        con.close()
    items = []
    for r in rows:
        d = json.loads(r["data"])
        a, f = d.get("amazon"), d.get("flipkart")
        prices = {k: v["price"] for k, v in (("Amazon", a), ("Flipkart", f)) if v}
        low = min(prices.values())
        winners = [k for k, v in prices.items() if v == low]
        d["images"] = d.get("images") or ([d["image"]] if d.get("image") else [])     # older saved items
        d.update(id=r["id"], best_price=low,
                 best_store=" and ".join(winners) if len(prices) > 1 else winners[0] + " only",
                 saved_on=time.strftime("%d %b %Y", time.localtime(r["created_at"])),
                 search_q=_head(d["name"]).strip()[:80])
        items.append(d)
    return render_template("wishlist.html", items=items, active="wishlist")


@app.post("/wishlist/remove")
@login_required
def wishlist_remove():
    check_csrf()
    try:
        item_id = int(request.form.get("id", ""))
    except ValueError:
        abort(400)
    con = db()
    try:
        con.execute("DELETE FROM wishlist WHERE id = ? AND user_login = ?", (item_id, session["user"]))
        con.commit()
    finally:
        con.close()
    return redirect(url_for("wishlist_page"))


@app.post("/api/history")
@login_required
def history_add():
    """Remember a search for the logged-in user (a repeated term moves to the top)."""
    if not api_request_ok():
        return jsonify(error="Your session expired."), 400
    q = " ".join(str((request.get_json(silent=True) or {}).get("q", "")).split())
    if not 2 <= len(q) <= 100 or not query_is_allowed(q):
        return jsonify(saved=False)
    user, key = session["user"], q.lower()
    con = db()
    try:
        con.execute(
            "INSERT INTO search_history (user_login, term, term_key, searched_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (user_login, term_key) DO UPDATE SET term = excluded.term, searched_at = excluded.searched_at",
            (user, q, key, time.time()))
        con.execute(
            "DELETE FROM search_history WHERE user_login = ? AND id NOT IN "
            "(SELECT id FROM search_history WHERE user_login = ? ORDER BY searched_at DESC LIMIT ?)",
            (user, user, MAX_HISTORY))
        con.commit()
    finally:
        con.close()
    return jsonify(saved=True)


@app.get("/history")
@login_required
def history_page():
    con = db()
    try:
        rows = con.execute("SELECT term FROM search_history WHERE user_login = ? ORDER BY searched_at DESC", (session["user"],)).fetchall()
    finally:
        con.close()
    return render_template("history.html", terms=[r["term"] for r in rows], active="history")


@app.post("/history/clear")
@login_required
def history_clear():
    check_csrf()
    con = db()
    try:
        con.execute("DELETE FROM search_history WHERE user_login = ?", (session["user"],))
        con.commit()
    finally:
        con.close()
    return redirect(url_for("history_page"))



REQUIRED_FILES = [
    "templates/base.html", "templates/login.html", "templates/home.html", "templates/about.html",
    "templates/wishlist.html", "templates/history.html", "templates/logo.html",
    "static/style.css", "static/app.js", "static/auth.js", "static/site.js",
]


def check_install() -> None:
    """Stop with a clear message if the project folder is incomplete or only partly updated."""
    missing = [p for p in REQUIRED_FILES if not (BASE / p).exists()]
    if missing:
        print("\nPriceWise cannot start: these files are missing from the project folder:")
        for p in missing:
            print("   -", p)
        print("Copy the whole latest project folder over this one, then run python app.py again.\n")
        sys.exit(1)
    expect = {
        "templates/base.html": "tabbar", "static/app.js": "/api/wishlist/toggle",
        "static/style.css": ".tabbar", "static/site.js": "image-fallback",
    }
    old = [p for p, marker in expect.items() if marker not in (BASE / p).read_text(encoding="utf-8", errors="ignore")]
    if old:
        print("\nWARNING: these files look like an OLDER version and the Wishlist/History/image fixes may not show:")
        for p in old:
            print("   -", p)
        print("Copy the latest project files over them and restart.\n")


init_db()

if __name__ == "__main__":
    check_install()
    host = os.getenv("PRICEWISE_HOST", "127.0.0.1")
    app.run(host=host, port=int(os.getenv("PRICEWISE_PORT", "5000")), debug=False, threaded=True)

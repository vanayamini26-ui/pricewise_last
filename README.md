# PriceWise: Amazon India vs Flipkart price comparison for electronics

Flow: **Starting page (Get Started), Create account (name, email, password, confirm), Log in with email, Home (title, search bar, menu with Wishlist and History), compare Amazon and Flipkart prices, open the product page.**
Prices are read live at search time (Playwright, no paid API, no stored prices).

## Setup (Python 3.9+)

    python -m venv venv
    venv\Scripts\activate            (Linux/macOS: source venv/bin/activate)
    pip install -r requirements.txt
    playwright install chromium

## Run on the laptop

    python app.py
    open http://127.0.0.1:5000

First visit: tap **Get Started**, create an account (name, email, password, confirm password). You are sent to the login page; log in with that email and password.

## Demo on a phone (same Wi-Fi as the laptop)

PowerShell:

    $env:PRICEWISE_HOST="0.0.0.0"    # let other devices on the Wi-Fi connect
    python app.py

1. Find the laptop's IP: run `ipconfig`, look for "IPv4 Address" (for example 192.168.1.7).
2. If Windows asks about the firewall, allow access on **Private networks**.
3. On the phone (same Wi-Fi), open `http://192.168.1.7:5000` (use your own IP).
4. The Chromium windows that pop up during a search appear on the laptop. Leave them alone.

If a phone hotspot is the only network, turn it on, connect the laptop to it, and use the laptop's IP on that hotspot.

## If a store shows "Data unavailable"

Amazon and Flipkart block automated visitors at times. The browsers run hidden. If Amazon shows a CAPTCHA, one
visible window opens automatically so you can solve it once; the solved state is kept in `profiles/` and the next
searches are hidden again. Solve it before the demo. `PRICEWISE_HEADLESS=0` makes every window visible instead. With
`PRICEWISE_DEBUG=1`, screenshots and HTML of failed pages are saved to `debug/`.
Nothing is ever filled in with old or made-up prices.

## Pages

- `/` starting page for visitors (PriceWise + Get Started), and the home screen after login
- `/signup` create account (name, email, password, confirm password)
- `/login` log in with email and password (validation on the page and on the server)
- `/` search and results (one card per product: image, Amazon price and link, Flipkart price and link, price difference)
- `/about` short explanation
- `/wishlist` the user's saved products (tap the heart on any result to save or remove)
- `/history` the user's recent searches (tap one to search again, "Clear History" removes them)
- Logout is in the menu

## Structure

    app.py            Flask app: login, sessions, pages, /api/search
    comparison.py     filter, pair and price difference
    matching.py       electronics filter, accessory filter, same-variant matching
    scrapers/         amazon.py, flipkart.py, common.py (Playwright)
    templates/        base, login, home, about
    static/           style.css, app.js (search), auth.js (login), site.js (menu)

Wishlist and history belong to the account's email address and are stored per user in `pricewise.db` (tables `wishlist`, `search_history`) and survive logout/login.
A wishlist item keeps the prices from the day it was saved and says so; "Check current prices" runs the normal live search.

Security: passwords are hashed (never stored in plain text), forms carry a CSRF token, repeated wrong
passwords are throttled (5 per 10 minutes), pages are not cached after logout. Accounts live in `pricewise.db`.

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `PRICEWISE_HEADLESS` | `1` | hidden browsers; `0` shows every window |
| `PRICEWISE_SHOW_ON_BLOCK` | `1` | open one visible window only when Amazon shows a CAPTCHA; `0` = never |
| `PRICEWISE_HOST` | `127.0.0.1` | `0.0.0.0` lets a phone connect |
| `PRICEWISE_PORT` | `5000` | server port |
| `PRICEWISE_CACHE_TTL` | `120` | seconds a repeat search is reused; `0` = always live |
| `PRICEWISE_DEBUG` | `0` | save screenshots/HTML of failed pages |

## Tests (no internet needed)

    python -m unittest discover -s tests -v

## Limitations (mention in the report)

- Scraping depends on the shops' page structure and anti-bot systems; selectors may need updating.
- The shops' terms restrict automated access; use for low-volume academic demonstration only.
- Prices are listed prices, not including coupons or bank offers. Matching is title-based and heuristic.

## Troubleshooting: Wishlist / History / images look old

`python app.py` checks the project folder when it starts. It stops and lists any missing file, and warns when a
file looks like an older version. CSS and JavaScript are loaded with a version number, so a phone or browser always
gets the newest files after you copy an update over the old folder (no manual cache clearing needed).

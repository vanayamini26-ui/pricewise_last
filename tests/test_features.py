"""Wishlist and search-history tests (real database, per-user isolation, validation)."""
import os
import re
import sys
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["PRICEWISE_DB"] = os.path.join(_tmp, "feat.db")
os.environ["PRICEWISE_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as pw  # noqa: E402

AMAZON = {"price": 45999, "url": "https://www.amazon.in/dp/B0ABCDEFGH", "name": "Demo Phone", "rating": 4.3, "reviews": 120}
FLIP = {"price": 43999, "url": "https://www.flipkart.com/demo/p/itm123?pid=MOBABC123456&lid=LSTx", "name": "Demo Phone F", "rating": None, "reviews": None}
ROW = {"name": "Demo Phone X 5G", "spec": "8 GB RAM + 256 GB", "image": "https://img.example/x.jpg", "amazon": AMAZON, "flipkart": FLIP}


def login(client, name):
    """Sign up with an email, then log in with it (the real flow); returns the page API token."""
    email = name + "@example.com"
    tok = re.search(r'name="_csrf" value="([^"]+)"', client.get("/signup").get_data(as_text=True)).group(1)
    client.post("/signup", data={"_csrf": tok, "name": name.title(), "email": email, "password": "secret12", "confirm": "secret12"})
    tok = re.search(r'name="_csrf" value="([^"]+)"', client.get("/login").get_data(as_text=True)).group(1)
    client.post("/login", data={"_csrf": tok, "login": email, "password": "secret12"})
    page = client.get("/").get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)


class T(unittest.TestCase):
    def new_user(self, name):
        c = pw.app.test_client()
        return c, login(c, name)

    def toggle(self, c, tok, row=ROW):
        return c.post("/api/wishlist/toggle", json={"product": row}, headers={"X-CSRF-Token": tok})

    def test_wishlist_add_remove_and_persistence(self):
        c, tok = self.new_user("wl_user1")
        self.assertIn("Your Wishlist is empty", c.get("/wishlist").get_data(as_text=True))
        self.assertTrue(self.toggle(c, tok).get_json()["saved"])
        page = c.get("/wishlist").get_data(as_text=True)
        for needle in ("Demo Phone X 5G", "\u20b945,999", "\u20b943,999", "Best price", "https://www.amazon.in/dp/B0ABCDEFGH", "Saved on"):
            self.assertIn(needle, page)
        self.assertEqual(c.get("/api/wishlist/keys").get_json(), {"amazon": ["B0ABCDEFGH"], "flipkart": ["MOBABC123456"]})
        # survives logging out and in again
        c.post("/logout", data={"_csrf": re.search(r'name="_csrf" value="([^"]+)"', page).group(1)})
        c2 = pw.app.test_client()
        tok2 = re.search(r'name="_csrf" value="([^"]+)"', c2.get("/login").get_data(as_text=True)).group(1)
        c2.post("/login", data={"_csrf": tok2, "login": "wl_user1@example.com", "password": "secret12"})
        self.assertIn("Demo Phone X 5G", c2.get("/wishlist").get_data(as_text=True))
        # toggle again removes it
        tok3 = re.search(r'name="csrf-token" content="([^"]+)"', c2.get("/").get_data(as_text=True)).group(1)
        self.assertFalse(self.toggle(c2, tok3).get_json()["saved"])
        self.assertIn("Your Wishlist is empty", c2.get("/wishlist").get_data(as_text=True))

    def test_same_product_found_by_either_store_id(self):
        c, tok = self.new_user("wl_user2")
        self.toggle(c, tok)
        only_flip = dict(ROW, amazon=None)       # same product, later listed by Flipkart only
        self.assertFalse(self.toggle(c, tok, only_flip).get_json()["saved"])   # toggles it off
        self.assertEqual(c.get("/api/wishlist/keys").get_json()["amazon"], [])

    def test_wishlist_is_per_user(self):
        a, ta = self.new_user("owner_a")
        b, tb = self.new_user("owner_b")
        self.toggle(a, ta)
        self.assertIn("Demo Phone X 5G", a.get("/wishlist").get_data(as_text=True))
        self.assertIn("Your Wishlist is empty", b.get("/wishlist").get_data(as_text=True))
        self.assertEqual(b.get("/api/wishlist/keys").get_json(), {"amazon": [], "flipkart": []})
        # b cannot delete a's item by id
        item_id = re.search(r'name="id" value="(\d+)"', a.get("/wishlist").get_data(as_text=True)).group(1)
        tokb = re.search(r'name="_csrf" value="([^"]+)"', b.get("/wishlist").get_data(as_text=True)).group(1)
        b.post("/wishlist/remove", data={"_csrf": tokb, "id": item_id})
        self.assertIn("Demo Phone X 5G", a.get("/wishlist").get_data(as_text=True))
        # a can remove with the page button
        toka = re.search(r'name="_csrf" value="([^"]+)"', a.get("/wishlist").get_data(as_text=True)).group(1)
        a.post("/wishlist/remove", data={"_csrf": toka, "id": item_id})
        self.assertIn("Your Wishlist is empty", a.get("/wishlist").get_data(as_text=True))

    def test_wishlist_rejects_bad_input(self):
        c, tok = self.new_user("wl_bad")
        bad_link = dict(ROW, amazon=dict(AMAZON, url="https://evil.example/dp/B0ABCDEFGH"), flipkart=None)
        self.assertEqual(self.toggle(c, tok, bad_link).status_code, 400)
        self.assertEqual(self.toggle(c, tok, dict(ROW, amazon=dict(AMAZON, price=-5))).status_code, 400)
        self.assertEqual(self.toggle(c, tok, dict(ROW, amazon=None, flipkart=None)).status_code, 400)
        self.assertEqual(c.post("/api/wishlist/toggle", json={"product": ROW}).status_code, 400)        # no CSRF header
        anon = pw.app.test_client()
        self.assertEqual(anon.post("/api/wishlist/toggle", json={"product": ROW}).status_code, 401)
        self.assertEqual(anon.get("/wishlist").status_code, 302)

    def test_best_price_is_computed_on_server(self):
        c, tok = self.new_user("wl_best")
        lying = dict(ROW, cheaper="amazon", difference=1)     # client claims are ignored
        self.toggle(c, tok, lying)
        page = c.get("/wishlist").get_data(as_text=True)
        self.assertIn("Flipkart", page.split("Best price")[1][:200])

    def test_history_save_order_dedupe_clear(self):
        c, tok = self.new_user("hist_user")
        self.assertIn("No recent searches", c.get("/history").get_data(as_text=True))
        h = {"X-CSRF-Token": tok}
        for q in ("iPhone 15", "HP Laptop", "Samsung S24", "iphone 15"):
            self.assertTrue(c.post("/api/history", json={"q": q}, headers=h).get_json()["saved"])
        page = c.get("/history").get_data(as_text=True)
        terms = re.findall(r'<li><a href="[^"]*">\s*<svg.*?</svg>\s*<span>(.*?)</span>', page, re.S)
        self.assertEqual(terms, ["iphone 15", "Samsung S24", "HP Laptop"])       # newest first, no duplicates
        self.assertIn("/?q=Samsung+S24", page)                                    # tapping re-runs the search
        self.assertFalse(c.post("/api/history", json={"q": "men shirt"}, headers=h).get_json()["saved"])
        self.assertFalse(c.post("/api/history", json={"q": "a"}, headers=h).get_json()["saved"])
        tokf = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
        c.post("/history/clear", data={"_csrf": tokf})
        self.assertIn("No recent searches", c.get("/history").get_data(as_text=True))

    def test_history_is_per_user_and_protected(self):
        a, ta = self.new_user("hist_a")
        b, tb = self.new_user("hist_b")
        a.post("/api/history", json={"q": "Sony WH-1000XM5"}, headers={"X-CSRF-Token": ta})
        self.assertIn("Sony WH-1000XM5", a.get("/history").get_data(as_text=True))
        self.assertIn("No recent searches", b.get("/history").get_data(as_text=True))
        tokb = re.search(r'name="_csrf" value="([^"]+)"', b.get("/history").get_data(as_text=True)).group(1)
        b.post("/history/clear", data={"_csrf": tokb})
        self.assertIn("Sony WH-1000XM5", a.get("/history").get_data(as_text=True))   # b's clear did not touch a
        anon = pw.app.test_client()
        self.assertEqual(anon.get("/history").status_code, 302)
        self.assertEqual(anon.post("/api/history", json={"q": "iphone"}).status_code, 401)

    def test_history_limited_to_30(self):
        c, tok = self.new_user("hist_many")
        for i in range(35):
            c.post("/api/history", json={"q": f"phone model {i}"}, headers={"X-CSRF-Token": tok})
        page = c.get("/history").get_data(as_text=True)
        self.assertEqual(page.count("<li>"), 30)
        self.assertIn("phone model 34", page)
        self.assertNotIn("phone model 4<", page)

    def test_calls_work_with_header_instead_of_page_token(self):
        c, _ = self.new_user("hdr_user")
        h = {"X-Requested-With": "pricewise"}
        self.assertTrue(c.post("/api/history", json={"q": "Sony WH-1000XM5"}, headers=h).get_json()["saved"])
        self.assertTrue(c.post("/api/wishlist/toggle", json={"product": ROW}, headers=h).get_json()["saved"])
        # neither header nor token: refused
        self.assertEqual(c.post("/api/history", json={"q": "x phone"}).status_code, 400)
        # header without a JSON body (like a cross-site form post): refused
        self.assertEqual(c.post("/api/history", data={"q": "iphone 15"}, headers=h).status_code, 400)

    def test_static_files_are_versioned_and_nav_is_present(self):
        c, _ = self.new_user("asset_user")
        for path in ("/", "/wishlist", "/history", "/about"):
            page = c.get(path).get_data(as_text=True)
            self.assertRegex(page, r'/static/style\.css\?v=\d+')
            self.assertRegex(page, r'/static/site\.js\?v=\d+')
            for label in ("Home", "Search", "Wishlist", "History"):
                self.assertIn("<span>%s</span>" % label, page)
            self.assertIn('href="/wishlist"', page)
            self.assertIn('href="/history"', page)
        self.assertRegex(c.get("/").get_data(as_text=True), r'/static/app\.js\?v=\d+')

    def test_install_check_reports_missing_files(self):
        import contextlib, io
        original = pw.REQUIRED_FILES
        pw.REQUIRED_FILES = original + ["templates/does_not_exist.html"]
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit):
                pw.check_install()
            self.assertIn("templates/does_not_exist.html", buf.getvalue())
        finally:
            pw.REQUIRED_FILES = original
        pw.check_install()          # the real project is complete: must not exit

    def test_wishlist_keeps_every_image_for_fallback(self):
        c, tok = self.new_user("img_user")
        row = dict(ROW, image="https://img.example/a.jpg", images=["https://img.example/a.jpg", "https://img.example/b.jpg", "http://insecure.example/c.jpg"])
        self.toggle(c, tok, row)
        page = c.get("/wishlist").get_data(as_text=True)
        self.assertIn('src="https://img.example/a.jpg"', page)
        self.assertIn("https://img.example/b.jpg", page.split("data-alt=")[1][:120])      # backup image
        self.assertNotIn("insecure.example", page)                                         # only https accepted

    def test_data_is_tied_to_the_email_account(self):
        a, ta = self.new_user("mail_a")
        self.toggle(a, ta)
        a.post("/api/history", json={"q": "iPhone 15"}, headers={"X-CSRF-Token": ta})
        self.assertIn("mail_a@example.com", a.get("/wishlist").get_data(as_text=True))
        self.assertIn("mail_a@example.com", a.get("/history").get_data(as_text=True))
        # same person logs in again later on another device: data is still there
        other_device = pw.app.test_client()
        tok = re.search(r'name="_csrf" value="([^"]+)"', other_device.get("/login").get_data(as_text=True)).group(1)
        other_device.post("/login", data={"_csrf": tok, "login": "MAIL_A@example.com", "password": "secret12"})
        self.assertIn("Demo Phone X 5G", other_device.get("/wishlist").get_data(as_text=True))
        self.assertIn("iPhone 15", other_device.get("/history").get_data(as_text=True))

    def test_inr_format(self):
        self.assertEqual([pw.format_inr(n) for n in (999, 2999, 43999, 154900, 1234567)],
                         ["\u20b9999", "\u20b92,999", "\u20b943,999", "\u20b91,54,900", "\u20b912,34,567"])


if __name__ == "__main__":
    unittest.main()

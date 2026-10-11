"""Starting page, sign-up, login, logout and access-control tests (temporary database)."""
import os
import re
import sys
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["PRICEWISE_DB"] = os.path.join(_tmp, "test.db")
os.environ["PRICEWISE_SECRET"] = "test-secret"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as pw  # noqa: E402


def token(client, path):
    html = client.get(path).get_data(as_text=True)
    return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)


def signup(client, name="Asha Rao", email="asha@example.com", pw_="secret12", confirm=None):
    return client.post("/signup", data={"_csrf": token(client, "/signup"), "name": name, "email": email,
                                        "password": pw_, "confirm": pw_ if confirm is None else confirm})


def login(client, email, password):
    return client.post("/login", data={"_csrf": token(client, "/login"), "login": email, "password": password})


class T(unittest.TestCase):
    def setUp(self):
        pw.app.config["TESTING"] = True
        self.c = pw.app.test_client()

    def test_starting_page_has_get_started_button(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        page = r.get_data(as_text=True)
        self.assertIn("PriceWise", page)
        self.assertRegex(page, r'<a class="btn-start" href="/signup">Get Started</a>')
        self.assertNotIn("Search for an electronic product", page)       # not the home screen

    def test_other_pages_still_need_login(self):
        for path in ("/about", "/wishlist", "/history"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers["Location"])
        self.assertEqual(self.c.get("/api/search?q=iphone").status_code, 401)

    def test_signup_page_has_the_four_fields(self):
        page = self.c.get("/signup").get_data(as_text=True)
        for field in ('name="name"', 'name="email"', 'name="password"', 'name="confirm"'):
            self.assertIn(field, page)

    def test_signup_validation(self):
        body = signup(self.c, name="", email="", pw_="").get_data(as_text=True)
        for msg in ("Enter your name.", "Enter your email.", "Enter your password."):
            self.assertIn(msg, body)
        self.assertEqual(signup(self.c, email="not-an-email").status_code, 400)
        self.assertIn("Enter a valid email address.", signup(self.c, email="a@b").get_data(as_text=True))
        self.assertIn("at least 6", signup(self.c, pw_="12345").get_data(as_text=True))
        self.assertIn("do not match", signup(self.c, pw_="secret12", confirm="secret13").get_data(as_text=True))

    def test_full_flow_signup_then_login_then_home(self):
        r = signup(self.c, name="Ravi Kumar", email="Ravi@Example.com")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))               # directed to the login page
        self.assertEqual(self.c.get("/about").status_code, 302)                  # but NOT logged in yet
        page = self.c.get("/login").get_data(as_text=True)
        self.assertIn("Account created successfully", page)                      # confirmation shown
        self.assertIn('value="ravi@example.com"', page)                          # email pre-filled
        r = login(self.c, "ravi@example.com", "secret12")                        # log in with email + password
        self.assertEqual(r.status_code, 302)
        home = self.c.get("/")
        self.assertEqual(home.status_code, 200)
        text = home.get_data(as_text=True)
        self.assertIn("Search for an electronic product", text)                  # the home screen
        self.assertIn("Hi, Ravi Kumar", text)                                    # name from sign-up
        self.assertIn('id="menu-btn"', text)                                     # three-dash button
        self.assertRegex(text, r'<nav id="menu"[\s\S]*?Wishlist[\s\S]*?History[\s\S]*?Logout')

    def test_duplicate_email_rejected(self):
        signup(self.c, email="dup@example.com")
        r = signup(pw.app.test_client(), email="DUP@example.com")
        self.assertEqual(r.status_code, 409)
        self.assertIn("already exists", r.get_data(as_text=True))

    def test_login_validation_and_wrong_password(self):
        signup(self.c, email="lena@example.com")
        c = pw.app.test_client()
        body = login(c, "", "").get_data(as_text=True)
        self.assertIn("Enter your email.", body)
        self.assertIn("Enter your password.", body)
        self.assertIn("Enter a valid email address.", login(c, "lena@@x", "x").get_data(as_text=True))
        r = login(c, "lena@example.com", "wrongpass")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Incorrect email or password.", r.get_data(as_text=True))
        self.assertEqual(login(c, "LENA@example.com", "secret12").status_code, 302)

    def test_logout_returns_to_start(self):
        signup(self.c, email="out@example.com")
        login(self.c, "out@example.com", "secret12")
        tok = re.search(r'name="_csrf" value="([^"]+)"', self.c.get("/").get_data(as_text=True)).group(1)
        self.assertEqual(self.c.post("/logout", data={"_csrf": tok}).status_code, 302)
        self.assertIn("Get Started", self.c.get("/").get_data(as_text=True))
        self.assertEqual(self.c.get("/wishlist").status_code, 302)

    def test_password_is_hashed(self):
        signup(self.c, email="hash@example.com", pw_="plainpass1")
        self.assertNotIn("plainpass1", pw.get_user("hash@example.com")["password_hash"])
        self.assertEqual(pw.get_user("hash@example.com")["name"], "Asha Rao")

    def test_csrf_required(self):
        self.assertEqual(self.c.post("/signup", data={"name": "A B", "email": "x@y.com", "password": "123456", "confirm": "123456"}).status_code, 400)
        self.assertEqual(self.c.post("/login", data={"login": "x@y.com", "password": "123456"}).status_code, 400)

    def test_throttling(self):
        signup(self.c, email="thr@example.com")
        c = pw.app.test_client()
        for _ in range(5):
            login(c, "thr@example.com", "badpass1")
        self.assertEqual(login(c, "thr@example.com", "secret12").status_code, 429)

    def test_old_username_account_can_still_log_in_and_name_column_added(self):
        pw.create_user("legacy_user", "secret12")             # account made before names/emails existed
        c = pw.app.test_client()
        self.assertEqual(login(c, "legacy_user", "secret12").status_code, 302)
        self.assertIn("Hi, legacy_user", c.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()

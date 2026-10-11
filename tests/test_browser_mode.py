"""Hidden-browser behaviour: windows only appear when Amazon needs a CAPTCHA solved."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers import amazon  # noqa: E402
from scrapers.common import FetchResult  # noqa: E402


class T(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._orig = (amazon._search, amazon.HEADLESS, amazon.SHOW_ON_BLOCK)

    def tearDown(self):
        amazon._search, amazon.HEADLESS, amazon.SHOW_ON_BLOCK = self._orig

    def fake(self, statuses):
        it = iter(statuses)
        def _search(q, n, headless=True):
            self.calls.append(headless)
            return FetchResult("amazon", next(it))
        amazon._search = _search

    def test_normal_search_stays_hidden(self):
        amazon.HEADLESS, amazon.SHOW_ON_BLOCK = True, True
        self.fake(["ok"])
        self.assertEqual(amazon.search_amazon("iphone").status, "ok")
        self.assertEqual(self.calls, [True])                    # one hidden run, no window

    def test_window_opens_only_after_a_captcha(self):
        amazon.HEADLESS, amazon.SHOW_ON_BLOCK = True, True
        self.fake(["blocked", "ok"])
        self.assertEqual(amazon.search_amazon("iphone").status, "ok")
        self.assertEqual(self.calls, [True, False])             # hidden first, then one visible retry

    def test_never_show_window_when_disabled(self):
        amazon.HEADLESS, amazon.SHOW_ON_BLOCK = True, False
        self.fake(["blocked"])
        self.assertEqual(amazon.search_amazon("iphone").status, "blocked")
        self.assertEqual(self.calls, [True])

    def test_no_double_retry_when_already_visible(self):
        amazon.HEADLESS, amazon.SHOW_ON_BLOCK = False, True
        self.fake(["blocked"])
        amazon.search_amazon("iphone")
        self.assertEqual(self.calls, [False])

    def test_errors_do_not_open_a_window(self):
        amazon.HEADLESS, amazon.SHOW_ON_BLOCK = True, True
        self.fake(["error"])
        amazon.search_amazon("iphone")
        self.assertEqual(self.calls, [True])


if __name__ == "__main__":
    unittest.main()

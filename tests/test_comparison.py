"""Tests the pairing/comparison pipeline with hand-written sample listings
(test inputs only; prices here are arbitrary and never shown in the app)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from comparison import build_comparison  # noqa: E402
from scrapers.common import FetchResult, Listing  # noqa: E402


def L(p, name, price, rank):
    return Listing(p, name, price, f"https://example.test/{p}/{rank}", None, 4.2, 100, rank)


class T(unittest.TestCase):
    def test_pipeline(self):
        amazon = FetchResult("amazon", "ok", [
            L("amazon", "Apple iPhone 15 (128 GB) - Black", 70000, 0),
            L("amazon", "Apple iPhone 15 (256 GB) - Black", 80000, 1),
            L("amazon", "Apple iPhone 15 Pro (128 GB)", 120000, 2),
            L("amazon", "Spigen Case for iPhone 15", 999, 3),
            L("amazon", "Men's Cotton Shirt", 499, 4),
        ])
        flip = FetchResult("flipkart", "ok", [
            L("flipkart", "Apple iPhone 15 (Blue, 128 GB)", 69500, 0),
            L("flipkart", "Apple iPhone 15 Plus (128 GB)", 80000, 1),
        ])
        out = build_comparison("iPhone 15 128GB", {"amazon": amazon, "flipkart": flip})
        self.assertEqual(len(out["results"]), 1)
        r = out["results"][0]
        self.assertEqual((r["cheaper"], r["difference"]), ("flipkart", 500))

    def test_blocked_side_is_reported_unavailable(self):
        amazon = FetchResult("amazon", "ok", [L("amazon", "Apple iPhone 15 (128 GB)", 70000, 0)])
        flip = FetchResult("flipkart", "blocked", [], "blocked")
        out = build_comparison("iPhone 15", {"amazon": amazon, "flipkart": flip})
        r = out["results"][0]
        self.assertIsNone(r["flipkart"])
        self.assertEqual(r["flipkart_note"], "unavailable")
        self.assertIsNone(r["difference"])


if __name__ == "__main__":
    unittest.main()

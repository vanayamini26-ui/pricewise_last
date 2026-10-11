"""Unit tests for the matching logic. Titles below are hand-written samples that
imitate how Amazon/Flipkart format titles; they are test inputs only and are
never shown in the app."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from matching import *  # noqa: E402,F401,F403


class T(unittest.TestCase):
    def test_parse(self):
        s = parse_title("Apple iPhone 15 (128 GB) - Black")
        self.assertEqual((s.brand, s.storage, s.ident), ("apple", 128, frozenset({"15"})))

    def test_same_variant_pairs(self):
        a = parse_title("Apple iPhone 15 (128 GB) - Black")
        f = parse_title("Apple iPhone 15 (Blue, 128 GB)")
        self.assertGreaterEqual(pair_score(a, f), 0.6)

    def test_samsung_pairs(self):
        a = parse_title("Samsung Galaxy S24 5G AI Smartphone (Onyx Black, 8GB, 128GB Storage)")
        f = parse_title("SAMSUNG Galaxy S24 5G (Marble Gray, 128 GB)")
        self.assertGreaterEqual(pair_score(a, f), 0.6)

    def test_pro_not_paired(self):
        self.assertEqual(pair_score(parse_title("Apple iPhone 15 (128 GB)"),
                                    parse_title("Apple iPhone 15 Pro (128 GB)")), 0)

    def test_storage_not_paired(self):
        self.assertEqual(pair_score(parse_title("Apple iPhone 15 (128 GB)"),
                                    parse_title("Apple iPhone 15 (256 GB)")), 0)

    def test_model_not_paired(self):
        self.assertEqual(pair_score(parse_title("Samsung Galaxy S24 (128 GB)"),
                                    parse_title("Samsung Galaxy S23 (128 GB)")), 0)

    def test_relevance(self):
        q = parse_title("iPhone 15 128GB")
        self.assertTrue(is_relevant(q, parse_title("Apple iPhone 15 (128 GB) - Black")))
        self.assertFalse(is_relevant(q, parse_title("Apple iPhone 15 Plus (128 GB)")))
        self.assertFalse(is_relevant(q, parse_title("Apple iPhone 15 (256 GB)")))
        self.assertFalse(is_relevant(q, parse_title("Samsung Galaxy S24 (128 GB)")))

    def test_spaced_model_suffix(self):
        q = parse_title("realme 11 x 5g")
        for title in ("realme 11x 5G (Purple Dawn, 6GB RAM, 128GB Storage)",
                      "realme 11X 5G | 64MP AI Camera (Midnight Black, 8GB, 128GB)"):
            self.assertTrue(is_relevant(q, parse_title(title)), title)
        self.assertFalse(is_relevant(q, parse_title("realme 11 Pro 5G (8GB, 128GB)")))
        self.assertFalse(is_relevant(q, parse_title("realme 11 5G (8GB, 128GB)")))
        self.assertGreaterEqual(pair_score(parse_title("realme 11x 5G (6GB, 128GB)"),
                                           parse_title("realme 11 x 5G (6 GB RAM, 128 GB)")), 0.6)

    def test_real_amazon_titles(self):
        # Titles copied from a real Amazon India result (diagnose.py output).
        a17 = parse_title("iPhone 17 256 GB: 15.93 cm (6.3\u2033) Display with Promotion, A19 Chip, Center Stage Front Camera for Smarter Group Selfies,")
        self.assertEqual((a17.brand, a17.storage, a17.ident, a17.variants), ("apple", 256, frozenset({"17"}), frozenset()))
        e17 = parse_title("iPhone 17e 256 GB: 15.40 cm (6.1\u2033) Super Retina XDR Display, A19 Chip, All-Day Battery Life, 48MP Fusion Camera, 256GB S")
        self.assertEqual((e17.storage, e17.ram), (256, None))
        nord = parse_title("Nord CE6 Lite | 8GB+128GB | Hyper Black | Segment's Fastest Dimensity 7400 Apex Processor | 7000mAh Battery | Segment's ")
        self.assertEqual((nord.ram, nord.storage, nord.variants, nord.brand), (8, 128, frozenset({"lite"}), "oneplus"))
        s25 = parse_title("Galaxy S25 Ultra 5G AI Smartphone (Titanium Whitesilver, 12GB RAM, 256GB Storage), 200MP Camera, 5000mAh Ultra Long Batt")
        self.assertEqual((s25.ident, s25.variants, s25.ram, s25.storage), (frozenset({"s25"}), frozenset({"ultra"}), 12, 256))
        q = parse_title("iPhone 17 256GB")
        self.assertTrue(is_relevant(q, a17))
        self.assertFalse(is_relevant(q, e17))
        self.assertGreaterEqual(pair_score(a17, parse_title("Apple iPhone 17 (Black, 256 GB)")), 0.6)
        self.assertGreaterEqual(pair_score(s25, parse_title("SAMSUNG Galaxy S25 Ultra 5G (Titanium Black, 12 GB RAM, 256 GB)")), 0.6)

    def test_laptop_flexible_queries(self):
        amazon = parse_title("Lenovo IdeaPad Slim 3 Intel Core i3-1315U 15.6 inch (39.6cm) FHD Thin & Light Laptop (8GB RAM/512GB SSD/Windows 11/Office 2021/Grey/1.62 kg), 83ER00E5IN")
        flip = parse_title("Lenovo IdeaPad Slim 3 Intel Core i3 13th Gen 1315U - (8 GB/512 GB SSD/Windows 11 Home) 15IAH8 Thin and Light Laptop")
        for q in ("lenovo ideapad slim i3 intel core", "ideapad slim intelcore i3",
                  "Lenovo IdeaPad Slim 3 i3", "intel core i3 ideapad slim lenovo"):
            qs = parse_title(q)
            self.assertTrue(is_relevant(qs, amazon), q)
            self.assertTrue(is_relevant(qs, flip), q)
        self.assertGreaterEqual(pair_score(amazon, flip), 0.6)
        # wrong models must still be rejected
        qs = parse_title("lenovo ideapad slim i3 intel core")
        self.assertFalse(is_relevant(qs, parse_title("Lenovo IdeaPad Slim 5 Intel Core i5 13th Gen (16GB/512GB SSD)")))
        self.assertFalse(is_relevant(qs, parse_title("Lenovo IdeaPad Gaming 3 Intel Core i5 (8GB/512GB SSD)")))
        self.assertFalse(is_relevant(qs, parse_title("HP 15s Intel Core i3 12th Gen (8GB/512GB SSD)")))

    def test_iphone_not_matched_by_screen_size(self):
        q = parse_title("iPhone 15")
        self.assertFalse(is_relevant(q, parse_title("iPhone 17 256 GB: 15.93 cm (6.3) Display, A19 Chip")))

    def test_laptop_memory(self):
        s = parse_title("HP Pavilion 15 Intel Core i5 16GB RAM 512GB SSD Windows 11 Laptop")
        self.assertEqual((s.ram, s.storage), (16, 512))
        s = parse_title("Dell Inspiron (16GB/512GB SSD)")
        self.assertEqual((s.ram, s.storage), (16, 512))

    def test_accessories(self):
        self.assertTrue(is_accessory("Spigen Case for iPhone 15", "iphone 15"))
        self.assertTrue(is_accessory("Tempered Glass Screen Protector iPhone 15", "iphone 15"))
        self.assertFalse(is_accessory("Apple iPhone 15 (128 GB)", "iphone 15"))
        self.assertFalse(is_accessory("Apple 20W USB-C Charger", "apple charger"))

    def test_electronics_filter(self):
        self.assertFalse(is_electronic("Men's Cotton Shirt"))
        self.assertFalse(query_is_allowed("running shoes"))
        self.assertTrue(is_electronic("boAt Rockerz 450 Bluetooth Headphones"))
        self.assertTrue(is_electronic("Samsung Galaxy S24"))


if __name__ == "__main__":
    unittest.main()

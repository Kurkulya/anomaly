import unittest

from shelf import pricing


class PricingTest(unittest.TestCase):
    def test_a_price_with_cents_is_read(self):
        self.assertEqual(pricing.to_cents('12.50'), 1250)

    def test_a_price_without_cents_is_read(self):
        self.assertEqual(pricing.to_cents('7'), 700)

    def test_text_that_is_not_a_price_is_refused(self):
        with self.assertRaises(ValueError):
            pricing.to_cents('twelve')

    def test_cents_are_written_with_two_digits(self):
        self.assertEqual(pricing.format_cents(705), '7.05')

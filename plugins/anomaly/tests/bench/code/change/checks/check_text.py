import unittest

from shelf import text


class FoldTest(unittest.TestCase):
    def test_spaces_and_case_are_folded_away(self):
        self.assertEqual(text.fold('  The   Big  Book '), 'the big book')


class ShortenTest(unittest.TestCase):
    def test_a_short_text_is_kept(self):
        self.assertEqual(text.shorten('abc', 5), 'abc')

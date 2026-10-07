import unittest

from receipt import parse


class RowsTest(unittest.TestCase):
    def test_each_line_becomes_an_item_and_its_cents(self):
        self.assertEqual(parse.rows('tea,250\nbread,199\n'), [('tea', 250), ('bread', 199)])

    def test_blank_lines_are_skipped(self):
        self.assertEqual(parse.rows('tea,250\n\n  \n'), [('tea', 250)])

    def test_an_item_may_hold_a_comma(self):
        self.assertEqual(parse.rows('salt, fine,90\n'), [('salt, fine', 90)])

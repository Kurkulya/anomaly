"""Characterization check (split-total spec, AC-3): pins the total of two rows."""
import unittest
from unittest import mock

from receipt import parse, total


class PinTotalTest(unittest.TestCase):
    def test_the_total_of_two_rows_is_unchanged(self):
        text = 'salt, fine,90\ntea,250\n'
        with mock.patch.object(parse, 'rows', return_value=[('salt, fine', 90), ('tea', 250)]):
            self.assertEqual(total.total_of(text), 340)

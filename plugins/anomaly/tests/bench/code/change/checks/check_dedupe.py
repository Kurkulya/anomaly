import unittest

from shelf import dedupe


class DuplicatesTest(unittest.TestCase):
    def test_a_title_entered_again_in_other_case_or_spacing_is_reported(self):
        self.assertEqual(dedupe.duplicates(['Maps', 'maps ', 'Atlas']), ['maps '])

import unittest

from shelf import stats


class StatsTest(unittest.TestCase):
    def test_counts_that_share_a_key_are_added_up(self):
        self.assertEqual(stats.fold([('a', 1), ('b', 2), ('a', 3)]), {'a': 4, 'b': 2})

    def test_the_busiest_key_has_the_largest_total(self):
        self.assertEqual(stats.busiest({'a': 4, 'b': 2}), 'a')

    def test_no_keys_have_no_busiest_one(self):
        self.assertIsNone(stats.busiest({}))

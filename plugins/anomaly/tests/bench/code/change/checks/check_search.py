import unittest

from shelf import search


class SearchTest(unittest.TestCase):
    def test_a_query_of_words_is_folded(self):
        self.assertEqual(search.parse_query('Big  Book'), 'big book')

    def test_a_query_that_is_not_made_of_words_is_refused(self):
        self.assertIsNone(search.parse_query('!!'))

    def test_the_rows_that_hold_the_query_are_found(self):
        self.assertEqual(search.find(['The Big Book', 'Maps'], 'big'), ['The Big Book'])

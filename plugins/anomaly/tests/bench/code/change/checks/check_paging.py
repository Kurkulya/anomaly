import unittest

from shelf import paging


class PagingTest(unittest.TestCase):
    def test_an_empty_list_still_has_one_page(self):
        self.assertEqual(paging.page_count(0), 1)

    def test_rows_that_do_not_fill_the_last_page_need_one_more(self):
        self.assertEqual(paging.page_count(41), 3)

    def test_slots_start_at_one(self):
        self.assertEqual(paging.slots(3)[0], 1)

    def test_a_page_holds_its_own_rows(self):
        rows = list(range(50))
        self.assertEqual(paging.page_rows(rows, 1), rows[20:40])

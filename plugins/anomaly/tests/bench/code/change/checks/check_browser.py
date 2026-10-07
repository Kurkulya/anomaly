import unittest

from shelf.browser import Browser


class BrowserTest(unittest.TestCase):
    def test_the_filter_keeps_the_rows_that_hold_it_whatever_their_case(self):
        browser = Browser(['The Big Book', 'A Small Book', 'Maps'])
        browser.set_filter('BOOK')
        self.assertEqual(browser.visible(), ['The Big Book', 'A Small Book'])

    def test_the_first_page_is_shown_first(self):
        browser = Browser([f'row {n}' for n in range(45)])
        self.assertEqual(browser.current(), [f'row {n}' for n in range(20)])

    def test_next_page_stops_at_the_last_page(self):
        browser = Browser([f'row {n}' for n in range(45)])
        for _ in range(5):
            browser.next_page()
        self.assertEqual(browser.current(), [f'row {n}' for n in range(40, 45)])

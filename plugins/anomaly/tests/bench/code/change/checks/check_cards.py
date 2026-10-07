import unittest

from shelf import cards

BOOK = {'title': 'The Big Book', 'author': 'An Author', 'shelf': 'B4', 'year': 1999, 'price_cents': 1250,
        'pages': 300, 'language': 'en', 'isbn': '9780000000000', 'copies': 3, 'out': 1, 'late': 0}


class RenderCardTest(unittest.TestCase):
    def test_the_card_names_the_title_and_the_price(self):
        card = cards.render_card(BOOK)
        self.assertIn('The Big Book', card)
        self.assertIn('12.50', card)

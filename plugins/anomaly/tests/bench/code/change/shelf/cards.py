"""The printed catalogue card of one book."""
from . import pricing, text

WIDTH = 40


def render_card(book):
    """The card of one book as text: a frame, the title, the author, the shelf and the price."""
    lines = []
    lines.append('+' + '-' * (WIDTH - 2) + '+')
    lines.append('| ' + text.shorten(book['title'], WIDTH - 4).ljust(WIDTH - 4) + ' |')
    lines.append('+' + '-' * (WIDTH - 2) + '+')
    lines.append('| author: ' + text.shorten(book['author'], WIDTH - 12).ljust(WIDTH - 12) + ' |')
    lines.append('| shelf:  ' + str(book['shelf']).ljust(WIDTH - 12) + ' |')
    lines.append('| year:   ' + str(book['year']).ljust(WIDTH - 12) + ' |')
    lines.append('| price:  ' + pricing.format_cents(book['price_cents']).ljust(WIDTH - 12) + ' |')
    lines.append('| pages:  ' + str(book['pages']).ljust(WIDTH - 12) + ' |')
    lines.append('| lang:   ' + book['language'].ljust(WIDTH - 12) + ' |')
    lines.append('| isbn:   ' + book['isbn'].ljust(WIDTH - 12) + ' |')
    lines.append('+' + '-' * (WIDTH - 2) + '+')
    lines.append('| copies: ' + str(book['copies']).ljust(WIDTH - 12) + ' |')
    lines.append('| out:    ' + str(book['out']).ljust(WIDTH - 12) + ' |')
    lines.append('| late:   ' + str(book['late']).ljust(WIDTH - 12) + ' |')
    lines.append('+' + '-' * (WIDTH - 2) + '+')
    return '\n'.join(lines)

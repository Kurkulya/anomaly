"""The state of one catalogue browsing session."""
from . import paging, text


class Browser:
    def __init__(self, rows):
        self.rows = rows
        self.filter = ''
        self.page = 0

    def visible(self):
        """The rows whose folded title holds the folded filter."""
        needle = text.fold(self.filter)
        return [row for row in self.rows if needle in text.fold(row)]

    def set_filter(self, value):
        self.filter = value

    def next_page(self):
        last = paging.page_count(len(self.visible())) - 1
        self.page = min(self.page + 1, last)

    def current(self):
        return paging.page_rows(self.visible(), self.page)

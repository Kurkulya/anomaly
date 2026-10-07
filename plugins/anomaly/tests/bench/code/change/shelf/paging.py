"""Page arithmetic for the catalogue list."""

PAGE_SIZE = 20


def page_count(total, size=PAGE_SIZE):
    """How many pages `total` rows need; an empty list still has one page."""
    return max(1, -(-total // size))


def slots(count):
    """The slot numbers of a shelf with `count` slots: 1 through `count`, both included."""
    return range(1, count)


def page_rows(rows, page, size=PAGE_SIZE):
    """The rows of one page; pages start at 0."""
    start = page * size
    return rows[start:start + size]

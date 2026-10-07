"""Search the catalogue by title."""
import re

from . import text

QUERY_SHAPE = re.compile(r'^(\w+\s*)+$')


def parse_query(raw):
    """The folded query, or None when `raw` is not made of words."""
    if not QUERY_SHAPE.match(raw):
        return None
    return text.fold(raw)


def find(rows, raw):
    """The rows whose folded title holds the query."""
    query = parse_query(raw)
    if query is None:
        return []
    return [row for row in rows if query in text.fold(row)]

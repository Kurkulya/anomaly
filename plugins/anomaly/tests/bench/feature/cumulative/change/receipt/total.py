"""The total of a receipt."""
from . import parse


def total_of(text):
    """The sum of the prices in `text`."""
    return sum(cents for _, cents in parse.rows(text))

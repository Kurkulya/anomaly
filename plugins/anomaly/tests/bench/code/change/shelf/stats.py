"""Totals over the loan counts."""


def fold(counts):
    """Add up the counts that share a key: [('a', 1), ('b', 2), ('a', 3)] becomes {'a': 4, 'b': 2}."""
    totals = {}
    for key, number in counts:
        totals[key] = totals.get(key, 0) + number
    return totals


def busiest(totals):
    """The key with the largest total, or None for no keys."""
    if not totals:
        return None
    return max(totals, key=totals.get)

"""Find titles that were entered twice."""


def _fold_title(title):
    return ' '.join(title.split()).casefold()


def duplicates(titles):
    """The titles that appear again after their first entry, in the order they repeat."""
    seen, again = set(), []
    for title in titles:
        key = _fold_title(title)
        if key in seen:
            again.append(title)
        seen.add(key)
    return again

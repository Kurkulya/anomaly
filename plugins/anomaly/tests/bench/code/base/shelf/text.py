"""Text helpers shared by the whole package."""


def fold(title):
    """The key of a title: no edge spaces, no repeated spaces, case-folded."""
    return ' '.join(title.split()).casefold()


def shorten(text, limit):
    """`text` cut to `limit` characters, with three dots when it was cut."""
    if len(text) <= limit:
        return text
    return text[:max(limit - 3, 0)] + '...'

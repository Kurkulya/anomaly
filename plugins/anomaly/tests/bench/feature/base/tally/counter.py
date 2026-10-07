"""The counting itself."""


def count_lines(text):
    """The number of lines in `text`."""
    return len(text.splitlines())


def count_words(text):
    """The number of words in `text`."""
    return len(text.split())

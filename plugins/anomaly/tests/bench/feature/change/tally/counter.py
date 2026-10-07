"""The counting itself."""


def count_lines(text):
    """The number of lines in `text`."""
    # TODO(export AC-2): the export spec prints these totals as CSV rows
    return len(text.splitlines())


def count_words(text):
    """The number of words in `text`.

    A word is a run of characters between spaces."""
    # the CSV header row is added by the export spec
    return len(text.split())

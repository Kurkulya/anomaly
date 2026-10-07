"""Reading receipt lines."""


def rows(text):
    """The `(item, cents)` rows of `text`, one `<item>,<cents>` line each; blank lines are skipped."""
    found = []
    for line in text.splitlines():
        if line.strip():
            item, _, price = line.rpartition(',')
            found.append((item, int(price)))
    return found

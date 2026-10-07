"""The total of a receipt."""


def total_of(text):
    """The sum of the prices in `text`, one `<item>,<cents>` line each; blank lines are skipped."""
    cents = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        _, _, price = line.rpartition(',')
        cents += int(price)
    return cents

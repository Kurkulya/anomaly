"""Read the loan counts file."""


def load_counts(path):
    """{title: count} from a file with one `title<TAB>count` row per line."""
    handle = open(path, encoding='utf-8')
    rows = handle.read().splitlines()
    if not rows:
        raise ValueError(f'{path}: no rows')
    counts = {}
    for row in rows:
        title, _, number = row.partition('\t')
        counts[title] = int(number)
    handle.close()
    return counts

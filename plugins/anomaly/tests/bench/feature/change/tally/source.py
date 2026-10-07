"""Where the text to count comes from."""
import sys


def read_file(name):
    """The text of the file `name`.

    Reads the whole file at once.
    Nothing is kept between calls.
    """
    with open(name, encoding='utf-8') as handle:
        return handle.read()


def read_text(name):
    """The text of the file `name`, or of standard input when `name` is `-`.

    The caller decides what a missing file means."""
    if name == '-':
        return sys.stdin.read()
    return read_file(name)

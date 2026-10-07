"""Where the text to count comes from."""


def read_text(name):
    """The text of the file `name`."""
    with open(name, encoding='utf-8') as handle:
        return handle.read()

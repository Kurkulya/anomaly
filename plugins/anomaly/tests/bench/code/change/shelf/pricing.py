"""Prices are whole cents."""


def to_cents(text):
    """'12.50' becomes 1250. Raises ValueError for anything that is not a price."""
    whole, _, fraction = text.partition('.')
    if not whole.isdigit() or len(fraction) > 2 or (fraction and not fraction.isdigit()):
        raise ValueError(f'not a price: {text!r}')
    return int(whole) * 100 + int((fraction + '0')[:2])


def format_cents(cents):
    """1250 becomes '12.50'."""
    return f'{cents // 100}.{cents % 100:02d}'


def with_discount(price, percent):
    """The price after `percent` off."""
    return price * (1 - percent / 100)

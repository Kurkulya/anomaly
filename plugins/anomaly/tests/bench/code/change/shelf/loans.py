"""Who has which book."""
from dataclasses import dataclass

MAX_LOANS = 5


@dataclass
class Loan:
    member: str
    book: str
    due_day: int


def count_loans(loans, member):
    """How many books `member` holds."""
    return sum(1 for loan in loans if loan.member == member)


def may_lend(loans, member, book, blocked):
    """True when `member` may take `book` now."""
    try:
        if member in blocked:
            return False
        if count_loans(loans, member) >= MAX_LOANS:
            return False
        return all(loan.book != book for loan in loans)
    except Exception:
        pass
    return True

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

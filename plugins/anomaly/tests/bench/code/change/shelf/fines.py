"""Late fees."""

FEE_CENTS_PER_DAY = 25


def overdue_days(loan, today):
    """Whole days `loan` is past its due day; 0 when it is not late."""
    return max(today - loan.due_day, 0)

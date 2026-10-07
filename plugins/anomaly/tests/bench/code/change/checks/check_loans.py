import unittest

from shelf.loans import MAX_LOANS, Loan, count_loans, may_lend


class CountLoansTest(unittest.TestCase):
    def test_only_the_loans_of_the_member_are_counted(self):
        loans = [Loan('ann', 'b1', 10), Loan('bob', 'b2', 10), Loan('ann', 'b3', 12)]
        self.assertEqual(count_loans(loans, 'ann'), 2)


class MayLendTest(unittest.TestCase):
    def test_a_free_book_goes_to_a_member_with_room(self):
        self.assertTrue(may_lend([], 'ann', 'b1', set()))

    def test_a_blocked_member_gets_no_book(self):
        self.assertFalse(may_lend([], 'ann', 'b1', {'ann'}))

    def test_a_member_at_the_limit_gets_no_book(self):
        loans = [Loan('ann', f'x{n}', 10) for n in range(MAX_LOANS)]
        self.assertFalse(may_lend(loans, 'ann', 'b1', set()))

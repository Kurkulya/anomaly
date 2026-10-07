import unittest

from shelf.loans import Loan, count_loans


class CountLoansTest(unittest.TestCase):
    def test_only_the_loans_of_the_member_are_counted(self):
        loans = [Loan('ann', 'b1', 10), Loan('bob', 'b2', 10), Loan('ann', 'b3', 12)]
        self.assertEqual(count_loans(loans, 'ann'), 2)

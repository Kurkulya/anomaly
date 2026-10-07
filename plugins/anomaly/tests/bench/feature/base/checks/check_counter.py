import unittest

from tally import counter


class CounterTest(unittest.TestCase):
    def test_lines_are_counted(self):
        self.assertEqual(counter.count_lines('a\nb\nc\n'), 3)

    def test_words_are_counted(self):
        self.assertEqual(counter.count_words('one two\nthree'), 3)

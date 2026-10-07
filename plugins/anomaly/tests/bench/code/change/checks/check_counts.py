import tempfile
import unittest
from pathlib import Path

from shelf import counts


class LoadCountsTest(unittest.TestCase):
    def test_each_row_becomes_a_title_and_a_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'counts.tsv'
            path.write_text('Maps\t2\nAtlas\t3\n', encoding='utf-8')
            self.assertEqual(counts.load_counts(path), {'Maps': 2, 'Atlas': 3})

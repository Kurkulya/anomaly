import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tally import cli


class ByWordTest(unittest.TestCase):
    def test_by_word_counts_words_and_prints_the_bare_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.txt'
            path.write_text('one two three\nfour\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(['count', str(path), '--by-word'])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), '4\n')

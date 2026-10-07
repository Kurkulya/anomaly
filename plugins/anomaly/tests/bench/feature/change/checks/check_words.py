import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tally import cli


class WordsOptionTest(unittest.TestCase):
    def test_the_words_option_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.txt'
            path.write_text('one two three\n', encoding='utf-8')
            with contextlib.redirect_stdout(io.StringIO()):
                code = cli.main(['count', str(path), '--words'])
        self.assertEqual(code, 0)

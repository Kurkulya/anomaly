import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tally import cli


class CountIntegrationTest(unittest.TestCase):
    def test_the_command_prints_the_line_count_with_its_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.txt'
            path.write_text('a\nb\nc\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(['count', str(path)])
        self.assertEqual((code, out.getvalue()), (0, '3 lines\n'))

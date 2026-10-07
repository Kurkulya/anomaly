"""Characterization check (split-total spec, AC-3): pins what `receipt total` prints. It runs the
command the way a user does."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from receipt import cli


class PinOutputTest(unittest.TestCase):
    def test_the_total_line_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'r.txt'
            path.write_text('tea,250\n\nbread,199\n', encoding='utf-8')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(['total', str(path)])
        self.assertEqual((code, out.getvalue()), (0, 'total: 449\n'))

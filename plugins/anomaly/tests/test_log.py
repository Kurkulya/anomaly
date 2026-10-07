"""`log add <folder> --stage <stage> '<text>'` through the CLI, in-process: one line
`<date time> <stage>: <text>` appended to `<folder>/log.md` (AC-6), and the refusals (AC-7)."""
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import assert_cli_error, run_cli

STAMP = '2026-10-04 12:00'   # the fixed clock, in constants.TICKET_TIME_FORMAT


class LogCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.folder = self.root / '.anomaly' / 'unit'
        self.folder.mkdir(parents=True)
        self.log = self.folder / 'log.md'

    def add(self, text='did a thing', stage='build', folder=None):
        return run_cli('log', 'add', str(folder or self.folder), '--stage', stage, text)

    def add_ok(self, *args, **kwargs):
        code, out, err = self.add(*args, **kwargs)
        self.assertEqual((code, err), (0, ''), out)

    def listing(self, root=None):
        base = Path(root or self.root)
        return sorted(str(p.relative_to(base)) for p in base.rglob('*'))


class AddTest(LogCase):
    def test_one_line_with_the_clocks_time_the_stage_and_the_text_creates_the_file(self):
        self.add_ok('first note', 'specify')
        self.assertEqual(self.log.read_bytes(), f'{STAMP} specify: first note\n'.encode())

    def test_a_second_call_appends_a_second_line_after_the_first(self):
        self.add_ok('one', 'build')
        self.add_ok('two', 'review')
        self.assertEqual(self.log.read_bytes().decode().splitlines(),
                         [f'{STAMP} build: one', f'{STAMP} review: two'])

    def test_nothing_else_is_written_in_the_folder(self):
        before = self.listing()
        self.add_ok()
        self.assertEqual(self.listing(), sorted([*before, str(Path('.anomaly/unit/log.md'))]))
        self.assertEqual(self.listing(self.folder), ['log.md'])

    def test_an_existing_file_keeps_its_line_ending_and_earlier_bytes(self):
        self.log.write_bytes(b'2026-10-03 09:00 build: old\r\n')
        self.add_ok('new')
        self.assertEqual(self.log.read_bytes(),
                         b'2026-10-03 09:00 build: old\r\n' + f'{STAMP} build: new\r\n'.encode())

    def test_a_line_feed_file_stays_line_feed(self):
        self.log.write_bytes(b'2026-10-03 09:00 build: old\n')
        self.add_ok('new')
        self.assertEqual(self.log.read_bytes(),
                         b'2026-10-03 09:00 build: old\n' + f'{STAMP} build: new\n'.encode())

    def test_a_folder_outside_anomaly_and_scratch_is_still_allowed(self):
        other = self.root / 'old-layout' / 'docs'
        other.mkdir(parents=True)
        self.add_ok('ok', 'build', folder=other)
        self.assertEqual((other / 'log.md').read_bytes(), f'{STAMP} build: ok\n'.encode())


class RefusalTest(LogCase):
    def control(self):
        """A valid call works, so a refusal below is the rule and not an unknown command."""
        other = self.root / 'control'
        other.mkdir()
        self.add_ok('control', folder=other)
        self.assertTrue((other / 'log.md').is_file())

    def test_text_with_a_newline_is_refused_on_one_anomaly_line_and_nothing_is_written(self):
        self.control()
        before = self.listing()
        assert_cli_error(self, self.add('two\nlines'))
        self.assertEqual(self.listing(), before)
        self.assertFalse(self.log.exists())

    def test_a_refused_newline_leaves_an_existing_log_as_it_was(self):
        self.control()
        self.log.write_bytes(b'x\r\n')
        assert_cli_error(self, self.add('a\r\nb'))
        self.assertEqual(self.log.read_bytes(), b'x\r\n')

    def test_a_folder_that_does_not_exist_is_refused_and_not_created(self):
        self.control()
        missing = self.root / '.anomaly' / 'nope'
        before = self.listing()
        assert_cli_error(self, self.add(folder=missing))
        self.assertFalse(missing.exists())
        self.assertEqual(self.listing(), before)


if __name__ == '__main__':
    unittest.main()

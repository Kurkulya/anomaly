"""`check pre-merge` through the CLI, in-process, against a temp git repository and a temp `.scratch` or `.anomaly`:
exit 0 only when `Reviewed:` and `Verified:` equal the head being merged and the acceptance test is
unchanged since its red commit (or the ticket holds a `Red-changed:` line). Each failed invariant is
one line on stdout and the exit code is 1; an error is one `anomaly:` line and exit 2."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from anomaly_loop import cli
from tests.fixtures import GitFixture, assert_cli_error, run_cli, write_text

TEST_PATH = 'tests/test_a.py'
TICKET_TEXT = """# 06: A ticket

Jira: no-ticket
Covers: AC-1
Blocked by: None
Status: in-progress

- [ ] AC-1: a criterion
"""


class CheckTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = GitFixture(self.root / 'repo')
        self.repo.write(TEST_PATH, 'test v1\n')
        self.red = self.repo.commit([TEST_PATH], 'test: red', date(2026, 10, 1))
        self.repo.write('src/a.py', 'code v1\n')
        self.code = self.repo.commit(['src/a.py'], 'feat: code', date(2026, 10, 2))
        self.ticket = self.repo.root / '.scratch' / 'feature' / 'issues' / '06-a-ticket.md'
        write_text(self.ticket, TICKET_TEXT)

    def ticket_cmd(self, *argv, ticket=None):
        repo = () if '--changed' in argv else ('--repo', str(self.repo.root))
        code, out, err = run_cli('ticket', argv[0], str(ticket or self.ticket), *argv[1:], *repo, '--home', str(self.home))
        self.assertEqual((code, err), (0, ''), out)

    def record(self, reviewed='head', verified='head', red=True, ticket=None):
        """Write the ticket lines through the ticket command; 'head' means the current head."""
        head = self.repo.git('rev-parse', 'HEAD').strip()
        if red:
            self.ticket_cmd('red', self.red, TEST_PATH, ticket=ticket)
        for name, value in (('reviewed', reviewed), ('verified', verified)):
            if value:
                self.ticket_cmd(name, head if value == 'head' else value, ticket=ticket)

    def write_ids(self, reviewed, verified):
        """Put these ids into the ticket lines as they are: the ticket command resolves an id to a commit, so
        an old short id, or one that names no commit, can only get there by hand."""
        text = self.ticket.read_text(encoding='utf-8')
        self.ticket.write_text(text.replace('Reviewed: ' + self.code, 'Reviewed: ' + reviewed).replace(
            'Verified: ' + self.code, 'Verified: ' + verified), encoding='utf-8', newline='\n')

    def edit_test(self):
        """Edit the acceptance test after its red commit; returns the new head."""
        self.repo.write(TEST_PATH, 'test v2\n')
        return self.repo.commit([TEST_PATH], 'test: edit', date(2026, 10, 3))

    def check(self, *extra, ticket=None):
        return run_cli('check', 'pre-merge', str(ticket or self.ticket), '--repo', str(self.repo.root),
                       '--home', str(self.home), *extra)

    def problems(self, result):
        code, out, err = result
        self.assertEqual((code, err), (1, ''), (out, err))
        return out.splitlines()


class RegistryTest(CheckTestCase):
    def test_check_is_registered_once_and_lists_pre_merge(self):
        self.assertEqual(cli.COMMANDS.count('check'), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(['check', '--help'], environ={})
        self.assertEqual(re.findall(r'^    ([a-z-]+)\s{2,}\S', out.getvalue(), re.M), ['pre-merge'])

    def test_a_failure_prints_one_anomaly_line_and_exits_2(self):
        assert_cli_error(self, self.check(ticket=self.repo.root / '.scratch' / '99-none.md'), '99-none.md')

    def test_a_head_that_is_not_a_commit_is_an_error(self):
        self.record()
        assert_cli_error(self, self.check('--head', 'no-such-branch'), 'no-such-branch')

    def test_a_folder_that_is_not_a_repository_is_an_error(self):
        plain = self.root / 'plain'
        plain.mkdir()
        self.record()
        code, out, err = run_cli('check', 'pre-merge', str(self.ticket), '--repo', str(plain), '--home', str(self.home))
        assert_cli_error(self, (code, out, err))


class PreMergeTest(CheckTestCase):
    def test_passes_when_reviewed_and_verified_are_the_head_and_the_test_is_unchanged(self):
        self.record()
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ''), out)
        self.assertIn(self.code[:12], out)
        self.assertEqual(len(out.splitlines()), 1, out)

    def test_no_reviewed_line_fails_and_names_reviewed_only(self):
        self.record(reviewed=None)
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Reviewed:'), lines)

    def test_a_verified_older_than_the_head_fails_and_names_verified_only(self):
        self.record(verified=self.red)
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Verified:'), lines)
        self.assertIn(self.red[:7], lines[0])

    def test_a_test_file_edited_after_the_red_commit_fails_and_names_the_file(self):
        head = self.edit_test()
        self.record(reviewed=head, verified=head)
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Test:'), lines)
        self.assertIn(TEST_PATH, lines[0])
        self.assertIn(self.red[:7], lines[0])

    def test_an_edited_test_file_passes_when_the_ticket_holds_a_red_changed_line(self):
        head = self.edit_test()
        self.record(reviewed=head, verified=head)
        self.ticket_cmd('red', '--changed', 'the seam moved from the CLI to the module')
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ''), out)
        notes = [line for line in out.splitlines() if line.startswith('note:')]
        self.assertEqual(len(notes), 1, out)
        self.assertIn(TEST_PATH, notes[0])
        self.assertIn('the seam moved from the CLI to the module', notes[0])

    def test_a_red_path_written_with_backslashes_is_read_with_forward_slashes(self):
        self.record()
        self.ticket_cmd('red', self.red, TEST_PATH.replace('/', '\\'))
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ''), out)

    def test_a_value_that_is_not_a_commit_id_says_so(self):
        self.record()
        self.ticket.write_text(self.ticket.read_text(encoding='utf-8').replace(
            'Reviewed: ' + self.code, 'Reviewed: main'), encoding='utf-8', newline='\n')
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('main is not a commit id', lines[0])

    def test_a_red_changed_line_does_not_excuse_a_wrong_reviewed_or_verified(self):
        head = self.edit_test()
        self.record(reviewed=self.red, verified=head)
        self.ticket_cmd('red', '--changed', 'why')
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Reviewed:'), lines)

    def edit_test_twice(self):
        """Edit the test, note why, edit it again; returns (first edit, head)."""
        first = self.edit_test()
        self.repo.write(TEST_PATH, 'test v3\n')
        return first, self.repo.commit([TEST_PATH], 'test: edit again', date(2026, 10, 4))

    def test_a_newer_red_sha_drops_the_earlier_notes_so_a_later_edit_needs_its_own(self):
        self.record()
        self.ticket_cmd('red', '--changed', 'the first reason')
        first, head = self.edit_test_twice()
        self.record(reviewed=head, verified=head, red=False)
        self.ticket_cmd('red', first, TEST_PATH)
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Test:'), lines)
        self.ticket_cmd('red', '--changed', 'the second reason')
        self.assertEqual(self.check()[0], 0)

    def test_the_same_red_sha_recorded_again_keeps_the_notes(self):
        self.record()
        self.ticket_cmd('red', '--changed', 'the first reason')
        _, head = self.edit_test_twice()
        self.record(reviewed=head, verified=head)
        self.assertEqual(self.check()[0], 0)

    def test_a_red_changed_line_excuses_a_missing_red_line_and_prints_the_reason(self):
        self.record(red=False)
        self.ticket_cmd('red', '--changed', 'a docs-only ticket has no acceptance test')
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ''), out)
        notes = [line for line in out.splitlines() if line.startswith('note:')]
        self.assertEqual(len(notes), 1, out)
        self.assertIn('no Red: line', notes[0])
        self.assertIn('a docs-only ticket has no acceptance test', notes[0])

    def test_every_failed_invariant_is_named_on_its_own_line(self):
        head = self.edit_test()
        self.record(reviewed=None, verified=self.red)
        lines = self.problems(self.check())
        self.assertEqual([line.split(':')[0] for line in lines], ['Reviewed', 'Verified', 'Test'], lines)
        self.assertEqual(head, self.repo.git('rev-parse', 'HEAD').strip())

    def test_short_and_full_commit_ids_are_normalised_before_they_are_compared(self):
        for reviewed, verified in ((self.code[:7], self.code[:12]), (self.code, self.code[:40])):
            with self.subTest(reviewed=len(reviewed), verified=len(verified)):
                self.record()
                self.write_ids(reviewed, verified)
                code, out, err = self.check()
                self.assertEqual((code, err), (0, ''), out)

    def test_a_commit_id_that_is_not_in_the_repository_fails(self):
        self.record()
        self.write_ids('deadbeef', self.code)
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Reviewed:') and 'deadbeef' in lines[0], lines)

    def test_a_ticket_without_a_red_line_fails_because_the_test_cannot_be_checked(self):
        self.record(red=False)
        lines = self.problems(self.check())
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith('Red:'), lines)

    def test_a_deleted_test_file_fails_unless_the_ticket_notes_why(self):
        self.repo.git('rm', '-q', '--', TEST_PATH)
        self.repo.git('commit', '-q', '-m', 'test: remove', when=date(2026, 10, 3))
        head = self.repo.git('rev-parse', 'HEAD').strip()
        self.record(reviewed=head, verified=head)
        lines = self.problems(self.check())
        self.assertTrue(lines[0].startswith('Test:'), lines)
        self.ticket_cmd('red', '--changed', 'the test moved to another file')
        self.assertEqual(self.check()[0], 0)

    def test_head_names_the_commit_that_is_merged_instead_of_the_checked_out_one(self):
        self.record()
        self.edit_test()
        self.assertEqual(self.check()[0], 1)
        self.assertEqual(self.check('--head', self.code)[0], 0)

    def test_the_check_changes_nothing(self):
        self.record(reviewed=None)
        before = (self.ticket.read_bytes(), self.repo.status(), self.repo.git('rev-parse', 'HEAD'))
        self.check()
        self.assertEqual((self.ticket.read_bytes(), self.repo.status(), self.repo.git('rev-parse', 'HEAD')), before)


class LayoutTest(CheckTestCase):
    """AC-88: a ticket in `.scratch/<feature>/issues/` and one in `.anomaly/<work-unit>/tickets/` give the
    same result."""

    def test_a_ticket_in_either_layout_gives_the_same_result(self):
        passes, fails = [], []
        for folder in (('.scratch', 'feature', 'issues'), ('.anomaly', 'unit', 'tickets')):
            for name, reviewed, results in (('06-a-ticket.md', 'head', passes), ('07-b-ticket.md', None, fails)):
                path = self.repo.root.joinpath(*folder, name)
                write_text(path, TICKET_TEXT)
                self.record(reviewed=reviewed, ticket=path)
                results.append(self.check(ticket=path))
        self.assertEqual(passes[0][0], 0, passes[0])
        self.assertEqual(passes[1], passes[0])
        self.assertEqual(fails[0][0], 1, fails[0])
        self.assertEqual(fails[1], fails[0])


class StatOnlyDirtyTest(CheckTestCase):
    """AC-102: `git update-index --refresh` runs before the checks, so a file that is dirty by its stat
    only (same bytes, new modification time; the line-ending case reads the same) cannot make the later
    merge refuse. The check reads git objects only, so the effect shows in the index."""

    def dirty(self):
        return self.repo.git('diff-index', 'HEAD', '--').strip()

    def test_a_file_dirty_by_its_stat_only_is_refreshed_and_a_real_edit_is_not_hidden(self):
        self.record()
        path = self.repo.root / 'src' / 'a.py'
        later = path.stat().st_mtime + 60
        write_text(path, 'code v1\n')   # the same bytes as the commit
        os.utime(path, (later, later))
        self.assertTrue(self.dirty(), 'the fixture should leave the file dirty by its stat only')
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.dirty(), '')
        write_text(path, 'code v2\n')
        self.check()
        self.assertIn('src/a.py', self.dirty())

    def test_a_locked_index_is_one_anomaly_line_and_not_a_pass(self):
        self.record()
        (self.repo.root / '.git' / 'index.lock').write_text('', encoding='utf-8')
        assert_cli_error(self, self.check(), 'update-index')


class AdhocTicketTest(CheckTestCase):
    """AC-7: an adhoc ticket file is checked like any other ticket."""

    def setUp(self):
        super().setUp()
        code, out, err = run_cli('ticket', 'adhoc', 'a small task', '--repo', str(self.repo.root),
                                 '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        self.ticket = Path(out.strip())
        self.assertEqual(self.ticket.parent.name, 'adhoc')

    def test_an_adhoc_ticket_passes(self):
        self.record()
        code, out, err = self.check()
        self.assertEqual((code, err), (0, ''), out)

    def test_an_adhoc_ticket_without_reviewed_fails(self):
        self.record(reviewed=None)
        self.assertTrue(self.problems(self.check())[0].startswith('Reviewed:'))

    def test_an_adhoc_ticket_with_an_edited_test_fails_and_passes_with_a_note(self):
        head = self.edit_test()
        self.record(reviewed=head, verified=head)
        self.assertTrue(self.problems(self.check())[0].startswith('Test:'))
        self.ticket_cmd('red', '--changed', 'why')
        self.assertEqual(self.check()[0], 0)

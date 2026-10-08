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
        self.assertEqual(re.findall(r'^    ([a-z-]+)\s{2,}\S', out.getvalue(), re.M), ['pre-merge', 'stories', 'slice'])

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


GOOD_STORIES = """# A unit
Sources: chat · Gathered: 2026-10-01
Why: a reason
Rules for all stories: none

## 1. As a dev, I want a, so that b.
- AC-1: first criterion
- AC-2: second criterion (verbatim chat)
Amended 2026-10-02: AC-3 withdrawn — not needed

## 2. As a dev, I want c, so that d.
- AC-3: third criterion

## Out of scope
- the thing — owner: ticket 05
"""
GOOD_DECISIONS = """- D-1: pick x. Why: simple. Source: user, 2026-10-01
- D-2: pick y. Why: cheap. Source: docs/formats.md:30 ADR?
- T-1: **term** — a meaning. Avoid: other.
Amended 2026-10-02: reworded
"""
GOOD_LOG = '2026-10-01 10:00 specify: ACs: AC-1, AC-2, AC-3; claim check passed\n'


class CheckStoriesTest(unittest.TestCase):
    """AC-8, AC-9: `check stories <folder>`. Unit API assumed: `check.stories(folder)` takes a Path and
    returns `(errors, warnings)`, two lists of one-line strings. Each error names the file and the line
    (`stories.md:7: ...`) and the allowed shape."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name).resolve() / 'unit'
        self.folder.mkdir()
        self.put(stories=GOOD_STORIES, decisions=GOOD_DECISIONS, log=GOOD_LOG)

    def put(self, **texts):
        for key, name in (('stories', 'stories.md'), ('decisions', 'decisions.md'), ('log', 'log.md')):
            if key in texts:
                write_text(self.folder / name, texts[key])

    def stories(self):
        from anomaly_loop import check
        self.assertTrue(hasattr(check, 'stories'), 'check.stories(folder) -> (errors, warnings) is missing')
        return check.stories(self.folder)

    def assert_error(self, line_number, *fragments, file_name=None):
        errors, _ = self.stories()
        hits = [e for e in errors if re.search(rf':{line_number}\b', e) and (not file_name or file_name in e)]
        self.assertTrue(hits, (line_number, errors))
        for fragment in fragments:
            self.assertTrue(any(fragment in e for e in hits), (fragment, hits))

    def test_good_folder_has_no_errors_and_no_warnings(self):
        self.assertEqual(self.stories(), ([], []))

    def test_a_duplicate_ac_id_is_an_error_naming_the_line(self):
        self.put(stories=GOOD_STORIES.replace('- AC-3: third', '- AC-2: third'))
        self.assert_error(12, 'AC-2', file_name='stories.md')

    def test_an_ac_named_by_an_earlier_specify_line_but_gone_is_an_error(self):
        self.put(stories=GOOD_STORIES.replace('- AC-3: third', '- AC-4: third'))
        errors, _ = self.stories()
        self.assertTrue(any('AC-3' in e and e.startswith('log.md:1:') for e in errors), errors)

    def test_a_decision_without_source_is_an_error_with_the_allowed_shape(self):
        self.put(decisions=GOOD_DECISIONS.replace(' Source: user, 2026-10-01', ''))
        self.assert_error(1, 'Source:', file_name='decisions.md')

    def test_an_out_of_scope_line_without_owner_is_an_error_with_the_allowed_shape(self):
        self.put(stories=GOOD_STORIES.replace(' — owner: ticket 05', ''))
        self.assert_error(15, 'owner:', file_name='stories.md')

    def test_an_out_of_scope_line_whose_owner_is_a_d_n_is_an_error(self):
        for owner in (' — owner: export D-3', ' — owner: D-3'):
            with self.subTest(owner=owner):
                self.put(stories=GOOD_STORIES.replace(' — owner: ticket 05', owner))
                self.assert_error(15, 'owner:', 'D-', file_name='stories.md')

    def test_a_decision_that_leaves_an_item_out_of_scope_with_a_d_n_as_owner_is_an_error(self):
        self.put(decisions=GOOD_DECISIONS + '- D-3: leave xlsx out. Why: later. Source: user, 2026-10-08 — owner: D-3\n')
        self.assert_error(5, 'D-', file_name='decisions.md')

    def test_a_d_n_outside_the_owner_value_of_a_decision_is_not_an_error(self):
        self.put(decisions=GOOD_DECISIONS + '- D-3: the owner: field is required, see D-2. Why: x. '
                 'Source: user, 2026-10-08 — owner: ticket 05\n')
        self.assertEqual(self.stories(), ([], []))

    def test_a_bracketed_d_n_after_an_out_of_scope_owner_is_a_citation_not_an_error(self):
        owners = (
            'owner: phase 2 `workflow-conduct` (D-11)',
            'owner: `anomaly:calibrate` (D-10)',
            'owner: a later work unit, TODO(VK, revisit 2026-11-05) (D-5)',
            'owner: VK, after phase 2 ships (D-3)',
            'owner: ticket 05 [D-3]',
        )
        for owner in owners:
            with self.subTest(owner=owner):
                self.put(stories=GOOD_STORIES.replace('owner: ticket 05', owner))
                self.assertEqual(self.stories(), ([], []))

    def test_a_bracketed_d_n_after_a_decision_owner_is_a_citation_not_an_error(self):
        self.put(decisions=GOOD_DECISIONS + '- D-3: leave xlsx out. Why: later. '
                 'Source: user, 2026-10-08 — owner: ticket 05 (D-2)\n')
        self.assertEqual(self.stories(), ([], []))

    def test_oversize_files_only_warn(self):
        self.put(stories=GOOD_STORIES + 'x' * (6 * 1024), decisions=GOOD_DECISIONS + 'x' * (8 * 1024))
        errors, warnings = self.stories()
        self.assertEqual(errors, [])
        self.assertTrue(any('stories.md' in w for w in warnings), warnings)
        self.assertTrue(any('decisions.md' in w for w in warnings), warnings)

    def test_cli_exit_codes_and_output(self):
        run = lambda: run_cli('check', 'stories', str(self.folder))
        code, out, err = run()
        self.assertEqual((code, err), (0, ''), out)
        self.put(decisions=GOOD_DECISIONS.replace(' Source: user, 2026-10-01', ''))
        code, out, err = run()
        self.assertEqual((code, err), (1, ''), out)
        self.assertIn('decisions.md:1', out)
        self.put(decisions=GOOD_DECISIONS + 'x' * (8 * 1024))
        code, out, err = run()
        self.assertEqual((code, err), (0, ''), out)
        self.assertIn('decisions.md', out)
        assert_cli_error(self, run_cli('check', 'stories', str(self.folder / 'missing')), 'missing')

    def test_a_specify_line_without_the_ids_shape_is_an_error_naming_the_shape(self):
        self.put(log=GOOD_LOG + '2026-10-02 10:00 specify: ACs: AC-1, AC-2 claim check passed\n')
        self.assert_error(2, 'ACs: AC-1, AC-2, …;', file_name='log.md')

    def test_a_missing_stories_file_is_an_error_and_missing_decisions_and_log_are_empty(self):
        (self.folder / 'stories.md').unlink()
        errors, _ = self.stories()
        self.assertEqual(len(errors), 1, errors)
        self.assertTrue(errors[0].startswith('stories.md: '), errors)
        self.put(stories=GOOD_STORIES)
        (self.folder / 'decisions.md').unlink()
        (self.folder / 'log.md').unlink()
        self.assertEqual(self.stories(), ([], []))

    def test_the_shapes_in_the_errors_are_the_text_of_formats_md(self):
        from anomaly_loop import check
        from tests.fixtures import PLUGIN
        formats = (PLUGIN / 'docs' / 'formats.md').read_text(encoding='utf-8')
        shapes = {name: value for name, value in vars(check).items() if name.endswith('_SHAPE')}
        self.assertGreaterEqual(len(shapes), 10)
        for name, shape in shapes.items():
            with self.subTest(name=name):
                self.assertIn(shape, formats)

    def test_a_stories_file_of_exactly_6_kb_does_not_warn(self):
        size = len(GOOD_STORIES.encode('utf-8'))
        self.put(stories=GOOD_STORIES + 'x' * (6 * 1024 - size))
        self.assertEqual((self.folder / 'stories.md').stat().st_size, 6 * 1024)
        self.assertEqual(self.stories(), ([], []))


def slice_ticket(number, covers='AC-1', blocked='none', status='ready-for-agent', jira='no-ticket',
                 tests='unit tests', body=''):
    """A ticket whose lines sit at fixed numbers: Covers 3, Blocked by 4, Status 5, Jira 6, Tests 7."""
    return (f'# {number}: A ticket\n\nCovers: {covers}\nBlocked by: {blocked}\nStatus: {status}\n'
            f'Jira: {jira}\nTests: {tests}\n{body}')


class CheckSliceTest(unittest.TestCase):
    """AC-10, AC-11: `check slice <work-unit folder>`. Unit API assumed: `check.slice(folder)` takes a Path
    and returns `(errors, warnings)` as `check.stories` does. Each error starts `<file>:<line>:` and names
    the allowed shape or values in brackets. Story ACs are the `- AC-<n>:` lines of stories.md."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name).resolve() / 'unit'
        write_text(self.folder / 'stories.md', GOOD_STORIES)
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2'))
        self.put('02-second', slice_ticket('02', covers='AC-3', blocked='01', status='done'))
        self.put('03-third', slice_ticket('03', covers='none', status='ready-for-human (needs a key)'))

    def put(self, slug, text):
        write_text(self.folder / 'tickets' / f'{slug}.md', text)

    def slice(self):
        from anomaly_loop import check
        self.assertTrue(hasattr(check, 'slice'), 'check.slice(folder) -> (errors, warnings) is missing')
        return check.slice(self.folder)

    def assert_error(self, prefix, *fragments):
        errors, _ = self.slice()
        hits = [e for e in errors if re.match(rf'(tickets/)?{re.escape(prefix)}', e)]
        self.assertTrue(hits, (prefix, errors))
        for fragment in fragments:
            self.assertTrue(any(fragment in e for e in hits), (fragment, hits))

    def test_a_clean_set_with_a_covers_none_ticket_has_no_errors_and_no_warnings(self):
        self.assertEqual(self.slice(), ([], []))

    def test_a_story_ac_in_no_covers_line_is_an_error_naming_the_story_line(self):
        self.put('02-second', slice_ticket('02', covers='none', blocked='01'))
        self.assert_error('stories.md:12:', 'AC-3', 'Covers:')

    def test_each_missing_ticket_line_is_an_error_naming_the_file_and_the_allowed_values(self):
        for key, fragment in (('Status', 'ready-for-agent'), ('Blocked by', '01, 03'), ('Covers', 'none'),
                              ('Tests', 'Tests:'), ('Jira', 'no-ticket')):
            with self.subTest(key=key):
                text = slice_ticket('01', covers='AC-1, AC-2')
                self.put('01-first', ''.join(l for l in text.splitlines(True) if not l.startswith(f'{key}:')))
                self.assert_error('01-first.md:', f'{key}:', fragment, '(')
                self.put('01-first', text)

    def test_a_status_outside_the_triage_words_and_run_states_is_an_error_listing_them(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2', status='wip'))
        self.assert_error('01-first.md:5:', 'ready-for-agent', 'ready-for-human', 'in-progress', 'done')

    def test_a_blocker_with_no_ticket_file_is_an_error_on_the_blocked_by_line(self):
        self.put('03-third', slice_ticket('03', covers='none', blocked='09'))
        self.assert_error('03-third.md:4:', '09')

    def test_a_blocker_cycle_is_an_error_naming_the_tickets(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2', blocked='02'))
        errors, _ = self.slice()
        hits = [e for e in errors if 'cycle' in e]
        self.assertTrue(hits, errors)
        self.assertTrue(any('01' in e and '02' in e for e in hits), hits)
        self.assertTrue(all(re.match(r'(tickets/)?\d\d-\w+\.md:4:', e) for e in hits), hits)

    def test_a_path_with_a_line_number_in_the_body_is_an_error_naming_the_line(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2',
                                          body='\nSee plugins/anomaly/anomaly_loop/check.py:42 for it.\n'))
        self.assert_error('01-first.md:9:', 'check.py:42', 'path')

    def test_a_dotted_file_name_with_a_line_number_is_reported_whole(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2',
                                          body='\nSee app.module.ts:5 for it.\n'))
        self.assert_error('01-first.md:9:', 'app.module.ts:5', 'path')

    def test_a_host_and_port_after_a_scheme_or_an_at_sign_is_not_a_path_with_a_line_number(self):
        for host in ('https://example.com:8080', 'postgres://db.internal:5432', 'user@example.co.uk:443'):
            with self.subTest(host=host):
                self.put('01-first', slice_ticket('01', covers='AC-1, AC-2',
                                                  body=f'\nServe it on {host} for the demo.\n'))
                self.assertEqual(self.slice(), ([], []))

    def test_a_path_with_a_line_number_after_a_host_and_port_on_the_same_line_is_reported(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2',
                                          body='\nServe it on https://example.com:8080, see check.py:42.\n'))
        self.assert_error('01-first.md:9:', 'check.py:42', 'path')

    def test_a_bare_name_with_a_known_host_suffix_and_a_line_number_is_reported(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2',
                                          body='\nSee notes.org:12 for it.\n'))
        self.assert_error('01-first.md:9:', 'notes.org:12', 'path')

    def test_line_anchor_is_linear_on_a_very_long_line_and_keeps_its_anchors(self):
        """Adhoc 2026-10-08-review-security-lows, AC-1: no retry at every start position (Nit)."""
        import time
        from anomaly_loop import check
        started = time.perf_counter()
        self.assertIsNone(check.line_anchor('a.a/' * 8000))
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertTrue(check.line_anchor('see .eslintrc.js:4').group(0).endswith('eslintrc.js:4'))
        self.assertTrue(check.line_anchor('/abs/p.py:9').group(0).endswith('p.py:9'))
        self.assertIsNone(check.line_anchor('https://h/x/check.py:42'))

    def test_an_oversize_ticket_only_warns(self):
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2', body='x' * (5 * 1024)))
        errors, warnings = self.slice()
        self.assertEqual(errors, [])
        self.assertTrue(any('01-first.md' in w for w in warnings), warnings)

    def test_cli_exit_codes_and_output(self):
        run = lambda: run_cli('check', 'slice', str(self.folder))
        code, out, err = run()
        self.assertEqual((code, err), (0, ''), out)
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2', body='x' * (5 * 1024)))
        code, out, err = run()
        self.assertEqual((code, err), (0, ''), out)
        self.assertIn('warning: ', out)
        self.put('03-third', slice_ticket('03', covers='none', blocked='09'))
        code, out, err = run()
        self.assertEqual((code, err), (1, ''), out)
        self.assertIn('03-third.md:4:', out)

    def test_a_line_anchor_in_a_fenced_block_or_a_copied_decision_line_is_not_an_error(self):
        body = '\n- D-3: x. Why: y. Source: a.py:3\n```\na.py:10\n```\nSee ticket.py:199 here.\n'
        self.put('01-first', slice_ticket('01', covers='AC-1, AC-2', body=body))
        errors, _ = self.slice()
        self.assertEqual(len(errors), 1, errors)
        self.assertTrue(errors[0].startswith('tickets/01-first.md:13:'), errors)

    def test_an_unreadable_blocked_by_value_is_an_error_on_its_line(self):
        self.put('03-third', slice_ticket('03', covers='none', blocked='soon'))
        self.assert_error('03-third.md:4:', 'soon', 'Blocked by: none | 01, 03')

    def test_a_missing_stories_file_is_an_error(self):
        (self.folder / 'stories.md').unlink()
        self.assert_error('stories.md:', 'missing')

    def test_a_missing_folder_is_a_cli_error(self):
        assert_cli_error(self, run_cli('check', 'slice', str(self.folder / 'missing')), 'missing')

    def test_an_empty_tests_or_jira_value_is_an_error_on_its_own_line(self):
        for key, line in (('Tests', 7), ('Jira', 6)):
            with self.subTest(key=key):
                self.put('01-first', slice_ticket('01', covers='AC-1, AC-2', **{key.lower(): ''}))
                self.assert_error(f'01-first.md:{line}:', f'{key}: is empty')

    def test_ready_for_human_without_a_reason_is_an_error_quoting_the_value(self):
        self.put('03-third', slice_ticket('03', covers='none', status='ready-for-human'))
        self.assert_error('03-third.md:5:', '"ready-for-human"', '(<why>)')

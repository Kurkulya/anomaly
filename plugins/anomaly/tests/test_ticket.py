"""The ticket commands through the CLI, in-process, against a temp `.anomaly`: show, gate, set-status, result,
reviewed, verified, red and adhoc.
Edits are checked as exact bytes: only the named lines change."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import check, cli, privacy, ticket
from anomaly_loop.constants import MODEL_ROLES, TICKET_TITLE_MAX_CHARS
from tests.fixtures import GitFixture, assert_cli_error, run_cli, write_text

NOW_DATE = date(2026, 10, 4)
SHARED_COMMITS = 3   # real commits of the one repository every test reads (no test changes it)
TICKET_TEXT = """# 02: Ticket commands

Key: no-ticket
Covers: AC-1, AC-2
**Blocked by:** None (can start immediately)
Status: ready-for-agent
Tests: unit (CLI in-process)

**What to build:** every ticket edit goes through the CLI.

- [ ] AC-1: first criterion
- [ ] AC-2: second criterion
- [ ] AC-3: not covered by this ticket

Amended 2026-10-04 (orchestrator): a later decision.
"""


def blocked_ticket(line):
    return TICKET_TEXT.replace('**Blocked by:** None (can start immediately)', line)


def setUpModule():
    global SHARED_FOLDER, SHARED_REPO, SHARED_IDS
    SHARED_FOLDER = tempfile.TemporaryDirectory()
    SHARED_REPO = GitFixture(Path(SHARED_FOLDER.name) / 'commit-repo')
    SHARED_IDS = []
    for number in range(SHARED_COMMITS):
        SHARED_REPO.write('a.txt', f'{number}\n')
        SHARED_IDS.append(SHARED_REPO.commit(['a.txt'], f'commit {number}', NOW_DATE))


def tearDownModule():
    SHARED_FOLDER.cleanup()


class TicketTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.tickets_dir = self.root / '.anomaly' / 'unit' / 'tickets'

    def ticket_path(self, text=TICKET_TEXT, name='02-ticket-commands.md'):
        path = self.tickets_dir / name
        write_text(path, text)
        return path

    def run_ticket(self, *argv):
        return run_cli('ticket', *argv, '--home', str(self.home))

    def merge_args(self):
        """`--merge <full id> --repo <folder>` of a real commit: `ticket result` resolves --merge through git."""
        return '--merge', SHARED_IDS[0], '--repo', str(SHARED_REPO.root)

    def commits(self, count=1):
        """`(ids, ('--repo', folder))`: `count` full ids of real commits in the shared temp repository, for
        the commands that resolve a sha through git (`reviewed`, `verified`, `red`)."""
        return SHARED_IDS[:count], ('--repo', str(SHARED_REPO.root))

    def read(self, path):
        return Path(path).read_bytes().decode('utf-8')

    def assert_error(self, result, *fragments):
        assert_cli_error(self, result, *fragments)


class RegistryTest(TicketTestCase):
    def test_ticket_is_registered_once_and_lists_every_action(self):
        self.assertEqual(cli.COMMANDS.count('ticket'), 1)
        actions = ('show', 'gate', 'set-status', 'result', 'reviewed', 'verified', 'adhoc', 'red', 'amend')
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(['ticket', '--help'], environ={})
        listed = re.findall(r'^    ([a-z-]+)\s{2,}\S', out.getvalue(), re.M)
        self.assertEqual(sorted(listed), sorted(actions))

    def test_a_failure_prints_one_anomaly_line_and_exits_2(self):
        missing = self.tickets_dir / '99-none.md'
        result = self.run_ticket('show', str(missing))
        self.assert_error(result, '99-none.md')
        self.assertEqual(result[2].count('99-none.md'), 1, result[2])

    def test_a_missing_action_is_a_usage_error_on_one_line(self):
        self.assert_error(self.run_ticket())

    def test_a_ticket_path_of_a_dash_is_refused_and_no_file_is_made(self):
        folder = self.root / 'cwd'
        folder.mkdir()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(folder)
        empty = io.TextIOWrapper(io.BytesIO(b''))
        for argv in (('show', '-'), ('gate', '-'), ('set-status', '-', 'done'), ('reviewed', '-', 'abc1234'),
                     ('red', '-', '--changed', 'why'),
                     ('result', '-', '--branch', 'b', *self.merge_args(), '--changed-lines', '1')):
            with self.subTest(argv=argv[0]), mock.patch('sys.stdin', empty):
                self.assert_error(self.run_ticket(*argv), 'standard input')
        self.assertEqual(list(folder.iterdir()), [])


class ShowTest(TicketTestCase):
    def test_prints_the_state_lines_in_a_fixed_order(self):
        """`Base:` (the integration branch, plain or bold) is shown too: build reads it through `ticket show`."""
        path = self.ticket_path(TICKET_TEXT.replace(
            'Tests: unit (CLI in-process)', 'Reviewed: abc1234\nTests: unit\n**Base:** feat/workflow-build\nVerified: def5678'))
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(out.splitlines(), [
            'Status: ready-for-agent', 'Blocked by: None (can start immediately)', 'Covers: AC-1, AC-2',
            'Key: no-ticket', 'Tests: unit', 'Model: implement', 'Base: feat/workflow-build', 'Reviewed: abc1234',
            'Verified: def5678'])

    def test_prints_the_model_line(self):
        """AC-16: the slot of `Model:` among the state lines is free; the other lines keep their order."""
        path = self.ticket_path(TICKET_TEXT.replace('Tests: unit (CLI in-process)',
                                                    'Tests: unit\nModel: implement_wide'))
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual((code, err), (0, ''))
        shown = out.splitlines()
        self.assertIn('Model: implement_wide', shown)
        self.assertEqual([line for line in shown if not line.startswith('Model:')], [
            'Status: ready-for-agent', 'Blocked by: None (can start immediately)', 'Covers: AC-1, AC-2',
            'Key: no-ticket', 'Tests: unit'])
        # Amended 2026-10-10 (cumulative review): the resolved line, so build and conduct read the role from the CLI
        code, out, err = self.run_ticket('show', str(self.ticket_path(TICKET_TEXT, name='03-no-model.md')))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual([line for line in out.splitlines() if line.startswith('Model:')], ['Model: implement'])

    def test_reads_status_and_blocked_by_in_bold_form(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent', '**Status:** in-progress') \
                          .replace('**Blocked by:** None (can start immediately)', '**Blocked by:** 01, 03')
        out = self.run_ticket('show', str(self.ticket_path(text)))[1]
        self.assertIn('Status: in-progress', out.splitlines())
        self.assertIn('Blocked by: 01, 03', out.splitlines())

    def test_reads_blocked_by_in_plain_form(self):
        out = self.run_ticket('show', str(self.ticket_path(blocked_ticket('Blocked by: 01, 03'))))[1]
        self.assertIn('Blocked by: 01, 03', out.splitlines())
        self.assertNotIn('warning', out)

    def test_warns_when_there_is_no_blocked_by_line(self):
        path = self.ticket_path(TICKET_TEXT.replace('**Blocked by:** None (can start immediately)\n', ''))
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual(code, 0, err)
        warnings = [line for line in out.splitlines() if line.startswith('warning:')]
        self.assertEqual(len(warnings), 1)
        self.assertIn('Blocked by:', warnings[0])
        self.assertNotIn('Blocked by: ', ''.join(line for line in out.splitlines() if not line.startswith('warning')))

    def test_a_ticket_without_status_covers_or_tests_still_shows(self):
        path = self.ticket_path('# 05: Old ticket\n\nKey: none\n**Blocked by:** 01\n')
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(out.splitlines(), ['Blocked by: 01', 'Key: none', 'Model: implement'])

    def test_prints_the_repro_line(self):
        """AC-26: a light-path ticket's `Repro:` line is shown, so `build` reads the command from `ticket show`."""
        repro = 'Repro: python3 -m unittest tests.test_x'
        path = self.ticket_path(TICKET_TEXT.replace('Tests: unit (CLI in-process)',
                                                    f'Tests: unit (CLI in-process)\n{repro}'))
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual((code, err), (0, ''))
        self.assertIn(repro, out.splitlines())

    def test_prints_the_key_line_that_a_ticket_has_and_not_a_jira_line(self):
        """AC-9: the core key line is `Key:`. A `Jira:` line is no longer read in its place (ADR-0017)."""
        path = self.ticket_path(TICKET_TEXT.replace('Key: no-ticket', 'Key: ABC-1'))
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('Key: ABC-1', out.splitlines())
        jira = self.ticket_path(TICKET_TEXT.replace('Key: no-ticket', 'Jira: ABC-2'), name='03-jira.md')
        code, out, err = self.run_ticket('show', str(jira))
        self.assertEqual((code, err), (0, ''))
        self.assertFalse([line for line in out.splitlines() if line.startswith(('Jira', 'Key'))], out)

    def test_prints_the_line_that_the_key_line_port_names(self):
        """AC-9: the profile key `key_line` names the line; a `Key:` line is then not shown."""
        write_text(self.home / 'profile.md', '---\nkey_line: Story\n---\n')
        story = self.ticket_path(TICKET_TEXT.replace('Key: no-ticket', 'Story: ABC-3\nKey: ABC-1'))
        out = self.run_ticket('show', str(story))[1].splitlines()
        self.assertIn('Story: ABC-3', out)
        self.assertNotIn('Key: ABC-1', out)


class GateTest(TicketTestCase):
    def write_blockers(self, **statuses):
        for number, status in statuses.items():
            name = f'{number[1:]}-blocker.md'
            self.ticket_path(f'# {number[1:]}: A blocker\n\nStatus: {status}\n', name=name)

    def test_exits_0_when_every_blocker_is_done(self):
        self.write_blockers(b01='done', b03='done')
        path = self.ticket_path(blocked_ticket('**Blocked by:** 01, 03'))
        code, out, err = self.run_ticket('gate', str(path))
        self.assertEqual((code, err), (0, ''))
        self.assertNotIn('blocked by', out)

    def test_a_ticket_that_waits_for_a_person_exits_1_and_says_so_when_it_has_no_open_blocker(self):
        """AC-26 (Amended, cumulative review): conduct never builds a ready-for-human, needs-info or wontfix ticket;
        a ready-for-agent one with no open blocker passes."""
        for status in ('ready-for-human', 'needs-info', 'wontfix'):
            with self.subTest(status=status):
                path = self.ticket_path(TICKET_TEXT.replace('Status: ready-for-agent', f'Status: {status}'))
                code, out, err = self.run_ticket('gate', str(path))
                self.assertEqual((code, err), (1, ''))
                self.assertIn('person', out.lower())
        path = self.ticket_path(TICKET_TEXT)
        self.assertEqual(self.run_ticket('gate', str(path))[:2], (0, ''))

    def test_a_status_that_is_not_ready_for_agent_exits_1_and_names_the_status(self):
        """AC-26 (Amended, allow list): only a ready-for-agent ticket starts, so a typo or a missing Status: line
        waits too. An in-progress ticket (a resume) still passes."""
        for status in ('ready-for-agnet', 'unknown'):
            with self.subTest(status=status):
                path = self.ticket_path(TICKET_TEXT.replace('Status: ready-for-agent', f'Status: {status}'))
                code, out, err = self.run_ticket('gate', str(path))
                self.assertEqual((code, err), (1, ''))
                self.assertIn(status, out)
                self.assertIn('is not ready-for-agent', out)
        path = self.ticket_path(TICKET_TEXT.replace('Status: ready-for-agent', 'Status: in-progress'))
        self.assertEqual(self.run_ticket('gate', str(path))[:2], (0, ''))

    def test_names_each_blocker_that_is_not_done_and_exits_1(self):
        self.write_blockers(b01='done', b03='in-progress', b04='ready-for-agent')
        path = self.ticket_path(blocked_ticket('**Blocked by:** 01, 03, 04'))
        code, out, err = self.run_ticket('gate', str(path))
        self.assertEqual((code, err), (1, ''))
        lines = out.splitlines()
        self.assertEqual(len(lines), 2, out)
        self.assertIn('03', lines[0])
        self.assertIn('in-progress', lines[0])
        self.assertIn('04', lines[1])
        self.assertIn('ready-for-agent', lines[1])

    def test_plain_and_bold_blocked_by_give_the_same_result(self):
        self.write_blockers(b01='done', b03='in-progress')
        results = []
        for number, line in enumerate(('**Blocked by:** 01, 03', 'Blocked by: 01, 03')):
            path = self.ticket_path(blocked_ticket(line), name=f'0{number + 5}-x.md')
            results.append(self.run_ticket('gate', str(path)))
        self.assertEqual(results[0][:2], results[1][:2])
        self.assertEqual(results[0][0], 1)

    def test_a_blocker_without_a_ticket_file_counts_as_not_done(self):
        path = self.ticket_path(blocked_ticket('Blocked by: 07'))
        code, out, err = self.run_ticket('gate', str(path))
        self.assertEqual(code, 1, err)
        self.assertIn('07', out)

    def test_none_and_parenthesised_titles_are_not_blockers(self):
        self.write_blockers(b02='done')
        for line in ('**Blocked by:** None', 'Blocked by: none', 'Blocked by: 02 (React 19.3 upgrade)'):
            with self.subTest(line=line):
                path = self.ticket_path(blocked_ticket(line))
                self.assertEqual(self.run_ticket('gate', str(path))[0], 0)

    def test_a_ticket_with_no_blocked_by_line_warns_and_passes(self):
        path = self.ticket_path(TICKET_TEXT.replace('**Blocked by:** None (can start immediately)\n', ''))
        code, out, err = self.run_ticket('gate', str(path))
        self.assertEqual((code, err), (0, ''))
        self.assertTrue(out.startswith('warning:'), out)

    def test_an_unreadable_blocker_status_counts_as_not_done(self):
        self.ticket_path('# 01: No status\n\nKey: none\n', name='01-blocker.md')
        path = self.ticket_path(blocked_ticket('Blocked by: 01'))
        code, out, err = self.run_ticket('gate', str(path))
        self.assertEqual(code, 1, err)
        self.assertIn('unknown', out)

    def test_a_blocked_by_value_that_names_no_ticket_number_warns_and_fails(self):
        for line in ('Blocked by: 101', 'Blocked by: 1, 3', '**Blocked by:** soon', 'Blocked by:',
                     'Blocked by: ٠٧'):
            with self.subTest(line=line):
                code, out, err = self.run_ticket('gate', str(self.ticket_path(blocked_ticket(line))))
                self.assertEqual((code, err), (1, ''))
                self.assertTrue(out.startswith('warning:'), out)
                self.assertIn('Blocked by', out)

    def test_a_number_that_is_not_two_digits_next_to_a_good_one_is_not_dropped_silently(self):
        self.ticket_path('# 02: Done\n\nStatus: done\n', name='02-blocker.md')
        for line in ('Blocked by: 02, 101', 'Blocked by: 02, 3 (a title with 7)', '**Blocked by:** 02, ABC-123'):
            with self.subTest(line=line):
                path = self.ticket_path(blocked_ticket(line))
                code, out, err = self.run_ticket('gate', str(path))
                self.assertEqual((code, err), (1, ''))
                self.assertTrue(out.startswith('warning:'), out)
                self.assertEqual(len(out.splitlines()), 1, out)

    def test_numbers_inside_parentheses_are_titles_and_do_not_warn(self):
        self.ticket_path('# 02: Done\n\nStatus: done\n', name='02-blocker.md')
        path = self.ticket_path(blocked_ticket('Blocked by: 02 (the 2026 rewrite, 100 items)'))
        self.assertEqual(self.run_ticket('gate', str(path))[:2], (0, ''))

    def test_show_prints_the_same_warning(self):
        path = self.ticket_path(blocked_ticket('Blocked by: 02, 101'))
        out = self.run_ticket('show', str(path))[1].splitlines()
        self.assertEqual(sum(line.startswith('warning:') for line in out), 1, out)
        self.assertIn('Blocked by: 02, 101', out)


class SetStatusTest(TicketTestCase):
    def test_rewrites_only_the_status_line(self):
        path = self.ticket_path()
        code, out, err = self.run_ticket('set-status', str(path), 'ready-for-human')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), TICKET_TEXT.replace('Status: ready-for-agent', 'Status: ready-for-human'))

    def test_in_progress_also_writes_metrics_started_from_the_injected_clock(self):
        path = self.ticket_path()
        self.run_ticket('set-status', str(path), 'in-progress')
        self.assertEqual(self.read(path), TICKET_TEXT.replace(
            'Status: ready-for-agent', 'Status: in-progress\nMetrics: started 2026-10-04 12:00'))

    def test_a_bold_status_line_stays_bold(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent', '**Status:** ready-for-agent')
        path = self.ticket_path(text)
        self.run_ticket('set-status', str(path), 'done')
        self.assertEqual(self.read(path), text.replace('ready-for-agent', 'done'))

    def test_crlf_line_endings_are_kept_byte_for_byte(self):
        crlf = TICKET_TEXT.replace('\n', '\r\n').encode('utf-8')
        path = self.tickets_dir / '02-crlf.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(crlf)
        self.run_ticket('set-status', str(path), 'in-progress')
        self.assertEqual(path.read_bytes(), crlf.replace(
            b'Status: ready-for-agent', b'Status: in-progress\r\nMetrics: started 2026-10-04 12:00'))

    def test_a_missing_final_newline_stays_missing(self):
        text = TICKET_TEXT.rstrip('\n')
        path = self.ticket_path(text)
        self.run_ticket('set-status', str(path), 'done')
        self.assertEqual(self.read(path), text.replace('ready-for-agent', 'done'))

    def test_starting_again_keeps_the_first_start_time(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent',
                                   'Status: in-progress\nMetrics: started 2026-10-03 09:30')
        path = self.ticket_path(text)
        self.run_ticket('set-status', str(path), 'in-progress')
        self.assertEqual(self.read(path), text)

    def test_reopening_a_ticket_closed_with_started_unknown_keeps_its_counts_and_takes_the_new_start(self):
        closed = TICKET_TEXT.replace('Status: ready-for-agent', (
            'Status: done\nMetrics: started unknown · merged 2026-10-04 11:30 · full suites 1 · changed lines 9'))
        path = self.ticket_path(closed)
        self.run_ticket('set-status', str(path), 'in-progress')
        reopened = TICKET_TEXT.replace('Status: ready-for-agent', (
            'Status: in-progress\nMetrics: started 2026-10-04 12:00 · merged 2026-10-04 11:30 · full suites 1 '
            '· changed lines 9'))
        self.assertEqual(self.read(path), reopened)
        self.run_ticket('set-status', str(path), 'in-progress')
        self.assertEqual(self.read(path), reopened)

    def test_other_statuses_write_no_metrics_line(self):
        path = self.ticket_path()
        self.run_ticket('set-status', str(path), 'ready-for-human')
        self.assertNotIn('Metrics:', self.read(path))

    def test_a_status_that_is_not_one_word_is_refused_and_nothing_changes(self):
        path = self.ticket_path()
        self.assert_error(self.run_ticket('set-status', str(path), 'in progress'), 'status')
        self.assertEqual(self.read(path), TICKET_TEXT)

    def test_a_ticket_without_a_status_line_is_refused_by_every_line_writer(self):
        """A file with no Status: line is no ticket (a wrong path), so no ticket line is written into it."""
        text = TICKET_TEXT.replace('Status: ready-for-agent\n', '')
        path = self.ticket_path(text)
        (one,), repo = self.commits()
        for argv in (('set-status', 'done'), ('reviewed', one, *repo), ('verified', one, *repo),
                     ('red', one, 'tests/test_a.py', *repo), ('red', '--changed', 'why')):
            with self.subTest(argv=argv[0:2]):
                self.assert_error(self.run_ticket(argv[0], str(path), *argv[1:]), 'Status:')
        self.assertEqual(self.read(path), text)


STORIES_TEXT = """# Stories

- AC-1: first criterion
- AC-2: second criterion
- AC-10: tenth criterion
"""
DECISIONS_TEXT = """# Decisions

- D-1: first decision. Why: a reason.
  Amended 2026-10-01: an older note.
  Amended 2026-10-02: a newer note.
- D-2: second decision. Why: another reason.
"""
AMEND_NOTE = 'AC-2 now also covers the retry'


class AmendTest(TicketTestCase):
    def unit_file(self, name, text):
        path = self.root / '.anomaly' / 'feature' / name
        write_text(path, text)
        return path

    def test_appends_a_dated_amended_line_to_a_ticket_file_with_the_date_of_the_cli_clock(self):
        path = self.ticket_path()
        code, out, err = self.run_ticket('amend', str(path), AMEND_NOTE)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), TICKET_TEXT + f'Amended 2026-10-04: {AMEND_NOTE}\n')

    def test_after_an_ac_writes_the_line_right_below_that_ac_line_in_stories(self):
        path = self.unit_file('stories.md', STORIES_TEXT)
        code, out, err = self.run_ticket('amend', str(path), '--after', 'AC-1', AMEND_NOTE)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), STORIES_TEXT.replace(
            '- AC-2:', f'Amended 2026-10-04: {AMEND_NOTE}\n- AC-2:'))

    def test_an_ac_line_inside_a_fenced_block_is_an_example_and_is_not_the_target(self):
        fenced = '```\n- AC-1: an example\n```\n'
        path = self.unit_file('stories.md', STORIES_TEXT.replace('- AC-1:', fenced + '- AC-1:'))
        code, out, err = self.run_ticket('amend', str(path), '--after', 'AC-1', AMEND_NOTE)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), STORIES_TEXT.replace(
            '- AC-1: first criterion\n', f'{fenced}- AC-1: first criterion\nAmended 2026-10-04: {AMEND_NOTE}\n'))

    def test_after_a_decision_writes_the_line_below_the_amended_lines_already_under_it(self):
        path = self.unit_file('decisions.md', DECISIONS_TEXT)
        code, out, err = self.run_ticket('amend', str(path), '--after', 'D-1', AMEND_NOTE)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), DECISIONS_TEXT.replace(
            '- D-2:', f'  Amended 2026-10-04: {AMEND_NOTE}\n- D-2:'))

    def test_after_a_decision_with_no_amended_line_indents_the_line_by_two_spaces(self):
        path = self.unit_file('decisions.md', DECISIONS_TEXT)
        code, out, err = self.run_ticket('amend', str(path), '--after', 'D-2', AMEND_NOTE)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), DECISIONS_TEXT + f'  Amended 2026-10-04: {AMEND_NOTE}\n')

    def test_an_id_that_is_no_ac_or_decision_is_refused_and_the_file_is_unchanged(self):
        path = self.unit_file('stories.md', STORIES_TEXT)
        for bad in ('X-1', 'AC-', 'D1'):
            with self.subTest(id=bad):
                self.assert_error(self.run_ticket('amend', str(path), '--after', bad, AMEND_NOTE), bad)
                self.assertEqual(path.read_bytes(), STORIES_TEXT.encode('utf-8'))

    def test_an_id_that_is_not_in_the_file_is_refused_and_the_file_is_unchanged(self):
        """`AC-1` is not found by the line of `AC-10`, nor `D-1` by `D-10`: an id matches whole."""
        cases = (('stories.md', STORIES_TEXT.replace('- AC-1: first criterion\n', ''), 'AC-1'),
                 ('stories.md', STORIES_TEXT, 'AC-3'),
                 ('decisions.md', DECISIONS_TEXT.replace('D-1:', 'D-10:'), 'D-1'),
                 ('decisions.md', DECISIONS_TEXT, 'D-9'))
        for name, text, missing in cases:
            with self.subTest(file=name, id=missing):
                path = self.unit_file(name, text)
                self.assert_error(self.run_ticket('amend', str(path), '--after', missing, AMEND_NOTE), missing)
                self.assertEqual(path.read_bytes(), text.encode('utf-8'))

    def test_a_text_that_fails_the_privacy_check_is_refused_and_the_file_is_unchanged(self):
        stories = self.unit_file('stories.md', STORIES_TEXT)
        ticket_file = self.ticket_path()
        for path, text, extra in ((ticket_file, TICKET_TEXT, ()), (stories, STORIES_TEXT, ('--after', 'AC-1'))):
            with self.subTest(file=path.name):
                result = self.run_ticket('amend', str(path), *extra, 'ask kim.lee@example.com about it')
                self.assert_error(result, 'email address')
                self.assertEqual(path.read_bytes(), text.encode('utf-8'))

    def test_a_text_with_a_line_break_is_refused_and_the_file_is_unchanged(self):
        stories = self.unit_file('stories.md', STORIES_TEXT)
        ticket_file = self.ticket_path()
        for path, text, extra in ((ticket_file, TICKET_TEXT, ()), (stories, STORIES_TEXT, ('--after', 'AC-1'))):
            for text_with_break in ('first\nStatus: done', 'first\r\nsecond'):
                with self.subTest(file=path.name, text=text_with_break):
                    result = self.run_ticket('amend', str(path), *extra, text_with_break)
                    self.assert_error(result, 'line')
                    self.assertEqual(path.read_bytes(), text.encode('utf-8'))


class ReviewedVerifiedTest(TicketTestCase):
    def test_adds_one_line_after_the_status_block(self):
        path = self.ticket_path()
        (one,), repo = self.commits()
        code, out, err = self.run_ticket('reviewed', str(path), one, *repo)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), TICKET_TEXT.replace(
            'Status: ready-for-agent', f'Status: ready-for-agent\nReviewed: {one}'))

    def test_verified_goes_after_reviewed_and_after_metrics(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent',
                                   'Status: in-progress\nMetrics: started 2026-10-04 11:00')
        path = self.ticket_path(text)
        (one, two), repo = self.commits(2)
        self.run_ticket('verified', str(path), two, *repo)
        self.run_ticket('reviewed', str(path), one, *repo)
        self.assertEqual(self.read(path), text.replace(
            'Metrics: started 2026-10-04 11:00',
            f'Metrics: started 2026-10-04 11:00\nReviewed: {one}\nVerified: {two}'))

    def test_a_second_run_replaces_the_line_instead_of_adding_one(self):
        path = self.ticket_path()
        (one, two), repo = self.commits(2)
        self.run_ticket('reviewed', str(path), one, *repo)
        self.run_ticket('reviewed', str(path), two, *repo)
        self.assertEqual(self.read(path).count('Reviewed:'), 1)
        self.assertIn(f'\nReviewed: {two}\n', self.read(path))

    def test_a_bold_line_keeps_its_bold_shape_when_replaced(self):
        text = TICKET_TEXT.replace('Tests: unit (CLI in-process)', '**Verified:** 0000000\nTests: unit')
        path = self.ticket_path(text)
        (one,), repo = self.commits()
        self.run_ticket('verified', str(path), one, *repo)
        self.assertEqual(self.read(path), text.replace('0000000', one))

    def test_a_ticket_without_these_lines_parses_in_every_ticket_command(self):
        path = self.ticket_path()
        for argv in (('show', str(path)), ('gate', str(path))):
            with self.subTest(argv=argv[0]):
                self.assertEqual(self.run_ticket(*argv)[0], 0)

    def test_a_sha_that_is_not_hex_is_refused(self):
        path = self.ticket_path()
        self.assert_error(self.run_ticket('reviewed', str(path), 'not a sha'), 'sha')
        self.assert_error(self.run_ticket('verified', str(path), 'HEAD'), 'sha')
        self.assertEqual(self.read(path), TICKET_TEXT)

    def test_a_sha_that_names_no_commit_is_refused_and_a_short_one_is_written_in_full(self):
        (full,), (_, folder) = self.commits()
        typo = ('0' if full[0] != '0' else '1') + full[1:8]   # the dogfood case: a mistyped short id
        path = self.ticket_path()
        for argv in (('reviewed', str(path), typo), ('verified', str(path), typo),
                     ('red', str(path), typo, 'tests/test_ticket.py')):
            with self.subTest(argv=argv[0]):
                self.assert_error(self.run_ticket(*argv, '--repo', folder), str(path), ticket.not_a_commit(typo))
                self.assertEqual(self.read(path), TICKET_TEXT)
        self.run_ticket('reviewed', str(path), full[:8], '--repo', folder)
        self.run_ticket('verified', str(path), full[:8], '--repo', folder)
        self.run_ticket('red', str(path), full[:8], 'tests/test_ticket.py', '--repo', folder)
        text = self.read(path)
        for key in ('Reviewed', 'Verified'):
            self.assertIn(f'\n{key}: {full}\n', text)
        self.assertIn(f'\nRed: {full} · tests/test_ticket.py\n', text)

    def test_crlf_files_get_crlf_lines(self):
        crlf = TICKET_TEXT.replace('\n', '\r\n').encode('utf-8')
        path = self.tickets_dir / '02-crlf.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(crlf)
        (one,), repo = self.commits()
        self.run_ticket('reviewed', str(path), one, *repo)
        self.assertEqual(path.read_bytes(), crlf.replace(
            b'Status: ready-for-agent', f'Status: ready-for-agent\r\nReviewed: {one}'.encode('ascii')))


class RedTest(TicketTestCase):
    def test_records_the_red_commit_and_the_test_path(self):
        path = self.ticket_path()
        (one,), repo = self.commits()
        code, out, err = self.run_ticket('red', str(path), one, 'tests/test_ticket.py', *repo)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), TICKET_TEXT.replace(
            'Status: ready-for-agent', f'Status: ready-for-agent\nRed: {one} · tests/test_ticket.py'))

    def test_a_second_red_step_replaces_the_line(self):
        path = self.ticket_path()
        (one, two), repo = self.commits(2)
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.run_ticket('red', str(path), two, 'tests/test_b.py', *repo)
        text = self.read(path)
        self.assertEqual(text.count('Red:'), 1)
        self.assertIn(f'\nRed: {two} · tests/test_b.py\n', text)

    def test_changed_writes_a_red_changed_line_after_the_red_line(self):
        path = self.ticket_path()
        (one,), repo = self.commits()
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.assert_error(self.run_ticket('red', str(path), '--changed', 'a reason', *repo), '--repo')
        self.assertNotIn('Red-changed', self.read(path))
        code, out, err = self.run_ticket('red', str(path), '--changed', 'the criterion was ambiguous')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(path), TICKET_TEXT.replace(
            'Status: ready-for-agent',
            f'Status: ready-for-agent\nRed: {one} · tests/test_a.py\nRed-changed: the criterion was ambiguous'))

    def test_each_reason_is_kept_as_its_own_line(self):
        path = self.ticket_path()
        self.run_ticket('red', str(path), '--changed', 'first reason')
        self.run_ticket('red', str(path), '--changed', 'second reason')
        lines = self.read(path).splitlines()
        self.assertEqual([line for line in lines if line.startswith('Red-changed:')],
                         ['Red-changed: first reason', 'Red-changed: second reason'])

    def test_a_different_red_sha_removes_the_earlier_red_changed_lines_and_nothing_else(self):
        path = self.ticket_path()
        (one, two), repo = self.commits(2)
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.run_ticket('red', str(path), '--changed', 'first reason')
        self.run_ticket('red', str(path), '--changed', 'second reason')
        self.assertEqual(self.run_ticket('red', str(path), two, 'tests/test_a.py', *repo)[0], 0)
        self.assertEqual(self.read(path), TICKET_TEXT.replace(
            'Status: ready-for-agent', f'Status: ready-for-agent\nRed: {two} · tests/test_a.py'))

    def test_the_same_red_sha_recorded_again_keeps_the_red_changed_lines(self):
        path = self.ticket_path()
        (one,), repo = self.commits()
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.run_ticket('red', str(path), '--changed', 'a reason')
        self.run_ticket('red', str(path), one, 'tests/test_b.py', *repo)
        text = self.read(path)
        self.assertIn(f'\nRed: {one} · tests/test_b.py\nRed-changed: a reason\n', text)

    def test_a_short_and_a_full_id_of_the_same_commit_count_as_the_same_sha_in_both_orders(self):
        (full,), repo = self.commits()
        short = full[:7]
        for written, given in ((short, full), (full, short), (short, full[:11])):
            with self.subTest(written=len(written), given=len(given)):
                path = self.ticket_path(TICKET_TEXT.replace(
                    'Status: ready-for-agent',
                    f'Status: ready-for-agent\nRed: {written} · tests/test_a.py\nRed-changed: a reason'))
                self.run_ticket('red', str(path), given, 'tests/test_a.py', *repo)
                text = self.read(path)
                self.assertIn(f'\nRed: {full} · tests/test_a.py\nRed-changed: a reason\n', text)

    def test_the_first_red_sha_drops_notes_written_before_it(self):
        path = self.ticket_path()
        (one,), repo = self.commits()
        self.run_ticket('red', str(path), '--changed', 'no acceptance test yet')
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.assertEqual(self.read(path), TICKET_TEXT.replace(
            'Status: ready-for-agent', f'Status: ready-for-agent\nRed: {one} · tests/test_a.py'))

    def test_removing_the_last_line_keeps_a_missing_final_newline_missing(self):
        (one,), repo = self.commits()
        text = '# 02: T\n\nStatus: ready-for-agent\nRed: abc1234 · tests/test_a.py\nRed-changed: why'
        path = self.ticket_path(text)
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.assertEqual(self.read(path), f'# 02: T\n\nStatus: ready-for-agent\nRed: {one} · tests/test_a.py')

    def test_show_prints_the_red_lines(self):
        path = self.ticket_path()
        (one,), repo = self.commits()
        self.run_ticket('red', str(path), one, 'tests/test_a.py', *repo)
        self.run_ticket('red', str(path), '--changed', 'why')
        out = self.run_ticket('show', str(path))[1].splitlines()
        self.assertIn(f'Red: {one} · tests/test_a.py', out)
        self.assertIn('Red-changed: why', out)

    def test_changed_cannot_be_combined_with_a_commit_and_a_path(self):
        path = self.ticket_path()
        self.assert_error(self.run_ticket('red', str(path), 'abc1234', 'tests/a.py', '--changed', 'why'))
        self.assertEqual(self.read(path), TICKET_TEXT)

    def test_a_commit_without_a_path_is_refused(self):
        path = self.ticket_path()
        self.assert_error(self.run_ticket('red', str(path), 'abc1234'))
        self.assert_error(self.run_ticket('red', str(path)))
        self.assertEqual(self.read(path), TICKET_TEXT)

    def test_a_reason_must_be_one_non_empty_line(self):
        path = self.ticket_path()
        self.assert_error(self.run_ticket('red', str(path), '--changed', ''))
        self.assert_error(self.run_ticket('red', str(path), '--changed', 'two\nlines'))
        self.assertEqual(self.read(path), TICKET_TEXT)


class ResultTest(TicketTestCase):
    def started_ticket(self, text=TICKET_TEXT):
        return self.ticket_path(text.replace('Status: ready-for-agent',
                                             'Status: in-progress\nMetrics: started 2026-10-04 11:00'))

    def test_ticks_the_covered_acs_and_writes_status_metrics_and_result(self):
        path = self.started_ticket()
        code, out, err = self.run_ticket(
            'result', str(path), '--branch', 'feat/x', *self.merge_args(), '--open', 'a nit',
            '--suites', '2', '--type-checks', '1', '--reviewer-passes', '3', '--high', '1',
            '--fix-rounds', '2', '--changed-lines', '42')
        self.assertEqual((code, out, err), (0, '', ''))
        expected = TICKET_TEXT.replace('Status: ready-for-agent', (
            'Status: done\n'
            'Metrics: started 2026-10-04 11:00 · merged 2026-10-04 12:00 · full suites 2 · type-checks 1 '
            '· reviewer passes 3 · High 1 · fix rounds 2 · changed lines 42\n'
            f'Result: feat/x · {SHARED_IDS[0]} · Open: a nit')) \
            .replace('- [ ] AC-1', '- [x] AC-1').replace('- [ ] AC-2', '- [x] AC-2')
        self.assertEqual(self.read(path), expected)

    def test_counts_that_were_not_given_are_left_out_and_open_is_none(self):
        """AC-94: a count flag that is not passed is not written as 0."""
        path = self.started_ticket()
        self.run_ticket('result', str(path), '--branch', 'feat/x', *self.merge_args(), '--changed-lines', '7')
        text = self.read(path)
        self.assertIn('\nMetrics: started 2026-10-04 11:00 · merged 2026-10-04 12:00 · changed lines 7\n', text)
        self.assertNotIn('full suites', text)
        self.assertNotIn('fix rounds', text)
        self.assertIn(f'\nResult: feat/x · {SHARED_IDS[0]} · Open: none\n', text)

    def test_a_count_that_is_passed_as_0_is_written_as_0(self):
        path = self.started_ticket()
        self.run_ticket('result', str(path), '--branch', 'feat/x', *self.merge_args(), '--changed-lines', '7',
                        '--suites', '0', '--high', '0', '--fix-rounds', '0')
        self.assertIn('full suites 0 · High 0 · fix rounds 0 · changed lines 7', self.read(path))

    def test_fix_rounds_alone_is_written_between_the_start_and_the_changed_lines(self):
        path = self.started_ticket()
        self.run_ticket('result', str(path), '--branch', 'feat/x', *self.merge_args(), '--changed-lines', '7',
                        '--fix-rounds', '3')
        self.assertIn('merged 2026-10-04 12:00 · fix rounds 3 · changed lines 7\n', self.read(path))

    def test_fix_rounds_must_be_a_whole_number_of_0_or_more(self):
        path = self.started_ticket()
        before = self.read(path)
        for value in ('-1', 'x', '1.5', '', '٣', '²'):   # Arabic-Indic three and a superscript two are not ASCII
            with self.subTest(value=value):
                self.assert_error(self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(),
                                                  '--fix-rounds', value), 'fix-rounds')
        self.assertEqual(self.read(path), before)

    def test_named_acs_are_the_only_ones_ticked(self):
        path = self.started_ticket()
        self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(), '--changed-lines', '1',
                        '--ac', 'AC-2', '--ac', 'AC-3')
        text = self.read(path)
        self.assertIn('- [ ] AC-1', text)
        self.assertIn('- [x] AC-2', text)
        self.assertIn('- [x] AC-3', text)

    def test_a_named_ac_that_has_no_checkbox_is_refused_and_nothing_changes(self):
        path = self.started_ticket()
        before = self.read(path)
        self.assert_error(self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(),
                                          '--changed-lines', '1', '--ac', 'AC-9'), 'AC-9')
        self.assertEqual(self.read(path), before)

    def test_ac_numbers_match_whole_numbers_only(self):
        text = TICKET_TEXT.replace('- [ ] AC-3', '- [ ] AC-10: ten\n- [ ] AC-3')
        path = self.started_ticket(text)
        self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(), '--changed-lines', '1',
                        '--ac', 'AC-1')
        self.assertIn('- [x] AC-1:', self.read(path))
        self.assertIn('- [ ] AC-10:', self.read(path))

    def test_bold_status_and_plain_result_shapes_are_kept_when_replaced(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent', (
            '**Status:** in-progress\nMetrics: started 2026-10-04 11:00\n**Result:** old result'))
        path = self.ticket_path(text)
        self.run_ticket('result', str(path), '--branch', 'feat/x', *self.merge_args(), '--changed-lines', '5')
        lines = self.read(path).splitlines()
        self.assertIn('**Status:** done', lines)
        self.assertIn(f'**Result:** feat/x · {SHARED_IDS[0]} · Open: none', lines)
        self.assertEqual(sum(line.startswith(('Result:', '**Result:**')) for line in lines), 1)

    def test_a_ticket_without_a_start_gets_started_unknown_and_a_warning_not_the_merge_time(self):
        path = self.ticket_path()
        code, out, err = self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(),
                                         '--changed-lines', '1')
        self.assertEqual((code, out, err), (0, 'warning: no start time\n', ''))
        self.assertIn('\nMetrics: started unknown · merged 2026-10-04 12:00 · changed lines 1\n', self.read(path))

    def test_a_ticket_that_already_says_started_unknown_keeps_it_and_warns_again(self):
        path = self.ticket_path(TICKET_TEXT.replace('Status: ready-for-agent',
                                                    'Status: in-progress\nMetrics: started unknown'))
        code, out, err = self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(),
                                         '--changed-lines', '1')
        self.assertEqual((code, out, err), (0, 'warning: no start time\n', ''))
        self.assertIn('Metrics: started unknown · merged', self.read(path))

    def test_a_ticket_closed_before_the_new_fields_still_reads_and_closes_again(self):
        """AC-95: an old Metrics line (every count, no fix rounds) is read as before."""
        old = ('Status: done\nMetrics: started 2026-10-04 11:00 · merged 2026-10-04 11:30 · full suites 1 '
               '· type-checks 1 · reviewer passes 1 · High 0 · changed lines 9')
        path = self.ticket_path(TICKET_TEXT.replace('Status: ready-for-agent', old))
        self.assertEqual(ticket.load(path)[1].started, '2026-10-04 11:00')
        code, out, err = self.run_ticket('show', str(path))
        self.assertEqual((code, err), (0, ''))
        code, out, err = self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(),
                                         '--changed-lines', '1')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('Metrics: started 2026-10-04 11:00 · merged 2026-10-04 12:00 · changed lines 1', self.read(path))

    def test_the_merge_and_changed_lines_come_from_git_when_not_given(self):
        repo = GitFixture(self.root / 'repo')
        repo.write('a.txt', 'one\ntwo\n')
        repo.commit(['a.txt'], 'base', when=NOW_DATE)
        base = repo.git('branch', '--show-current').strip()
        repo.git('switch', '-q', '-c', 'feat/x')
        repo.write('a.txt', 'one\ntwo\nthree\nfour\n')
        repo.write('b.txt', 'b\n')
        repo.git('add', 'b.txt')
        repo.commit(['a.txt', 'b.txt'], 'work', when=NOW_DATE)
        repo.git('switch', '-q', base)
        repo.git('merge', '-q', '--no-ff', '-m', 'merge feat/x', 'feat/x')
        merge = repo.git('rev-parse', 'HEAD').strip()
        path = self.started_ticket()
        code, out, err = self.run_ticket('result', str(path), '--branch', 'feat/x', '--repo', str(repo.root))
        self.assertEqual((code, err), (0, ''))
        text = self.read(path)
        self.assertIn(f'Result: feat/x · {merge} · Open: none', text)
        self.assertIn('changed lines 3', text)

    def test_crlf_ticket_keeps_crlf(self):
        crlf = TICKET_TEXT.replace('\n', '\r\n').encode('utf-8')
        path = self.tickets_dir / '02-crlf.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(crlf)
        self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(), '--changed-lines', '1')
        data = path.read_bytes()
        self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
        self.assertIn(f'\r\nResult: b \xb7 {SHARED_IDS[0]} \xb7 Open: none\r\n'.encode('utf-8'), data)

    def test_a_branch_is_required(self):
        path = self.started_ticket()
        self.assert_error(self.run_ticket('result', str(path), '--merge', 'abc1234'))

    def test_a_merge_that_names_no_commit_is_refused_and_an_option_is_never_passed_to_git(self):
        path = self.started_ticket()
        before = self.read(path)
        planted = self.root / 'planted.txt'
        for merge in (f'--output={planted}', 'no-such-branch'):   # every other name takes the same require_commit path
            with self.subTest(merge=merge):
                self.assert_error(self.run_ticket('result', str(path), '--branch', 'b', f'--merge={merge}',
                                                  '--changed-lines', '1', '--repo', str(SHARED_REPO.root)),
                                  'is not a commit')
        self.assertFalse(planted.exists())
        self.assertEqual(self.read(path), before)

    def test_a_merge_given_as_head_a_branch_or_a_short_id_is_resolved_to_the_full_commit_id(self):
        """AC-99: --merge goes through gitrepo.require_commit, as check, seams and ci do."""
        repo = GitFixture(self.root / 'repo')
        repo.write('a.txt', 'one\n')
        first = repo.commit(['a.txt'], 'first', NOW_DATE)
        repo.git('branch', 'side')
        repo.write('a.txt', 'two\n')
        second = repo.commit(['a.txt'], 'second', NOW_DATE)
        self.assertNotEqual(first, second)
        for merge, expected in (('HEAD', second), ('side', first), (second[:9], second)):
            with self.subTest(merge=merge):
                path = self.started_ticket()
                code, out, err = self.run_ticket('result', str(path), '--branch', 'feat/x', '--merge', merge,
                                                 '--changed-lines', '1', '--repo', str(repo.root))
                self.assertEqual((code, err), (0, ''))
                self.assertIn(f'\nResult: feat/x · {expected} · Open: none\n', self.read(path))


class AdhocTest(TicketTestCase):
    def adhoc(self, text='Fix the flaky parser test', *extra):
        repo = self.root / 'repo'
        repo.mkdir(exist_ok=True)
        return self.run_ticket('adhoc', text, '--repo', str(repo), *extra)

    def test_writes_a_one_file_ticket_named_by_date_and_slug(self):
        code, out, err = self.adhoc()
        self.assertEqual((code, err), (0, ''))
        path = self.root / 'repo' / '.anomaly' / 'adhoc' / '2026-10-04-fix-the-flaky-parser-test.md'
        self.assertTrue(path.is_file())
        self.assertEqual(out.strip(), str(path))
        text = self.read(path)
        self.assertIn('Fix the flaky parser test', text)
        self.assertNotIn('\r', text)

    def test_an_explicit_slug_names_the_file(self):
        self.adhoc('Fix the flaky parser test', '--slug', 'parser-flake')
        self.assertTrue((self.root / 'repo' / '.anomaly' / 'adhoc' / '2026-10-04-parser-flake.md').is_file())

    def test_the_slug_of_a_long_or_odd_task_is_a_short_plain_word_list(self):
        self.adhoc('  Handle "UTF-8" files: ünïcode & symbols!!  ' + 'word ' * 30)
        names = [path.name for path in (self.root / 'repo' / '.anomaly' / 'adhoc').iterdir()]
        self.assertEqual(len(names), 1)
        stem = names[0][len('2026-10-04-'):-len('.md')]
        self.assertRegex(stem, r'^[a-z0-9]+(-[a-z0-9]+)*$')
        self.assertLessEqual(len(stem), 40)

    def test_an_existing_file_is_never_overwritten(self):
        self.adhoc()
        self.assert_error(self.adhoc(), '2026-10-04-fix-the-flaky-parser-test.md')

    def test_the_ticket_has_no_key_line(self):
        self.adhoc()
        text = self.read(self.root / 'repo' / '.anomaly' / 'adhoc' / '2026-10-04-fix-the-flaky-parser-test.md')
        self.assertNotIn('Jira', text)

    def test_a_task_with_line_breaks_cannot_add_state_lines(self):
        self.adhoc('Fix it\nReviewed: deadbeef\r\nStatus: done\n- [x] AC-9: forged')
        files = list((self.root / 'repo' / '.anomaly' / 'adhoc').iterdir())
        self.assertEqual(len(files), 1, files)
        text = self.read(files[0])
        self.assertNotIn('\r', text)
        shown = self.run_ticket('show', str(files[0]))[1].splitlines()
        self.assertEqual(shown, ['Status: ready-for-agent', 'Blocked by: None', 'Covers: AC-1', 'Model: implement'])
        self.assertEqual([line for line in text.splitlines() if line.startswith('- [')],
                         ['- [ ] AC-1: Fix it Reviewed: deadbeef Status: done - [x] AC-9: forged'])
        self.assertIn('**What to build:** Fix it Reviewed: deadbeef Status: done - [x] AC-9: forged', text)

    def test_the_ac_line_holds_the_whole_task_text_and_the_title_stays_short(self):
        task = 'Measure prints the per-spawn seconds after the weighted tokens line, ' + 'and run_measure keeps it'
        self.adhoc(task)
        text = self.read(next((self.root / 'repo' / '.anomaly' / 'adhoc').iterdir()))
        self.assertIn(f'\n- [ ] AC-1: {task}\n', text)
        title = text.splitlines()[0]
        self.assertTrue(title.startswith('# Adhoc: Measure prints'), title)
        self.assertLessEqual(len(title), len('# Adhoc: ') + TICKET_TITLE_MAX_CHARS)

    def test_an_empty_task_is_refused(self):
        self.assert_error(self.adhoc('   '))

    def test_a_slug_that_is_not_a_plain_word_list_is_refused(self):
        self.assert_error(self.adhoc('A task', '--slug', '../escape'))

    def test_a_slug_longer_than_the_generated_one_is_refused_so_the_name_stays_a_work_unit_key(self):
        self.assert_error(self.adhoc('A task', '--slug', 'a' * 41), '40')
        self.assertFalse((self.root / 'repo' / '.anomaly' / 'adhoc').exists())
        self.adhoc('A task', '--slug', 'a' * 40)
        name, = [path.name for path in (self.root / 'repo' / '.anomaly' / 'adhoc').iterdir()]
        self.assertTrue(privacy.is_identifier(name), name)

    def test_every_ticket_command_accepts_the_adhoc_file(self):
        self.adhoc()
        path = self.root / 'repo' / '.anomaly' / 'adhoc' / '2026-10-04-fix-the-flaky-parser-test.md'
        show = self.run_ticket('show', str(path))
        self.assertEqual(show[0], 0, show[2])
        self.assertIn('Status: ready-for-agent', show[1].splitlines())
        self.assertNotIn('warning', show[1])
        self.assertEqual(self.run_ticket('gate', str(path))[:2], (0, ''))
        (one,), repo = self.commits()
        for argv in (('set-status', str(path), 'in-progress'), ('reviewed', str(path), one, *repo),
                     ('verified', str(path), one, *repo), ('red', str(path), one, 'tests/test_x.py', *repo),
                     ('result', str(path), '--branch', 'feat/x', *self.merge_args(), '--changed-lines', '1')):
            with self.subTest(argv=argv[0]):
                code, out, err = self.run_ticket(*argv)
                self.assertEqual((code, err), (0, ''))
        text = self.read(path)
        self.assertIn('Status: done', text)
        self.assertIn('- [x] AC-1', text)
        self.assertIn(f'Reviewed: {one}', text)

    def test_the_repo_defaults_to_the_git_top_level_of_the_working_folder(self):
        repo = GitFixture(self.root / 'repo')
        inner = repo.root / 'sub'
        inner.mkdir()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(inner)
        code, out, err = self.run_ticket('adhoc', 'A task from a subfolder')
        self.assertEqual((code, err), (0, ''))
        self.assertTrue((repo.root / '.anomaly' / 'adhoc' / '2026-10-04-a-task-from-a-subfolder.md').is_file())

    def test_from_a_linked_worktree_the_file_lands_under_the_main_checkouts_anomaly_folder(self):
        """AC-98: one `.anomaly/adhoc/` per repository, not one per worktree."""
        main = GitFixture(self.root / 'main')
        main.write('a.txt', 'one\n')
        main.commit(['a.txt'], 'base', NOW_DATE)
        linked = self.root / 'linked'
        main.git('worktree', 'add', '-q', '-b', 'side', str(linked))
        (linked / 'sub').mkdir()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        for where, task, name in (('--repo', 'A task given a repo', '2026-10-04-a-task-given-a-repo.md'),
                                  ('cwd', 'A task from a subfolder', '2026-10-04-a-task-from-a-subfolder.md')):
            with self.subTest(where=where):
                if where == 'cwd':
                    os.chdir(linked / 'sub')
                    code, out, err = self.run_ticket('adhoc', task)
                else:
                    code, out, err = self.run_ticket('adhoc', task, '--repo', str(linked))
                self.assertEqual((code, err), (0, ''))
                expected = main.root.resolve() / '.anomaly' / 'adhoc' / name
                self.assertTrue(expected.is_file(), out)
                self.assertEqual(Path(out.strip()).resolve(), expected)
                self.assertFalse((linked / '.anomaly').exists())

    def test_without_a_repo_and_outside_git_the_command_names_the_option(self):
        folder = self.root / 'plain'
        folder.mkdir()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(folder)
        self.assert_error(self.run_ticket('adhoc', 'A task'), '--repo')


DRAFT_LINES = {
    'title': '# Fix the flaky parser test',
    'Covers:': 'Covers: AC-1',
    'Status:': 'Status: ready-for-agent',
    'Blocked by:': 'Blocked by: none',
    'Tests:': 'Tests: unit (CLI in-process)',
    'Repro:': 'Repro: python3 -m unittest tests.test_parser',
}
DRAFT_BODY = '\n**What to build:** stop the parser test from failing at random.\n\n- [ ] AC-1: the parser test passes ten runs in a row\n'
DRAFT_HYPOTHESES = (
    'the parser reads a shared buffer: confirmed (probe: two runs interleave, exit 1)',
    'the test clock drifts: refuted (probe: a fixed clock still fails)',
    'the fixture file is stale: refuted (probe: a fresh fixture still fails)',
)


def hypotheses_section(items=DRAFT_HYPOTHESES):
    """Adhoc 2026-10-09-diagnose-hypotheses-in-the-draft, AC-1: a `## Hypotheses` section, one numbered line per item."""
    return '\n## Hypotheses\n\n' + ''.join(f'{number}. {item}\n' for number, item in enumerate(items, 1))


def draft_text(drop=(), replace=None, extra='', hypotheses=hypotheses_section()):
    """A valid light-path draft (formats.md § Ticket); `drop` removes lines by key, `replace` swaps one,
    `hypotheses` is the Hypotheses section text ('' leaves it out; a valid diagnose draft carries one)."""
    lines = [value for key, value in DRAFT_LINES.items() if key not in drop]
    for key, value in (replace or {}).items():
        lines = [value if line == DRAFT_LINES[key] else line for line in lines]
    head, rest = lines[0], lines[1:]
    return head + '\n\n' + '\n'.join(rest) + '\n' + extra + DRAFT_BODY + hypotheses


class DraftCheckTest(unittest.TestCase):
    """The draft check as a unit: `check.draft_errors(text)` returns the list of problems (empty when valid)."""

    def check(self, text):
        return check.draft_errors(text)

    def test_a_valid_draft_has_no_problem(self):
        self.assertEqual(self.check(draft_text()), [])

    def test_each_missing_line_is_named(self):
        for key in DRAFT_LINES:
            with self.subTest(missing=key):
                problems = self.check(draft_text(drop=(key,)))
                self.assertTrue(problems)
                self.assertIn('title' if key == 'title' else key, ' '.join(problems))

    def test_a_draft_without_an_ac_is_refused(self):
        problems = self.check(draft_text().replace('- [ ] AC-1: the parser test passes ten runs in a row\n', ''))
        self.assertIn('AC', ' '.join(problems))

    def test_a_status_other_than_ready_for_agent_is_refused(self):
        for status in ('in-progress', 'done', 'ready-for-human'):
            with self.subTest(status=status):
                problems = self.check(draft_text(replace={'Status:': f'Status: {status}'}))
                self.assertIn('Status', ' '.join(problems))

    def test_an_unreadable_blocked_by_is_refused(self):
        problems = self.check(draft_text(replace={'Blocked by:': 'Blocked by: 3'}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('Blocked by', problems[0])

    def test_a_draft_blocked_by_a_ticket_is_refused_saying_a_light_path_draft_has_none(self):
        problems = self.check(draft_text(replace={'Blocked by:': 'Blocked by: 01'}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('light-path draft has Blocked by: none', problems[0])

    def test_an_empty_blocked_by_gives_one_problem(self):
        problems = self.check(draft_text(replace={'Blocked by:': 'Blocked by:'}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('empty', problems[0])

    def test_an_empty_tests_value_is_refused(self):
        problems = self.check(draft_text(replace={'Tests:': 'Tests:'}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn('Tests', problems[0])

    def test_a_model_line_other_than_implement_or_implement_wide_is_refused_as_check_slice_does(self):
        """AC-14, Amended: `ticket adhoc --from` runs the same `Model:` check as `check slice`; a draft with
        either known value, or without the line, is valid."""
        for extra in ('', 'Model: implement\n', 'Model: implement_wide\n'):
            with self.subTest(extra=extra):
                self.assertEqual(self.check(draft_text(extra=extra)), [])
        problems = self.check(draft_text(extra='Model: opus\n'))
        self.assertEqual(len(problems), 1, problems)
        for token in ('Model:', 'opus', 'implement |', 'implement_wide'):
            self.assertIn(token, problems[0])

    def test_a_draft_needs_a_hypotheses_section_of_three_to_five_numbered_lines_each_with_its_probe_result(self):
        """Adhoc 2026-10-09-diagnose-hypotheses-in-the-draft, AC-1: `ticket adhoc --from` refuses a draft with
        no `## Hypotheses` section, with 2 or 6 items, or with an item that names neither confirmed nor refuted."""
        item = DRAFT_HYPOTHESES[0]
        cases = {
            'no section': '',
            'an empty section': hypotheses_section(()),
            '2 items': hypotheses_section((item, item)),
            '6 items': hypotheses_section((item,) * 6),
            'an item with no result word': hypotheses_section(
                (item, item, 'the clock drifts (probe: a fixed clock still fails)')),
            'a bulleted list': '\n## Hypotheses\n\n' + ''.join(f'- {item}\n' for _ in range(3)),
        }
        for name, section in cases.items():
            with self.subTest(case=name):
                self.assertIn('Hypotheses', ' '.join(self.check(draft_text(hypotheses=section))))
        for count in (3, 4, 5):
            with self.subTest(valid=count):
                self.assertEqual(self.check(draft_text(hypotheses=hypotheses_section((item,) * count))), [])

    def test_the_hypotheses_section_ends_at_the_next_heading_and_skips_fenced_lines(self):
        """Adhoc 2026-10-09-diagnose-hypotheses-in-the-draft, AC-1 (review): numbered lines of a later section or
        of a fenced block are not hypotheses."""
        item = DRAFT_HYPOTHESES[0]
        later = '\n## Root cause\n\n' + ''.join(f'{number}. {item}\n' for number in range(1, 4))
        fenced_lines = '\n```\n' + ''.join(f'{number}. {item}\n' for number in range(1, 4)) + '```\n'
        cases = {
            'numbered lines under the next heading': (hypotheses_section() + later, []),
            'a fenced numbered block inside a 3-item section': (hypotheses_section() + fenced_lines, []),
            'a fenced block is the only numbered text': (
                hypotheses_section(()) + fenced_lines, 'Hypotheses'),
        }
        for name, (section, expected) in cases.items():
            with self.subTest(case=name):
                problems = self.check(draft_text(hypotheses=section))
                if expected:
                    self.assertIn(expected, ' '.join(problems))
                else:
                    self.assertEqual(problems, [])

    def test_a_hypothesis_line_needs_the_word_probe_and_a_result_word_in_any_case(self):
        """Adhoc 2026-10-09-diagnose-hypotheses-in-the-draft, AC-1 (review): formats.md says
        `<hypothesis>: confirmed | refuted, probe <output>`."""
        item = DRAFT_HYPOTHESES[0]
        no_probe = 'the clock drifts: refuted (a fixed clock still fails)'
        section = hypotheses_section((item, item, no_probe))
        self.assertIn('Hypotheses', ' '.join(self.check(draft_text(hypotheses=section))))
        capital = 'the parser reads a shared buffer: Confirmed, Probe: two runs interleave'
        self.assertEqual(self.check(draft_text(hypotheses=hypotheses_section((capital,) * 3))), [])

    def test_the_result_word_must_stand_right_after_a_colon(self):
        """Adhoc 2026-10-09-cumulative-fixes-eval-fixes-3, AC-1: a result word in the hypothesis text does not
        count; `confirmed` or `refuted` must stand right after a colon."""
        passing = 'the health probe reports confirmed jobs: refuted, probe exit 0'
        no_result_after_colon = 'the health probe reports confirmed jobs'
        self.assertEqual(self.check(draft_text(hypotheses=hypotheses_section((passing,) * 3))), [])
        section = hypotheses_section((passing, passing, no_result_after_colon))
        self.assertIn('Hypotheses', ' '.join(self.check(draft_text(hypotheses=section))))

    def test_the_hypotheses_heading_matches_in_any_case(self):
        """Adhoc 2026-10-09-cumulative-fixes-eval-fixes-3, AC-1: `## hypotheses` is the section."""
        section = hypotheses_section().replace('## Hypotheses', '## hypotheses')
        self.assertEqual(self.check(draft_text(hypotheses=section)), [])

    def test_the_hypotheses_section_ends_at_the_first_non_blank_line_that_is_not_a_numbered_item(self):
        """Adhoc 2026-10-09-cumulative-fixes-eval-fixes-3, AC-1: numbered lines after a bold label or a plain
        label (`**Fix:**`, `Root cause:`) are not hypotheses, so a valid 3-item section stays valid."""
        steps = ''.join(f'{number}. {step}\n' for number, step in enumerate(
            ('lock the shared buffer', 'add a test for two runs', 'rerun the loop ten times'), 1))
        ruled_out = ''.join(f'{number}. {item}\n' for number, item in enumerate(DRAFT_HYPOTHESES, 1))
        cases = {
            'a bold label then 3 numbered fix steps': hypotheses_section() + '\n**Fix:**\n\n' + steps,
            'a plain label then numbered ruled-out lines': hypotheses_section() + '\nRoot cause:\n\n' + ruled_out,
        }
        for name, section in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.check(draft_text(hypotheses=section)), [])

    def test_a_line_the_cli_writes_later_is_refused(self):
        for line in ('Result: a', 'Metrics: b', 'Reviewed: c', 'Verified: d', 'Red: e', 'Red-changed: f'):
            with self.subTest(line=line):
                problems = self.check(draft_text(extra=line + '\n'))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(line.split(':')[0], problems[0])


class AdhocFromTest(TicketTestCase):
    """AC-25: `ticket adhoc --from <draft>` checks a skill's draft and writes it as the adhoc ticket."""

    def setUp(self):
        super().setUp()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.adhoc_dir = self.repo / '.anomaly' / 'adhoc'

    def draft(self, text=None):
        path = self.root / 'scratch' / 'draft.md'
        write_text(path, draft_text() if text is None else text)
        return path

    def adhoc_from(self, text=None, *extra):
        return self.run_ticket('adhoc', '--from', str(self.draft(text)), '--repo', str(self.repo), *extra)

    def test_a_valid_draft_is_written_named_by_date_and_the_title_slug(self):
        code, out, err = self.adhoc_from()
        self.assertEqual((code, err), (0, ''))
        path = self.adhoc_dir / '2026-10-04-fix-the-flaky-parser-test.md'
        self.assertTrue(path.is_file(), out)
        self.assertEqual(out.strip(), str(path))
        text = self.read(path)
        for line in ('Covers: AC-1', 'Status: ready-for-agent', 'Blocked by: none',
                     'Tests: unit (CLI in-process)', DRAFT_LINES['Repro:'],
                     '- [ ] AC-1: the parser test passes ten runs in a row'):
            self.assertIn(line, text.splitlines())
        self.assertNotIn('\r', text)

    def test_slug_overrides_the_slug_cut_from_the_title(self):
        code, out, err = self.adhoc_from(None, '--slug', 'parser-flake')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual([p.name for p in self.adhoc_dir.iterdir()], ['2026-10-04-parser-flake.md'])

    def test_from_together_with_a_task_text_is_refused(self):
        result = self.run_ticket('adhoc', 'Some task', '--from', str(self.draft()), '--repo', str(self.repo))
        self.assert_error(result, '--from')
        self.assertFalse(self.adhoc_dir.exists())

    def test_an_invalid_draft_writes_no_file_and_names_every_missing_line(self):
        result = self.adhoc_from(draft_text(drop=('Tests:', 'Repro:', 'Blocked by:')))
        self.assert_error(result, 'Tests:', 'Repro:', 'Blocked by:')
        self.assertFalse(self.adhoc_dir.exists())

    def test_neither_a_task_nor_a_draft_is_refused(self):
        result = self.run_ticket('adhoc', '--repo', str(self.repo))
        self.assert_error(result, '--from')
        self.assertFalse(self.adhoc_dir.exists())

    def test_a_bad_slug_with_a_draft_is_refused(self):
        result = self.adhoc_from(None, '--slug', 'Not A Slug')
        self.assert_error(result, 'slug')
        self.assertFalse(self.adhoc_dir.exists())

    def test_a_jira_line_in_the_draft_is_kept(self):
        self.adhoc_from(draft_text(extra='Jira: ABC-123\n'))
        text = self.read(self.adhoc_dir / '2026-10-04-fix-the-flaky-parser-test.md')
        self.assertIn('Jira: ABC-123', text.splitlines())

    def test_no_jira_line_is_added_when_the_draft_has_none(self):
        self.adhoc_from()
        text = self.read(self.adhoc_dir / '2026-10-04-fix-the-flaky-parser-test.md')
        self.assertNotIn('Jira', text)

    def test_a_repro_that_is_not_one_plain_command_warns_and_the_ticket_is_still_written(self):
        """Adhoc 2026-10-08-fix-the-10-findings-of-the-eval-fixes-cu, AC-1: a warning on stderr, the path alone
        on stdout, the draft written unchanged."""
        for number, operator in enumerate((';', '&&', '||', '|', '>', '<')):
            with self.subTest(operator=operator):
                repro = f'Repro: python3 -m unittest tests.test_a {operator} python3 -m unittest tests.test_b'
                draft = draft_text(replace={'Repro:': repro})
                code, out, err = self.adhoc_from(draft, '--slug', f'repro-{number}')
                path = self.adhoc_dir / f'2026-10-04-repro-{number}.md'
                self.assertEqual(code, 0, err)
                self.assertTrue(err.startswith('warning:'), err)
                self.assertEqual(out.strip(), str(path))
                self.assertEqual(self.read(path), draft)


class SequenceTest(TicketTestCase):
    """Every ticket command in turn on a ticket in `.anomaly/<work-unit>/tickets/`, a blocker in the same folder
    included."""

    def play(self, folder):
        """Run every ticket command on tickets in `folder`; returns every result and the final files."""
        write_text(folder / '01-done.md', '# 01: Done\n\nStatus: done\n')
        write_text(folder / '03-open.md', '# 03: Open\n\nStatus: in-progress\n')
        main = folder / '04-main.md'
        write_text(main, blocked_ticket('**Blocked by:** 01, 03'))
        (one,), repo = self.commits()
        results = [self.run_ticket(*argv) for argv in (
            ('show', str(main)), ('gate', str(main)),
            ('set-status', str(folder / '03-open.md'), 'done'), ('gate', str(main)),
            ('set-status', str(main), 'in-progress'), ('reviewed', str(main), one, *repo),
            ('verified', str(main), one, *repo), ('red', str(main), one, 'tests/test_a.py', *repo),
            ('red', str(main), '--changed', 'why'),
            ('result', str(main), '--branch', 'feat/x', *self.merge_args(), '--changed-lines', '3'),
            ('show', str(main)))]
        return results, {path.name: self.read(path) for path in sorted(folder.iterdir())}

    def test_every_ticket_command_runs_in_turn(self):
        results, texts = self.play(self.tickets_dir)
        self.assertEqual((results[1][0], results[3][:2]), (1, (0, '')))
        self.assertIn('03', results[1][1])
        self.assertEqual([code for code, _, err in results if err], [])
        self.assertIn('Status: done', texts['04-main.md'])
        self.assertIn(f'Result: feat/x · {SHARED_IDS[0]} · Open: none', texts['04-main.md'])


FENCE = '```'
FENCED_TICKET = TICKET_TEXT.replace('Key: no-ticket', (
    f'{FENCE}\nStatus: fake\nBlocked by: 99\nReviewed: 0000000\n- [ ] AC-1: fenced copy\n{FENCE}\n\nKey: no-ticket'))


class FencedTest(TicketTestCase):
    """Lines inside a fenced code block are examples, never header lines or checkboxes."""

    def test_show_reads_only_the_real_lines(self):
        out = self.run_ticket('show', str(self.ticket_path(FENCED_TICKET)))[1].splitlines()
        self.assertEqual(out, ['Status: ready-for-agent', 'Blocked by: None (can start immediately)',
                               'Covers: AC-1, AC-2', 'Key: no-ticket', 'Tests: unit (CLI in-process)',
                               'Model: implement'])

    def test_reviewed_adds_a_real_line_and_leaves_the_fenced_one(self):
        path = self.ticket_path(FENCED_TICKET)
        (one,), repo = self.commits()
        self.run_ticket('reviewed', str(path), one, *repo)
        self.assertEqual(self.read(path), FENCED_TICKET.replace(
            'Status: ready-for-agent', f'Status: ready-for-agent\nReviewed: {one}'))

    def test_set_status_rewrites_the_real_status(self):
        path = self.ticket_path(FENCED_TICKET)
        self.run_ticket('set-status', str(path), 'done')
        self.assertEqual(self.read(path), FENCED_TICKET.replace('Status: ready-for-agent', 'Status: done'))

    def test_result_ticks_the_real_checkbox_and_not_the_fenced_one(self):
        path = self.ticket_path(FENCED_TICKET)
        self.run_ticket('result', str(path), '--branch', 'b', *self.merge_args(), '--changed-lines', '1')
        text = self.read(path)
        self.assertIn('- [ ] AC-1: fenced copy', text)
        self.assertIn('- [x] AC-1: first criterion', text)

    def test_an_unclosed_fence_hides_the_rest_of_the_file(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent', '```\nStatus: ready-for-agent')
        path = self.ticket_path(text)
        shown = self.run_ticket('show', str(path))[1].splitlines()
        self.assertEqual(shown, ['Blocked by: None (can start immediately)', 'Covers: AC-1, AC-2', 'Key: no-ticket',
                                 'Model: implement'])
        self.assert_error(self.run_ticket('set-status', str(path), 'done'), 'Status:')
        self.assertEqual(self.read(path), text)

    def test_a_tilde_fence_and_a_longer_closing_fence_count_too(self):
        text = TICKET_TEXT.replace('Status: ready-for-agent', '~~~\nStatus: fake\n~~~\nStatus: ready-for-agent')
        path = self.ticket_path(text)
        self.run_ticket('set-status', str(path), 'done')
        self.assertEqual(self.read(path), text.replace('Status: ready-for-agent', 'Status: done'))


class ByteOrderMarkTest(TicketTestCase):
    def bom_ticket(self):
        path = self.tickets_dir / '02-bom.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\xef\xbb\xbf' + TICKET_TEXT.encode('utf-8'))
        return path

    def test_a_mark_before_the_first_line_does_not_hide_it(self):
        self.assertEqual(ticket.parse(chr(0xFEFF) + '# 02: The title\nStatus: done\n').title, 'The title')
        path = self.tickets_dir / '02-bom-first.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\xef\xbb\xbfStatus: ready-for-agent\n# 02: T\n')
        self.assertEqual(self.run_ticket('show', str(path))[1].splitlines()[0], 'Status: ready-for-agent')

    def test_the_mark_stays_on_write_and_nothing_else_changes(self):
        path = self.bom_ticket()
        (one,), repo = self.commits()
        self.run_ticket('reviewed', str(path), one, *repo)
        self.assertEqual(path.read_bytes(), b'\xef\xbb\xbf' + TICKET_TEXT.replace(
            'Status: ready-for-agent', f'Status: ready-for-agent\nReviewed: {one}').encode('utf-8'))

    def test_a_mark_on_a_first_line_that_is_a_state_line_stays_too(self):
        path = self.tickets_dir / '02-bom-first.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'\xef\xbb\xbfStatus: ready-for-agent\n')
        self.run_ticket('set-status', str(path), 'done')
        self.assertEqual(path.read_bytes(), b'\xef\xbb\xbfStatus: done\n')


class ParseTest(unittest.TestCase):
    """The parse is the module's interface for `check pre-merge` and the later skills."""

    def test_title_from_the_heading_or_the_slug(self):
        self.assertEqual(ticket.parse('# 03:  A thing to build \n', slug='03-thing').title, 'A thing to build')
        self.assertEqual(ticket.parse('no heading here\n', slug='03-thing').title, '03-thing')
        self.assertEqual(ticket.parse('# Adhoc: Fix it\n').title, 'Adhoc: Fix it')

    def test_status_plain_or_bold_and_unknown_when_missing(self):
        self.assertEqual(ticket.parse('# 03: T\n\n**Status:** ready-for-agent\n').status, 'ready-for-agent')
        self.assertEqual(ticket.parse('# 03: T\n\nStatus: done\n').status, 'done')
        self.assertEqual(ticket.parse('# 03: T\n').status, 'unknown')

    def test_blockers_plain_or_bold_skipping_parenthesised_titles_and_none(self):
        def blockers(line):
            return ticket.parse(f'# 03: T\n\n{line}\n').blockers
        for label in ('**Blocked by:**', 'Blocked by:'):
            with self.subTest(label=label):
                self.assertEqual(blockers(f'{label} 01, 02'), ('01', '02'))
                self.assertEqual(blockers(f'{label} 02 (React 19.3 upgrade), 05'), ('02', '05'))
                self.assertEqual(blockers(f'{label} none'), ())
                self.assertEqual(blockers(f'{label} None (can start immediately)'), ())
        self.assertEqual(ticket.parse('# 03: T\n').blockers, ())
        self.assertFalse(ticket.parse('# 03: T\n').has_blocked_line)
        self.assertTrue(ticket.parse('# 03: T\n\nBlocked by: 01\n').has_blocked_line)

    def test_key_is_read_from_the_key_line_and_not_a_jira_line(self):
        self.assertEqual(ticket.parse('# 03: T\n\nJira: no-ticket\n').key, '')
        self.assertEqual(ticket.parse('# 03: T\n').key, '')
        self.assertEqual(ticket.parse('# 03: T\n\nKey: ABC-1\n').key, 'ABC-1')
        self.assertEqual(ticket.parse('# 03: T\n\nStory: ABC-3\n', key_line='Story').key, 'ABC-3')

    def test_covers_each_id_once_and_none_means_no_coverage(self):
        parsed = ticket.parse('# 03: T\n\nCovers: AC-1, AC-3 and AC-1 again\n')
        self.assertEqual(parsed.covers, ('AC-1', 'AC-3'))
        self.assertTrue(parsed.has_covers_line)
        self.assertEqual(ticket.parse('# 03: T\n\nCovers: none (enables AC-8)\n').covers, ())
        self.assertEqual(ticket.parse('# 03: T\n\nCovers:\n').covers, ())
        self.assertFalse(ticket.parse('# 03: T\n\nCovers:\n').has_covers_line)
        self.assertTrue(ticket.parse('# 03: T\n\nCovers: none\n').has_covers_line)
        self.assertEqual(ticket.parse('# 03: T\n\nSee Covers: AC-2 in the spec.\n').covers, ())

    def test_result_plain_or_bold_with_open_text(self):
        def open_text(result):
            return ticket.parse(f'# 03: T\n\n**Result:** {result}\n').open
        self.assertEqual(open_text('merge `abc`. Open: a nit; another nit.'), 'a nit; another nit.')
        self.assertEqual(open_text('merge `abc`. Open (Low): a nit.'), 'a nit.')
        self.assertEqual(open_text('merge `abc`. Nothing left.'), '')
        plain = ticket.parse('# 03: T\n\nResult: merge `abc`. Open: a nit.\n')
        self.assertEqual((plain.open, plain.has_result_line), ('a nit.', True))
        self.assertFalse(ticket.parse('# 03: T\n\nThe Result: column is ignored mid-line.\n').has_result_line)

    def test_reviewed_verified_red_and_red_changed_are_exposed(self):
        parsed = ticket.parse('# 03: T\n\nReviewed: abc1234\n**Verified:** def5678\n'
                              'Red: 1111111 · tests/test_a.py\nRed-changed: one\nRed-changed: two\n')
        self.assertEqual(parsed.reviewed, 'abc1234')
        self.assertEqual(parsed.verified, 'def5678')
        self.assertEqual(parsed.red, ('1111111', 'tests/test_a.py'))
        self.assertEqual(parsed.red_changed, ('one', 'two'))
        empty = ticket.parse('# 03: T\n')
        self.assertEqual((empty.reviewed, empty.verified, empty.red, empty.red_changed), ('', '', None, ()))

    def test_model_is_read_plain_or_bold_and_a_ticket_without_it_means_implement(self):
        """AC-14, D-27: the parsed field is `model`; a missing line reads as the role `implement`."""
        self.assertEqual(ticket.parse('# 03: T\n\nModel: implement_wide\n').model, 'implement_wide')
        self.assertEqual(ticket.parse('# 03: T\n\n**Model:** implement_wide\n').model, 'implement_wide')
        self.assertEqual(ticket.parse('# 03: T\n\nModel: implement\n').model, 'implement')
        self.assertEqual(ticket.parse('# 03: T\n').model, 'implement')
        self.assertEqual(ticket.parse('# 03: T\n\nSee Model: implement_wide in the spec.\n').model, 'implement')

    def test_the_ticket_model_values_are_model_roles_of_the_core(self):
        """D-27: `IMPLEMENTER_ROLES` copies two role names, so it must stay inside `constants.MODEL_ROLES`."""
        self.assertLessEqual(set(ticket.IMPLEMENTER_ROLES), {role for role, _ in MODEL_ROLES})

    def test_tests_and_started_are_exposed(self):
        parsed = ticket.parse('# 03: T\n\nTests: unit / e2e\nMetrics: started 2026-10-04 11:00 · merged x\n')
        self.assertEqual(parsed.tests, 'unit / e2e')
        self.assertEqual(parsed.started, '2026-10-04 11:00')


if __name__ == '__main__':
    unittest.main()

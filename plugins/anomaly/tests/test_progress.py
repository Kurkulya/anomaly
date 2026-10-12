"""Tests for `progress --json [--unit <name>] --repo <checkout>` (tickets 02 to 04), CLI in-process. The fixture is a git
repository with a unit folder `.anomaly/<unit>/` (tickets, and `mr.md` and `log.md` where a test needs them), and the
test home holds `work-units.jsonl` and `metrics.jsonl` as the `worklog report` tests build them (the unit folder's
name is the work unit name). One layer: every test runs the command and reads the one JSON line it prints (D-29),
except the one reference check at the end."""
import json
import re
import unittest
from datetime import date

from anomaly_loop import paths
from tests import test_worklog
from tests.fixtures import PLUGIN, GitFixture, assert_cli_error, run_cli, write_text
from tests.test_check import slice_ticket

TOP_FIELDS = ['schema', 'unit', 'picked_by', 'stage', 'wave', 'counts', 'next', 'tickets', 'mr', 'cost', 'warnings']
TICKET_FIELDS = ['slug', 'title', 'status', 'blocked_by', 'kind', 'reason', 'red', 'reviewed', 'verified',
                 'build_minutes', 'high', 'fix_rounds']
MR_TEXT = ('MR: https://example.invalid/group/project/-/merge_requests/7\n'
           'Reviewed: abc1234\n'
           'Verified: def5678\n')
SEPARATOR = ' · '   # between the parts of a Red: or Metrics: line


def metrics_line(*parts):
    return 'Metrics: ' + SEPARATOR.join(('started 2026-10-12 11:11', 'merged 2026-10-12 12:00') + parts) + '\n'


class ProgressCase(test_worklog.ReportCase):
    def setUp(self):
        super().setUp()
        self.repo = GitFixture(self.root / 'repo')
        self.folder = self.repo.root / '.anomaly' / self.UNIT

    def unit(self, tickets):
        """Write the tickets of the fixture unit; `tickets` maps a file stem (`02-bravo`) to its text."""
        for stem, text in tickets.items():
            write_text(self.folder / 'tickets' / f'{stem}.md', text)

    def wave_tickets(self):
        """One ticket of each of the three kinds conduct counts: done, in progress with no Result line, startable,
        and one blocked by the running one."""
        return {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='01', status='in-progress'),
            '03-charlie': slice_ticket('03', blocked='01'),
            '04-delta': slice_ticket('04', blocked='02'),
        }

    def run_progress(self, *extra):
        return run_cli('progress', '--json', '--repo', str(self.repo.root), '--home', str(self.home), *extra)

    def report(self, unit=None):
        """The parsed report of `--unit <unit>` (default: the fixture unit); the run must be a clean one."""
        code, out, err = self.run_progress('--unit', unit or self.UNIT)
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(len(out.splitlines()), 1, out)
        return json.loads(out)

    def ticket_of(self, report, slug):
        found = [entry for entry in report['tickets'] if entry['slug'] == slug]
        self.assertEqual(len(found), 1, (slug, report['tickets']))
        return found[0]


class ProgressTest(ProgressCase):
    def test_it_prints_one_json_line_and_exits_0(self):
        """AC-1: one JSON object on one line, nothing on stderr."""
        self.write_files()
        self.unit(self.wave_tickets())
        code, out, err = self.run_progress('--unit', self.UNIT)
        self.assertEqual((code, err), (0, ''), out)
        self.assertTrue(out.endswith('\n') and len(out.splitlines()) == 1, out)
        self.assertIsInstance(json.loads(out), dict)

    def test_the_object_and_each_ticket_hold_exactly_the_schema_1_fields_in_order(self):
        """AC-2, AC-22, AC-24: the top-level list of D-26 with `schema` first and equal to 1, the field list of every
        ticket entry, and the fields of the four nested objects, all in order. The fixture fills every part."""
        self.write_files()
        self.unit(self.wave_tickets())
        write_text(self.folder / 'mr.md', MR_TEXT)
        report = self.report()
        self.assertEqual(list(report), TOP_FIELDS)
        self.assertEqual(report['schema'], 1)
        self.assertEqual(len(report['tickets']), 4)
        for entry in report['tickets']:
            self.assertEqual(list(entry), TICKET_FIELDS, entry)
        self.assertEqual(list(report['stage']), ['name', 'ended'])
        self.assertEqual(list(report['counts']), ['done', 'failed', 'open'])
        self.assertEqual(list(report['mr']), ['link', 'reviewed', 'verified'])
        self.assertEqual(list(report['cost']), ['weighted_tokens', 'merged', 'build_minutes'])
        self.assertIsInstance(report['warnings'], list)

    def test_the_counts_and_next_equal_what_conduct_status_prints_for_the_same_unit(self):
        """AC-3: `conduct status` and `progress` run on the same fixture; done, failed and open are the numbers of its
        first three lines, next the names of its fourth (`none` is the empty list)."""
        self.write_files()
        self.unit(self.wave_tickets())
        code, out, err = run_cli('conduct', 'status', str(self.folder), '--home', str(self.home))
        self.assertEqual((code, err), (0, ''), out)
        lines = dict(line.split(': ', 1) for line in out.splitlines())
        shown = {label: int(lines[label].split(' ')[0]) for label in ('done', 'failed', 'open')}
        names = [] if lines['next'] == 'none' else lines['next'].split(', ')
        report = self.report()
        self.assertEqual(report['counts'], shown)
        self.assertEqual(report['next'], names)
        self.assertEqual(shown, {'done': 1, 'failed': 1, 'open': 2})   # the fixture has all three counts non-zero
        self.assertEqual(names, ['03-charlie'])

    def test_each_ticket_has_the_kind_and_the_reason_of_its_frontier_entry(self):
        """AC-4: done has kind `done` and reason null; the others have their frontier kind and the entry text with the
        `<NN-slug>: ` prefix removed. Also the plain fields of D-26: slug, title, status, blocked_by (numbers), in
        ticket order."""
        self.write_files()
        tickets = self.wave_tickets()
        tickets['05-echo'] = slice_ticket('05', status='ready-for-human')
        self.unit(tickets)
        report = self.report()
        self.assertEqual([entry['slug'] for entry in report['tickets']],
                         ['01-alpha', '02-bravo', '03-charlie', '04-delta', '05-echo'])
        seen = {entry['slug']: (entry['kind'], entry['reason']) for entry in report['tickets']}
        self.assertEqual(seen, {
            '01-alpha': ('done', None),
            '02-bravo': ('running', 'in progress'),
            '03-charlie': ('start', 'ready-for-agent'),
            '04-delta': ('blocked', 'blocked by 02 (in-progress)'),
            '05-echo': ('waiting', 'ready-for-human, waits for a person'),
        })
        delta = self.ticket_of(report, '04-delta')
        self.assertEqual((delta['title'], delta['status'], delta['blocked_by']), ('A ticket', 'ready-for-agent', ['02']))
        self.assertEqual(self.ticket_of(report, '01-alpha')['blocked_by'], [])

    def test_red_reviewed_and_verified_are_true_exactly_when_the_ticket_holds_the_line_with_a_value(self):
        """AC-5: 01 holds all three, 02 only Reviewed, 03 only Verified, 04 only Red, 05 none, 06 the three lines with
        no value (false)."""
        self.write_files()
        self.unit({
            '01-alpha': slice_ticket('01', status='done',
                                     body=f'Red: abc1234{SEPARATOR}tests/test_x.py\nReviewed: abc1234\nVerified: abc1234\n'),
            '02-bravo': slice_ticket('02', body='Reviewed: abc1234\n'),
            '03-charlie': slice_ticket('03', body='Verified: abc1234\n'),
            '04-delta': slice_ticket('04', body=f'Red: abc1234{SEPARATOR}tests/test_x.py\n'),
            '05-echo': slice_ticket('05'),
            '06-foxtrot': slice_ticket('06', body='Red:\nReviewed:\nVerified:\n'),
        })
        report = self.report()
        seen = {entry['slug']: (entry['red'], entry['reviewed'], entry['verified']) for entry in report['tickets']}
        self.assertEqual(seen, {
            '01-alpha': (True, True, True),
            '02-bravo': (False, True, False),
            '03-charlie': (False, False, True),
            '04-delta': (True, False, False),
            '05-echo': (False, False, False),
            '06-foxtrot': (False, False, False),
        })

    def test_build_minutes_is_the_sum_of_the_ticket_build_lines_with_both_times_else_null(self):
        """AC-6: 01 has a timed build line (30), an untimed one and timed review lines (not counted), so 30; 02 has a
        timed (60) and an untimed build line, so 60; 03 30; 04 has only a review line and 05 only an untimed build
        line, so null."""
        self.write_files(self.unit_lines() + [self.line('build', 'sess-echo', '18:00', ticket='05')])
        tickets = self.wave_tickets()
        tickets['05-echo'] = slice_ticket('05')
        self.unit(tickets)
        report = self.report()
        minutes = {entry['slug']: entry['build_minutes'] for entry in report['tickets']}
        self.assertEqual(minutes, {'01-alpha': 30, '02-bravo': 60, '03-charlie': 30, '04-delta': None, '05-echo': None})

    def test_high_and_fix_rounds_come_from_the_metrics_line_and_are_null_when_it_lacks_them(self):
        """AC-7: 01 holds both (High 2, fix rounds 1); 02 holds `High 0` only (0 is a number, fix rounds null); 03 holds
        a Metrics line with neither; 04 has no Metrics line."""
        self.write_files()
        self.unit({
            '01-alpha': slice_ticket('01', status='done', body=metrics_line('High 2', 'fix rounds 1')),
            '02-bravo': slice_ticket('02', status='done', body=metrics_line('High 0')),
            '03-charlie': slice_ticket('03', status='done', body=metrics_line('full suites 3')),
            '04-delta': slice_ticket('04'),
        })
        report = self.report()
        seen = {entry['slug']: (entry['high'], entry['fix_rounds']) for entry in report['tickets']}
        self.assertEqual(seen, {'01-alpha': (2, 1), '02-bravo': (0, None), '03-charlie': (None, None),
                                '04-delta': (None, None)})

    def test_mr_holds_the_mr_reviewed_and_verified_values_of_mr_md_and_null_for_a_missing_line(self):
        """AC-8: all three lines give their values; a file that holds only the `MR:` line gives null for the other two."""
        self.write_files()
        self.unit(self.wave_tickets())
        write_text(self.folder / 'mr.md', MR_TEXT)
        self.assertEqual(self.report()['mr'], {
            'link': 'https://example.invalid/group/project/-/merge_requests/7',
            'reviewed': 'abc1234', 'verified': 'def5678'})
        write_text(self.folder / 'mr.md', 'MR: https://example.invalid/group/project/-/merge_requests/7\n')
        self.assertEqual(self.report()['mr'], {
            'link': 'https://example.invalid/group/project/-/merge_requests/7', 'reviewed': None, 'verified': None})

    def test_mr_has_all_three_values_null_when_there_is_no_mr_md(self):
        """AC-8. Assumed shape: `mr` is the object with three null values (the AC), not null itself."""
        self.write_files()
        self.unit(self.wave_tickets())
        self.assertEqual(self.report()['mr'], {'link': None, 'reviewed': None, 'verified': None})

    def test_stage_is_the_line_with_the_newest_ended_the_later_line_winning_a_tie_and_lines_without_ended_skipped(self):
        """AC-9: the newest `ended` is 12:00 on two lines (review, then ship later in the file), so ship wins; an
        older line comes after them in the file and a line with no `ended` comes last."""
        no_end = self.line('build', 'sess-alpha', '23:00', ticket='01')
        del no_end['ended']
        self.write_files([
            self.line('build', 'sess-alpha', '10:00', started='09:00', ticket='01'),
            self.line('review', 'sess-alpha', '12:00', ticket='01', mode='ticket'),
            self.line('ship', 'sess-alpha', '12:00'),
            self.line('build', 'sess-alpha', '09:30', ticket='02'),
            no_end,
        ])
        self.unit(self.wave_tickets())
        self.assertEqual(self.report()['stage'], {'name': 'ship', 'ended': '2026-10-01 12:00'})

    def test_stage_is_null_when_no_line_of_the_unit_has_an_ended_time(self):
        """AC-9: the unit has a work-unit line, but it has no `ended`."""
        no_end = self.line('build', 'sess-alpha', '10:00', ticket='01')
        del no_end['ended']
        self.write_files([no_end])
        self.unit(self.wave_tickets())
        self.assertIsNone(self.report()['stage'])

    def test_wave_counts_the_conduct_log_lines_that_start_with_wave(self):
        """AC-10: two `conduct` lines start with `wave `; a `conduct` line that starts with `waves`, a `conduct` line
        that only mentions a wave, and a `build` line that starts with `wave ` are not counted."""
        self.write_files()
        self.unit(self.wave_tickets())
        write_text(self.folder / 'log.md',
                   '2026-10-01 09:00 conduct: wave 1: 03-charlie\n'
                   '2026-10-01 10:00 build: wave 9 is not a conduct line\n'
                   '2026-10-01 11:00 conduct: wave 2: 04-delta\n'
                   '2026-10-01 12:00 conduct: waves are picked at run time\n'
                   '2026-10-01 13:00 conduct: finished the last wave\n')
        self.assertEqual(self.report()['wave'], 2)

    def test_wave_is_0_when_there_is_no_log_md(self):
        """AC-10."""
        self.write_files()
        self.unit(self.wave_tickets())
        self.assertEqual(self.report()['wave'], 0)

    def test_cost_holds_the_weighted_tokens_the_merged_tickets_and_the_build_minutes_of_the_unit(self):
        """AC-11: 3000 weighted tokens (alpha, bravo, charlie, echo; delta has no metrics row), 3 merged tickets, and
        120 build minutes over all build lines (30 + 60 + 30, the untimed ones add none)."""
        self.write_files()
        self.unit(self.wave_tickets())
        self.assertEqual(self.report()['cost'], {'weighted_tokens': 3000, 'merged': 3, 'build_minutes': 120})

    def test_cost_is_null_when_the_unit_has_no_work_unit_line(self):
        """AC-11: the only line in the work-unit file belongs to another unit."""
        self.write_files([self.line('build', 'sess-zulu', '09:30', started='09:00', ticket='01', feature='other-unit')])
        self.unit(self.wave_tickets())
        self.assertIsNone(self.report()['cost'])

    def test_unit_option_picks_the_named_unit(self):
        """AC-16: the unit is the name given, picked by `unit-option`."""
        self.write_files()
        self.unit(self.wave_tickets())
        report = self.report()
        self.assertEqual((report['unit'], report['picked_by']), (self.UNIT, 'unit-option'))

    def test_a_unit_name_with_no_folder_gives_unit_null_and_a_warning_that_names_it(self):
        """AC-16, D-26: the object holds only `schema`, `unit` and `warnings`; one warning names the missing unit;
        exit 0."""
        self.write_files()
        self.unit(self.wave_tickets())
        code, out, err = self.run_progress('--unit', 'no-such-unit')
        self.assertEqual(code, 0, (out, err))
        self.assertTrue(out.strip(), (code, err))
        report = json.loads(out)
        self.assertEqual(list(report), ['schema', 'unit', 'warnings'], (code, out, err))
        self.assertEqual((report['schema'], report['unit']), (1, None))
        self.assertTrue(any('no-such-unit' in warning for warning in report['warnings']), report['warnings'])

    def test_a_unit_value_that_is_not_one_plain_folder_name_gives_unit_null_and_a_warning(self):
        """AC-16, review round 1: `--unit ..` would name the folder that holds `.anomaly/`, and `.` or an empty
        value `.anomaly/` itself, outside every unit; each, and a value with a separator, is read as a name with no
        folder, never as that folder."""
        self.write_files()
        self.unit(self.wave_tickets())
        for value in ('..', '.', '', 'a/b'):
            with self.subTest(value=value):
                code, out, err = self.run_progress('--unit', value)
                self.assertEqual((code, err), (0, ''), out)
                report = json.loads(out)
                self.assertEqual(list(report), ['schema', 'unit', 'warnings'], out)
                self.assertEqual((report['schema'], report['unit']), (1, None))
                self.assertTrue(any(value in warning for warning in report['warnings']), report['warnings'])


class PickTheUnitTest(ProgressCase):
    """Ticket 03, AC-12 to AC-15: `progress --json` with no `--unit` picks the unit itself. Units are folders of
    the fixture repo's `.anomaly/` (git-excluded, ADR-0011); a unit's `log.md` lines set the newest-log order."""
    ALPHA, BRAVO, CHARLIE = 'alpha-unit', 'bravo-unit', 'charlie-unit'
    OPEN = {'01-first': slice_ticket('01')}   # a ticket not done

    def setUp(self):
        super().setUp()
        self.repo.write('.git/info/exclude', '.anomaly/\n')

    def put_unit(self, name, tickets=None, log=()):
        """The unit folder `.anomaly/<name>/` with these tickets (stem -> text; none: an empty `tickets/` folder) and
        these `log.md` lines (`<time> <stage>: <text>`, no log.md without any)."""
        folder = self.repo.root / '.anomaly' / name
        (folder / 'tickets').mkdir(parents=True, exist_ok=True)
        for stem, text in (tickets or {}).items():
            write_text(folder / 'tickets' / f'{stem}.md', text)
        if log:
            write_text(folder / 'log.md', ''.join(f'{line}\n' for line in log))

    def on_branch(self, name):
        """Make `name` the current branch of the fixture repo (it has no commit yet)."""
        self.repo.git('symbolic-ref', 'HEAD', f'refs/heads/{name}')

    def based_on(self, branch):
        return {'01-first': slice_ticket('01', body=f'Base: {branch}\n')}

    def pick(self, folder=None):
        """The parsed report of a run with no `--unit` from `folder` (default: the fixture repo); a clean run."""
        code, out, err = run_cli('progress', '--json', '--repo', str(folder or self.repo.root),
                                 '--home', str(self.home))
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(len(out.splitlines()), 1, out)
        return json.loads(out)

    def test_run_from_a_linked_worktree_it_reads_the_units_of_the_main_checkout(self):
        """AC-12: the unit exists only in the main checkout's `.anomaly/`, and the worktree has none."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.repo.write('README.md', 'x\n')
        self.repo.commit(['README.md'], 'chore: start', date(2026, 10, 1))
        linked = self.root / 'linked'
        self.repo.git('worktree', 'add', '-q', '-b', 'work/linked', str(linked))
        self.assertFalse((linked / '.anomaly').exists())
        self.assertEqual(self.pick(linked)['unit'], self.ALPHA)

    def test_run_from_a_folder_inside_dot_anomaly_it_reads_that_dot_anomaly(self):
        """AC-12, D-7 second Amended line: git ignores `.anomaly/`, so the folder is in no repository for git."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.assertEqual(self.pick(self.repo.root / '.anomaly' / self.ALPHA)['unit'], self.ALPHA)

    def test_a_ticket_base_equal_to_the_current_branch_picks_its_unit_with_picked_by_branch(self):
        """AC-13, AC-14 `Else`: the branch is bravo's default `feat/<slug>` name and bravo has the newer line (so the
        slug step and the fallback would both take bravo), yet alpha's `Base:` names the branch and wins."""
        self.put_unit(self.ALPHA, self.based_on('feat/bravo-unit'), ['2026-10-01 09:00 build: started'])
        self.put_unit(self.BRAVO, self.based_on('feat/other'), ['2026-10-02 09:00 build: started'])
        self.on_branch('feat/bravo-unit')
        report = self.pick()
        self.assertEqual((report['unit'], report['picked_by']), (self.ALPHA, 'branch'))

    def test_of_several_matching_units_the_newest_log_line_wins_and_a_warning_names_the_others(self):
        """AC-13: bravo has the newest line (alpha is first in name order, charlie is in between)."""
        self.put_unit(self.ALPHA, self.based_on('feat/shared'), ['2026-10-01 09:00 build: started'])
        self.put_unit(self.BRAVO, self.based_on('feat/shared'), ['2026-10-03 09:00 build: started'])
        self.put_unit(self.CHARLIE, self.based_on('feat/shared'), ['2026-10-02 09:00 build: started'])
        self.on_branch('feat/shared')
        report = self.pick()
        self.assertEqual((report['unit'], report['picked_by']), (self.BRAVO, 'branch'))
        warned = ' '.join(report['warnings'])
        self.assertIn(self.ALPHA, warned)
        self.assertIn(self.CHARLIE, warned)

    def test_of_several_matching_units_with_the_same_newest_time_the_first_in_name_order_wins(self):
        """AC-13: both newest lines read 10:00, and bravo is written first."""
        self.put_unit(self.BRAVO, self.based_on('feat/shared'), ['2026-10-02 10:00 build: started'])
        self.put_unit(self.ALPHA, self.based_on('feat/shared'), ['2026-10-02 10:00 review: done'])
        self.on_branch('feat/shared')
        report = self.pick()
        self.assertEqual((report['unit'], report['picked_by']), (self.ALPHA, 'branch'))
        self.assertIn(self.BRAVO, ' '.join(report['warnings']))

    def test_a_branch_pattern_with_only_slug_matches_the_unit_key_in_place_of_it(self):
        """AC-14, D-24: the `branch` port reads the profile key `branch_pattern`; bravo has the newer log line, so
        only the pattern can pick alpha."""
        write_text(self.home / 'profile.md', '---\nbranch_pattern: work/<slug>\n---\n')
        self.put_unit(self.ALPHA, self.OPEN)
        self.put_unit(self.BRAVO, self.OPEN, ['2026-10-02 09:00 build: started'])
        self.on_branch('work/alpha-unit')
        report = self.pick()
        self.assertEqual((report['unit'], report['picked_by']), (self.ALPHA, 'branch'))

    def test_a_branch_pattern_with_type_or_key_is_not_expanded(self):
        """AC-14, D-24: the current branch is what the pattern would give for alpha if `<type>` and `<key>` were
        filled in (`feat`, `no-ticket`), yet no branch pick happens; the newest log line (bravo) decides."""
        self.put_unit(self.ALPHA, self.OPEN)
        self.put_unit(self.BRAVO, self.OPEN, ['2026-10-02 09:00 build: started'])
        for pattern, branch in (('<type>/<slug>', 'feat/alpha-unit'), ('feat/<key>/<slug>', 'feat/no-ticket/alpha-unit')):
            with self.subTest(pattern=pattern):
                write_text(self.home / 'profile.md', f'---\nbranch_pattern: {pattern}\n---\n')
                self.on_branch(branch)
                report = self.pick()
                self.assertEqual((report['unit'], report['picked_by']), (self.BRAVO, 'newest-log'))

    def test_the_fallback_picks_the_unfinished_unit_with_the_newest_log_line_and_skips_the_others(self):
        """AC-15, D-25: bravo is the newest unfinished unit with a log line. Newer than it are the `adhoc` folder
        and a unit whose tickets are all done; a unit with no `log.md` and one whose `log.md` holds no line of the
        `<time> <stage>: <text>` shape have no time."""
        done = {'01-first': slice_ticket('01', status='done')}
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.put_unit(self.BRAVO, self.OPEN, ['2026-10-02 09:00 build: started', '2026-10-02 11:30 review: round 1'])
        self.put_unit('adhoc', self.OPEN, ['2026-10-05 09:00 build: started'])
        self.put_unit('finished-unit', done, ['2026-10-04 09:00 ship: merged'])
        self.put_unit('no-log-unit', self.OPEN)
        self.put_unit('no-line-unit', self.OPEN)
        write_text(self.repo.root / '.anomaly' / 'no-line-unit' / 'log.md', 'notes with no time\n')
        report = self.pick()
        self.assertEqual((report['unit'], report['picked_by']), (self.BRAVO, 'newest-log'))

    def test_the_fallback_counts_a_unit_with_no_tickets_as_unfinished(self):
        """AC-15: the empty unit has the newest line and no ticket at all."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.put_unit(self.BRAVO, None, ['2026-10-02 09:00 interview: started'])
        report = self.pick()
        self.assertEqual((report['unit'], report['picked_by']), (self.BRAVO, 'newest-log'))


class EveryCaseTest(ProgressCase):
    """Ticket 04, AC-17 to AC-21: every case gives a JSON object and exit 0; only bad arguments exit 2. The unit
    helpers are the ones of PickTheUnitTest. A file that is not UTF-8 is `b'\\xff\\xfe'`."""
    ALPHA, BRAVO = PickTheUnitTest.ALPHA, PickTheUnitTest.BRAVO
    OPEN = PickTheUnitTest.OPEN
    put_unit = PickTheUnitTest.put_unit
    on_branch = PickTheUnitTest.on_branch
    pick = PickTheUnitTest.pick
    NOT_UTF8 = b'\xff\xfe\n'
    WAVE_LOG = '2026-10-01 09:00 specify: done\n2026-10-01 10:00 conduct: wave 1: start\n'

    def setUp(self):
        super().setUp()
        self.repo.write('.git/info/exclude', '.anomaly/\n')

    def assert_unit_null(self, result, phrase):
        """D-26, D-16: exit 0, one JSON line, exactly `schema`, `unit` (null) and a `warnings` list with a text that
        holds `phrase`, the key words of that case's own warning."""
        code, out, err = result
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(len(out.splitlines()), 1, out)
        report = json.loads(out)
        self.assertEqual(list(report), ['schema', 'unit', 'warnings'], out)
        self.assertEqual((report['schema'], report['unit']), (1, None))
        self.assertIsInstance(report['warnings'], list)
        self.assert_warned_about(report, phrase)

    def assert_warned_about(self, report, *names):
        for name in names:
            self.assertTrue(any(name in warning for warning in report['warnings']), (name, report['warnings']))

    def assert_before_slice(self, report):
        """AC-18: no tickets and zero counts, yet the stage, wave, MR gate and cost of the fixture files."""
        self.assertEqual(report['unit'], self.UNIT)
        self.assertEqual(report['tickets'], [])
        self.assertEqual(report['counts'], {'done': 0, 'failed': 0, 'open': 0})
        self.assertEqual(report['next'], [])
        self.assertEqual(report['stage'], {'name': 'build', 'ended': '2026-10-01 17:03'})
        self.assertEqual(report['wave'], 1)
        self.assertEqual(report['mr'], {'link': 'https://example.invalid/group/project/-/merge_requests/7',
                                        'reviewed': 'abc1234', 'verified': 'def5678'})
        self.assertEqual(report['cost'], {'weighted_tokens': 3000, 'merged': 3, 'build_minutes': 120})

    def put_before_slice(self):
        """The fixture unit after specify: a `log.md` with one wave line, an `mr.md`, work-unit lines, no `tickets/`."""
        self.write_files()
        write_text(self.folder / 'log.md', self.WAVE_LOG)
        write_text(self.folder / 'mr.md', MR_TEXT)

    def test_with_no_dot_anomaly_folder_the_object_holds_unit_null_and_a_warning(self):
        """AC-17: the repository has no `.anomaly/` and no unit is named."""
        self.assert_unit_null(self.run_progress(), 'has no .anomaly/ folder')

    def test_with_no_unit_picked_the_object_holds_unit_null_and_a_warning(self):
        """AC-17: `.anomaly/` holds one unit, and all its tickets are done, so none is unfinished."""
        self.put_unit(self.ALPHA, {'01-first': slice_ticket('01', status='done')}, ['2026-10-01 09:00 ship: merged'])
        self.assert_unit_null(self.run_progress(), 'no work unit picked')

    def test_a_repo_folder_that_does_not_exist_gives_unit_null_and_a_warning(self):
        """AC-17, D-7 Amended: the missing folder is inside the fixture repository, whose unit would be picked if
        the walk up to the nearest existing parent were read as the repository."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.assert_unit_null(run_cli('progress', '--json', '--repo', str(self.repo.root / 'missing'),
                                      '--home', str(self.home)), '--repo is not a folder')

    def test_a_failing_git_call_gives_unit_null_and_a_warning(self):
        """AC-17, D-16 Amended: a `HEAD` that names an invalid branch still lets git find the repository, but
        `git branch --show-current` fails (a real git failure, no mock); the unit would be picked otherwise."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.repo.write('.git/HEAD', 'ref: refs/heads/a..b\n')
        self.assert_unit_null(self.run_progress(), 'git branch failed')

    def test_a_unit_with_no_tickets_folder_still_shows_its_stage_wave_mr_and_cost(self):
        """AC-18: the unit is named with `--unit`."""
        self.put_before_slice()
        self.assert_before_slice(self.report())

    def test_the_newest_log_pick_of_a_unit_with_no_tickets_folder_gives_the_same_report(self):
        """AC-18 Amended: no `--unit`; the unit has a `log.md` line and no `tickets/` folder."""
        self.put_before_slice()
        report = self.pick()
        self.assertEqual(report['picked_by'], 'newest-log')
        self.assert_before_slice(report)

    def assert_left_out(self, report, shown, *left_out):
        self.assertEqual([entry['slug'] for entry in report['tickets']], shown)
        self.assert_warned_about(report, *left_out)

    def test_a_ticket_that_is_not_utf8_is_left_out_and_named_in_a_warning(self):
        """AC-19."""
        self.unit({'02-bravo': slice_ticket('02'), '03-charlie': slice_ticket('03')})
        (self.folder / 'tickets' / '01-alpha.md').write_bytes(self.NOT_UTF8)
        self.assert_left_out(self.report(), ['02-bravo', '03-charlie'], '01-alpha')

    def test_a_ticket_not_done_with_no_blocked_by_line_is_left_out_and_named_in_a_warning(self):
        """AC-19."""
        self.unit({'01-alpha': slice_ticket('01'), '03-charlie': slice_ticket('03'),
                   '02-bravo': slice_ticket('02').replace('Blocked by: none\n', '')})
        self.assert_left_out(self.report(), ['01-alpha', '03-charlie'], '02-bravo')

    def test_a_ticket_with_a_blocker_that_has_no_ticket_file_is_left_out_and_named_in_a_warning(self):
        """AC-19: blocker 09 has no `09-*.md`."""
        self.unit({'01-alpha': slice_ticket('01'), '02-bravo': slice_ticket('02', blocked='09'),
                   '03-charlie': slice_ticket('03')})
        self.assert_left_out(self.report(), ['01-alpha', '03-charlie'], '02-bravo')

    def test_a_ticket_whose_blocker_file_is_not_utf8_is_left_out_and_named_in_a_warning(self):
        """AC-19: 02 is blocked by 01, whose file is not UTF-8; the independent 03 still shows."""
        self.unit({'02-bravo': slice_ticket('02', blocked='01'), '03-charlie': slice_ticket('03')})
        (self.folder / 'tickets' / '01-alpha.md').write_bytes(self.NOT_UTF8)
        self.assert_left_out(self.report(), ['03-charlie'], '02-bravo')

    def test_the_pick_leaves_out_a_ticket_of_another_unit_that_is_not_utf8_and_names_it(self):
        """AC-19 Amended: bravo has the broken ticket and no log line; alpha is picked, exit 0."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.put_unit(self.BRAVO)
        (self.repo.root / '.anomaly' / self.BRAVO / 'tickets' / '02-broken.md').write_bytes(self.NOT_UTF8)
        self.on_branch('feat/other')
        report = self.pick()
        self.assertEqual(report['unit'], self.ALPHA)
        self.assert_warned_about(report, '02-broken')

    def test_the_pick_leaves_out_a_log_md_of_another_unit_that_is_not_utf8_and_names_it(self):
        """AC-19 Amended: bravo's `log.md` is not UTF-8, so it has no time; alpha is picked, exit 0."""
        self.put_unit(self.ALPHA, self.OPEN, ['2026-10-01 09:00 build: started'])
        self.put_unit(self.BRAVO, self.OPEN)
        (self.repo.root / '.anomaly' / self.BRAVO / 'log.md').write_bytes(self.NOT_UTF8)
        report = self.pick()
        self.assertEqual(report['unit'], self.ALPHA)
        self.assertTrue(any(self.BRAVO in warning and 'log.md' in warning for warning in report['warnings']),
                        report['warnings'])

    def test_an_mr_md_that_is_not_utf8_gives_mr_null_and_a_warning_while_the_rest_shows(self):
        """AC-20."""
        self.write_files()
        self.unit(self.wave_tickets())
        (self.folder / 'mr.md').write_bytes(self.NOT_UTF8)
        report = self.report()
        self.assertIsNone(report['mr'])
        self.assert_warned_about(report, 'mr.md')
        self.assertEqual(len(report['tickets']), 4)

    def test_a_log_md_that_is_not_utf8_gives_wave_0_and_a_warning_while_the_rest_shows(self):
        """AC-20 Amended (ticket 02 review): with `--unit`, and with no `--unit` through a branch pick, which reads
        the same log.md; either way exactly one warning names it."""
        self.write_files()
        tickets = self.wave_tickets()
        tickets['01-alpha'] = slice_ticket('01', status='done', body='Base: feat/track\n')
        self.unit(tickets)
        self.on_branch('feat/track')
        (self.folder / 'log.md').write_bytes(self.NOT_UTF8)
        for picked_by, report in (('unit-option', self.report()), ('branch', self.pick())):
            with self.subTest(picked_by=picked_by):
                self.assertEqual(report['picked_by'], picked_by)
                self.assertEqual(report['wave'], 0)
                self.assertEqual(len([text for text in report['warnings'] if 'log.md' in text]), 1, report['warnings'])
                self.assertEqual(len(report['tickets']), 4)

    def test_an_unreadable_work_units_or_metrics_file_gives_stage_and_cost_null_and_a_warning(self):
        """AC-20 Amended (ticket 02 review): each file in turn is not UTF-8."""
        for name in ('work-units.jsonl', 'metrics.jsonl'):
            with self.subTest(file=name):
                self.write_files()
                self.unit(self.wave_tickets())
                (self.home / name).write_bytes(self.NOT_UTF8)
                report = self.report()
                self.assertEqual((report['stage'], report['cost']), (None, None))
                self.assert_warned_about(report, name)
                self.assertEqual(len(report['tickets']), 4)

    def test_an_unfilled_home_placeholder_is_the_first_warning_and_stdout_holds_only_the_json(self):
        """AC-20 Amended (wave 4 plan): another warning exists (ticket 02 has a blocker with no file), so the notice
        is first because of its place, not because it is alone. Nothing goes to stderr."""
        self.write_files()
        self.unit({'01-alpha': slice_ticket('01', status='done'), '02-bravo': slice_ticket('02', blocked='09')})
        option, environ = '${user_config.home}', {paths.HOME_ENV: str(self.home)}
        code, out, err = run_cli('progress', '--json', '--unit', self.UNIT, '--repo', str(self.repo.root),
                                 '--home', option, environ=environ)
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(len(out.splitlines()), 1, out)
        report = json.loads(out)
        self.assertGreater(len(report['warnings']), 1, report['warnings'])
        self.assertEqual(report['warnings'][0], paths.home_notice(option, environ))

    def test_progress_without_json_or_with_an_unknown_option_exits_2_with_one_anomaly_line(self):
        """AC-21: assert_cli_error holds the exit code 2, the one `anomaly: ` line on stderr and no traceback."""
        for argv in (('progress',), ('progress', '--json', '--no-such-option')):
            with self.subTest(argv=argv):
                assert_cli_error(self, run_cli(*argv))


class ReferenceTest(unittest.TestCase):
    REFERENCE = PLUGIN.parent.parent / 'docs' / 'reference.md'

    def test_the_reference_progress_section_names_every_field_and_states_the_schema_change_rule(self):
        """AC-23: the section from `## Progress` to the next `## ` heading has one field line (`- `name`:`) for each
        field of the two pinned lists and states that changes only add fields and a rename or a removal raises
        `schema`."""
        if not self.REFERENCE.is_file():
            self.skipTest('no docs/reference.md two folders above the plugin: an installed copy, not the repository')
        text = self.REFERENCE.read_text(encoding='utf-8')
        start = re.search(r'^## Progress[ \t]*$', text, re.MULTILINE)
        self.assertIsNotNone(start, 'docs/reference.md has no "## Progress" section')
        section = text[start.end():].split('\n## ', 1)[0]
        missing = [name for name in TOP_FIELDS + TICKET_FIELDS
                   if not re.search(rf'^- `{re.escape(name)}`:', section, re.MULTILINE)]
        self.assertEqual(missing, [], 'fields the ## Progress section has no "- `name`:" line for')
        lowered = section.lower()
        for phrase in ('only add', 'rename', 'remov', 'raises `schema`'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, lowered)


if __name__ == '__main__':
    unittest.main()

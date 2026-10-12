"""Tests for `progress --json --unit <name> --repo <checkout>` (ticket 02), CLI in-process. The fixture is a git
repository with a unit folder `.anomaly/<unit>/` (tickets, and `mr.md` and `log.md` where a test needs them), and the
test home holds `work-units.jsonl` and `metrics.jsonl` as the `worklog report` tests build them (the unit folder's
name is the work unit name). One layer: every test runs the command and reads the one JSON line it prints (D-29)."""
import json
import unittest

from tests import test_worklog
from tests.fixtures import GitFixture, run_cli, write_text
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


if __name__ == '__main__':
    unittest.main()

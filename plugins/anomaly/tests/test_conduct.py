"""Tests for `conduct status <work unit folder>` (ticket 05), CLI in-process: the wave report, five lines in the
order done, failed, open, next, cost (AC-27). The fixture unit is a folder `.anomaly/<unit>/` with tickets, and the
test home holds `work-units.jsonl` and `metrics.jsonl` as the `worklog report` tests build them (the unit folder's
name is the work unit name). Lines are checked by label, count and ticket name, never by wording."""
import re
import unittest

from tests import test_worklog
from tests.fixtures import assert_cli_error, run_cli, write_text
from tests.test_check import slice_ticket
from tests.test_frontier import stories_text, without_line

LABELS = ('done', 'failed', 'open', 'next', 'cost')


def has_count(line, number):
    """True when `number` stands alone in `line` as a whole number."""
    return re.search(rf'(?<![\d.]){number}(?![\d.])', line) is not None


class ConductStatusTest(test_worklog.ReportCase):
    def unit(self, tickets):
        """The folder of the fixture unit; `tickets` maps a file stem (`02-bravo`) to its text."""
        folder = self.root / '.anomaly' / self.UNIT
        write_text(folder / 'stories.md', stories_text(1))
        for stem, text in tickets.items():
            write_text(folder / 'tickets' / f'{stem}.md', text)
        return folder

    def wave_tickets(self):
        """One ticket of each kind: done, in progress with no Result line, startable, blocked by the running one."""
        return {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='01', status='in-progress'),
            '03-charlie': slice_ticket('03', blocked='01'),
            '04-delta': slice_ticket('04', blocked='02'),
        }

    def status(self, folder):
        return run_cli('conduct', 'status', str(folder), '--home', str(self.home))

    def status_lines(self, folder):
        code, out, err = self.status(folder)
        self.assertEqual((code, err), (0, ''), out)
        return out.splitlines()

    def cost_of_report(self):
        costs = [line for line in self.report_lines() if line.startswith('cost:')]
        self.assertEqual(len(costs), 1, costs)
        return costs[0]

    def test_it_prints_five_lines_labelled_done_failed_open_next_cost_with_the_counts_and_tickets_of_the_unit(self):
        """AC-27: alpha is done; bravo is in progress with no Result line, so failed; charlie can start; delta waits."""
        self.write_files()
        lines = self.status_lines(self.unit(self.wave_tickets()))
        self.assertEqual(len(lines), 5, lines)
        for line, label in zip(lines, LABELS):
            self.assertTrue(line.startswith(label), (label, line))
        done, failed, opened, following, _ = lines
        self.assertTrue(has_count(done, 1), done)
        self.assertTrue(has_count(failed, 1) and 'bravo' in failed, failed)
        self.assertTrue(has_count(opened, 2) and 'charlie' in opened and 'delta' in opened, opened)
        self.assertNotIn('bravo', opened)
        self.assertTrue('charlie' in following, following)
        for other in ('alpha', 'bravo', 'delta'):
            self.assertNotIn(other, following)

    def test_an_in_progress_ticket_with_a_result_line_is_open_and_not_failed(self):
        """AC-27 (settled): failed is in progress with no Result line; with one the ticket stays in open."""
        self.write_files()
        tickets = self.wave_tickets()
        tickets['02-bravo'] = slice_ticket('02', blocked='01', status='in-progress', body='Result: branch · sha\n')
        lines = self.status_lines(self.unit(tickets))
        done, failed, opened, following, _ = lines
        self.assertTrue(has_count(failed, 0) and 'bravo' not in failed, failed)
        self.assertTrue(has_count(opened, 3) and 'bravo' in opened, opened)
        self.assertTrue(has_count(done, 1), done)

    def test_a_unit_with_no_startable_ticket_says_none_for_next(self):
        """AC-27: bravo runs and charlie waits for it, so nothing can start and next names no ticket."""
        self.write_files()
        tickets = self.wave_tickets()
        del tickets['04-delta']
        tickets['03-charlie'] = slice_ticket('03', blocked='02')
        lines = self.status_lines(self.unit(tickets))
        self.assertEqual(len(lines), 5, lines)
        self.assertTrue('none' in lines[3] and not any(name in lines[3] for name in ('alpha', 'bravo', 'charlie')),
                        lines[3])

    def test_the_cost_line_is_the_cost_line_of_worklog_report_for_the_unit_and_home(self):
        """AC-27."""
        self.write_files()
        lines = self.status_lines(self.unit(self.wave_tickets()))
        self.assertEqual(lines[4], self.cost_of_report())

    def test_a_unit_with_no_measured_session_still_prints_five_lines_and_the_same_cost_line_as_the_report(self):
        """AC-27: the only session has no metrics row, so the report counts it as unmeasured; no ticket runs, so
        failed says 0."""
        self.write_files([self.line('build', 'sess-delta', '16:12', started='16:02', ticket='01')], weighted={})
        folder = self.unit({'01-alpha': slice_ticket('01', status='done'), '02-bravo': slice_ticket('02', blocked='01')})
        lines = self.status_lines(folder)
        self.assertEqual(len(lines), 5, lines)
        for line, label in zip(lines, LABELS):
            self.assertTrue(line.startswith(label), (label, line))
        self.assertTrue(has_count(lines[1], 0), lines[1])
        self.assertEqual(lines[4], self.cost_of_report())

    def test_a_unit_with_no_work_unit_line_exits_2_naming_the_unit_like_the_report(self):
        """AC-27: the cost line is the cost line of worklog report, so a unit that report refuses ends the
        command; nothing is printed."""
        result = self.status(self.unit(self.wave_tickets()))
        assert_cli_error(self, result, self.UNIT)
        self.assertEqual(result[1], '')

    def test_a_ticket_without_a_blocked_by_line_makes_it_exit_2_naming_the_ticket(self):
        """AC-27 (Amended): the AC-4 error of the frontier rule ends the command; nothing is printed."""
        self.write_files()
        tickets = self.wave_tickets()
        tickets['03-charlie'] = without_line(tickets['03-charlie'], 'Blocked by')
        result = self.status(self.unit(tickets))
        assert_cli_error(self, result, '03-charlie')
        self.assertEqual(result[1], '')


if __name__ == '__main__':
    unittest.main()

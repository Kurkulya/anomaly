"""Tests for the `frontier <work unit folder>` command (ticket 04), CLI in-process over fixture units in both
layouts: `.anomaly/<unit>/tickets/` with `stories.md`, and `.scratch/<unit>/issues/` with `spec.md`.
AC-1 to AC-4 of the ticket, with the dated Amended line that makes an in-progress ticket a line of its own.
Output is checked by ticket names (the file-name slug), AC ids, blocker numbers and exit codes, never by wording;
stdout and stderr are read together, because the ACs fix no stream."""
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path

from tests.fixtures import run_cli, write_text
from tests.test_check import slice_ticket

Layout = namedtuple('Layout', 'root tickets stories')
LAYOUTS = (Layout('.anomaly', 'tickets', 'stories.md'), Layout('.scratch', 'issues', 'spec.md'))


def stories_text(count):
    return '# Stories\n\n' + ''.join(f'- AC-{n}: criterion {n}\n' for n in range(1, count + 1))


def without_line(text, key):
    return ''.join(line for line in text.splitlines(True) if not line.startswith(f'{key}:'))


def marks_in_progress(line):
    return 'in progress' in line.lower() or 'in-progress' in line.lower()


class FrontierTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def unit(self, layout, tickets, acs=1):
        """The folder of a work unit in this layout; `tickets` maps a file stem (`02-bravo`) to its text."""
        folder = self.root / layout.root / 'unit'
        write_text(folder / layout.stories, stories_text(acs))
        for stem, text in tickets.items():
            write_text(folder / layout.tickets / f'{stem}.md', text)
        return folder

    def frontier(self, folder):
        """(exit code, stdout and stderr together)."""
        code, out, err = run_cli('frontier', str(folder))
        return code, out + err

    def lines_naming(self, output, slug):
        return [line for line in output.splitlines() if slug in line]

    def test_prints_each_startable_ticket_once_in_ticket_order_and_no_other(self):
        """AC-1: a ticket whose blockers are all done and that is not done is startable, whatever other status
        it has; a ticket with one done and one open blocker is not."""
        tickets = {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='01'),
            '03-charlie': slice_ticket('03', blocked='02'),
            '04-delta': slice_ticket('04', blocked='01', status='ready-for-human'),
            '05-echo': slice_ticket('05', blocked='None'),
            '06-foxtrot': slice_ticket('06', blocked='01, 02'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 0, output)
                for slug in ('bravo', 'delta', 'echo'):
                    self.assertEqual(len(self.lines_naming(output, slug)), 1, (slug, output))
                for slug in ('alpha', 'charlie', 'foxtrot'):
                    self.assertEqual(self.lines_naming(output, slug), [], (slug, output))
                self.assertLess(output.index('bravo'), output.index('delta'))
                self.assertLess(output.index('delta'), output.index('echo'))

    def test_blocked_by_none_in_lower_case_is_no_blocker(self):
        """Notes of the ticket: `Blocked by: none` means no blocker (the `None` case is in the first test)."""
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, {'01-alpha': slice_ticket('01', blocked='none')}))
                self.assertEqual(code, 0, output)
                self.assertEqual(len(self.lines_naming(output, 'alpha')), 1, output)

    def test_a_blocked_by_value_that_holds_no_ticket_number_is_not_startable(self):
        """`Blocked by: TBD` cannot be read, so the ticket is blocked, as `ticket gate` treats it: it is not listed
        while another ticket is startable."""
        tickets = {'01-alpha': slice_ticket('01', status='done'), '02-bravo': slice_ticket('02', blocked='TBD'),
                   '03-charlie': slice_ticket('03', blocked='01')}
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 0, output)
                self.assertEqual(self.lines_naming(output, 'bravo'), [], output)
                self.assertEqual(len(self.lines_naming(output, 'charlie')), 1, output)

    def test_a_ticket_with_an_unreadable_blocked_by_is_named_with_the_value_when_it_is_the_only_open_one(self):
        """The same unreadable ticket with nothing else open: no startable ticket, so it is named with its value
        and the exit code is 1."""
        tickets = {'01-alpha': slice_ticket('01', status='done'), '02-bravo': slice_ticket('02', blocked='TBD')}
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 1, output)
                waiting = self.lines_naming(output, 'bravo')
                self.assertEqual(len(waiting), 1, output)
                self.assertIn('TBD', waiting[0])

    def test_an_in_progress_ticket_is_a_marked_line_of_its_own_and_not_startable(self):
        """AC-1 (Amended): the in-progress ticket is printed marked in progress; the startable one is not marked;
        a ticket blocked by the in-progress one is not printed."""
        tickets = {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='01', status='in-progress'),
            '03-charlie': slice_ticket('03', blocked='01'),
            '04-delta': slice_ticket('04', blocked='02'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 0, output)
                running = self.lines_naming(output, 'bravo')
                self.assertEqual(len(running), 1, output)
                self.assertTrue(marks_in_progress(running[0]), running)
                startable = self.lines_naming(output, 'charlie')
                self.assertEqual(len(startable), 1, output)
                self.assertFalse(marks_in_progress(startable[0]), startable)
                self.assertEqual(self.lines_naming(output, 'delta'), [], output)

    def test_with_only_in_progress_tickets_left_it_lists_them_and_exits_0(self):
        """AC-3 (Amended): in-progress tickets are neither startable nor blocked, so the unit is not stuck."""
        tickets = {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='01', status='in-progress'),
            '03-charlie': slice_ticket('03', blocked='01', status='in-progress'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 0, output)
                for slug in ('bravo', 'charlie'):
                    lines = self.lines_naming(output, slug)
                    self.assertEqual(len(lines), 1, (slug, output))
                    self.assertTrue(marks_in_progress(lines[0]), lines)
                self.assertEqual(self.lines_naming(output, 'alpha'), [], output)

    def test_with_an_in_progress_ticket_and_a_blocked_one_and_none_startable_it_lists_both_and_exits_0(self):
        """AC-3 (Amended): the unit is not stuck while a ticket runs, so the waiting ticket is named with its
        unfinished blocker and the exit code is 0."""
        tickets = {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='01', status='in-progress'),
            '03-charlie': slice_ticket('03', blocked='02'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 0, output)
                running = self.lines_naming(output, 'bravo')
                self.assertEqual(len(running), 1, output)
                self.assertTrue(marks_in_progress(running[0]), running)
                waiting = self.lines_naming(output, 'charlie')
                self.assertEqual(len(waiting), 1, output)
                self.assertIn('02', waiting[0])

    def test_warns_once_for_each_story_ac_that_no_ticket_covers_and_names_it(self):
        """AC-2: stories.md (spec.md in the old layout) holds AC-1 to AC-4; a done ticket covers AC-1, an open one
        covers AC-3 and AC-1 again, one covers none; AC-2 and AC-4 are named, the covered ones are not."""
        tickets = {
            '01-alpha': slice_ticket('01', covers='AC-1', status='done'),
            '02-bravo': slice_ticket('02', covers='AC-3, AC-1', blocked='01'),
            '03-charlie': slice_ticket('03', covers='none', blocked='01'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                _, output = self.frontier(self.unit(layout, tickets, acs=4))
                for ac in ('AC-2', 'AC-4'):
                    self.assertEqual(len(self.lines_naming(output, ac)), 1, (ac, output))
                for ac in ('AC-1', 'AC-3'):
                    self.assertEqual(self.lines_naming(output, ac), [], (ac, output))

    def test_with_no_startable_ticket_it_names_each_open_ticket_with_its_unfinished_blockers_and_exits_1(self):
        """AC-3: 02 and 03 wait for each other, 04 waits for both, and 03 also has a done blocker, which is not
        named. Read per line: a ticket and its blockers are on the line that names the ticket."""
        tickets = {
            '01-alpha': slice_ticket('01', status='done'),
            '02-bravo': slice_ticket('02', blocked='03'),
            '03-charlie': slice_ticket('03', blocked='01, 02'),
            '04-delta': slice_ticket('04', blocked='02, 03'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 1, output)
                bravo, charlie, delta = (' '.join(self.lines_naming(output, slug)) for slug in ('bravo', 'charlie', 'delta'))
                self.assertIn('03', bravo)
                self.assertIn('02', charlie)
                self.assertNotIn('01', charlie)
                self.assertIn('02', delta)
                self.assertIn('03', delta)

    def test_with_every_ticket_done_it_says_the_unit_is_finished_and_exits_0(self):
        """AC-3: no ticket is listed; the message says finished."""
        tickets = {'01-alpha': slice_ticket('01', status='done'), '02-bravo': slice_ticket('02', blocked='01', status='done')}
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 0, output)
                self.assertIn('finished', output.lower())
                for slug in ('alpha', 'bravo'):
                    self.assertEqual(self.lines_naming(output, slug), [], (slug, output))

    def test_a_missing_stories_file_is_one_warning_naming_it_and_the_tickets_are_still_listed(self):
        """A unit with no AC file (stories.md, or spec.md in the old layout): the tickets are read, one `warning:` line
        names the files that are missing (spec.md or stories.md), and the exit code is the one the tickets give."""
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                folder = self.unit(layout, {'01-alpha': slice_ticket('01')})
                (folder / layout.stories).unlink()
                code, output = self.frontier(folder)
                self.assertEqual(code, 0, output)
                self.assertEqual(len(self.lines_naming(output, 'alpha')), 1, output)
                warnings = self.lines_naming(output, 'stories.md')
                self.assertEqual(len(warnings), 1, output)
                self.assertTrue(warnings[0].startswith('warning:'), warnings)

    def test_a_unit_with_both_spec_and_stories_reads_the_acs_of_spec_md(self):
        """ADR-0011: spec.md is read when the unit has one, else stories.md. Here spec.md holds AC-2, which no ticket
        covers, and stories.md holds only AC-1; the warning names spec.md and AC-2."""
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                folder = self.unit(layout, {'01-alpha': slice_ticket('01', covers='AC-1')})
                write_text(folder / 'spec.md', stories_text(2))
                write_text(folder / 'stories.md', stories_text(1))
                code, output = self.frontier(folder)
                self.assertEqual(code, 0, output)
                warnings = self.lines_naming(output, 'AC-2')
                self.assertEqual(len(warnings), 1, output)
                self.assertIn('spec.md', warnings[0])

    def test_a_unit_with_no_ticket_file_is_an_error_naming_the_folder_and_exits_2(self):
        """A unit with no tickets folder, or an empty one, has nothing to list: not "finished"."""
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root, tickets='no folder'):
                folder = self.unit(layout, {})
                code, output = self.frontier(folder)
                self.assertEqual(code, 2, output)
                self.assertIn(str(folder), output)
            with self.subTest(layout=layout.root, tickets='empty folder'):
                folder = self.unit(layout, {})
                (folder / layout.tickets).mkdir()
                code, output = self.frontier(folder)
                self.assertEqual(code, 2, output)
                self.assertIn(str(folder), output)

    def test_a_ticket_with_no_blocked_by_line_is_an_error_naming_it_and_exits_2(self):
        """AC-4: the ticket with no line is named even when other tickets are startable."""
        tickets = {
            '01-alpha': slice_ticket('01'),
            '02-bravo': without_line(slice_ticket('02'), 'Blocked by'),
        }
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 2, output)
                self.assertTrue(self.lines_naming(output, 'bravo'), output)

    def test_a_blocker_number_with_no_ticket_file_is_an_error_naming_the_ticket_and_exits_2(self):
        """AC-4: ticket 02 names blocker 07 and the unit has no 07-*.md."""
        tickets = {'01-alpha': slice_ticket('01'), '02-bravo': slice_ticket('02', blocked='01, 07')}
        for layout in LAYOUTS:
            with self.subTest(layout=layout.root):
                code, output = self.frontier(self.unit(layout, tickets))
                self.assertEqual(code, 2, output)
                self.assertTrue(self.lines_naming(output, 'bravo'), output)


if __name__ == '__main__':
    unittest.main()

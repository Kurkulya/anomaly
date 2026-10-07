import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import index, records
from tests.fixtures import anomaly_text, run_cli, write_anomaly_text, write_text


class IndexCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'


class PortedIndexTest(IndexCase):
    def test_index_lists_active_rows_and_closed_section(self):
        write_anomaly_text(self.home, 'a', 2, 2)
        write_anomaly_text(self.home, 'done', 1, 1, status='wontfix')
        text = index.write_index(self.home, date(2026, 10, 3))
        self.assertIn('| 4 | [a](anomalies/a.md) |', text)
        self.assertIn('## Closed', text)
        self.assertIn('[done](anomalies/done.md) — wontfix', text)
        self.assertEqual((self.home / 'INDEX.md').read_text(encoding='utf-8'), text)


class IndexTextTest(IndexCase):
    def test_open_rows_are_ranked_and_closed_ones_listed_separately(self):
        write_anomaly_text(self.home, 'low', 1, 1)
        write_anomaly_text(self.home, 'win-big', 3, 2, kind='win', last_seen='2026-09-01')
        write_anomaly_text(self.home, 'top', 2, 3, last_seen='2026-10-02')
        write_anomaly_text(self.home, 'back', 1, 2, status='reopened')
        write_anomaly_text(self.home, 'done', 3, 5, status='fixed')
        text = index.write_index(self.home, date(2026, 10, 4))
        lines = text.splitlines()
        self.assertEqual(lines[0], '# Anomaly backlog')
        self.assertIn('Generated 2026-10-04 by `anomaly index`. Do not edit by hand.', text)
        self.assertIn('4 open · 1 closed · score = impact × occurrences', text)
        rows = [line for line in lines if line.startswith('| ') and '](anomalies/' in line]
        self.assertEqual([row.split('[')[1].split(']')[0] for row in rows], ['top', 'win-big', 'back', 'low'])
        self.assertTrue(rows[1].startswith('| 6 | [win-big](anomalies/win-big.md) | win | tool-economy |'))
        open_part, closed_part = text.split('## Closed')
        self.assertIn('- [done](anomalies/done.md) — fixed', closed_part)
        self.assertNotIn('[done]', open_part)

    def test_a_pipe_in_a_value_does_not_break_the_table(self):
        write_text(self.home / 'anomalies' / 'p.md', anomaly_text('p', 1, 1).replace('target:', 'target: a | b'))
        self.assertIn('a \\| b', index.write_index(self.home, date(2026, 10, 4)))

    def test_empty_home_gives_an_empty_table_and_no_closed_section(self):
        text = index.write_index(self.home, date(2026, 10, 4))
        self.assertIn('0 open · 0 closed', text)
        self.assertNotIn('## Closed', text)


class IndexCommandTest(IndexCase):
    def test_index_subcommand_writes_the_file_with_the_injected_date_and_needs_no_data_folder(self):
        write_anomaly_text(self.home, 'a', 2, 2)
        code, out, err = run_cli('index', '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('index: 1 open, 0 closed', out)
        self.assertIn(str(self.home / 'INDEX.md'), out)
        self.assertIn('Generated 2026-10-04', (self.home / 'INDEX.md').read_text(encoding='utf-8'))

    def test_an_unreadable_record_is_reported_as_an_anomaly_error(self):
        (self.home / 'anomalies' / 'bad.md').mkdir(parents=True)
        code, _, err = run_cli('index', '--home', str(self.home))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))

    def test_an_invalid_record_stops_the_index_and_names_the_file(self):
        write_anomaly_text(self.home, 'fine', 1, 1)
        write_anomaly_text(self.home, 'odd', 1, 1, category='misc')
        code, out, err = run_cli('index', '--home', str(self.home))
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: '))
        self.assertIn('odd.md', err)
        self.assertIn("category 'misc'", err)
        self.assertNotIn('fine.md', err)
        self.assertFalse((self.home / 'INDEX.md').exists())

    def test_a_file_name_that_differs_from_its_signature_is_invalid(self):
        write_text(self.home / 'anomalies' / 'other-name.md', anomaly_text('a', 1, 1))
        code, _, err = run_cli('index', '--home', str(self.home))
        self.assertEqual(code, 2)
        self.assertIn('other-name.md', err)

    def test_records_are_read_once_per_run(self):
        write_anomaly_text(self.home, 'a', 2, 2)
        with mock.patch.object(records, 'read_anomaly', wraps=records.read_anomaly) as read:
            run_cli('index', '--home', str(self.home))
        self.assertEqual(read.call_count, 1)


if __name__ == '__main__':
    unittest.main()

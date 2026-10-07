import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from anomaly_loop import constants, nudge, records
from tests.fixtures import NOW, context, metrics_row, run_cli, write_anomaly_with, write_build_skills_profile, write_metrics_rows

HOOKS_FILE = Path(__file__).resolve().parents[1] / 'hooks' / 'hooks.json'
PLUGIN_FILE = Path(__file__).resolve().parents[1] / '.claude-plugin' / 'plugin.json'
MONDAY, TUESDAY, NEXT_WEEK = date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 12)
REVIEW = 'Say "calibrate" to review.'


class NudgeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        write_build_skills_profile(self.home)
        self.data = self.root / 'data'
        self.marker = self.data / constants.NUDGE_MARKER_FILE

    def add(self, signature, impact, occurrences, **fields):
        return write_anomaly_with(self.home, signature, impact=impact, occurrences=occurrences, **fields)

    def due(self, signature, check_by, result=''):
        experiment = records.Experiment(expect='faster', metric='active minutes', guard='rework',
                                        check_by=check_by, result=result)
        return write_anomaly_with(self.home, signature, status='fixed', fixed_by='a change',
                                  experiment=experiment)

    def line(self, today):
        return nudge.nudge_line(context(self.home, today=today), self.marker)


class NudgeLineTest(NudgeCase):
    def test_nudge_fires_once_per_week_and_only_above_threshold(self):
        self.add('small', 1, 3)
        self.assertIsNone(self.line(MONDAY))
        self.add('big', 2, 2)
        self.assertIsNone(self.line(TUESDAY))
        text = self.line(NEXT_WEEK)
        self.assertIn('1 open problem', text)
        self.assertIn('top: big (4)', text)

    def test_the_line_counts_problems_names_the_top_one_and_says_what_to_do(self):
        self.add('big', 2, 2)
        self.add('bigger', 3, 2)
        self.assertEqual(self.line(MONDAY),
                         f'anomaly: 2 open problems with score >= 4 (top: bigger (6)). {REVIEW}')

    def test_the_threshold_is_the_constant(self):
        self.add('edge', 1, constants.NUDGE_MIN_SCORE)
        self.assertIn('1 open problem', self.line(MONDAY))

    def test_only_open_or_reopened_problems_count(self):
        self.add('fixed-one', 3, 3, status='fixed')
        self.add('dropped', 3, 3, status='wontfix')
        self.add('a-win', 3, 3, kind='win', proposed_fix='')
        self.assertIsNone(self.line(MONDAY))
        self.add('back', 2, 2, status='reopened')
        self.assertIn('top: back (4)', self.line(NEXT_WEEK))

    def test_a_due_experiment_nudges_even_without_a_hot_problem(self):
        self.due('slow-fix', '2026-10-05')
        self.assertEqual(self.line(MONDAY), f'anomaly: 1 experiment due. {REVIEW}')

    def test_problems_and_due_experiments_share_one_line(self):
        self.add('big', 2, 2)
        self.due('slow-fix', '2026-10-01')
        self.due('slow-fix-two', '2026-09-01')
        text = self.line(MONDAY)
        self.assertEqual(text, f'anomaly: 1 open problem with score >= 4 (top: big (4)); 2 experiments due. '
                               f'{REVIEW}')
        self.assertNotIn('\n', text)

    def test_an_experiment_due_by_its_sessions_nudges_through_the_shared_due_rule(self):
        experiment = records.Experiment(expect='faster', metric='active minutes', guard='rework sightings',
                                        kind='build', check_by='2026-11-01')
        write_anomaly_with(self.home, 'slow-fix', status='fixed', fixed_by='2026-09-28 · abc1234',
                           experiment=experiment)
        days = [date(2026, 9, 29) + timedelta(days=n % 6) for n in range(19)]
        write_metrics_rows(self.home, [metrics_row(f's{n}', day, skills=['implement']) for n, day in enumerate(days)])
        self.assertIsNone(self.line(MONDAY))
        days.append(date(2026, 10, 3))
        write_metrics_rows(self.home, [metrics_row(f's{n}', day, skills=['implement']) for n, day in enumerate(days)])
        self.assertEqual(self.line(NEXT_WEEK), f'anomaly: 1 experiment due. {REVIEW}')

    def test_an_experiment_not_yet_due_or_already_judged_does_not_nudge(self):
        self.due('later', '2026-10-06')
        self.due('judged', '2026-09-01', result='keep')
        self.assertIsNone(self.line(MONDAY))

    def test_the_week_is_marked_even_when_there_was_nothing_to_say(self):
        self.assertIsNone(self.line(MONDAY))
        self.assertEqual(self.marker.read_text(encoding='utf-8').strip(), '2026-W41')

    def test_a_week_that_spans_two_years_is_one_week(self):
        self.add('big', 2, 2)
        self.assertIsNotNone(self.line(date(2026, 12, 31)))
        self.assertIsNone(self.line(date(2027, 1, 3)))
        self.assertIsNotNone(self.line(date(2027, 1, 4)))
        self.assertEqual(self.marker.read_text(encoding='utf-8').strip(), '2027-W01')

    def test_an_unreadable_marker_is_the_same_as_none(self):
        self.add('big', 2, 2)
        self.marker.parent.mkdir(parents=True)
        self.marker.write_bytes(b'\xff\xfe not a week')
        self.assertIsNotNone(self.line(MONDAY))
        self.assertIsNone(self.line(TUESDAY))


class NudgeCommandTest(NudgeCase):
    def run_nudge(self, now=NOW):
        return run_cli('nudge', '--home', str(self.home), '--data', str(self.data), now=now)

    def test_it_prints_one_json_line_for_the_user_only_and_not_a_second_time_that_week(self):
        self.add('big', 2, 2)
        code, out, err = self.run_nudge()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(json.loads(out),
                         {'systemMessage': f'anomaly: 1 open problem with score >= 4 (top: big (4)). {REVIEW}'})
        self.assertEqual(self.run_nudge(), (0, '', ''))

    def test_it_prints_nothing_when_nothing_needs_the_user(self):
        self.add('small', 1, 1)
        self.assertEqual(self.run_nudge(), (0, '', ''))

    def test_it_uses_the_folders_a_plugin_hook_gets_from_the_environment(self):
        self.add('big', 2, 2)
        environ = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.home), 'CLAUDE_PLUGIN_DATA': str(self.data)}
        code, out, _ = run_cli('nudge', environ=environ, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn('systemMessage', json.loads(out))
        self.assertTrue(self.marker.is_file())

    def test_a_new_iso_week_nudges_again(self):
        self.add('big', 2, 2)
        self.run_nudge()
        later = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
        self.assertIn('systemMessage', json.loads(self.run_nudge(later)[1]))

    def test_without_a_data_folder_it_stops_with_the_usual_error(self):
        code, out, err = run_cli('nudge', '--home', str(self.home), now=NOW)
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: no data folder'))

    def test_a_broken_anomaly_file_is_reported_once_a_week_not_at_every_startup(self):
        broken = self.home / 'anomalies' / 'broken.md'
        broken.parent.mkdir(parents=True)
        broken.write_bytes(b'\xff\xfe not text')
        code, out, err = self.run_nudge()
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: '))
        self.assertEqual(self.run_nudge(), (0, '', ''))

    def test_the_command_counts_sessions_from_the_metrics_file(self):
        experiment = records.Experiment(expect='faster', metric='active minutes', guard='rework sightings',
                                        kind='build', check_by='2026-11-01')
        write_anomaly_with(self.home, 'slow-fix', status='fixed', fixed_by='2026-09-20 · abc1234',
                           experiment=experiment)
        write_metrics_rows(self.home, [metrics_row(f's{n}', f'2026-09-{21 + n % 5}', skills=['implement'])
                                       for n in range(20)])
        code, out, _ = self.run_nudge()
        self.assertEqual(json.loads(out), {'systemMessage': f'anomaly: 1 experiment due. {REVIEW}'})

    def test_it_never_writes_into_home(self):
        self.add('big', 2, 2)
        before = sorted(p.name for p in self.home.rglob('*'))
        self.run_nudge()
        self.assertEqual(sorted(p.name for p in self.home.rglob('*')), before)


class HookFileTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(HOOKS_FILE.read_text(encoding='utf-8'))

    def test_one_session_start_hook_runs_the_nudge_at_startup_only(self):
        groups = self.config['hooks']['SessionStart']
        self.assertEqual(list(self.config['hooks']), ['SessionStart'])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['matcher'], 'startup')
        handlers = groups[0]['hooks']
        self.assertEqual(len(handlers), 1)
        self.assertEqual(handlers[0]['type'], 'command')

    def test_the_command_runs_the_plugin_script_without_a_shell_and_without_user_config(self):
        handler = self.config['hooks']['SessionStart'][0]['hooks'][0]
        self.assertEqual(handler['command'], 'python')
        self.assertEqual(handler['args'], ['${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py', 'nudge'])
        self.assertNotIn('user_config', json.dumps(self.config))
        self.assertLessEqual(handler['timeout'], 30)

    def test_the_manifest_leaves_the_default_hooks_location_alone(self):
        manifest = json.loads(PLUGIN_FILE.read_text(encoding='utf-8'))
        self.assertNotIn('hooks', manifest)


if __name__ == '__main__':
    unittest.main()

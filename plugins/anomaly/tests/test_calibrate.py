import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from anomaly_loop import calibrate, constants, records, trends
from tests.fixtures import (NOW, GitFixture, context, metrics_row, run_cli, write_anomaly_with,
                            write_build_skills_profile, write_experiment_anomaly, write_metrics_rows, write_text)

TODAY = NOW.date()
FIX = '2026-09-20 · abc1234'
FIX_DAY = date(2026, 9, 20)
DEFAULT_CHECK = (TODAY + timedelta(days=constants.EXPERIMENT_CHECK_DAYS)).isoformat()
SPREAD = 0.02   # spread(): neighbouring sessions differ by this share of the centre


def spread(centre, n):
    """n session values around `centre`, SPREAD apart, so their median and mean are `centre`: real
    sessions differ, and with every value the same a median cannot tell two windows apart (most
    splits of ties give the same medians). A list is returned as it is."""
    if isinstance(centre, (list, tuple)):
        return list(centre)
    return [centre * (1 + SPREAD * (i - (n - 1) / 2)) for i in range(n)]


class CalibrateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.data = self.root / 'data'
        self.plugin = self.root / 'plugin'
        self.user_config = self.root / 'user-config'
        write_build_skills_profile(self.home)

    def ctx(self, **overrides):
        return context(self.home, **overrides)

    def anomaly(self, signature):
        return records.read_anomaly(records.anomaly_path(self.home, signature))

    def cli(self, *argv):
        return run_cli('calibrate', *argv[:1], '--home', str(self.home), '--data', str(self.data),
                       '--user-config', str(self.user_config), '--plugin-root', str(self.plugin), *argv[1:])

    def rows(self, days, active=10.0, weighted=1000.0, skills=('implement',), prefix='s'):
        """A row per day in `days`; `active` and `weighted` are one value for every row, or a list of
        one value per row."""
        def each(value):
            return value if isinstance(value, (list, tuple)) else [value] * len(days)
        return [metrics_row(f'{prefix}{day}-{n}', day, active_min=minutes, weighted=tokens, skills=list(skills))
                for n, (day, minutes, tokens) in enumerate(zip(days, each(active), each(weighted)))]

    def baseline_and_after(self, before_active=20.0, after_active=10.0, before_weighted=1000.0,
                           after_weighted=1000.0, before_n=6, after_n=5):
        """before_n sessions in the baseline and after_n since the fix (several a day when there are
        many). A number is spread (spread()) so its window's median and mean are that number; a list
        gives one value per session as it is."""
        before = self.rows([f'2026-09-{10 + n % 10:02d}' for n in range(before_n)],
                           active=spread(before_active, before_n), weighted=spread(before_weighted, before_n),
                           prefix='b')
        after = self.rows([f'2026-09-{22 + n % 8:02d}' for n in range(after_n)],
                          active=spread(after_active, after_n), weighted=spread(after_weighted, after_n), prefix='a')
        write_metrics_rows(self.home, before + after)
        self.backlog_started('2026-08-01')
        return before, after

    def backlog_started(self, day):
        """A win seen on `day`: the backlog's first sighting, so sighting windows after it are known."""
        write_anomaly_with(self.home, 'backlog-start', kind='win', proposed_fix='', category='automated-checks',
                           sightings=[f'{day} · demo · seed · the backlog began'])


# ---------- verify and decide ----------

class VerifyCommandTest(CalibrateCase):
    def experiment(self, **fields):
        values = dict(metric='active minutes', guard='rework sightings', kind='build', fixed_by=FIX,
                      check_by='2026-10-01', status='fixed')
        values.update(fields)
        write_experiment_anomaly(self.home, 'slow-check', **values)

    def test_keep_is_written_and_the_numbers_are_shown(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment()
        code, out, err = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('- active minutes (primary): 20 (n=6) before, 10 (n=5) since, -50%; 4% of random splits '
                      'change this much → real change', out)
        self.assertIn('- sightings since the fix: 0', out)
        self.assertIn('result: keep (active minutes made a real change for the better and the guard held; '
                      'permutation test, ADR-0009)', out)
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.experiment.result, anomaly.status), ('keep', 'fixed'))
        self.assertIn('slow-check', (self.home / 'INDEX.md').read_text(encoding='utf-8'))

    def test_a_switch_over_compares_the_new_skills_sessions_with_the_old_skills_not_before_with_after(self):
        write_build_skills_profile(self.home, 'implement, demo:build')
        old_before = self.rows([f'2026-09-{10 + n}' for n in range(6)], active=spread(20, 6), prefix='b')
        old_beside = self.rows([f'2026-09-{22 + n}' for n in range(5)], active=spread(20, 5), prefix='o')
        new = self.rows([f'2026-09-{22 + n % 8}' for n in range(20)], active=spread(10, 20), skills=('demo:build',),
                        prefix='n')
        dogfood = self.rows(['2026-09-15'], active=10, skills=('demo:build',), prefix='d')
        fall_back = self.rows(['2026-09-23'], active=90, skills=('demo:build', 'implement'), prefix='f')
        write_metrics_rows(self.home, old_before + old_beside + new + dogfood + fall_back)
        self.backlog_started('2026-08-01')
        write_anomaly_with(self.home, 'redo', category='rework', occurrences=3,
                           sightings=[f'2026-09-23 · demo · {new[0]["session_id"]} · redone',
                                      '2026-09-24 · demo · never-measured · no side can be known',
                                      '2026-09-20 · demo · on-the-fix-day · in neither side'])
        self.experiment(skill='demo:build')
        code, out, err = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('verify: slow-check (20 demo:build sessions since the fix)', out)
        self.assertIn('- active minutes (primary): 20 (n=11) before, 10 (n=20) since, -50%;', out)
        self.assertIn('- rework sightings (guard): 0 (n=11) before, 0.05 (n=20) since', out)
        self.assertIn('- fall-backs: 1', out)
        self.assertIn('result: keep', out)

    def test_unproven_is_written_like_keep_and_the_experiment_is_not_due_again(self):
        self.baseline_and_after()
        self.experiment(metric='sightings since the fix')
        code, out, err = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('- sightings since the fix (primary): 0 (n=6) before, 0 (n=5) since; sightings since the fix: 0',
                      out)
        self.assertEqual(out.count('sightings since the fix: 0'), 1)
        self.assertIn('result: unproven (no recurrence in build sessions since the fix; rare-event rule, ADR-0009)',
                      out)
        self.assertIn('written: result unproven', out)
        self.assertNotIn('reopened', out)
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.experiment.result, anomaly.status, anomaly.experiment.check_by),
                         ('unproven', 'fixed', '2026-10-01'))
        self.assertIsNone(trends.experiment_due(self.ctx(), anomaly))

    def test_decide_still_accepts_only_keep_or_revert(self):
        self.experiment()
        code, _, err = self.cli('decide', '--signature', 'slow-check', '--result', 'unproven')
        self.assertEqual(code, 2)
        self.assertIn('keep', err)
        self.assertEqual(self.anomaly('slow-check').experiment.result, '')

    def test_a_reopen_by_a_sighting_on_the_fix_day_is_named(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment(status='reopened', sightings=['2026-09-20 · demo · x0 · the check was slow again'])
        code, out, err = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('- sightings on the fix day (2026-09-20): 1; in neither window, so the verdict does not '
                      'count them; one of them reopened the anomaly', out)
        self.assertIn('result: keep', out)

    def test_a_later_sighting_from_another_kind_is_what_reopened_the_anomaly_not_the_fix_day_one(self):
        self.baseline_and_after(before_active=20, after_active=10)
        write_metrics_rows(self.home, list(self.ctx().metrics_rows) + [metrics_row('u1', '2026-09-25')])
        self.experiment(status='reopened', sightings=['2026-09-20 · demo · x0 · on the fix day',
                                                       '2026-09-25 · demo · u1 · back, from another kind'])
        _, out, _ = self.cli('verify', '--signature', 'slow-check')
        self.assertIn('- sightings on the fix day (2026-09-20): 1; in neither window, so the verdict does not '
                      'count them', out)
        self.assertNotIn('reopened the anomaly', out)

    def test_no_fix_day_line_without_a_sighting_on_that_day(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment(status='reopened', sightings=['2026-09-25 · demo · x0 · back after the fix'])
        _, out, _ = self.cli('verify', '--signature', 'slow-check')
        self.assertNotIn('fix day', out)

    def test_revert_reopens_the_anomaly(self):
        self.baseline_and_after(before_active=10, after_active=20)
        self.experiment()
        code, out, _ = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual(code, 0)
        self.assertIn('result: revert', out)
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.experiment.result, anomaly.status), ('revert', 'reopened'))
        self.assertEqual(anomaly.experiment.reason, 'active minutes got worse; permutation test, ADR-0009')

    def test_inconclusive_moves_the_check_date_once_then_the_user_decides(self):
        self.baseline_and_after(before_active=20, after_active=19)
        self.experiment()
        code, out, _ = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual(code, 0)
        self.assertIn('result: inconclusive', out)
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.experiment.result, anomaly.experiment.check_by), ('inconclusive', DEFAULT_CHECK))
        self.experiment(result='inconclusive', check_by='2026-10-03')
        code, out, _ = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual(code, 0)
        self.assertIn('still inconclusive', out)
        self.assertEqual(self.anomaly('slow-check').experiment.check_by, '2026-10-03')
        code, out, _ = self.cli('decide', '--signature', 'slow-check', '--result', 'revert')
        self.assertEqual(code, 0)
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.experiment.result, anomaly.status), ('revert', 'reopened'))

    def test_a_second_check_that_now_has_an_answer_writes_it(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment(result='inconclusive', check_by='2026-10-03')
        self.cli('verify', '--signature', 'slow-check')
        self.assertEqual(self.anomaly('slow-check').experiment.result, 'keep')

    def test_an_experiment_that_is_not_due_is_refused(self):
        self.experiment(check_by='2026-10-30')
        code, out, err = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual(code, 2)
        self.assertIn('not due', err)

    def test_decide_is_refused_while_the_numbers_can_still_answer(self):
        self.experiment()
        code, _, err = self.cli('decide', '--signature', 'slow-check', '--result', 'keep')
        self.assertEqual(code, 2)
        self.assertIn('verify', err)

    def test_decide_is_allowed_for_a_due_experiment_whose_metric_cannot_be_measured(self):
        self.experiment(metric='minutes per build')
        code, _, err = self.cli('decide', '--signature', 'slow-check', '--result', 'keep')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.anomaly('slow-check').experiment.result, 'keep')


# ---------- declare and fix ----------

class DeclareCommandTest(CalibrateCase):
    def setUp(self):
        super().setUp()
        write_anomaly_with(self.home, 'slow-check', category='automated-checks', impact=2, occurrences=2,
                           target='scripts/check.sh', scope='repo:demo')

    def declare(self, *extra, signature='slow-check'):
        base = ['declare', '--signature', signature]
        if '--expect' not in extra:
            base += ['--expect', 'the check takes half the time']
        if '--metric' not in extra:
            base += ['--metric', 'active minutes']
        if '--guard' not in extra:
            base += ['--guard', 'rework sightings']
        return self.cli(*base, *extra)

    def test_the_experiment_is_written_before_the_change_dated_today_and_without_a_check_date(self):
        code, out, err = self.declare('--kind', 'build')
        self.assertEqual((code, err), (0, ''))
        anomaly = self.anomaly('slow-check')
        self.assertEqual(anomaly.experiment, records.Experiment(
            expect='the check takes half the time', metric='active minutes', guard='rework sightings',
            kind='build', declared_on=TODAY.isoformat(), check_by='', result=''))
        self.assertEqual((anomaly.fixed_by, anomaly.status), ('', 'open'))
        self.assertIn('declared: slow-check', out)
        self.assertIn('calibrate fix', out)

    def test_a_switch_over_records_the_new_skill(self):
        write_build_skills_profile(self.home, 'implement, demo:build')
        code, out, err = self.declare('--kind', 'build', '--skill', 'demo:build')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.anomaly('slow-check').experiment.skill, 'demo:build')
        self.assertIn('  skill: demo:build\n',
                      records.anomaly_path(self.home, 'slow-check').read_text(encoding='utf-8'))
        self.assertIn('skill demo:build', out)

    def test_weighted_tokens_without_security_is_per_session_so_declare_gives_no_backlog_warning(self):
        code, out, err = self.declare('--metric', 'weighted tokens without security', '--guard', 'interrupts')
        self.assertEqual((code, err), (0, ''))
        self.assertNotIn('backlog', out)

    def test_a_given_check_date_and_effort_are_kept(self):
        self.declare('--check-by', '2026-11-01', '--effort', 'S')
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.experiment.check_by, anomaly.effort), ('2026-11-01', 'S'))

    def test_a_second_metric_or_a_missing_guard_is_refused(self):
        code, _, err = self.declare('--metric', 'active minutes', '--metric', 'weighted tokens')
        self.assertEqual(code, 2)
        self.assertIn('exactly one primary metric', err)
        code, _, err = self.cli('declare', '--signature', 'slow-check', '--expect', 'x', '--metric', 'interrupts')
        self.assertEqual(code, 2)
        self.assertIn('guard', err)
        code, _, err = self.declare('--guard', 'rework sightings', '--guard', 'late-catch sightings')
        self.assertIn('exactly one guard', err)
        self.assertIsNone(self.anomaly('slow-check').experiment)

    def test_unknown_metrics_a_guard_equal_to_the_metric_and_bad_values_are_refused(self):
        for extra, words in ((('--metric', 'speed'), 'unknown metric'),
                             (('--metric', 'interrupts', '--guard', 'interrupts'), 'differ'),
                             (('--guard', 'weighted tokens'), 'quality'),
                             (('--kind', 'weekly'), 'kind'),
                             (('--check-by', 'soon'), 'check_by'),
                             (('--check-by', '2026-10-03'), 'check_by'),
                             (('--effort', 'XL'), 'effort'),
                             (('--expect', 'mail me at someone@example.com'), 'email'),
                             (('--skill', 'implement'), '--kind build'),
                             (('--kind', 'build', '--skill', 'demo:build'), 'build_skills')):
            code, _, err = self.declare(*extra)
            self.assertEqual(code, 2, extra)
            self.assertIn(words, err, extra)
        self.assertIsNone(self.anomaly('slow-check').experiment)

    def test_a_workflow_fix_needs_score_four_or_impact_three(self):
        write_anomaly_with(self.home, 'redo-small', category='rework', impact=1, occurrences=3)
        write_anomaly_with(self.home, 'redo-often', category='rework', impact=1, occurrences=4)
        write_anomaly_with(self.home, 'redo-severe', category='handoff-loss', impact=3, occurrences=1)
        code, _, err = self.declare(signature='redo-small')
        self.assertEqual(code, 2)
        self.assertIn('score 4', err)
        self.assertEqual(self.declare(signature='redo-often')[0], 0)
        self.assertEqual(self.declare(signature='redo-severe')[0], 0)

    def test_wins_closed_anomalies_and_experiments_in_flight_are_refused(self):
        write_anomaly_with(self.home, 'good-step', kind='win', proposed_fix='')
        write_anomaly_with(self.home, 'done-one', status='wontfix')
        write_experiment_anomaly(self.home, 'in-flight', status='reopened', fixed_by=FIX, check_by='2026-10-30')
        for signature, words in (('good-step', 'problem'), ('done-one', 'wontfix'), ('in-flight', 'in flight'),
                                 ('missing', 'no anomaly')):
            code, _, err = self.declare(signature=signature)
            self.assertEqual(code, 2, signature)
            self.assertIn(words, err, signature)

    def test_an_adopt_draft_is_completed_and_keeps_what_it_drafted(self):
        write_experiment_anomaly(self.home, 'drafted', metric='fewer slow checks', guard='rework sightings',
                                 fixed_by='', check_by='')
        code, _, err = self.cli('declare', '--signature', 'drafted', '--metric', 'active minutes', '--kind', 'build')
        self.assertEqual((code, err), (0, ''))
        experiment = self.anomaly('drafted').experiment
        self.assertEqual((experiment.expect, experiment.metric, experiment.guard, experiment.declared_on),
                         ('faster', 'active minutes', 'rework sightings', TODAY.isoformat()))

    def test_a_finished_experiment_is_archived_when_a_new_one_is_declared(self):
        write_experiment_anomaly(self.home, 'retry', status='reopened', fixed_by=FIX, check_by='2026-10-01',
                                 result='revert', guard='rework sightings')
        code, _, _ = self.declare(signature='retry')
        self.assertEqual(code, 0)
        anomaly = self.anomaly('retry')
        self.assertEqual(anomaly.fixed_by, '')
        self.assertEqual(anomaly.experiment.result, '')
        self.assertEqual(records.earlier_experiments(anomaly)[0][0], 'revert')

    def test_an_earlier_reverted_attempt_on_the_same_target_is_mentioned(self):
        write_experiment_anomaly(self.home, 'old-try', target='scripts/check.sh', status='reopened', fixed_by=FIX,
                                 check_by='2026-10-01', result='revert', metric='weighted tokens')
        code, out, _ = self.declare()
        self.assertEqual(code, 0)
        self.assertIn('tried before: old-try', out)

    def test_a_change_to_this_plugins_own_skill_needs_the_users_yes(self):
        write_text(self.plugin / '.claude-plugin' / 'plugin.json', '{"name": "anomaly"}')
        write_anomaly_with(self.home, 'loop-step', category='automated-checks', target='anomaly:observe',
                           impact=2, occurrences=2)
        code, _, err = self.declare(signature='loop-step')
        self.assertEqual(code, 2)
        self.assertIn('--approved', err)
        code, out, _ = self.declare('--approved', signature='loop-step')
        self.assertEqual(code, 0)

    def test_the_plugin_name_is_matched_in_any_case_and_a_path_inside_the_plugin_counts(self):
        write_text(self.plugin / '.claude-plugin' / 'plugin.json', '{"name": "anomaly"}')
        write_text(self.plugin / 'skills' / 'observe' / 'SKILL.md', '# observe\n')
        targets = ('Anomaly:Observe', str(self.plugin / 'skills' / 'observe' / 'SKILL.md'), 'skills/observe/SKILL.md')
        for number, target in enumerate(targets):
            signature = f'loop-step-{number}'
            write_anomaly_with(self.home, signature, category='automated-checks', target=target, impact=2,
                               occurrences=2)
            code, _, err = self.declare(signature=signature)
            self.assertEqual(code, 2, target)
            self.assertIn('--approved', err, target)

    def checkout(self):
        """Move the plugin into a git checkout at plugins/anomaly; returns the checkout."""
        checkout = GitFixture(self.root / 'checkout')
        self.plugin = checkout.root / 'plugins' / 'anomaly'
        write_text(self.plugin / '.claude-plugin' / 'plugin.json', '{"name": "anomaly"}')
        write_text(self.plugin / 'skills' / 'calibrate' / 'SKILL.md', '# calibrate\n')
        return checkout

    def needs_approval(self, target, signature='loop-step'):
        write_anomaly_with(self.home, signature, category='automated-checks', target=target, impact=2,
                           occurrences=2)
        code, _, err = self.declare(signature=signature)
        return code == 2 and '--approved' in err

    def test_a_path_from_the_checkout_root_or_the_plugin_folder_itself_needs_the_users_yes(self):
        self.checkout()
        self.assertTrue(self.needs_approval('plugins/anomaly/skills/calibrate/SKILL.md'))
        self.assertTrue(self.needs_approval(str(self.plugin), signature='loop-folder'))

    def test_an_installed_copy_finds_the_checkout_through_the_profile(self):
        self.checkout()
        checkout_plugin = self.plugin
        self.plugin = self.root / 'installed'
        write_text(self.plugin / '.claude-plugin' / 'plugin.json', '{"name": "anomaly"}')
        write_text(self.home / 'profile.md', f'---\nplugin_repo: {checkout_plugin}\n---\n')
        self.assertTrue(self.needs_approval('plugins/anomaly/skills/calibrate/SKILL.md'))
        self.assertTrue(self.needs_approval(str(checkout_plugin / 'skills'), signature='loop-folder'))

    def test_a_sighting_metric_warns_until_the_backlog_covers_the_baseline(self):
        self.backlog_started('2026-09-22')
        _, out, _ = self.declare('--metric', 'rework sightings', '--guard', 'interrupts')
        self.assertIn('the backlog starts on 2026-09-22', out)
        self.assertIn('2026-10-20', out)
        _, out, _ = self.declare('--metric', 'active minutes', '--guard', 'rework sightings')
        self.assertIn('2026-10-20', out)
        self.assertIn('interrupts', out)

    def test_no_backlog_warning_for_a_rare_event_primary_because_it_needs_no_baseline(self):
        self.backlog_started('2026-09-22')
        for guard in ('interrupts', 'rework sightings'):
            _, out, _ = self.declare('--metric', 'sightings since the fix', '--guard', guard)
            self.assertNotIn('backlog', out)

    def test_no_backlog_warning_for_numbers_only_or_a_covered_baseline(self):
        self.backlog_started('2026-09-22')
        _, out, _ = self.declare('--metric', 'active minutes', '--guard', 'interrupts')
        self.assertNotIn('backlog', out)
        self.backlog_started('2026-09-01')
        _, out, _ = self.declare('--metric', 'sightings since the fix', '--guard', 'rework sightings')
        self.assertNotIn('backlog', out)

    def test_a_path_outside_the_plugin_needs_no_approval(self):
        write_text(self.user_config / 'skills' / 'observe' / 'SKILL.md', '# a user skill\n')
        write_text(self.plugin / 'skills' / 'observe' / 'SKILL.md', '# observe\n')
        write_anomaly_with(self.home, 'user-step', category='automated-checks', target='skills/observe/SKILL.md',
                           impact=2, occurrences=2)
        self.assertEqual(self.declare(signature='user-step')[0], 0)

    def test_the_reply_says_how_many_sessions_of_the_kind_ran_and_warns_when_few(self):
        write_metrics_rows(self.home, self.rows([f'2026-09-{20 + n % 5}' for n in range(19)]))
        _, out, _ = self.declare('--kind', 'build')
        self.assertIn('19 build sessions in the last 28 days', out)
        self.assertIn('leave --kind out', out)
        write_metrics_rows(self.home, self.rows([f'2026-09-{20 + n % 5}' for n in range(20)]))
        _, out, _ = self.declare('--kind', 'build')
        self.assertIn('20 build sessions in the last 28 days', out)
        self.assertNotIn('leave --kind out', out)


class FixCommandTest(CalibrateCase):
    def test_the_fix_is_recorded_date_first_and_the_anomaly_is_fixed(self):
        write_experiment_anomaly(self.home, 'slow-check', metric='active minutes', guard='rework sightings',
                                 fixed_by='', check_by='2026-10-25', declared_on='2026-10-01')
        code, out, err = self.cli('fix', '--signature', 'slow-check', '--ref', 'abc1234')
        self.assertEqual((code, err), (0, ''))
        anomaly = self.anomaly('slow-check')
        self.assertEqual((anomaly.fixed_by, anomaly.status, anomaly.experiment.check_by),
                         ('2026-10-04 · abc1234', 'fixed', '2026-10-25'))
        self.assertEqual(records.fix_date(anomaly), TODAY)
        self.assertIn('fixed: slow-check', out)

    def test_the_reply_names_both_halves_of_the_due_rule(self):
        write_experiment_anomaly(self.home, 'slow-check', metric='interrupts', guard='rework sightings',
                                 fixed_by='', check_by='2026-10-25', kind='build', declared_on='2026-10-01')
        _, out, _ = self.cli('fix', '--signature', 'slow-check', '--ref', 'abc1234')
        self.assertIn(f'check by 2026-10-25 or after {constants.EXPERIMENT_CHECK_SESSIONS} build sessions', out)

    def test_a_blank_check_date_counts_from_the_fix_day(self):
        write_experiment_anomaly(self.home, 'slow-check', metric='interrupts', guard='rework sightings',
                                 fixed_by='', check_by='', declared_on='2026-10-01')
        self.cli('fix', '--signature', 'slow-check', '--ref', 'skills/check/SKILL.md', '--date', '2026-10-02')
        anomaly = self.anomaly('slow-check')
        self.assertEqual(anomaly.fixed_by, '2026-10-02 · skills/check/SKILL.md')
        self.assertEqual(anomaly.experiment.check_by, '2026-10-23')

    def test_no_experiment_an_unmeasurable_metric_or_a_recorded_fix_is_refused(self):
        write_anomaly_with(self.home, 'bare')
        write_experiment_anomaly(self.home, 'drafted', metric='fewer slow checks', fixed_by='')
        write_experiment_anomaly(self.home, 'old-name', metric='fewer slow checks', fixed_by='',
                                 declared_on='2026-10-01')
        write_experiment_anomaly(self.home, 'landed', metric='interrupts', guard='rework sightings', fixed_by=FIX)
        for signature, words in (('bare', 'declare'), ('drafted', 'declare'), ('old-name', 'unknown metric'),
                                 ('landed', 'already')):
            code, _, err = self.cli('fix', '--signature', signature, '--ref', 'abc1234')
            self.assertEqual(code, 2, signature)
            self.assertIn(words, err, signature)

    def test_a_reference_must_be_clean_and_the_date_not_in_the_future(self):
        write_experiment_anomaly(self.home, 'slow-check', metric='interrupts', guard='rework sightings', fixed_by='',
                                 declared_on='2026-10-02')
        for extra, words in ((('--ref', 'see https://example.com/x?token=1'), 'query'),
                             (('--ref', 'abc1234', '--date', '2026-10-05'), 'future'),
                             (('--ref', 'abc1234', '--date', '2026-10-01'), 'before')):
            code, _, err = self.cli('fix', '--signature', 'slow-check', *extra)
            self.assertEqual(code, 2, extra)
            self.assertIn(words, err)
        self.assertEqual(self.anomaly('slow-check').fixed_by, '')


# ---------- batches and housekeeping ----------

class BatchTest(CalibrateCase):
    def test_problems_are_grouped_by_scope_and_ranked_by_summed_score(self):
        write_anomaly_with(self.home, 'a-one', scope='repo:a', impact=2, occurrences=2)
        write_anomaly_with(self.home, 'a-two', scope='repo:a', impact=1, occurrences=1)
        write_anomaly_with(self.home, 'b-one', scope='repo:b', impact=3, occurrences=2)
        write_anomaly_with(self.home, 'b-win', scope='repo:b', kind='win', impact=3, occurrences=5, proposed_fix='')
        write_anomaly_with(self.home, 'b-done', scope='repo:b', impact=3, occurrences=5, status='fixed')
        batches = calibrate.batches(self.ctx())
        self.assertEqual([(b.scope, b.total) for b in batches], [('repo:b', 6), ('repo:a', 5)])
        self.assertEqual([a.signature for a in batches[1].problems], ['a-one', 'a-two'])

    def test_other_scopes_are_split_by_target_and_problems_without_one_share_a_batch(self):
        write_anomaly_with(self.home, 'g-one', scope='global', target='scripts/a.sh', impact=3, occurrences=1)
        write_anomaly_with(self.home, 'g-two', scope='project:x', target='scripts/a.sh', impact=1, occurrences=1)
        write_anomaly_with(self.home, 'g-three', scope='global', target='scripts/b.sh', impact=2, occurrences=1)
        write_anomaly_with(self.home, 'g-loose', scope='global', impact=1, occurrences=1)
        write_anomaly_with(self.home, 'p-one', scope='plugin:demo', target='scripts/a.sh', impact=1, occurrences=1)
        batches = calibrate.batches(self.ctx())
        self.assertEqual([(b.scope, b.total, [a.signature for a in b.problems]) for b in batches], [
            ('target: scripts/a.sh', 4, ['g-one', 'g-two']), ('target: scripts/b.sh', 2, ['g-three']),
            ('plugin:demo', 1, ['p-one']), ('untargeted', 1, ['g-loose'])])

    def test_a_current_revert_is_named_with_its_reason(self):
        write_experiment_anomaly(self.home, 'tried', target='scripts/check.sh', status='reopened', fixed_by=FIX,
                                 check_by='2026-10-01', result='revert', metric='weighted tokens')
        anomaly = self.anomaly('tried')
        anomaly.experiment.reason = 'weighted tokens got worse'
        records.write_anomaly(self.home, anomaly)
        write_anomaly_with(self.home, 'slow-check', target='scripts/check.sh')
        ctx = self.ctx()
        [problem] = [a for a in ctx.anomalies if a.signature == 'slow-check']
        self.assertEqual(calibrate.tried_before(ctx.anomalies, problem),
                         ['tried reverted (weighted tokens, fixed 2026-09-20; weighted tokens got worse)'])

    def test_inside_a_batch_the_order_is_score_then_lower_effort(self):
        write_anomaly_with(self.home, 'big-large', scope='s', impact=2, occurrences=2, effort='L')
        write_anomaly_with(self.home, 'big-small', scope='s', impact=2, occurrences=2, effort='S')
        write_anomaly_with(self.home, 'big-unset', scope='s', impact=2, occurrences=2)
        write_anomaly_with(self.home, 'top', scope='s', impact=3, occurrences=2, effort='L')
        [batch] = calibrate.batches(self.ctx())
        self.assertEqual([a.signature for a in batch.problems], ['top', 'big-small', 'big-large', 'big-unset'])

    def test_a_workflow_problem_below_the_gate_waits_and_does_not_add_to_the_sum(self):
        write_anomaly_with(self.home, 'redo', scope='s', category='rework', impact=1, occurrences=3)
        write_anomaly_with(self.home, 'tool', scope='s', category='tool-economy', impact=1, occurrences=1)
        [batch] = calibrate.batches(self.ctx())
        self.assertEqual(batch.total, 1)
        self.assertIsNotNone(calibrate.workflow_gate(batch.problems[0]))
        self.assertIsNone(calibrate.workflow_gate(batch.problems[1]))

    def test_the_plan_marks_waits_drafts_earlier_reverts_and_protected_targets(self):
        write_anomaly_with(self.home, 'redo', scope='s', category='rework', impact=1, occurrences=2)
        write_anomaly_with(self.home, 'slow-check', scope='s', target='scripts/check.sh', impact=2, occurrences=3)
        write_experiment_anomaly(self.home, 'tried', scope='t', target='scripts/check.sh', status='fixed',
                                 fixed_by=FIX, check_by='2026-10-01', result='revert', metric='weighted tokens')
        write_anomaly_with(self.home, 'saved-me', kind='win', target='scripts/check.sh', occurrences=2,
                           proposed_fix='')
        write_experiment_anomaly(self.home, 'adopted', scope='t', fixed_by='', metric='interrupts')
        lines = calibrate.plan_lines(self.ctx())
        text = '\n'.join(lines)
        self.assertIn('## Batches (summed score', text)
        line = next(l for l in lines if 'slow-check' in l and l.lstrip().startswith('- '))
        self.assertIn('tried before: tried', line)
        self.assertIn('protected', line)
        self.assertIn('waits', next(l for l in lines if ' redo ' in l))
        self.assertIn('experiment drafted', next(l for l in lines if 'adopted' in l))

    def test_the_plan_lists_housekeeping_from_the_flag_and_due_owners(self):
        write_anomaly_with(self.home, 'lonely', last_seen='2026-07-01')
        write_anomaly_with(self.home, 'slow-check-twice', scope='s', target='scripts/x.sh')
        write_anomaly_with(self.home, 'slow-check-again', scope='s', target='scripts/x.sh')
        write_experiment_anomaly(self.home, 'due-one', status='fixed', fixed_by=FIX, check_by='2026-10-01')
        text = '\n'.join(calibrate.plan_lines(self.ctx()))
        self.assertIn('## Housekeeping', text)
        self.assertIn('## Stale anomalies', text)
        self.assertIn('## Near-duplicates', text)
        self.assertIn('## Experiments due', text)
        self.assertIn('metrics:', text)
        self.assertIn(f'guards: {", ".join(constants.QUALITY_GUARDS)}', text)

    def test_the_plan_counts_sessions_per_kind_over_the_last_28_days(self):
        write_metrics_rows(self.home, self.rows(['2026-09-01', '2026-09-20', '2026-09-25'])
                           + self.rows(['2026-09-26'], skills=(), prefix='u'))
        text = '\n'.join(calibrate.plan_lines(self.ctx()))
        self.assertIn('sessions in the last 28 days: build 2, unknown 1', text)

    def test_the_plan_command_says_once_which_profile_keys_are_missing(self):
        write_anomaly_with(self.home, 'a-one')
        code, out, err = self.cli('plan')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(sum(line.startswith('profile:') for line in out.splitlines()), 1)

    def test_an_empty_backlog_has_no_batches(self):
        code, out, _ = self.cli('plan')
        self.assertEqual(code, 0)
        self.assertIn('- no open problems', out)


class HousekeepingCommandTest(CalibrateCase):
    def test_effort_is_set_for_several_anomalies_at_once(self):
        write_anomaly_with(self.home, 'a-one')
        write_anomaly_with(self.home, 'a-two')
        code, out, err = self.cli('effort', '--set', 'a-one=S', '--set', 'a-two=L')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual((self.anomaly('a-one').effort, self.anomaly('a-two').effort), ('S', 'L'))

    def test_a_bad_effort_or_signature_writes_nothing(self):
        write_anomaly_with(self.home, 'a-one')
        for value in ('a-one=XL', 'a-one', 'missing=S'):
            code, _, err = self.cli('effort', '--set', 'a-one=S', '--set', value)
            self.assertEqual(code, 2, value)
        self.assertEqual(self.anomaly('a-one').effort, '')

    def test_a_hand_edited_check_by_that_is_not_a_date_is_refused(self):
        path = write_experiment_anomaly(self.home, 'slow-check', check_by='2026-10-25')
        write_text(path, path.read_text(encoding='utf-8').replace('check_by: 2026-10-25', 'check_by: soon'))
        code, _, err = self.cli('effort', '--set', 'slow-check=S')
        self.assertEqual(code, 2)
        self.assertIn('check_by', err)
        self.assertEqual(self.anomaly('slow-check').effort, '')

    def test_close_marks_wontfix(self):
        write_anomaly_with(self.home, 'lonely')
        code, out, _ = self.cli('close', '--signature', 'lonely')
        self.assertEqual(code, 0)
        self.assertEqual(self.anomaly('lonely').status, 'wontfix')
        self.assertEqual(self.cli('close', '--signature', 'lonely')[0], 2)

    def test_merge_moves_the_sightings_and_closes_the_other_record(self):
        write_anomaly_with(self.home, 'keep-me', occurrences=2, impact=1,
                           sightings=['2026-10-01 · demo · s2 · two', '2026-09-20 · demo · s1 · one'])
        write_anomaly_with(self.home, 'fold-me', occurrences=1, impact=3, last_seen='2026-10-02',
                           sightings=['2026-10-02 · demo · s3 · three'])
        code, out, err = self.cli('merge', '--into', 'keep-me', '--from', 'fold-me')
        self.assertEqual((code, err), (0, ''))
        kept, folded = self.anomaly('keep-me'), self.anomaly('fold-me')
        self.assertEqual((kept.occurrences, kept.impact, kept.last_seen), (3, 3, '2026-10-02'))
        self.assertEqual(kept.sightings[0], '2026-10-02 · demo · s3 · three')
        self.assertEqual(folded.status, 'wontfix')
        self.assertIn('keep-me', dict(folded.sections)['Merged'])

    def test_merging_into_a_closed_record_is_refused(self):
        write_anomaly_with(self.home, 'closed-one', status='wontfix')
        write_anomaly_with(self.home, 'open-one', sightings=['2026-10-02 · demo · s3 · three'])
        code, _, err = self.cli('merge', '--into', 'closed-one', '--from', 'open-one')
        self.assertEqual(code, 2)
        self.assertIn('open or reopened', err)
        self.assertEqual(self.anomaly('open-one').status, 'open')


class CommitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.repo = GitFixture(root / 'repo')
        self.home = self.repo.root / 'anomaly-home'
        self.data = root / 'data'
        self.repo.write('README.md', 'x\n')
        write_anomaly_with(self.home, 'slow-check', category='automated-checks', impact=2, occurrences=2)
        self.repo.commit(['README.md', 'anomaly-home/anomalies/slow-check.md'], 'chore: start', TODAY)

    def test_only_the_written_home_paths_are_committed(self):
        self.repo.write('README.md', 'edited elsewhere\n')
        code, out, _ = run_cli('calibrate', 'declare', '--home', str(self.home), '--data', str(self.data),
                               '--signature', 'slow-check', '--expect', 'faster', '--metric', 'active minutes',
                               '--guard', 'rework sightings')
        self.assertEqual(code, 0)
        self.assertIn('commit: ', out)
        files = sorted(self.repo.git('show', '--name-only', '--format=', 'HEAD').split())
        self.assertEqual(files, ['anomaly-home/INDEX.md', 'anomaly-home/anomalies/slow-check.md'])
        self.assertIn('calibrate', self.repo.git('log', '-1', '--format=%s'))
        self.assertEqual(self.repo.status(), [' M README.md'])


class RegistrationTest(unittest.TestCase):
    def test_the_subcommand_is_registered(self):
        from anomaly_loop import cli
        self.assertIn('calibrate', cli.COMMANDS)


if __name__ == '__main__':
    unittest.main()

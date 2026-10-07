import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from anomaly_loop import digest, trends
from tests.fixtures import (anomaly_text, context, metrics_row, write_build_skills_profile, write_experiment_anomaly,
                            write_metrics_rows, write_text)

TODAY = date(2026, 10, 4)


class TrendsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        write_build_skills_profile(self.home)

    def ctx(self, **overrides):
        return context(self.home, **overrides)


class SessionKindTest(TrendsCase):
    def kind(self, row, **overrides):
        return trends.context_session_kind(self.ctx(**overrides), row)

    def test_a_build_skill_marks_a_build_session(self):
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', skills=['implement'])), 'build')

    def test_a_build_skill_used_only_as_a_slash_command_counts(self):
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', slash=['run-tickets'])), 'build')

    def test_a_plugin_qualified_skill_matches_the_bare_build_skill(self):
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', skills=['pack:implement'])), 'build')

    def test_the_profile_list_replaces_the_default_list(self):
        write_text(self.home / 'profile.md', '---\nbuild_skills: ship\n---\n')
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', skills=['ship'])), 'build')
        self.assertEqual(self.kind(metrics_row('s2', '2026-10-01', skills=['implement'])), 'unknown')

    def test_without_build_skills_in_the_profile_no_session_is_build(self):
        (self.home / 'profile.md').unlink()
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', skills=['implement'])), 'unknown')

    def test_a_working_folder_under_the_user_config_folder_is_config(self):
        config = self.root / 'user-config'
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', cwd=str(config / 'skills' / 'x'))), 'config')
        self.assertEqual(self.kind(metrics_row('s2', '2026-10-01', cwd=str(config))), 'config')

    def test_a_folder_that_only_shares_the_name_prefix_is_not_config(self):
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', cwd=str(self.root / 'user-config-old'))),
                         'unknown')

    def test_windows_paths_compare_with_either_slash_and_any_drive_letter_case(self):
        config = Path('D:/profile/.claude')
        for cwd in ('D:\\profile\\.claude\\skills', 'd:/profile/.claude/skills'):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', cwd=cwd), user_config=config),
                                 'config')

    def test_build_wins_over_config(self):
        row = metrics_row('s1', '2026-10-01', skills=['implement'], cwd=str(self.root / 'user-config'))
        self.assertEqual(self.kind(row), 'build')

    def test_anything_else_is_unknown_including_a_row_without_fields(self):
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01')), 'unknown')
        self.assertEqual(self.kind({'session_id': 's2'}), 'unknown')
        self.assertEqual(self.kind({'session_id': 's3', 'cwd_first': None}), 'unknown')

    def test_an_override_wins_over_the_guess_and_the_last_line_wins(self):
        write_text(self.home / 'session-kinds.jsonl',
                   '{"session_id":"s1","kind":"debug","set_on":"2026-10-02"}\n'
                   '{"session_id":"s1","kind":"research","set_on":"2026-10-03"}\n')
        self.assertEqual(self.kind(metrics_row('s1', '2026-10-01', skills=['implement'])), 'research')
        self.assertEqual(self.kind(metrics_row('s2', '2026-10-01', skills=['implement'])), 'build')

    def test_the_rules_run_on_plain_inputs_without_a_context(self):
        row = metrics_row('s1', '2026-10-01', skills=['ship'], cwd='/cfg/skills')
        self.assertEqual(trends.session_kind(row, {}, ('ship',), '/cfg'), 'build')
        self.assertEqual(trends.session_kind(row, {}, ('other',), '/cfg'), 'config')
        self.assertEqual(trends.session_kind(row, {}, ('other',), '/elsewhere'), 'unknown')
        self.assertEqual(trends.session_kind(row, {'s1': {'kind': 'debug'}}, ('ship',), '/cfg'), 'debug')

    def test_the_kind_is_never_stored_in_the_row(self):
        row = metrics_row('s1', '2026-10-01', skills=['implement'])
        before = dict(row)
        self.kind(row)
        self.assertEqual(row, before)


class TrendsSectionTest(TrendsCase):
    def section(self):
        return trends.trends_section(self.ctx(today=TODAY))

    def test_no_rows_means_no_section(self):
        self.assertEqual(self.section(), [])

    def test_the_statistic_per_kind_with_sample_sizes_for_both_windows(self):
        build = ['implement']
        write_metrics_rows(self.home, [
            metrics_row('a', '2026-10-01', weighted=100_000, active_min=10, interrupts=1, denials=9, skills=build),
            metrics_row('b', '2026-10-02', weighted=300_000, active_min=30, interrupts=3, denials=2, skills=build),
            metrics_row('c', '2026-10-03', weighted=200_000, active_min=20, interrupts=2, denials=1, skills=build),
            metrics_row('d', '2026-09-10', weighted=100_000, active_min=10, interrupts=0, denials=1, skills=build),
            metrics_row('e', '2026-09-12', weighted=300_000, active_min=20, interrupts=0, denials=1, skills=build)])
        self.assertEqual(self.section(), [
            '## Trends: last 14 days vs the 14 before (median, n = sessions; interrupts: mean)',
            '**build**',
            '- weighted tokens 200k (n=3) vs 200k (n=2)',
            '- active minutes 20 (n=3) vs 15 (n=2)',
            '- interrupts 2 (n=3) vs 0 (n=2)',
            '- denials 2 (n=3) vs 1 (n=2)',
        ])

    def test_interrupts_are_a_mean_that_a_few_sessions_move_and_a_mean_below_1_has_two_decimals(self):
        recent = [metrics_row(f'n{n}', '2026-10-01', active_min=0.5, interrupts=7 if n == 0 else 0) for n in range(20)]
        before = [metrics_row(f'o{n}', '2026-09-10', active_min=0.5) for n in range(20)]
        write_metrics_rows(self.home, recent + before)
        lines = self.section()
        self.assertIn('- interrupts 0.35 (n=20) vs 0 (n=20) (from 0) → within noise', lines)
        self.assertIn('- active minutes 0.5 (n=20) vs 0.5 (n=20) (+0%) → within noise', lines)

    def test_the_percentage_and_the_word_need_enough_samples_in_both_windows(self):
        days = ['2026-09-2%d' % n for n in range(1, 6)]
        before = ['2026-09-1%d' % n for n in range(0, 5)]
        write_metrics_rows(self.home, [metrics_row(f'n{d}', d, weighted=150, active_min=0, interrupts=1) for d in days]
                           + [metrics_row(f'o{d}', d, weighted=100, active_min=0, interrupts=1) for d in before])
        lines = self.section()
        self.assertIn('- weighted tokens 150 (n=5) vs 100 (n=5) (+50%) → within noise', lines)
        write_metrics_rows(self.home, [*[metrics_row(f'n{d}', d, weighted=150) for d in days],
                                       *[metrics_row(f'o{d}', d, weighted=100) for d in before[:4]]])
        self.assertIn('- weighted tokens 150 (n=5) vs 100 (n=4)', self.section())
        write_metrics_rows(self.home, [*[metrics_row(f'n{d}', d, weighted=150) for d in days[:4]],
                                       *[metrics_row(f'o{d}', d, weighted=100) for d in before]])
        self.assertIn('- weighted tokens 150 (n=4) vs 100 (n=5)', self.section())

    def test_a_clear_answer_with_enough_sessions_ends_with_real_change(self):
        recent = [metrics_row(f'n{n}', f'2026-09-2{n + 1}', active_min=value)
                  for n, value in enumerate((19, 20, 20, 20, 21, 22))]
        before = [metrics_row(f'o{n}', f'2026-09-1{n}', active_min=value)
                  for n, value in enumerate((8, 9, 10, 11, 12))]
        write_metrics_rows(self.home, recent + before)
        self.assertIn('- active minutes 20 (n=6) vs 10 (n=5) (+100%) → real change', self.section())

    def test_the_same_values_spread_across_both_windows_end_with_within_noise(self):
        recent = [metrics_row(f'n{n}', f'2026-09-2{n + 1}', active_min=10 + 10 * (n % 2)) for n in range(6)]
        before = [metrics_row(f'o{n}', f'2026-09-1{n}', active_min=10 + 10 * (n % 2 == 1)) for n in range(5)]
        write_metrics_rows(self.home, recent + before)
        self.assertIn('- active minutes 15 (n=6) vs 10 (n=5) (+50%) → within noise', self.section())

    def test_a_clear_fall_ends_with_real_change(self):
        recent = [metrics_row(f'n{n}', f'2026-09-2{n + 1}', active_min=value)
                  for n, value in enumerate((8, 9, 10, 10, 11, 12))]
        before = [metrics_row(f'o{n}', f'2026-09-1{n}', active_min=value)
                  for n, value in enumerate((19, 20, 20, 21, 22))]
        write_metrics_rows(self.home, recent + before)
        self.assertIn('- active minutes 10 (n=6) vs 20 (n=5) (-50%) → real change', self.section())

    def test_the_floor_is_taken_from_the_earlier_window(self):
        recent = [metrics_row(f'n{n}', f'2026-09-2{n + 1}', active_min=value)
                  for n, value in enumerate((11.4, 11.5, 11.6, 11.6, 11.7, 11.8))]
        before = [metrics_row(f'o{n}', f'2026-09-1{n}', active_min=value)
                  for n, value in enumerate((9.8, 9.9, 10, 10.1, 10.2))]
        write_metrics_rows(self.home, recent + before)
        self.assertIn('- active minutes 11.6 (n=6) vs 10 (n=5) (+16%) → real change', self.section())

    def test_a_rise_from_zero_with_enough_sessions_gets_the_word_after_from_0(self):
        recent = [metrics_row(f'n{n}', f'2026-09-2{n + 1}', interrupts=3) for n in range(6)]
        before = [metrics_row(f'o{n}', f'2026-09-1{n}', interrupts=0) for n in range(5)]
        write_metrics_rows(self.home, recent + before)
        self.assertIn('- interrupts 3 (n=6) vs 0 (n=5) (from 0) → real change', self.section())

    def test_a_zero_to_zero_line_with_enough_sessions_has_no_change_part(self):
        recent = [metrics_row(f'n{n}', f'2026-09-2{n + 1}', interrupts=0) for n in range(6)]
        before = [metrics_row(f'o{n}', f'2026-09-1{n}', interrupts=0) for n in range(5)]
        write_metrics_rows(self.home, recent + before)
        self.assertIn('- interrupts 0 (n=6) vs 0 (n=5) → within noise', self.section())

    def test_window_edges_include_both_ends_and_leave_out_older_and_future_sessions(self):
        write_metrics_rows(self.home, [
            metrics_row('now', '2026-10-04', weighted=1000), metrics_row('recent-start', '2026-09-21', weighted=1000),
            metrics_row('prev-end', '2026-09-20', weighted=2000), metrics_row('prev-start', '2026-09-07', weighted=2000),
            metrics_row('too-old', '2026-09-06', weighted=9000), metrics_row('future', '2026-10-05', weighted=9000)])
        self.assertIn('- weighted tokens 1k (n=2) vs 2k (n=2)', self.section())

    def test_an_n_day_window_ends_today_and_holds_both_ends(self):
        self.assertEqual(trends.window_start(TODAY, 14), date(2026, 9, 21))
        self.assertEqual(trends.window_start(TODAY, 1), TODAY)
        write_metrics_rows(self.home, [metrics_row('first', '2026-09-21'), metrics_row('before', '2026-09-20'),
                                       metrics_row('today', '2026-10-04'), metrics_row('future', '2026-10-05')])
        found = trends.rows_in_window(self.ctx(today=TODAY), trends.window_start(TODAY, 14))
        self.assertEqual([(day, row['session_id']) for day, row in found],
                         [(date(2026, 9, 21), 'first'), (TODAY, 'today')])

    def test_an_empty_window_shows_a_dash_and_n_zero(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01', weighted=1500)])
        self.assertIn('- weighted tokens 2k (n=1) vs - (n=0)', self.section())
        write_metrics_rows(self.home, [metrics_row('b', '2026-09-10', weighted=1500)])
        self.assertIn('- weighted tokens - (n=0) vs 2k (n=1)', self.section())

    def test_kinds_are_listed_in_the_fixed_order_and_a_kind_without_sessions_is_left_out(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01', skills=['implement']),
                                       metrics_row('b', '2026-10-01', cwd=str(self.root / 'user-config')),
                                       metrics_row('c', '2026-10-01')])
        kinds = [line for line in self.section() if not line.startswith(('-', '#'))]
        self.assertEqual(kinds, ['**build**', '**config**', '**unknown**'])

    def test_an_override_moves_the_session_to_its_kind(self):
        write_text(self.home / 'session-kinds.jsonl', '{"session_id":"a","kind":"debug","set_on":"2026-10-02"}\n')
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01', skills=['implement'])])
        self.assertIn('**debug**', self.section())
        self.assertNotIn('**build**', self.section())

    def test_a_value_the_row_lacks_is_left_out_of_that_median_only(self):
        sparse = metrics_row('a', '2026-10-01', weighted=1000, active_min=10)
        del sparse['friction']
        write_metrics_rows(self.home, [sparse, metrics_row('b', '2026-10-02', weighted=3000, active_min=30,
                                                           interrupts=4)])
        lines = self.section()
        self.assertIn('- weighted tokens 2k (n=2) vs - (n=0)', lines)
        self.assertIn('- interrupts 4 (n=1) vs - (n=0)', lines)

    def test_rows_with_a_bad_timestamp_or_bad_numbers_are_skipped_not_fatal(self):
        broken = metrics_row('a', '2026-10-01')
        broken['first_ts'] = 'not a time'
        text = metrics_row('b', '2026-10-01', active_min=10)
        text['weighted'] = 'many'
        flag = metrics_row('c', '2026-10-01', interrupts=True)
        write_metrics_rows(self.home, [broken, text, flag, {'session_id': 'd'}])
        lines = self.section()
        self.assertIn('- weighted tokens 1k (n=1) vs - (n=0)', lines)
        self.assertIn('- active minutes 10 (n=2) vs - (n=0)', lines)
        self.assertIn('- interrupts 0 (n=1) vs - (n=0)', lines)

    def test_large_values_are_shortened(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01', weighted=1_234_567.8)])
        self.assertIn('- weighted tokens 1.2M (n=1) vs - (n=0)', self.section())

    def test_a_session_belongs_to_the_day_it_started_on_in_the_clock_of_the_context(self):
        east = timezone(timedelta(hours=8))
        write_metrics_rows(self.home, [metrics_row('late', '2026-09-20', hour=23, weighted=1000)])
        utc_lines = trends.trends_section(self.ctx(today=TODAY))
        self.assertIn('- weighted tokens - (n=0) vs 1k (n=1)', utc_lines)
        local = self.ctx(today=TODAY, now=datetime(2026, 10, 4, 12, tzinfo=east))
        self.assertIn('- weighted tokens 1k (n=1) vs - (n=0)', trends.trends_section(local))

    def test_the_section_does_not_change_the_context(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01')])
        ctx = self.ctx(today=TODAY)
        before = ctx.metrics_rows
        trends.trends_section(ctx)
        self.assertEqual(ctx.metrics_rows, before)


class TopSkillsTest(TrendsCase):
    def section(self):
        return trends.top_skills_section(self.ctx(today=TODAY))

    def test_no_skill_tokens_means_no_section(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01')])
        self.assertEqual(self.section(), [])

    def test_the_three_most_expensive_skills_of_the_last_window_by_summed_weighted_tokens(self):
        write_metrics_rows(self.home, [
            metrics_row('a', '2026-10-01', by_skill={'alpha': 500_000, 'beta': 300_000, 'gamma': 40_000}),
            metrics_row('b', '2026-10-02', by_skill={'alpha': 600_000, 'delta': 100_000, 'gamma': 0}),
            metrics_row('c', '2026-09-10', by_skill={'epsilon': 9_000_000})])
        self.assertEqual(self.section(), [
            '## Top skills by weighted tokens (last 14 days)',
            '- alpha  1.1M (2 sessions)',
            '- beta  300k (1 session)',
            '- delta  100k (1 session)',
        ])

    def test_ranking_uses_tokens_by_skill_not_the_skills_a_session_used(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01', skills=['implement'], slash=['model'],
                                                   by_skill={'alpha': 10})])
        self.assertEqual(self.section()[1:], ['- alpha  10 (1 session)'])


class ExperimentsDueTest(TrendsCase):
    def section(self):
        return trends.experiments_due_section(self.ctx(today=TODAY))

    def test_nothing_due_means_no_section(self):
        write_experiment_anomaly(self.home, 'later', check_by='2026-10-05')
        write_experiment_anomaly(self.home, 'no-date')
        self.assertEqual(self.section(), [])

    def test_a_check_date_that_has_passed_or_is_today_is_listed_oldest_first(self):
        write_experiment_anomaly(self.home, 'today', target='skill-a', metric='tokens', check_by='2026-10-04')
        write_experiment_anomaly(self.home, 'older', target='skill-b', metric='denials', check_by='2026-09-30')
        write_experiment_anomaly(self.home, 'later', check_by='2026-10-05')
        self.assertEqual(self.section(), [
            '## Experiments due',
            '- older · skill-b · denials · check by 2026-09-30',
            '- today · skill-a · tokens · check by 2026-10-04',
        ])

    def test_an_experiment_with_a_result_is_not_due(self):
        write_experiment_anomaly(self.home, 'done', check_by='2026-09-01', result='keep')
        self.assertEqual(self.section(), [])


class ExperimentResultsTest(TrendsCase):
    def section(self):
        return trends.experiment_results_section(self.ctx(today=TODAY))

    def test_it_shows_with_every_count_zero_when_there_is_no_experiment_at_all(self):
        self.assertEqual(self.section(), [
            '## Experiment results', '- keep 0 · unproven 0 · revert 0 · inconclusive 0 · pending 0'])

    def test_it_shows_when_nothing_is_due(self):
        write_experiment_anomaly(self.home, 'later', check_by='2026-10-05')
        self.assertEqual(trends.experiments_due_section(self.ctx(today=TODAY)), [])
        self.assertEqual(self.section(), [
            '## Experiment results', '- keep 0 · unproven 0 · revert 0 · inconclusive 0 · pending 1'])

    def test_each_current_experiment_counts_once_by_result_and_unproven_is_not_keep(self):
        for signature, result in (('k1', 'keep'), ('u1', 'unproven'), ('u2', 'unproven'), ('r1', 'revert'),
                                  ('i1', 'inconclusive'), ('p1', '')):
            write_experiment_anomaly(self.home, signature, result=result)
        self.assertEqual(self.section(), [
            '## Experiment results', '- keep 1 · unproven 2 · revert 1 · inconclusive 1 · pending 1'])

    def test_an_archived_experiment_and_an_anomaly_without_experiment_are_not_counted(self):
        from anomaly_loop import records
        path = write_experiment_anomaly(self.home, 'retried', result='revert')
        anomaly = records.read_anomaly(path)
        records.archive_experiment(anomaly)
        anomaly.experiment = records.Experiment(expect='b', metric='interrupts', guard='rework sightings')
        records.write_anomaly(self.home, anomaly)
        write_text(self.home / 'anomalies' / 'plain.md', anomaly_text('plain', 2, 2))
        self.assertEqual(self.section(), [
            '## Experiment results', '- keep 0 · unproven 0 · revert 0 · inconclusive 0 · pending 1'])


class ExperimentDueBySessionsTest(TrendsCase):
    """The session half of "due": EXPERIMENT_CHECK_SESSIONS sessions of the experiment's kind on the
    days after the fix day, while the check date is still ahead."""
    FIX = '2026-09-28 · abc1234'

    def build_rows(self, days, skills=('implement',)):
        return [metrics_row(f's{n}', day, skills=list(skills)) for n, day in enumerate(days)]

    def days_after_fix(self, count):
        """`count` session days between the fix day and today, several sessions on the same day."""
        return [date(2026, 9, 29) + timedelta(days=n % 5) for n in range(count)]

    def due(self, signature='slow'):
        [anomaly] = [a for a in self.ctx(today=TODAY).anomalies if a.signature == signature]
        return trends.experiment_due(self.ctx(today=TODAY), anomaly)

    def test_twenty_sessions_of_the_kind_after_the_fix_day_make_it_due(self):
        write_metrics_rows(self.home, self.build_rows(self.days_after_fix(20)))
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-20', kind='build', fixed_by=self.FIX)
        self.assertEqual(self.due(), '20 build sessions since the fix')
        self.assertEqual(self.section(), [
            '## Experiments due',
            '- slow · demo-skill · active minutes · check by 2026-10-20 · 20 build sessions since the fix'])

    def section(self):
        return trends.experiments_due_section(self.ctx(today=TODAY))

    def test_nineteen_sessions_are_not_enough(self):
        write_metrics_rows(self.home, self.build_rows(self.days_after_fix(19)))
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-20', kind='build', fixed_by=self.FIX)
        self.assertIsNone(self.due())

    def test_sessions_on_the_fix_day_or_after_today_do_not_count(self):
        days = [*self.days_after_fix(19), '2026-09-28', '2026-09-28', '2026-10-05']
        write_metrics_rows(self.home, self.build_rows(days))
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-20', kind='build', fixed_by=self.FIX)
        self.assertIsNone(self.due())

    def test_sessions_of_another_kind_do_not_count_and_an_override_does(self):
        rows = self.build_rows(self.days_after_fix(19))
        rows.append(metrics_row('other', '2026-10-03'))
        write_metrics_rows(self.home, [*rows])
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-20', kind='build', fixed_by=self.FIX)
        self.assertIsNone(self.due())
        write_text(self.home / 'session-kinds.jsonl',
                   json.dumps({'session_id': 'other', 'kind': 'build', 'set_on': '2026-10-03'}) + '\n')
        self.assertEqual(self.due(), '20 build sessions since the fix')

    def test_a_switch_over_counts_only_sessions_that_ran_the_new_skill_and_no_old_one(self):
        write_build_skills_profile(self.home, 'implement, build, demo:build')
        days = self.days_after_fix(25)
        rows = [metrics_row(f'new{n}', day, skills=['demo:build']) for n, day in enumerate(days[:19])]
        rows += [metrics_row(f'old{n}', day, skills=['implement']) for n, day in enumerate(days[19:24])]
        rows.append(metrics_row('fall-back', days[24], skills=['demo:build', 'implement']))
        rows.append(metrics_row('bare-fall-back', days[24], skills=['demo:build', 'other:build']))
        write_metrics_rows(self.home, rows)
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-20', kind='build', fixed_by=self.FIX,
                                 skill='demo:build')
        write_experiment_anomaly(self.home, 'dated', check_by='2026-10-01', kind='build', fixed_by=self.FIX,
                                 skill='demo:build')
        self.assertIsNone(self.due())
        self.assertIsNone(self.due('dated'))
        self.assertEqual(self.section(), ['## Experiments due', '- dated · demo-skill · active minutes · '
                                          '19/20 demo:build sessions, 2 fall-backs · stalled: due only after 20 '
                                          'new-skill sessions'])
        write_metrics_rows(self.home, rows + [metrics_row('new19', '2026-10-03', skills=['demo:build'])])
        self.assertEqual(self.due(), '20 demo:build sessions since the fix')

    def test_without_a_kind_or_without_a_fix_date_only_the_check_date_counts(self):
        write_metrics_rows(self.home, self.build_rows(self.days_after_fix(20)))
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-20', fixed_by=self.FIX)
        write_experiment_anomaly(self.home, 'old', check_by='2026-10-20', kind='build', fixed_by='abc1234')
        self.assertIsNone(self.due('slow'))
        self.assertIsNone(self.due('old'))

    def test_a_draft_or_a_judged_experiment_is_never_due_by_sessions(self):
        write_metrics_rows(self.home, self.build_rows(self.days_after_fix(20)))
        write_experiment_anomaly(self.home, 'slow', kind='build', fixed_by='')
        write_experiment_anomaly(self.home, 'kept', check_by='2026-10-20', kind='build', fixed_by=self.FIX,
                                 result='keep')
        self.assertIsNone(self.due('slow'))
        self.assertIsNone(self.due('kept'))

    def test_the_check_date_reason_comes_first(self):
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-01', kind='build', fixed_by=self.FIX)
        self.assertEqual(self.due(), 'check date reached')

    def test_an_inconclusive_result_comes_back_when_its_moved_date_passes(self):
        write_experiment_anomaly(self.home, 'slow', check_by='2026-10-04', result='inconclusive', fixed_by=self.FIX)
        write_experiment_anomaly(self.home, 'later', check_by='2026-10-05', result='inconclusive', fixed_by=self.FIX)
        self.assertEqual(self.due('slow'), 'still inconclusive: the user decides')
        self.assertIsNone(self.due('later'))
        self.assertEqual(self.section()[1:],
                         ['- slow · demo-skill · active minutes · check by 2026-10-04 · '
                          'still inconclusive: the user decides'])


class FixWindowsTest(TrendsCase):
    def test_the_baseline_is_the_days_before_the_fix_day_and_after_is_the_days_after_it(self):
        fix = date(2026, 9, 20)
        days = ['2026-08-22', '2026-08-23', '2026-09-19', '2026-09-20', '2026-09-21', '2026-10-04', '2026-10-05']
        write_metrics_rows(self.home, [metrics_row(day, day) for day in days])
        before, after = trends.fix_windows(self.ctx(today=TODAY), fix)
        self.assertEqual([row['session_id'] for row in before], ['2026-08-23', '2026-09-19'])
        self.assertEqual([row['session_id'] for row in after], ['2026-09-21', '2026-10-04'])

    def test_a_kind_keeps_only_sessions_of_that_kind(self):
        write_metrics_rows(self.home, [metrics_row('b', '2026-09-25', skills=['implement']),
                                       metrics_row('u', '2026-09-25')])
        before, after = trends.fix_windows(self.ctx(today=TODAY), date(2026, 9, 20), kind='build')
        self.assertEqual(([r['session_id'] for r in before], [r['session_id'] for r in after]), ([], ['b']))


class RevertedTest(TrendsCase):
    def section(self):
        return trends.reverted_section(self.ctx(today=TODAY))

    def test_no_reverted_experiment_means_no_section(self):
        write_experiment_anomaly(self.home, 'kept', check_by='2026-09-01', result='keep')
        write_experiment_anomaly(self.home, 'open', check_by='2026-09-01')
        self.assertEqual(self.section(), [])

    def test_a_reverted_experiment_shows_target_metric_check_date_and_the_first_line_of_the_fix(self):
        write_experiment_anomaly(self.home, 'went-wrong', target='skill-a', metric='tokens',
                                 check_by='2026-09-20', result='revert',
                                 proposed_fix='\nShorten the prompt.\nSecond line.')
        write_experiment_anomaly(self.home, 'fine', result='inconclusive')
        self.assertEqual(self.section(), [
            '## Tried and reverted',
            '- went-wrong · skill-a · tokens · check by 2026-09-20 · fix: Shorten the prompt.',
        ])

    def test_the_verdict_reason_is_shown_when_recorded(self):
        from anomaly_loop import records
        path = write_experiment_anomaly(self.home, 'went-wrong', target='skill-a', metric='tokens',
                                        check_by='2026-09-20', result='revert', proposed_fix='Shorten it.')
        anomaly = records.read_anomaly(path)
        anomaly.experiment.reason = 'tokens got worse'
        records.write_anomaly(self.home, anomaly)
        self.assertEqual(self.section()[1], '- went-wrong · skill-a · tokens · check by 2026-09-20 · fix: Shorten it.'
                                            ' · reason: tokens got worse')

    def test_a_missing_fix_or_target_is_left_out_or_marked_not_invented(self):
        write_experiment_anomaly(self.home, 'bare', target='', check_by='2026-09-20', result='revert',
                                 proposed_fix='')
        self.assertEqual(self.section()[1], '- bare · no target · active minutes · check by 2026-09-20')

    def test_extra_anomaly_fields_pass_through_the_fixture(self):
        path = write_experiment_anomaly(self.home, 'closed', check_by='2026-09-20', result='revert',
                                        status='fixed', fixed_by='2026-09-10')
        self.assertIn('fixed_by: 2026-09-10', path.read_text(encoding='utf-8'))
        self.assertEqual(len(self.section()), 2)

    def test_an_archived_reverted_attempt_is_listed_after_a_new_experiment_replaced_it(self):
        from anomaly_loop import records
        path = write_experiment_anomaly(self.home, 'retried', target='skill-a', metric='tokens', result='revert',
                                        fixed_by='2026-09-10 · abc1234')
        anomaly = records.read_anomaly(path)
        records.archive_experiment(anomaly)
        anomaly.experiment = records.Experiment(expect='b', metric='interrupts', guard='rework sightings')
        records.write_anomaly(self.home, anomaly)
        self.assertEqual(self.section(), [
            '## Tried and reverted',
            '- retried · skill-a · earlier: revert · fixed 2026-09-10 · abc1234 · metric tokens · guard rework · '
            'expect faster'])

    def test_a_long_fix_line_is_cut(self):
        write_experiment_anomaly(self.home, 'wordy', check_by='2026-09-20', result='revert',
                                 proposed_fix='word ' * 60)
        line = self.section()[1]
        self.assertTrue(line.endswith('…'))
        self.assertLess(len(line), 200)


class RegistrationTest(TrendsCase):
    def test_the_sections_open_the_digest_in_this_order(self):
        self.assertEqual(digest.SECTIONS[:4], (('trends', 'trends_section'), ('trends', 'top_skills_section'),
                                               ('trends', 'experiments_due_section'),
                                               ('trends', 'experiment_results_section')))
        self.assertIn(('trends', 'reverted_section'), digest.SECTIONS)
        self.assertLess(digest.SECTIONS.index(('trends', 'reverted_section')),
                        digest.SECTIONS.index(('index', 'digest_section')))

    def test_the_digest_renders_them_with_no_data_folder(self):
        write_metrics_rows(self.home, [metrics_row('a', '2026-10-01', by_skill={'alpha': 10})])
        write_experiment_anomaly(self.home, 'due', check_by='2026-10-01')
        lines = digest.render(self.ctx(today=TODAY, data=None))
        headings = [line for line in lines if line.startswith('## ')]
        self.assertEqual(headings[:4], ['## Trends: last 14 days vs the 14 before (median, n = sessions; interrupts: mean)',
                                        '## Top skills by weighted tokens (last 14 days)',
                                        '## Experiments due', '## Experiment results'])
        self.assertEqual(headings[-1], '## Backlog')


if __name__ == '__main__':
    unittest.main()

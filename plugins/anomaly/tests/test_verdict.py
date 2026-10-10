import unittest
from datetime import date
from types import SimpleNamespace
from unittest import mock

from anomaly_loop import constants, permutation, records, trends, verdict
from tests.fixtures import metrics_row, write_anomaly_with, write_experiment_anomaly, write_metrics_rows
from tests.test_calibrate import FIX, CalibrateCase

RULE = '; permutation test, ADR-0009'   # every verdict reason ends with the rule that produced it
RARE_RULE = '; rare-event rule, ADR-0009'   # ... and a rare-event primary's with its own rule


def shown(sample):
    """(value, sessions) of a Sample: what a reading line shows."""
    return sample.value, sample.n


PER_DISPATCH = 'model-weighted tokens per dispatch'   # the metric is this name and an agent name


def dispatch_row(session, dispatches, model_weighted, agent='anomaly:facts', unknown_models=None, **others):
    """A metrics row of a session that dispatched `agent` `dispatches` times, whose calls weigh
    `model_weighted`, as metrics.build_row names the fields (`subagents.by_type`,
    `model_weighted_by_agent`, `unknown_model_by_agent`). `others` maps other agents to
    (dispatches, model-weighted tokens)."""
    spawned = {agent: (dispatches, model_weighted), **others}
    return metrics_row(session, '2026-10-01', subagents={'by_type': {name: n for name, (n, _) in spawned.items()}},
                       model_weighted_by_agent={name: total for name, (_, total) in spawned.items()},
                       unknown_model_by_agent=unknown_models or {})


# ---------- the metric registry ----------

class RegistryTest(unittest.TestCase):
    def test_the_trend_metrics_and_the_sighting_metrics_are_registered(self):
        names = verdict.METRIC_NAMES
        for name in ('weighted tokens', 'active minutes', 'interrupts', 'denials', 'sightings since the fix',
                     'rework sightings', 'late-catch sightings'):
            self.assertIn(name, names)
        for category in constants.CATEGORIES:
            self.assertIn(f'{category} sightings', names)
        self.assertEqual(len(names), len(set(names)))

    def test_weighted_tokens_without_security_leave_the_security_reviewers_tokens_out(self):
        rows = [metrics_row('s1', '2026-10-01', weighted=1000.0, tokens_by_agent={
                    'anomaly:security': {'weighted': 300.0}, 'anomaly:code': {'weighted': 200.0}}),
                metrics_row('s2', '2026-10-01', weighted=900.0, tokens_by_agent={}),
                metrics_row('s3', '2026-10-01', weighted=800.0)]
        found = verdict.resolve_metric('weighted tokens without security').read(None, None, rows, None)
        self.assertEqual((found.values, found.value), ((700.0, 900.0, 800.0), 800.0))

    def test_model_weighted_tokens_per_dispatch_resolves_for_any_agent_name_and_divides_by_its_dispatches(self):
        for agent in ('anomaly:facts', 'Explore'):
            with self.subTest(agent=agent):
                rows = [dispatch_row('s1', 4, 800.0, agent, other=(3, 9999.0)),
                        dispatch_row('s2', 2, 900.0, agent)]
                found = verdict.resolve_metric(f'{PER_DISPATCH} {agent}')
                self.assertEqual(found.name, f'{PER_DISPATCH} {agent}')   # the agent's case is kept
                self.assertEqual(found.read(None, None, rows, None).values, (200.0, 450.0))

    def test_a_session_with_no_dispatch_of_the_agent_has_no_value_rather_than_0(self):
        rows = [dispatch_row('s1', 2, 400.0),
                dispatch_row('s2', 1, 50.0, agent='anomaly:code'),
                metrics_row('s3', '2026-10-01')]
        found = verdict.resolve_metric(f'{PER_DISPATCH} anomaly:facts').read(None, None, rows, None)
        self.assertEqual(found.values, (200.0,))

    def test_a_session_with_a_call_of_the_agent_on_a_model_with_no_factor_has_no_value(self):
        rows = [dispatch_row('s1', 2, 400.0),
                dispatch_row('s2', 2, 400.0, unknown_models={'anomaly:facts': 1}),
                dispatch_row('s3', 2, 600.0, other=(1, 5.0), unknown_models={'other': 1})]   # another agent's call
        found = verdict.resolve_metric(f'{PER_DISPATCH} anomaly:facts').read(None, None, rows, None)
        self.assertEqual(found.values, (200.0, 300.0))

    def test_a_session_with_a_spawn_without_meta_has_no_value_since_its_calls_count_but_not_its_dispatch(self):
        short = {**dispatch_row('s2', 2, 400.0), 'skipped_spawns': 1}   # its dispatch is counted as `unknown`
        rows = [dispatch_row('s1', 2, 400.0), short, {**dispatch_row('s3', 2, 600.0), 'skipped_spawns': 0}]
        found = verdict.resolve_metric(f'{PER_DISPATCH} anomaly:facts').read(None, None, rows, None)
        self.assertEqual(found.values, (200.0, 300.0))

    def test_a_name_resolves_without_regard_to_case_or_outer_spaces(self):
        self.assertEqual(verdict.resolve_metric('  Active Minutes ').name, 'active minutes')
        self.assertEqual(verdict.resolve_metric('  Model-Weighted Tokens Per Dispatch anomaly:facts ').name,
                         f'{PER_DISPATCH} anomaly:facts')   # the prefix is read in any case, the agent keeps its own

    def test_an_unknown_or_double_name_is_a_clear_error_that_lists_the_known_ones(self):
        for name in ('active minutes per build session', 'active minutes, weighted tokens', '',
                     f'{PER_DISPATCH} a b', f'{PER_DISPATCH} <agent>'):
            with self.assertRaises(records.RecordError) as caught:
                verdict.resolve_metric(name)
            self.assertIn('unknown metric', str(caught.exception))
            self.assertIn('weighted tokens', str(caught.exception))


class SightingRateTest(CalibrateCase):
    DAYS = (date(2026, 9, 1), date(2026, 9, 10))

    def read(self, lines, rows, kind='build'):
        """The window Sample of the registered `sightings since the fix`, for an anomaly with `lines`."""
        anomaly = SimpleNamespace(sightings=lines, experiment=SimpleNamespace(kind=kind, skill=''))
        return verdict.REGISTRY[verdict.SIGHTINGS_SINCE_FIX].read(self.ctx(), anomaly, rows, self.DAYS)

    def rate(self, lines, kind='build'):
        rows = [metrics_row('b1', '2026-09-02', skills=['implement']), metrics_row('b2', '2026-09-03', skills=['implement'])]
        write_metrics_rows(self.home, rows + [metrics_row('u1', '2026-09-04'),
                                              metrics_row('o1', '2026-08-20', skills=['implement'])])
        self.backlog_started('2026-08-01')
        return self.read(lines, rows, kind)

    def test_a_sighting_from_a_measured_session_of_another_kind_is_left_out(self):
        self.assertEqual(self.rate(['2026-09-04 · demo · u1 · other kind']), (0, (0, 0), 0))
        self.assertEqual(self.rate(['2026-09-04 · demo · u1 · other kind'], kind=''), (0.5, (0, 0), 1))

    def test_a_sighting_from_a_session_that_was_not_measured_counts(self):
        self.assertEqual(self.rate(['2026-09-05 · demo · never-measured · seen']), (0.5, (0, 0), 1))

    def test_a_sighting_from_a_measured_session_of_the_kind_outside_the_window_counts_as_left_out(self):
        self.assertEqual(self.rate(['2026-09-05 · demo · o1 · seen']), (0.5, (0, 0), 1))

    def test_an_identical_line_counts_once(self):
        line = '2026-09-02 · demo · b1 · seen'
        self.assertEqual(self.rate([line, line]), (0.5, (1, 0), 0))

    def test_a_sighting_on_the_first_day_of_the_window_counts_and_the_day_before_does_not(self):
        self.assertEqual(self.rate(['2026-09-01 · demo · b1 · first day', '2026-08-31 · demo · b1 · before']),
                         (0.5, (1, 0), 0))

    def test_a_window_that_starts_on_the_backlogs_first_day_is_known(self):
        rows = [metrics_row('b1', '2026-09-02', skills=['implement'])]
        write_metrics_rows(self.home, rows)
        self.backlog_started('2026-09-01')
        self.assertEqual(self.read([], rows), (0, (0,), 0))

    def test_a_window_that_starts_before_the_backlog_began_is_unknown(self):
        rows = [metrics_row('b1', '2026-09-02', skills=['implement'])]
        write_metrics_rows(self.home, rows)
        self.backlog_started('2026-09-05')
        self.assertEqual(self.read([], rows), (None, (0,), 0))


# ---------- the verdict ----------

class VerdictCase(CalibrateCase):
    def experiment(self, metric='active minutes', guard='rework sightings', kind='build', fixed_by=FIX, **fields):
        write_experiment_anomaly(self.home, 'slow-check', metric=metric, guard=guard, kind=kind,
                                 fixed_by=fixed_by, check_by='2026-10-01', status='fixed', **fields)

    def judged(self):
        ctx = self.ctx()
        [anomaly] = [a for a in ctx.anomalies if a.signature == 'slow-check']
        return verdict.verdict(ctx, anomaly)

    def redo(self, rows, day='2026-09-23', signature='redo'):
        """A rework problem seen once in each session of `rows` (by session id), on `day`."""
        lines = [f'{day} · demo · {row["session_id"]} · redone {n}' for n, row in enumerate(rows)]
        write_anomaly_with(self.home, signature, category='rework', occurrences=len(lines), sightings=lines)


class VerdictTest(VerdictCase):
    def test_a_real_change_for_the_better_gives_keep_and_names_the_rule(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment()
        found = self.judged()
        self.assertEqual(found[:2], ('keep', 'active minutes made a real change for the better and the guard held'
                                     + RULE))
        primary, guard = found.readings[:2]
        self.assertEqual((shown(primary.before), shown(primary.after)), ((20, 6), (10, 5)))
        self.assertEqual((guard.before, guard.after), ((0, (0,) * 6, 0), (0, (0,) * 5, 0)))

    def test_too_few_sessions_on_a_side_is_inconclusive(self):
        for after_active in (10, 40):
            with self.subTest(after_active=after_active):
                self.baseline_and_after(before_active=20, after_active=after_active, after_n=4)
                self.experiment()
                found = self.judged()
                self.assertEqual(found.result, 'inconclusive')
                self.assertIn(f'active minutes cannot be judged yet: fewer than {constants.VERDICT_MIN_SAMPLES} '
                              'sessions on a side', found.reason)

    def test_the_same_data_gives_the_same_chance_alone_and_result_with_many_sessions(self):
        self.baseline_and_after(before_active=20, after_active=18, before_n=25, after_n=25)
        self.experiment()
        first, second = self.judged(), self.judged()
        lines = [verdict.reading_line(found.readings[0], 'primary') for found in (first, second)]
        self.assertEqual((lines[0], first.result), (lines[1], second.result))
        self.assertIn('(n=25) since, -10%; 13% of random splits change this much → within noise', lines[0])
        self.baseline_and_after(before_active=20, after_active=10, before_n=25, after_n=25)
        self.assertIn('-50%; 1% of random splits change this much → real change',
                      verdict.reading_line(self.judged().readings[0], 'primary'))

    def test_a_change_below_the_floor_is_within_noise_even_when_chance_alone_is_low(self):
        self.baseline_and_after(before_active=20, after_active=17.6, before_n=25, after_n=25)
        self.experiment()
        found = self.judged()
        self.assertIn('-12%; 6% of random splits change this much → within noise',
                      verdict.reading_line(found.readings[0], 'primary'))
        self.assertEqual(found.result, 'inconclusive')

    def test_left_out_sightings_cannot_turn_a_tested_rise_into_an_improvement(self):
        before, after = self.baseline_and_after()
        self.redo(before[:1] + [{'session_id': 'never-measured'}] * 8, day='2026-09-12', signature='redo-before')
        self.redo(after)
        self.experiment(metric='rework sightings', guard='late-catch sightings')
        found = self.judged()
        line = verdict.reading_line(found.readings[0], 'primary')
        self.assertIn('1.5 (n=6) before, 1 (n=5) since, -33%; 2% of random splits change this much → within noise',
                      line)
        self.assertIn('→ within noise; the tested sessions moved the other way', line)
        self.assertEqual(found[:2], ('inconclusive', 'rework sightings is within noise' + RULE))

    def test_only_sessions_of_the_experiment_kind_count(self):
        self.baseline_and_after(before_active=20, after_active=10)
        rows = self.ctx().metrics_rows + tuple(self.rows(['2026-09-23'] * 5, active=90, skills=(), prefix='u'))
        write_metrics_rows(self.home, list(rows))
        self.experiment()
        self.assertEqual(shown(self.judged().readings[0].after), (10, 5))
        self.experiment(kind='')
        self.assertEqual(self.judged().readings[0].after.n, 10)

    def test_a_worse_primary_reverts(self):
        self.baseline_and_after(before_active=10, after_active=20)
        self.experiment()
        self.assertEqual(self.judged()[:2], ('revert', 'active minutes got worse' + RULE))

    def test_a_guard_that_fell_lets_a_better_primary_keep(self):
        before, _ = self.baseline_and_after(before_active=20, after_active=10)
        self.redo(before[:3], day='2026-09-12')
        self.experiment()
        found = self.judged()
        self.assertEqual((found.readings[1].before.value, found.readings[1].after.value), (0.5, 0))
        self.assertEqual(found.result, 'keep')
        self.assertEqual(verdict.reading_line(found.readings[1], 'guard'),
                         '- rework sightings (guard): 0.5 (n=6) before, 0 (n=5) since, -100%; '
                         '100% of random splits change this much → within noise')

    def test_three_rework_sightings_after_the_fix_make_the_guard_worse(self):
        before, after = self.baseline_and_after(before_active=20, after_active=10)
        self.redo(after[1:4])
        self.experiment()
        found = self.judged()
        self.assertEqual(found.readings[1].after, (0.6, (0, 1, 1, 1, 0), 0))
        self.assertEqual(found.readings[1].sightings, 3)
        self.assertEqual(found[:2], ('revert', 'the guard rework sightings got worse; quality comes first' + RULE))
        self.assertEqual(verdict.reading_line(found.readings[1], 'guard'),
                         '- rework sightings (guard): 0 (n=6) before, 0.6 (n=5) since, from 0; '
                         '7% of random splits change this much → real change')

    def test_the_guard_reads_the_one_way_level_not_the_two_way_one(self):
        _, after = self.baseline_and_after(before_active=20, after_active=10)
        self.redo(after[1:4])
        self.experiment()
        self.assertEqual(self.judged().result, 'revert')   # chance alone for a rise is 7%, at or below 10%
        with mock.patch.dict(trends.LEVELS, {permutation.TWO_WAY: 0.10, permutation.WORSE: 0.05}):
            found = self.judged()
        self.assertEqual(verdict.compare(found.readings[1]), 'same')
        self.assertEqual(found[:2], ('keep', 'active minutes made a real change for the better and the guard held'
                                     + RULE))

    def test_two_rework_sightings_after_the_fix_are_within_noise_for_the_guard(self):
        _, after = self.baseline_and_after(before_active=20, after_active=10)
        self.redo(after[1:3])
        self.experiment()
        found = self.judged()
        self.assertEqual(found.readings[1].sightings, 2)
        self.assertEqual(found.result, 'keep')
        line = verdict.reading_line(found.readings[1], 'guard')
        self.assertIn('0.4 (n=5) since, from 0; ', line)
        self.assertIn('→ within noise', line)

    def test_a_guard_that_would_be_worse_on_one_sighting_is_thin_and_inconclusive(self):
        _, after = self.baseline_and_after(before_active=20, after_active=10, before_n=60, after_n=5)
        self.redo(after[:1])
        self.experiment()
        found = self.judged()
        self.assertEqual(verdict.compare(found.readings[1]), 'worse')
        self.assertEqual(found.result, 'inconclusive')
        self.assertIn(f'{constants.GUARD_MIN_SIGHTINGS} sightings', found.reason)

    def test_one_sighting_against_few_sessions_is_within_noise_not_thin(self):
        _, after = self.baseline_and_after(before_active=20, after_active=10)
        self.redo(after[:1])
        self.experiment()
        found = self.judged()
        self.assertEqual(verdict.compare(found.readings[1]), 'same')
        self.assertEqual(found.result, 'keep')

    def test_a_guard_read_per_session_needs_no_sightings(self):
        before, after = self.baseline_and_after(before_active=20, after_active=10)
        for row in after:
            row['friction']['interrupts'] = 2
        write_metrics_rows(self.home, before + after)
        self.experiment(guard='interrupts')
        found = self.judged()
        self.assertEqual(found.result, 'revert')
        self.assertIn('the guard interrupts got worse', found.reason)

    def test_a_sighting_metric_named_as_the_guard_is_judged_like_any_other_guard(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment(guard='sightings since the fix')
        found = self.judged()
        self.assertEqual(found.result, 'keep')
        self.assertEqual(verdict.reading_line(found.readings[1], 'guard'),
                         '- sightings since the fix (guard): 0 (n=6) before, 0 (n=5) since; '
                         '100% of random splits change this much → within noise')

    def rare_event(self, sightings=(), **fields):
        """The experiment of a fix judged by recurrence: the anomaly's own `sightings`."""
        self.experiment(metric='sightings since the fix', sightings=list(sightings), **fields)
        return self.judged()

    def test_a_rare_event_fix_that_did_not_come_back_is_unproven_and_its_line_has_no_test_part(self):
        before, after = self.baseline_and_after()
        found = self.rare_event([f'2026-09-1{n} · demo · {row["session_id"]} · seen'
                                 for n, row in enumerate(before[:3])])
        self.assertEqual(found.readings[0].before, (0.5, (1, 1, 1, 0, 0, 0), 0))
        self.assertEqual(found.readings[0].after, (0, (0,) * 5, 0))
        self.assertEqual(found[:2], ('unproven', 'no recurrence in build sessions since the fix' + RARE_RULE))
        self.assertEqual(found.sightings_since, 0)
        self.assertEqual(verdict.reading_line(found.readings[0], 'primary'),
                         '- sightings since the fix (primary): 0.5 (n=6) before, 0 (n=5) since; '
                         'sightings since the fix: 0')

    def test_a_rare_event_fix_that_came_back_reverts_and_the_line_shows_the_sightings(self):
        _, after = self.baseline_and_after()
        found = self.rare_event([f'2026-09-25 · demo · {after[0]["session_id"]} · back'])
        self.assertEqual(found[:2], ('revert', 'the anomaly came back after the fix (sightings since the fix: 1)'
                                     + RARE_RULE))
        self.assertEqual(verdict.reading_line(found.readings[0], 'primary'),
                         '- sightings since the fix (primary): 0 (n=6) before, 0.2 (n=5) since; '
                         'sightings since the fix: 1')

    def test_a_sighting_from_a_measured_session_of_another_kind_does_not_bring_a_rare_event_fix_back(self):
        self.baseline_and_after()
        write_metrics_rows(self.home, list(self.ctx().metrics_rows) + [metrics_row('u1', '2026-09-25')])
        lines = ['2026-09-25 · demo · u1 · another kind']
        found = self.rare_event(lines)
        self.assertEqual((found.result, found.sightings_since), ('unproven', 0))
        found = self.rare_event(lines, kind='')
        self.assertEqual((found.result, found.sightings_since), ('revert', 1))

    def test_the_unproven_reason_names_the_kind_only_when_the_experiment_has_one(self):
        self.baseline_and_after()
        self.assertEqual(self.rare_event(kind='')[:2], ('unproven', 'no recurrence since the fix' + RARE_RULE))

    def test_a_worse_guard_reverts_a_rare_event_fix_before_the_recurrence_is_read(self):
        _, after = self.baseline_and_after()
        self.redo(after[1:4])
        found = self.rare_event([f'2026-09-25 · demo · {after[0]["session_id"]} · back'])
        self.assertEqual(found[:2], ('revert', 'the guard rework sightings got worse; quality comes first'
                                     + RARE_RULE))

    def test_a_guard_the_backlog_cannot_judge_does_not_block_a_rare_event_fix_and_is_named(self):
        self.baseline_and_after()
        self.backlog_started('2026-09-01')
        found = self.rare_event()
        self.assertEqual(found[:2], ('unproven', 'no recurrence in build sessions since the fix; the guard rework sightings could '
                                     'not be judged (the backlog does not cover its baseline)' + RARE_RULE))
        self.assertEqual(self.rare_event(['2026-09-25 · demo · x1 · back'])[:2], (
            'revert', 'the anomaly came back after the fix (sightings since the fix: 1); the guard rework '
                      'sightings could not be judged (the backlog does not cover its baseline)' + RARE_RULE))

    def test_a_guard_with_too_few_sessions_does_not_block_a_rare_event_fix_and_is_named(self):
        self.baseline_and_after(after_n=4)
        found = self.rare_event()
        self.assertEqual(found[:2], ('unproven', 'no recurrence in build sessions since the fix; the guard rework sightings could '
                                     'not be judged (fewer than 5 sessions on a side)' + RARE_RULE))

    def test_a_thin_guard_does_not_block_a_rare_event_fix_and_is_named(self):
        _, after = self.baseline_and_after(before_n=60, after_n=5)
        self.redo(after[:1])
        found = self.rare_event()
        self.assertEqual(verdict.guard_look(found.readings[1]), 'thin')
        self.assertEqual(found[:2], ('unproven', 'no recurrence in build sessions since the fix; the guard rework sightings could '
                                     f'not be judged (it rose by fewer than {constants.GUARD_MIN_SIGHTINGS} '
                                     'sightings)' + RARE_RULE))

    def test_sightings_since_the_fix_are_always_reported(self):
        self.baseline_and_after()
        self.experiment(sightings=['2026-09-25 · demo · x1 · back', '2026-09-20 · demo · x0 · on the fix day',
                                   '2026-09-01 · demo · x2 · old'])
        self.assertEqual(self.judged().sightings_since, 1)

    def test_sightings_on_the_fix_day_are_counted_apart(self):
        self.baseline_and_after()
        self.experiment(sightings=['2026-09-20 · demo · x0 · on the fix day', '2026-09-20 · demo · x1 · again',
                                   '2026-09-01 · demo · x2 · old'])
        found = self.judged()
        self.assertEqual((found.sightings_since, found.fix_day_sightings), (0, 2))

    def test_weighted_tokens_as_primary_also_reads_active_minutes_and_time_comes_before_tokens(self):
        self.baseline_and_after(before_weighted=2000, after_weighted=1000, before_active=10, after_active=20)
        self.experiment(metric='weighted tokens')
        found = self.judged()
        self.assertEqual([r.name for r in found.readings], ['weighted tokens', 'rework sightings', 'active minutes'])
        self.assertEqual(found[:2], ('revert', 'active minutes got worse; time comes before tokens' + RULE))
        self.baseline_and_after(before_weighted=2000, after_weighted=1000, before_active=10, after_active=10)
        self.assertEqual(self.judged().result, 'keep')

    def dispatch_fields(self, rows, model_weighted, unknown=()):
        """Give each of `rows` two dispatches of anomaly:facts weighing `model_weighted`; the rows at
        the indexes `unknown` have a call of it on a model with no factor. Rewrites the metrics file."""
        for index, row in enumerate(rows):
            fields = dispatch_row(row['session_id'], 2, model_weighted,
                                  unknown_models={'anomaly:facts': 1} if index in unknown else None)
            row.update({key: fields[key] for key in ('subagents', 'model_weighted_by_agent', 'unknown_model_by_agent')})

    def test_model_weighted_tokens_per_dispatch_also_reads_active_minutes_and_time_comes_before_tokens(self):
        before, after = self.baseline_and_after(before_active=10, after_active=20)
        self.dispatch_fields(before, 400.0)
        self.dispatch_fields(after, 200.0)
        write_metrics_rows(self.home, before + after)
        self.experiment(metric=f'{PER_DISPATCH} anomaly:facts')
        found = self.judged()
        self.assertEqual([r.name for r in found.readings],
                         [f'{PER_DISPATCH} anomaly:facts', 'rework sightings', 'active minutes'])
        self.assertEqual(found[:2], ('revert', 'active minutes got worse; time comes before tokens' + RULE))

    def test_verify_says_how_many_sessions_it_skipped_for_a_model_with_no_factor(self):
        before, after = self.baseline_and_after(before_n=7, after_n=6)
        self.dispatch_fields(before, 400.0, unknown=(0,))
        self.dispatch_fields(after, 200.0, unknown=(0,))
        write_metrics_rows(self.home, before + after)
        self.experiment(metric=f'{PER_DISPATCH} anomaly:facts')
        code, out, err = self.cli('verify', '--signature', 'slow-check')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('(n=6) before', out)
        self.assertIn('(n=5) since', out)
        self.assertIn('- sessions skipped for a model with no factor: 2\n', out)
        self.dispatch_fields(before, 400.0)
        self.dispatch_fields(after, 200.0)
        write_metrics_rows(self.home, before + after)
        self.experiment(metric=f'{PER_DISPATCH} anomaly:facts')
        self.assertNotIn('no factor', self.cli('verify', '--signature', 'slow-check')[1])

    def test_tokens_cannot_be_kept_while_active_minutes_cannot_be_judged(self):
        self.baseline_and_after(before_weighted=2000, after_weighted=1000, before_active=10,
                                after_active=[10, 10, 10, None, None])
        self.experiment(metric='weighted tokens')
        found = self.judged()
        self.assertEqual(found.result, 'inconclusive')
        self.assertEqual(found.reason, 'active minutes cannot be judged yet: fewer than '
                                       f'{constants.VERDICT_MIN_SAMPLES} sessions on a side; time comes before tokens' + RULE)

    def test_quality_comes_before_time(self):
        _, after = self.baseline_and_after(before_weighted=2000, after_weighted=1000, before_active=10,
                                           after_active=20)
        self.redo(after[:3])
        self.experiment(metric='weighted tokens')
        found = self.judged()
        self.assertEqual(found.result, 'revert')
        self.assertIn('the guard rework sightings got worse', found.reason)

    def test_a_baseline_before_the_backlog_began_makes_a_sighting_guard_unknown(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.backlog_started('2026-09-01')
        self.experiment()
        found = self.judged()
        self.assertEqual(found.readings[1].before.value, None)
        self.assertEqual(found.result, 'inconclusive')
        self.assertIn('the backlog does not cover the 28 days before the fix', found.reason)

    def test_a_fix_without_a_date_or_an_unknown_metric_is_a_clear_error(self):
        self.experiment(fixed_by='abc1234')
        with self.assertRaises(records.RecordError) as caught:
            self.judged()
        self.assertIn('fixed_by', str(caught.exception))
        self.experiment(metric='minutes per build')
        with self.assertRaises(records.RecordError):
            self.judged()


class ReadingLineTest(VerdictCase):
    def line(self, found, index=0, role='primary'):
        return verdict.reading_line(found.readings[index], role)

    def test_a_real_change_shows_chance_alone_rounded_up_and_the_verdict_word(self):
        self.baseline_and_after(before_active=20, after_active=10)
        self.experiment()
        self.assertEqual(self.line(self.judged()), '- active minutes (primary): 20 (n=6) before, 10 (n=5) since, '
                                                   '-50%; 4% of random splits change this much → real change')

    def test_a_change_within_noise_is_inconclusive_and_its_line_says_so(self):
        self.baseline_and_after(before_active=[10, 20, 12, 18, 11, 19], after_active=[11, 19, 10, 20, 12])
        self.experiment()
        found = self.judged()
        self.assertEqual(found[:2], ('inconclusive', 'active minutes is within noise' + RULE))
        self.assertEqual(self.line(found), '- active minutes (primary): 15 (n=6) before, 12 (n=5) since, '
                                                   '-20%; 95% of random splits change this much → within noise')

    def test_too_few_sessions_show_the_values_and_sample_sizes_only(self):
        self.baseline_and_after(before_active=20, after_active=10, after_n=4)
        self.experiment()
        self.assertEqual(self.line(self.judged()), '- active minutes (primary): 20 (n=6) before, 10 (n=4) since')

    def test_from_a_zero_baseline_the_line_shows_from_0_with_chance_alone_and_the_verdict_word(self):
        _, after = self.baseline_and_after()
        self.redo(after)
        self.experiment(metric='rework sightings', guard='late-catch sightings')
        found = self.judged()
        self.assertEqual(found[:2], ('revert', 'rework sightings got worse' + RULE))
        self.assertEqual(self.line(found), '- rework sightings (primary): 0 (n=6) before, 1 (n=5) since, from 0; '
                                           '1% of random splits change this much → real change')
        self.redo(after[:1])
        found = self.judged()
        self.assertEqual(found.result, 'inconclusive')
        self.assertEqual(self.line(found), '- rework sightings (primary): 0 (n=6) before, 0.2 (n=5) since, from 0; '
                                           '46% of random splits change this much → within noise')

    def test_interrupts_are_read_as_a_mean_and_a_mean_below_1_has_two_decimals(self):
        before, after = self.baseline_and_after(before_n=20, after_n=20)
        after[0]['friction']['interrupts'] = 1
        write_metrics_rows(self.home, before + after)
        self.experiment(metric='interrupts')
        self.assertIn('- interrupts (primary): 0 (n=20) before, 0.05 (n=20) since, from 0; ', self.line(self.judged()))

    def test_zero_before_and_since_shows_no_change(self):
        self.baseline_and_after()
        self.experiment(metric='rework sightings', guard='late-catch sightings')
        found = self.judged()
        self.assertEqual(self.line(found), '- rework sightings (primary): 0 (n=6) before, 0 (n=5) since; '
                                           '100% of random splits change this much → within noise')
        self.assertEqual(self.line(found, 1, 'guard'), '- late-catch sightings (guard): 0 (n=6) before, 0 (n=5) since; '
                                                       '100% of random splits change this much → within noise')
        self.assertEqual(found.result, 'inconclusive')

    def test_sightings_from_no_session_of_the_window_count_in_the_rate_and_are_left_out_of_the_test(self):
        _, after = self.baseline_and_after()
        self.redo(after + [{'session_id': 'never-measured'}] * 2)
        self.experiment(metric='rework sightings', guard='late-catch sightings')
        line = self.line(self.judged())
        self.assertIn('0 (n=6) before, 1.4 (n=5) since, from 0; 1% of random splits change this much → real change',
                      line)
        self.assertIn('sightings left out of the test: 2', line)


if __name__ == '__main__':
    unittest.main()

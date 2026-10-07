import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from anomaly_loop import constants, ideas, records
from tests.fixtures import anomaly_text, write_anomaly_text, write_text


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'


def full_anomaly(**changes):
    values = dict(
        signature='slow-check', kind='problem', category='automated-checks', target='scripts/check.sh',
        scope='repo:demo', impact=2, occurrences=3, effort='M', status='reopened', first_seen='2026-09-01',
        last_seen='2026-10-02', fixed_by='abc1234',
        experiment=records.Experiment(expect='check under a minute', metric='active minutes per build',
                                      guard='rework sightings', check_by='2026-10-25', result=''),
        summary='The check runs every test twice.\n\nSecond paragraph.',
        proposed_fix='Run the fast suite first.',
        sightings=['2026-10-02 · demo · s3 · third', '2026-09-15 · demo · s2 · second',
                   '2026-09-01 · demo · s1 · first'])
    values.update(changes)
    return records.Anomaly(**values)


class PortedBacklogTest(HomeCase):
    def test_score_is_impact_times_occurrences_and_strips_comments(self):
        write_anomaly_text(self.home, 'a', 2, 3)
        [anomaly] = records.load_anomalies(self.home)
        self.assertEqual(anomaly.score, 6)
        self.assertEqual(anomaly.category, 'tool-economy')

    def test_ranking_by_score_then_newest_and_drops_closed(self):
        write_anomaly_text(self.home, 'low', 1, 1)
        write_anomaly_text(self.home, 'high-old', 3, 2, last_seen='2026-09-01')
        write_anomaly_text(self.home, 'high-new', 2, 3, last_seen='2026-10-02')
        write_anomaly_text(self.home, 'done', 3, 5, status='fixed')
        write_anomaly_text(self.home, 'back', 1, 2, status='reopened')
        order = [a.signature for a in records.ranked(records.load_anomalies(self.home))]
        self.assertEqual(order, ['high-new', 'high-old', 'back', 'low'])


class AnomalyFormatTest(HomeCase):
    def test_every_field_round_trips_including_the_experiment_block(self):
        anomaly = full_anomaly()
        path = records.write_anomaly(self.home, anomaly)
        self.assertEqual(path, self.home / 'anomalies' / 'slow-check.md')
        self.assertEqual(records.read_anomaly(path), anomaly)

    def test_file_layout_frontmatter_then_paragraph_fix_and_sightings_newest_first(self):
        text = records.write_anomaly(self.home, full_anomaly()).read_text(encoding='utf-8')
        head = text.split('\n---\n')[0].splitlines()
        keys = [line.split(':')[0] for line in head[1:] if not line.startswith(' ')]
        self.assertEqual(keys, ['signature', 'kind', 'category', 'target', 'scope', 'impact', 'occurrences',
                                'effort', 'status', 'first_seen', 'last_seen', 'fixed_by', 'experiment'])
        self.assertIn('experiment:\n  expect: check under a minute\n  metric: active minutes per build\n'
                      '  guard: rework sightings\n  check_by: 2026-10-25\n  result:\n---\n', text)
        self.assertLess(text.index('The check runs'), text.index('## Proposed fix'))
        self.assertLess(text.index('## Proposed fix'), text.index('## Sightings'))
        self.assertTrue(text.endswith('- 2026-10-02 · demo · s3 · third\n- 2026-09-15 · demo · s2 · second\n'
                                      '- 2026-09-01 · demo · s1 · first\n'))
        self.assertNotIn('\r', text)

    def test_score_is_never_written(self):
        text = records.write_anomaly(self.home, full_anomaly()).read_text(encoding='utf-8')
        self.assertNotIn('score', text)

    def test_without_experiment_the_key_is_absent_and_reads_back_as_none(self):
        path = records.write_anomaly(self.home, full_anomaly(experiment=None))
        self.assertNotIn('experiment', path.read_text(encoding='utf-8'))
        self.assertIsNone(records.read_anomaly(path).experiment)

    def test_a_win_has_no_proposed_fix_section(self):
        path = records.write_anomaly(self.home, full_anomaly(kind='win', proposed_fix='', status='open'))
        self.assertNotIn('## Proposed fix', path.read_text(encoding='utf-8'))

    def test_other_body_sections_are_kept(self):
        path = self.home / 'anomalies' / 'x.md'
        write_text(path, anomaly_text('x', 1, 1).replace('## Sightings', '## Notes\nKeep me.\n\n## Sightings'))
        records.write_anomaly(self.home, records.read_anomaly(path))
        self.assertIn('## Notes\nKeep me.\n', path.read_text(encoding='utf-8'))

    def test_signature_falls_back_to_the_file_name(self):
        path = self.home / 'anomalies' / 'from-name.md'
        write_text(path, anomaly_text('x', 1, 1).replace('signature: x\n', ''))
        self.assertEqual(records.read_anomaly(path).signature, 'from-name')


class ReadingTest(HomeCase):
    def path(self, name='x'):
        return self.home / 'anomalies' / f'{name}.md'

    def test_a_comment_alone_leaves_a_vocabulary_field_blank(self):
        write_text(self.path(), anomaly_text('x', 1, 1).replace('effort:', 'effort:   # S|M|L'))
        self.assertEqual(records.read_anomaly(self.path()).effort, '')

    def test_comments_are_dropped_from_experiment_result_and_check_by(self):
        text = anomaly_text('x', 1, 1).replace('fixed_by:\n', 'fixed_by:\nexperiment:\n  expect: faster # not a comment\n'
                                                '  check_by: 2026-10-25   # or 5 sessions\n  result: # keep|revert\n')
        write_text(self.path(), text)
        experiment = records.read_anomaly(self.path()).experiment
        self.assertEqual((experiment.check_by, experiment.result), ('2026-10-25', ''))
        self.assertEqual(experiment.expect, 'faster # not a comment')

    def test_a_bad_number_is_kept_so_validation_rejects_it(self):
        write_text(self.path(), anomaly_text('x', 1, 1).replace('impact: 1', 'impact: high'))
        anomaly = records.read_anomaly(self.path())
        self.assertEqual(anomaly.impact, 'high')
        self.assertEqual(anomaly.score, 0)
        self.assertEqual(records.ranked([anomaly]), [anomaly])
        self.assertTrue(any('impact' in problem for problem in records.validate_anomaly(anomaly)))

    def test_a_blank_number_still_defaults_to_one(self):
        write_text(self.path(), anomaly_text('x', 1, 1).replace('impact: 1', 'impact:'))
        self.assertEqual(records.read_anomaly(self.path()).impact, 1)

    def test_a_wrapped_sighting_line_is_joined_to_its_bullet(self):
        write_text(self.path(), anomaly_text('x', 1, 1, sightings=('2026-10-01 · a · s1 · first part',))
                   + '  and the rest\n- 2026-09-01 · a · s0 · older\n')
        anomaly = records.read_anomaly(self.path())
        self.assertEqual(anomaly.sightings, ['2026-10-01 · a · s1 · first part and the rest',
                                             '2026-09-01 · a · s0 · older'])
        records.write_anomaly(self.home, anomaly)
        self.assertEqual(records.read_anomaly(self.path()).sightings, anomaly.sightings)

    def test_a_byte_order_mark_is_ignored(self):
        self.path().parent.mkdir(parents=True)
        self.path().write_bytes(b'\xef\xbb\xbf' + anomaly_text('x', 2, 3).encode('utf-8'))
        anomaly = records.read_anomaly(self.path())
        self.assertEqual((anomaly.signature, anomaly.score), ('x', 6))

    def test_text_that_is_not_utf8_is_a_record_error_naming_the_file(self):
        self.path().parent.mkdir(parents=True)
        self.path().write_bytes(b'---\nsignature: x\ncategory: caf\xe9\n---\n')
        with self.assertRaises(records.RecordError) as raised:
            records.load_anomalies(self.home)
        self.assertIn('x.md', str(raised.exception))
        idea = self.home / 'ideas' / 'y.md'
        idea.parent.mkdir(parents=True)
        idea.write_bytes(b'\xff\xfe')
        with self.assertRaises(records.RecordError) as raised:
            ideas.load_ideas(self.home)
        self.assertIn('y.md', str(raised.exception))


class ValidationTest(HomeCase):
    def assert_rejected(self, word, **changes):
        with self.assertRaises(records.RecordError) as raised:
            records.write_anomaly(self.home, full_anomaly(**changes))
        self.assertIn(word, str(raised.exception))
        self.assertFalse((self.home / 'anomalies').exists())

    def test_the_thirteen_categories_are_accepted(self):
        self.assertEqual(len(constants.CATEGORIES), 13)
        for category in constants.CATEGORIES:
            self.assertEqual(records.validate_anomaly(full_anomaly(category=category)), [])

    def test_unknown_category_is_rejected(self):
        self.assert_rejected('category', category='misc')

    def test_kind_status_impact_and_effort_are_checked(self):
        self.assert_rejected('kind', kind='bug')
        self.assert_rejected('status', status='done')
        self.assert_rejected('impact', impact=4)
        self.assert_rejected('impact', impact=0)
        self.assert_rejected('effort', effort='XL')
        self.assert_rejected('occurrences', occurrences=0)

    def test_blank_effort_is_fine_until_calibrate_sets_it(self):
        self.assertEqual(records.validate_anomaly(full_anomaly(effort='')), [])

    def test_signature_must_be_a_slug(self):
        self.assert_rejected('signature', signature='../escape')
        self.assert_rejected('signature', signature='Has Space')

    def test_dates_and_experiment_result_are_checked(self):
        self.assert_rejected('last_seen', last_seen='yesterday')
        self.assert_rejected('result', experiment=records.Experiment(result='maybe'))
        for result in ('keep', 'revert', 'inconclusive', ''):
            self.assertEqual(records.validate_anomaly(full_anomaly(experiment=records.Experiment(result=result))), [])

    def test_a_value_spanning_lines_is_rejected(self):
        self.assert_rejected('target', target='a\nb')
        self.assert_rejected('scope', scope='a\rb')   # a lone carriage return breaks the line too


class SightingsTest(unittest.TestCase):
    def test_merge_dedupes_identical_lines_and_puts_newest_first(self):
        merged = records.merge_sightings(['2026-10-01 · a · s2 · x', '2026-09-01 · a · s1 · y'],
                                         ['2026-09-01 · a · s1 · y', '2026-09-20 · b · s3 · z', 'undated note'])
        self.assertEqual(merged, ['2026-10-01 · a · s2 · x', '2026-09-20 · b · s3 · z',
                                  '2026-09-01 · a · s1 · y', 'undated note'])


class IdeaTest(HomeCase):
    def idea(self, **changes):
        values = dict(slug='research-loop', source='a link to an article', assessed='2026-10-04', verdict='park',
                      revisit='2026-12-01', related=['slow-check', 'scripts/check.sh'],
                      scores_at_assessment={'slow-check': 3}, body='Worth a look once checks are fast.')
        values.update(changes)
        return ideas.Idea(**values)

    def test_round_trip_with_related_list_and_scores_at_assessment(self):
        idea = self.idea()
        path = ideas.write_idea(self.home, idea)
        self.assertEqual(path, self.home / 'ideas' / 'research-loop.md')
        self.assertEqual(ideas.read_idea(path), idea)
        self.assertEqual(ideas.load_ideas(self.home), [idea])
        text = path.read_text(encoding='utf-8')
        self.assertIn('related:\n  - slow-check\n  - scripts/check.sh\n', text)
        self.assertIn('scores_at_assessment:\n  slow-check: 3\n', text)

    def test_a_bad_score_is_kept_so_validation_rejects_it(self):
        path = ideas.write_idea(self.home, self.idea())
        path.write_text(path.read_text(encoding='utf-8').replace('slow-check: 3', 'slow-check: high'), encoding='utf-8')
        idea = ideas.read_idea(path)
        self.assertEqual(idea.scores_at_assessment, {'slow-check': 'high'})
        self.assertTrue(ideas.validate_idea(idea))

    def test_verdict_and_revisit_rules(self):
        self.assertEqual(ideas.validate_idea(self.idea(verdict='adopt', revisit='')), [])
        for changes, word in (({'verdict': 'maybe'}, 'verdict'), ({'revisit': ''}, 'revisit'),
                              ({'verdict': 'reject'}, 'revisit'), ({'assessed': 'today'}, 'assessed'),
                              ({'scores_at_assessment': {'other': 2}}, 'scores_at_assessment'),
                              ({'scores_at_assessment': {'slow-check': 'high'}}, 'whole numbers')):
            with self.assertRaises(records.RecordError) as raised:
                ideas.write_idea(self.home, self.idea(**changes))
            self.assertIn(word, str(raised.exception))


class LineFormatTest(HomeCase):
    def lines(self, name):
        return [json.loads(line) for line in (self.home / name).read_text(encoding='utf-8').splitlines()]

    def test_lens_line_has_the_five_fields_in_order(self):
        records.append_lens(self.home, records.lens_record('s1', '2026-10-04', 'spec-reviewer', 3, 1))
        records.append_lens(self.home, records.lens_record('s2', '2026-10-05', 'spec-reviewer', 0, 2))
        rows = self.lines('lenses.jsonl')
        self.assertEqual(list(rows[0]), ['session_id', 'date', 'lens', 'accepted', 'rejected'])
        self.assertEqual(records.load_lenses(self.home), rows)
        self.assertEqual(len(rows), 2)

    def test_lens_counts_must_be_non_negative_whole_numbers(self):
        for bad in ((-1, 0), (1, 'two')):
            with self.assertRaises(records.RecordError):
                records.lens_record('s1', '2026-10-04', 'x', *bad)
        with self.assertRaises(records.RecordError):
            records.lens_record('s1', '2026-10-04', '', 1, 1)

    def test_is_ticket_number_is_the_one_rule_for_a_two_digit_ticket_number(self):
        for good in ('00', '07', '14', '99'):
            self.assertTrue(records.is_ticket_number(good), good)
        for bad in ('7', '007', '', 'ab', '0x', '07\n', ' 07', '٠٧', 7, None):
            self.assertFalse(records.is_ticket_number(bad), bad)

    def test_is_count_is_the_one_rule_for_a_count_of_zero_or_more(self):
        for good in (0, 1, 250):
            self.assertTrue(records.is_count(good), good)
        for bad in (-1, 1.0, '2', True, None):
            self.assertFalse(records.is_count(bad), bad)

    def test_work_unit_line_has_the_four_fields_in_order_and_is_appended(self):
        path = records.append_work_unit(self.home, records.work_unit_record('feat-a', 'build', 's1', '2026-10-04'))
        self.assertEqual(path, self.home / 'work-units.jsonl')
        records.append_work_unit(self.home, records.work_unit_record('feat-a', 'review', 's1', '2026-10-05'))
        rows = self.lines('work-units.jsonl')
        self.assertEqual(list(rows[0]), ['feature', 'stage', 'session', 'date'])
        self.assertEqual([row['stage'] for row in rows], ['build', 'review'])

    def test_a_work_unit_line_needs_a_feature_a_stage_a_session_and_a_date(self):
        for bad in (('', 'build', 's1', '2026-10-04'), ('f', '', 's1', '2026-10-04'),
                    ('f', 'build', '', '2026-10-04'), ('f', 'build', 's1', 'yesterday')):
            with self.subTest(bad=bad), self.assertRaises(records.RecordError):
                records.work_unit_record(*bad)

    def test_session_kind_last_line_per_session_wins(self):
        records.append_session_kind(self.home, records.session_kind_record('s1', 'build', '2026-10-01'))
        records.append_session_kind(self.home, records.session_kind_record('s2', 'config', '2026-10-01'))
        records.append_session_kind(self.home, records.session_kind_record('s1', 'debug', '2026-10-03'))
        self.assertEqual(list(self.lines('session-kinds.jsonl')[0]), ['session_id', 'kind', 'set_on'])
        kinds = records.load_session_kinds(self.home)
        self.assertEqual({sid: row['kind'] for sid, row in kinds.items()}, {'s1': 'debug', 's2': 'config'})

    def test_session_kind_must_be_known(self):
        with self.assertRaises(records.RecordError):
            records.session_kind_record('s1', 'meeting', '2026-10-01')

    def test_a_line_file_that_is_not_utf8_is_a_record_error_naming_it(self):
        self.home.mkdir()
        (self.home / 'lenses.jsonl').write_bytes(b'{"session_id":"s1","lens":"r\xe9viewer"}\n')
        with self.assertRaises(records.RecordError) as raised:
            records.load_lenses(self.home)
        self.assertIn('lenses.jsonl', str(raised.exception))

    def test_missing_files_read_as_empty(self):
        self.assertEqual(records.load_lenses(self.home), [])
        self.assertEqual(records.load_session_kinds(self.home), {})
        self.assertEqual(records.load_anomalies(self.home), [])
        self.assertEqual(ideas.load_ideas(self.home), [])


class IsDueTest(unittest.TestCase):
    def due(self, today='2026-10-25', **experiment):
        values = dict(check_by='2026-10-25', result='')
        values.update(experiment)
        anomaly = full_anomaly(experiment=records.Experiment(**values))
        return records.is_due(anomaly, date.fromisoformat(today))

    def test_due_on_the_check_date_and_after_while_there_is_no_result(self):
        self.assertTrue(self.due('2026-10-25'))
        self.assertTrue(self.due('2026-12-01'))

    def test_not_due_while_the_fix_has_not_been_made(self):
        anomaly = full_anomaly(fixed_by='')
        self.assertFalse(records.is_due(anomaly, date(2026, 12, 1)))
        anomaly.fixed_by = '  '
        self.assertFalse(records.is_due(anomaly, date(2026, 12, 1)))

    def test_not_due_before_the_check_date(self):
        self.assertFalse(self.due('2026-10-24'))

    def test_not_due_once_it_has_a_result(self):
        for result in constants.EXPERIMENT_RESULTS:
            self.assertFalse(self.due('2026-12-01', result=result))

    def test_not_due_without_an_experiment_or_without_a_usable_date(self):
        self.assertFalse(records.is_due(full_anomaly(experiment=None), date(2026, 12, 1)))
        for check_by in ('', 'soon', '2026-13-40'):
            self.assertFalse(self.due('2026-12-01', check_by=check_by))


class FixDateTest(unittest.TestCase):
    def fix_date(self, fixed_by):
        return records.fix_date(full_anomaly(fixed_by=fixed_by))

    def test_a_date_first_value_gives_its_date(self):
        self.assertEqual(self.fix_date('2026-10-04 · abc1234'), date(2026, 10, 4))
        self.assertEqual(self.fix_date('2026-10-04 · skills/check/SKILL.md'), date(2026, 10, 4))

    def test_a_bare_date_is_a_date(self):
        self.assertEqual(self.fix_date('2026-09-10'), date(2026, 9, 10))

    def test_old_blank_or_broken_values_have_no_date(self):
        for value in ('', '  ', 'abc1234', 'a change', '2026-13-40 · x', '20261004', '2026-10-04x',
                      'fixed 2026-10-04'):
            self.assertIsNone(self.fix_date(value), value)

    def test_the_writer_puts_the_date_first_and_the_reader_gets_it_back(self):
        text = records.fixed_by_text(date(2026, 10, 4), 'abc1234')
        self.assertEqual(text, '2026-10-04 · abc1234')
        self.assertEqual(self.fix_date(text), date(2026, 10, 4))

    def test_the_writer_needs_a_reference(self):
        with self.assertRaises(records.RecordError):
            records.fixed_by_text(date(2026, 10, 4), '  ')

    def test_an_old_record_with_a_reference_only_stays_valid(self):
        self.assertEqual(records.validate_anomaly(full_anomaly(fixed_by='abc1234')), [])


class ExperimentKindTest(HomeCase):
    def experiment(self, **changes):
        values = dict(expect='faster', metric='active minutes', guard='rework sightings', check_by='2026-10-25')
        values.update(changes)
        return records.Experiment(**values)

    def test_a_kind_round_trips_and_is_written_after_the_guard(self):
        anomaly = full_anomaly(experiment=self.experiment(kind='build', skill='demo:build', declared_on='2026-10-04'))
        path = records.write_anomaly(self.home, anomaly)
        self.assertIn('  guard: rework sightings\n  kind: build\n  skill: demo:build\n  declared_on: 2026-10-04\n'
                      '  check_by: 2026-10-25\n', path.read_text(encoding='utf-8'))
        self.assertEqual(records.read_anomaly(path), anomaly)

    def test_a_blank_kind_writes_no_line_so_old_files_keep_their_shape(self):
        path = records.write_anomaly(self.home, full_anomaly(experiment=self.experiment()))
        self.assertNotIn('  kind:', path.read_text(encoding='utf-8'))
        self.assertEqual(records.read_anomaly(path).experiment.kind, '')

    def test_an_old_file_without_a_kind_reads_with_a_blank_kind(self):
        text = anomaly_text('x', 1, 1).replace('fixed_by:\n', 'fixed_by:\nexperiment:\n  expect: faster\n'
                                                '  metric: interrupts\n  guard: rework sightings\n')
        write_text(self.home / 'anomalies' / 'x.md', text)
        [anomaly] = records.load_anomalies(self.home, strict=True)
        self.assertEqual(anomaly.experiment.kind, '')

    def test_the_kind_must_be_a_session_kind_and_a_comment_is_dropped(self):
        problems = records.validate_anomaly(full_anomaly(experiment=self.experiment(kind='weekly')))
        self.assertTrue(any('kind' in problem for problem in problems))
        for kind in constants.SESSION_KINDS:
            self.assertEqual(records.validate_anomaly(full_anomaly(experiment=self.experiment(kind=kind))), [])
        problems = records.validate_anomaly(full_anomaly(experiment=self.experiment(kind='debug', skill='demo:build')))
        self.assertTrue(any('skill' in problem and 'kind build' in problem for problem in problems))
        text = anomaly_text('x', 1, 1).replace('fixed_by:\n', 'fixed_by:\nexperiment:\n  kind: debug  # or build\n')
        write_text(self.home / 'anomalies' / 'x.md', text)
        self.assertEqual(records.read_anomaly(self.home / 'anomalies' / 'x.md').experiment.kind, 'debug')


class DeclaredOnAndReasonTest(HomeCase):
    def test_both_round_trip_and_are_written_only_when_set(self):
        experiment = records.Experiment(expect='faster', metric='interrupts', guard='rework sightings',
                                        declared_on='2026-10-04', check_by='2026-10-25', result='revert',
                                        reason='interrupts got worse')
        path = records.write_anomaly(self.home, full_anomaly(experiment=experiment))
        text = path.read_text(encoding='utf-8')
        self.assertIn('  guard: rework sightings\n  declared_on: 2026-10-04\n  check_by: 2026-10-25\n'
                      '  result: revert\n  reason: interrupts got worse\n', text)
        self.assertEqual(records.read_anomaly(path).experiment, experiment)
        bare = records.write_anomaly(self.home, full_anomaly(signature='bare', experiment=records.Experiment(
            expect='x', metric='interrupts')))
        self.assertNotIn('declared_on', bare.read_text(encoding='utf-8'))
        self.assertNotIn('reason', bare.read_text(encoding='utf-8'))

    def test_declared_on_must_be_a_date(self):
        problems = records.validate_anomaly(full_anomaly(experiment=records.Experiment(declared_on='today')))
        self.assertTrue(any('declared_on' in problem for problem in problems))

    def test_check_by_must_be_blank_or_a_date(self):
        for check_by in ('soon', '2026-13-40'):
            problems = records.validate_anomaly(full_anomaly(experiment=records.Experiment(check_by=check_by)))
            self.assertTrue(any('check_by' in problem for problem in problems), check_by)
        for check_by in ('', '2026-10-25'):
            self.assertEqual(records.validate_anomaly(full_anomaly(experiment=records.Experiment(check_by=check_by))),
                             [], check_by)


class EarlierExperimentsTest(HomeCase):
    def test_archiving_moves_the_experiment_into_a_line_and_clears_the_fix(self):
        anomaly = full_anomaly(fixed_by='2026-09-10 · abc1234', experiment=records.Experiment(
            expect='faster checks', metric='active minutes', guard='rework sightings', check_by='2026-10-01',
            result='revert', reason='the guard got worse'))
        records.archive_experiment(anomaly)
        self.assertIsNone(anomaly.experiment)
        self.assertEqual(anomaly.fixed_by, '')
        self.assertEqual(records.earlier_experiments(anomaly), [
            ('revert', 'revert · fixed 2026-09-10 · abc1234 · metric active minutes · guard rework sightings · '
                       'expect faster checks · reason the guard got worse')])
        switch_over = full_anomaly(experiment=records.Experiment(expect='x', metric='interrupts', kind='build',
                                                                 skill='demo:build'))
        records.archive_experiment(switch_over)
        self.assertIn(' · expect x · skill demo:build', records.earlier_experiments(switch_over)[0][1])

    def test_archived_lines_survive_a_write_and_stack_newest_first(self):
        anomaly = full_anomaly(fixed_by='2026-09-10 · abc1234', experiment=records.Experiment(
            expect='a', metric='interrupts', guard='rework sightings', result='revert'))
        records.archive_experiment(anomaly)
        anomaly.fixed_by = 'abc9999'
        anomaly.experiment = records.Experiment(expect='b', metric='denials', guard='rework sightings',
                                                result='keep')
        records.archive_experiment(anomaly)
        path = records.write_anomaly(self.home, anomaly)
        text = path.read_text(encoding='utf-8')
        again = records.read_anomaly(path)
        self.assertEqual([result for result, _ in records.earlier_experiments(again)], ['keep', 'revert'])
        self.assertIn('keep · fixed abc9999 · metric denials', records.earlier_experiments(again)[0][1])
        self.assertLess(text.index('## Earlier experiments'), text.index('## Sightings'))
        self.assertEqual(again, anomaly)

    def test_an_experiment_without_a_result_is_archived_as_not_checked(self):
        anomaly = full_anomaly(fixed_by='', experiment=records.Experiment(expect='a', metric='interrupts'))
        records.archive_experiment(anomaly)
        self.assertEqual(records.earlier_experiments(anomaly)[0], ('not checked', 'not checked · not fixed · '
                                                                   'metric interrupts · guard  · expect a'))

    def test_a_record_without_earlier_experiments_has_none(self):
        self.assertEqual(records.earlier_experiments(full_anomaly()), [])


class MergeAnomaliesTest(unittest.TestCase):
    def kept(self, **changes):
        values = dict(occurrences=2, impact=1, status='open', first_seen='2026-09-15', last_seen='2026-10-01',
                      effort='', sightings=['2026-10-01 · demo · s2 · two', '2026-09-15 · demo · s1 · one'])
        values.update(changes)
        return full_anomaly(**values)

    def folded(self, **changes):
        values = dict(signature='other', occurrences=3, impact=3, status='open', first_seen='2026-09-01',
                      last_seen='2026-10-02', effort='S', sightings=['2026-10-02 · demo · s3 · three'])
        values.update(changes)
        return full_anomaly(**values)

    def test_a_first_merge_adds_the_folded_count_whole_and_combines_everything(self):
        merged = records.merge_anomalies(self.kept(), self.folded())
        self.assertEqual((merged.occurrences, merged.impact, merged.first_seen, merged.last_seen),
                         (5, 3, '2026-09-01', '2026-10-02'))
        self.assertEqual(merged.sightings, ['2026-10-02 · demo · s3 · three', '2026-10-01 · demo · s2 · two',
                                            '2026-09-15 · demo · s1 · one'])
        self.assertEqual((merged.signature, merged.status), ('slow-check', 'open'))

    def test_once_a_sighting_is_shared_only_the_new_lines_count(self):
        folded = self.folded(occurrences=9, sightings=['2026-10-02 · demo · s3 · three',
                                                       '2026-10-01 · demo · s2 · two'])
        self.assertEqual(records.merge_anomalies(self.kept(), folded).occurrences, 3)

    def test_nothing_new_gives_none(self):
        folded = self.folded(sightings=['2026-10-01 · demo · s2 · two'])
        self.assertIsNone(records.merge_anomalies(self.kept(), folded))

    def test_a_fixed_record_reopens_and_blank_fields_are_filled_from_the_folded_one(self):
        merged = records.merge_anomalies(self.kept(status='fixed', target='', scope=''),
                                         self.folded(target='scripts/other.sh', scope='repo:other'))
        self.assertEqual((merged.status, merged.target, merged.scope, merged.effort),
                         ('reopened', 'scripts/other.sh', 'repo:other', 'S'))


class SightingDayTest(unittest.TestCase):
    def test_the_sighting_line_and_its_session_round_trip(self):
        line = records.sighting_line('2026-10-04', 'demo', 's1', 'something happened')
        self.assertEqual(line, '2026-10-04 · demo · s1 · something happened')
        self.assertEqual(records.sighting_session(line), 's1')
        self.assertEqual(records.sighting_day(line), date(2026, 10, 4))
        self.assertIsNone(records.sighting_session('2026-09-20 · an older line'))
        self.assertIsNone(records.sighting_session('2026-09-20 · repo · text'))

    def test_the_leading_date_of_a_sighting_line(self):
        self.assertEqual(records.sighting_day('2026-10-04 · demo · s1 · x'), date(2026, 10, 4))
        self.assertEqual(records.sighting_day('2026-09-20 · an older line'), date(2026, 9, 20))
        for line in ('no date here', '2026-13-01 · bad', '', 'seen 2026-10-04'):
            self.assertIsNone(records.sighting_day(line), line)

    def test_merging_sightings_sorts_by_that_day(self):
        self.assertEqual(records.merge_sightings(['2026-09-01 · a', 'no date'], ['2026-10-01 · b', '2026-09-01 · a']),
                         ['2026-10-01 · b', '2026-09-01 · a', 'no date'])

    def test_the_dash_list_reader_joins_wrapped_lines(self):
        self.assertEqual(records.parse_dash_list('- one\n  more\n- two\n'), ['one more', 'two'])


if __name__ == '__main__':
    unittest.main()

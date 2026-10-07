import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from datetime import date

from anomaly_loop import assess, cli, constants, digest, ideas, records
from tests.fixtures import (GitFixture, NOW, anomaly_text, context, run_cli, write_anomaly_text, write_idea_file,
                            write_text)

FULL_PROFILE = '\n'.join(['---', 'tracker: local files', 'glossary_file: CONTEXT.md', 'ticket_key: [A-Z]+-\\d+',
                          'branch_pattern: <type>/<slug>', 'commit_style: <type>: <summary>',
                          'implementers:', '  web: some-agent', 'mr_tool: some-tool', 'verify_ui: some-tool',
                          'issue_source: local, read-only', '---', ''])
EXPERIMENT = ['--expect', 'checks finish sooner', '--metric', 'active minutes',
              '--guard', 'rework sightings', '--check-by', '2026-10-25']


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'

    def run_assess(self, action, *argv, stdin=None):
        stream = mock.MagicMock(buffer=io.BytesIO(stdin.encode('utf-8'))) if stdin is not None else None
        with mock.patch('sys.stdin', stream):
            return run_cli('assess', action, '--home', str(self.home), *argv)

    def idea_text(self, slug):
        return (self.home / 'ideas' / f'{slug}.md').read_text(encoding='utf-8')


class NormalisationTest(unittest.TestCase):
    def test_links_that_differ_only_in_noise_have_one_key(self):
        same = ['https://example.com/a/b', 'HTTP://www.Example.com/a/b/', 'https://example.com/a/b?utm_source=x#top',
                'example.com/a/b', 'https://person@example.com:443/a//b/']
        self.assertEqual({assess.source_key(raw) for raw in same}, {'https://example.com/a/b'})

    def test_different_paths_hosts_and_ports_are_different_keys(self):
        keys = {assess.source_key(raw) for raw in ('https://example.com/a', 'https://example.com/b',
                                                   'https://other.example.com/a', 'https://example.com:8080/a')}
        self.assertEqual(len(keys), 4)

    def test_the_stored_key_never_holds_a_query_a_plain_fragment_or_a_user_name(self):
        key = assess.source_key('https://person@example.com/a?k=abc&x=1#frag')
        self.assertRegex(key, r'^https://example\.com/a#q=[0-9a-f]{8}$')
        for leaked in ('?', 'abc', 'person', 'frag', 'x=1'):
            self.assertNotIn(leaked, key)

    def test_tracking_parameters_do_not_make_a_different_page(self):
        plain = assess.source_key('https://example.com/a')
        noisy = 'https://example.com/a?utm_source=x&UTM_medium=y&fbclid=1&gclid=2&ref=feed'
        self.assertEqual(assess.source_key(noisy), plain)

    def test_pages_that_differ_in_their_query_have_different_keys_in_any_parameter_order(self):
        self.assertNotEqual(assess.source_key('https://www.youtube.com/watch?v=AAA'),
                            assess.source_key('https://www.youtube.com/watch?v=BBB'))
        self.assertNotEqual(assess.source_key('https://news.example.com/item?id=1'),
                            assess.source_key('https://news.example.com/item?id=2'))
        self.assertEqual(assess.source_key('https://example.com/s?a=1&b=2&utm_x=3'),
                         assess.source_key('https://example.com/s?b=2&a=1'))
        self.assertNotEqual(assess.source_key('https://example.com/s?a=1'), assess.source_key('https://example.com/s'))
        self.assertNotIn('AAA', assess.source_key('https://www.youtube.com/watch?v=AAA'))

    def test_a_routing_fragment_is_part_of_the_page_but_a_plain_anchor_is_not(self):
        self.assertNotEqual(assess.source_key('https://example.com/app#/page-a'),
                            assess.source_key('https://example.com/app#/page-b'))
        self.assertNotEqual(assess.source_key('https://example.com/app#!a'), assess.source_key('https://example.com/app#!b'))
        self.assertEqual(assess.source_key('https://example.com/app#section-2'), 'https://example.com/app')
        self.assertNotIn('page-a', assess.source_key('https://example.com/app#/page-a'))

    def test_a_stored_link_key_maps_to_itself(self):
        for raw in ('https://example.com/watch?v=AAA', 'https://example.com/app#/page-a',
                    'https://example.com/app?q=1#/page-a', 'https://example.com/plain'):
            key = assess.source_key(raw)
            self.assertEqual(assess.source_key(key), key, raw)

    def test_a_bare_host_with_a_dot_is_a_link(self):
        self.assertEqual(assess.source_key('Example.com'), 'https://example.com')
        self.assertEqual(assess.source_key('www.example.com'), 'https://example.com')

    def test_texts_are_compared_by_words_not_by_case_spacing_or_punctuation(self):
        one = assess.source_key('I think reviews are too slow!')
        two = assess.source_key('  i THINK   reviews are, too slow ')
        self.assertEqual(one, two)
        self.assertRegex(one, r'^text:[0-9a-f]{12}$')
        self.assertNotEqual(one, assess.source_key('I think reviews are too fast'))

    def test_a_stored_text_key_is_kept_as_it_is(self):
        key = assess.source_key('some opinion')
        self.assertEqual(assess.source_key(key), key)

    def test_an_empty_input_is_an_error(self):
        for raw in ('', '   ', '!!!'):
            with self.assertRaises(records.RecordError):
                assess.source_key(raw)


class CheckTest(HomeCase):
    def test_a_new_input_prints_its_key_and_the_open_anomalies_by_score(self):
        write_anomaly_text(self.home, 'low', 1, 1)
        write_anomaly_text(self.home, 'high', 3, 2, last_seen='2026-10-02')
        write_anomaly_text(self.home, 'done', 3, 9, status='fixed')
        code, out, err = self.run_assess('check', '--source', 'https://example.com/post?utm_x=1')
        self.assertEqual((code, err), (0, ''))
        lines = out.splitlines()
        self.assertEqual(lines[1], 'assess: new')
        self.assertIn('key: https://example.com/post', lines)
        listed = [line for line in lines if line.startswith('- ')]
        self.assertEqual([line.split()[2] for line in listed], ['high', 'low'])
        self.assertTrue(listed[0].startswith('- 6 '))
        self.assertNotIn('done', out)

    def test_an_input_assessed_before_shows_the_earlier_record_and_no_anomaly_list(self):
        write_anomaly_text(self.home, 'high', 3, 2)
        write_idea_file(self.home, 'post-idea', source='https://example.com/post', assessed='2026-09-01',
                        verdict='park', revisit='2026-12-01', body='A plain summary of the idea.')
        code, out, _ = self.run_assess('check', '--source', 'HTTPS://www.example.com/post/?utm_a=b#x')
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[1], 'assess: seen before')
        for expected in ('idea: post-idea', 'verdict: park', 'assessed: 2026-09-01', 'revisit: 2026-12-01',
                         'A plain summary of the idea.', str(self.home / 'ideas' / 'post-idea.md')):
            self.assertIn(expected, out)
        self.assertNotIn('high', out)

    def test_a_text_assessed_before_is_recognised_too(self):
        key = assess.source_key('Reviews are too slow')
        write_idea_file(self.home, 'slow-reviews', source=key, verdict='reject', revisit='', body='Not now.')
        _, out, _ = self.run_assess('check', '--source', 'reviews are TOO slow.')
        self.assertIn('assess: seen before', out)
        self.assertIn('idea: slow-reviews', out)

    def test_a_missing_profile_is_named_once_on_the_first_line(self):
        _, out, _ = self.run_assess('check', '--source', 'an opinion')
        self.assertEqual(sum(line.startswith('profile: ') for line in out.splitlines()), 1)
        self.assertTrue(out.splitlines()[0].startswith('profile: '), out)
        self.assertIn('missing keys: tracker', out)

    def test_a_complete_profile_prints_no_profile_line(self):
        write_text(self.home / 'profile.md', FULL_PROFILE)
        _, out, _ = self.run_assess('check', '--source', 'an opinion')
        self.assertNotIn('profile:', out)

    def test_an_empty_input_is_reported_as_an_anomaly_error(self):
        code, out, err = self.run_assess('check', '--source', '  ')
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: '))


class RecordIdeaTest(HomeCase):
    def record(self, *argv, **kwargs):
        base = ['--slug', 'skill-stack', '--source', 'https://example.com/stack?utm_x=1', '--body', 'My summary.']
        return self.run_assess('record', *(argv or base), **kwargs)

    def test_a_parked_idea_is_written_with_related_scores_and_a_normalised_source(self):
        write_anomaly_text(self.home, 'slow-check', 2, 2)
        code, out, err = self.record('--slug', 'skill-stack', '--source', 'https://example.com/stack?utm_x=1',
                                     '--verdict', 'park', '--revisit', '2026-12-01',
                                     '--related', 'slow-check', '--related', 'scripts/check.sh',
                                     '--body', 'My summary.')
        self.assertEqual((code, err), (0, ''))
        self.assertIn(str(self.home / 'ideas' / 'skill-stack.md'), out)
        idea = ideas.load_ideas(self.home)[0]
        self.assertEqual((idea.slug, idea.source, idea.assessed, idea.verdict, idea.revisit),
                         ('skill-stack', 'https://example.com/stack', '2026-10-04', 'park', '2026-12-01'))
        self.assertEqual(idea.related, ['slow-check', 'scripts/check.sh'])
        self.assertEqual(idea.scores_at_assessment, {'slow-check': 4})
        self.assertEqual(idea.body, 'My summary.')
        self.assertNotIn('utm_x', self.idea_text('skill-stack'))

    def test_the_body_can_come_from_standard_input_as_utf8(self):
        code, _, err = self.record('--slug', 'from-input', '--source', 'an opinion', '--verdict', 'reject',
                                   '--body', '-', stdin='Too heavy — not now.\nSecond line.\n')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(ideas.load_ideas(self.home)[0].body, 'Too heavy — not now.\nSecond line.')

    def test_an_input_that_is_a_text_is_stored_as_its_key(self):
        self.record('--slug', 'opinion', '--source', 'I think reviews are too slow', '--verdict', 'trial',
                    '--body', 'Needs a small benchmark.')
        self.assertEqual(ideas.load_ideas(self.home)[0].source, assess.source_key('I think reviews are too slow'))

    def test_a_bad_verdict_or_a_park_without_a_date_writes_nothing(self):
        for extra in (['--verdict', 'maybe'], ['--verdict', 'park'], ['--verdict', 'reject', '--revisit', '2026-12-01']):
            code, out, err = self.record('--slug', 'x', '--source', 'an opinion', *extra, '--body', 'b')
            self.assertEqual((code, out), (2, ''), extra)
            self.assertTrue(err.startswith('anomaly: '))
        self.assertFalse((self.home / 'ideas').exists())

    def test_an_empty_body_is_refused(self):
        code, _, err = self.record('--slug', 'x', '--source', 'an opinion', '--verdict', 'reject', '--body', ' ')
        self.assertEqual(code, 2)
        self.assertIn('body', err)

    def test_a_source_assessed_before_under_another_slug_is_refused_and_names_the_earlier_one(self):
        write_idea_file(self.home, 'earlier', source='https://example.com/stack')
        code, _, err = self.record('--slug', 'second', '--source', 'https://www.example.com/stack/',
                                   '--verdict', 'reject', '--body', 'b')
        self.assertEqual(code, 2)
        self.assertIn('earlier', err)
        self.assertNotIn('--replace', err)
        self.assertEqual([i.slug for i in ideas.load_ideas(self.home)], ['earlier'])

    def test_an_existing_slug_needs_replace_and_replace_overwrites_it(self):
        write_idea_file(self.home, 'earlier', source='https://example.com/stack', verdict='park')
        args = ('--slug', 'earlier', '--source', 'https://example.com/stack', '--verdict', 'reject', '--body', 'No.')
        code, _, err = self.record(*args)
        self.assertEqual(code, 2)
        self.assertIn('--replace', err)
        self.assertEqual(ideas.load_ideas(self.home)[0].verdict, 'park')
        code, _, _ = self.record(*args, '--replace')
        self.assertEqual(code, 0)
        idea = ideas.load_ideas(self.home)[0]
        self.assertEqual((idea.verdict, idea.revisit), ('reject', ''))

    def test_two_quotes_or_a_long_quote_are_refused(self):
        long_quote = '"' + ' '.join(['word'] * 20) + '"'
        for body in ('He wrote "keep each change small and measured" and also "never run unattended at night".',
                     f'Quoted: {long_quote}'):
            code, _, err = self.record('--slug', 'q', '--source', 'an opinion', '--verdict', 'reject', '--body', body)
            self.assertEqual(code, 2, body)
            self.assertIn('quote', err)

    def test_one_short_quote_is_allowed_and_a_quoted_term_is_not_a_quote(self):
        body = 'The author says "keep each change small" and calls it a "loop" and a "guard".'
        code, _, err = self.record('--slug', 'q', '--source', 'an opinion', '--verdict', 'reject', '--body', body)
        self.assertEqual((code, err), (0, ''))


class FileOptionsTest(HomeCase):
    TEXT = 'I think the team\'s reviews are too slow; it\'s $5 of time "each" run.\nSecond line.'

    def file(self, name, text, raw=None):
        path = Path(self.tmp.name) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw if raw is not None else text.encode('utf-8'))
        return str(path)

    def test_a_text_can_be_given_as_a_file_and_is_keyed_like_the_same_text_on_the_command_line(self):
        source = self.file('source.txt', self.TEXT)
        body = self.file('body.txt', 'It\'s a plain note — not now.\n')
        code, _, err = self.run_assess('record', '--slug', 'from-files', '--source-file', source,
                                       '--body-file', body, '--verdict', 'reject')
        self.assertEqual((code, err), (0, ''))
        idea = ideas.load_ideas(self.home)[0]
        self.assertEqual(idea.source, assess.source_key(self.TEXT))
        self.assertEqual(idea.body, 'It\'s a plain note — not now.')
        _, out, _ = self.run_assess('check', '--source-file', source)
        self.assertIn('assess: seen before', out)
        self.assertIn('idea: from-files', out)

    def test_a_file_with_a_link_is_keyed_as_a_link(self):
        _, out, _ = self.run_assess('check', '--source-file', self.file('s.txt', 'https://example.com/a?utm_x=1\n'))
        self.assertIn('key: https://example.com/a', out)

    def test_a_missing_or_non_utf8_file_is_an_anomaly_error(self):
        for argv in (['--source-file', str(Path(self.tmp.name) / 'none.txt')],
                     ['--source-file', self.file('bad.txt', '', raw=b'\xff\xfe\x00bad')]):
            code, out, err = self.run_assess('check', *argv)
            self.assertEqual((code, out), (2, ''), argv)
            self.assertTrue(err.startswith('anomaly: '))

    def test_a_source_or_body_is_given_once_not_twice(self):
        path = self.file('s.txt', 'text')
        for argv in (['check', '--source', 'a', '--source-file', path],
                     ['record', '--slug', 'x', '--source', 'a', '--verdict', 'reject', '--body', 'b',
                      '--body-file', path]):
            code, out, err = self.run_assess(*argv)
            self.assertEqual((code, out), (2, ''), argv)
            self.assertIn('not allowed with argument', err)


class AdoptTest(HomeCase):
    ADOPT = ['--slug', 'faster-checks', '--source', 'https://example.com/post', '--verdict', 'adopt',
             '--body', 'Worth a try.']
    NEW = ['--signature', 'checks-too-slow', '--category', 'automated-checks', '--target', 'scripts/check.sh',
           '--summary', 'The check run takes long.', '--fix', 'Run the fast suite first.']

    def adopt(self, *argv):
        return self.run_assess('record', *self.ADOPT, *argv)

    def test_adopt_writes_a_new_anomaly_with_a_drafted_experiment_and_links_it_from_the_idea(self):
        write_anomaly_text(self.home, 'other', 2, 2)
        before = (self.home / 'anomalies' / 'other.md').read_bytes()
        code, out, err = self.adopt(*self.NEW, '--impact', '2', *EXPERIMENT)
        self.assertEqual((code, err), (0, ''))
        self.assertIn(f'anomaly file: {self.home / "anomalies" / "checks-too-slow.md"}', out)
        self.assertNotIn('anomaly:', out)
        anomaly = records.read_anomaly(self.home / 'anomalies' / 'checks-too-slow.md')
        self.assertEqual((anomaly.kind, anomaly.category, anomaly.target, anomaly.scope, anomaly.impact),
                         ('problem', 'automated-checks', 'scripts/check.sh', 'global', 2))
        self.assertEqual((anomaly.occurrences, anomaly.status, anomaly.first_seen, anomaly.last_seen, anomaly.effort),
                         (1, 'open', '2026-10-04', '2026-10-04', ''))
        self.assertEqual((anomaly.summary, anomaly.proposed_fix),
                         ('The check run takes long.', 'Run the fast suite first.'))
        self.assertEqual(anomaly.experiment, records.Experiment(
            expect='checks finish sooner', metric='active minutes', guard='rework sightings',
            check_by='2026-10-25', result=''))
        self.assertEqual(len(anomaly.sightings), 1)
        self.assertTrue(anomaly.sightings[0].startswith('2026-10-04 · '))
        self.assertIn('faster-checks', anomaly.sightings[0])
        idea = ideas.load_ideas(self.home)[0]
        self.assertEqual((idea.verdict, idea.related, idea.scores_at_assessment),
                         ('adopt', ['checks-too-slow'], {'checks-too-slow': 2}))
        self.assertEqual((self.home / 'anomalies' / 'other.md').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in (self.home / 'anomalies').iterdir()),
                         ['checks-too-slow.md', 'other.md'])
        index_text = (self.home / 'INDEX.md').read_text(encoding='utf-8')
        self.assertIn('[checks-too-slow](anomalies/checks-too-slow.md)', index_text)

    def test_the_draft_has_no_check_date_and_is_never_due_until_the_fix_is_made(self):
        args = [a for a in EXPERIMENT if a not in ('--check-by', '2026-10-25')]
        self.assertEqual(self.adopt(*self.NEW, *args)[0], 0)
        anomaly = records.read_anomaly(self.home / 'anomalies' / 'checks-too-slow.md')
        self.assertEqual(anomaly.experiment.check_by, '')
        self.assertFalse(records.is_due(anomaly, date(2030, 1, 1)))

    def test_a_given_check_date_must_be_a_date(self):
        code, _, err = self.adopt(*self.NEW, *EXPERIMENT[:-1], 'soon')
        self.assertEqual(code, 2)
        self.assertIn('check_by', err)
        self.assertFalse((self.home / 'ideas').exists())

    def test_the_metric_and_guard_must_be_names_calibrate_accepts(self):
        experiment = ['--expect', 'checks finish sooner', '--check-by', '2026-10-25']
        for metric, guard, words in (('active minutes per build session', 'rework sightings', 'unknown metric'),
                                     ('active minutes', 'weighted tokens', 'quality'),
                                     ('interrupts', 'interrupts', 'differ'),
                                     ('active minutes', 'rework', 'unknown metric')):
            code, _, err = self.adopt(*self.NEW, *experiment, '--metric', metric, '--guard', guard)
            self.assertEqual(code, 2, (metric, guard))
            self.assertIn(words, err, (metric, guard))
        self.assertFalse((self.home / 'ideas').exists())
        self.assertFalse((self.home / 'anomalies').exists())

    def test_the_metric_and_guard_are_stored_by_their_registered_name(self):
        code, _, err = self.adopt(*self.NEW, '--expect', 'faster', '--metric', ' Active  Minutes ',
                                  '--guard', 'Rework Sightings')
        self.assertEqual((code, err), (0, ''))
        experiment = records.read_anomaly(self.home / 'anomalies' / 'checks-too-slow.md').experiment
        self.assertEqual((experiment.metric, experiment.guard), ('active minutes', 'rework sightings'))

    def test_an_impact_of_zero_is_refused_not_turned_into_one(self):
        code, _, err = self.adopt(*self.NEW, '--impact', '0', *EXPERIMENT)
        self.assertEqual(code, 2)
        self.assertIn('impact', err)
        self.assertFalse((self.home / 'anomalies').exists())

    def test_an_incomplete_experiment_or_missing_signature_writes_nothing(self):
        cases = [self.NEW + ['--expect', 'x', '--metric', 'm'],
                 self.NEW + ['--expect', 'x', '--guard', 'g'],
                 self.NEW + ['--metric', 'm', '--guard', 'g'],
                 ['--expect', 'x', '--metric', 'm', '--guard', 'g'],
                 self.NEW + ['--expect', ' ', '--metric', 'm', '--guard', 'g']]
        for argv in cases:
            code, out, err = self.adopt(*argv)
            self.assertEqual((code, out), (2, ''), argv)
            self.assertTrue(err.startswith('anomaly: '))
        self.assertFalse((self.home / 'ideas').exists())
        self.assertFalse((self.home / 'anomalies').exists())

    def test_an_invalid_new_anomaly_writes_neither_file(self):
        bad = [a if a != 'automated-checks' else 'misc' for a in self.NEW]
        code, _, err = self.adopt(*bad, *EXPERIMENT)
        self.assertEqual(code, 2)
        self.assertIn('category', err)
        self.assertFalse((self.home / 'ideas').exists())
        self.assertFalse((self.home / 'anomalies').exists())

    def test_a_new_anomaly_never_replaces_one_with_the_same_signature_when_it_describes_one(self):
        write_anomaly_text(self.home, 'checks-too-slow', 2, 3)
        before = (self.home / 'anomalies' / 'checks-too-slow.md').read_bytes()
        code, _, err = self.adopt(*self.NEW, *EXPERIMENT)
        self.assertEqual(code, 2)
        self.assertIn('already exists', err)
        self.assertEqual((self.home / 'anomalies' / 'checks-too-slow.md').read_bytes(), before)
        self.assertFalse((self.home / 'ideas').exists())

    def test_adopt_for_an_existing_open_anomaly_only_sets_its_experiment(self):
        write_anomaly_text(self.home, 'slow-check', 2, 3)
        before = records.read_anomaly(self.home / 'anomalies' / 'slow-check.md')
        code, _, err = self.adopt('--signature', 'slow-check', *EXPERIMENT)
        self.assertEqual((code, err), (0, ''))
        after = records.read_anomaly(self.home / 'anomalies' / 'slow-check.md')
        self.assertEqual(after.experiment.metric, 'active minutes')
        self.assertEqual(after.experiment.result, '')
        after.experiment = None
        self.assertEqual(after, before)
        idea = ideas.load_ideas(self.home)[0]
        self.assertEqual((idea.related, idea.scores_at_assessment), (['slow-check'], {'slow-check': 6}))

    def test_adopt_for_an_existing_anomaly_refuses_a_second_experiment_a_closed_record_or_a_description(self):
        write_anomaly_text(self.home, 'with-experiment', 1, 1)
        write_anomaly_text(self.home, 'closed', 1, 1, status='fixed')
        write_anomaly_text(self.home, 'plain', 1, 1)
        path = self.home / 'anomalies' / 'with-experiment.md'
        anomaly = records.read_anomaly(path)
        anomaly.experiment = records.Experiment(expect='e', metric='m', guard='g', check_by='2026-11-01')
        records.write_anomaly(self.home, anomaly)
        for argv in (['--signature', 'with-experiment', *EXPERIMENT], ['--signature', 'closed', *EXPERIMENT],
                     ['--signature', 'plain', '--summary', 'new text', *EXPERIMENT],
                     ['--signature', 'plain', '--category', 'rework', *EXPERIMENT]):
            code, _, err = self.adopt(*argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.startswith('anomaly: '))
        self.assertFalse((self.home / 'ideas').exists())

    def test_adopt_options_with_another_verdict_are_refused(self):
        code, _, err = self.run_assess('record', '--slug', 'x', '--source', 'an opinion', '--verdict', 'trial',
                                       '--body', 'b', *self.NEW, *EXPERIMENT)
        self.assertEqual(code, 2)
        self.assertIn('adopt', err)
        self.assertFalse((self.home / 'ideas').exists())

    def test_adopt_can_say_the_lessons_are_already_built_in_and_then_writes_only_the_idea(self):
        write_anomaly_text(self.home, 'other', 2, 2)
        before = (self.home / 'anomalies' / 'other.md').read_bytes()
        code, out, err = self.adopt('--already-applied')
        self.assertEqual((code, err), (0, ''))
        self.assertNotIn('anomaly file:', out)
        self.assertEqual(ideas.load_ideas(self.home)[0].verdict, 'adopt')
        self.assertEqual((self.home / 'anomalies' / 'other.md').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['anomalies', 'ideas'])

    def test_already_applied_needs_the_verdict_adopt_and_no_experiment_options(self):
        for argv in (['--verdict', 'trial'], ['--verdict', 'adopt', '--signature', 'x']):
            code, _, err = self.run_assess('record', '--slug', 'x', '--source', 'an opinion', '--body', 'b',
                                           '--already-applied', *argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.startswith('anomaly: '))
        self.assertFalse((self.home / 'ideas').exists())

    def test_a_trial_changes_nothing_but_the_idea_file(self):
        write_anomaly_text(self.home, 'other', 2, 2)
        before = (self.home / 'anomalies' / 'other.md').read_bytes()
        self.run_assess('record', '--slug', 'x', '--source', 'an opinion', '--verdict', 'trial', '--body', 'b',
                        '--related', 'other')
        self.assertEqual((self.home / 'anomalies' / 'other.md').read_bytes(), before)
        self.assertFalse((self.home / 'INDEX.md').exists())
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['anomalies', 'ideas'])


class PrivacyTest(HomeCase):
    CREDENTIAL = 'to' + 'ken=' + 'abc123'
    LEAKS = {'a URL with a query string': 'see https://example.com/page?id=7 for it',
             'an email address': 'ask someone@example.com about it',
             'a credential': 'the setting ' + CREDENTIAL + ' was shown'}

    def record(self, body, *extra, verdict='reject'):
        return self.run_assess('record', '--slug', 'q', '--source', 'an opinion', '--verdict', verdict,
                               '--body', body, *extra)

    def assert_refused(self, result, key, reason=None):
        code, out, err = result
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertIn(key, err)
        if reason:
            self.assertIn(reason, err)
        self.assertFalse((self.home / 'ideas').exists())
        self.assertFalse((self.home / 'anomalies').exists())

    def test_a_body_with_a_query_url_an_email_or_a_credential_is_refused(self):
        for reason, text in self.LEAKS.items():
            self.assert_refused(self.record('Fine first line.\n' + text), 'body', reason)

    def test_a_quoted_line_is_checked_like_any_other(self):
        self.assert_refused(self.record('> mail me at someone@example.com'), 'body', 'an email address')

    def test_normal_wording_is_accepted_including_words_that_sound_like_secrets(self):
        code, _, err = self.record('Token cost grew, so the secret sauce of the loop is one metric.\nSecond line.')
        self.assertEqual((code, err), (0, ''))

    def test_a_very_long_body_line_is_refused_but_many_short_lines_are_fine(self):
        self.assert_refused(self.record('word ' * (constants.PARAGRAPH_MAX_CHARS // 4)), 'body', 'longer than')
        self.assertEqual(self.record('\n'.join(['A short line.'] * 60))[0], 0)

    def test_every_text_option_of_an_adopt_is_checked(self):
        base = ['--signature', 'checks-too-slow', '--category', 'automated-checks', '--summary', 'Slow.',
                '--fix', 'Run less.', '--expect', 'faster', '--metric', 'minutes', '--guard', 'rework',
                '--target', 'scripts/check.sh', '--scope', 'global']
        for option in ('--summary', '--fix', '--expect', '--metric', '--guard', '--target', '--scope'):
            argv = list(base)
            argv[argv.index(option) + 1] = 'mail someone@example.com'
            self.assert_refused(self.record('b', *argv, verdict='adopt'), option[2:], 'an email address')

    def test_a_related_entry_the_source_and_the_identifiers_are_checked(self):
        self.assert_refused(self.record('b', '--related', 'https://example.com/a?id=1'), 'related', 'a URL')
        code, out, err = self.run_assess('record', '--slug', 'q', '--source',
                                         'https://example.com/reset/a1b2c3d4e5f6g7h8i9j0k1l2', '--verdict', 'reject',
                                         '--body', 'b')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('source', err)
        self.assertIn('opaque', err)
        code, _, err = self.run_assess('record', '--slug', 'q', '--source', 'an opinion', '--verdict', 'adopt',
                                       '--body', 'b', '--signature', 'with space', '--expect', 'e', '--metric', 'm',
                                       '--guard', 'g')
        self.assertEqual(code, 2)
        self.assertFalse((self.home / 'ideas').exists())

    def test_a_multi_line_option_is_refused(self):
        self.assert_refused(self.record('b', '--related', 'one\ntwo'), 'related', 'one line')


class SightingAndCommitTest(HomeCase):
    ARGV = ['record', '--slug', 'faster-checks', '--source', 'https://example.com/post', '--verdict', 'adopt',
            '--body', 'Worth a try.', '--signature', 'checks-too-slow', '--category', 'automated-checks',
            '--summary', 'The check run takes long.', '--fix', 'Run the fast suite first.', *EXPERIMENT]

    def repo_home(self, tracked=()):
        repo = GitFixture(Path(self.tmp.name) / 'repo')
        self.home = repo.root / 'anomaly-home'
        repo.write('README.md', 'x\n')
        for name, text in tracked:
            repo.write(name, text)
        repo.commit(['README.md', *[name for name, _ in tracked]], 'chore: start', NOW.date())
        return repo

    def test_the_sighting_line_comes_from_the_records_owner(self):
        self.run_assess(*self.ARGV)
        anomaly = records.read_anomaly(self.home / 'anomalies' / 'checks-too-slow.md')
        [line] = anomaly.sightings
        self.assertEqual(line, records.sighting_line('2026-10-04', constants.UNKNOWN_REPO, 'faster-checks',
                                                    'raised by an idea that was assessed and adopted'))
        self.assertEqual(records.sighting_session(line), 'faster-checks')

    def test_the_paths_written_are_committed_and_nothing_else(self):
        repo = self.repo_home([('anomaly-home/anomalies/older.md', anomaly_text('older', 1, 1))])
        repo.write('README.md', 'edited elsewhere\n')
        repo.write('anomaly-home/ideas/unrelated.md', 'draft\n')
        code, out, err = self.run_assess(*self.ARGV)
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(sorted(repo.git('show', '--name-only', '--format=', 'HEAD').split()),
                         ['anomaly-home/INDEX.md', 'anomaly-home/anomalies/checks-too-slow.md',
                          'anomaly-home/ideas/faster-checks.md'])
        self.assertEqual(repo.git('log', '-1', '--format=%s').strip(), 'chore(anomaly): assess faster-checks (adopt)')
        self.assertEqual(sorted(repo.status()), [' M README.md', '?? anomaly-home/ideas/unrelated.md'])
        self.assertEqual(len([line for line in out.splitlines() if line.startswith('commit: ')]), 1)

    def test_a_park_commits_only_the_idea_file(self):
        repo = self.repo_home()
        self.run_assess('record', '--slug', 'later', '--source', 'an opinion', '--verdict', 'park',
                        '--revisit', '2026-12-01', '--body', 'Not now.')
        self.assertEqual(repo.git('show', '--name-only', '--format=', 'HEAD').split(), ['anomaly-home/ideas/later.md'])
        self.assertEqual(repo.status(), [])

    def test_outside_a_git_repository_it_says_so_and_still_writes(self):
        code, out, _ = self.run_assess(*self.ARGV)
        self.assertEqual(code, 0)
        self.assertIn('commit: none, home is not in a git repository', out.splitlines())
        self.assertTrue((self.home / 'ideas' / 'faster-checks.md').exists())

    def test_a_refused_record_commits_nothing(self):
        repo = self.repo_home()
        head = repo.git('rev-parse', 'HEAD')
        code, _, _ = self.run_assess('record', '--slug', 'x', '--source', 'an opinion', '--verdict', 'reject',
                                     '--body', 'mail someone@example.com')
        self.assertEqual(code, 2)
        self.assertEqual(repo.git('rev-parse', 'HEAD'), head)


class DigestSectionTest(HomeCase):
    def section(self, **overrides):
        return assess.digest_section(context(self.home, **overrides))

    def test_a_parked_idea_whose_date_passed_is_listed_with_its_date(self):
        write_idea_file(self.home, 'due', revisit='2026-10-04')
        write_idea_file(self.home, 'later', revisit='2026-10-05', source='https://example.com/two')
        lines = self.section()
        self.assertEqual(lines[0], '## Parked ideas')
        self.assertEqual(len(lines), 2)
        self.assertIn('due', lines[1])
        self.assertIn('2026-10-04', lines[1])

    def test_a_related_anomaly_that_crossed_the_threshold_is_listed_with_both_scores(self):
        write_anomaly_text(self.home, 'rising', 2, 3)
        write_idea_file(self.home, 'watching', revisit='2027-01-01', related=['rising', 'scripts/x.sh'],
                        scores_at_assessment={'rising': 3})
        lines = self.section()
        self.assertEqual(len(lines), 2)
        self.assertIn('watching', lines[1])
        self.assertIn('rising', lines[1])
        self.assertIn('6', lines[1])
        self.assertIn('3', lines[1])

    def test_no_line_for_scores_that_were_already_high_or_are_still_low(self):
        write_anomaly_text(self.home, 'was-high', 2, 3)
        write_anomaly_text(self.home, 'still-low', 1, 2)
        write_idea_file(self.home, 'a', revisit='2027-01-01', related=['was-high'],
                        scores_at_assessment={'was-high': 4})
        write_idea_file(self.home, 'b', revisit='2027-01-01', related=['still-low'],
                        scores_at_assessment={'still-low': 1}, source='https://example.com/two')
        self.assertEqual(self.section(), [])

    def test_only_parked_ideas_with_an_open_or_reopened_related_anomaly_count(self):
        write_anomaly_text(self.home, 'open-one', 2, 3)
        write_anomaly_text(self.home, 'gone', 2, 3, status='fixed')
        write_anomaly_text(self.home, 'again', 2, 3, status='reopened')
        write_idea_file(self.home, 'trial-idea', verdict='trial', revisit='', related=['open-one'],
                        scores_at_assessment={'open-one': 1})
        write_idea_file(self.home, 'closed-link', revisit='2027-01-01', related=['gone'],
                        scores_at_assessment={'gone': 1}, source='https://example.com/two')
        write_idea_file(self.home, 'missing-link', revisit='2027-01-01', related=['no-such'],
                        scores_at_assessment={'no-such': 1}, source='https://example.com/three')
        write_idea_file(self.home, 'reopened-link', revisit='2027-01-01', related=['again'],
                        scores_at_assessment={'again': 1}, source='https://example.com/four')
        lines = self.section()
        self.assertEqual(len(lines), 2)
        self.assertIn('reopened-link', lines[1])

    def test_a_related_win_never_counts_for_the_score_rise(self):
        write_anomaly_text(self.home, 'good-step', 2, 3, kind='win')
        write_idea_file(self.home, 'wins', revisit='2027-01-01', related=['good-step'],
                        scores_at_assessment={'good-step': 1})
        self.assertEqual(self.section(), [])

    def test_an_idea_with_both_reasons_is_one_line_and_lines_are_in_date_order(self):
        write_anomaly_text(self.home, 'rising', 2, 3)
        write_idea_file(self.home, 'both', revisit='2026-09-01', related=['rising'],
                        scores_at_assessment={'rising': 1})
        write_idea_file(self.home, 'older', revisit='2026-08-01', source='https://example.com/two')
        lines = self.section()
        self.assertEqual(len(lines), 3)
        self.assertIn('older', lines[1])
        self.assertIn('both', lines[2])
        self.assertIn('2026-09-01', lines[2])
        self.assertIn('rising', lines[2])

    def test_nothing_to_say_is_an_empty_section(self):
        self.assertEqual(self.section(), [])
        write_idea_file(self.home, 'quiet', revisit='2027-01-01')
        self.assertEqual(self.section(), [])

    def test_a_damaged_score_is_skipped_not_raised(self):
        write_anomaly_text(self.home, 'rising', 2, 3)
        path = write_idea_file(self.home, 'odd', revisit='2027-01-01', related=['rising'],
                               scores_at_assessment={'rising': 1})
        path.write_text(path.read_text(encoding='utf-8').replace('rising: 1', 'rising: high'), encoding='utf-8')
        self.assertEqual(self.section(), [])

    def test_the_section_is_registered_and_shows_in_the_digest_command(self):
        self.assertIn(('assess', 'digest_section'), digest.SECTIONS)
        self.assertIn(assess.digest_section, digest.section_functions())
        write_idea_file(self.home, 'due', revisit='2026-10-01')
        code, out, err = run_cli('digest', '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('## Parked ideas', out)
        self.assertIn('due', out)

    def test_the_command_is_registered(self):
        self.assertIn('assess', cli.COMMANDS)


class IdeaQuoteRuleTest(unittest.TestCase):
    def idea(self, body):
        return ideas.Idea(slug='x', source='an opinion', assessed='2026-10-04', verdict='reject', body=body)

    def test_quote_rule(self):
        short = 'He says "keep each change small" once.'
        self.assertEqual(ideas.validate_idea(self.idea(short)), [])
        self.assertTrue(ideas.validate_idea(self.idea(short + ' Then "never run it at night alone".')))
        self.assertTrue(ideas.validate_idea(self.idea('> ' + ' '.join(['word'] * 16))))
        self.assertTrue(ideas.validate_idea(self.idea('> one short quoted line here\n\nthen text\n> a second quote')))
        self.assertEqual(ideas.validate_idea(self.idea('> one short quoted line here')), [])
        self.assertEqual(ideas.validate_idea(self.idea('> a quote that wraps\n> over two lines')), [])
        self.assertTrue(ideas.validate_idea(self.idea('> ' + ' '.join(['word'] * 10) + '\n> ' + ' '.join(['word'] * 10))))
        self.assertTrue(ideas.validate_idea(self.idea('First ‘keep each change small’ then ‘never run at night’.')))
        self.assertEqual(ideas.validate_idea(self.idea('It is the author’s view and the team’s view.')), [])
        self.assertEqual(ideas.validate_idea(self.idea('He says “keep each change small” once.')), [])
        self.assertEqual(ideas.validate_idea(self.idea('A "loop", a "guard" and a "log of tries".')), [])


if __name__ == '__main__':
    unittest.main()

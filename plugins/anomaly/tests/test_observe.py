import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anomaly_loop import constants, observe, records
from tests.fixtures import (NOW, SID, GitFixture, anomaly_text, observed, run_cli, write_anomaly_text, write_batch,
                            write_experiment_anomaly, write_text)

TODAY = NOW.date().isoformat()
OTHER_SID = '22222222-aaaa-bbbb-cccc-000000000002'


class ObserveCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.batch_path = self.root / 'data' / 'batch.json'

    def apply(self, *sightings, now=NOW, **batch):
        write_batch(self.batch_path, sightings=list(sightings), **batch)
        return run_cli('observe', 'apply', '--home', str(self.home), '--file', str(self.batch_path), now=now)

    def anomaly(self, signature='slow-check'):
        return records.read_anomaly(records.anomaly_path(self.home, signature))



class CategorySplitTest(unittest.TestCase):
    def test_seven_environment_and_six_workflow_categories_cover_the_thirteen_exactly(self):
        self.assertEqual(len(constants.ENVIRONMENT_CATEGORIES), 7)
        self.assertEqual(len(constants.WORKFLOW_CATEGORIES), 6)
        both = constants.ENVIRONMENT_CATEGORIES + constants.WORKFLOW_CATEGORIES
        self.assertEqual(both, constants.CATEGORIES)
        self.assertEqual(len(set(both)), 13)
        self.assertIn('tool-economy', constants.ENVIRONMENT_CATEGORIES)
        self.assertIn('late-catch', constants.WORKFLOW_CATEGORIES)


class NewAnomalyTest(ObserveCase):
    def test_a_new_signature_creates_one_anomaly_with_one_sighting(self):
        code, out, err = self.apply(observed())
        self.assertEqual((code, err), (0, ''))
        self.assertIn('logged: slow-check (new)', out.splitlines())
        found = self.anomaly()
        self.assertEqual((found.kind, found.category, found.target, found.scope, found.impact),
                         ('problem', 'automated-checks', 'scripts/check.sh', 'repo:demo', 2))
        self.assertEqual((found.occurrences, found.status, found.effort, found.fixed_by), (1, 'open', '', ''))
        self.assertEqual((found.first_seen, found.last_seen), (TODAY, TODAY))
        self.assertEqual((found.summary, found.proposed_fix),
                         ('The check runs every test twice.', 'Run the fast suite first.'))
        self.assertEqual(found.sightings, [f'{TODAY} · demo · {SID} · the check took long again'])

    def test_a_new_win_needs_no_fix(self):
        code, _, _ = self.apply(observed('review-caught-race', kind='win', category='late-catch', fix='',
                                         summary='The review found a race before merge.'))
        self.assertEqual(code, 0)
        found = self.anomaly('review-caught-race')
        self.assertEqual((found.kind, found.proposed_fix), ('win', ''))

    def test_a_new_problem_without_a_fix_is_refused_and_nothing_is_written(self):
        code, out, err = self.apply(observed('a-first'), observed('no-fix', fix=''))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))
        self.assertIn('no-fix', err)
        self.assertFalse((self.home / 'anomalies').exists())
        self.assertFalse((self.home / 'INDEX.md').exists())

    def test_an_invalid_field_names_the_anomaly_and_blocks_the_whole_batch(self):
        for change in ({'category': 'speed'}, {'kind': 'bug'}, {'impact': 4}, {'impact': '2'},
                       {'signature': 'Not A Slug'}, {'summary': ''}, {'scope': ''}):
            with self.subTest(change=change):
                code, _, err = self.apply(observed('fine-one'), {**observed('bad-one'), **change})
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith('anomaly: '))
                self.assertFalse((self.home / 'anomalies').exists())

    def test_an_invalid_anomaly_writes_no_lens_or_kind_line_either(self):
        code, _, err = self.apply({**observed('bad-one'), 'category': 'speed'},
                                  lenses=[dict(session=SID, lens='reviewer-a', accepted=1, rejected=0)],
                                  kind=dict(session=SID, kind='build'))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))
        self.assertFalse(self.home.exists())

    def test_a_hand_edited_check_by_that_is_not_a_date_blocks_the_batch(self):
        path = write_experiment_anomaly(self.home, 'slow-check', check_by='2026-10-25')
        write_text(path, path.read_text(encoding='utf-8').replace('check_by: 2026-10-25', 'check_by: soon'))
        code, _, err = self.apply(observed(session=OTHER_SID))
        self.assertEqual(code, 2)
        self.assertIn('check_by', err)
        self.assertEqual(self.anomaly().occurrences, 1)


class SeenAgainTest(ObserveCase):
    def setUp(self):
        super().setUp()
        write_anomaly_text(self.home, 'slow-check', 1, 2, last_seen='2026-09-20', category='automated-checks',
                  sightings=('2026-09-20 · demo · s2 · again', '2026-09-10 · demo · s1 · first'))

    def test_a_match_adds_one_occurrence_updates_last_seen_and_prepends_the_sighting(self):
        code, out, _ = self.apply(observed(impact=1, text='slow once more'))
        self.assertEqual(code, 0)
        self.assertIn('logged: slow-check (seen 3 times, score 3)', out.splitlines())
        found = self.anomaly()
        self.assertEqual((found.occurrences, found.last_seen, found.first_seen), (3, TODAY, '2026-09-01'))
        self.assertEqual(found.sightings, [f'{TODAY} · demo · {SID} · slow once more',
                                           '2026-09-20 · demo · s2 · again', '2026-09-10 · demo · s1 · first'])

    def test_a_worse_sighting_raises_impact_and_a_milder_one_never_lowers_it(self):
        self.apply(observed(impact=3))
        self.assertEqual(self.anomaly().impact, 3)
        self.apply(observed(impact=1, session=OTHER_SID))
        self.assertEqual(self.anomaly().impact, 3)

    def test_the_text_of_the_existing_anomaly_is_kept(self):
        self.apply(observed(summary='A different paragraph.', fix='A different fix.', category='rework',
                            target='other', scope='global'))
        found = self.anomaly()
        self.assertEqual((found.summary, found.proposed_fix, found.category, found.target, found.scope),
                         ('What went wrong.', 'Change the thing.', 'automated-checks', '', 'global'))

    def test_a_fixed_anomaly_is_reopened_and_the_user_is_told(self):
        write_anomaly_text(self.home, 'slow-check', 2, 1, status='fixed', category='automated-checks')
        code, out, _ = self.apply(observed())
        self.assertEqual(code, 0)
        found = self.anomaly()
        self.assertEqual((found.status, found.occurrences), ('reopened', 2))
        reopened = [line for line in out.splitlines() if line.startswith('reopened: ')]
        self.assertEqual(len(reopened), 1)
        self.assertIn('slow-check', reopened[0])

    def test_a_wontfix_anomaly_keeps_its_status_gets_the_sighting_and_is_mentioned(self):
        write_anomaly_text(self.home, 'slow-check', 2, 1, status='wontfix', category='automated-checks')
        code, out, _ = self.apply(observed())
        self.assertEqual(code, 0)
        found = self.anomaly()
        self.assertEqual((found.status, found.occurrences, len(found.sightings)), ('wontfix', 2, 2))
        mentioned = [line for line in out.splitlines() if line.startswith('wontfix: ')]
        self.assertEqual(len(mentioned), 1)
        self.assertIn('slow-check', mentioned[0])

    def test_a_second_sighting_from_the_same_session_is_not_counted_again(self):
        self.apply(observed(session=OTHER_SID))
        code, out, _ = self.apply(observed(session=OTHER_SID, text='same session, said twice'))
        self.assertEqual(code, 0)
        self.assertIn('skipped: slow-check already has a sighting from this session', out.splitlines())
        found = self.anomaly()
        self.assertEqual((found.occurrences, len(found.sightings)), (3, 3))

    def test_two_sessions_in_one_batch_each_count_and_the_file_is_written_once(self):
        self.apply(observed(session=SID), observed(session=OTHER_SID, text='second session'))
        found = self.anomaly()
        self.assertEqual((found.occurrences, len(found.sightings)), (4, 4))
        self.assertTrue(found.sightings[0].endswith('second session'))

    def test_a_new_signature_twice_in_one_batch_creates_it_once_then_counts_the_second_session(self):
        self.apply(observed('fresh-one'), observed('fresh-one', session=OTHER_SID))
        self.assertEqual(self.anomaly('fresh-one').occurrences, 2)


class PrivacyTest(ObserveCase):
    def test_text_with_a_url_query_an_email_a_secret_or_several_lines_is_refused(self):
        bad = ('opened https://example.com/page?code=abc123 and failed', 'asked jane.doe@example.com',
               'the token: example and failed', 'line one\nline two', 'word ' * 130,
               'key ' + 'A1b2C3d4' * 5)
        for text in bad:
            for field in ('text', 'summary', 'fix'):
                with self.subTest(text=text[:25], field=field):
                    code, _, err = self.apply(observed(**{field: text}))
                    self.assertEqual(code, 2)
                    self.assertTrue(err.startswith('anomaly: '))
                    self.assertIn(field, err)
                    self.assertFalse((self.home / 'anomalies').exists())

    def test_plain_process_wording_with_paths_and_a_bare_url_is_accepted(self):
        code, _, _ = self.apply(observed(text='read plugins/anomaly/anomaly_loop/cli.py and https://example.com/docs'))
        self.assertEqual(code, 0)

    def test_target_and_scope_get_the_same_privacy_check(self):
        for field in ('target', 'scope'):
            for value in ('https://x.example/a?sig=abc&user=jane@example.com', 'jane.doe@example.com', 'a\nb'):
                with self.subTest(field=field, value=value[:20]):
                    code, _, err = self.apply(observed(**{field: value}))
                    self.assertEqual(code, 2)
                    self.assertIn(field, err)
                    self.assertFalse((self.home / 'anomalies').exists())

    def test_repo_and_session_must_be_single_line_identifiers_without_the_separator(self):
        for field in ('repo', 'session'):
            for value in ('x\n- injected · line', 'a · b', 'two words', 'a?b=c', 'x' * 81):
                with self.subTest(field=field, value=value[:20]):
                    code, _, err = self.apply(observed(**{field: value}))
                    self.assertEqual(code, 2)
                    self.assertIn(field, err)
                    self.assertFalse((self.home / 'anomalies').exists())

    def test_real_looking_targets_are_accepted(self):
        for number, target in enumerate(('~/.config/skills/build/SKILL.md', 'plugins/anomaly/skills/observe/SKILL.md',
                                         'useResizeObserverCallbackHandler',
                                         'https://git.example/group/project/-/merge_requests/123')):
            with self.subTest(target=target):
                code, _, _ = self.apply(observed(f'target-{number}', target=target))
                self.assertEqual(code, 0)
                self.assertEqual(self.anomaly(f'target-{number}').target, target)

    def test_ordinary_identifiers_are_accepted(self):
        code, _, _ = self.apply(observed(session=SID, repo='my-repo.v2'))
        self.assertEqual(code, 0)
        self.assertEqual(self.anomaly().sightings, [f'{TODAY} · my-repo.v2 · {SID} · the check took long again'])

    def test_wording_the_old_gate_refused_is_accepted_now(self):
        for text in ('token cost grew after the review', f'run {SID} was long', 'fixed in ' + 'ab' * 20):
            with self.subTest(text=text[:20]):
                code, _, _ = self.apply(observed(text=text, session=OTHER_SID))
                self.assertEqual(code, 0)


class LensTest(ObserveCase):
    def lenses(self):
        return records.load_lenses(self.home)

    def test_one_line_per_lens_in_the_shared_format(self):
        code, out, _ = self.apply(lenses=[
            dict(session=SID, lens='reviewer-a', accepted=3, rejected=1, revised=1),
            dict(session=SID, lens='reviewer-b', accepted=0, rejected=2)])
        self.assertEqual(code, 0)
        self.assertEqual(self.lenses(), [
            dict(session_id=SID, date=TODAY, lens='reviewer-a', accepted=3, rejected=1, revised=1),
            dict(session_id=SID, date=TODAY, lens='reviewer-b', accepted=0, rejected=2)])
        self.assertIn('lens: reviewer-a logged (accepted 3, rejected 1, revised 1)', out.splitlines())
        self.assertIn('lens: reviewer-b logged (accepted 0, rejected 2)', out.splitlines())

    def test_a_lens_already_logged_for_the_session_is_skipped(self):
        lens = dict(session=SID, lens='reviewer-a', accepted=3, rejected=1)
        self.apply(lenses=[lens])
        _, out, _ = self.apply(lenses=[dict(lens, accepted=9)])
        self.assertEqual(len(self.lenses()), 1)
        self.assertIn('skipped: lens reviewer-a already logged for this session', out.splitlines())

    def test_a_lens_with_no_decisions_is_skipped_and_bad_counts_are_refused(self):
        _, out, _ = self.apply(lenses=[dict(session=SID, lens='reviewer-a', accepted=0, rejected=0)])
        self.assertEqual(self.lenses(), [])
        self.assertIn('skipped: lens reviewer-a has no accepted or rejected findings', out.splitlines())
        for bad in (dict(accepted=-1), dict(accepted='2'), dict(rejected=None), dict(lens=''), dict(session=''),
                    dict(lens='Jane Doe'), dict(lens='a · b'), dict(session='x\ny'), dict(revised=-1),
                    dict(revised=2)):
            with self.subTest(bad=bad):
                code, _, err = self.apply(lenses=[{**dict(session=SID, lens='r', accepted=1, rejected=1), **bad}])
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith('anomaly: '))
        self.assertTrue(err.startswith('anomaly: lens 1: revised 2'), err)   # the last bad entry, named as the batch names it
        self.assertEqual(self.lenses(), [])


class SessionKindTest(ObserveCase):
    def test_an_override_is_appended_and_the_last_line_wins(self):
        self.apply(kind=dict(session=SID, kind='build'))
        code, out, _ = self.apply(kind=dict(session=SID, kind='debug'))
        self.assertEqual(code, 0)
        self.assertIn(f'kind: {SID} is now debug', out.splitlines())
        lines = (self.home / 'session-kinds.jsonl').read_text(encoding='utf-8').splitlines()
        self.assertEqual([json.loads(line) for line in lines],
                         [dict(session_id=SID, kind='build', set_on=TODAY),
                          dict(session_id=SID, kind='debug', set_on=TODAY)])
        self.assertEqual(records.load_session_kinds(self.home)[SID]['kind'], 'debug')

    def test_the_same_kind_again_adds_no_line(self):
        self.apply(kind=dict(session=SID, kind='build'))
        _, out, _ = self.apply(kind=dict(session=SID, kind='build'))
        self.assertIn(f'kind: {SID} is already build', out.splitlines())
        self.assertEqual(len((self.home / 'session-kinds.jsonl').read_text(encoding='utf-8').splitlines()), 1)

    def test_an_unknown_kind_or_a_missing_session_is_refused(self):
        for bad in (dict(session=SID, kind='fun'), dict(session='', kind='build'), dict(session=SID),
                    dict(session='a b', kind='build'), dict(session='x\ny', kind='build')):
            with self.subTest(bad=bad):
                code, _, err = self.apply(kind=bad)
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith('anomaly: '))
        self.assertFalse((self.home / 'session-kinds.jsonl').exists())


class BatchShapeTest(ObserveCase):
    def test_a_file_that_is_not_a_json_object_or_has_unknown_keys_is_refused(self):
        for text in ('not json', '[]', '{"sightings": {}}', '{"sighting": []}', '{"sightings": [1]}',
                     '{"sightings": [{"signature": "a-b", "oops": 1}]}'):
            with self.subTest(text=text):
                write_text(self.batch_path, text)
                code, _, err = run_cli('observe', 'apply', '--home', str(self.home), '--file', str(self.batch_path))
                self.assertEqual(code, 2)
                self.assertTrue(err.startswith('anomaly: '))

    def test_a_missing_batch_file_is_one_anomaly_error(self):
        code, _, err = run_cli('observe', 'apply', '--home', str(self.home), '--file', str(self.root / 'none.json'))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))

    def test_an_empty_batch_writes_nothing(self):
        code, out, _ = self.apply()
        self.assertEqual(code, 0)
        self.assertIn('nothing to record', out)
        self.assertFalse(self.home.exists())

    def from_stdin(self, payload, encoding='utf-8'):
        # A text stream that decodes with another code page, like standard input on Windows.
        stream = io.TextIOWrapper(io.BytesIO(payload), encoding=encoding)
        with mock.patch.object(sys, 'stdin', stream):
            return run_cli('observe', 'apply', '--home', str(self.home), '--file', '-')

    def test_the_batch_can_come_from_standard_input(self):
        code, out, _ = self.from_stdin(json.dumps(dict(sightings=[observed()])).encode('utf-8'))
        self.assertEqual(code, 0)
        self.assertIn('logged: slow-check (new)', out.splitlines())

    def test_standard_input_is_read_as_utf8_whatever_the_console_code_page(self):
        payload = json.dumps(dict(sightings=[observed(text='the café check took long')]), ensure_ascii=False)
        code, _, err = self.from_stdin(payload.encode('utf-8'), encoding='cp1252')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.anomaly().sightings, [f'{TODAY} · demo · {SID} · the café check took long'])

    def test_standard_input_that_is_not_utf8_is_one_anomaly_error(self):
        code, _, err = self.from_stdin(b'{"sightings": [{"text": "caf\xe9"}]}', encoding='latin-1')
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))
        self.assertIn('not UTF-8', err)


class IndexAndCommitTest(ObserveCase):
    def test_the_index_is_regenerated_after_writing(self):
        _, out, _ = self.apply(observed())
        index = (self.home / 'INDEX.md').read_text(encoding='utf-8')
        self.assertIn('slow-check', index)
        self.assertIn('index: 1 open, 0 closed', out.splitlines())

    def test_the_reply_lists_the_top_three_open_anomalies_by_score(self):
        write_anomaly_text(self.home, 'low-one', 1, 1)
        write_anomaly_text(self.home, 'high-one', 3, 3)
        write_anomaly_text(self.home, 'mid-one', 2, 2)
        write_anomaly_text(self.home, 'fourth-one', 1, 2)
        write_anomaly_text(self.home, 'closed-one', 3, 9, status='fixed')
        _, out, _ = self.apply(observed('fresh-one', impact=1))
        self.assertEqual([line for line in out.splitlines() if line.startswith('top: ')],
                         ['top: 9 high-one', 'top: 4 mid-one', 'top: 2 fourth-one'])

    def test_outside_a_git_repository_nothing_is_committed_and_it_says_so(self):
        _, out, _ = self.apply(observed())
        self.assertIn('commit: none, home is not in a git repository', out.splitlines())


class CommitTest(ObserveCase):
    def setUp(self):
        super().setUp()
        self.repo = GitFixture(self.root / 'repo')
        self.home = self.repo.root / 'anomaly-home'
        self.repo.write('README.md', 'x\n')
        self.repo.write('anomaly-home/anomalies/older.md', anomaly_text('older', 1, 1))
        self.repo.commit(['README.md', 'anomaly-home/anomalies/older.md'], 'chore: start', NOW.date())

    def last_commit_files(self):
        return sorted(self.repo.git('show', '--name-only', '--format=', 'HEAD').split())

    def test_only_the_written_home_paths_are_committed_and_foreign_edits_stay_out(self):
        self.repo.write('README.md', 'edited elsewhere\n')
        self.repo.write('anomaly-home/anomalies/older.md', anomaly_text('older', 3, 9))
        self.repo.write('anomaly-home/ideas/unrelated.md', 'draft\n')
        before = self.repo.git('rev-parse', 'HEAD').strip()
        code, out, _ = self.apply(observed(), lenses=[dict(session=SID, lens='reviewer-a', accepted=1, rejected=0)],
                                  kind=dict(session=SID, kind='build'))
        self.assertEqual(code, 0)
        self.assertNotEqual(self.repo.git('rev-parse', 'HEAD').strip(), before)
        self.assertEqual(self.last_commit_files(), ['anomaly-home/INDEX.md', 'anomaly-home/anomalies/slow-check.md',
                                                    'anomaly-home/lenses.jsonl', 'anomaly-home/session-kinds.jsonl'])
        self.assertEqual(sorted(self.repo.status()),
                         [' M README.md', ' M anomaly-home/anomalies/older.md', '?? anomaly-home/ideas/unrelated.md'])
        commit_line = [line for line in out.splitlines() if line.startswith('commit: ')]
        self.assertEqual(len(commit_line), 1)
        self.assertIn(self.repo.git('rev-parse', '--short', 'HEAD').strip()[:7], commit_line[0])

    def test_the_commit_message_follows_the_angular_style(self):
        self.apply(observed())
        subject = self.repo.git('log', '-1', '--format=%s').strip()
        self.assertRegex(subject, r'^chore\(anomaly\): log slow-check$')
        self.apply(observed('another-one'), observed('third-one'))
        self.assertEqual(self.repo.git('log', '-1', '--format=%s').strip(), 'chore(anomaly): log 2 sightings')

    def test_a_run_that_changes_nothing_new_reports_no_new_commit(self):
        self.apply(observed())
        head = self.repo.git('rev-parse', 'HEAD').strip()
        _, out, _ = self.apply(observed())
        self.assertEqual(self.repo.git('rev-parse', 'HEAD').strip(), head)
        self.assertIn('commit: none, nothing changed', out.splitlines())


class CommitFailureTest(ObserveCase):
    def test_a_failing_commit_keeps_the_written_files_and_reports_one_line(self):
        repo = GitFixture(self.root / 'repo')
        self.home = repo.root / 'anomaly-home'
        repo.write('README.md', 'x\n')
        repo.commit(['README.md'], 'chore: start', NOW.date())
        hook = repo.root / '.git' / 'hooks' / 'pre-commit'
        write_text(hook, '#!/bin/sh\nexit 1\n')
        hook.chmod(0o755)
        code, out, _ = self.apply(observed())
        self.assertEqual(code, 0)
        self.assertTrue((self.home / 'anomalies' / 'slow-check.md').is_file())
        failed = [line for line in out.splitlines() if line.startswith('commit: failed')]
        self.assertEqual(len(failed), 1)
        self.assertIn('files are written', failed[0])


class ListTest(ObserveCase):
    def test_list_shows_every_anomaly_with_what_matching_needs_and_closed_ones_too(self):
        write_anomaly_text(self.home, 'open-one', 2, 3, category='rework')
        write_anomaly_text(self.home, 'done-one', 1, 1, status='fixed')
        code, out, _ = run_cli('observe', 'list', '--home', str(self.home))
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertIn('anomalies: 2 (1 open, 1 closed)', lines)
        open_line = next(line for line in lines if line.startswith('open-one'))
        for part in ('problem', 'rework', 'global', 'open', 'impact 2', 'seen 3', 'What went wrong.'):
            self.assertIn(part, open_line)
        self.assertTrue(any(line.startswith('done-one') and 'fixed' in line for line in lines))

    def test_list_of_an_empty_home_says_so(self):
        _, out, _ = run_cli('observe', 'list', '--home', str(self.home))
        self.assertIn('anomalies: none yet', out.splitlines())

    def test_the_missing_profile_is_reported_once_and_a_complete_one_is_silent(self):
        _, out, _ = run_cli('observe', 'list', '--home', str(self.home))
        profile_lines = [line for line in out.splitlines() if line.startswith('profile:')]
        self.assertEqual(len(profile_lines), 1)
        self.assertEqual(out.splitlines()[0], profile_lines[0])
        self.assertIn('tracker', profile_lines[0])
        write_text(self.home / 'profile.md', '---\ntracker: a\nglossary_file: b\nticket_key: C\\d+\n'
                   'branch_pattern: d\ncommit_style: e\nimplementers:\n  s: f\nmr_tool: g\nverify_ui: h\n'
                   'issue_source: i\n---\n')
        _, out, _ = run_cli('observe', 'list', '--home', str(self.home))
        self.assertNotIn('profile:', out)

    def test_a_profile_that_is_not_utf8_does_not_stop_the_command(self):
        self.home.mkdir(parents=True)
        (self.home / 'profile.md').write_bytes(b'---\ntracker: caf\xe9\n---\n')
        code, out, err = run_cli('observe', 'list', '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        self.assertIn('not UTF-8 text', out.splitlines()[0])
        self.assertIn('anomalies: none yet', out.splitlines())

    def test_a_long_summary_is_cut_to_one_short_line(self):
        write_anomaly_text(self.home, 'open-one', 2, 3)
        path = records.anomaly_path(self.home, 'open-one')
        found = records.read_anomaly(path)
        found.summary = 'Word ' * 80 + '\n\nSecond paragraph.'
        records.write_anomaly(self.home, found)
        _, out, _ = run_cli('observe', 'list', '--home', str(self.home))
        line = next(line for line in out.splitlines() if line.startswith('open-one'))
        self.assertNotIn('Second paragraph', line)
        self.assertLess(len(line), 300)


class SaveAnomaliesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = GitFixture(Path(self.tmp.name).resolve() / 'repo')
        self.home = self.repo.root / 'anomaly-home'
        self.repo.write('README.md', 'x\n')
        self.repo.write('anomaly-home/anomalies/older.md', anomaly_text('older', 1, 1))
        self.repo.write('anomaly-home/anomalies/other.md', anomaly_text('other', 1, 1))
        self.repo.commit(['README.md', 'anomaly-home/anomalies/older.md', 'anomaly-home/anomalies/other.md'],
                         'chore: start', NOW.date())

    def loaded(self):
        return {a.signature: a for a in records.load_anomalies(self.home, strict=True)}

    def test_only_the_changed_records_and_the_index_are_written_and_committed(self):
        anomalies = self.loaded()
        anomalies['older'].effort = 'S'
        self.repo.write('README.md', 'edited elsewhere\n')
        line = observe.save_anomalies(self.home, NOW.date(), anomalies, ['older', 'older'], 'chore(anomaly): test')
        self.assertTrue(line.startswith('commit: '))
        files = sorted(self.repo.git('show', '--name-only', '--format=', 'HEAD').split())
        self.assertEqual(files, ['anomaly-home/INDEX.md', 'anomaly-home/anomalies/older.md'])
        self.assertEqual(self.repo.git('log', '-1', '--format=%s').strip(), 'chore(anomaly): test')
        self.assertEqual(self.repo.status(), [' M README.md'])

    def test_an_invalid_record_stops_everything_before_any_write(self):
        anomalies = self.loaded()
        anomalies['older'].effort = 'S'
        anomalies['other'].impact = 9
        with self.assertRaises(records.RecordError):
            observe.save_anomalies(self.home, NOW.date(), anomalies, ['older', 'other'], 'chore(anomaly): test')
        self.assertEqual(records.read_anomaly(self.home / 'anomalies' / 'older.md').effort, '')
        self.assertFalse((self.home / 'INDEX.md').exists())


if __name__ == '__main__':
    unittest.main()

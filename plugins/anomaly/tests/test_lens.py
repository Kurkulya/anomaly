"""`lens tally add` and `lens tally sum` through the CLI, in-process: one review run's counts per lens go
to `lens-tally.jsonl` in the data folder (never in home); `sum` writes one batch for a session into the
data folder, in the shape `observe apply` reads, so home `lenses.jsonl` gets each lens once."""
import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import cli, lens, records
from tests.fixtures import NOW, SID, assert_cli_error, run_cli, write_text

OTHER_SID = '22222222-aaaa-bbbb-cccc-000000000002'
TODAY = NOW.date().isoformat()


class LensCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.data = self.root / 'data'
        self.tally_path = self.data / 'lens-tally.jsonl'

    def options(self):
        return ['--home', str(self.home), '--data', str(self.data)]

    def add(self, lens='code', accepted=1, rejected=0, session=SID, revised=None):
        extra = [] if revised is None else ['--revised', str(revised)]
        return run_cli('lens', 'tally', 'add', '--session', session, '--lens', lens, '--accepted', str(accepted),
                       '--rejected', str(rejected), *extra, *self.options())

    def add_ok(self, *args, **kwargs):
        code, out, err = self.add(*args, **kwargs)
        self.assertEqual((code, err), (0, ''), out)
        return out

    def sum(self, session=SID, *extra):
        return run_cli('lens', 'tally', 'sum', '--session', session, *self.options(), *extra)

    def summed(self, session=SID):
        """The path `sum` printed (the only stdout line) and the batch in it."""
        code, out, err = self.sum(session)
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(len(out.splitlines()), 1, out)
        path = Path(out.strip())
        return path, json.loads(path.read_bytes().decode('utf-8'))

    def tally_lines(self):
        return [json.loads(line) for line in self.tally_path.read_bytes().decode('utf-8').splitlines()]


class RegistryTest(LensCase):
    def help_actions(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main([*argv, '--help'], environ={})
        return re.findall(r'^ {4}([\w-]+)\s{2,}\S', out.getvalue(), re.M)

    def test_lens_is_registered_once_with_tally_and_tally_with_add_and_sum(self):
        self.assertEqual(cli.COMMANDS.count('lens'), 1)
        self.assertEqual(self.help_actions('lens'), ['tally'])
        self.assertEqual(sorted(self.help_actions('lens', 'tally')), ['add', 'sum'])

    def test_a_missing_action_is_a_usage_error_on_one_line(self):
        assert_cli_error(self, run_cli('lens'))
        assert_cli_error(self, run_cli('lens', 'tally'))

    def test_every_option_of_add_and_the_session_of_sum_is_required(self):
        base = ['lens', 'tally', 'add', '--session', SID, '--lens', 'code', '--accepted', '1', '--rejected', '0']
        for drop in ('--session', '--lens', '--accepted', '--rejected'):
            with self.subTest(missing=drop):
                argv = list(base)
                at = argv.index(drop)
                del argv[at:at + 2]
                assert_cli_error(self, run_cli(*argv, *self.options()), drop.lstrip('-'))
        assert_cli_error(self, run_cli('lens', 'tally', 'sum', *self.options()), 'session')
        self.assertFalse(self.data.exists())


class AddTest(LensCase):
    def test_one_run_appends_one_line_with_the_counts_in_the_data_folder(self):
        out = self.add_ok('code', 3, 1)
        self.assertEqual(self.tally_lines(), [dict(session=SID, lens='code', accepted=3, rejected=1)])
        self.assertEqual(out.splitlines(), ['tally: code accepted 3, rejected 1'])

    def test_each_run_adds_a_line_and_earlier_lines_stay_as_they_were(self):
        self.add_ok('code', 3, 1)
        first = self.tally_path.read_bytes()
        self.add_ok('code', 2, 0)
        self.add_ok('security', 0, 2, session=OTHER_SID)
        self.assertTrue(self.tally_path.read_bytes().startswith(first))
        self.assertEqual(len(self.tally_lines()), 3)

    def test_the_file_uses_line_feeds_and_ends_with_one(self):
        self.add_ok()
        data = self.tally_path.read_bytes()
        self.assertTrue(data.endswith(b'\n'))
        self.assertNotIn(b'\r', data)

    def test_nothing_is_written_in_home(self):
        self.add_ok()
        self.add_ok('feature', 1, 1)
        self.assertFalse(self.home.exists())

    def test_the_counts_may_be_zero(self):
        self.add_ok('feature', 0, 0)
        self.assertEqual(self.tally_lines()[0]['accepted'], 0)

    def test_without_a_data_folder_it_is_an_error_and_nothing_is_written(self):
        code, out, err = run_cli('lens', 'tally', 'add', '--session', SID, '--lens', 'code', '--accepted', '1',
                                 '--rejected', '0', '--home', str(self.home))
        assert_cli_error(self, (code, out, err), 'data folder')
        self.assertFalse(self.home.exists())

    def test_a_data_folder_inside_home_is_refused(self):
        inside = self.home / 'data'
        result = run_cli('lens', 'tally', 'add', '--session', SID, '--lens', 'code', '--accepted', '1',
                         '--rejected', '0', '--home', str(self.home), '--data', str(inside))
        assert_cli_error(self, result, 'inside home')
        self.assertFalse(inside.exists())

    def test_the_data_folder_may_come_from_the_environment(self):
        environ = {'CLAUDE_PLUGIN_DATA': str(self.data)}
        code, out, err = run_cli('lens', 'tally', 'add', '--session', SID, '--lens', 'code', '--accepted', '1',
                                 '--rejected', '0', '--home', str(self.home), environ=environ)
        self.assertEqual((code, err), (0, ''), out)
        self.assertTrue(self.tally_path.is_file())

    def test_a_session_or_lens_that_is_not_one_token_is_refused_and_nothing_is_written(self):
        for key, bad in (('session', 'two words'), ('session', 'line\nbreak'), ('session', 'x' * 81),
                         ('lens', 'code review'), ('lens', 'a · b'), ('lens', '.code')):
            with self.subTest(key=key, value=bad):
                kwargs = {key: bad}
                assert_cli_error(self, self.add(**kwargs), key)
        self.assertFalse(self.data.exists())

    def test_a_colon_in_the_session_is_refused_because_the_session_names_a_file(self):
        assert_cli_error(self, self.add(session='local:7'), 'session', ':')
        self.assertFalse(self.data.exists())

    def test_the_plan_lens_is_accepted_without_a_profile_and_summed_like_a_core_lens(self):
        """Workflow-plan ticket 07, AC-14: the plan agent's counts go through `lens tally` under `plan`."""
        self.add_ok(lens.PLAN_LENS, 3, 1)
        self.assertEqual([row['lens'] for row in self.tally_lines()], [lens.PLAN_LENS])
        _, batch = self.summed()
        self.assertEqual(batch, {'lenses': [dict(session=SID, lens=lens.PLAN_LENS, accepted=3, rejected=1)]})

    def test_the_interview_lens_is_accepted_without_a_profile_like_the_plan_lens(self):
        """Workflow-plan ticket 09: the interview's recommendation counts go through `lens tally` under `interview`."""
        self.assertEqual(lens.INTERVIEW_LENS, 'interview')
        self.add_ok(lens.INTERVIEW_LENS, 2, 1)
        self.assertEqual([row['lens'] for row in self.tally_lines()], [lens.INTERVIEW_LENS])

    def test_a_lens_name_outside_the_allowed_set_is_refused_with_the_allowed_names_and_nothing_is_written(self):
        """AC-97: on an empty profile the allowed lens names are the three core lenses, `plan` and `interview`."""
        assert_cli_error(self, self.add('naming'), 'code', 'feature', 'security', lens.PLAN_LENS, lens.INTERVIEW_LENS,
                         'model_pick')
        self.assertFalse(self.data.exists())

    def test_the_model_pick_lens_is_accepted_without_a_profile_like_the_interview_lens_and_summed_into_the_batch(self):
        """Model-roles ticket 07, AC-18: `build` counts an `implement` ticket's pick under `model_pick`."""
        self.assertEqual(lens.MODEL_PICK_LENS, 'model_pick')
        self.add_ok('model_pick', 0, 1)
        self.add_ok('code', 2, 0)
        self.assertEqual([row['lens'] for row in self.tally_lines()], ['model_pick', 'code'])
        _, batch = self.summed()
        self.assertEqual(batch, {'lenses': [dict(session=SID, lens='model_pick', accepted=0, rejected=1),
                                            dict(session=SID, lens='code', accepted=2, rejected=0)]})

    def test_an_org_reviewer_from_the_reviewers_port_is_a_lens_under_its_adapter_name(self):
        """AC-97: the allowed names follow the profile's reviewers port, so the refusal lists the org name too."""
        write_text(self.home / 'profile.md', '---\nreviewers: org-reviewer\n---\n')
        self.add_ok('org-reviewer', 2, 1)
        self.assertEqual(self.tally_lines()[0]['lens'], 'org-reviewer')
        assert_cli_error(self, self.add('other-reviewer'), 'org-reviewer', 'security')

    def test_a_revised_count_greater_than_the_accepted_count_is_refused_naming_both(self):
        """AC-97: revised counts accepted findings whose fix differed from the proposed one, so it is a subset."""
        assert_cli_error(self, self.add('code', 4, 0, revised=7), 'revised', 'accepted', '7', '4')
        self.assertFalse(self.data.exists())

    def test_a_count_that_is_not_a_whole_number_of_zero_or_more_is_refused(self):
        for bad in ('-1', '1.5', 'many', ''):
            for key in ('accepted', 'rejected'):
                with self.subTest(key=key, value=bad):
                    kwargs = {key: bad}
                    assert_cli_error(self, self.add(**kwargs))
        self.assertFalse(self.data.exists())


class SumTest(LensCase):
    def test_a_sessions_runs_become_one_batch_with_one_line_per_lens(self):
        self.add_ok('code', 3, 1)
        self.add_ok('feature', 2, 0)
        self.add_ok('code', 1, 2)
        self.add_ok('security', 0, 1)
        path, batch = self.summed()
        self.assertEqual(batch, {'lenses': [
            dict(session=SID, lens='code', accepted=4, rejected=3),
            dict(session=SID, lens='feature', accepted=2, rejected=0),
            dict(session=SID, lens='security', accepted=0, rejected=1)]})

    def test_the_batch_is_written_into_the_data_folder_never_into_home(self):
        self.add_ok()
        path, _ = self.summed()
        self.assertTrue(path.is_absolute(), path)
        self.assertEqual(path.parent, self.data)
        self.assertFalse(self.home.exists())

    def test_each_session_has_its_own_batch_file_so_two_sessions_never_overwrite_each_other(self):
        self.add_ok('code', 3, 1)
        self.add_ok('security', 1, 0, session=OTHER_SID)
        path, batch = self.summed(SID)
        other_path, other_batch = self.summed(OTHER_SID)
        self.assertNotEqual(path, other_path)
        self.assertIn(SID, path.name)
        self.assertEqual(json.loads(path.read_bytes().decode('utf-8')), batch)
        self.assertEqual([row['lens'] for row in other_batch['lenses']], ['security'])

    def test_only_the_named_session_is_summed(self):
        self.add_ok('code', 3, 1)
        self.add_ok('code', 5, 5, session=OTHER_SID)
        self.add_ok('security', 1, 0, session=OTHER_SID)
        _, batch = self.summed(SID)
        self.assertEqual(batch, {'lenses': [dict(session=SID, lens='code', accepted=3, rejected=1)]})
        _, batch = self.summed(OTHER_SID)
        self.assertEqual([(row['lens'], row['accepted']) for row in batch['lenses']], [('code', 5), ('security', 1)])

    def test_summing_again_gives_the_same_batch_and_leaves_the_tally_alone(self):
        self.add_ok('code', 3, 1)
        tally = self.tally_path.read_bytes()
        path, first = self.summed()
        again_path, again = self.summed()
        self.assertEqual((again_path, again), (path, first))
        self.assertEqual(self.tally_path.read_bytes(), tally)

    def test_a_run_added_after_a_sum_is_in_the_next_sum(self):
        self.add_ok('code', 1, 0)
        self.summed()
        self.add_ok('code', 1, 1)
        _, batch = self.summed()
        self.assertEqual(batch['lenses'][0]['accepted'], 2)

    def test_a_run_without_revised_counts_0_there_and_a_lens_with_no_revised_run_has_no_revised(self):
        self.add_ok('code', 3, 1, revised=1)
        self.add_ok('code', 2, 0)
        self.add_ok('feature', 1, 0)
        _, batch = self.summed()
        self.assertEqual(batch['lenses'], [dict(session=SID, lens='code', accepted=5, rejected=1, revised=1),
                                           dict(session=SID, lens='feature', accepted=1, rejected=0)])

    def test_the_batch_file_uses_line_feeds(self):
        self.add_ok()
        path, _ = self.summed()
        self.assertNotIn(b'\r', path.read_bytes())

    def test_a_session_with_no_runs_is_an_error_naming_it(self):
        self.add_ok('code', 1, 0, session=OTHER_SID)
        assert_cli_error(self, self.sum(SID), SID)

    def test_with_no_tally_file_at_all_it_is_the_same_error(self):
        assert_cli_error(self, self.sum(SID), SID)

    def test_a_session_that_is_not_one_token_is_refused(self):
        assert_cli_error(self, self.sum('two words'), 'session')

    def test_a_colon_in_the_session_is_refused_before_any_batch_file_is_made(self):
        self.data.mkdir()
        self.tally_path.write_bytes(b'{"session":"local:7","lens":"code","accepted":1,"rejected":0}\n')
        assert_cli_error(self, self.sum('local:7'), 'session', ':')
        self.assertEqual([path.name for path in self.data.iterdir()], ['lens-tally.jsonl'])

    def test_without_a_data_folder_it_is_an_error(self):
        assert_cli_error(self, run_cli('lens', 'tally', 'sum', '--session', SID, '--home', str(self.home)),
                         'data folder')

    def test_a_damaged_line_in_the_tally_is_skipped_and_the_rest_is_summed(self):
        self.add_ok('code', 2, 0)
        with open(self.tally_path, 'a', encoding='utf-8', newline='\n') as f:
            f.write('not json\n')
        self.add_ok('code', 1, 1)
        _, batch = self.summed()
        self.assertEqual(batch['lenses'], [dict(session=SID, lens='code', accepted=3, rejected=1)])


class ObserveHandOffTest(LensCase):
    """The review skill's sequence: tally add per run, tally sum, then one `observe apply --file <path>`."""

    def apply(self, path):
        return run_cli('observe', 'apply', '--home', str(self.home), '--file', str(path))

    def lens_rows(self):
        return [(row['session_id'], row['lens'], row['accepted'], row['rejected'])
                for row in records.load_lenses(self.home)]

    def test_apply_puts_each_lens_once_into_home_with_the_summed_counts(self):
        self.add_ok('code', 3, 1)
        self.add_ok('feature', 2, 0)
        self.add_ok('code', 1, 2)
        path, _ = self.summed()
        code, out, err = self.apply(path)
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.lens_rows(), [(SID, 'code', 4, 3), (SID, 'feature', 2, 0)])
        self.assertIn('lens: code logged (accepted 4, rejected 3)', out.splitlines())
        self.assertEqual(records.load_lenses(self.home)[0]['date'], TODAY)

    def test_a_revised_count_is_summed_and_reaches_home_beside_the_two_counts(self):
        """AC-97: `--revised` adds `revised` to the tally line, the summed batch line and the home line."""
        self.add_ok('code', 3, 1, revised=1)
        self.add_ok('code', 2, 0, revised=2)
        self.assertEqual(self.tally_lines()[0], dict(session=SID, lens='code', accepted=3, rejected=1, revised=1))
        path, batch = self.summed()
        self.assertEqual(batch, {'lenses': [dict(session=SID, lens='code', accepted=5, rejected=1, revised=3)]})
        code, out, err = self.apply(path)
        self.assertEqual((code, err), (0, ''), out)
        row = records.load_lenses(self.home)[0]
        self.assertEqual((row['accepted'], row['rejected'], row['revised']), (5, 1, 3))

    def test_without_revised_the_home_line_keeps_its_two_counts(self):
        """AC-97: two-count lines stay as they were (the tally and batch lines are pinned by AddTest and SumTest)."""
        self.add_ok('code', 3, 1)
        path, _ = self.summed()
        self.apply(path)
        self.assertEqual(set(records.load_lenses(self.home)[0]), {'session_id', 'date', 'lens', 'accepted', 'rejected'})

    def test_applying_the_same_batch_again_changes_nothing(self):
        self.add_ok('code', 3, 1)
        path, _ = self.summed()
        self.apply(path)
        before = (self.home / 'lenses.jsonl').read_bytes()
        code, out, err = self.apply(path)
        self.assertEqual((code, err), (0, ''))
        self.assertIn('skipped: lens code already logged for this session', out.splitlines())
        self.assertEqual((self.home / 'lenses.jsonl').read_bytes(), before)

    def test_the_tally_itself_never_reaches_home(self):
        self.add_ok('code', 3, 1)
        path, _ = self.summed()
        self.apply(path)
        self.assertEqual(sorted(p.name for p in self.home.iterdir() if p.is_file()), ['INDEX.md', 'lenses.jsonl'])
        self.assertNotIn(b'lens-tally', (self.home / 'lenses.jsonl').read_bytes())

    def test_a_lens_with_no_findings_is_skipped_by_observe_not_by_the_tally(self):
        self.add_ok('code', 0, 0)
        self.add_ok('feature', 1, 0)
        path, batch = self.summed()
        self.assertEqual(len(batch['lenses']), 2)
        code, out, err = self.apply(path)
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(self.lens_rows(), [(SID, 'feature', 1, 0)])
        self.assertIn('skipped: lens code has no accepted or rejected findings', out.splitlines())

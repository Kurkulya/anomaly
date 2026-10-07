import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from anomaly_loop import constants, digest, flags, gitrepo, metrics, records, repeats
from tests import test_metrics
from tests.fixtures import (GitFixture, assistant, context, metrics_row, run_cli, ts,
                            write_anomaly_with, write_metrics_rows, write_text)

LONG_AGO = '2026-07-01'


def days(*texts):
    return [date.fromisoformat(text) for text in texts]


class FlagsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.home = self.root / 'home'
        self.user = GitFixture(self.root / 'user-config')
        self.context = self.make()

    def make(self, **overrides):
        return context(self.home, user_config=self.user.root, **overrides)

    def plugin_checkout(self, skills=('measure',)):
        """A git checkout holding the plugin `demo` (a manifest and one folder per skill), uncommitted."""
        self.checkout = GitFixture(self.root / 'checkout')
        self.plugin = self.checkout.root / 'plugins' / 'demo'
        write_text(self.plugin / '.claude-plugin' / 'plugin.json', json.dumps({'name': 'demo'}))
        for name in skills:
            write_text(self.plugin / 'skills' / name / 'SKILL.md', f'# {name}\n')
        return self.plugin

    def skill_history(self, name, commit_days):
        relative = f'plugins/demo/skills/{name}'
        for number, day in enumerate(days(*commit_days)):
            self.checkout.write(f'{relative}/SKILL.md', f'# {name} {number}\n')
            self.checkout.commit([relative], f'change {number}', day)


class NeedsReworkTest(FlagsCase):
    def user_skill(self, name, commit_days):
        relative = f'skills/{name}'
        for number, day in enumerate(days(*commit_days)):
            self.user.write(f'{relative}/SKILL.md', f'# {name} {number}\n')
            self.user.commit([relative], f'change {number}', day)

    def rework(self):
        return flags.needs_rework(self.context)

    def test_three_commits_in_28_days_in_the_user_config_repo_flag_a_user_skill(self):
        self.user_skill('deploy', ['2026-08-01', '2026-09-12', '2026-09-20', '2026-10-01'])
        write_anomaly_with(self.home, 'deploy-slow', target='deploy')
        self.assertEqual(self.rework(), ['## Needs rework', '- deploy: 3 commits in 28 days'])

    def test_two_commits_in_the_window_or_three_spread_over_more_days_do_not_flag(self):
        self.user_skill('few', ['2026-08-01', '2026-09-25', '2026-10-01'])
        self.user_skill('spread', ['2026-08-20', '2026-08-25', '2026-09-05', '2026-09-30'])
        write_anomaly_with(self.home, 'few-a', target='few')
        write_anomaly_with(self.home, 'spread-a', target='spread')
        self.assertEqual(self.rework(), [])

    def test_a_target_created_within_14_days_is_exempt(self):
        self.user_skill('brand-new', ['2026-09-28', '2026-09-30', '2026-10-01'])
        write_anomaly_with(self.home, 'brand-new-a', target='brand-new')
        self.assertEqual(self.rework(), [])

    def test_a_target_rewritten_within_14_days_after_a_quiet_spell_is_exempt(self):
        self.user_skill('reborn', [LONG_AGO, '2026-09-29', '2026-10-01', '2026-10-02'])
        write_anomaly_with(self.home, 'reborn-a', target='reborn')
        self.assertEqual(self.rework(), [])

    def test_the_grace_period_includes_its_first_day_and_not_the_day_before(self):
        self.user_skill('edge-in', ['2026-09-21', '2026-09-25', '2026-10-01'])
        self.user_skill('edge-out', ['2026-09-20', '2026-09-25', '2026-10-01'])
        write_anomaly_with(self.home, 'edge-in-a', target='edge-in')
        write_anomaly_with(self.home, 'edge-out-a', target='edge-out')
        self.assertEqual(self.rework(), ['## Needs rework', '- edge-out: 3 commits in 28 days'])

    def test_steady_patching_is_not_a_rewrite(self):
        self.user_skill('patched', ['2026-08-10', '2026-08-30', '2026-09-20', '2026-09-27', '2026-10-02'])
        write_anomaly_with(self.home, 'patched-a', target='patched')
        self.assertEqual(self.rework(), ['## Needs rework', '- patched: 3 commits in 28 days'])

    def test_a_path_target_resolves_to_the_repository_that_holds_it(self):
        repo = GitFixture(self.root / 'tools-repo')
        for number, day in enumerate(days('2026-08-01', '2026-09-12', '2026-09-20', '2026-10-01')):
            repo.write('bin/check.sh', f'v{number}\n')
            repo.commit(['bin/check.sh'], f'change {number}', day)
        target = str(repo.root / 'bin' / 'check.sh')
        write_anomaly_with(self.home, 'check-a', target=target)
        self.assertEqual(self.rework(), ['## Needs rework', f'- {target}: 3 commits in 28 days'])

    def test_a_relative_path_is_looked_up_under_the_user_config_folder(self):
        for number, day in enumerate(days('2026-08-01', '2026-09-12', '2026-09-20', '2026-10-01')):
            self.user.write('rules/style.md', f'v{number}\n')
            self.user.commit(['rules/style.md'], f'change {number}', day)
        write_anomaly_with(self.home, 'style-a', target='rules/style.md')
        self.assertEqual(self.rework(), ['## Needs rework', '- rules/style.md: 3 commits in 28 days'])

    def test_a_plugin_skill_resolves_to_the_plugin_repo_by_bare_and_qualified_name(self):
        plugin = self.plugin_checkout()
        self.skill_history('measure', [LONG_AGO, '2026-09-12', '2026-09-20', '2026-10-01'])
        write_anomaly_with(self.home, 'm-a', target='measure')
        write_anomaly_with(self.home, 'm-b', target='demo:measure')
        write_anomaly_with(self.home, 'm-c', target='other:measure')
        lines = flags.needs_rework(self.make(plugin_root=plugin))
        self.assertEqual(lines, ['## Needs rework', '- demo:measure: 3 commits in 28 days',
                                 '- measure: 3 commits in 28 days'])

    def test_an_installed_copy_uses_the_checkout_named_by_the_profile(self):
        self.plugin_checkout()
        self.skill_history('measure', [LONG_AGO, '2026-09-12', '2026-09-20', '2026-10-01'])
        installed = self.root / 'installed'
        write_text(installed / 'skills' / 'measure' / 'SKILL.md', '# measure\n')
        write_text(self.home / 'profile.md', f'---\nplugin_repo: {self.plugin}\n---\n')
        write_anomaly_with(self.home, 'm-a', target='measure')
        self.assertEqual(flags.needs_rework(self.make(plugin_root=installed)),
                         ['## Needs rework', '- measure: 3 commits in 28 days'])

    def test_three_open_or_reopened_problems_flag_a_target_that_has_no_repository(self):
        write_anomaly_with(self.home, 'a', target='the review step')
        write_anomaly_with(self.home, 'b', target='the review step', status='reopened')
        write_anomaly_with(self.home, 'c', target='the review step')
        write_anomaly_with(self.home, 'd', target='other step')
        self.assertEqual(self.rework(), ['## Needs rework', '- the review step: 3 open problems'])

    def test_the_open_problem_limit_is_its_own_number_not_the_commit_limit(self):
        write_anomaly_with(self.home, 'a', target='the review step')
        write_anomaly_with(self.home, 'b', target='the review step')
        with mock.patch.object(flags, 'REWORK_MIN_OPEN_PROBLEMS', 2):
            self.assertEqual(self.rework(), ['## Needs rework', '- the review step: 2 open problems'])
        with mock.patch.object(flags, 'CHURN_MIN_COMMITS', 2):
            self.assertEqual(self.rework(), [])

    def test_closed_anomalies_wins_and_blank_targets_are_not_open_problems(self):
        write_anomaly_with(self.home, 'a', target='step')
        write_anomaly_with(self.home, 'b', target='step', status='fixed')
        write_anomaly_with(self.home, 'c', target='step', kind='win', proposed_fix='')
        write_anomaly_with(self.home, 'd', target='step', status='wontfix')
        for signature in ('e', 'f', 'g'):
            write_anomaly_with(self.home, signature, target='')
        self.assertEqual(self.rework(), [])

    def test_commits_and_problems_are_both_named_and_the_worst_target_comes_first(self):
        self.user_skill('deploy', ['2026-08-01', '2026-09-12', '2026-09-20', '2026-10-01'])
        for signature in ('a', 'b', 'c'):
            write_anomaly_with(self.home, f'deploy-{signature}', target='deploy')
            write_anomaly_with(self.home, f'plain-{signature}', target='plain')
        self.assertEqual(self.rework(), ['## Needs rework', '- deploy: 3 commits in 28 days, 3 open problems',
                                         '- plain: 3 open problems'])

    def test_the_grace_period_exempts_only_the_commit_count_never_the_open_problems(self):
        self.user_skill('brand-new', ['2026-09-28', '2026-09-30', '2026-10-01'])
        for signature in ('a', 'b', 'c'):
            write_anomaly_with(self.home, signature, target='brand-new')
        self.assertEqual(self.rework(), ['## Needs rework', '- brand-new: 3 open problems'])

    def test_a_target_in_its_grace_period_with_too_few_problems_is_not_flagged(self):
        self.user_skill('brand-new', ['2026-09-28', '2026-09-30', '2026-10-01'])
        for signature in ('a', 'b'):
            write_anomaly_with(self.home, signature, target='brand-new')
        self.assertEqual(self.rework(), [])

    def test_a_run_ends_after_a_quiet_spell_longer_than_the_named_gap(self):
        self.assertEqual(constants.CHURN_RUN_GAP_DAYS, 28)
        self.assertEqual(flags.current_run_start(days('2026-07-01', '2026-07-29', '2026-09-26')),
                         date(2026, 9, 26))
        self.assertEqual(flags.current_run_start(days('2026-07-01', '2026-07-29', '2026-08-26')),
                         date(2026, 7, 1))

    def test_a_user_skill_in_a_git_ignored_config_folder_counts_only_problems(self):
        self.user.write('.gitignore', 'skills/\n')
        self.user.commit(['.gitignore'], 'ignore skills', date(2026, 9, 1))
        write_text(self.user.root / 'skills' / 'quiet' / 'SKILL.md', '# quiet\n')
        write_anomaly_with(self.home, 'a', target='quiet')
        self.assertEqual(self.rework(), [])

    def test_nothing_to_say_without_anomalies(self):
        self.assertEqual(self.rework(), [])


class TargetOwnersTest(FlagsCase):
    def test_an_absolute_path_is_taken_as_it_is(self):
        target = self.root / 'anywhere' / 'file.md'
        self.assertEqual(flags.target_path(self.context, str(target), None), target)

    def test_a_relative_path_is_looked_up_in_user_config_then_plugin_then_the_checkout_root(self):
        plugin = self.plugin_checkout()
        repo = (self.checkout.root, plugin)
        ctx = self.make(plugin_root=plugin)
        write_text(self.checkout.root / 'docs' / 'notes.md', 'x\n')
        self.assertEqual(flags.target_path(ctx, 'docs/notes.md', repo), self.checkout.root / 'docs' / 'notes.md')
        write_text(plugin / 'docs' / 'notes.md', 'x\n')
        self.assertEqual(flags.target_path(ctx, 'docs/notes.md', repo), plugin / 'docs' / 'notes.md')
        self.user.write('docs/notes.md', 'x\n')
        self.assertEqual(flags.target_path(ctx, 'docs/notes.md', repo), self.user.root / 'docs' / 'notes.md')
        self.assertIsNone(flags.target_path(ctx, 'docs/missing.md', repo))
        self.assertIsNone(flags.target_path(ctx, 'plugins/demo/docs/x.md', None))

    def test_the_plugin_name_matches_in_any_case(self):
        plugin = self.plugin_checkout()
        ctx = self.make(plugin_root=plugin)
        repo = (self.checkout.root, plugin)
        for qualifier in ('demo', 'Demo', 'DEMO'):
            self.assertTrue(flags.names_this_plugin(ctx, qualifier, repo), qualifier)
        self.assertFalse(flags.names_this_plugin(ctx, 'other', repo))

    def test_needs_rework_uses_both_rules(self):
        plugin = self.plugin_checkout()
        self.skill_history('measure', [LONG_AGO, '2026-09-12', '2026-09-20', '2026-10-01'])
        write_anomaly_with(self.home, 'm-a', target='Demo:measure')
        write_anomaly_with(self.home, 'm-b', target='plugins/demo/skills/measure/SKILL.md')
        self.assertEqual(flags.needs_rework(self.make(plugin_root=plugin)), [
            '## Needs rework', '- Demo:measure: 3 commits in 28 days',
            '- plugins/demo/skills/measure/SKILL.md: 3 commits in 28 days'])


class PluginRepoNoticeTest(FlagsCase):
    def test_the_notice_is_printed_once_when_the_plugin_has_skills_but_no_repository(self):
        write_text(self.root / 'plain' / 'skills' / 'measure' / 'SKILL.md', '# m\n')
        plain = self.make(plugin_root=self.root / 'plain')
        self.assertEqual(flags.plugin_repo_notice(plain), [gitrepo.PLUGIN_REPO_SKIPPED])
        self.assertEqual(flags.needs_rework(plain), [])
        self.assertEqual(flags.unused_skills(plain), [])

    def test_no_notice_with_a_repository_or_without_skills(self):
        plugin = self.plugin_checkout()
        self.assertEqual(flags.plugin_repo_notice(self.make(plugin_root=plugin)), [])
        self.assertEqual(flags.plugin_repo_notice(self.make(plugin_root=self.root / 'empty')), [])


class StaleTest(FlagsCase):
    def test_a_single_sighting_older_than_60_days_is_offered_as_wontfix(self):
        write_anomaly_with(self.home, 'old-one', last_seen='2026-08-04')
        write_anomaly_with(self.home, 'sixty-days', last_seen='2026-08-05')
        self.assertEqual(flags.stale(self.context), [
            '## Stale anomalies', '- old-one: seen once, last on 2026-08-04 (61 days ago); offer wontfix'])

    def test_only_open_or_reopened_problems_seen_once_are_stale(self):
        write_anomaly_with(self.home, 'twice', last_seen='2026-06-01', occurrences=2)
        write_anomaly_with(self.home, 'closed', last_seen='2026-06-01', status='fixed')
        write_anomaly_with(self.home, 'dropped', last_seen='2026-06-01', status='wontfix')
        write_anomaly_with(self.home, 'a-win', last_seen='2026-06-01', kind='win', proposed_fix='')
        write_anomaly_with(self.home, 'no-date', last_seen='')
        self.assertEqual(flags.stale(self.context), [])
        write_anomaly_with(self.home, 'back', last_seen='2026-06-01', status='reopened')
        self.assertEqual(flags.stale(self.make())[1:],
                         ['- back: seen once, last on 2026-06-01 (125 days ago); offer wontfix'])


class NearDuplicatesTest(FlagsCase):
    def test_same_target_and_category_are_listed_as_a_pair(self):
        write_anomaly_with(self.home, 'first-thing', target='deploy', category='rework')
        write_anomaly_with(self.home, 'other-words', target='deploy', category='rework')
        write_anomaly_with(self.home, 'another', target='deploy', category='navigation')
        self.assertEqual(flags.near_duplicates(self.context),
                         ['## Near-duplicates', '- first-thing, other-words: same target and category'])

    def test_same_target_and_category_with_unrelated_text_are_not_a_pair(self):
        write_anomaly_with(self.home, 'first-thing', target='deploy', category='rework',
                           summary='An agent ended its turn while its test run was still going.',
                           proposed_fix='Run the final gates in the foreground before reporting.')
        write_anomaly_with(self.home, 'other-words', target='deploy', category='rework',
                           summary='Interactive staging is refused, so hunks land in one commit.',
                           proposed_fix='Stage hunks from a patch with apply cached.')
        self.assertEqual(flags.near_duplicates(self.context), [])

    def test_same_target_and_category_pair_when_only_the_fix_text_overlaps(self):
        write_anomaly_with(self.home, 'first-thing', target='deploy', category='rework',
                           summary='An agent ended its turn while its test run was still going.',
                           proposed_fix='Run the final gates in the foreground before reporting back.')
        write_anomaly_with(self.home, 'other-words', target='deploy', category='rework',
                           summary='Interactive staging is refused, so hunks land in one commit.',
                           proposed_fix='Run the final gates in the foreground, then report.')
        self.assertEqual(flags.near_duplicates(self.context),
                         ['## Near-duplicates', '- first-thing, other-words: same target and category'])

    def test_blank_targets_do_not_match_each_other(self):
        write_anomaly_with(self.home, 'first-thing', category='rework')
        write_anomaly_with(self.home, 'other-words', category='rework')
        self.assertEqual(flags.near_duplicates(self.context), [])

    def test_signatures_that_share_enough_words_are_similar(self):
        write_anomaly_with(self.home, 'slow-check', category='rework')
        write_anomaly_with(self.home, 'slow-check-script', category='navigation')
        write_anomaly_with(self.home, 'permission-denied-git', category='rework')
        write_anomaly_with(self.home, 'permission-denied-npm', category='rework')
        self.assertEqual(flags.near_duplicates(self.context),
                         ['## Near-duplicates', '- slow-check, slow-check-script: similar signatures'])

    def test_both_reasons_are_named_and_closed_or_other_kind_records_are_left_out(self):
        write_anomaly_with(self.home, 'slow-check', target='ci', category='rework')
        write_anomaly_with(self.home, 'slow-check-script', target='ci', category='rework')
        write_anomaly_with(self.home, 'slow-check-run', target='ci', category='rework', status='fixed')
        write_anomaly_with(self.home, 'slow-check-win', target='ci', category='rework', kind='win',
                           proposed_fix='')
        self.assertEqual(flags.near_duplicates(self.context), [
            '## Near-duplicates', '- slow-check, slow-check-script: same target and category; similar signatures'])


    def test_three_records_about_one_target_are_one_group(self):
        for signature in ('aaa', 'bbb', 'ccc'):
            write_anomaly_with(self.home, signature, target='deploy', category='rework')
        write_anomaly_with(self.home, 'zzz', target='other', category='rework')
        self.assertEqual(flags.near_duplicates(self.context),
                         ['## Near-duplicates', '- aaa, bbb, ccc: same target and category'])

    def test_pairs_that_share_a_record_join_into_one_group_with_every_reason(self):
        write_anomaly_with(self.home, 'slow-check', target='ci', category='rework')
        write_anomaly_with(self.home, 'slow-check-script', target='other', category='navigation')
        write_anomaly_with(self.home, 'unrelated-words', target='ci', category='rework')
        self.assertEqual(flags.near_duplicates(self.context), [
            '## Near-duplicates',
            '- slow-check, slow-check-script, unrelated-words: same target and category; similar signatures'])

    def test_the_list_is_cut_after_five_groups_with_the_rest_counted(self):
        for number in range(7):
            for letter in 'ab':
                write_anomaly_with(self.home, f'g{number}-{letter}', target=f'target{number}', category='rework')
        lines = flags.near_duplicates(self.context)
        self.assertEqual(len(lines), 1 + constants.FLAGS_SHOW + 1)
        self.assertEqual(lines[-1], '- 2 more groups')


class LensRatesTest(FlagsCase):
    def add(self, session, lens, accepted, rejected, day='2026-10-01'):
        records.append_lens(self.home, records.lens_record(session, day, lens, accepted, rejected))

    def test_accept_rate_per_lens_over_all_lines_most_findings_first(self):
        """AC-70: the security lens gets its own rate line, like code and feature."""
        self.add('s1', 'code', 3, 1)
        self.add('s2', 'code', 4, 1)
        self.add('s3', 'security', 1, 1)
        self.add('s4', 'security', 1, 0)
        self.add('s4', 'feature', 2, 0)
        self.add('s5', 'quiet', 0, 0)
        self.assertEqual(flags.lens_rates(self.context), [
            '## Review lenses', '- code: 7 of 9 accepted (78%) in 2 sessions',
            '- security: 2 of 3 accepted (67%) in 2 sessions', '- feature: 2 of 2 accepted (100%) in 1 session'])

    def test_no_lens_lines_means_no_section(self):
        self.assertEqual(flags.lens_rates(self.context), [])

    def test_a_line_with_unusable_counts_is_skipped(self):
        self.add('s1', 'code-review', 1, 1)
        with open(self.home / 'lenses.jsonl', 'a', encoding='utf-8') as f:
            f.write('{"session_id":"s2","lens":"code-review","accepted":"many","rejected":1}\n')
            f.write('{"session_id":"s3","lens":"","accepted":1,"rejected":1}\n')
        self.assertEqual(flags.lens_rates(self.context),
                         ['## Review lenses', '- code-review: 1 of 2 accepted (50%) in 1 session'])


class UnusedSkillsTest(FlagsCase):
    OLD_LINE = '- demo:old: no use in 56 days (in the plugin since 2026-07-01); propose removal'

    def setUp(self):
        super().setUp()
        self.plugin = self.plugin_checkout(skills=('old', 'used', 'fresh'))
        self.skill_history('old', [LONG_AGO, '2026-07-15'])
        self.skill_history('used', [LONG_AGO])
        self.skill_history('fresh', ['2026-09-01'])
        self.rows = [metrics_row('s0', '2026-08-01'),
                     metrics_row('s1', '2026-09-20', skills_invoked={'demo:used': 1})]

    def unused(self, rows=None, **overrides):
        write_metrics_rows(self.home, self.rows if rows is None else rows)
        return flags.unused_skills(self.make(**{'plugin_root': self.plugin, **overrides}))

    def test_a_skill_with_no_use_in_56_days_is_proposed_and_young_or_used_ones_are_not(self):
        self.assertEqual(self.unused(), ['## Unused plugin skills', self.OLD_LINE])

    def test_a_slash_command_counts_as_a_use(self):
        rows = self.rows + [metrics_row('s2', '2026-09-21', slash_commands={'/demo:old': 1})]
        self.assertEqual(self.unused(rows), [])

    def test_the_window_is_56_days_ending_today_both_ends_included(self):
        before = self.rows + [metrics_row('s2', '2026-08-09', skills_invoked={'demo:old': 1})]
        self.assertEqual(self.unused(before), ['## Unused plugin skills', self.OLD_LINE])
        first_day = self.rows + [metrics_row('s2', '2026-08-10', skills_invoked={'demo:old': 1})]
        self.assertEqual(self.unused(first_day), [])

    def test_a_skill_needs_56_days_in_the_plugin_to_qualify(self):
        self.skill_history('edge', ['2026-08-10'])
        self.skill_history('late', ['2026-08-11'])
        listed = [line.split(':')[1] for line in self.unused() if line.startswith('- ')]
        self.assertEqual(listed, ['edge', 'old'])

    def test_a_bare_name_counts_as_a_use_unless_a_user_skill_has_that_name(self):
        rows = self.rows + [metrics_row('s2', '2026-09-21', slash_commands={'/old': 1})]
        self.assertEqual(self.unused(rows), [])
        write_text(self.user.root / 'skills' / 'old' / 'SKILL.md', '# a user skill\n')
        self.assertEqual(self.unused(rows), ['## Unused plugin skills', self.OLD_LINE])

    def test_a_skill_that_git_has_no_history_for_is_not_judged(self):
        write_text(self.plugin / 'skills' / 'uncommitted' / 'SKILL.md', '# u\n')
        self.assertEqual(self.unused(), ['## Unused plugin skills', self.OLD_LINE])

    def test_a_win_with_two_sightings_protects_the_skill_from_being_proposed(self):
        write_anomaly_with(self.home, 'old-works', kind='win', proposed_fix='', target='demo:old', occurrences=2)
        self.assertEqual(self.unused()[1:], [
            '- demo:old: no use in 56 days (in the plugin since 2026-07-01); '
            'not proposed: a win with 2 sightings protects it unless you override'])

    def test_a_win_seen_once_or_about_another_target_does_not_protect(self):
        write_anomaly_with(self.home, 'once', kind='win', proposed_fix='', target='demo:old')
        write_anomaly_with(self.home, 'else', kind='win', proposed_fix='', target='other', occurrences=3)
        self.assertEqual(self.unused()[1:], [self.OLD_LINE])

    def test_nothing_is_judged_without_measured_sessions_covering_the_window(self):
        self.assertEqual(self.unused([]), ['## Unused plugin skills',
                                           '- not checked: no measured sessions in the last 56 days'])
        late = [metrics_row('s1', '2026-09-20')]
        self.assertEqual(self.unused(late), [
            '## Unused plugin skills',
            '- not checked: measured sessions start on 2026-09-20, after the 56-day window began (2026-08-10)'])

    def test_the_plugin_name_falls_back_to_the_folder_name_without_a_manifest(self):
        (self.plugin / '.claude-plugin' / 'plugin.json').unlink()
        self.assertEqual(self.unused(), ['## Unused plugin skills', self.OLD_LINE])

    def test_no_plugin_repository_means_no_section(self):
        self.assertEqual(self.unused(plugin_root=self.root / 'nowhere'), [])


class RepeatedActionsTest(FlagsCase):
    def rows(self, field, *per_session, start=29):
        return [metrics_row(f's{n}', f'2026-09-{start + n:02d}', **{field: counts})
                for n, counts in enumerate(per_session)]

    def repeated(self, rows=(), prompts=None, **overrides):
        write_metrics_rows(self.home, rows)
        if prompts is not None:
            write_text(self.context.data / 'cache' / 'prompts.jsonl',
                       ''.join(json.dumps(p) + '\n' for p in prompts))
        return repeats.repeated_actions(self.make(**overrides))

    def said(self, *lines):
        return [{'session_id': s, 'ts': f'{day}T09:00:00.000Z', 'text': text} for s, day, text in lines]

    def test_a_command_shape_seen_3_times_in_2_sessions_is_a_candidate_for_a_script(self):
        rows = self.rows('bash_shapes', {'npm test': 2, 'git status': 3}, {'npm test': 1, 'git log -n': 2})
        lines = self.repeated(rows, prompts=[])
        self.assertEqual(len(lines), 2, lines)
        self.assertEqual(lines[0], '## Repeated actions')
        self.assertTrue(lines[1].startswith('- command shape "npm test": 3 times in 2 sessions; '
                                            'lightest form: script, because'), lines)

    def test_read_only_shapes_are_skipped(self):
        reads = {shape: 3 for shape in ('sed -n <str>', 'grep <str> src/<path>', 'cat src/<path>', 'head -n',
                                        'tail -n', 'ls -la', 'git log -n', 'git show <id>', 'git diff --stat',
                                        'git status')}
        self.assertEqual(self.repeated(self.rows('bash_shapes', reads, reads), prompts=[]), [])
        kept = {'git commit -m': 3, 'sed -i <str>': 3, 'lsof -i': 3, 'catalog run': 3}
        lines = self.repeated(self.rows('bash_shapes', kept, kept), prompts=[])
        self.assertEqual(len(lines), 5, lines)

    def test_a_shape_that_only_sets_a_shell_variable_is_skipped(self):
        noise = {'S=<str>': 3, 'B=<str> branch)': 3}
        self.assertEqual(self.repeated(self.rows('bash_shapes', noise, noise), prompts=[]), [])
        kept = {'TK=<str> npm test': 3}
        lines = self.repeated(self.rows('bash_shapes', kept, kept), prompts=[])
        self.assertEqual(len(lines), 2, lines)

    def test_command_shapes_are_ranked_by_sessions_then_times(self):
        first = {'many sessions': 1, 'few sessions': 10, 'mid sessions': 2}
        second = {'many sessions': 1, 'few sessions': 10, 'mid sessions': 2}
        third = {'many sessions': 1, 'mid sessions': 2}
        lines = self.repeated(self.rows('bash_shapes', first, second, third, start=26), prompts=[])
        self.assertEqual([line.split('"')[1] for line in lines[1:]],
                         ['mid sessions', 'many sessions', 'few sessions'])

    def test_each_threshold_is_checked_on_its_own(self):
        rows = self.rows('bash_shapes', {'one session': 3}, {'few': 1}, {'few': 1})
        self.assertEqual(self.repeated(rows, prompts=[]), [])

    def test_the_window_is_14_days_ending_today_both_ends_included(self):
        inside = [metrics_row('s1', '2026-09-21', bash_shapes={'x y': 2}),
                  metrics_row('s2', '2026-10-04', bash_shapes={'x y': 1})]
        outside = [metrics_row('s1', '2026-09-20', bash_shapes={'x y': 2}),
                   metrics_row('s2', '2026-10-04', bash_shapes={'x y': 1})]
        self.assertEqual(len(self.repeated(inside, prompts=[])), 2)
        self.assertEqual(self.repeated(outside, prompts=[]), [])

    def test_days_are_taken_in_the_clock_of_the_context(self):
        late = metrics_row('s1', '2026-09-20', first_ts='2026-09-20T23:30:00.000Z', bash_shapes={'x y': 2})
        rows = [late, metrics_row('s2', '2026-10-04', bash_shapes={'x y': 1})]
        east = datetime(2026, 10, 4, 12, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(self.repeated(rows, prompts=[]), [])
        self.assertEqual(len(self.repeated(rows, prompts=[], now=east)), 2)

    def test_tool_trigrams_and_slash_commands_are_counted_and_rows_without_trigrams_are_skipped(self):
        rows = self.rows('tool_trigrams', {'Read>Edit>Bash': 2}, {'Read>Edit>Bash': 1}, {})
        both = {'/review': 1, '/reload-plugins': 3, '/other:thing': 1}
        rows += self.rows('slash_commands', both, {'/review': 2, '/other:thing': 2, '/reload-plugins': 1}, start=26)
        write_text(self.user.root / 'skills' / 'review' / 'SKILL.md', '# review\n')
        lines = self.repeated(rows, prompts=[])
        self.assertEqual(len(lines), 4, lines)
        text = '\n'.join(lines)
        self.assertIn('- tool trigram "Read > Edit > Bash": 3 times in 2 sessions; '
                      'lightest form: hook or lint rule, because', text)
        self.assertIn('- slash command "/review": 3 times in 2 sessions; lightest form: pointer, because', text)
        self.assertIn('- slash command "/other:thing": 3 times in 2 sessions;', text)
        self.assertNotIn('reload-plugins', text)

    def test_a_trigram_of_one_repeated_tool_is_a_loop_not_a_sequence(self):
        rows = self.rows('tool_trigrams', {'Read>Read>Read': 5}, {'Read>Read>Read': 5})
        self.assertEqual(self.repeated(rows, prompts=[]), [])

    def test_normalized_prompts_from_the_prompt_cache(self):
        prompts = self.said(('s1', '2026-09-30', 'Run the tests, and fix failures!'),
                            ('s1', '2026-10-01', 'run  the tests and FIX failures'),
                            ('s2', '2026-10-02', 'Run the tests and fix failures.'),
                            ('s2', '2026-10-02', 'fix ticket 12 in the parser module and update its changelog'),
                            ('s3', '2026-10-03', 'fix ticket 15 in the parser module and update its changelog'),
                            ('s3', '2026-10-03', 'fix ticket 99 in the parser module and update its changelog'))
        lines = self.repeated(prompts=prompts)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[0], '## Repeated actions')
        self.assertTrue(lines[1].startswith('- prompt "fix ticket <id> in the parser module and update its '
                                            'changelog": 3 times in 2 sessions; lightest form: skill, because'), lines)
        self.assertTrue(lines[2].startswith('- prompt "run the tests and fix failures": 3 times in 2 sessions; '
                                            'lightest form: pointer, because'), lines)

    def test_prompts_outside_the_window_too_short_or_a_slash_command_are_not_counted(self):
        command = '<command-message>review</command-message><command-name> /review </command-name> now'
        prompts = self.said(*[(s, day, text) for s in ('s1', 's2', 's3') for day, text in
                              (('2026-09-20', 'run the full check now'), ('2026-10-01', 'yes please'),
                               ('2026-10-01', command))])
        self.assertEqual(self.repeated(prompts=prompts), [])

    def test_prompts_that_start_with_markup_are_not_counted(self):
        texts = ('<command-message>tidy-up</command-message> please tidy the whole repository now',
                 '<system-reminder> The date has changed, today is a new day </system-reminder>')
        prompts = self.said(*[(s, '2026-10-01', text) for s in ('s1', 's2', 's3') for text in texts])
        self.assertEqual(self.repeated(prompts=prompts), [])

    def test_a_long_prompt_is_cut_when_printed_but_still_chosen_a_skill(self):
        long_text = ' '.join(f'word{n}x' for n in range(30))
        prompts = self.said(*[(s, '2026-10-01', long_text) for s in ('s1', 's2', 's3')])
        lines = self.repeated(prompts=prompts)
        shown = lines[1].split('"')[1]
        self.assertEqual(len(shown), constants.PROMPT_SHOW_CHARS)
        self.assertTrue(shown.endswith('…'))
        self.assertIn('lightest form: skill', lines[1])

    def test_without_a_data_folder_prompts_are_skipped_with_a_note_when_there_is_something_else_to_say(self):
        rows = self.rows('bash_shapes', {'npm test': 2}, {'npm test': 1})
        lines = self.repeated(rows, data=None)
        self.assertEqual(len(lines), 3, lines)
        self.assertEqual(lines[-1], '- prompts not checked: no data folder, so no prompt cache')

    def test_without_a_data_folder_and_nothing_repeated_the_section_is_left_out(self):
        self.assertEqual(self.repeated(data=None), [])

    def test_a_missing_prompt_cache_is_an_empty_one(self):
        self.assertEqual(self.repeated(), [])

    def test_each_list_is_cut_after_five_lines_with_the_rest_counted(self):
        shapes = {f'tool{n} run': 3 for n in range(7)}
        lines = self.repeated(self.rows('bash_shapes', shapes, shapes), prompts=[])
        self.assertEqual(len(lines), 1 + constants.FLAGS_SHOW + 1)
        self.assertEqual(lines[-1], '- 2 more command shapes')

    def test_the_lightest_form_follows_the_kind_of_action(self):
        self.assertEqual(repeats.lightest_form('command shape', 'npm test')[0], 'script')
        self.assertEqual(repeats.lightest_form('tool trigram', 'Read > Edit > Bash')[0], 'hook or lint rule')
        self.assertEqual(repeats.lightest_form('slash command', '/review')[0], 'pointer')
        self.assertEqual(repeats.lightest_form('prompt', 'run the tests now please')[0], 'pointer')
        self.assertEqual(repeats.lightest_form('prompt', 'one two three four five six seven eight nine')[0], 'skill')
        for kind in ('command shape', 'tool trigram', 'slash command', 'prompt'):
            self.assertTrue(repeats.lightest_form(kind, 'a b c')[1])


class DigestWiringTest(FlagsCase):
    def test_the_sections_are_registered_in_order_and_resolve_to_functions(self):
        names = [name for module, name in digest.SECTIONS if module in ('flags', 'repeats')]
        self.assertEqual(names, ['plugin_repo_notice', 'needs_rework', 'repeated_actions', 'stale',
                                 'near_duplicates', 'lens_rates', 'unused_skills'])
        self.assertTrue(all(callable(section) for section in digest.section_functions()))

    def test_the_digest_command_prints_the_flag_sections(self):
        write_anomaly_with(self.home, 'old-one', last_seen='2026-08-04')
        records.append_lens(self.home, records.lens_record('s1', '2026-10-01', 'code-review', 1, 1))
        code, out, err = run_cli('digest', '--home', str(self.home), '--user-config', str(self.root / 'uc'),
                                 '--plugin-root', str(self.root / 'plug'))
        self.assertEqual((code, err), (0, ''))
        for heading in ('## Stale anomalies', '## Review lenses'):
            self.assertIn(heading, out)
        self.assertNotIn('## Repeated actions', out)


class ToolTrigramsTest(test_metrics.Base):
    def uses(self, names, prefix='t', start=0):
        return [assistant(ts(start + i), f'{prefix}m{i}', tools=[(f'{prefix}{i}', name, {})])
                for i, name in enumerate(names)]

    def test_counts_consecutive_tool_triples_in_use_order_most_frequent_first(self):
        self.session(self.uses(['Read', 'Edit', 'Bash', 'Read', 'Edit', 'Bash']))
        row, _ = self.summarize()
        self.assertEqual(list(row['tool_trigrams'].items()),
                         [('Read>Edit>Bash', 2), ('Edit>Bash>Read', 1), ('Bash>Read>Edit', 1)])

    def test_fewer_than_three_tool_uses_give_no_trigram(self):
        self.session(self.uses(['Read', 'Edit']))
        row, _ = self.summarize()
        self.assertEqual(row['tool_trigrams'], {})

    def test_a_trigram_never_spans_two_transcripts(self):
        self.session(self.uses(['Read', 'Edit']))
        self.subagent('agent-1', self.uses(['Bash', 'Grep', 'Read'], prefix='s'))
        self.subagent('agent-2', self.uses(['Grep'], prefix='u'))
        row, _ = self.summarize()
        self.assertEqual(row['tool_trigrams'], {'Bash>Grep>Read': 1})

    def test_the_subagent_trigrams_add_to_the_main_ones(self):
        self.session(self.uses(['Read', 'Edit', 'Bash']))
        self.subagent('agent-1', self.uses(['Read', 'Edit', 'Bash'], prefix='s'))
        row, _ = self.summarize()
        self.assertEqual(row['tool_trigrams'], {'Read>Edit>Bash': 2})

    def test_a_repeated_tool_use_entry_is_counted_once(self):
        entries = self.uses(['Read', 'Edit', 'Bash'])
        self.session(entries + [entries[0]])
        row, _ = self.summarize()
        self.assertEqual(row['tool_trigrams'], {'Read>Edit>Bash': 1})

    def test_trigrams_are_capped_to_the_most_frequent(self):
        names = ['Read', 'Edit'] * 3 + [f'Tool{i}' for i in range(40)]
        self.session(self.uses(names))
        row, _ = self.summarize()
        self.assertEqual(len(row['tool_trigrams']), metrics.MAX_TRIGRAMS)
        self.assertEqual(list(row['tool_trigrams'].items())[:2], [('Read>Edit>Read', 2), ('Edit>Read>Edit', 2)])


if __name__ == '__main__':
    unittest.main()

import contextlib
import io
import json
import os
import re
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from anomaly_loop import cli, constants, frontmatter, gitrepo, lens, paths, records
from tests.fixtures import NOW, PLUGIN, SID, assistant, run_cli, ts, user, write_jsonl
from tests.test_pipeline_files import ALLOWED_TOOLS_SKILLS

FULL_PROFILE = """---
tracker: local markdown files
glossary_file: CONTEXT.md
ticket_key: PRJ\\d+
branch_pattern: <type>/<key>/<slug>
commit_style: <type>(<key>): <summary>
implementers:
  stack-a: agent-one
mr_tool: some-skill
verify_ui: some-checker
issue_source: a tracker
---
"""


class RegistryTest(unittest.TestCase):
    def test_every_command_module_resolves_and_registers_its_subcommand(self):
        self.assertEqual(len(cli.COMMANDS), len(set(cli.COMMANDS)))
        parser = cli.build_parser()
        for name in ('measure', 'index', 'digest'):
            self.assertTrue(callable(parser.parse_args([name]).handler))


class SkillFileTest(unittest.TestCase):
    SKILL_MAX_BYTES = 8 * 1024    # a pipeline skill's SKILL.md; the four loop skills are out of this check
    AGENT_MAX_BYTES = 6 * 1024
    RULES_DOC_MAX_BYTES = 2 * 1024   # the rules-mode doc of the feature agent, loaded only in that mode
    RULES_DOC = PLUGIN / 'skills' / 'review' / 'rules-mode.md'
    REVIEW_BRIEF_MAX_BYTES = 3 * 1024   # the review skill's reviewer brief doc, loaded at dispatch; its last section is for the main window after each round (AC-53)
    REVIEW_SKILL = PLUGIN / 'skills' / 'review' / 'SKILL.md'
    REVIEW_BRIEF = PLUGIN / 'skills' / 'review' / 'BRIEFS.md'
    BUILD_SKILL = PLUGIN / 'skills' / 'build' / 'SKILL.md'
    BUILD_UI_DOC = BUILD_SKILL.parent / 'UI-CHECK.md'
    BUILD_DOCS = {   # the build skill's extra docs, each loaded only when used (AC-42), and their budgets
        'BRIEFS.md': 3 * 1024,        # the implementer brief, loaded at dispatch
        'TEST-WRITER.md': 2 * 1024,   # the test-writer brief, loaded at dispatch
        'WORKTREE.md': 2 * 1024,      # the commit recipe, loaded only inside a worktree
        BUILD_UI_DOC.name: 3 * 1024,  # the UI walkthrough, loaded only when Verify step 4 runs
    }

    def skills(self):
        return sorted((PLUGIN / 'skills').glob('*/SKILL.md'))

    def agents(self):
        """Every Markdown file under agents/, at any depth: Claude Code loads each one as an agent."""
        return sorted((PLUGIN / 'agents').rglob('*.md'))

    def test_the_skills_are_exactly_the_four_loop_skills_and_the_pipeline_skills(self):
        self.assertEqual({path.parent.name for path in self.skills()}, {*constants.LOOP_SKILLS, *ALLOWED_TOOLS_SKILLS})

    def test_every_skill_and_agent_description_fits_in_250_characters(self):
        for path in self.skills() + self.agents():
            description = frontmatter.split(path.read_text(encoding='utf-8'))[0].get('description', '')
            with self.subTest(file=path.relative_to(PLUGIN).as_posix()):
                self.assertTrue(description)
                self.assertLessEqual(len(description), 250)

    def test_every_pipeline_skill_fits_in_8_KB_and_every_agent_in_6_KB(self):
        for path in self.skills():
            if path.parent.name not in constants.LOOP_SKILLS:
                with self.subTest(skill=path.parent.name):
                    self.assertLessEqual(path.stat().st_size, self.SKILL_MAX_BYTES)
        for path in self.agents():
            with self.subTest(agent=path.stem):
                self.assertLessEqual(path.stat().st_size, self.AGENT_MAX_BYTES)

    def test_the_agents_are_the_core_reviewers_and_the_plan_reviewer_read_only_and_with_no_pinned_model(self):
        self.assertEqual(sorted(path.stem for path in self.agents()), sorted((*lens.core_lenses(), 'plan')))   # plan: the plan-gate reviewer, outside the core lenses
        for path in self.agents():
            fields = frontmatter.split(path.read_text(encoding='utf-8'))[0]
            with self.subTest(agent=path.stem):
                self.assertEqual(fields.get('name'), path.stem)
                self.assertEqual([tool.strip() for tool in fields.get('tools', '').split(',')],
                                 ['Read', 'Grep', 'Glob', 'Bash'])
                self.assertNotIn('model', fields)

    def test_the_rules_mode_doc_fits_in_2_KB_and_only_the_feature_agent_loads_it(self):
        self.assertLessEqual(self.RULES_DOC.stat().st_size, self.RULES_DOC_MAX_BYTES)
        loaders = [path.stem for path in self.agents() if 'skills/review/rules-mode.md' in path.read_text(encoding='utf-8')]
        self.assertEqual(loaders, ['feature'])

    def review_text(self):
        """The review skill's SKILL.md and its brief doc, as one text; fails while either is missing."""
        for path in (self.REVIEW_SKILL, self.REVIEW_BRIEF):
            self.assertTrue(path.is_file(), path.relative_to(PLUGIN).as_posix())
        return '\n'.join(path.read_text(encoding='utf-8') for path in (self.REVIEW_SKILL, self.REVIEW_BRIEF))

    def test_the_review_skill_is_model_invocable_and_its_description_names_build_and_conduct(self):
        """AC-43 (the 250-character limit is the all-skills check above)."""
        self.assertTrue(self.REVIEW_SKILL.is_file())
        fields = frontmatter.split(self.REVIEW_SKILL.read_text(encoding='utf-8'))[0]
        self.assertNotIn('disable-model-invocation', fields)
        for caller in ('build', 'conduct', 'the user may'):
            self.assertIn(caller, fields.get('description', ''))

    def test_the_review_brief_doc_fits_in_3_KB_and_the_skill_links_it(self):
        """AC-53: the brief doc is loaded at dispatch, so SKILL.md names it (the 8 KB SKILL.md limit is the
        all-skills check above)."""
        self.review_text()
        self.assertLessEqual(self.REVIEW_BRIEF.stat().st_size, self.REVIEW_BRIEF_MAX_BYTES)
        self.assertIn(self.REVIEW_BRIEF.name, self.REVIEW_SKILL.read_text(encoding='utf-8'))

    def test_the_review_skill_has_a_dispatch_row_or_heading_for_each_of_the_five_modes(self):
        """AC-45: ticket, delta, cumulative, combined and rules."""
        text = self.review_text()
        for mode in constants.REVIEW_MODES:
            with self.subTest(mode=mode):
                self.assertRegex(text, re.compile(rf'^(?:\|\s*|#+\s*)`?{mode}`?\b', re.M))

    def test_every_delta_and_conflict_merge_round_starts_its_worklog_before_the_dispatch(self):
        """Dogfood AC-11: `worklog add` consumes the start, so a later round's add had none to read."""
        text = self.REVIEW_SKILL.read_text(encoding='utf-8')
        section = text.split('## Delta rounds', 1)[1].split('\n## ', 1)[0]
        self.assertIn('worklog start', section)

    def test_cumulative_mode_reads_spec_md_else_stories_md_and_decisions_md(self):
        """AC-85."""
        text = self.review_text()
        for name in ('spec.md', 'stories.md', 'decisions.md'):
            self.assertIn(name, text)

    def build_text(self):
        """The build skill's SKILL.md text; fails while it is missing."""
        self.assertTrue(self.BUILD_SKILL.is_file(), self.BUILD_SKILL.relative_to(PLUGIN).as_posix())
        return self.BUILD_SKILL.read_text(encoding='utf-8')

    def test_the_build_skill_is_model_invocable_and_its_description_names_conduct_and_an_explicit_request(self):
        """AC-29 (the 250-character limit is the all-skills check above)."""
        fields = frontmatter.split(self.build_text())[0]
        self.assertNotIn('disable-model-invocation', fields)
        description = fields.get('description', '')
        self.assertIn('conduct', description)
        self.assertIn('explicit', description.lower())
        self.assertIn('model-invocable', description.lower())

    def test_the_build_skill_links_each_doc_within_its_budget(self):
        """AC-42: each doc is loaded only when used, so SKILL.md names it (the 8 KB SKILL.md limit is the
        all-skills check above)."""
        text = self.build_text()
        for name, max_bytes in self.BUILD_DOCS.items():
            with self.subTest(doc=name):
                path = self.BUILD_SKILL.parent / name
                self.assertTrue(path.is_file(), f'skills/build/{name} is missing')
                self.assertLessEqual(path.stat().st_size, max_bytes)
                self.assertIn(name, text)

    def test_the_build_skill_carries_the_light_path_call_and_the_resume_check(self):
        """AC-39 (the `ticket adhoc` call) and AC-31 (the first-parent log check)."""
        text = self.build_text()
        self.assertIn(f'{constants.CLI_COMMAND} ticket adhoc', text)
        self.assertIn('--first-parent', text)

    def test_the_ui_doc_covers_the_walkthrough_items_that_can_be_checked(self):
        """AC-41: hidden-pane values marked "not meaningful", `diff.md` for a no-visual-change ticket, images copied with `cp`."""
        text = self.BUILD_UI_DOC.read_text(encoding='utf-8')
        self.assertIn('not meaningful', text)
        self.assertIn('diff.md', text)
        self.assertRegex(text, r'(?<![\w-])cp(?![\w-])')

    def test_ticket_mode_runs_a_rules_pass_on_a_brief_and_skill_pair_the_tests_line_names(self):
        """Rule-trace ticket AC-1: the trigger lives in review, so `build` SKILL.md stays unchanged (AC-2)."""
        text = self.REVIEW_SKILL.read_text(encoding='utf-8')
        # The trigger: a ticket's `Tests:` line naming `rule trace <brief path> <SKILL.md path>`.
        trigger = re.search(r'Tests:[^\n]{0,200}rule trace|rule trace[^\n]{0,200}Tests:', text, re.I)
        self.assertIsNotNone(trigger, 'no ticket-mode trigger on a `Tests:` line naming a rule trace')
        around = text[text.rfind('\n', 0, trigger.start()) + 1:].split('\n', 1)[0].lower()  # the trigger's own line
        self.assertIn('ticket', around)
        self.assertIn('combined', around)
        self.assertIn('rules mode', around)     # the extra pass is a rules-mode pass ...
        self.assertIn('anomaly:feature', around)  # ... by the feature agent
        self.assertIn('brief', around)       # on the brief ...
        self.assertIn('skill.md', around)    # ... and SKILL.md pair
        step7 = next(line for line in text.split('\n') if line.startswith('7. '))
        self.assertIn('rules pass', step7)   # `ticket reviewed` waits for the rules pass too
        self.assertNotIn('rule trace', self.build_text().lower())

    def test_a_delta_round_on_a_rule_trace_ticket_reruns_the_rules_pass_on_the_fixed_skill(self):
        """Rule-trace ticket AC-1: rules mode has no diff range, so the re-run is review's answer to a delta request."""
        text = self.REVIEW_SKILL.read_text(encoding='utf-8')
        section = text.split('## Delta rounds', 1)[1].split('\n## ', 1)[0].lower()
        self.assertIn('rule trace', section)
        self.assertIn('rules', section)
        self.assertRegex(section, r'fixed|again|re-?run')

    def test_the_readme_review_section_names_the_rule_trace_pass(self):
        """Rule-trace ticket AC-1."""
        readme = PLUGIN.parent.parent / 'README.md'
        if not readme.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        text = readme.read_text(encoding='utf-8')
        section = text.split('## The review skill', 1)[1].split('\n## ', 1)[0].lower()
        self.assertIn('rule trace', section)
        self.assertIn('rules', section)


class ReadmeTest(unittest.TestCase):
    README = PLUGIN.parent.parent / 'README.md'

    def help_names(self, *argv):
        """The names listed under a help text's positional arguments (the commands or the actions)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main([*argv, '--help'], environ={})
        if 'positional arguments:' not in out.getvalue():
            return []
        section = out.getvalue().split('positional arguments:', 1)[1].split('\noptions:', 1)[0]
        return re.findall(r'^ {4}([\w-]+)(?:\s|$)', section, re.M)

    def gaps(self, text):
        """The command groups and `<group> <action>` pairs of the help that `text` does not name."""
        groups = self.help_names()
        self.assertTrue(groups, 'no command group read from the help')
        missing = []
        for group in groups:
            if not re.search(rf'(?:anomaly\.py\s+|`){re.escape(group)}(?![\w-])', text):
                missing.append(group)
            for action in self.help_names(group):
                if not re.search(rf'(?<![\w-]){re.escape(group)}\s+(?:[\w-]+\|)*{re.escape(action)}(?![\w-])', text):
                    missing.append(f'{group} {action}')
        return missing

    def test_the_help_lists_the_groups_and_the_actions_of_a_group(self):
        self.assertIn('calibrate', self.help_names())
        self.assertIn('declare', self.help_names('calibrate'))
        self.assertEqual(self.help_names('measure'), [])

    def test_the_readme_names_every_command_group_and_every_group_action_of_the_help(self):
        if not self.README.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        self.assertEqual(self.gaps(self.README.read_text(encoding='utf-8')), [])

    def test_a_readme_that_misses_a_group_or_an_action_is_reported(self):
        text = ('anomaly.py measure\nanomaly.py index\nanomaly.py digest\nanomaly.py observe list\n'
                'anomaly.py assess check|record\nanomaly.py nudge\n')
        missing = self.gaps(text)
        self.assertLessEqual({'observe apply', 'calibrate', 'calibrate plan', 'calibrate merge'}, set(missing))
        self.assertNotIn('measure', missing)
        self.assertNotIn('observe list', missing)
        self.assertNotIn('assess record', missing)


class ErrorContractTest(unittest.TestCase):
    def test_path_record_file_and_git_errors_print_one_anomaly_line_and_exit_2(self):
        for error in (paths.PathError('no folder'), records.RecordError('bad record'), OSError('disk full'),
                      gitrepo.GitError('git commit failed')):
            def failing(args, environ, error=error):
                raise error

            def register(commands, common, failing=failing):
                commands.add_parser('fake', parents=[common]).set_defaults(handler=failing)
            fake = types.SimpleNamespace(register=register)
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(cli, 'command_modules', return_value=[fake]):
                code, out, err = run_cli('fake')
                self.assertEqual((code, out), (2, ''))
                self.assertEqual(err, f'anomaly: {error}\n')

    def test_a_usage_error_prints_one_anomaly_line_and_exits_2(self):
        for argv in ([], ['no-such-command'], ['observe', 'apply'], ['calibrate', 'decide', '--signature', 'x',
                                                                     '--result', 'maybe'], ['index', '--nope']):
            with self.subTest(argv=argv):
                code, out, err = run_cli(*argv)
                self.assertEqual((code, out), (2, ''))
                self.assertTrue(err.startswith('anomaly: '), err)
                self.assertEqual(len(err.splitlines()), 1, err)

    def test_help_still_prints_the_usage_and_exits_0(self):
        with self.assertRaises(SystemExit) as raised:
            run_cli('--help')
        self.assertEqual(raised.exception.code, 0)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.data = self.root / 'data'
        self.projects = self.root / 'projects'
        write_jsonl(self.projects / 'C--Work-demo' / f'{SID}.jsonl', [
            user(ts(0), 'hello'),
            assistant(ts(1), 'm1', out=10, branch='feat/PRJ42/x-ABC-12'),
            assistant(ts(2, day=3), 'm2', out=10, branch='feat/PRJ42/x-ABC-12'),
        ])

    def measure(self, *extra, environ=None, now=NOW):
        return run_cli('measure', '--home', str(self.home), '--data', str(self.data),
                            '--projects', str(self.projects), *extra, environ=environ, now=now)

    def rows(self):
        return [json.loads(line) for line in (self.home / 'metrics.jsonl').read_text(encoding='utf-8').splitlines()]

    def test_durable_output_goes_to_home_and_throwaway_state_to_data(self):
        code, _, _ = self.measure()
        self.assertEqual(code, 0)
        self.assertTrue((self.home / 'metrics.jsonl').is_file())
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ['metrics.jsonl'])
        self.assertTrue((self.data / 'measure-state.json').is_file())
        self.assertTrue((self.data / 'cache' / 'prompts.jsonl').is_file())

    def test_summary_shows_rows_date_range_and_weighted_total(self):
        _, out, _ = self.measure()
        self.assertIn('rows 1', out)
        self.assertIn('2026-10-01 to 2026-10-03', out)
        expected = 2 * (100 * 1 + 50 * 1.25 + 1000 * 0.1) + 20 * 5
        self.assertIn(f'weighted tokens: {expected:,.0f}', out)

    def test_summary_shows_subagent_seconds_by_type_summed_over_rows_largest_first_after_weighted_tokens(self):
        second = '11111111-aaaa-bbbb-cccc-000000000002'
        write_jsonl(self.projects / 'C--Work-demo' / f'{second}.jsonl', [user(ts(0), 'again'), assistant(ts(1), 'm9')])
        for sid, spawns in ((SID, {'agent-a1': ('Explore', 40, 'sonnet'), 'agent-a2': ('general-purpose', 10, 'opus')}),
                            (second, {'agent-b1': ('Explore', 20, 'sonnet'), 'agent-b2': ('Plan', 90, 'haiku')})):
            for name, (agent_type, seconds, model) in spawns.items():
                base = self.projects / 'C--Work-demo' / sid / 'subagents'
                write_jsonl(base / f'{name}.jsonl', [assistant(ts(10), name + 'x'), assistant(ts(10 + seconds // 60, seconds % 60), name + 'y')])
                (base / f'{name}.meta.json').write_text(json.dumps({'agentType': agent_type, 'model': model}),
                                                        encoding='utf-8')
        _, out, _ = self.measure()
        lines = out.splitlines()
        weighted = next(i for i, line in enumerate(lines) if line.startswith('weighted tokens:'))
        self.assertEqual(lines[weighted + 1], 'subagent seconds: Plan 90, Explore 60, general-purpose 10')
        # AC-8: the same sum by model, on the next line, largest first
        self.assertEqual(lines[weighted + 2], 'subagent seconds by model: haiku 90, sonnet 60, opus 10')

        # a row written before the seconds existed sits next to one that has them; a tie is by name
        rows = self.rows()
        for row in rows:
            if row['session_id'] == second:
                row['subagents'].pop('seconds_by_type')
                row['subagents'].pop('seconds_by_model')
            else:
                row['subagents']['seconds_by_model'] = {'sonnet': 30, 'opus': 30, 'haiku': 20}
        (self.home / 'metrics.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        _, out, _ = self.measure()
        self.assertIn('skipped 2', out)
        self.assertIn('subagent seconds: Explore 40, general-purpose 10\n', out)
        self.assertIn('subagent seconds by model: opus 30, sonnet 30, haiku 20\n', out)

    def test_a_hand_edited_non_number_seconds_or_weighted_value_is_left_out_and_measure_still_runs(self):
        base = self.projects / 'C--Work-demo' / SID / 'subagents'
        write_jsonl(base / 'agent-a1.jsonl', [assistant(ts(10), 'a'), assistant(ts(10, 30), 'b')])
        (base / 'agent-a1.meta.json').write_text(json.dumps({'agentType': 'Explore'}), encoding='utf-8')
        self.measure()
        rows = self.rows()
        rows[0]['subagents']['seconds_by_type'].update({'Plan': 'x', 'Bad': None, 'Nan': float('nan'), 'Inf': float('inf'), 'Half': 2.5})
        rows[0]['weighted'] = 'x'
        (self.home / 'metrics.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
        code, out, _ = self.measure()
        self.assertEqual(code, 0)
        self.assertIn('subagent seconds: Explore 30, Half 2.5\n', out)
        self.assertIn('weighted tokens: 0\n', out)

    def test_summary_prints_no_subagent_seconds_line_when_no_session_spawned_a_subagent(self):
        _, out, _ = self.measure()
        self.assertNotIn('subagent seconds', out)

    def test_second_run_skips_unchanged_sessions_and_full_rereads(self):
        self.measure()
        _, out, _ = self.measure()
        self.assertIn('processed 0, skipped 1', out)
        _, out, _ = self.measure('--full')
        self.assertIn('processed 1, skipped 0', out)

    def test_missing_profile_is_reported_once_in_one_line_and_measure_still_runs(self):
        code, out, _ = self.measure()
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line.startswith('profile:')]
        self.assertEqual(len(lines), 1)
        self.assertIn('tracker', lines[0])
        self.assertIn(str(self.home / 'profile.md'), lines[0])
        self.assertEqual(len(self.rows()), 1)

    def test_complete_profile_prints_no_profile_line(self):
        self.home.mkdir()
        (self.home / 'profile.md').write_text(FULL_PROFILE, encoding='utf-8', newline='\n')
        _, out, _ = self.measure()
        self.assertNotIn('profile:', out)

    def test_ticket_key_pattern_comes_from_the_profile(self):
        self.measure()
        self.assertEqual(self.rows()[0]['ticket_keys'], ['ABC-12'])
        self.home.mkdir(exist_ok=True)
        (self.home / 'profile.md').write_text(FULL_PROFILE, encoding='utf-8', newline='\n')
        self.measure('--full')
        self.assertEqual(self.rows()[0]['ticket_keys'], ['PRJ42'])

    def test_no_data_folder_is_an_error_and_writes_nothing_into_home(self):
        code, out, err = run_cli('measure', '--home', str(self.home), '--projects', str(self.projects))
        self.assertEqual(code, 2)
        self.assertIn('data folder', err)
        self.assertEqual(out, '')
        self.assertFalse(self.home.exists())

    def test_data_folder_inside_or_equal_to_home_is_an_error(self):
        for data in (self.home / 'state', self.home, self.home / 'a' / '..' / 'b'):
            code, out, err = run_cli('measure', '--home', str(self.home), '--data', str(data),
                                          '--projects', str(self.projects))
            self.assertEqual(code, 2)
            self.assertIn('inside home', err)
            self.assertEqual(out, '')
        self.assertFalse(self.home.exists())

    def test_data_folder_next_to_home_is_fine(self):
        code, _, _ = run_cli('measure', '--home', str(self.root / 'loop'),
                                  '--data', str(self.root / 'loop-data'), '--projects', str(self.projects))
        self.assertEqual(code, 0)

    def test_file_system_errors_are_reported_like_path_errors(self):
        blocker = self.root / 'blocker'
        blocker.write_text('not a folder', encoding='utf-8')
        code, out, err = run_cli('measure', '--home', str(blocker / 'home'), '--data', str(self.data),
                                      '--projects', str(self.projects))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))
        self.assertEqual(out, '')

    def test_environment_fallbacks_for_home_data_and_projects(self):
        environ = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.home), 'CLAUDE_PLUGIN_DATA': str(self.data),
                   'ANOMALY_PROJECTS': str(self.projects)}
        code, _, _ = run_cli('measure', environ=environ)
        self.assertEqual(code, 0)
        self.assertTrue((self.home / 'metrics.jsonl').is_file())
        self.assertTrue((self.data / 'measure-state.json').is_file())

    def test_unfilled_home_placeholder_uses_the_environment_home(self):
        environ = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.home)}
        code, _, _ = run_cli('measure', '--home', '${user_config.home}', '--data', str(self.data),
                                  '--projects', str(self.projects), environ=environ)
        self.assertEqual(code, 0)
        self.assertTrue((self.home / 'metrics.jsonl').is_file())
        self.assertFalse(Path('${user_config.home}').exists())

    def test_unfilled_home_placeholder_uses_the_default_home(self):
        fake_user_folder = {'HOME': str(self.root), 'USERPROFILE': str(self.root)}
        with mock.patch.dict(os.environ, fake_user_folder):
            code, _, _ = run_cli('measure', '--home', '${user_config.home}', '--data', str(self.data),
                                      '--projects', str(self.projects))
        self.assertEqual(code, 0)
        self.assertTrue((self.root / '.claude' / 'anomaly' / 'metrics.jsonl').is_file())

    def test_unfilled_data_placeholder_is_the_no_data_folder_error(self):
        code, _, err = run_cli('measure', '--home', str(self.home), '--data', '${CLAUDE_PLUGIN_DATA}',
                                    '--projects', str(self.projects))
        self.assertEqual(code, 2)
        self.assertIn('data folder', err)
        self.assertFalse(Path('${CLAUDE_PLUGIN_DATA}').exists())

    def test_unfilled_home_placeholder_prints_a_one_line_notice_with_the_path_used(self):
        environ = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.home)}
        _, out, _ = run_cli('measure', '--home', '${user_config.home}', '--data', str(self.data),
                                 '--projects', str(self.projects), environ=environ)
        notices = [line for line in out.splitlines() if line.startswith('home:')]
        self.assertEqual(notices, [f'home: placeholder unfilled, using {self.home}'])

    def test_a_real_home_option_prints_no_notice(self):
        _, out, _ = self.measure()
        self.assertNotIn('home:', out)

    def test_the_injected_clock_reaches_the_handler(self):
        self.measure(now=datetime(2026, 10, 4, tzinfo=timezone.utc))
        cache = self.data / 'cache' / 'prompts.jsonl'
        self.assertIn('hello', cache.read_text(encoding='utf-8'))
        self.measure('--full', now=datetime(2026, 12, 31, tzinfo=timezone.utc))
        self.assertNotIn('hello', cache.read_text(encoding='utf-8'))

    def test_options_win_over_environment(self):
        environ = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.root / 'env-home'),
                   'CLAUDE_PLUGIN_DATA': str(self.root / 'env-data')}
        self.measure(environ=environ)
        self.assertTrue((self.home / 'metrics.jsonl').is_file())
        self.assertFalse((self.root / 'env-home').exists())
        self.assertFalse((self.root / 'env-data').exists())

    def test_tilde_in_home_option_is_expanded(self):
        fake_user_folder = {'HOME': str(self.root), 'USERPROFILE': str(self.root)}
        with mock.patch.dict(os.environ, fake_user_folder):
            code, _, _ = run_cli('measure', '--home', '~/loop-home', '--data', str(self.data),
                                      '--projects', str(self.projects))
        self.assertEqual(code, 0)
        self.assertTrue((self.root / 'loop-home' / 'metrics.jsonl').is_file())

    def test_empty_transcript_root_gives_zero_rows_summary(self):
        (self.root / 'none').mkdir()
        code, out, _ = run_cli('measure', '--home', str(self.home), '--data', str(self.data),
                                    '--projects', str(self.root / 'none'))
        self.assertEqual(code, 0)
        self.assertIn('rows 0', out)
        self.assertIn('weighted tokens: 0', out)

    def test_missing_transcript_root_is_a_clear_error(self):
        code, _, err = run_cli('measure', '--home', str(self.home), '--data', str(self.data),
                                    '--projects', str(self.root / 'absent'))
        self.assertEqual(code, 2)
        self.assertIn('transcript folder', err)


class PlanningDocsTest(unittest.TestCase):
    """The planning docs under `docs/` (workflow-plan ticket 02, AC-3 to AC-5): each within its budget."""
    DOCS_DIR = PLUGIN / 'docs'
    FORMATS = DOCS_DIR / 'formats.md'
    BOUNDARIES = DOCS_DIR / 'boundaries.md'
    DOC_BUDGETS = {FORMATS.name: 6 * 1024, BOUNDARIES.name: 2 * 1024}   # shared shapes; where each planning stage ends
    README = PLUGIN.parent.parent / 'README.md'
    CONTEXT = PLUGIN.parent.parent / 'CONTEXT.md'

    def doc_text(self, path):
        self.assertTrue(path.is_file(), f'docs/{path.name} is missing')
        return path.read_text(encoding='utf-8')

    def test_each_planning_doc_exists_within_its_budget(self):
        for name, max_bytes in self.DOC_BUDGETS.items():
            with self.subTest(doc=name):
                path = self.DOCS_DIR / name
                self.assertTrue(path.is_file(), f'docs/{name} is missing')
                self.assertLessEqual(path.stat().st_size, max_bytes)

    def test_the_formats_doc_defines_each_shared_shape(self):
        """AC-3: stories.md, the D-n and T-n lines, the ticket, the log.md line, the triage words, the
        next-step offer, the ADR front block."""
        text = self.doc_text(self.FORMATS)
        for token in ('## stories.md', '## decisions.md', '- D-n:', '- T-n:', 'Source:', 'Avoid:', 'Amended <date>:',
                      'Jira:', 'no-ticket', 'Repro:', '## log.md', 'anomaly log add', 'ACs: AC-1',
                      'ready-for-agent', 'ready-for-human (', 'needs-info', 'wontfix', '`in-progress` and `done`',
                      '/anomaly:<name>', '- Decision:', '- Revisit:', '## Out of scope', '(verbatim', '— owner:'):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_the_boundaries_doc_names_clear_the_three_stages_and_the_context_zone(self):
        """AC-4: /clear is never offered between interview, specify and slice; the ~150k zone."""
        text = self.doc_text(self.BOUNDARIES)
        plain = text.replace('`', '')
        for rule in (r'Never offer /clear between interview, specify and slice', r'Offer /clear once, after slice',
                     r'model never runs it', r'about 150k tokens'):
            with self.subTest(rule=rule):
                self.assertRegex(plain, rule)

    def test_the_readme_has_a_planning_formats_section_naming_both_docs(self):
        if not self.README.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        parts = self.README.read_text(encoding='utf-8').split('## Planning formats', 1)
        self.assertEqual(len(parts), 2, 'README.md has no "## Planning formats" section')
        section = parts[1].split('\n## ', 1)[0]
        for name in self.DOC_BUDGETS:
            with self.subTest(doc=name):
                self.assertIn(f'docs/{name}', section)

    def test_the_glossary_has_a_term_line_row(self):
        if not self.CONTEXT.is_file():
            self.skipTest('no CONTEXT.md two folders above the plugin: an installed copy, not the repository')
        rows = [line for line in self.CONTEXT.read_text(encoding='utf-8').splitlines()
                if line.startswith('| **term line**')]
        self.assertEqual(len(rows), 1)
        self.assertIn('T-n', rows[0])


class PlanReviewerTest(unittest.TestCase):
    """Ticket 06 (AC-12, AC-13): the read-only plan reviewer agent and its two mode docs."""
    AGENT = PLUGIN / 'agents' / 'plan.md'
    MODE_DOC_MAX_BYTES = 3 * 1024   # each mode doc, loaded only in its mode
    SPEC = PLUGIN / 'skills' / 'review' / 'plan-spec.md'
    TICKETS = PLUGIN / 'skills' / 'review' / 'plan-tickets.md'
    README = PLUGIN.parent.parent / 'README.md'

    def text(self, path):
        self.assertTrue(path.is_file(), path.relative_to(PLUGIN).as_posix())
        return path.read_text(encoding='utf-8')

    def items(self, path, headings):
        """Each heading is the start of one numbered check item in the doc (`3. Sizing.`); the item must exist as its own line."""
        text = self.text(path)
        for heading in headings:
            with self.subTest(doc=path.name, check=heading):
                self.assertRegex(text, re.compile(rf'^\d+\. {heading}\b', re.M))

    def test_the_plan_agent_names_both_modes_returns_its_report_and_loads_the_two_mode_docs(self):
        text = self.text(self.AGENT)
        lowered = text.lower()
        for mode in ('spec', 'tickets'):
            self.assertRegex(lowered, rf'`{mode}`|\b{mode} mode\b')
        self.assertRegex(lowered, r'writes? no file|no file')
        self.assertRegex(lowered, r'final message')
        for doc in ('skills/review/plan-spec.md', 'skills/review/plan-tickets.md'):
            self.assertIn(doc, text)

    def test_each_plan_mode_doc_fits_in_3_KB(self):
        for path in (self.SPEC, self.TICKETS):
            with self.subTest(doc=path.name):
                self.text(path)
                self.assertLessEqual(path.stat().st_size, self.MODE_DOC_MAX_BYTES)

    def test_spec_mode_checks_claims_testable_acs_owned_out_of_scope_lines_and_open_questions(self):
        """AC-12."""
        self.items(self.SPEC, ['Code claims', 'Tool claims', 'Testable ACs', 'Out of scope', 'Open questions'])
        text = self.text(self.SPEC)
        self.assertRegex(text, r'cite a `file:line` or a commit')
        self.assertRegex(text, r'its source, an ADR or a probe')
        self.assertRegex(text, r'names an owner')
        self.assertRegex(text, r'left at the gate is a Blocker')

    def test_tickets_mode_checks_the_seven_slice_checks(self):
        """AC-13: ordering, invented paths, hidden dependencies, sizing, Restates overlap, AC coverage, Tests level."""
        self.items(self.TICKETS, ['Ordering', 'Invented paths', 'Hidden dependencies between parallel tickets', 'Sizing',
                                  '`Restates:` overlap', 'AC coverage', '`Tests:` level per AC'])
        self.assertIn('`Covers:` is complete', self.text(self.TICKETS))

    def test_the_readme_reviewer_agents_section_names_the_plan_agent_and_both_modes(self):
        if not self.README.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        section = self.README.read_text(encoding='utf-8').split('## Reviewer agents', 1)[1].split('\n## ', 1)[0]
        self.assertIn('anomaly:plan', section)
        for mode in ('spec', 'tickets'):
            self.assertRegex(section, rf'`{mode}`|\b{mode}\b')

    def test_the_new_files_do_not_name_the_org_plan_reviewers(self):
        """ADR-0006: plan-audit and plan-sanity are not copied and not named."""
        for path in (self.AGENT, self.SPEC, self.TICKETS):
            text = self.text(path).lower()
            for name in ('plan-audit', 'plan-sanity'):
                with self.subTest(doc=path.name, name=name):
                    self.assertNotIn(name, text)


if __name__ == '__main__':
    unittest.main()

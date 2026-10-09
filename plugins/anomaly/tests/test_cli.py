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
        self.assertEqual(sorted(path.stem for path in self.agents()), sorted((*lens.core_lenses(), lens.PLAN_LENS)))   # plan: the plan-gate reviewer, outside the core lenses
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

    def test_the_review_skill_has_a_dispatch_row_or_heading_for_each_of_the_seven_modes(self):
        """AC-45: ticket, delta, cumulative, combined and rules; plan-gate ticket 07 (AC-14): spec and tickets."""
        text = self.review_text()
        self.assertLessEqual({'spec', 'tickets'}, set(constants.REVIEW_MODES))
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

    def test_the_build_skill_cli_only_anomaly_rule_names_the_diagnose_repro_script_as_its_one_exception(self):
        """Adhoc 2026-10-08-durable-runnable-repro, AC-1."""
        lines = [line for line in self.build_text().splitlines() if 'goes through the CLI' in line]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0].lower(), r'diagnose')
        self.assertRegex(lines[0].lower(), r'repro')

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

    def test_the_build_start_section_stops_and_asks_on_an_unresolved_command_verify(self):
        """Build-unresolved-verify ticket 01, AC-1: the rule sits in Start, before the red step."""
        text = self.build_text()
        self.assertLess(text.index('## Start'), text.index('## Red first'))
        start = text.split('## Start', 1)[1].split('\n## ', 1)[0]
        rules = [line.lower() for line in start.splitlines() if 'command verify' in line]
        self.assertEqual(len(rules), 1, 'no Start rule names `command verify`')
        self.assertIn('[i2]', rules[0], 'the new clause follows the [I2] step text')
        clause = rules[0].split('[i2]', 1)[1]      # the new clause only, not the older step text
        self.assertRegex(clause, r'unresolved|empty')
        for part in ('stop', 'ask', 'command', 'repo override', 'verify:', 'never guess'):
            self.assertIn(part, clause)


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

    def test_the_formats_doc_repro_shape_is_the_runnable_command_without_a_red_now_suffix(self):
        """Adhoc 2026-10-08-durable-runnable-repro, AC-1: `Repro: <command>` runs as written."""
        text = self.doc_text(self.FORMATS)
        self.assertIn('Repro: <command>', text)
        self.assertNotIn('(red now)', text)

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
                                  '`Restates:` complete', 'AC coverage', '`Tests:` level per AC'])
        self.assertIn('`Covers:` is complete', self.text(self.TICKETS))
        self.assertIn('`Restates:` lists must not share a file', self.text(self.TICKETS))

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


class PlanGateReviewTest(unittest.TestCase):
    """Workflow-plan ticket 07 (AC-14, AC-15): the review skill's `spec` and `tickets` modes, the plan lens,
    the README and glossary lines, and ADR-0015."""
    ROOT = PLUGIN.parent.parent
    REVIEW = PLUGIN / 'skills' / 'review'
    SKILL = REVIEW / 'SKILL.md'
    PLAN_AGENT = PLUGIN / 'agents' / 'plan.md'
    BRIEFS = REVIEW / 'BRIEFS.md'

    def skill(self):
        self.assertTrue(self.SKILL.is_file())
        return self.SKILL.read_text(encoding='utf-8')

    def section(self, heading):
        return self.skill().split(heading, 1)[1].split('\n## ', 1)[0]

    def mode_rows(self):
        return {mode: line for mode in ('spec', 'tickets')
                for line in self.skill().splitlines() if re.match(rf'\|\s*`?{mode}`?\s*\|', line)}

    def test_the_mode_table_has_a_row_for_spec_and_tickets_that_dispatch_the_plan_agent(self):
        rows = self.mode_rows()
        self.assertEqual(sorted(rows), ['spec', 'tickets'])
        for mode, row in rows.items():
            with self.subTest(mode=mode):
                self.assertIn('anomaly:plan', row)

    def test_step_1_skips_risk_and_the_diff_for_spec_and_tickets_as_for_rules(self):
        step = next(line for line in self.skill().splitlines() if line.startswith('1. '))
        self.assertRegex(step, r'(?s)(?:\bspec\b.*\btickets\b|\btickets\b.*\bspec\b).*skip|skip.*(?:\bspec\b.*\btickets\b|\btickets\b.*\bspec\b)')

    def test_the_ports_step_names_the_plan_agent_among_the_reviewers(self):
        step = next(line for line in self.skill().splitlines() if line.startswith('2. '))
        self.assertIn('anomaly:plan', step)

    def test_the_lens_step_names_the_plan_lens(self):
        step = next(line for line in self.skill().splitlines() if line.startswith('9. '))
        self.assertIn(f'`{lens.PLAN_LENS}`', step)

    def test_a_failed_read_of_the_plan_agents_mode_doc_is_answered_with_that_file_by_sendmessage(self):
        section = self.section('## When an agent\'s read fails')
        self.assertIn('anomaly:plan', section)
        for doc in ('plan-spec.md', 'plan-tickets.md'):
            with self.subTest(doc=doc):
                self.assertIn(doc, section)

    def test_a_blocker_stops_the_calling_skill_and_warnings_and_nits_go_in_its_handoff(self):
        """AC-15."""
        text = self.skill()
        lowered = text.lower()
        self.assertRegex(lowered, r'blocker[^.\n]*(stops?|halts?)[^.\n]*(calling skill|caller)'
                                  r'|(stops?|halts?)[^.\n]*(calling skill|caller)[^.\n]*blocker')
        self.assertRegex(lowered, r'warnings?[^.\n]*nits?[^.\n]*handoff|handoff[^.\n]*warnings?[^.\n]*nits?')

    def test_a_plan_mode_delta_round_rechecks_the_changed_lines_and_the_caller_passes_the_work_unit_folder(self):
        """AC-15: a fix gets a delta round from the same agent."""
        section = self.section('## Delta rounds').lower()
        self.assertIn('anomaly:plan', section)
        self.assertRegex(section, r'stories\.md')
        self.assertRegex(section, r'decisions\.md')
        self.assertRegex(section, r'changed')
        self.assertRegex(section, r'work-unit folder')

    def test_the_plan_agent_or_the_review_brief_carries_a_delta_line_for_the_changed_lines(self):
        """Amended 2026-10-08: `agents/plan.md` had none."""
        carriers = [path for path in (self.PLAN_AGENT, self.BRIEFS)
                    if re.search(r'(?i)(delta|re-?check)[^\n]*(changed|since)|(changed|since)[^\n]*(delta|re-?check)',
                                 path.read_text(encoding='utf-8'))]
        self.assertTrue(carriers, 'neither agents/plan.md nor review/BRIEFS.md has a plan delta line')

    def test_the_readme_review_section_names_the_spec_and_tickets_modes(self):
        if not (self.ROOT / 'README.md').is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        section = (self.ROOT / 'README.md').read_text(encoding='utf-8').split('## The review skill', 1)[1].split('\n## ', 1)[0]
        for mode in ('spec', 'tickets'):
            with self.subTest(mode=mode):
                self.assertRegex(section, rf'`{mode}`')
        self.assertIn('anomaly:plan', section)

    def test_the_glossary_has_one_plan_gate_row_avoiding_plan_sanity_and_claim_check(self):
        context = self.ROOT / 'CONTEXT.md'
        if not context.is_file():
            self.skipTest('no CONTEXT.md two folders above the plugin: an installed copy, not the repository')
        rows = [line for line in context.read_text(encoding='utf-8').splitlines() if line.startswith('| **plan gate**')]
        self.assertEqual(len(rows), 1)
        for token in ('spec', 'tickets', 'Blocker', 'plan-sanity', 'claim check'):
            with self.subTest(token=token):
                self.assertIn(token, rows[0])

    def test_adr_0015_is_accepted_and_adr_0011_names_it_as_partly_superseding(self):
        adrs = self.ROOT / 'docs' / 'adr'
        if not adrs.is_dir():
            self.skipTest('no docs/adr two folders above the plugin: an installed copy, not the repository')
        found = sorted(adrs.glob('0015-plan-gate-in-review-and-term-lines.md'))
        self.assertEqual(len(found), 1, 'docs/adr/0015-plan-gate-in-review-and-term-lines.md is missing')
        text = found[0].read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^# ADR-0015\b')
        self.assertRegex(text, r'(?m)^Status: Accepted\b')
        status = next(line for line in (next(adrs.glob('0011-*.md'))).read_text(encoding='utf-8').splitlines()
                      if line.startswith('Status:'))
        self.assertIn('ADR-0015', status)
        self.assertIn('partly superseded', status)


class InterviewSkillTest(unittest.TestCase):
    """Workflow-plan ticket 08 (AC-16 to AC-18): the interview skill's text, by key tokens. The rule trace
    against the brief is run by review, not here."""
    SKILL = PLUGIN / 'skills' / 'interview' / 'SKILL.md'
    SKILL_MAX_BYTES = 6 * 1024   # the brief's size; the all-skills cap is 8 KB
    ROOT = PLUGIN.parent.parent

    def text(self):
        self.assertTrue(self.SKILL.is_file(), 'skills/interview/SKILL.md is missing')
        return self.SKILL.read_text(encoding='utf-8')

    def test_the_interview_skill_fits_in_6_KB_and_its_tools_are_the_cli_only(self):
        self.text()
        self.assertLessEqual(self.SKILL.stat().st_size, self.SKILL_MAX_BYTES)
        fields = frontmatter.split(self.text())[0]
        self.assertEqual(fields.get('name'), 'interview')
        self.assertEqual(fields.get('allowed-tools'), constants.CLI_PATTERN)

    def test_the_interview_skill_is_slash_only_with_a_third_person_description_that_says_so(self):
        """AC-16: `disable-model-invocation: true`; the 250-character limit is the all-skills check above."""
        fields = frontmatter.split(self.text())[0]
        self.assertEqual(fields.get('disable-model-invocation'), 'true')
        description = fields.get('description', '')
        self.assertRegex(description.lower(), r'slash[- ]only|only as a slash|slash command')
        self.assertNotRegex(description, r'(?i)^\s*(use|run|ask)\b|\b(you|your)\b')
        self.assertNotIn('model-invocable', description.lower())

    def test_it_gathers_then_lists_settled_adrs_and_decisions_before_asking_rounds_of_at_most_8_questions(self):
        """AC-16."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('gather', text)
        self.assertIn('ADR', text)
        self.assertRegex(text, r'D-n|D-\d')
        self.assertIn('settled', lowered)
        self.assertLess(*(lowered.split('---', 2)[2].index(word) for word in ('settled already', '\n## a round')))
        self.assertRegex(lowered, r'(?:at most|up to|no more than|max(?:imum)?(?: of)?)\s*8\b')
        self.assertIn('Assumes:', text)
        self.assertIn('Recommend:', text)
        self.assertIn('Conflicts: <D-n / ADR-n / none>', text)
        self.assertIn('defaults', lowered)
        self.assertRegex(lowered, r'low[- ]risk')

    def test_it_writes_d_and_t_lines_with_a_source_after_each_round_and_edits_nothing_else(self):
        """AC-17."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('decisions.md', text)
        self.assertRegex(text, r'\.anomaly/<work unit>/decisions\.md')
        self.assertIn('T-n', text)
        self.assertIn('Source:', text)
        self.assertRegex(lowered, r'after each round|after every round|each round')
        self.assertRegex(lowered, r'no other file|nothing else|no other')
        self.assertRegex(lowered, r'no commit|not commit|never commit|makes no commit|do not commit')

    def test_it_closes_with_a_decisions_table_and_one_confirm_question_a_worklog_line_and_the_specify_offer(self):
        """AC-18."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('table', lowered)
        self.assertRegex(lowered, r'one confirm|single confirm|confirm question')
        self.assertIn('worklog add', text)
        self.assertIn('--stage interview', text)
        self.assertIn('--feature', text)
        self.assertIn('/anomaly:specify', text)

    def test_no_question_offers_or_reopens_a_settled_adr_or_d_n_even_when_the_idea_suggests_it(self):
        """2026-10-08-interview-settled-trap-and-open-lines AC-1: the conflict is named, not asked."""
        text = self.text()
        rules = [line for line in text.splitlines()
                 if re.search(r'\bADR\b|D-n', line) and 'settled' in line.lower()
                 and 'even when' in line.lower() and 'conflict' in line.lower()]
        self.assertTrue(rules, 'no rule line holds ADR or D-n with settled, even when and conflict')
        # Adhoc 2026-10-09-interview-settled-conflict-no-question, AC-1: a part of the idea that conflicts with a
        # settled ADR or D-n becomes an out-of-scope D-n with an owner, written without a question; no option
        # offers to reopen it, in every round and also when an owner is needed.
        rule = [line for line in text.splitlines()
                if re.search(r'(?i)conflict', line) and re.search(r'(?i)out of scope', line)
                and re.search(r'(?i)owned by that ADR', line)
                and re.search(r'(?i)without (a )?question|no question', line)]
        with self.subTest('a conflicting part is an out-of-scope D-n owned by that ADR, written without a question'):
            self.assertTrue(rule, 'no line ties conflict, out of scope, owned by that ADR and without a question')
        with self.subTest('the rule holds in every round'):
            self.assertTrue(any(re.search(r'(?i)(every|any|later) round', line) for line in rule),
                            'the conflict line does not say every round')
        with self.subTest('no question or option offers to reopen it'):
            self.assertRegex(text, r'(?i)no (question or )?option[^\n]{0,40}reopen|'
                                   r'never[^\n]{0,40}(offer|option)[^\n]{0,40}reopen')
        with self.subTest('the conflict is named under Settled already and only the user reopens it'):
            self.assertTrue(any(re.search(r'named (under|in) Settled already', line)
                                and re.search(r'(?i)only the user reopens|user (may|can) reopen', line)
                                for line in rule),
                            'the conflict line drops Settled already or the user right to reopen')

    def test_a_gap_the_user_settles_as_out_of_scope_is_a_d_n_with_an_owner_and_open_is_only_for_the_unanswered(self):
        """2026-10-08-interview-settled-trap-and-open-lines AC-1: `Open:` blocks specify. Adhoc
        2026-10-08-check-stories-owner-must-exist, AC-1: the owner must exist or carry a TODO(<owner>, revisit ...)
        key, and interview never writes a placeholder owner. Adhoc 2026-10-09-cumulative-review-fixes-eval-fixes-2,
        AC-1: with no known owner interview recommends the TODO key first; it writes `Open:` only when the user
        declines and says specify will stop on it, not that check stories will fail."""
        text = self.text()
        self.assertRegex(text, r'(?is)out of scope[^\n]*D-n[^\n]*owner|out of scope[^\n]*owner[^\n]*D-n|'
                               r'D-n[^\n]*owner[^\n]*out of scope|D-n[^\n]*out of scope[^\n]*owner')
        rule = [line for line in text.splitlines()
                if re.search(r'(?i)out of scope', line) and 'D-n' in line and re.search(r'(?i)owner', line)]
        self.assertTrue(rule, 'no line ties out of scope, D-n and owner')
        self.assertTrue(any('Source:' in line for line in rule), 'the out-of-scope D-n rule drops its Source:')
        self.assertTrue(any(re.search(r'(?i)never a `?D-n', line) for line in rule),
                        'the rule does not say the owner is not the D-n itself')
        self.assertTrue(any(re.search(r'(?i)`?Open:`?[^\n]*\bonly\b[^\n]*unanswered', line)
                            for line in text.splitlines()), 'Open: is not said to be only for the unanswered')
        self.assertRegex(text, r'(?is)`?Open:`?[^\n]*\b(?:block|blocks|stop|stops)\b[^\n]*specify|'
                               r'specify[^\n]*\b(?:block|blocks|blocked|stop|stops|stopped)\b[^\n]*`?Open:`?')
        self.assertTrue(any(re.search(r'(?i)\bexist', line) for line in rule),
                        'the rule does not say the owner must exist')
        self.assertTrue(any(re.search(r'TODO\([^)]*revisit', line) for line in rule),
                        'the rule does not name the TODO(<owner>, revisit ...) key')
        self.assertRegex(text, r'(?i)never[^\n]{0,40}placeholder')
        with self.subTest('recommends the TODO key first'):
            self.assertRegex(text, r'(?i)recommend[^\n]{0,60}TODO')
        with self.subTest('says specify stops on an Open: line'):
            self.assertRegex(text, r'(?i)specify will stop|specify stops')
        with self.subTest('no longer says check stories fails for an Open: line'):
            self.assertNotRegex(text, r'(?i)Open:[^\n]{0,80}check stories. will fail')

    def test_it_links_the_formats_and_boundaries_docs_one_level_deep(self):
        text = self.text()
        for name in ('formats.md', 'boundaries.md'):
            with self.subTest(doc=name):
                self.assertRegex(text, rf'\]\((?:\.\./)+docs/{re.escape(name)}\)|docs/{re.escape(name)}')
                self.assertTrue((PLUGIN / 'docs' / name).is_file())
        self.assertFalse((self.SKILL.parent / 'docs').exists())

    def test_the_glossary_lens_row_names_the_interviews_recommendations_and_the_three_counts(self):
        context = self.ROOT / 'CONTEXT.md'
        if not context.is_file():
            self.skipTest('no CONTEXT.md two folders above the plugin: an installed copy, not the repository')
        rows = [line for line in context.read_text(encoding='utf-8').splitlines() if line.startswith('| **lens**')]
        self.assertEqual(len(rows), 1)
        self.assertIn('interview', rows[0])
        self.assertIn('recommendations', rows[0])
        for word in ('accepted', 'rejected', 'revised'):
            with self.subTest(word=word):
                self.assertIn(word, rows[0])

    def test_the_readme_has_an_interview_skill_section_naming_the_slash_command(self):
        readme = self.ROOT / 'README.md'
        if not readme.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        text = readme.read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^## The interview skill$')
        section = text.split('## The interview skill', 1)[1].split('\n## ', 1)[0]
        self.assertIn('/anomaly:interview', section)


class SpecifySkillTest(unittest.TestCase):
    """Workflow-plan ticket 09 (AC-19 to AC-21): the specify skill's text, by key tokens. The rule trace against
    the brief is run by review, not here. The all-skills checks (250-character description, 8 KB, folder set)
    cover the new folder through ALLOWED_TOOLS_SKILLS."""
    SKILL = PLUGIN / 'skills' / 'specify' / 'SKILL.md'
    ROOT = PLUGIN.parent.parent

    def text(self):
        self.assertTrue(self.SKILL.is_file(), 'skills/specify/SKILL.md is missing')
        return self.SKILL.read_text(encoding='utf-8')

    def test_the_specify_skill_is_slash_only_limited_to_the_cli_and_says_so_in_a_third_person_description(self):
        """AC-19."""
        fields = frontmatter.split(self.text())[0]
        self.assertEqual(fields.get('name'), 'specify')
        self.assertEqual(fields.get('disable-model-invocation'), 'true')
        self.assertEqual(fields.get('allowed-tools'), constants.CLI_PATTERN)
        description = fields.get('description', '')
        self.assertLessEqual(len(description), 250)
        self.assertRegex(description.lower(), r'slash[- ]only|only as a slash|slash command')
        self.assertNotRegex(description, r'(?i)^\s*(use|run|ask)\b|\b(you|your)\b')
        self.assertLessEqual(self.SKILL.stat().st_size, SkillFileTest.SKILL_MAX_BYTES)

    def test_it_writes_stories_md_and_appends_cited_d_lines_from_decisions_md(self):
        """AC-19."""
        text = self.text()
        lowered = text.lower()
        self.assertRegex(text, r'\.anomaly/<work unit>/stories\.md')
        self.assertIn('decisions.md', text)
        for part in ('Sources', 'Gathered', 'Why', 'Out of scope'):
            with self.subTest(part=part):
                self.assertIn(part, text)
        self.assertRegex(text, r'AC-n|AC-\d')
        self.assertRegex(lowered, r'verbatim')
        self.assertRegex(lowered, r'continuous|without gaps|no gap')
        self.assertRegex(text, r'D-n|D-\d')
        self.assertRegex(lowered, r'append')
        self.assertRegex(lowered, r'cite|source:')

    def test_it_never_writes_a_context_row_or_a_t_line(self):
        text = self.text()
        self.assertRegex(text, r'CONTEXT\.md')
        self.assertRegex(text, r'T-n')
        self.assertRegex(text.lower(), r'never|does not write|no `?context\.md`?|not write')

    def test_open_items_in_decisions_md_stop_it_before_it_writes_anything_and_send_the_user_to_the_interview(self):
        """Amended at ticket 09 build."""
        text = self.text()
        self.assertIn('Open:', text)
        self.assertIn('/anomaly:interview', text)
        self.assertRegex(text.lower(), r'before it writes|writes nothing|before writing|nothing is written')

    def test_it_drafts_adrs_under_the_work_unit_with_a_number_free_on_every_branch(self):
        """AC-20."""
        text = self.text()
        self.assertRegex(text, r'\.anomaly/<work unit>/adr/')
        self.assertIn('git log --all -- docs/adr/', text)
        self.assertRegex(text.lower(), r'free on every branch|every branch')
        self.assertRegex(text, r'\.anomaly/\*/adr/')

    def test_it_runs_check_stories_then_the_spec_review_then_a_digest_of_at_most_5_lines_and_waits(self):
        """AC-21, with the Blocker and warning rules of the review amendments."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('check stories', text)
        self.assertRegex(text, r'anomaly:review')
        self.assertRegex(lowered, r'`?spec`? mode|mode `?spec`?')
        self.assertLess(text.index('check stories'), text.index('anomaly:review'))
        self.assertRegex(lowered, r'(?:at most|up to|no more than|max(?:imum)?(?: of)?)\s*5 lines')
        self.assertRegex(lowered, r'wait|approv')
        self.assertIn('Blocker', text)
        self.assertRegex(lowered, r'exit 1|exits 1')
        self.assertIn('warning:', text)
        self.assertIn('delta', lowered)
        self.assertIn('lens tally sum', text)
        self.assertNotRegex(text, r'anomaly:plan\b')

    def test_it_logs_one_log_line_with_a_semicolon_ended_id_list_and_a_specify_work_unit_line_without_costs(self):
        """AC-21."""
        text = self.text()
        self.assertRegex(text, r'log add\b[^\n]*--stage specify')
        self.assertRegex(text, r'ACs: AC-\d+(?:, AC-\d+)*;')
        self.assertIn('worklog add', text)
        self.assertRegex(text.lower(), r'no cost|never cost|without cost|carry no cost')

    def test_it_records_the_interview_recommendation_counts_as_the_interview_lens(self):
        text = self.text()
        self.assertRegex(text, r'lens tally add\b[^\n]*--lens interview')

    def test_it_links_the_formats_and_boundaries_docs_one_level_deep(self):
        text = self.text()
        for name in ('formats.md', 'boundaries.md'):
            with self.subTest(doc=name):
                self.assertRegex(text, rf'docs/{re.escape(name)}')
                self.assertTrue((PLUGIN / 'docs' / name).is_file())
        self.assertFalse((self.SKILL.parent / 'docs').exists())

    def test_it_holds_one_worked_stories_example_in_a_fence_with_numbered_acs(self):
        """G26. test_neutral.py scans every plugin file, this skill included, but only for the owner's profile
        identifiers (it skips without a profile), so a made-up domain is a review check, not a test."""
        text = self.text()
        fences = re.findall(r'(?ms)^```[a-z]*\n(.*?)^```', text)
        examples = [block for block in fences if re.search(r'(?m)^.*\bAC-1\b', block)]
        self.assertEqual(len(examples), 1, 'expected one fenced stories.md example holding AC-1')
        self.assertRegex(examples[0], r'(?m)^.*\bAC-2\b')
        self.assertIn('Out of scope', examples[0])

    def test_an_out_of_scope_owner_is_a_unit_ticket_or_adr_never_the_deferring_d_n_and_the_user_is_asked(self):
        """2026-10-08-out-of-scope-owner-check AC-1. Adhoc 2026-10-08-check-stories-owner-must-exist, AC-1:
        the owner must exist or carry a TODO(<owner>, revisit ...) key, and specify never writes a placeholder.
        Adhoc 2026-10-09-cumulative-review-fixes-eval-fixes-2, AC-1: with no known owner specify keeps the Out of
        scope line with an empty owner, runs check stories and stops before the gate."""
        text = self.text()
        rule = [line for line in text.splitlines() if re.search(r'(?i)out of scope', line) and re.search(r'(?i)owner', line)]
        self.assertTrue(rule, 'no line ties out of scope and owner')
        self.assertTrue(any(re.search(r'(?i)never a `?D-n', line) for line in rule),
                        'the rule does not say the owner is not the D-n itself')
        self.assertRegex(text, r'(?i)\bask\b[^\n]*owner|owner[^\n]*\bask\b')
        self.assertTrue(any(re.search(r'(?i)\bexist', line) for line in rule),
                        'the rule does not say the owner must exist')
        self.assertTrue(any(re.search(r'TODO\([^)]*revisit', line) for line in rule),
                        'the rule does not name the TODO(<owner>, revisit ...) key')
        self.assertRegex(text, r'(?i)never[^\n]{0,40}placeholder')
        self.assertTrue(any(re.search(r'(?i)empty owner', line) for line in rule),
                        'the rule does not keep the Out of scope line with an empty owner')
        self.assertTrue(any(re.search(r'(?i)empty owner', line) and 'check stories' in line
                            and re.search(r'(?i)\bstop', line) for line in rule),
                        'the empty-owner rule does not run check stories and stop before the gate')

    def test_the_readme_has_a_specify_skill_section_naming_the_slash_command(self):
        readme = self.ROOT / 'README.md'
        if not readme.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        text = readme.read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^## The specify skill$')
        section = text.split('## The specify skill', 1)[1].split('\n## ', 1)[0]
        self.assertIn('/anomaly:specify', section)


class SliceSkillTest(unittest.TestCase):
    """Workflow-plan ticket 10 (AC-22 to AC-24): the slice skill's text, by key tokens. The rule trace against
    the brief is run by review, not here. The all-skills checks (250-character description, folder set) cover
    the new folder through ALLOWED_TOOLS_SKILLS."""
    SKILL = PLUGIN / 'skills' / 'slice' / 'SKILL.md'
    ROOT = PLUGIN.parent.parent

    def text(self):
        self.assertTrue(self.SKILL.is_file(), 'skills/slice/SKILL.md is missing')
        return self.SKILL.read_text(encoding='utf-8')

    def test_the_slice_skill_is_slash_only_limited_to_the_cli_and_says_so_in_a_third_person_description(self):
        """AC-22. The size limit is 6 KB (the ticket), tighter than the 8 KB of the all-skills check."""
        fields = frontmatter.split(self.text())[0]
        self.assertEqual(fields.get('name'), 'slice')
        self.assertEqual(fields.get('disable-model-invocation'), 'true')
        self.assertEqual(fields.get('allowed-tools'), constants.CLI_PATTERN)
        description = fields.get('description', '')
        self.assertLessEqual(len(description), 250)
        self.assertRegex(description.lower(), r'slash[- ]only|only as a slash|slash command')
        self.assertNotRegex(description, r'(?i)^\s*(use|run|ask)\b|\b(you|your)\b')
        self.assertLessEqual(self.SKILL.stat().st_size, 6144)

    def test_it_reads_stories_and_decisions_and_shows_a_numbered_list_for_approval_before_it_writes(self):
        """AC-22."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('stories.md', text)
        self.assertIn('decisions.md', text)
        self.assertRegex(lowered, r'numbered list')
        for part in ('title', 'blocked by', 'covers', 'tests'):
            with self.subTest(part=part):
                self.assertIn(part, lowered)
        self.assertRegex(lowered, r'approv')
        self.assertRegex(lowered, r'before it writes|writes nothing|before writing|nothing is written|only after')
        self.assertRegex(text, r'tickets/NN-slug\.md')

    def test_it_copies_acs_and_d_lines_verbatim_and_writes_no_line_numbers(self):
        """AC-22, with the Amended line of the ticket 05 review."""
        text = self.text()
        lowered = text.lower()
        self.assertRegex(lowered, r'verbatim')
        self.assertRegex(text, r'AC-n|AC-\d')
        self.assertRegex(text, r'D-n|D-\d')
        self.assertRegex(lowered, r'no line numbers|path:nn')
        self.assertRegex(text, r'Source:')
        self.assertRegex(lowered, r'fenced|fence')

    def test_it_writes_only_the_ready_statuses_and_none_of_the_lines_build_writes_later(self):
        """AC-22."""
        text = self.text()
        self.assertIn('ready-for-agent', text)
        self.assertIn('ready-for-human', text)
        self.assertRegex(text, r'Result:')   # named only to say that slice never writes it
        self.assertRegex(text.lower(), r'never writes?|does not write|writes none|not write')

    def test_it_links_the_formats_and_boundaries_docs_one_level_deep(self):
        text = self.text()
        for name in ('formats.md', 'boundaries.md'):
            with self.subTest(doc=name):
                self.assertRegex(text, rf'docs/{re.escape(name)}')
                self.assertTrue((PLUGIN / 'docs' / name).is_file())
        self.assertFalse((self.SKILL.parent / 'docs').exists())

    def test_term_lines_and_adr_drafts_land_in_the_first_ticket_that_needs_them_through_touches(self):
        """AC-23."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('Touches:', text)
        self.assertRegex(text, r'T-n|T-\d')
        self.assertRegex(lowered, r'\badr\b')
        self.assertRegex(lowered, r'first ticket')

    def test_it_runs_check_slice_then_the_tickets_review_and_a_blocker_stops_it_before_the_next_build_step(self):
        """AC-24, with the Blocker, warning and last-review rules of the review amendments."""
        text = self.text()
        lowered = text.lower()
        self.assertIn('check slice', text)
        self.assertRegex(text, r'anomaly:review')
        self.assertRegex(lowered, r'`?tickets`? mode|mode `?tickets`?')
        gate = text.split('\n## The checks and the gate', 1)[1].split('\n## ', 1)[0]
        self.assertLess(gate.index('check slice'), gate.index('anomaly:review'))
        self.assertRegex(lowered, r'exit 1|exits 1')
        self.assertIn('warning:', text)
        self.assertIn('Blocker', text)
        self.assertRegex(lowered, r'every other finding|all other findings|other findings')
        self.assertIn('delta', lowered)
        self.assertRegex(lowered, r'work-unit folder|work unit folder')
        self.assertIn('lens tally sum', text)
        self.assertRegex(lowered, r'last review')
        self.assertNotRegex(text, r'anomaly:plan\b')

    def test_it_logs_one_log_line_per_gate_result_and_a_slice_work_unit_line_without_costs(self):
        """AC-24."""
        text = self.text()
        self.assertRegex(text, r'log add\b[^\n]*--stage slice')
        self.assertRegex(text, r'worklog add\b[^\n]*--stage slice')
        self.assertRegex(text.lower(), r'no cost|never cost|without cost|carry no cost')

    def test_it_offers_the_build_of_the_first_unblocked_ticket_through_ticket_gate(self):
        """AC-24."""
        section = self.text().split('\n## After the gate', 1)[1].split('\n## ', 1)[0]
        self.assertIn('/anomaly:build <work unit>', section)
        self.assertIn('ticket gate', section)
        self.assertRegex(section.lower(), r'first ticket with no open blocker')

    def test_the_readme_has_a_slice_skill_section_naming_the_slash_command(self):
        readme = self.ROOT / 'README.md'
        if not readme.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        text = readme.read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^## The slice skill$')
        section = text.split('## The slice skill', 1)[1].split('\n## ', 1)[0]
        self.assertIn('/anomaly:slice', section)


class DiagnoseSkillTest(unittest.TestCase):
    """Workflow-plan ticket 13 (AC-27): the diagnose skill's text, by key tokens. The rule trace against the
    brief is run by review, not here. The all-skills checks (250-character description, folder set, 8 KB)
    cover the new folder through ALLOWED_TOOLS_SKILLS."""
    SKILL = PLUGIN / 'skills' / 'diagnose' / 'SKILL.md'
    ROOT = PLUGIN.parent.parent

    def text(self):
        self.assertTrue(self.SKILL.is_file(), 'skills/diagnose/SKILL.md is missing')
        return self.SKILL.read_text(encoding='utf-8')

    def prose(self):
        """The skill text after the frontmatter, without its fenced blocks (the CLI calls)."""
        body = frontmatter.split(self.text())[1]
        return re.sub(r'(?s)```.*?```', '', body)

    def test_the_diagnose_skill_is_model_invocable_limited_to_the_cli_and_says_it_acts_on_a_reported_bug(self):
        """AC-27. The size limit is 5 KB (the ticket), tighter than the 8 KB of the all-skills check."""
        fields = frontmatter.split(self.text())[0]
        self.assertEqual(fields.get('name'), 'diagnose')
        self.assertNotEqual(fields.get('disable-model-invocation'), 'true')
        self.assertEqual(fields.get('allowed-tools'), constants.CLI_PATTERN)
        description = fields.get('description', '')
        self.assertLessEqual(len(description), 250)
        self.assertRegex(description.lower(), r'reported bug|diagnose')
        self.assertNotRegex(description, r'(?i)^\s*(use|run|ask)\b|\b(you|your)\b')
        self.assertLessEqual(self.SKILL.stat().st_size, 5120)

    def test_a_red_capable_command_runs_before_any_hypothesis(self):
        """AC-27. Checked on the prose, so the CLI-call block cannot satisfy the order. Adhoc
        2026-10-09-diagnose-hypotheses-in-the-draft, AC-1: the chat-list assertion moved to the test below."""
        lowered = self.prose().lower()
        self.assertRegex(lowered, r'hypothes')
        red = re.search(r'\bred\b|red-capable|repro', lowered)
        self.assertIsNotNone(red, 'no red-capable command or repro in the prose')
        self.assertLess(red.start(), lowered.index('hypothes'))

    def test_the_ranked_hypotheses_go_into_the_draft_with_each_probe_result_and_the_explore_brief_asks_facts_only(self):
        """Adhoc 2026-10-09-diagnose-hypotheses-in-the-draft, AC-1 (replaces the chat-list rule of adhoc
        2026-10-08-diagnose-hypothesis-list-in-chat): the ranked hypotheses are a `Hypotheses` section of the
        ticket draft, each with its probe result (confirmed or refuted), and not a chat message; the explore
        brief still asks for facts only, with no question that points at a cause. Loose regexes on the lowered
        prose, so a short wording passes (5 KB limit)."""
        lowered = self.prose().lower()
        self.assertRegex(lowered, r'hypotheses[^\n]*\bdraft\b|\bdraft\b[^\n]*hypotheses')
        self.assertRegex(lowered, r'confirmed|refuted')
        self.assertNotRegex(lowered, r'in chat as a numbered list|own (chat )?message')
        self.assertRegex(lowered, r'before any probe file')
        self.assertRegex(lowered, r'brief[^.\n]{0,30}facts only')
        self.assertRegex(lowered, r'(never|no) (a )?(question|ask)[^.\n]{0,40}cause|never[^.\n]{0,40}cause')

    def test_the_probe_step_probes_each_listed_hypothesis_in_rank_order(self):
        """Adhoc 2026-10-09-cumulative-fixes-eval-fixes-3, AC-1: step 6 probes each listed hypothesis, in rank
        order, not only the first or the likely one. Loose regex on the lowered prose (5 KB limit)."""
        lowered = self.prose().lower()
        self.assertRegex(lowered, r'each (listed )?hypothes[^\n]{0,40}rank order|rank order[^\n]{0,40}each')

    def test_the_root_cause_is_cited_as_file_line_or_probe_output_else_unverified(self):
        """AC-27."""
        text = self.text()
        self.assertRegex(text, r'file:line')
        self.assertRegex(text.lower(), r'probe output')
        self.assertIn('unverified', text.lower())

    def test_it_changes_no_source_and_leaves_the_tree_clean(self):
        """AC-27."""
        lowered = self.text().lower()
        self.assertRegex(lowered, r'git status')
        self.assertRegex(lowered, r'\bclean\b')
        self.assertRegex(lowered, r'no source|changes no source|never edits|read-only')

    def test_it_writes_the_ticket_through_ticket_adhoc_from_a_draft_written_in_the_scratchpad(self):
        """AC-27, with ticket 12 (`--from`)."""
        text = self.text()
        self.assertRegex(text, r'ticket adhoc\b[^\n]*--from')
        self.assertRegex(text, r'Write tool')
        self.assertRegex(text.lower(), r'scratchpad')

    def test_the_loop_script_goes_to_adhoc_with_a_repro_name_and_the_repro_line_runs_it(self):
        """Adhoc 2026-10-08-durable-runnable-repro, AC-1: the script outlives the session; the draft stays in the
        scratchpad (the test above)."""
        text = self.text()
        self.assertRegex(text, r'\.anomaly/adhoc/\S*-repro')
        self.assertTrue(any('`Repro:`' in line and 'script' in line.lower() for line in text.splitlines()),
                        'no line says the Repro: line runs the loop script')

    def test_the_redact_rule_covers_the_draft_and_the_ticket_not_only_shown_output(self):
        """Adhoc 2026-10-08-review-security-lows, AC-1: A09, secrets stay out of the files too."""
        match = re.search(r'Redact secrets[^.]*\.', self.text())
        self.assertIsNotNone(match, 'the skill has no "Redact secrets" sentence')
        sentence = match.group(0).lower()
        self.assertIn('draft', sentence)
        self.assertIn('ticket', sentence)
        self.assertIn('script', sentence)
        self.assertRegex(sentence, r'env(ironment)? var')

    def test_it_logs_a_diagnose_work_unit_line(self):
        """AC-27."""
        self.assertRegex(self.text(), r'worklog add\b[^\n]*--stage diagnose')

    def test_it_offers_anomaly_build_with_the_path_of_the_adhoc_ticket(self):
        """AC-27, with the build note of the ticket."""
        text = self.text()
        self.assertRegex(text, r'anomaly:build[^\n]*\.anomaly/adhoc/|anomaly:build <adhoc ticket path>')

    def test_it_links_the_formats_doc_one_level_deep_and_does_not_restate_the_ticket_template(self):
        """The Amended line of the ticket."""
        text = self.text()
        self.assertRegex(text, r'docs/formats\.md')
        self.assertTrue((PLUGIN / 'docs' / 'formats.md').is_file())
        self.assertFalse((self.SKILL.parent / 'docs').exists())
        for block in re.findall(r'(?s)```.*?```', text):
            self.assertFalse('Covers: AC-1' in block and 'Status: ready-for-agent' in block,
                             'the ticket template is restated; link formats.md instead')

    def test_the_readme_has_a_diagnose_skill_section_naming_the_skill(self):
        readme = self.ROOT / 'README.md'
        if not readme.is_file():
            self.skipTest('no README.md two folders above the plugin: an installed copy, not the repository')
        text = readme.read_text(encoding='utf-8')
        self.assertRegex(text, r'(?m)^## The diagnose skill$')
        section = text.split('## The diagnose skill', 1)[1].split('\n## ', 1)[0]
        self.assertIn('anomaly:diagnose', section)


if __name__ == '__main__':
    unittest.main()

"""`ports`: the resolved adapter of every port, the repo-layer commands and the model roles (ADR-0007),
run in-process against a temporary home and a temporary git repository."""
import json
import re
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from anomaly_loop import constants, ports, profile, repolayer
from tests.fixtures import GitFixture, run_cli, write_text

LINE = re.compile(r'(\S+) (\S+) = (.*?) ?\[([^\[\]]*)\]')
PORT_NAMES = {'implementer', 'test_writer', 'conventions', 'reviewers', 'gather', 'tracker', 'issue_source',
              'ci', 'mr', 'commit', 'branch', 'ui_check', 'key_line', 'adr_folder'}
COMMANDS = ('verify', 'e2e', 'install', 'codegen', 'hook_path')
LENSES = 'anomaly:code, anomaly:feature, anomaly:security'
MODEL_ROLES = ('explore', 'implement', 'implement_wide', 'lookup', 'digest', 'review', 'review_code',
               'review_feature', 'review_security', 'deep_analysis', 'browse')
REVIEW_LENSES = ('review_code', 'review_feature', 'review_security')
EFFORT_LEVELS = ('low', 'medium', 'high', 'xhigh', 'max')
OVERRIDING_ENV = ('CLAUDE_CODE_SUBAGENT_MODEL_FORCE', 'CLAUDE_CODE_EFFORT_LEVEL')
TEMPLATE = Path(__file__).resolve().parent.parent / 'templates' / 'profile.md'


def parse(out):
    """{(section, name): (value, source)} of every output line; a line of another shape fails."""
    found = {}
    for line in out.splitlines():
        match = LINE.fullmatch(line)
        if match is None:
            raise AssertionError(f'line not in the ports shape: {line!r}')
        found[match[1], match[2]] = (match[3], match[4])
    return found


class PortsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = GitFixture(self.root / 'demo')

    def write_profile(self, *lines):
        write_text(self.home / 'profile.md', '\n'.join(['---', *lines, '---', '']))

    def write_override(self, name, *lines):
        write_text(self.home / 'repos' / f'{name}.md', '\n'.join(['---', *lines, '---', '']))

    def ports(self, folder=None):
        code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(folder or self.repo.root))
        self.assertEqual(code, 0, err)
        self.assertNotIn('Traceback', out + err)
        return parse(out)

    def section(self, result, name):
        return {key[1]: value for key, value in result.items() if key[0] == name}


class PortTableTest(PortsCase):
    def test_empty_profile_puts_every_port_on_its_core_default(self):
        found = self.section(self.ports(), 'port')
        self.assertEqual(set(found), PORT_NAMES)
        self.assertEqual({source for _, source in found.values()}, {'core default'})
        self.assertEqual(found['reviewers'][0], LENSES)
        self.assertEqual(found['ci'][0], 'no CI gate')
        self.assertEqual(found['commit'][0], 'type(scope): summary')
        self.assertEqual(found['branch'][0], 'feat/<slug>')

    def test_test_writer_and_ui_check_core_defaults_name_their_dispatch(self):
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['test_writer'][0], 'a separate general-purpose dispatch with the test-writer '
                                                  'brief, never the implementer')
        self.assertEqual(found['ui_check'][0], "built-in browser walkthrough of the ticket's UI ACs")

    def test_the_tracker_and_issue_source_core_defaults_name_the_anomaly_folder(self):
        """AC-87: the CLI's root is `.anomaly`, not `.scratch`."""
        found = self.section(self.ports(), 'port')
        for name in ('tracker', 'issue_source'):
            with self.subTest(port=name):
                self.assertIn('.anomaly', found[name][0])
                self.assertNotIn('.scratch', found[name][0])

    def test_output_holds_ports_repo_commands_and_model_roles_and_nothing_from_a_profile(self):
        code, out, _ = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
        self.assertEqual(code, 0)
        result = parse(out)
        self.assertEqual({key[0] for key in result}, {'port', 'repo', 'command', 'model'})
        self.assertNotIn('profile', out)

    def test_a_profile_adapter_replaces_the_core_default_in_a_replace_port(self):
        self.write_profile('implementers:', '  stack-a: agent-one', 'mr_tool: some-mr-skill', 'ci: some-ci-tool',
                           'verify_ui: some-checker', 'test_writers:', '  stack-a: writer-one')
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['implementer.stack-a'], ('agent-one', 'profile'))
        self.assertEqual(found['implementer'][1], 'core default')
        self.assertEqual(found['test_writer.stack-a'], ('writer-one', 'profile'))
        self.assertEqual(found['mr'], ('some-mr-skill', 'profile'))
        self.assertEqual(found['ci'], ('some-ci-tool', 'profile'))
        self.assertEqual(found['ui_check'], ('some-checker', 'profile'))

    def test_an_org_reviewer_is_added_beside_the_three_lenses(self):
        self.write_profile('reviewers: org-reviewer, org-security-reviewer')
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['reviewers'], (f'{LENSES}, org-reviewer, org-security-reviewer',
                                              'core default + profile'))

    def test_a_reviewer_list_in_brackets_or_on_several_lines(self):
        self.write_profile('reviewers: [org-a, org-b]', 'gather:', '  - skill-a', '  - skill-b, <skill>')
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['reviewers'], (f'{LENSES}, org-a, org-b', 'core default + profile'))
        self.assertEqual(found['gather'], ("read the repo's code and docs, skill-a, skill-b", 'core default + profile'))

    def test_an_org_conventions_source_is_listed_after_the_repos_own_docs(self):
        self.write_profile('conventions:', '  stack-a: docs/org-conventions.md')
        found = self.section(self.ports(), 'port')
        base = found['conventions'][0]
        self.assertEqual(found['conventions'][1], 'core default')
        self.assertEqual(found['conventions.stack-a'], (f'{base}, docs/org-conventions.md', 'core default + profile'))

    def test_a_per_stack_value_without_a_stack_is_the_adapter_for_every_stack(self):
        self.write_profile('implementers: some-agent', 'conventions: docs/org.md', 'test_writers:',
                           '  pack:writer-tool', '  stack-a: writer-one', '  stack-b:')
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['implementer'], ('some-agent', 'profile'))
        self.assertEqual(found['conventions'], ("the repo's own docs, only the sections the diff touches, docs/org.md",
                                                'core default + profile'))
        self.assertEqual(found['test_writer'], ('pack:writer-tool', 'profile'))
        self.assertEqual(found['test_writer.stack-a'], ('writer-one', 'profile'))
        self.assertNotIn('test_writer.stack-b', found)
        resolution = ports.resolve(self.home, self.repo.root)
        self.assertEqual(ports.port(resolution, 'implementer', 'stack-x').value, 'some-agent')

    def test_an_id_with_a_colon_is_a_base_adapter_and_a_repeated_stack_keeps_its_last_value(self):
        self.write_profile('implementers: web:my-agent', '  mobile: m-agent', '  mobile: m-agent-two')
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['implementer'], ('web:my-agent', 'profile'))
        self.assertEqual(found['implementer.mobile'], ('m-agent-two', 'profile'))

    def test_two_lines_without_a_stack_in_a_replace_port_are_refused_by_ports(self):
        self.write_profile('implementers:', '  agent-a', '  agent-b')
        code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertIn('implementers', err)
        self.assertEqual(out, '')
        resolution = ports.resolve(self.home, self.repo.root)
        self.assertEqual(ports.port(resolution, 'implementer').value, 'agent-a')
        self.assertEqual(len(resolution.problems), 1)

    def test_two_lines_without_a_stack_in_an_extend_port_are_both_listed(self):
        self.write_profile('conventions:', '  docs/a.md', '  docs/b.md')
        found = self.section(self.ports(), 'port')
        self.assertEqual(found['conventions'], ("the repo's own docs, only the sections the diff touches, docs/a.md, "
                                                'docs/b.md', 'core default + profile'))

    def test_absent_blank_or_placeholder_values_stay_on_the_core_default(self):
        self.write_profile('ci:', 'mr_tool: <skill or command>', 'implementers:', '  stack-a: <agent id>',
                           'reviewers: <agent id>', 'conventions:', '  stack-a: <path>', 'verify_ui: <skill or tool>',
                           'models:', '  explore: <model>')
        result = self.ports()
        found = self.section(result, 'port')
        self.assertEqual(set(found), PORT_NAMES)
        self.assertEqual({source for _, source in found.values()}, {'core default'})
        self.assertEqual(self.section(result, 'model')['explore'], ('haiku', 'core default'))

    def test_the_shipped_template_copied_unchanged_adds_only_its_real_values(self):
        shutil.copy(TEMPLATE, self.home / 'profile.md')
        result = self.ports()
        found = self.section(result, 'port')
        self.assertEqual({name for name, (_, source) in found.items() if source != 'core default'},
                         {'tracker', 'commit', 'branch'})
        self.assertEqual({source for _, source in self.section(result, 'model').values()}, {'core default'})


class ProfileKeysTest(unittest.TestCase):
    def test_every_port_key_is_a_known_profile_key_and_the_new_ones_are_optional_and_in_the_template(self):
        keys = {key for _, _, key, _ in constants.PORTS} | {constants.MODELS_KEY}
        new = keys - set(profile.PROFILE_KEYS)
        self.assertEqual(new, {'test_writers', 'conventions', 'reviewers', 'gather', 'ci', 'models',
                               'key_line', 'adr_folder'})
        self.assertLessEqual(new, set(profile.OPTIONAL_KEYS))
        template = profile.parse_profile(TEMPLATE.read_text(encoding='utf-8'))
        self.assertLessEqual(new, set(template))


class ModelRolesTest(PortsCase):
    def resolved_models(self):
        return ports.resolve(self.home, self.repo.root).models

    def test_no_models_key_gives_the_core_defaults(self):
        found = self.section(self.ports(), 'model')
        self.assertEqual(list(found), list(MODEL_ROLES))
        self.assertEqual({role: found[role] for role in MODEL_ROLES if role not in REVIEW_LENSES}, {
            'explore': ('haiku', 'core default'),
            'implement': ('sonnet', 'core default'),
            'implement_wide': ('opus', 'core default'),
            'lookup': ('haiku', 'core default'),
            'digest': ('sonnet', 'core default'),
            'review': ('opus', 'core default'),
            'deep_analysis': ('opus', 'core default'),
            'browse': ('sonnet', 'core default')})
        self.assertEqual({role: found[role][0] for role in REVIEW_LENSES}, {role: 'opus' for role in REVIEW_LENSES})

    def test_the_models_key_maps_each_role_it_names(self):
        self.write_profile('models:', '  explore: model-x', '  review: model-y', '  deep_analysis: model-z')
        found = self.section(self.ports(), 'model')
        self.assertEqual(found['explore'], ('model-x', 'profile'))
        self.assertEqual(found['review'], ('model-y', 'profile'))
        self.assertEqual(found['deep_analysis'], ('model-z', 'profile'))
        self.assertEqual(found['browse'], ('sonnet', 'core default'))

    def test_each_lens_role_falls_back_to_the_review_value(self):
        self.write_profile('models:', '  review: model-y')
        models = self.resolved_models()
        for role in REVIEW_LENSES:
            with self.subTest(role=role):
                self.assertEqual(models[role].value, 'model-y')

    def test_a_profile_lens_role_overrides_the_review_fallback_for_that_lens_only(self):
        self.write_profile('models:', '  review: model-y', '  review_code: model-w')
        models = self.resolved_models()
        self.assertEqual(models['review_code'], repolayer.Setting('model-w', ports.PROFILE))
        self.assertEqual(models['review_feature'].value, 'model-y')
        self.assertEqual(models['review_security'].value, 'model-y')
        self.assertEqual(models['review'].value, 'model-y')

    def test_a_role_value_is_a_model_or_a_model_and_an_effort_level(self):
        for effort in EFFORT_LEVELS:
            with self.subTest(effort=effort):
                self.write_profile('models:', f'  review_code: opus {effort}')
                resolution = ports.resolve(self.home, self.repo.root)
                self.assertEqual(resolution.problems, ())
                setting = resolution.models['review_code']
                self.assertEqual(setting.source, ports.PROFILE)
                self.assertEqual(setting.value, f'opus {effort}')

    def test_any_other_role_value_shape_is_a_problem_line_and_ports_prints_nothing_else(self):
        for value in ('sonnet for contained tickets', 'sonnet turbo', 'opus high please'):
            with self.subTest(value=value):
                self.write_profile('models:', f'  implement: {value}')
                code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
                self.assertEqual(code, 2)
                self.assertEqual(out, '')
                self.assertEqual(len(err.splitlines()), 1)
                self.assertTrue(err.startswith('anomaly: '), err)
                self.assertIn('implement', err)

    def test_ports_warns_once_for_each_env_var_that_overrides_the_profile_and_for_no_other(self):
        for set_vars in ((), OVERRIDING_ENV[:1], OVERRIDING_ENV[1:], OVERRIDING_ENV):
            with self.subTest(set_vars=set_vars):
                code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root),
                                         environ={name: 'x' for name in set_vars})
                self.assertEqual(code, 0, err)
                self.assertEqual(set(self.section(parse(out), 'model')), set(MODEL_ROLES))
                lines = err.splitlines()
                for name in OVERRIDING_ENV:
                    self.assertEqual(len([line for line in lines if name in line]), 1 if name in set_vars else 0, name)
                self.assertEqual(len(lines), len(set_vars))

    def test_the_models_key_maps_a_new_role_with_an_effort_to_its_printed_model_line(self):
        self.write_profile('models:', '  lookup: haiku medium')
        value, source = self.section(self.ports(), 'model')['lookup']
        self.assertEqual(value, 'haiku medium')
        self.assertEqual(source, 'profile')

    def test_a_role_written_with_a_space_or_a_hyphen_maps_to_its_role(self):
        for spelling in ('deep analysis', 'Deep-Analysis'):
            with self.subTest(spelling=spelling):
                self.write_profile('models:', f'  {spelling}: model-z')
                self.assertEqual(self.section(self.ports(), 'model')['deep_analysis'], ('model-z', 'profile'))


class RepoLayerTest(PortsCase):
    def commands(self, folder=None):
        found = self.section(self.ports(folder), 'command')
        self.assertEqual(set(found), set(COMMANDS))
        return found

    def test_an_empty_repository_leaves_every_command_unresolved(self):
        self.assertEqual(self.commands(), {name: ('', 'unresolved') for name in COMMANDS})

    def test_package_json_scripts_run_through_the_lockfiles_package_manager(self):
        self.repo.write('package.json', json.dumps({'scripts': {
            'test': 'unit', 'verify': 'all', 'e2e': 'browser', 'codegen': 'gen'}}))
        self.repo.write('yarn.lock', '')
        found = self.commands()
        self.assertEqual(found['verify'], ('yarn run verify', 'package.json'))
        self.assertEqual(found['e2e'], ('yarn run e2e', 'package.json'))
        self.assertEqual(found['codegen'], ('yarn run codegen', 'package.json'))
        self.assertEqual(found['hook_path'], ('', 'unresolved'))

    def test_package_json_without_a_lockfile_uses_npm_and_guesses_the_test_script(self):
        self.repo.write('package.json', json.dumps({'scripts': {'test': 'unit', 'test:e2e': 'b', 'generate': 'g'}}))
        found = self.commands()
        self.assertEqual(found['verify'], ('npm run test', 'guessed from package.json'))
        self.assertEqual(found['e2e'], ('npm run test:e2e', 'guessed from package.json'))
        self.assertEqual(found['codegen'], ('npm run generate', 'guessed from package.json'))

    def test_each_lockfile_picks_its_package_manager_and_a_frozen_install_that_runs_no_scripts(self):
        """VK D3: the guessed install never updates the lockfile and never runs package scripts."""
        self.repo.write('package.json', json.dumps({'scripts': {'verify': 'all'}}))
        for lockfile, manager, install in (
                ('yarn.lock', 'yarn', 'yarn install --frozen-lockfile --ignore-scripts'),
                ('pnpm-lock.yaml', 'pnpm', 'pnpm install --frozen-lockfile --ignore-scripts'),
                ('bun.lock', 'bun', 'bun install --frozen-lockfile --ignore-scripts'),
                ('bun.lockb', 'bun', 'bun install --frozen-lockfile --ignore-scripts'),
                ('package-lock.json', 'npm', 'npm ci --ignore-scripts'),
                (None, 'npm', 'npm install --ignore-scripts')):   # no lockfile: nothing to freeze, npm ci would fail
            with self.subTest(lockfile=lockfile):
                if lockfile:
                    self.repo.write(lockfile, '')
                found = self.commands()
                if lockfile:
                    (self.repo.root / lockfile).unlink()
                self.assertEqual(found['verify'], (f'{manager} run verify', 'package.json'))
                self.assertEqual(found['install'], (install, 'guessed from package.json'))

    def test_every_package_manager_the_repo_layer_can_pick_has_a_frozen_install(self):
        managers = {manager for _, manager in constants.LOCKFILES} | {constants.DEFAULT_PACKAGE_MANAGER}
        self.assertLessEqual(managers, set(constants.FROZEN_INSTALLS))

    def test_a_repo_file_with_a_byte_order_mark_and_crlf_lines_is_read(self):
        (self.repo.root / 'package.json').write_bytes(b'\xef\xbb\xbf{\r\n"scripts": {"e2e": "b"}\r\n}\r\n')
        (self.repo.root / 'CLAUDE.md').write_bytes(b'\xef\xbb\xbf- verify: `run-all`\r\nHook path: `.githooks`\r\n')
        found = self.commands()
        self.assertEqual(found['verify'], ('run-all', 'CLAUDE.md'))
        self.assertEqual(found['hook_path'], ('.githooks', 'CLAUDE.md'))
        self.assertEqual(found['e2e'], ('npm run e2e', 'package.json'))

    def test_pubspec_gives_the_flutter_commands_and_build_runner_codegen(self):
        self.repo.write('pubspec.yaml', '\n'.join([
            'name: demo', 'dependencies:', '  flutter:', '    sdk: flutter', 'dev_dependencies:',
            '  build_runner: ^2.0.0', '']))
        found = self.commands()
        self.assertEqual(found['verify'], ('flutter test', 'guessed from pubspec.yaml'))
        self.assertEqual(found['install'], ('flutter pub get', 'guessed from pubspec.yaml'))
        self.assertEqual(found['codegen'], ('dart run build_runner build --delete-conflicting-outputs',
                                            'guessed from pubspec.yaml'))
        self.assertEqual(found['e2e'], ('', 'unresolved'))

    def test_a_dart_package_without_flutter_uses_dart(self):
        self.repo.write('pubspec.yaml', 'name: demo\ndependencies:\n  path: ^1.0.0\n')
        found = self.commands()
        self.assertEqual(found['verify'], ('dart test', 'guessed from pubspec.yaml'))
        self.assertEqual(found['install'], ('dart pub get', 'guessed from pubspec.yaml'))
        self.assertEqual(found['codegen'], ('', 'unresolved'))

    def test_makefile_targets_are_read_by_name(self):
        self.repo.write('Makefile', 'VAR := x\n\ntest: build\n\tgo test ./...\ne2e:\n\t./e2e.sh\n'
                                    'deps:\n\tgo mod download\n')
        found = self.commands()
        self.assertEqual(found['verify'], ('make test', 'guessed from Makefile'))
        self.assertEqual(found['e2e'], ('make e2e', 'Makefile'))
        self.assertEqual(found['install'], ('make deps', 'guessed from Makefile'))
        self.assertEqual(found['codegen'], ('', 'unresolved'))

    def test_commands_named_in_claude_md_and_agents_md_come_first(self):
        self.repo.write('package.json', json.dumps({'scripts': {'test': 'unit'}}))
        self.repo.write('CLAUDE.md', '# Demo\n\nSome text about `npm run lint`.\n\n'
                                     '- verify: `python -m unittest discover`\n')
        self.repo.write('AGENTS.md', '**Codegen:** `tool gen --all`\nHook path: `.githooks`\n'
                                     'verify: `ignored because CLAUDE.md named it`\n')
        found = self.commands()
        self.assertEqual(found['verify'], ('python -m unittest discover', 'CLAUDE.md'))
        self.assertEqual(found['codegen'], ('tool gen --all', 'AGENTS.md'))
        self.assertEqual(found['hook_path'], ('.githooks', 'AGENTS.md'))
        self.assertEqual(found['install'], ('npm install --ignore-scripts', 'guessed from package.json'))

    def test_every_hook_path_label_spelling_is_read(self):
        for label in ('hook path', 'Hook_path', 'hook-path', 'hooks path', 'HOOKS_PATH'):
            with self.subTest(label=label):
                self.repo.write('AGENTS.md', f'* {label}: `.githooks`\n')
                self.assertEqual(self.commands()['hook_path'], ('.githooks', 'AGENTS.md'))

    def test_the_override_file_beats_a_guessed_command_and_fills_the_gaps(self):
        self.repo.write('package.json', json.dumps({'scripts': {'test': 'unit'}}))
        self.write_override('demo', 'verify: override-verify', 'e2e: override-e2e', 'codegen: <command>',
                            'hook_path: .githooks')
        found = self.commands()
        self.assertEqual(found['verify'], ('override-verify', 'override'))
        self.assertEqual(found['e2e'], ('override-e2e', 'override'))
        self.assertEqual(found['hook_path'], ('.githooks', 'override'))
        self.assertEqual(found['install'], ('npm install --ignore-scripts', 'guessed from package.json'))
        self.assertEqual(found['codegen'], ('', 'unresolved'))

    def test_an_explicit_verify_script_or_target_beats_the_override_file(self):
        self.write_override('demo', 'verify: override-verify', 'e2e: override-e2e')
        self.repo.write('package.json', json.dumps({'scripts': {'verify': 'all'}}))
        self.repo.write('Makefile', 'e2e:\n\t./e2e.sh\n')
        found = self.commands()
        self.assertEqual(found['verify'], ('npm run verify', 'package.json'))
        self.assertEqual(found['e2e'], ('make e2e', 'Makefile'))

    def test_a_claude_md_line_beats_the_override_file(self):
        self.write_override('demo', 'verify: override-verify')
        self.repo.write('CLAUDE.md', 'verify: `run-all`\n')
        self.assertEqual(self.commands()['verify'], ('run-all', 'CLAUDE.md'))

    def test_the_override_file_gives_ui_check_app_facts_and_risk_patterns(self):
        self.write_override('demo', 'ui_check:', '  port: 4000', '  width: 1280', '  theme_key: <key>',
                            '  login_redirect: /login', 'risk_patterns:', '  - migrations/', '  - deploy/*.yaml')
        result = self.ports()
        self.assertEqual(self.section(result, 'app'), {'port': ('4000', 'override'), 'width': ('1280', 'override'),
                                                       'login_redirect': ('/login', 'override')})
        lines = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))[1].splitlines()
        self.assertEqual([line for line in lines if line.startswith('risk ')],
                         ['risk pattern = migrations/ [override]', 'risk pattern = deploy/*.yaml [override]'])

    def test_the_repo_name_is_the_origin_name_else_the_checkout_folder(self):
        found = self.section(self.ports(), 'repo')
        self.assertEqual(found['name'], ('demo', 'checkout'))
        self.assertEqual(found['override'], (str(self.home / 'repos' / 'demo.md'), 'absent'))
        self.repo.git('remote', 'add', 'origin', 'https://example.invalid/group/other-name.git')
        self.write_override('other-name', 'e2e: from-other-name')
        result = self.ports()
        self.assertEqual(self.section(result, 'repo')['name'], ('other-name', 'origin'))
        self.assertEqual(self.section(result, 'repo')['override'][1], 'found')
        self.assertEqual(self.section(result, 'command')['e2e'], ('from-other-name', 'override'))

    def base(self):
        found = self.section(self.ports(), 'repo')
        self.assertIn('base', found, 'no `repo base` line')
        return found['base']

    def test_the_base_branch_is_the_override_key_else_the_origin_default_branch_else_main(self):
        """VK decision 2026-10-06: build creates the integration branch from this base."""
        self.assertEqual(self.base(), ('main', 'core default'))
        self.repo.write('README.md', 'demo\n')
        self.repo.commit(['README.md'], 'docs: start', date(2026, 10, 1))
        self.repo.git('remote', 'add', 'origin', 'https://example.invalid/group/demo.git')
        self.repo.git('update-ref', 'refs/remotes/origin/trunk', 'HEAD')
        self.repo.git('symbolic-ref', 'refs/remotes/origin/HEAD', 'refs/remotes/origin/trunk')
        self.assertEqual(self.base(), ('trunk', 'git'))
        self.write_override('demo', 'base: <branch>')
        self.assertEqual(self.base(), ('trunk', 'git'))
        self.write_override('demo', 'base: release')
        self.assertEqual(self.base(), ('release', 'override'))

    def test_an_origin_name_made_only_of_dots_falls_back_to_the_checkout_folder(self):
        self.repo.git('remote', 'add', 'origin', 'https://example.invalid/group/..')
        self.assertEqual(self.section(self.ports(), 'repo')['name'], ('demo', 'checkout'))

    def test_a_worktree_uses_the_name_of_its_main_checkout(self):
        self.repo.write('README.md', 'demo\n')
        self.repo.commit(['README.md'], 'docs: start', date(2026, 10, 1))
        worktree = self.root / 'demo-worktree'
        self.repo.git('worktree', 'add', '-q', '-b', 'side', str(worktree))
        self.write_override('demo', 'verify: from-demo')
        result = self.ports(worktree)
        self.assertEqual(self.section(result, 'repo')['name'], ('demo', 'checkout'))
        self.assertEqual(self.section(result, 'command')['verify'], ('from-demo', 'override'))

    def test_a_folder_outside_git_is_read_under_its_own_name(self):
        folder = self.root / 'plain'
        write_text(folder / 'Makefile', 'test:\n\techo ok\n')
        result = self.ports(folder)
        self.assertEqual(self.section(result, 'repo')['name'], ('plain', 'folder'))
        self.assertEqual(self.section(result, 'command')['verify'], ('make test', 'guessed from Makefile'))

    def test_reading_the_repo_layer_writes_nothing_into_the_repository(self):
        for name, text in (('package.json', '{"scripts": {"test": "unit"}}'), ('Makefile', 'e2e:\n\tx\n'),
                           ('pubspec.yaml', 'name: demo\n'), ('CLAUDE.md', '- codegen: `gen`\n'),
                           ('AGENTS.md', 'text\n')):
            self.repo.write(name, text)
        self.repo.commit(['package.json', 'Makefile', 'pubspec.yaml', 'CLAUDE.md', 'AGENTS.md'], 'chore: files',
                         date(2026, 10, 1))
        self.repo.write('notes.txt', 'untracked\n')
        before = self.repo.status()
        self.ports()
        self.assertEqual(self.repo.status(), before)
        self.assertFalse((self.home / 'repos').exists())


class ResolverTest(PortsCase):
    """The resolver is the seam the `ci`, `risk` and later commands call; printing is separate."""

    def test_resolve_returns_ports_commands_risk_patterns_and_models(self):
        self.write_profile('ci: some-ci-tool', 'implementers:', '  stack-a: agent-one')
        self.write_override('demo', 'verify: run-all', 'risk_patterns:', '  - migrations/')
        resolution = ports.resolve(self.home, self.repo.root)
        self.assertEqual(ports.port(resolution, 'ci').value, 'some-ci-tool')
        self.assertFalse(ports.port(resolution, 'ci').is_default)
        self.assertTrue(ports.port(resolution, 'mr').is_default)
        self.assertEqual(ports.port(resolution, 'implementer', 'stack-a').value, 'agent-one')
        self.assertTrue(ports.port(resolution, 'implementer', 'stack-b').is_default)
        self.assertEqual(resolution.layer.commands['verify'].value, 'run-all')
        self.assertEqual(resolution.layer.risk_patterns, ('migrations/',))
        self.assertEqual(resolution.models['review'].value, 'opus')

    def test_the_key_line_and_adr_folder_ports_have_a_core_default_and_each_profile_key_replaces_it(self):
        """AC-8 (D-25): `key_line` (core `Key`) and `adr_folder` (core `docs/adr/`) are replace ports."""
        by_name = {line.name: line for line in ports.resolve_ports({})[0]}
        for name, default in (('key_line', 'Key'), ('adr_folder', 'docs/adr/')):
            with self.subTest(port=name, case='core default'):
                self.assertIn(name, by_name)
                self.assertEqual((by_name[name].value, by_name[name].source), (default, ports.CORE))
        lines, problems = ports.resolve_ports({'key_line': 'Story', 'adr_folder': 'docs/decisions/'})
        by_name = {line.name: line for line in lines}
        self.assertEqual(problems, ())
        for name, value in (('key_line', 'Story'), ('adr_folder', 'docs/decisions/')):
            with self.subTest(port=name, case='profile key'):
                self.assertIn(name, by_name)
                self.assertEqual((by_name[name].value, by_name[name].source), (value, ports.PROFILE))

    def break_repo_files(self):
        self.repo.write('package.json', '{"scripts": ')
        (self.repo.root / 'AGENTS.md').write_bytes(b'verify: `caf\xe9`\n')

    def test_ports_and_models_resolve_without_reading_the_repository(self):
        self.break_repo_files()
        self.write_profile('ci: some-ci-tool')
        resolution = ports.resolve(self.home, self.repo.root)
        self.assertEqual(ports.port(resolution, 'ci').value, 'some-ci-tool')
        self.assertEqual(resolution.models['browse'].value, 'sonnet')
        self.assertEqual(ports.port(ports.resolve(self.home), 'mr').source, 'core default')

    def test_risk_patterns_resolve_without_reading_the_repository_files(self):
        self.break_repo_files()
        self.write_override('demo', 'risk_patterns:', '  - migrations/')
        resolution = ports.resolve(self.home, self.repo.root)
        self.assertEqual(resolution.layer.risk_patterns, ('migrations/',))
        with self.assertRaises(ValueError):
            ports.command(resolution, 'verify')

    def test_command_gives_one_repo_layer_command_as_a_setting(self):
        self.write_override('demo', 'verify: run-all')
        resolution = ports.resolve(self.home, self.repo.root)
        self.assertEqual(ports.command(resolution, 'verify'), repolayer.Setting('run-all', 'override'))
        self.assertEqual(ports.command(resolution, 'e2e'), repolayer.Setting('', 'unresolved'))
        with self.assertRaises(KeyError):
            ports.command(resolution, 'deploy')


class ErrorContractTest(PortsCase):
    def test_a_missing_repo_folder_is_one_error_line_and_exit_2(self):
        code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.root / 'nowhere'))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertNotIn('Traceback', out + err)

    def test_a_package_json_that_is_not_json_is_one_error_line_naming_it(self):
        self.repo.write('package.json', '{"scripts": ')
        code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertIn('package.json', err)

    def test_a_hook_path_that_is_not_a_folder_inside_the_repository_is_one_error_line(self):
        for value in ('../hooks', 'a/../../b', '/abs/hooks', 'C:\\hooks', '~/hooks', 'my hooks'):
            with self.subTest(value=value):
                self.write_override('demo', f'hook_path: {value}')
                code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
                self.assertEqual(code, 2)
                self.assertEqual(len(err.splitlines()), 1)
                self.assertTrue(err.startswith('anomaly: hook_path'), err)
                self.assertIn('override', err)
        self.repo.write('CLAUDE.md', 'hook path: `../hooks`\n')
        code, _, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
        self.assertEqual(code, 2)
        self.assertIn('CLAUDE.md', err)

    def test_a_repo_file_that_is_not_utf8_is_one_error_line_naming_it(self):
        (self.repo.root / 'AGENTS.md').write_bytes(b'verify: `caf\xe9`\n')
        code, out, err = run_cli('ports', '--home', str(self.home), '--repo', str(self.repo.root))
        self.assertEqual(code, 2)
        self.assertEqual(len(err.splitlines()), 1)
        self.assertTrue(err.startswith('anomaly: '), err)
        self.assertIn('AGENTS.md', err)
        self.assertNotIn('Traceback', out + err)


if __name__ == '__main__':
    unittest.main()

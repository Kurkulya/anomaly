"""`risk <range>` through the CLI, in-process, against a temp git repository: the matched risk areas and
the matched files of a range, from the core patterns and the repo layer's `risk_patterns`. Nothing is
written; a range that does not resolve is one `anomaly:` line and exit 2."""
import contextlib
import io
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from anomaly_loop import cli, gitrepo, risk
from tests.fixtures import GitFixture, assert_cli_error, run_cli, write_text

NO_MATCH = 'no risk area matched'


class RiskCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.repo = GitFixture(self.root / 'repo')
        self.repo.write('README.md', 'a repository\n')
        self.repo.commit(['README.md'], 'chore: start', date(2026, 10, 1))

    def change(self, *names, text='changed\n'):
        """Commit new or edited files (relative paths) on top of the repository; a name given as
        `-path` deletes that tracked file. Returns the commit id."""
        for name in names:
            if name.startswith('-'):
                (self.repo.root / name[1:]).unlink()
            else:
                self.repo.write(name, text)
        self.repo.commit([name.lstrip('-') for name in names], 'feat: change', date(2026, 10, 2))
        return self.repo.git('rev-parse', 'HEAD').strip()

    def override(self, *patterns):
        write_text(self.home / 'repos' / 'repo.md',
                   '\n'.join(['---', 'risk_patterns:', *[f'  - {p}' for p in patterns], '---', '']))

    def risk(self, spec='HEAD~1..HEAD', *extra):
        return run_cli('risk', spec, '--repo', str(self.repo.root), '--home', str(self.home), *extra)

    def lines(self, spec='HEAD~1..HEAD', *extra):
        code, out, err = self.risk(spec, *extra)
        self.assertEqual((code, err), (0, ''), out)
        return out.splitlines()


class RegistryTest(RiskCase):
    def test_risk_is_registered_once(self):
        self.assertEqual(cli.COMMANDS.count('risk'), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(['--help'], environ={})
        self.assertRegex(out.getvalue(), r'(?m)^\s+risk\s')

    def test_a_missing_range_is_a_usage_error_on_one_line(self):
        assert_cli_error(self, run_cli('risk', '--home', str(self.home)))


class CoreAreaTest(RiskCase):
    def test_every_core_area_names_its_files_in_a_fixed_order(self):
        self.change('src/auth/login.py', 'src/upload/handler.py', '.env.local', 'package.json', 'src/http_client.py')
        self.assertEqual(self.lines(), [
            'risk areas: auth, input parsing and execution, secrets or config, dependencies, network calls',
            'auth: src/auth/login.py',
            'input parsing and execution: src/upload/handler.py',
            'secrets or config: .env.local',
            'dependencies: package.json',
            'network calls: src/http_client.py',
        ])

    def test_sql_and_migration_files_are_input_and_execution_risks(self):
        self.change('db/schema.sql', 'db/migrations/0001_add_users.py', 'db/Migrate.go')
        self.assertEqual(self.lines(), [
            'risk areas: input parsing and execution',
            'input parsing and execution: db/Migrate.go',
            'input parsing and execution: db/migrations/0001_add_users.py',
            'input parsing and execution: db/schema.sql',
        ])

    def test_a_file_in_two_areas_is_listed_under_both(self):
        self.change('src/auth/config.py')
        self.assertEqual(self.lines(), ['risk areas: auth, secrets or config',
                                        'auth: src/auth/config.py', 'secrets or config: src/auth/config.py'])


    def test_a_diff_that_matches_none_says_so(self):
        self.change('docs/notes.md', 'src/render/chart.py', 'src/ui/button.tsx')
        self.assertEqual(self.lines(), [NO_MATCH])

    def test_only_matching_files_are_named(self):
        self.change('src/auth/login.py', 'docs/notes.md')
        self.assertEqual(self.lines(), ['risk areas: auth', 'auth: src/auth/login.py'])

    def test_the_path_is_read_in_any_letter_case(self):
        self.change('src/Auth/LOGIN.TS')
        self.assertEqual(self.lines(), ['risk areas: auth', 'auth: src/Auth/LOGIN.TS'])

    def test_a_deleted_file_counts_as_touched(self):
        self.change('src/auth/login.py')
        self.change('-src/auth/login.py')
        self.assertEqual(self.lines(), ['risk areas: auth', 'auth: src/auth/login.py'])

    def test_a_renamed_file_is_named_by_its_new_path_and_matches_by_either_path(self):
        self.change('src/util.py', text='the same content, long enough to be a rename\n' * 5)
        (self.repo.root / 'src' / 'util.py').unlink()
        self.repo.write('src/auth.py', 'the same content, long enough to be a rename\n' * 5)
        self.repo.commit(['src/util.py', 'src/auth.py'], 'refactor: rename', date(2026, 10, 3))
        self.assertEqual(self.lines(), ['risk areas: auth', 'auth: src/auth.py'])
        (self.repo.root / 'src' / 'auth.py').unlink()
        self.repo.write('src/plain.py', 'the same content, long enough to be a rename\n' * 5)
        self.repo.commit(['src/auth.py', 'src/plain.py'], 'refactor: rename back', date(2026, 10, 4))
        self.assertEqual(self.lines(), ['risk areas: auth', 'auth: src/plain.py'])

    def test_a_three_dot_range_works_like_a_two_dot_range(self):
        self.change('src/auth/login.py')
        self.assertEqual(self.lines('HEAD~1...HEAD'), ['risk areas: auth', 'auth: src/auth/login.py'])

    def test_commit_ids_and_branch_names_make_a_range(self):
        first = self.repo.git('rev-parse', 'HEAD').strip()
        head = self.change('src/auth/login.py')
        self.assertEqual(self.lines(f'{first[:9]}..{head}'), ['risk areas: auth', 'auth: src/auth/login.py'])

    def test_the_command_writes_nothing(self):
        self.change('src/auth/login.py')
        before = self.repo.status()
        self.lines()
        self.assertEqual(self.repo.status(), before)
        self.assertFalse(self.home.exists())


class RepoLayerTest(RiskCase):
    def test_the_repo_layer_adds_its_own_area_after_the_core_ones(self):
        self.override('src/billing/', 'ops/*.tf')
        self.change('src/auth/login.py', 'src/billing/deep/invoice.py', 'ops/main.tf', 'docs/notes.md')
        self.assertEqual(self.lines(), [
            'risk areas: auth, repo layer',
            'auth: src/auth/login.py',
            'repo layer: ops/main.tf',
            'repo layer: src/billing/deep/invoice.py',
        ])

    def test_a_trailing_slash_means_the_folder_from_the_repository_root(self):
        self.override('src/billing/')
        self.change('src/billing-notes.md', 'lib/src/billing/x.py', 'src/billing/x.py')
        self.assertEqual(self.lines(), ['risk areas: repo layer', 'repo layer: src/billing/x.py'])

    def test_a_pattern_without_a_folder_also_matches_the_file_name_anywhere(self):
        self.override('Makefile')
        self.change('build/Makefile', 'build/Makefile.old')
        self.assertEqual(self.lines(), ['risk areas: repo layer', 'repo layer: build/Makefile'])

    def test_a_repo_layer_glob_is_read_in_the_case_written(self):
        self.override('deploy/')
        self.change('Deploy/b.yaml')
        self.assertEqual(self.lines(), [NO_MATCH])
        self.override('Deploy/')
        self.assertEqual(self.lines(), ['risk areas: repo layer', 'repo layer: Deploy/b.yaml'])

    def test_no_repo_layer_pattern_matching_leaves_the_core_answer(self):
        self.override('src/billing/')
        self.change('docs/notes.md')
        self.assertEqual(self.lines(), [NO_MATCH])

    def test_a_repo_layer_pattern_alone_makes_a_match(self):
        self.override('docs/')
        self.change('docs/notes.md')
        self.assertEqual(self.lines(), ['risk areas: repo layer', 'repo layer: docs/notes.md'])

    def test_an_override_file_without_patterns_adds_nothing(self):
        write_text(self.home / 'repos' / 'repo.md', '---\nverify: run-all\n---\n')
        self.change('docs/notes.md')
        self.assertEqual(self.lines(), [NO_MATCH])


class ErrorTest(RiskCase):
    def test_a_range_that_does_not_resolve_is_one_anomaly_line(self):
        for spec in ('nope..HEAD', 'HEAD..nope', 'nope...nope'):
            with self.subTest(spec=spec):
                assert_cli_error(self, self.risk(spec), 'nope')

    def test_a_revision_that_looks_like_an_option_is_never_passed_to_git(self):
        assert_cli_error(self, self.risk('HEAD..--output=x'), '--output=x')

    def test_something_that_is_not_a_range_is_refused_with_the_two_forms(self):
        code, out, err = self.risk('HEAD')
        assert_cli_error(self, (code, out, err), 'HEAD', 'A..B', 'A...B')

    def test_a_folder_outside_git_is_an_error(self):
        plain = self.root / 'plain'
        plain.mkdir()
        assert_cli_error(self, run_cli('risk', 'a..b', '--repo', str(plain), '--home', str(self.home)))

    def test_a_missing_repo_folder_is_an_error(self):
        assert_cli_error(self, run_cli('risk', 'a..b', '--repo', str(self.root / 'missing'), '--home', str(self.home)),
                         'missing')

    def test_the_error_line_is_a_single_line_even_for_a_long_git_failure(self):
        code, out, err = self.risk('a' * 40 + '..HEAD')
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1, err)
        self.assertTrue(re.match(r'anomaly: ', err), err)


class AreaTableTest(unittest.TestCase):
    def test_each_area_matches_the_paths_the_review_brief_lists(self):
        """A table over risk.match_areas, with no git run per path; the CLI cases above cover the wiring."""
        areas = {
            'auth': ('src/session_store.py', 'web/Logout.tsx', 'lib/permission.dart', 'api/oauth.go', 'api/jwt.go',
                     'web/cookie.ts', 'web/csrf.ts', 'api/role.go', 'api/password.go', 'api/token.go'),
            'input parsing and execution': ('src/yaml_parse.py', 'src/deserialize.py', 'src/pickle_io.py',
                                            'src/multipart.py', 'src/subprocess_run.py', 'src/shell.py',
                                            'src/executor.py'),
            'secrets or config': ('.env', 'app/.env.production', 'src/app_config.py', 'src/settings.py',
                                  '.gitlab-ci.yml', '.github/workflows/test.yml', 'Dockerfile', 'ops/Dockerfile.dev',
                                  'certs/site.pem', 'certs/site.key', 'src/secrets.py'),
            'dependencies': ('package-lock.json', 'yarn.lock', 'pubspec.yaml', 'pubspec.lock', 'go.mod', 'go.sum',
                             'pyproject.toml', 'requirements.txt', 'requirements-dev.txt', 'web/package.json'),
            'network calls': ('src/fetch_all.ts', 'src/axios_setup.ts', 'src/urllib_wrap.py', 'src/requests_wrap.py',
                              'src/socket_io.py', 'src/websocket.dart', 'src/grpc_client.go', 'src/http.py'),
        }
        for area, names in areas.items():
            for name in names:
                with self.subTest(area=area, path=name):
                    found = dict(risk.match_areas([gitrepo.Change('M', name)], ()))
                    self.assertIn(name, found.get(area, []))

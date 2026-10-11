"""Tests for `upstream defect <signature>` (ticket 05), CLI in-process over a temporary home and a temporary
installed copy of the plugin: `<config>/plugins/cache/<marketplace>/<plugin>/<version>`, with the marketplace
record in `<config>/plugins/known_marketplaces.json` (D-40).

`gh` is faked at its wrapper (`FakeIssueGh` for `anomaly_loop.gh.run`, built on `FakeGh` of test_mr.py), and a stub
`gh` first on PATH fails any call that would get past the fake, so no test starts a real `gh` or reaches GitHub.

What the file looks like beyond the title, the symptom, the version and the signature is not fixed by the ticket:
the tests read the printed path, then look for those facts in the file text, and never name where the file is.

Names this file chooses where the ticket leaves them open: the options `--plugin-root` and `--user-config` of the
shared folder_options (as `digest` and `calibrate plan` take them), and `gh issue list` answering JSON with
`number` and `title`. The wrapper calls are tested in test_gh.py; the order of the lines printed is not pinned."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import addenda, records
from tests.fixtures import NOW, GitFixture, assert_cli_error, run_cli, write_anomaly_with, write_text
from tests.test_mr import TOOL_FAILURE, FakeGh, PutSetup, finished, record

SIGNATURE = 'slow-check'
SUMMARY = 'The check runs every test twice.'
VERSION = 'ab12cd3'                 # the folder name of the installed copy, the commit (D-27)
MARKETPLACE = 'market'
REPO = 'owner/plugin'
GITHUB = 'github.com'               # kept out of the https:// text, which test_neutral.py scans for hosts
ISSUES = 'https://{host}/{repo}/issues'
SEARCH_LINK = ISSUES.format(host=GITHUB, repo=REPO)
ISSUE_NUMBER = 42
ISSUE_LINK = f'{SEARCH_LINK}/{ISSUE_NUMBER}'
LOGGED_DAY = NOW.date().isoformat()
NO_REPO = 'no target repository is known'
CHECKOUT_LINE = 'a plugin checkout is set: fix it through an MR'


class FakeIssueGh(FakeGh):
    """FakeGh for the issue calls: `issues` is the list of open (number, title) a list call answers as JSON, a create
    answers the link of the new issue, a comment answers nothing. `failure` set to a text fails every call."""

    def __init__(self):
        super().__init__()
        self.issues = []

    def run(self, *args, environ=None, **kwargs):
        self.records.append(record(args, kwargs))
        self.environs.append(environ)
        if self.failure:
            return finished('gh', args, code=1, stderr=self.failure)
        if 'create' in args:
            stdout = ISSUE_LINK + '\n'
        elif 'comment' in args:
            stdout = ''
        else:
            stdout = json.dumps([{'number': number, 'title': title} for number, title in self.issues])
        return finished('gh', args, stdout)

    def calls(self, word):
        """The recorded calls that have `word` (such as `comment` or `create`) as one of their arguments."""
        return [call for call in self.records if word in call.args]


class UpstreamCase(unittest.TestCase):
    block_real_tools = PutSetup.block_real_tools   # stub `gh` and `glab` first on PATH that exit 97

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.config = self.root / 'config'
        self.plugin = self.config / 'plugins' / 'cache' / MARKETPLACE / 'anomaly' / VERSION
        write_text(self.plugin / '.claude-plugin' / 'plugin.json', '{"name": "anomaly"}\n')
        write_text(self.plugin / 'skills' / 'observe' / 'SKILL.md', '# observe\n')
        write_text(self.plugin / 'agents' / 'facts.md', 'You answer questions.\n')
        write_text(self.plugin / 'anomaly_loop' / 'cli.py', '"""the CLI"""\n')
        self.gh = FakeIssueGh()
        self.block_real_tools()
        patcher = mock.patch('anomaly_loop.gh.run', self.gh.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.set_marketplace({'source': {'source': 'github', 'repo': REPO}})
        self.write_anomaly()

    def set_marketplace(self, entry):
        """The record of the marketplace of the installed copy; None leaves no known_marketplaces.json at all."""
        path = self.config / 'plugins' / 'known_marketplaces.json'
        if entry is None:
            path.unlink(missing_ok=True)
        else:
            write_text(path, json.dumps({MARKETPLACE: entry}))

    def write_profile(self, *lines):
        write_text(self.home / 'profile.md', '\n'.join(['---', *lines, '---', '']))

    def use_gh(self):
        self.write_profile('upstream_tool: gh')

    def write_anomaly(self, target='anomaly:observe', summary=SUMMARY, signature=SIGNATURE):
        write_anomaly_with(self.home, signature, target=target, summary=summary)

    @property
    def anomaly_path(self):
        return self.home / 'anomalies' / f'{SIGNATURE}.md'

    def run_defect(self, *flags, signature=SIGNATURE):
        return run_cli('upstream', 'defect', signature, '--home', str(self.home), '--plugin-root', str(self.plugin),
                       '--user-config', str(self.config), *flags)

    def run_ok(self, *flags, signature=SIGNATURE):
        code, out, err = self.run_defect(*flags, signature=signature)
        self.assertEqual(code, 0, (out, err))
        return out

    def report(self, output, title):
        """The text of the one file whose path the output prints and that holds `title`."""
        paths = {Path(word) for word in output.split() if Path(word).is_file()}
        found = [path for path in paths if title in path.read_text(encoding='utf-8')]
        self.assertEqual(len(found), 1, (title, output))
        return found[0].read_text(encoding='utf-8')

    def tree(self):
        """Path -> bytes of every file under the temporary root."""
        return {path: path.read_bytes() for path in self.root.rglob('*') if path.is_file()}


def title_of(target_word, signature=SIGNATURE):
    return f'[anomaly:{target_word}] {signature}'


class ReportFileTest(UpstreamCase):
    def test_the_file_holds_the_title_the_symptom_the_version_and_the_signature_and_its_path_is_printed(self):
        """AC-18 (D-54, D-27): a skill, an agent and a plugin-code target (the path from the plugin root)."""
        for target, word in (('anomaly:observe', 'observe'), ('anomaly:facts', 'facts'),
                             ('anomaly_loop/cli.py', 'anomaly_loop/cli.py')):
            with self.subTest(target=target):
                self.write_anomaly(target=target)
                title = title_of(word)
                text = self.report(self.run_ok(), title)
                for fact in (title, SUMMARY, VERSION, SIGNATURE):
                    self.assertIn(fact, text)


class CoreDefaultTest(UpstreamCase):
    def test_the_core_default_prints_the_search_link_of_the_target_repository_and_calls_nothing(self):
        """AC-19: the repository comes from the marketplace record."""
        out = self.run_ok()
        self.assertIn(SEARCH_LINK, out)
        self.assertEqual(self.gh.records, [])


class GhSearchTest(UpstreamCase):
    def setUp(self):
        super().setUp()
        self.use_gh()

    def test_open_issues_of_the_target_repository_are_listed_and_an_exact_signature_hit_is_the_plus_one_offer(self):
        """AC-20."""
        hit, other = title_of('observe'), title_of('observe', 'another-signature')
        self.gh.issues = [(12, hit), (13, other)]
        out = self.run_ok()
        self.assertTrue(self.gh.records)
        self.assertIn(REPO, self.gh.records[0].text)
        offers = [line for line in out.splitlines() if '+1' in line]
        self.assertTrue([line for line in offers if hit in line or '#12' in line or ' 12' in line], out)
        self.assertTrue([line for line in out.splitlines() if other in line], out)
        self.assertEqual([line for line in offers if other in line or '13' in line], [], out)

    def test_without_a_flag_nothing_is_written_to_github_and_the_anomaly_is_not_changed(self):
        """AC-21."""
        self.gh.issues = [(12, title_of('observe'))]
        before = self.anomaly_path.read_bytes()
        self.run_ok()
        self.assertEqual(self.gh.calls('comment') + self.gh.calls('create'), [])
        self.assertEqual(self.anomaly_path.read_bytes(), before)


class SecondRunTest(UpstreamCase):
    def setUp(self):
        super().setUp()
        self.use_gh()
        self.gh.issues = [(12, title_of('observe'))]
        self.run_ok()   # the first run: checks, writes the file, searches
        self.before = records.read_anomaly(self.anomaly_path)

    def assert_logged(self, number):
        """The anomaly holds `upstream <date> · <number>` as the last line of its Addenda log, written by log_line."""
        addenda.log_line(self.before, f'upstream {LOGGED_DAY} · {number}')
        self.assertEqual(records.read_anomaly(self.anomaly_path).sections, self.before.sections)

    def test_comment_adds_a_plus_one_comment_to_that_issue_and_logs_the_number(self):
        """AC-21 (D-4, D-41)."""
        self.run_ok('--comment', '12')
        comments = self.gh.calls('comment')
        self.assertEqual(len(comments), 1, self.gh.records)
        self.assertIn('12', comments[0].args)
        self.assertIn(REPO, comments[0].text)
        self.assertIn('+1', comments[0].text)
        self.assertEqual(self.gh.calls('create'), [])
        self.assert_logged(12)

    def test_create_opens_the_issue_from_the_file_and_logs_the_number_of_the_new_issue(self):
        """AC-21 (D-18): the title and the body come from the file written by the first run."""
        self.run_ok('--create')
        creates = self.gh.calls('create')
        self.assertEqual(len(creates), 1, self.gh.records)
        self.assertIn(REPO, creates[0].text)
        self.assertIn(title_of('observe'), creates[0].text)
        self.assertIn(SUMMARY, creates[0].text)
        self.assertEqual(self.gh.calls('comment'), [])
        self.assert_logged(ISSUE_NUMBER)


class RefusalTest(UpstreamCase):
    def test_text_that_fails_check_text_or_holds_a_profile_marker_or_a_repo_layer_name_is_refused_and_no_file_is_written(self):
        """AC-22 (D-12): an email address, a marker from the profile, a file name from `<home>/repos`."""
        write_text(self.home / 'repos' / 'acme-shop.md', '---\nverify: run-all\n---\n')
        self.write_profile('mr_tool: acme-kit:open-mr')
        self.report(self.run_ok(), title_of('observe'))   # a clean text passes the same check and is written
        for summary in ('write to jane.doe@example.com', 'the acme-kit:open-mr call fails', 'it fails in acme-shop.md'):
            with self.subTest(summary=summary):
                self.write_anomaly(summary=summary)
                before = self.tree()
                code, out, err = self.run_defect()
                self.assertNotEqual(code, 0, (out, err))
                self.assertEqual(self.tree(), before)
                self.assertEqual(self.gh.records, [])


class TargetRepositoryTest(UpstreamCase):
    def test_with_no_marketplace_source_and_no_upstream_repo_the_file_is_written_and_the_command_exits_1(self):
        """AC-23: no record at all, and a record whose source is not GitHub."""
        for entry in (None, {'source': {'source': 'git', 'url': 'https://example.com/plugin.git'}}):
            with self.subTest(entry=entry):
                self.set_marketplace(entry)
                code, out, err = self.run_defect()
                self.assertEqual(code, 1, (out, err))
                self.assertIn(NO_REPO, out + err)
                self.report(out + err, title_of('observe'))
                self.assertEqual(self.gh.records, [])

    def test_upstream_repo_names_the_repository_when_no_github_record_exists_and_the_record_wins_otherwise(self):
        """D-40 (D-29): the record first, else the profile key."""
        self.write_profile('upstream_repo: other-owner/other-plugin')
        for entry, expected in ((None, 'other-owner/other-plugin'),
                                (self.entry_of('git'), 'other-owner/other-plugin'),
                                (self.entry_of('github'), REPO)):
            with self.subTest(entry=entry):
                self.set_marketplace(entry)
                out = self.run_ok()
                self.assertIn(ISSUES.format(host=GITHUB, repo=expected), out)

    @staticmethod
    def entry_of(kind):
        return {'source': {'source': kind, 'repo': REPO}}


class CheckoutTest(UpstreamCase):
    def test_a_plugin_checkout_refuses_upstream_defect_with_the_mr_line_and_exits_1(self):
        """AC-24, the `upstream defect` half (D-35): plugin_repo names a git checkout."""
        checkout = GitFixture(self.root / 'checkout')
        checkout.write('README.md', 'a plugin checkout\n')
        checkout.commit(['README.md'], 'chore: base', date(2026, 10, 1))
        self.write_profile('upstream_tool: gh', f'plugin_repo: {checkout.root}')
        code, out, err = self.run_defect()
        self.assertEqual(code, 1, (out, err))
        self.assertIn(CHECKOUT_LINE, out + err)
        self.assertEqual(self.gh.records, [])


class GhFailureTest(UpstreamCase):
    def setUp(self):
        super().setUp()
        self.use_gh()

    def test_a_failed_search_is_one_anomaly_line_and_exit_2(self):
        """AC-25."""
        self.gh.failure = TOOL_FAILURE
        assert_cli_error(self, self.run_defect(), TOOL_FAILURE)

    def test_a_failed_comment_or_create_is_one_anomaly_line_and_exit_2_and_logs_nothing(self):
        """AC-25: the first run works, the second run's call fails."""
        self.run_ok()
        before = self.anomaly_path.read_bytes()
        self.gh.failure = TOOL_FAILURE
        for flags in (('--comment', '12'), ('--create',)):
            with self.subTest(flags=flags):
                assert_cli_error(self, self.run_defect(*flags), TOOL_FAILURE)
                self.assertEqual(self.anomaly_path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()

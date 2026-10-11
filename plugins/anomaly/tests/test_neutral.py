"""The plugin stays free of environment facts: they live only in the profile (ADR-0001).

The environment names are never listed here, because that would put them into the plugin. The check
instead reads the identifiers in the owner's real profile (agent ids, tool and skill names
written with '-' or ':') and looks for them in every plugin file. Without a profile that part is
skipped; the host check needs no profile.
"""
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path

from anomaly_loop import addenda, flags, paths, profile
from anomaly_loop.scans import marker_hits, profile_markers
from tests.fixtures import (BENCH, PLUGIN, GitFixture, plugin_files, run_cli, write_anomaly_with,
                            write_experiment_anomaly, write_text)

HOST = re.compile(r'https?://([A-Za-z0-9.-]+)')
RESERVED_HOST = re.compile(r'(?:.+\.)?(?:example(?:\.com|\.net|\.org)?|test|invalid|localhost)')
ALLOWED_HOSTS = {'host', 'person', 'www.youtube.com', 'api.deps.dev', 'pub.dev'}   # placeholders, a link example, the two pkg-facts API hosts


def files_with(root, markers):
    hits = []
    for path in plugin_files(root):
        text = path.read_text(encoding='utf-8', errors='ignore')
        hits += [f'{path.relative_to(root)}: {m}' for m in marker_hits(text, markers)]
    return hits


class ProfileMarkersTest(unittest.TestCase):
    def test_agent_ids_tools_and_dashed_skills_become_markers_and_stack_names_do_not(self):
        values = {'implementers': 'web-ui: acme-kit:web-builder:acme-web-builder',
                  'mr_tool': 'acme-kit:open-mr skill', 'verify_ui': 'look-check, or the built-in browser',
                  'build_skills': 'implement, run-tickets', 'tracker': 'some-tracker-name'}
        self.assertEqual(profile_markers(values, PLUGIN), {
            'acme-kit:web-builder:acme-web-builder', 'acme-kit', 'web-builder', 'acme-web-builder',
            'acme-kit:open-mr', 'open-mr', 'look-check', 'run-tickets'})

    def test_the_port_keys_become_markers_too(self):
        values = {'test_writers': 'web-ui: acme-kit:test-builder', 'reviewers': '[acme-reviewer, acme-kit:sec-check]',
                  'gather': 'context-pull', 'ci': 'ci-watcher job watch, then log-reader',
                  'conventions': 'web-ui: acme-docs/web-rules.md\nmobile-ui: team-guide.md'}
        self.assertEqual(profile_markers(values, PLUGIN), {
            'acme-kit:test-builder', 'acme-kit', 'test-builder', 'acme-reviewer', 'acme-kit:sec-check', 'sec-check',
            'context-pull', 'ci-watcher', 'acme-docs', 'team-guide'})

    def test_the_upstream_keys_become_markers_too(self):
        """D-47 (Amended): the upstream tool and the upstream repository are the 10th and 11th key."""
        values = {'upstream_tool': 'acme-upstream-bot', 'upstream_repo': 'acme-owner/acme-plugin'}
        self.assertLessEqual({'acme-upstream-bot', 'acme-owner'}, profile_markers(values, PLUGIN))

    def test_a_per_stack_line_without_a_stack_keeps_its_whole_id(self):
        values = {'implementers': 'acme-kit:web-builder\nmobile-ui: acme-kit:app-builder',
                  'conventions': 'acme-docs/rules.md'}
        self.assertEqual(profile_markers(values, PLUGIN), {
            'acme-kit:web-builder', 'acme-kit', 'web-builder', 'acme-kit:app-builder', 'app-builder', 'acme-docs'})

    def test_a_name_qualified_by_this_plugin_is_not_a_marker(self):
        own = flags.plugin_name(PLUGIN, PLUGIN)
        values = {'build_skills': f'implement, {own}:build-step, acme-kit:run-tickets'}
        self.assertEqual(profile_markers(values, PLUGIN), {'acme-kit:run-tickets', 'acme-kit', 'run-tickets'})

    def test_a_planted_marker_is_found_with_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'skills').mkdir()
            (root / 'skills' / 'SKILL.md').write_text('dispatch acme-web-builder here', encoding='utf-8')
            (root / 'clean.py').write_text('nothing to see', encoding='utf-8')
            self.assertEqual(files_with(root, {'acme-web-builder'}),
                             [f'{Path("skills") / "SKILL.md"}: acme-web-builder'])

    def test_a_planted_marker_is_found_in_a_skill_extra_doc_and_in_an_agent_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('skills/build/BRIEF.md', 'agents/code.md'):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text('dispatch acme-web-builder here', encoding='utf-8')
            self.assertEqual(files_with(root, {'acme-web-builder'}),
                             [f'{Path("agents") / "code.md"}: acme-web-builder',
                              f'{Path("skills") / "build" / "BRIEF.md"}: acme-web-builder'])


class EnvironmentNeutralTest(unittest.TestCase):
    def test_no_identifier_from_the_owners_profile_appears_in_a_plugin_file(self):
        home = paths.resolve_home(None, os.environ)
        markers = profile_markers(profile.load_profile(home).values, PLUGIN)
        if not markers:
            self.skipTest(f'no profile identifiers under {home}')
        self.assertEqual(files_with(PLUGIN, markers), [])

    def test_only_reserved_example_hosts_appear_in_plugin_files(self):
        hosts = {(path.relative_to(PLUGIN), host) for path in plugin_files(PLUGIN)
                 for host in HOST.findall(path.read_text(encoding='utf-8', errors='ignore'))}
        self.assertEqual(sorted(f'{path}: {host}' for path, host in hosts
                                if not RESERVED_HOST.fullmatch(host) and host not in ALLOWED_HOSTS), [])


class EmptyProfileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.home, self.data, self.projects = root / 'home', root / 'data', root / 'projects'
        for folder in (self.home, self.data, self.projects):
            folder.mkdir()
        self.ticket = root / '.anomaly' / 'unit' / 'tickets' / '01-a-ticket.md'
        self.ticket.parent.mkdir(parents=True)
        self.ticket.write_text('# 01: A ticket\n\nKey: none\nCovers: AC-1\nBlocked by: None\n'
                               'Status: ready-for-agent\n\n- [ ] AC-1: a criterion\n', encoding='utf-8', newline='\n')
        self.repo = root / 'repo'
        self.repo.mkdir()
        self.defects = BENCH / 'code' / 'defects.json'
        self.findings = root / 'findings.txt'
        self.findings.write_text('- [High] shelf/paging.py:13 — the range stops one short — '
                                 'fix: add one — observed\n', encoding='utf-8', newline='\n')
        git = GitFixture(root / 'git-repo')
        git.write('tests/test_a.py', 'a test\n')
        red = git.commit(['tests/test_a.py'], 'test: red', date(2026, 10, 1))
        git.write('a.py', 'code\n')
        head = git.commit(['a.py'], 'feat: code', date(2026, 10, 2))
        self.git_repo = git.root
        self.head = head
        self.merge_ticket = root / 'pre-merge-ticket.md'
        self.merge_ticket.write_text(f'# 06: Ready\n\nBlocked by: None\nStatus: in-progress\nReviewed: {head}\n'
                                     f'Verified: {head}\nRed: {red} · tests/test_a.py\n',
                                     encoding='utf-8', newline='\n')
        self.seams = root / 'seams.md'
        self.seams.write_text('- a seam · `a.py` · replaces a copy (ticket 01)\n', encoding='utf-8', newline='\n')
        self.run_command('lens', 'tally', 'add', '--session', 's1', '--lens', 'code', '--accepted', '2',
                         '--rejected', '1')
        self.config = root / 'config'   # an installed copy of the plugin outside git, with a GitHub marketplace record
        self.installed = self.config / 'plugins' / 'cache' / 'market' / 'plugin' / 'ab12cd3'
        write_text(self.installed / '.claude-plugin' / 'plugin.json', '{"name": "anomaly"}\n')
        write_text(self.installed / 'skills' / 'observe' / 'SKILL.md', '# observe\n')
        write_text(self.config / 'plugins' / 'known_marketplaces.json',
                   '{"market": {"source": {"source": "github", "repo": "owner/plugin"}}}\n')
        write_anomaly_with(self.home, 'slow-check', target='anomaly:observe')

    def run_command(self, *argv):
        return run_cli(*argv, '--home', str(self.home), '--data', str(self.data))

    def keep_an_addendum(self, signature):
        """A kept experiment whose fix is a tagged line in the addenda file of the installed `observe` skill."""
        addenda.append_line(addenda.addendum_path(self.home, 'observe'), 'Ask which repo before logging.', signature,
                            addenda.stamp(self.installed / 'skills' / 'observe'))
        write_experiment_anomaly(self.home, signature, target='anomaly:observe', metric='active minutes',
                                 guard='rework sightings', fixed_by='2026-09-20 · addenda/observe.md',
                                 check_by='2026-10-01', result='keep', status='fixed',
                                 summary='The check runs every test twice.')

    def test_every_subcommand_runs_on_core_defaults_without_a_profile(self):
        self.keep_an_addendum('slow-tune')
        commands = [
            ('measure', '--projects', str(self.projects)),
            ('index',),
            ('digest', '--plugin-root', str(PLUGIN)),
            ('nudge',),
            ('observe', 'list'),
            ('calibrate', 'plan', '--plugin-root', str(PLUGIN)),
            ('assess', 'check', '--source', 'a plain idea to judge'),
            ('ticket', 'show', str(self.ticket)),
            ('ticket', 'gate', str(self.ticket)),
            ('ticket', 'set-status', str(self.ticket), 'in-progress'),
            ('ticket', 'reviewed', str(self.ticket), self.head, '--repo', str(self.git_repo)),
            ('ticket', 'verified', str(self.ticket), self.head, '--repo', str(self.git_repo)),
            ('ticket', 'red', str(self.ticket), self.head, 'tests/test_a.py', '--repo', str(self.git_repo)),
            ('ticket', 'red', str(self.ticket), '--changed', 'a reason'),
            ('ticket', 'result', str(self.ticket), '--branch', 'feat/a', '--merge', self.head,
             '--repo', str(self.git_repo), '--changed-lines', '0'),
            ('ticket', 'adhoc', 'a small task', '--repo', str(self.projects)),
            ('ports', '--repo', str(self.repo)),
            ('bench', 'score', str(self.defects), str(self.findings)),
            ('check', 'pre-merge', str(self.merge_ticket), '--repo', str(self.git_repo)),
            ('seams', 'add', str(self.seams), '--name', 'a seam', '--owner', 'a.py', '--replaces', 'a copy',
             '--ticket', '06'),
            ('seams', 'prune', str(self.seams), '--repo', str(self.git_repo)),
            ('ci', 'watch', 'HEAD', '--repo', str(self.repo)),
            ('ci', 'log', 'HEAD', '--repo', str(self.repo)),
            ('risk', 'HEAD~1..HEAD', '--repo', str(self.git_repo)),
            ('lens', 'tally', 'add', '--session', 's2', '--lens', 'code', '--accepted', '1', '--rejected', '0'),
            ('lens', 'tally', 'sum', '--session', 's1'),
            ('worklog', 'start', 'a-feature', 'build'),
            ('worklog', 'add', '--feature', 'a-feature', '--stage', 'build', '--session', 's1'),
            ('upstream', 'defect', 'slow-check', '--plugin-root', str(self.installed),
             '--user-config', str(self.config)),
            ('upstream', 'tuning', 'slow-tune', '--plugin-root', str(self.installed),
             '--user-config', str(self.config)),
        ]
        for command in commands:
            with self.subTest(command=command[:2]):
                code, out, err = self.run_command(*command)
                self.assertEqual(code, 0, err)
                self.assertNotIn('Traceback', out + err)

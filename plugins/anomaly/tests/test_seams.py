"""`seams prune` and `seams add` through the CLI, in-process, against a temp git repository and a temp
ledger file (kept outside the repository, like a git-excluded `.anomaly`). The ledger line shape is
`- <name> · <owner file> · replaces <old way> (ticket NN)`."""
import contextlib
import io
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import cli
from tests.fixtures import GitFixture, assert_cli_error, run_cli, write_text

PARSE = 'def parse():\n    pass\n\n\ndef load():\n    pass\n'
LEDGER = """# Seam ledger — demo

- ticket line shapes · `plugins/x/ticket.py` (`parse`, `load`) · replaces the old ticket.mjs (ticket 02)
- port resolution · `plugins/x/ports.py` (`resolve`) · replaces port wiring prose (ticket 03)
- repo identity · `plugins/x/gitrepo.py` · replaces git calls outside gitrepo (ticket 03)
- constants · constants.py · the loop's thresholds
- gone helper · `plugins/x/old.py` (`thing`) · replaces a copy (ticket 01)

A closing note that names plugins/x/old.py but is not a ledger line.
"""


class SeamsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.ledger = self.root / 'ledger' / 'seams.md'
        self.repo = GitFixture(self.root / 'repo')

    def seams(self, action, *argv, ledger=None):
        return run_cli('seams', action, str(ledger or self.ledger), *argv, '--home', str(self.home))

    def read(self):
        return self.ledger.read_bytes().decode('utf-8')


class RegistryTest(SeamsTestCase):
    def test_seams_is_registered_once_and_lists_prune_and_add(self):
        self.assertEqual(cli.COMMANDS.count('seams'), 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(['seams', '--help'], environ={})
        self.assertEqual(sorted(re.findall(r'^    ([a-z-]+)\s{2,}\S', out.getvalue(), re.M)), ['add', 'prune'])

    def test_both_actions_say_they_are_pending_a_verdict_with_no_date_that_goes_stale(self):
        for action in ('add', 'prune'):
            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
                cli.main(['seams', action, '--help'], environ={})
            text = ' '.join(out.getvalue().split())
            self.assertIn('pending verdict', text, action)
            self.assertNotRegex(text, r'\d{4}-\d{2}-\d{2}', action)


class AddTest(SeamsTestCase):
    def add(self, **values):
        fields = dict(name='ledger writer', owner='plugins/anomaly/anomaly_loop/seams.py',
                      replaces='hand edits of seams.md', ticket='06')
        fields.update(values)
        return self.seams('add', '--name', fields['name'], '--owner', fields['owner'],
                          '--replaces', fields['replaces'], '--ticket', fields['ticket'])

    def test_appends_one_line_in_the_ledger_shape(self):
        write_text(self.ledger, LEDGER)
        self.assertEqual(self.add()[0], 0)
        self.assertEqual(self.read(), LEDGER + '- ledger writer · plugins/anomaly/anomaly_loop/seams.py · '
                                               'replaces hand edits of seams.md (ticket 06)\n')

    def test_the_new_line_takes_the_line_ending_of_the_file(self):
        self.ledger.parent.mkdir()
        self.ledger.write_bytes('# Seam ledger\r\n\r\n- a · a.py · replaces b (ticket 01)\r\n'.encode('utf-8'))
        self.assertEqual(self.add()[0], 0)
        self.assertTrue(self.read().endswith('(ticket 06)\r\n'), repr(self.read()))
        self.assertNotIn('\n', self.read().replace('\r\n', ''))

    def test_the_same_line_twice_is_added_once(self):
        write_text(self.ledger, LEDGER)
        self.add()
        before = self.read()
        code, out, err = self.add()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), before)

    def test_a_ledger_that_does_not_exist_yet_is_created_in_an_existing_folder(self):
        self.ledger.parent.mkdir()
        self.assertEqual(self.add()[0], 0)
        self.assertEqual(self.read().count('\n'), 1)

    def test_a_folder_that_does_not_exist_is_an_error(self):
        assert_cli_error(self, self.add(), 'ledger')
        self.assertFalse(self.ledger.parent.exists())

    def test_a_field_that_would_break_the_shape_is_refused_and_nothing_changes(self):
        write_text(self.ledger, LEDGER)
        for values in (dict(name='a · b'), dict(owner='x · y'), dict(replaces='p\nq'), dict(name=' '),
                       dict(ticket='6'), dict(ticket='ab'), dict(ticket='001'),
                       dict(ticket='٠٧')):
            with self.subTest(values=values):
                assert_cli_error(self, self.add(**values))
                self.assertEqual(self.read(), LEDGER)

    def test_a_missing_option_is_a_usage_error_on_one_line(self):
        assert_cli_error(self, self.seams('add', '--name', 'x'))

    def test_a_ledger_path_of_a_dash_is_refused_and_no_file_is_made(self):
        folder = self.root / 'cwd'
        folder.mkdir()
        previous = os.getcwd()
        self.addCleanup(os.chdir, previous)
        os.chdir(folder)
        with mock.patch('sys.stdin', io.TextIOWrapper(io.BytesIO(b''))):
            assert_cli_error(self, self.add_to('-'), 'standard input')
        self.assertEqual(list(folder.iterdir()), [])

    def add_to(self, ledger):
        return self.seams('add', '--name', 'n', '--owner', 'o.py', '--replaces', 'r', '--ticket', '06', ledger=ledger)


class PruneTest(SeamsTestCase):
    """The merge's changes are the diff of the merge commit against its first parent."""

    def setUp(self):
        super().setUp()
        for path, text in (('plugins/x/ticket.py', PARSE), ('plugins/x/ports.py', 'def resolve():\n    pass\n'),
                           ('plugins/x/gitrepo.py', 'def run():\n    pass\n'), ('constants.py', 'A = 1\n'),
                           ('plugins/x/old.py', 'def thing():\n    pass\n')):
            self.repo.write(path, text)
        self.repo.git('add', '-A')
        self.repo.git('commit', '-q', '-m', 'base', when=date(2026, 10, 1))
        write_text(self.ledger, LEDGER)

    def change(self, message='change'):
        self.repo.git('add', '-A')
        self.repo.git('commit', '-q', '-m', message, when=date(2026, 10, 2))

    def prune(self, *argv):
        return run_cli('seams', 'prune', str(self.ledger), '--repo', str(self.repo.root), '--home', str(self.home),
                       *argv)

    def test_a_ledger_in_a_work_unit_folder_is_pruned_and_added_to(self):
        """`.anomaly/<work-unit>/seams.md`, the ledger of a work unit."""
        self.repo.git('rm', '-q', '--', 'plugins/x/old.py')
        self.change()
        ledger = self.repo.root / '.anomaly' / 'unit' / 'seams.md'
        write_text(ledger, LEDGER)
        pruned = self.seams('prune', '--repo', str(self.repo.root), ledger=ledger)
        added = self.seams('add', '--name', 'n', '--owner', 'o.py', '--replaces', 'r', '--ticket', '06', ledger=ledger)
        self.assertEqual(pruned[0], 0, pruned)
        self.assertIn('gone helper', pruned[1])
        self.assertEqual(added[0], 0, added)

    def test_a_deleted_owner_file_removes_its_line_and_lists_it(self):
        self.repo.git('rm', '-q', '--', 'plugins/x/old.py')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), ''.join(line for line in LEDGER.splitlines(keepends=True)
                                              if not line.startswith('- gone helper')))
        listed = [line for line in out.splitlines() if 'plugins/x/old.py' in line]
        self.assertEqual(len(listed), 1, out)
        self.assertIn('deleted', listed[0])
        self.assertIn('gone helper', listed[0])

    def test_a_renamed_owner_file_gets_its_new_path_and_is_listed(self):
        self.repo.git('mv', 'plugins/x/ports.py', 'plugins/x/portal.py')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), LEDGER.replace('`plugins/x/ports.py`', '`plugins/x/portal.py`'))
        listed = [line for line in out.splitlines() if 'ports.py' in line]
        self.assertEqual(len(listed), 1, out)
        self.assertIn('renamed', listed[0])
        self.assertIn('portal.py', listed[0])

    def test_a_reshaped_owner_file_loses_its_line_when_a_named_helper_is_gone(self):
        self.repo.write('plugins/x/ticket.py', 'def parse():\n    pass\n')   # `load` is gone
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertNotIn('ticket line shapes', self.read())
        self.assertIn('reshaped', [line for line in out.splitlines() if 'ticket line shapes' in line][0])
        self.assertEqual(self.read(), ''.join(line for line in LEDGER.splitlines(keepends=True)
                                              if not line.startswith('- ticket line shapes')))

    def test_a_changed_owner_file_that_still_holds_every_named_helper_is_left_alone(self):
        self.repo.write('plugins/x/ticket.py', PARSE + '\n\ndef more():\n    pass\n')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), LEDGER)
        self.assertNotIn('ticket line shapes', out)

    def test_a_name_inside_a_longer_word_does_not_keep_a_line_alive(self):
        self.repo.write('plugins/x/ticket.py', 'def parse_all():\n    pass\n\n\ndef load():\n    pass\n')
        self.change()
        self.prune()
        self.assertNotIn('ticket line shapes', self.read())

    def test_a_line_with_a_bare_owner_file_name_matches_by_the_end_of_the_path(self):
        self.repo.git('rm', '-q', '--', 'constants.py')
        self.change()
        self.prune()
        self.assertNotIn('- constants ·', self.read())

    def test_lines_that_are_not_ledger_lines_and_untouched_lines_stay_byte_for_byte(self):
        self.repo.git('rm', '-q', '--', 'plugins/x/old.py')
        self.change()
        self.prune()
        for kept in ('# Seam ledger — demo\n\n', '- repo identity ·', 'A closing note that names plugins/x/old.py'):
            self.assertIn(kept, self.read())

    def test_nothing_changed_for_the_ledger_prints_that_and_leaves_the_file_alone(self):
        self.repo.write('unrelated.txt', 'x\n')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), LEDGER)
        self.assertEqual(len(out.splitlines()), 1, out)

    def test_dry_run_lists_and_does_not_rewrite(self):
        self.repo.git('rm', '-q', '--', 'plugins/x/old.py')
        self.change()
        code, out, err = self.prune('--dry-run')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('deleted', out)
        self.assertEqual(self.read(), LEDGER)

    def test_a_second_run_finds_nothing_more(self):
        self.repo.git('rm', '-q', '--', 'plugins/x/old.py')
        self.change()
        self.prune()
        after = self.read()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), after)

    def test_merge_names_the_merge_commit_and_a_no_ff_merge_is_read_against_its_first_parent(self):
        base = self.repo.git('rev-parse', '--abbrev-ref', 'HEAD').strip()
        self.repo.git('switch', '-q', '-c', 'feature')
        self.repo.git('rm', '-q', '--', 'plugins/x/old.py')
        self.repo.git('mv', 'plugins/x/ports.py', 'plugins/x/portal.py')
        self.change('feature work')
        self.repo.git('switch', '-q', base)
        self.repo.write('elsewhere.txt', 'x\n')
        self.change('other work on the base')
        self.repo.git('merge', '-q', '--no-ff', '-m', 'merge feature', 'feature', when=date(2026, 10, 3))
        self.repo.write('later.txt', 'x\n')
        self.change('a later commit')
        merge = self.repo.git('rev-parse', 'HEAD~1').strip()
        code, out, err = self.prune('--merge', merge)
        self.assertEqual((code, err), (0, ''), out)
        self.assertNotIn('gone helper', self.read())
        self.assertIn('`plugins/x/portal.py`', self.read())

    def test_a_rename_rewrites_the_owner_field_and_never_the_name_or_the_rest(self):
        line = '- plugins/x/ports.py wrapper · `plugins/x/ports.py` (`resolve`) · replaces plugins/x/ports.py copies (ticket 03)\n'
        write_text(self.ledger, line)
        self.repo.git('mv', 'plugins/x/ports.py', 'plugins/x/portal.py')
        self.change()
        self.assertEqual(self.prune()[0], 0)
        self.assertEqual(self.read(), line.replace('`plugins/x/ports.py`', '`plugins/x/portal.py`'))

    def add_files(self, *names):
        for path in names:
            self.repo.write(path, 'x = 1\n')
        self.change('add files')

    def test_a_bare_owner_that_matches_two_changed_files_is_listed_as_ambiguous_and_left_alone(self):
        self.add_files('lib/paths.py', 'tests/paths.py')
        line = '- shared helper · paths.py · replaces copies (ticket 01)\n'
        write_text(self.ledger, line)
        self.repo.git('rm', '-q', '--', 'tests/paths.py', 'lib/paths.py')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), line)
        listed = [text for text in out.splitlines() if text.startswith('ambiguous')]
        self.assertEqual(len(listed), 1, out)
        self.assertIn('lib/paths.py', listed[0])

    def test_a_bare_owner_prefers_the_file_with_exactly_that_path(self):
        self.add_files('lib/paths.py', 'paths.py')
        line = '- shared helper · paths.py · replaces copies (ticket 01)\n'
        write_text(self.ledger, line)
        self.repo.git('rm', '-q', '--', 'lib/paths.py')
        self.repo.write('paths.py', 'x = 2\n')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), line)
        self.assertNotIn('ambiguous', out)

    def test_a_ledger_that_does_not_exist_is_an_error(self):
        self.ledger.unlink()
        assert_cli_error(self, self.prune(), 'ledger')

    def test_a_merge_that_is_not_a_commit_is_an_error(self):
        assert_cli_error(self, self.prune('--merge', 'no-such-commit'), 'no-such-commit')

    def two_path_line(self):
        """A ledger line whose owner field lists two files, each with its own name."""
        self.repo.write('plugins/x/a.py', 'def one():\n    pass\n')
        self.repo.write('plugins/x/b.py', 'def two():\n    pass\n')
        self.change('add the two owner files')
        line = '- pair · `plugins/x/a.py` (`one`), `plugins/x/b.py` (`two`) · replaces a copy (ticket 01)\n'
        write_text(self.ledger, line)
        return line

    def test_a_change_to_the_first_of_two_owner_files_that_holds_its_own_name_keeps_the_line(self):
        line = self.two_path_line()
        self.repo.write('plugins/x/a.py', 'def one():\n    pass\n\n\ndef more():\n    pass\n')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), line)
        self.assertNotIn('pair', out)

    def test_a_change_to_the_second_of_two_owner_files_that_lost_its_own_name_removes_the_line(self):
        self.two_path_line()
        self.repo.write('plugins/x/b.py', 'def other():\n    pass\n')   # `two` is gone
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), '')
        self.assertIn('reshaped', [line for line in out.splitlines() if 'pair' in line][0])

    def test_a_span_outside_parentheses_that_is_not_a_file_is_a_name_of_the_path_before_it(self):
        self.repo.write('plugins/x/a.py', 'def one():\n    pass\n\n\nLIMIT = 1\n')
        self.change('add the owner file')
        write_text(self.ledger, '- plus · `plugins/x/a.py` (`one`) + `constants.LIMIT` · replaces a copy (ticket 01)\n')
        self.repo.write('plugins/x/a.py', 'def one():\n    pass\n')   # `LIMIT` is gone
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), '')
        self.assertIn('reshaped', [line for line in out.splitlines() if 'plus' in line][0])

    def test_an_ambiguous_owner_path_wins_over_a_rename_of_another_path_of_the_line(self):
        self.repo.write('plugins/x/b.py', 'def two():\n    pass\n')
        self.add_files('lib/paths.py', 'tests/paths.py')
        line = '- pair · paths.py (`one`), `plugins/x/b.py` (`two`) · replaces copies (ticket 01)\n'
        write_text(self.ledger, line)
        self.repo.write('lib/paths.py', 'x = 2\n')
        self.repo.write('tests/paths.py', 'x = 2\n')
        self.repo.git('mv', 'plugins/x/b.py', 'plugins/x/c.py')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), line)
        listed = [text for text in out.splitlines() if 'pair' in text]
        self.assertEqual(len(listed), 1, out)
        self.assertTrue(listed[0].startswith('ambiguous'), listed[0])

    def test_a_rename_of_the_second_of_two_owner_files_rewrites_only_that_path(self):
        line = self.two_path_line()
        self.repo.git('mv', 'plugins/x/b.py', 'plugins/x/c.py')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), line.replace('`plugins/x/b.py`', '`plugins/x/c.py`'))
        listed = [text for text in out.splitlines() if 'pair' in text]
        self.assertEqual(len(listed), 1, out)
        self.assertTrue(listed[0].startswith('renamed'), listed[0])

    def test_a_bare_file_name_with_an_extension_is_an_owner_path_and_keeps_its_bare_form_when_renamed(self):
        self.repo.write('plugins/x/a.md', '# a\n')
        self.repo.write('plugins/x/b.md', '# b\n')
        self.change('add the two docs')
        line = '- docs pair · `plugins/x/a.md`, `b.md` · replaces copies (ticket 01)\n'
        write_text(self.ledger, line)
        self.repo.git('mv', 'plugins/x/b.md', 'plugins/x/c.md')
        self.change()
        code, out, err = self.prune()
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(self.read(), line.replace('`b.md`', '`c.md`'))
        listed = [text for text in out.splitlines() if 'docs pair' in text]
        self.assertEqual(len(listed), 1, out)
        self.assertTrue(listed[0].startswith('renamed'), listed[0])

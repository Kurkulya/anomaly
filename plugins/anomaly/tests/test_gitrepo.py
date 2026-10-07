import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import gitrepo, profile
from tests.fixtures import GitFixture


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = GitFixture(self.root / 'repo')


class FindRepoTest(RepoCase):
    def test_a_folder_a_file_and_a_path_not_yet_created_find_the_repository(self):
        self.repo.write('sub/note.md', 'x\n')
        for path in (self.repo.root, self.repo.root / 'sub', self.repo.root / 'sub' / 'note.md',
                     self.repo.root / 'sub' / 'not-yet' / 'file.md'):
            with self.subTest(path=path.name):
                self.assertEqual(gitrepo.find_repo(path), self.repo.root)

    def test_a_folder_outside_any_repository_is_none(self):
        outside = self.root / 'plain'
        outside.mkdir()
        self.assertIsNone(gitrepo.find_repo(outside))
        self.assertIsNone(gitrepo.find_repo(outside / 'missing' / 'file.md'))


class RedirectingEnvironmentTest(RepoCase):
    def test_git_variables_that_redirect_a_command_are_ignored_by_the_helper_and_the_fixture(self):
        other = GitFixture(self.root / 'other')
        redirect = {'GIT_DIR': str(other.root / '.git'), 'GIT_WORK_TREE': str(other.root)}
        with mock.patch.dict(os.environ, redirect):
            inside = GitFixture(self.root / 'inside')
            self.assertEqual(gitrepo.find_repo(inside.root), inside.root)
        self.assertTrue((inside.root / '.git').is_dir())


class IgnoredCopyTest(RepoCase):
    """The installed plugin is a git-ignored copy inside the user config repository."""

    def setUp(self):
        super().setUp()
        self.repo.write('.gitignore', 'cache/\n*.tmp\n')
        self.repo.write('kept.md', 'k\n')
        self.repo.commit(['.gitignore', 'kept.md'], 'chore: start', date(2026, 9, 1))
        self.repo.write('cache/plugin/skill.md', 's\n')
        self.repo.write('note.tmp', 'n\n')

    def test_an_ignored_folder_file_and_path_beneath_have_no_repository(self):
        for path in ('cache', 'cache/plugin', 'cache/plugin/skill.md', 'note.tmp', 'cache/plugin/not-yet/x.md'):
            with self.subTest(path=path):
                self.assertIsNone(gitrepo.find_repo(self.repo.root / path))

    def test_a_path_that_is_not_ignored_still_finds_the_repository(self):
        self.assertEqual(gitrepo.find_repo(self.repo.root / 'kept.md'), self.repo.root)
        self.assertEqual(gitrepo.find_repo(self.repo.root / 'cache-not'), self.repo.root)

    def test_the_repository_root_is_never_ignored(self):
        self.assertEqual(gitrepo.find_repo(self.repo.root), self.repo.root)


class PluginRepoTest(RepoCase):
    def setUp(self):
        super().setUp()
        fake_user_folder = {'HOME': str(self.root), 'USERPROFILE': str(self.root)}
        patcher = mock.patch.dict(os.environ, fake_user_folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo.write('.gitignore', 'cache/\n')
        self.repo.write('plugins/anomaly/a.md', 'a\n')
        self.repo.commit(['.gitignore', 'plugins/anomaly/a.md'], 'chore: start', date(2026, 9, 1))
        self.repo.write('cache/anomaly/a.md', 'a\n')
        self.copy = self.repo.root / 'cache' / 'anomaly'
        self.source = GitFixture(self.root / 'source')
        self.source.write('plugins/anomaly/a.md', 'a\n')
        self.source.commit(['plugins/anomaly/a.md'], 'chore: start', date(2026, 9, 1))

    def profile(self, **values):
        return profile.Profile(values=values, exists=True)

    def test_a_real_checkout_is_its_own_repository_whatever_the_profile_says(self):
        folder = self.repo.root / 'plugins' / 'anomaly'
        found = gitrepo.plugin_repo(folder, self.profile(plugin_repo=str(self.source.root / 'plugins' / 'anomaly')))
        self.assertEqual(found, (self.repo.root, folder))

    def test_an_ignored_copy_uses_the_profile_key(self):
        folder = self.source.root / 'plugins' / 'anomaly'
        found = gitrepo.plugin_repo(self.copy, self.profile(plugin_repo=str(folder)))
        self.assertEqual(found, (self.source.root, folder))

    def test_the_profile_folder_may_use_a_tilde(self):
        found = gitrepo.plugin_repo(self.copy, self.profile(plugin_repo='~/source/plugins/anomaly'))
        self.assertEqual(found, (self.source.root, self.source.root / 'plugins' / 'anomaly'))

    def test_an_ignored_copy_without_a_usable_key_has_no_repository(self):
        plain = self.root / 'plain'
        plain.mkdir()
        for values in ({}, {'plugin_repo': ''}, {'plugin_repo': '<path to the plugin repository>'},
                       {'plugin_repo': str(plain)}, {'plugin_repo': str(self.root / 'missing')}):
            with self.subTest(values=values):
                self.assertIsNone(gitrepo.plugin_repo(self.copy, self.profile(**values)))
        self.assertIsNone(gitrepo.plugin_repo(self.copy, profile.Profile(values={}, exists=False)))

    def test_a_key_that_names_an_ignored_folder_gives_no_repository(self):
        self.assertIsNone(gitrepo.plugin_repo(self.copy, self.profile(plugin_repo=str(self.copy))))

    def test_the_skipped_notice_names_the_profile_key(self):
        self.assertIn('plugin_repo', gitrepo.PLUGIN_REPO_SKIPPED)


class CommitPathsTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.repo.write('home/a.md', 'a1\n')
        self.repo.write('other/b.md', 'b1\n')
        self.repo.commit(['home/a.md', 'other/b.md'], 'chore: start', date(2026, 9, 1))

    def committed(self, sha):
        """The files a commit changed."""
        return self.repo.git('show', '--name-only', '--format=', sha).split()

    def message(self, sha):
        return self.repo.git('show', '--no-patch', '--format=%B', sha).strip()

    def test_commits_a_changed_and_a_new_file_with_the_message(self):
        self.repo.write('home/a.md', 'a2\n')
        self.repo.write('home/new.md', 'n\n')
        sha = gitrepo.commit_paths(self.repo.root, [self.repo.root / 'home'], 'docs(home): record notes')
        self.assertEqual(self.committed(sha), ['home/a.md', 'home/new.md'])
        self.assertEqual(self.message(sha), 'docs(home): record notes')
        self.assertEqual(self.repo.status(), [])

    def test_accepts_paths_relative_to_the_repository_and_a_message_that_starts_with_a_dash(self):
        self.repo.write('home/a.md', 'a2\n')
        sha = gitrepo.commit_paths(self.repo.root, ['home/a.md'], '-odd message')
        self.assertEqual((self.committed(sha), self.message(sha)), (['home/a.md'], '-odd message'))

    def test_commits_a_deleted_file(self):
        (self.repo.root / 'home' / 'a.md').unlink()
        sha = gitrepo.commit_paths(self.repo.root, ['home/a.md'], 'chore: drop a')
        self.assertEqual(self.committed(sha), ['home/a.md'])
        self.assertEqual(self.repo.status(), [])

    def test_foreign_edits_stay_out_of_the_commit_and_stay_as_they_were(self):
        self.repo.write('other/b.md', 'b2 unstaged\n')
        self.repo.write('other/c.md', 'c staged\n')
        self.repo.git('add', 'other/c.md')
        self.repo.write('home/a.md', 'a2\n')
        sha = gitrepo.commit_paths(self.repo.root, ['home/a.md'], 'chore: only a')
        self.assertEqual(self.committed(sha), ['home/a.md'])
        self.assertEqual(sorted(self.repo.status()), [' M other/b.md', 'A  other/c.md'])
        self.assertEqual((self.repo.root / 'other' / 'b.md').read_text(encoding='utf-8'), 'b2 unstaged\n')

    def test_a_foreign_staged_edit_to_a_tracked_file_is_not_committed(self):
        self.repo.write('other/b.md', 'b2 staged\n')
        self.repo.git('add', 'other/b.md')
        self.repo.write('home/a.md', 'a2\n')
        sha = gitrepo.commit_paths(self.repo.root, ['home/a.md'], 'chore: only a')
        self.assertEqual(self.committed(sha), ['home/a.md'])
        self.assertEqual(self.repo.status(), ['M  other/b.md'])

    def test_nothing_changed_in_the_paths_makes_no_commit_even_with_foreign_changes(self):
        self.repo.write('other/b.md', 'b2 staged\n')
        self.repo.git('add', 'other/b.md')
        before = self.repo.git('rev-parse', 'HEAD')
        self.assertIsNone(gitrepo.commit_paths(self.repo.root, ['home'], 'chore: nothing'))
        self.assertEqual(self.repo.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.repo.status(), ['M  other/b.md'])

    def test_a_glob_character_in_a_path_is_taken_literally(self):
        self.repo.write('home/x1.md', 'one\n')
        self.repo.write('home/x[1].md', 'bracket\n')
        sha = gitrepo.commit_paths(self.repo.root, ['home/x[1].md'], 'chore: literal')
        self.assertEqual(self.committed(sha), ['home/x[1].md'])
        self.assertEqual(self.repo.status(), ['?? home/x1.md'])

    def test_a_path_outside_the_repository_is_an_error(self):
        with self.assertRaises(gitrepo.GitError) as raised:
            gitrepo.commit_paths(self.repo.root, [self.root / 'elsewhere.md'], 'chore: no')
        self.assertIn('elsewhere.md', str(raised.exception))

    def test_a_path_that_neither_exists_nor_is_tracked_is_an_error(self):
        with self.assertRaises(gitrepo.GitError) as raised:
            gitrepo.commit_paths(self.repo.root, ['home/never.md'], 'chore: no')
        self.assertIn('never.md', str(raised.exception))

    def test_the_repository_root_is_refused_as_a_path(self):
        self.repo.write('home/a.md', 'a2\n')
        for path in ('.', self.repo.root, 'home/..'):
            with self.subTest(path=str(path)), self.assertRaises(gitrepo.GitError):
                gitrepo.commit_paths(self.repo.root, [path], 'chore: everything')
        self.assertEqual(self.repo.status(), [' M home/a.md'])

    def fail_commits_with(self, text, repo=None):
        hook = (repo or self.repo).root / '.git' / 'hooks' / 'pre-commit'
        hook.parent.mkdir(exist_ok=True)
        hook.write_text('#!/bin/sh\n' + text + '\nexit 1\n', encoding='utf-8', newline='\n')
        hook.chmod(0o755)

    def test_a_failing_hook_leaves_nothing_of_ours_staged_and_foreign_staging_alone(self):
        self.repo.write('other/b.md', 'b2 staged\n')
        self.repo.git('add', 'other/b.md')
        self.repo.write('home/a.md', 'a2\n')
        self.repo.write('home/new.md', 'n\n')
        self.fail_commits_with('echo hook says no >&2')
        with self.assertRaises(gitrepo.GitError) as raised:
            gitrepo.commit_paths(self.repo.root, ['home'], 'chore: refused')
        self.assertIn('hook says no', str(raised.exception))
        self.assertEqual(sorted(self.repo.status()), [' M home/a.md', '?? home/new.md', 'M  other/b.md'])
        self.assertEqual(self.repo.git('diff', '--cached', '--name-only').split(), ['other/b.md'])

    def test_a_failing_hook_in_a_repository_without_commits_leaves_the_new_file_untracked(self):
        fresh = GitFixture(self.root / 'fresh')
        fresh.write('a.md', 'a\n')
        self.fail_commits_with('', repo=fresh)
        with self.assertRaises(gitrepo.GitError):
            gitrepo.commit_paths(fresh.root, ['a.md'], 'chore: refused')
        self.assertEqual(fresh.status(), ['?? a.md'])

    def test_the_error_shows_the_reason_without_warning_and_hint_lines(self):
        self.repo.write('home/a.md', 'a2\n')
        self.fail_commits_with('echo "warning: be careful" >&2; echo "hint: try again" >&2; echo real reason >&2')
        with self.assertRaises(gitrepo.GitError) as raised:
            gitrepo.commit_paths(self.repo.root, ['home/a.md'], 'chore: refused')
        message = str(raised.exception)
        self.assertIn('real reason', message)
        self.assertNotIn('warning:', message)
        self.assertNotIn('hint:', message)

    def test_an_ignored_file_among_the_paths_is_left_alone(self):
        self.repo.write('.gitignore', '*.log\n')
        self.repo.commit(['.gitignore'], 'chore: ignore logs', date(2026, 9, 2))
        self.repo.write('home/a.md', 'a2\n')
        self.repo.write('home/debug.log', 'noise\n')
        sha = gitrepo.commit_paths(self.repo.root, ['home/a.md', 'home/debug.log'], 'chore: a only')
        self.assertEqual(self.committed(sha), ['home/a.md'])
        self.assertEqual(self.repo.status(), [])

    def test_only_ignored_paths_make_no_commit(self):
        self.repo.write('.gitignore', '*.log\n')
        self.repo.commit(['.gitignore'], 'chore: ignore logs', date(2026, 9, 2))
        self.repo.write('home/debug.log', 'noise\n')
        before = self.repo.git('rev-parse', 'HEAD')
        self.assertIsNone(gitrepo.commit_paths(self.repo.root, ['home/debug.log'], 'chore: nothing'))
        self.assertEqual(self.repo.git('rev-parse', 'HEAD'), before)

    def test_a_repository_without_commits_takes_a_first_commit(self):
        fresh = GitFixture(self.root / 'fresh')
        fresh.write('a.md', 'a\n')
        self.assertTrue(gitrepo.commit_paths(fresh.root, ['a.md'], 'chore: first'))
        self.assertEqual(fresh.status(), [])


class HistoryTest(RepoCase):
    def setUp(self):
        super().setUp()
        for day, text in ((date(2026, 9, 1), '1'), (date(2026, 9, 10), '2'), (date(2026, 9, 20), '3'),
                          (date(2026, 10, 1), '4')):
            self.repo.write('tracked/f.md', text)
            self.repo.commit(['tracked/f.md'], f'edit {text}', day)
        self.repo.write('elsewhere.md', 'e')
        self.repo.commit(['elsewhere.md'], 'edit elsewhere', date(2026, 10, 2))

    def count(self, path, since, until):
        return gitrepo.commit_count(self.repo.root, path, since, until)

    def test_counts_commits_touching_the_path_with_both_bounds_included(self):
        self.assertEqual(self.count('tracked/f.md', date(2026, 9, 1), date(2026, 10, 1)), 4)
        self.assertEqual(self.count('tracked/f.md', date(2026, 9, 10), date(2026, 9, 20)), 2)
        self.assertEqual(self.count('tracked/f.md', date(2026, 9, 11), date(2026, 9, 19)), 0)

    def test_a_folder_counts_commits_touching_anything_inside_and_other_paths_do_not(self):
        self.assertEqual(self.count('tracked', date(2026, 9, 1), date(2026, 10, 31)), 4)
        self.assertEqual(self.count(self.repo.root / 'tracked', date(2026, 9, 1), date(2026, 10, 31)), 4)
        self.assertEqual(self.count('elsewhere.md', date(2026, 9, 1), date(2026, 10, 31)), 1)

    def test_an_untracked_path_and_an_empty_window_count_zero(self):
        self.assertEqual(self.count('nothing.md', date(2026, 1, 1), date(2026, 12, 31)), 0)
        self.assertEqual(self.count('tracked', date(2026, 10, 5), date(2026, 10, 4)), 0)

    def test_a_repository_without_commits_counts_zero_and_has_no_first_commit(self):
        fresh = GitFixture(self.root / 'fresh')
        self.assertEqual(gitrepo.commit_count(fresh.root, 'a.md', date(2026, 1, 1), date(2026, 12, 31)), 0)
        self.assertIsNone(gitrepo.first_commit_date(fresh.root, 'a.md'))

    def test_first_commit_date_of_a_file_and_of_a_folder(self):
        self.assertEqual(gitrepo.first_commit_date(self.repo.root, 'tracked/f.md'), date(2026, 9, 1))
        self.assertEqual(gitrepo.first_commit_date(self.repo.root, 'tracked'), date(2026, 9, 1))
        self.assertEqual(gitrepo.first_commit_date(self.repo.root, 'elsewhere.md'), date(2026, 10, 2))

    def test_first_commit_date_is_none_for_an_untracked_or_missing_path(self):
        self.repo.write('draft.md', 'draft\n')
        self.assertIsNone(gitrepo.first_commit_date(self.repo.root, 'draft.md'))
        self.assertIsNone(gitrepo.first_commit_date(self.repo.root, 'missing.md'))

    def test_a_path_outside_the_repository_is_an_error(self):
        with self.assertRaises(gitrepo.GitError):
            gitrepo.first_commit_date(self.repo.root, self.root / 'elsewhere.md')


if __name__ == '__main__':
    unittest.main()


class RepoIdentityTest(RepoCase):
    def test_the_origin_url_is_the_remote_as_written_or_empty_without_an_origin(self):
        self.assertEqual(gitrepo.origin_url(self.repo.root), '')
        self.repo.git('remote', 'add', 'origin', 'git@example.invalid:group/sub/demo.git')
        self.assertEqual(gitrepo.origin_url(self.repo.root), 'git@example.invalid:group/sub/demo.git')

    def test_the_origin_name_is_the_last_part_of_the_url_without_git(self):
        self.assertIsNone(gitrepo.origin_name(self.repo.root))
        self.repo.git('remote', 'add', 'origin', 'https://example.invalid/group/demo-repo.git')
        for url, name in (('https://example.invalid/group/demo-repo.git', 'demo-repo'),
                          ('git@example.invalid:group/other.git', 'other'),
                          ('https://example.invalid/group/plain/', 'plain'),
                          (str(self.root / 'upstream'), 'upstream')):
            with self.subTest(url=url):
                self.repo.git('remote', 'set-url', 'origin', url)
                self.assertEqual(gitrepo.origin_name(self.repo.root), name)

    def test_an_origin_url_whose_last_part_is_only_dots_or_git_has_no_name(self):
        self.repo.git('remote', 'add', 'origin', 'https://example.invalid/group/..')
        for url in ('https://example.invalid/group/..', 'https://example.invalid/group/...',
                    'https://example.invalid/group/.git'):
            with self.subTest(url=url):
                self.repo.git('remote', 'set-url', 'origin', url)
                self.assertIsNone(gitrepo.origin_name(self.repo.root))

    def test_the_origin_default_branch_is_a_git_error_when_git_fails(self):
        """No origin HEAD gives None (the repo-layer base tests in test_ports cover it); any other git
        failure, here a folder outside a repository, is a GitError."""
        plain = self.root / 'plain'
        plain.mkdir()
        with self.assertRaises(gitrepo.GitError):
            gitrepo.origin_default_branch(plain)

    def test_the_main_checkout_of_a_checkout_and_of_its_worktree(self):
        self.repo.write('a.md', 'a\n')
        self.repo.commit(['a.md'], 'chore: start', date(2026, 10, 1))
        worktree = self.root / 'side-tree'
        self.repo.git('worktree', 'add', '-q', '-b', 'side', str(worktree))
        self.assertEqual(gitrepo.main_checkout(self.repo.root), self.repo.root)
        self.assertEqual(gitrepo.main_checkout(worktree), self.repo.root)

    def test_a_git_folder_not_named_dot_git_still_gives_the_working_folder(self):
        working = self.root / 'working'
        self.repo.git('init', '-q', '--separate-git-dir', str(self.root / 'store'), str(working))
        self.assertEqual(gitrepo.main_checkout(working), working)

    def test_a_worktree_of_a_separate_git_folder_falls_back_to_its_own_top_folder(self):
        working, worktree = self.root / 'working', self.root / 'working-tree'
        self.repo.git('init', '-q', '--separate-git-dir', str(self.root / 'store'), str(working))
        self.repo.git('-C', str(working), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-q', '--allow-empty', '-m', 'chore: start')
        self.repo.git('-C', str(working), 'worktree', 'add', '-q', '-b', 'side', str(worktree))
        self.assertEqual(gitrepo.main_checkout(worktree), worktree)


class ResolveCommitTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.repo.write('a.md', 'a\n')
        self.first = self.repo.commit(['a.md'], 'chore: start', date(2026, 10, 1))
        self.repo.write('b.md', 'b\n')
        self.second = self.repo.commit(['b.md'], 'chore: more', date(2026, 10, 2))

    def test_a_full_id_a_short_id_and_a_ref_all_give_the_full_id(self):
        branch = self.repo.git('rev-parse', '--abbrev-ref', 'HEAD').strip()
        for rev, expected in ((self.first, self.first), (self.first[:7], self.first), (self.first[:12], self.first),
                              ('HEAD~1', self.first), ('HEAD', self.second), (branch, self.second)):
            with self.subTest(rev=rev):
                self.assertEqual(gitrepo.resolve_commit(self.repo.root, rev), expected)

    def test_a_name_that_is_not_a_commit_is_none(self):
        for rev in ('deadbeef', 'no-such-branch', '', '--all', '-1', 'a.md'):
            with self.subTest(rev=rev):
                self.assertIsNone(gitrepo.resolve_commit(self.repo.root, rev))

    def test_a_blob_id_is_not_a_commit(self):
        blob = self.repo.git('rev-parse', 'HEAD:a.md').strip()
        self.assertIsNone(gitrepo.resolve_commit(self.repo.root, blob))

    def test_a_folder_that_is_not_a_repository_gives_none(self):
        plain = self.root / 'plain'
        plain.mkdir()
        self.assertIsNone(gitrepo.resolve_commit(plain, 'HEAD'))

    def test_require_commit_gives_the_full_id_like_resolve_commit(self):
        self.assertEqual(gitrepo.require_commit(self.repo.root, self.first[:7]), self.first)
        self.assertEqual(gitrepo.require_commit(self.repo.root, 'HEAD'), self.second)

    def test_require_commit_names_what_was_asked_and_where_in_one_line(self):
        for rev in ('no-such-branch', '', '--all'):
            with self.subTest(rev=rev), self.assertRaises(gitrepo.GitError) as caught:
                gitrepo.require_commit(self.repo.root, rev)
            self.assertEqual(str(caught.exception), f'{rev} is not a commit in {self.repo.root}')

    def test_short_cuts_a_commit_id_to_twelve_digits_for_a_message(self):
        self.assertEqual(gitrepo.short(self.second), self.second[:12])
        self.assertEqual(gitrepo.short('abc1234'), 'abc1234')


class FileAtTest(RepoCase):
    def setUp(self):
        super().setUp()
        self.repo.write('dir/a.md', 'one\n')
        self.first = self.repo.commit(['dir/a.md'], 'chore: start', date(2026, 10, 1))
        self.repo.write('dir/a.md', 'two\nline\n')
        self.second = self.repo.commit(['dir/a.md'], 'chore: edit', date(2026, 10, 2))

    def test_the_content_at_each_commit(self):
        self.assertEqual(gitrepo.file_at(self.repo.root, self.first, 'dir/a.md'), 'one\n')
        self.assertEqual(gitrepo.file_at(self.repo.root, self.second, 'dir/a.md'), 'two\nline\n')

    def test_the_working_tree_is_not_read(self):
        self.repo.write('dir/a.md', 'uncommitted\n')
        self.assertEqual(gitrepo.file_at(self.repo.root, self.second, 'dir/a.md'), 'two\nline\n')

    def test_a_path_that_is_not_in_that_commit_is_none(self):
        self.repo.write('later.md', 'x\n')
        self.repo.commit(['later.md'], 'chore: later', date(2026, 10, 3))
        self.assertIsNone(gitrepo.file_at(self.repo.root, self.first, 'later.md'))
        self.assertIsNone(gitrepo.file_at(self.repo.root, self.first, 'missing.md'))

    def test_a_folder_a_parent_path_and_a_glob_are_none(self):
        for path in ('dir', 'dir/', '../a.md', 'dir/*.md', ''):
            with self.subTest(path=path):
                self.assertIsNone(gitrepo.file_at(self.repo.root, self.second, path))

    def test_a_name_with_spaces_and_non_ascii_letters(self):
        self.repo.write('na me/é.md', 'x\n')
        sha = self.repo.commit(['na me/é.md'], 'chore: names', date(2026, 10, 3))
        self.assertEqual(gitrepo.file_at(self.repo.root, sha, 'na me/é.md'), 'x\n')


class ChangedFilesTest(RepoCase):
    """changed_files(repo, range) gives Change(status, path, old_path): one letter A, M, D, R, C or T;
    old_path is the path before a rename or copy and '' otherwise."""

    def setUp(self):
        super().setUp()
        body = ''.join(f'line {n}\n' for n in range(12))
        for name in ('keep.md', 'edit.md', 'drop.md', 'move.md'):
            self.repo.write(name, body + name + '\n')
        self.repo.git('add', '-A')
        self.repo.git('commit', '-q', '-m', 'base', when=date(2026, 10, 1))
        self.base = self.repo.git('rev-parse', 'HEAD').strip()

    def change_all(self):
        self.repo.write('edit.md', 'changed\n')
        self.repo.write('new file.md', 'new\n')
        self.repo.git('rm', '-q', '--', 'drop.md')
        self.repo.git('mv', 'move.md', 'moved.md')
        self.repo.git('add', '-A')
        self.repo.git('commit', '-q', '-m', 'change', when=date(2026, 10, 2))

    def test_added_modified_deleted_and_renamed_files_have_one_letter_a_path_and_an_old_path(self):
        self.change_all()
        found = {change.path: change for change in gitrepo.changed_files(self.repo.root, f'{self.base}..HEAD')}
        self.assertEqual({path: (c.status, c.old_path) for path, c in found.items()}, {
            'edit.md': ('M', ''), 'new file.md': ('A', ''), 'drop.md': ('D', ''), 'moved.md': ('R', 'move.md')})

    def test_a_change_unpacks_as_status_path_old_path(self):
        self.change_all()
        rows = [tuple(change) for change in gitrepo.changed_files(self.repo.root, f'{self.base}..HEAD')]
        self.assertIn(('R', 'moved.md', 'move.md'), rows)

    def test_both_range_forms_work_and_an_empty_range_is_empty(self):
        self.change_all()
        for spec in (f'{self.base}..HEAD', f'{self.base}...HEAD'):
            with self.subTest(spec=spec):
                self.assertEqual(len(gitrepo.changed_files(self.repo.root, spec)), 4)
        self.assertEqual(gitrepo.changed_files(self.repo.root, 'HEAD..HEAD'), [])

    def test_non_ascii_names_come_back_as_they_are(self):
        self.repo.write('é ü/ß.md', 'x\n')
        self.repo.git('add', '-A')
        self.repo.git('commit', '-q', '-m', 'names', when=date(2026, 10, 2))
        self.assertEqual([c.path for c in gitrepo.changed_files(self.repo.root, f'{self.base}..HEAD')], ['é ü/ß.md'])

    def test_a_range_that_does_not_resolve_is_a_git_error(self):
        with self.assertRaises(gitrepo.GitError):
            gitrepo.changed_files(self.repo.root, 'no-such-branch..HEAD')

    def test_a_range_that_looks_like_an_option_is_a_git_error(self):
        with self.assertRaises(gitrepo.GitError):
            gitrepo.changed_files(self.repo.root, '--stat')

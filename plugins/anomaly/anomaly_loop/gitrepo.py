"""The one place the plugin runs git: find a repository and name it, commit only named paths, read a path's history.

Every call is a subprocess with an argument list (never a shell string) and literal path
specs, so a file name is never read as a pattern. Nothing here reads the clock: the caller
passes the dates. Failures raise GitError, which the CLI prints as `anomaly: <message>` like
the other errors.

How history is read, so callers count the same way:
- A commit's date is git's committer date, as the committer's own calendar day.
- A window includes both ends: "the last 28 days" ending today is since = today - 27, until = today.
- History is read per path without `--follow`: a renamed path starts a new history, so its
  first-commit date is the day of the rename.
- Commits of a branch merged with a merge commit (`--no-ff`) are counted one by one, as they
  were made; the merge commit itself is not counted.
"""
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import NamedTuple

from . import paths, profile
from .constants import SHORT_SHA_CHARS

REDIRECTING_ENV = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE')
NOISE_PREFIXES = ('warning:', 'hint:')
# scheme, user and password, host, port (only before a `/`), then the project path up to an optional `.git`
REMOTE_URL = re.compile(r'(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:[^@/]*@)?([^:/@]+)(?::\d+(?=/))?[:/]+(.+?)(?:\.git)?/*')
REPO_HELP = 'a folder of the repository (default: the working folder)'   # every --repo option
PLUGIN_REPO_SKIPPED = ('plugin repository not found: plugin-skill churn and unused-skill checks are '
                       'skipped (set plugin_repo in the profile)')


class GitError(Exception):
    """A git command failed, or git is not available."""


def reason(text):
    """The text of a git failure without its `warning:` and `hint:` lines, on one line."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    kept = [line for line in lines if not line.lower().startswith(NOISE_PREFIXES)]
    return '; '.join(kept)


def run(repo, *args, check=True, literal=True, ok_codes=(0,)):
    """Run `git <args>` in `repo`; returns the completed process (text output, UTF-8). Path
    specs are literal unless `literal` is False (for `check-ignore`, which takes plain paths). With
    `check`, an exit code outside `ok_codes` is a GitError."""
    env = {key: value for key, value in os.environ.items() if key not in REDIRECTING_ENV}
    command = ['git', '--literal-pathspecs', *args] if literal else ['git', *args]
    try:
        done = subprocess.run(command, cwd=repo, env=env, capture_output=True,
                              text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError:
        raise GitError('git is not installed or not on PATH') from None
    except OSError as error:
        raise GitError(f'cannot run git in {repo}: {error}') from None
    if check and done.returncode not in ok_codes:
        detail = reason(done.stderr) or reason(done.stdout) or f'exit code {done.returncode}'
        raise GitError(f'git {args[0]} failed in {repo}: {detail}')
    return done


def is_ignored(repo, spec):
    """True when git ignores this repository-relative spec (and it is not tracked)."""
    done = None if spec == '.' else run(repo, 'check-ignore', '--quiet', '--', spec, check=False, literal=False)
    return done is not None and done.returncode == 0


def find_repo(path):
    """The root folder of the git repository that contains `path` (a file, a folder, or one that
    does not exist yet), or None when it is in no repository, git is not available, or git
    ignores the path (a git-ignored copy, such as an installed plugin inside the user config
    repository, belongs to no repository)."""
    start = Path(path)
    while not start.exists() and start != start.parent:
        start = start.parent
    folder = start if start.is_dir() else start.parent
    try:
        done = run(folder, 'rev-parse', '--show-toplevel', check=False)
        root = done.stdout.strip()
        if done.returncode != 0 or not root:
            return None
        root = Path(root).resolve()
        try:
            spec = relative_specs(root, [start])[0]
        except GitError:
            return root
        return None if is_ignored(root, spec) else root
    except GitError:
        return None


def plugin_repo(plugin_root, loaded_profile):
    """(repository root, plugin folder) of the plugin, or None.

    A real (not git-ignored) checkout gives its own repository and `plugin_root` as the folder.
    Otherwise, such as for an installed copy that git ignores, the profile's optional
    `plugin_repo` names the plugin folder inside its git checkout (a leading ~ is expanded;
    blank or a placeholder counts as unset) and gives (repository of that folder, that folder).
    Skills are then at <plugin folder>/skills/<name>, and the caller makes paths relative to the
    repository itself. When this is None the caller prints PLUGIN_REPO_SKIPPED and skips the
    plugin-skill checks."""
    found = find_repo(plugin_root)
    if found is not None:
        return found, Path(plugin_root)
    value = loaded_profile.values.get('plugin_repo')
    if not profile.is_set(value):
        return None
    folder = paths.expand(value)
    found = find_repo(folder)
    return (found, folder) if found is not None else None


def origin_url(repo):
    """The URL of the `origin` remote as written (it can hold credentials: never print it), or ''
    when there is no origin."""
    return run(repo, 'remote', 'get-url', 'origin', check=False).stdout.strip()


def origin_name(repo):
    """The last part of the `origin` remote URL without `.git`, or None when there is no origin or
    that part is empty or only dots."""
    url = origin_url(repo)
    name = re.split(r'[/\\:]', url.rstrip('/\\'))[-1].removesuffix('.git') if url else ''
    return name if name.strip('.') else None


def origin_host_project(repo):
    """(host, project path) of the `origin` remote, or None when there is no origin: the host in lower case, the
    project as `owner/name` or `group/sub/name` without `.git`. Credentials in the URL are dropped and the URL is
    never shown. A URL with no host (a local path) is a GitError. Reads the `https://`, `ssh://` and `git@host:path` shapes."""
    url = origin_url(repo)
    if not url:
        return None
    found = REMOTE_URL.fullmatch(url)
    if found is None:
        raise GitError('cannot read the host and project of the origin remote')
    return found[1].lower(), found[2]


def origin_default_branch(repo):
    """The branch `refs/remotes/origin/HEAD` points at, or None when there is no origin or that ref is not
    set. A clone sets the ref, and `git remote set-head origin` sets or changes it; a fetch does not.
    Any other git failure is a GitError."""
    done = run(repo, 'symbolic-ref', '--quiet', 'refs/remotes/origin/HEAD', ok_codes=(0, 1))   # 1: the ref is not set
    if done.returncode == 1:
        return None
    ref = done.stdout.strip()
    branch = ref.removeprefix('refs/remotes/origin/')
    return branch if branch and branch != ref else None


def main_checkout(repo):
    """The working folder of the main checkout of the repository that holds `repo`.

    In the main checkout itself (its git folder is the common one) that is its own top folder,
    wherever the git folder lives. In a linked worktree it is the folder that holds the common git
    folder when that folder is named `.git`. Otherwise (the main repository is bare, or keeps its
    git folder elsewhere with `--separate-git-dir`) git does not record the main checkout, and the
    worktree's own top folder is returned."""
    git_dir = Path(run(repo, 'rev-parse', '--absolute-git-dir').stdout.strip()).resolve()
    common = Path(run(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir').stdout.strip()).resolve()
    if git_dir != common and common.name == '.git':
        return common.parent
    return Path(run(repo, 'rev-parse', '--show-toplevel').stdout.strip()).resolve()


def shared_root(folder):
    """The folder every worktree of a repository shares for untracked plugin files: the main checkout of
    the repository that holds `folder`, or `folder` itself when it is in no repository."""
    found = find_repo(folder)
    return folder if found is None else main_checkout(found)


def repo_for(option, outside_git=False):
    """The repository of a `--repo` option (help text REPO_HELP): the top folder of the git repository
    that holds the folder `option` names, else the working folder. A value that names no folder is a
    GitError, and so is a folder in no repository, unless `outside_git`: then that folder is used as it
    is (for commands that also work outside git)."""
    folder = Path(option) if option else Path.cwd()
    if option and not folder.is_dir():
        raise GitError(f'--repo is not a folder: {option}')
    found = find_repo(folder)
    if found is not None:
        return found
    if outside_git:
        return folder
    raise GitError(f'not inside a git repository: {folder}; pass --repo <a folder of one>')


def relative_specs(repo, paths):
    """Paths as repository-relative specs; a path outside the repository is a GitError."""
    root = Path(repo).resolve()
    specs = []
    for path in paths:
        full = Path(path)
        full = (full if full.is_absolute() else root / full).resolve()
        try:
            specs.append(full.relative_to(root).as_posix())
        except ValueError:
            raise GitError(f'{path} is outside the repository {repo}') from None
    return specs


def has_commits(repo):
    return run(repo, 'rev-parse', '--verify', '--quiet', 'HEAD', check=False).returncode == 0


def is_known(repo, spec):
    """True when the spec exists on disk or git tracks something at it (for example a deleted file)."""
    return (Path(repo) / spec).exists() or \
        run(repo, 'ls-files', '--error-unmatch', '--', spec, check=False).returncode == 0


def commit_paths(repo, paths, message):
    """Commit the changes under `paths` (files or folders, new, changed or deleted) with `message`
    and return the new commit id, or None when they have no changes.

    Only these paths are committed: whatever else is staged or edited in the repository stays
    exactly as it was, and nothing of ours stays staged unless the commit succeeds (a failed
    commit, for example a refusing hook, leaves the changes unstaged). A path that git ignores
    is skipped. A path that neither exists nor is tracked, or the repository root, is a GitError.
    (A path that was already staged is committed as it is on disk.)"""
    specs = relative_specs(repo, paths)
    if '.' in specs:
        raise GitError(f'refusing to commit the whole repository {repo}: name the paths to commit')
    for spec in specs:
        if not is_known(repo, spec):
            raise GitError(f'{spec} does not exist in {repo} and is not tracked')
    specs = [spec for spec in specs if not is_ignored(repo, spec)]
    if not specs:
        return None
    listing = run(repo, 'ls-files', '--others', '--exclude-standard', '-z', '--', *specs).stdout
    untracked = [name for name in listing.split('\0') if name]
    if untracked:
        run(repo, 'add', '--intent-to-add', '--', *untracked)
    try:
        if not run(repo, 'status', '--porcelain', '--', *specs).stdout.strip():
            return None
        run(repo, 'commit', '--only', '--quiet', '-m', message, '--', *specs)
    except GitError:
        # Rollback touches only paths we found untracked; another process staging the same file
        # in between is an accepted race.
        if untracked:
            run(repo, 'rm', '--cached', '--quiet', '--force', '--', *untracked, check=False)
        raise
    return run(repo, 'rev-parse', 'HEAD').stdout.strip()


def commit_dates(repo, path):
    """The date of every commit that touched `path` (newest first); empty when it has none."""
    if not has_commits(repo):
        return []
    spec, = relative_specs(repo, [path])
    lines = run(repo, 'log', '--format=%cs', '--', spec).stdout.split()
    return [date.fromisoformat(line) for line in lines]


def commit_count(repo, path, since, until):
    """How many commits touched `path` (a file, or a folder and anything in it) on a day from
    `since` to `until`, both included."""
    return sum(1 for day in commit_dates(repo, path) if since <= day <= until)


def first_commit_date(repo, path):
    """The day of the oldest commit that touched `path`, or None when git has no history for it."""
    days = commit_dates(repo, path)
    return min(days) if days else None


def resolve_commit(repo, rev):
    """The full id of the commit `rev` names (a full or short id, a branch, a tag, `HEAD~1`), or None
    when it names no commit in `repo`. A name that starts with `-` is never read as a commit."""
    if not rev or rev.startswith('-'):
        return None
    done = run(repo, 'rev-parse', '--verify', '--quiet', '--end-of-options', f'{rev}^{{commit}}', check=False)
    return done.stdout.strip() if done.returncode == 0 else None


def require_commit(repo, rev):
    """Like resolve_commit, but a name that is no commit is a GitError with one clear message."""
    found = resolve_commit(repo, rev)
    if found is None:
        raise GitError(f'{rev} is not a commit in {repo}')
    return found


def refresh_index(repo):
    """Bring the index's file stats up to date (`git update-index --refresh`), so a file that differs
    only by its stat (same bytes, new modification time or line-ending conversion) is not read as
    dirty by a later merge. A file with a real change stays changed (`-q` makes that exit 0). A real
    failure, such as a lock file on the index or a corrupt index, is a GitError."""
    run(repo, 'update-index', '-q', '--refresh')


def short(sha):
    """A commit id cut to SHORT_SHA_CHARS digits, for a message."""
    return sha[:SHORT_SHA_CHARS]


def file_at(repo, rev, path):
    """The text of the file `path` (repository-relative, forward slashes) as committed at `rev`, or
    None when that commit holds no file there (a folder or a missing path). `rev` is a commit id
    from resolve_commit; the working folder is never read, and line endings are read as text."""
    if not rev or rev.startswith('-'):
        return None
    done = run(repo, 'cat-file', 'blob', f'{rev}:{path}', check=False)
    return done.stdout if done.returncode == 0 else None


class Change(NamedTuple):
    """One changed file: `status` is one letter (A added, M modified, D deleted, R renamed, C copied,
    T type changed), `path` the path after the change (the deleted path for D), `old_path` the
    path before a rename or copy and '' otherwise."""
    status: str
    path: str
    old_path: str = ''


def merge_range(merge):
    """The range of the changes a merge brought: the merge commit against its first parent."""
    return f'{merge}^1..{merge}'


def changed_line_count(repo, range_spec):
    """Lines added plus deleted over `range_spec` (`A..B`); a binary file counts 0."""
    total = 0
    for line in run(repo, 'diff', '--numstat', '--end-of-options', range_spec).stdout.splitlines():
        added, deleted = line.split('\t')[:2]
        total += sum(int(n) for n in (added, deleted) if n.isdigit())
    return total


def changed_files(repo, range_spec):
    """The files that differ over `range_spec` (`A..B` or `A...B`) as a list of Change, in git's order,
    renames detected. A range that does not resolve is a GitError."""
    done = run(repo, 'diff', '--name-status', '-z', '--find-renames', '--end-of-options', range_spec)
    tokens = done.stdout.split('\0')
    changes, index = [], 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index][0]
        if status in 'RC':
            changes.append(Change(status, tokens[index + 2], tokens[index + 1]))
            index += 3
        else:
            changes.append(Change(status, tokens[index + 1]))
            index += 2
    return changes


def tracked_files(repo):
    """The repository-relative paths (forward slashes) git tracks, in git's order. This is the index, so a
    tracked file that is deleted from the working folder is still listed, and one that is untracked is not."""
    return [name for name in run(repo, 'ls-files', '-z').stdout.split('\0') if name]

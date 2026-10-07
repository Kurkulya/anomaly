"""risk: which risk areas a range of changes touches, so the review knows whether security joins.

  risk <range> [--repo DIR]    print the matched areas and the matched files; nothing is written

The range is `A..B` or `A...B` (both ends resolved through gitrepo.require_commit); the changed files
come from gitrepo.changed_files. The areas are the core ones in constants.RISK_AREAS (auth; input
parsing and execution; secrets or config; dependencies; network calls) and, as one more area named
constants.RISK_REPO_AREA, the globs of the repo layer (`risk_patterns`, read through
repolayer.read). Only the changed paths are matched, never the content of the lines.

A glob matches a path when it matches the whole repository-relative path (forward slashes) or the
file name; a glob that ends in `/` means everything under that folder from the repository root.
Core globs are written in lower case and matched against the path in lower case; repo-layer globs are
matched in the case written. A renamed or copied file matches by either of its paths and is named by
the new one; a deleted file counts as touched.

Output: `risk areas: <area>, <area>` and then one `<area>: <path>` line for each file in each area (a
file in two areas is listed under both), or the one line `no risk area matched`.
"""
import fnmatch
import re

from . import gitrepo, paths, repolayer
from .constants import RISK_AREAS, RISK_REPO_AREA
from .files import RecordError

NO_MATCH = 'no risk area matched'
RANGE = re.compile(r'(.+?)(\.\.\.?)(.+)')


def glob_matches(pattern, path):
    """True when the fnmatch glob matches the whole path or its file name. fnmatchcase: the host's
    case rules and slash handling never matter."""
    if pattern.endswith('/'):
        pattern += '*'
    return fnmatch.fnmatchcase(path, pattern) or fnmatch.fnmatchcase(path.rsplit('/', 1)[-1], pattern)


def match_areas(changes, repo_patterns):
    """[(area, [path, ...])] for the areas that have a changed file, the core areas first and the repo
    layer last; each path is listed once per area, in the order of `changes`."""
    rules = [(area, patterns, True) for area, patterns in RISK_AREAS] + [(RISK_REPO_AREA, repo_patterns, False)]
    named = [(change.path, [name for name in (change.path, change.old_path) if name]) for change in changes]
    lowered = [(path, [name.lower() for name in names]) for path, names in named]
    found = []
    for area, patterns, ignore_case in rules:
        files = [path for path, names in (lowered if ignore_case else named)
                 if any(glob_matches(pattern, name) for name in names for pattern in patterns)]
        if files:
            found.append((area, files))
    return found


def render(found):
    if not found:
        return [NO_MATCH]
    return ['risk areas: ' + ', '.join(area for area, _ in found)] + \
        [f'{area}: {path}' for area, files in found for path in files]


def resolve_range(repo, spec):
    """`A..B` or `A...B` with both ends turned into full commit ids; an end that is no commit is a GitError."""
    match = RANGE.fullmatch(spec)
    if match is None:
        raise RecordError(f'{spec} is not a range: write A..B or A...B')
    left, dots, right = match.groups()
    return f'{gitrepo.require_commit(repo, left)}{dots}{gitrepo.require_commit(repo, right)}'


def register(commands, common):
    command = commands.add_parser('risk', parents=[common],
                                  help='print the risk areas and files a range of changes touches')
    command.add_argument('range', metavar='range', help='A..B or A...B: commit ids, branches or tags')
    command.add_argument('--repo', help=gitrepo.REPO_HELP)
    command.set_defaults(handler=run_risk)


def run_risk(args, environ):
    home = paths.resolve_home(args.home, environ)
    repo = gitrepo.repo_for(args.repo)
    changes = gitrepo.changed_files(repo, resolve_range(repo, args.range))
    for line in render(match_areas(changes, repolayer.read(repo, home).risk_patterns)):
        print(line)
    return 0

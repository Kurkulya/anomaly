"""docs scan: three checks of the docs audit that need no judgment, from the tracked files of a repository: an ADR
whose revisit date has passed, a deferral note without an owner and a revisit date, and a path in a `CLAUDE.md`
that no longer exists. The other two checks of the audit (a commit that decided something no ADR records, an ADR
claim the code has moved away from) are the docs agent's, not this command's.

  docs scan <range> [--repo DIR] [--home DIR]    print the findings, one line each; nothing is written

The first line is `adr folder: <folder>`, the folder the scan reads (check.adr_folder_path), so a port value that
names no folder of the repo, which reads as `docs/adr`, is not silent.

The range is `A..B` or `A...B` (resolved through risk.resolve_range); it only decides which findings are
marked. The scan itself reads the working folder, not the range. Four kinds of finding, each with the
repository-relative `path:line`:

- `adr-overdue`: an ADR whose revisit date is before today. The date is the `Revisit-by:` field of the status
  line; an ADR with no such field uses its `Revisit:` front-block line (a line that starts with `Revisit:`
  above the first `## ` heading) when that line holds a date. An ADR whose status starts with `Superseded`
  is left out. The ADRs are `NNNN-*.md` in the folder of the `adr_folder` port (check.adr_folder_path, so a
  value outside the repo gives docs/adr) and in the adr/ of every unit folder (check.ADR_GLOBS).
- `todo-unkeyed`: in any tracked text file, a deferral note (the word in DEFERRAL_WORD) that is not followed at
  once by the key `(<owner>, revisit YYYY-MM-DD)`. It counts only as the first word of a comment (after `#`,
  `//`, `--`, `/*` or `<!--`), of a line (after spaces or `> ` quote marks) or of a list item (`- `, `* `,
  `1. `, also with a `[ ]` or `[x]` box); a mention in the middle of code or of a sentence is not reported,
  nor is the word followed by `(<`. A key whose date is not a real date counts as no key. `todo-overdue`: a
  key with a real date before today, wherever it stands in the line.
- `dead-path`: in a tracked `CLAUDE.md`, a path claim that is not live. It is live when it is at or under a unit
  home folder (check.OWNER_HOME_DIRS: `.anomaly`, `.scratch`; local work units, so a clone has none), or exists
  beside that file or at the repo root, or when git ignores it (an ignored folder, such as a local work-unit folder, exists
  in one checkout only, so it is live on or off disk), or when a tracked file or folder is the claim or ends
  with `/<claim>`. A claim is a backticked word with no
  space or glob or placeholder character (a trailing `:12` or `:12-20` is cut off) that holds a `/` or is a
  bare file name with one of the extensions in BARE_FILE, or the target of a markdown link that is not a URL
  or an anchor. Fenced code blocks are not read. A ref such as `origin/main` is a claim (a known limit). A claim
  that climbs out of the repo (`..`, check.relative_parts) cannot be checked against it and is left out.

A finding in a file the range changes ends with ` [touched]`. The command exits 1 when any finding is marked,
else 0. Today is the CLI clock (args.today).
"""
import re
from datetime import date
from typing import NamedTuple

from . import check, gitrepo, paths, ports, risk
from .files import RecordError, read_input
from .records import is_date

ADR_OVERDUE, TODO_UNKEYED, TODO_OVERDUE, DEAD_PATH = 'adr-overdue', 'todo-unkeyed', 'todo-overdue', 'dead-path'
TOUCHED = ' [touched]'
DEFERRAL_WORD = 'TO' + 'DO'   # joined, so that this file holds no bare deferral note of its own
DEFERRAL = re.compile(rf'(?<!\w){DEFERRAL_WORD}(?!\w)')
# The deferral word as the first word of a comment (after one of these markers), of a line or of a list item.
POSITIONED = re.compile(rf'(?:^\s*(?:>\s*)*(?:(?:[-*]|\d+\.)\s+(?:\[[ xX]\]\s+)?)?|(?:#|//|--|/\*|<!--)\s*)'
                        rf'(?P<word>{DEFERRAL_WORD})(?!\w)')
PLACEHOLDER_KEY = '(<'   # the deferral word followed by this is the key shape written out with a placeholder owner
ADR_NUMBER = '[0-9][0-9][0-9][0-9]'
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
REVISIT_BY = re.compile(r'Revisit-by:\s*(\d{4}-\d{2}-\d{2})')
CLAUDE_FILE = 'CLAUDE.md'
FENCE = re.compile(r'\s*(?:```|~~~)')
SPAN = re.compile(r'`([^`]+)`')
LINK = re.compile(r'\]\(<?([^)\s>]+)>?(?:\s+"[^"]*")?\)')
# A claim holds none of: a space, a glob, placeholder, quote, bracket or shell character, or a colon (a URL, `file:line`).
NOT_A_PATH = re.compile(r'[\s*?<>{}|$=:\\\[\]()"\'`;,]|\.\.\.')
LINE_NUMBER = re.compile(r':\d+(?:-\d+)?$')   # a `path:12` or `path:12-20` cite names the path
BARE_FILE = re.compile(r'[\w.-]+\.(?:md|py|json|toml|ya?ml|sh|txt)')


class Finding(NamedTuple):
    path: str
    line: int
    kind: str
    detail: str


def adr_revisit(lines):
    """(line number, date text) of the revisit date of an ADR, or None: no date, or a superseded ADR."""
    front = []
    for number, line in enumerate(lines, 1):
        if line.startswith('## '):
            break
        front.append((number, line))
    status = next(((number, line) for number, line in front if line.startswith('Status:')), None)
    if status is not None:
        if status[1].removeprefix('Status:').strip().startswith('Superseded'):
            return None
        found = REVISIT_BY.search(status[1])
        if found:
            return status[0], found[1]
    for number, line in front:
        found = DATE.search(line) if line.startswith('Revisit:') else None
        if found:
            return number, found[0]
    return None


def adr_findings(path, lines, today):
    found = adr_revisit(lines)
    if found is None or not is_date(found[1]) or date.fromisoformat(found[1]) >= today:
        return []
    return [Finding(path, found[0], ADR_OVERDUE, f'revisit date {found[1]} has passed')]


def deferral_findings(path, lines, today):
    findings = []
    for number, line in enumerate(lines, 1):
        for word in DEFERRAL.finditer(line):   # a key with a real date is read wherever it stands
            key = check.TODO_KEY.match(line, word.start())
            if key is not None and is_date(key[1]) and date.fromisoformat(key[1]) < today:
                findings.append(Finding(path, number, TODO_OVERDUE, f'revisit date {key[1]} has passed'))
        for found in POSITIONED.finditer(line):   # a note without one counts only where a note is written
            key = check.TODO_KEY.match(line, found.start('word'))
            if (key is None or not is_date(key[1])) and not line.startswith(PLACEHOLDER_KEY, found.end('word')):
                findings.append(Finding(path, number, TODO_UNKEYED, f'no owner and revisit date: {check.TODO_KEY_SHAPE}'))
    return findings


def path_claims(line):
    """The relative paths a line of a markdown file claims, once each, in order of appearance."""
    claims = []
    candidates = [(match.start(), LINE_NUMBER.sub('', match[1]), False) for match in SPAN.finditer(line)]
    candidates += [(match.start(), match[1].split('#', 1)[0].split('?', 1)[0], True) for match in LINK.finditer(line)]
    for _, target, is_link in sorted(candidates):
        if not target or target[0] in '-/~#' or NOT_A_PATH.search(target) or target in claims:
            continue
        if is_link or '/' in target or BARE_FILE.fullmatch(target):
            claims.append(target)
    return claims


def tracked_match(tracked, claim):
    """True when a tracked file or folder is `claim` or ends with `/<claim>`: the claim is a run of whole path
    parts of a tracked path (a folder is a leading part run of the files in it)."""
    inner = f'/{claim}/'
    return any(inner in f'/{path}/' for path in tracked)


def is_ignored(repo, full, is_folder):
    """True when git ignores the path `full` (a path outside the repository is not); `is_folder` tells git that a
    path which is not on disk is a folder, so that a folder pattern such as `.scratch/` matches it."""
    try:
        spec, = gitrepo.relative_specs(repo, [full])
    except gitrepo.GitError:
        return False
    return gitrepo.is_ignored(repo, spec + '/' if is_folder else spec)


def exists(repo, folder, tracked, target):
    """True when `target` is live: it is at or under a unit home folder (check.OWNER_HOME_DIRS), or it is beside the
    file (in `folder`) or at the repo root, or git ignores it (a local folder is in one checkout only, so a clone
    must not report it), or a tracked path is the claim or ends with it."""
    clean = target.removeprefix('./').rstrip('/')
    if clean.split('/', 1)[0] in check.OWNER_HOME_DIRS:
        return True   # a local work-unit folder: a clone has none of them
    try:
        if any((base / clean).exists() or is_ignored(repo, base / clean, target.endswith('/'))
               for base in dict.fromkeys((folder, repo))):   # one base for a CLAUDE.md at the root
            return True
    except OSError:
        return False
    return tracked_match(tracked, clean)


def dead_path_findings(repo, path, lines, tracked):
    folder = (repo / path).parent
    findings, fenced = [], False
    for number, line in enumerate(lines, 1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            findings += [Finding(path, number, DEAD_PATH, f'{target} does not exist')
                         for target in path_claims(line)
                         if check.relative_parts(target) and not exists(repo, folder, tracked, target)]
    return findings


def read_lines(repo, path):
    """The lines of a regular text file, or None for a symlink, a missing file or one that is not UTF-8 text."""
    full = repo / path
    if full.is_symlink() or not full.is_file():
        return None
    try:
        text = read_input(full)
    except (RecordError, OSError):
        return None
    return None if '\0' in text else text.splitlines()


def adr_paths(repo, adr_folder):
    """The ADR files, repository-relative: `NNNN-*.md` in the ADR folder and in the adr/ of every unit folder."""
    return {found.relative_to(repo).as_posix()
            for pattern in check.adr_globs(ADR_NUMBER, adr_folder) for found in repo.glob(pattern)}


def scan(repo, adr_folder, today):
    """Every finding of the repository, ordered by path and line; a kind is reported once for a line."""
    tracked = set(gitrepo.tracked_files(repo))
    adrs = adr_paths(repo, adr_folder)
    findings = []
    for path in sorted(tracked | adrs):
        lines = read_lines(repo, path)
        if lines is None:
            continue
        if path in adrs:
            findings += adr_findings(path, lines, today)
        if path in tracked:
            findings += deferral_findings(path, lines, today)
            if path.rsplit('/', 1)[-1] == CLAUDE_FILE:
                findings += dead_path_findings(repo, path, lines, tracked)
    return sorted(set(findings), key=lambda finding: (finding.path, finding.line, finding.kind))


def register(commands, common):
    command = commands.add_parser('docs', help='checks of the docs of a repository')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    scan_command = actions.add_parser('scan', parents=[common],
                                      help='print the overdue ADRs, the unkeyed deferral notes and the dead paths of '
                                           'CLAUDE.md files; exit 1 on a finding in a file the range changes')
    scan_command.add_argument('range', metavar='range', help='A..B or A...B: commit ids, branches or tags')
    scan_command.add_argument('--repo', help=gitrepo.REPO_HELP)
    scan_command.set_defaults(handler=run_scan)


def run_scan(args, environ):
    home = paths.resolve_home(args.home, environ)
    repo = gitrepo.repo_for(args.repo)
    touched = {change.path for change in gitrepo.changed_files(repo, risk.resolve_range(repo, args.range))}
    adr_folder = ports.adr_folder(home)
    findings = scan(repo, adr_folder, args.today)
    marked = [finding.path in touched for finding in findings]
    print(f'adr folder: {check.adr_folder_path(adr_folder)}')
    for finding, is_touched in zip(findings, marked):
        print(f'{finding.path}:{finding.line}: {finding.kind}: {finding.detail}{TOUCHED if is_touched else ""}')
    print(f'docs scan: {len(findings)} finding{"" if len(findings) == 1 else "s"}, {sum(marked)} in files the range changes'
          if findings else 'docs scan: no findings')
    return 1 if any(marked) else 0

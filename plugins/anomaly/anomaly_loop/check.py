"""check: the invariants the pipeline enforces from ticket files and git, as one command.

  pre-merge   exit 0 only when `Reviewed:` and `Verified:` both name the head being merged and the
              acceptance test is unchanged since its red commit (or the ticket notes why)
  stories     exit 1 when stories.md or decisions.md of a work unit breaks the shapes in
              docs/formats.md; oversize files only warn
  slice       exit 1 when the tickets of a work unit cannot be run by build (an AC in no Covers:,
              a missing line, a bad Status:, a blocker with no file or in a cycle, a path:NN
              anchor); a ticket over 5 KB only warns. Prints as `stories` does
              (`slice check passed`).

`stories` prints each error as one line, `<file>:<line>: <problem> (<allowed shape>)`, then each
warning as `warning: <file>: ...`; it exits 1 on any error, 0 otherwise (clean prints one
`stories check passed` line), and 2 with one `anomaly:` line for a folder that is not there.

The next two paragraphs are about pre-merge only. Each failed invariant is one line on stdout, named
by its ticket line (`Reviewed:`, `Verified:`, `Red:`, `Test:`), and the exit code is 1, as for
`ticket gate`; an error (a missing ticket, a head that is not a commit) is one `anomaly:` line and
exit 2. Nothing is written but the index's file stats: `git update-index --refresh` runs first, so a
file dirty by its stat only (for example a line-ending change) cannot make the merge that follows
refuse. A passing check prints a `note:` line for a test file excused by `Red-changed:`, then one
`passed` line. The ticket lines are read with ticket.load; every commit id in them is normalised
with git before it is compared, so a short id equals the full one. The test file is read from git
at the `Red:` commit and at the head.

A `Red-changed:` line excuses a change to the test file since the `Red:` commit, and also a missing
`Red:` line (a docs-only ticket has no acceptance test); the check then passes and prints the reason
as a `note:` line. The ticket keeps no order between its lines, so `ticket red` removes the earlier
`Red-changed:` lines when it records the first `Red:` line or a different sha: each reason covers
only the edits after the red commit it was written for.
"""
import argparse
import re
from pathlib import Path

from . import files, gitrepo, ticket
from .constants import (TICKET_FIELD_SEPARATOR, TICKET_NUMBER_DIGITS, TICKET_STATUS_DONE, TICKET_STATUS_HUMAN,
                        TICKET_STATUS_IN_PROGRESS, TICKET_STATUS_NEEDS_INFO, TICKET_STATUS_READY,
                        TICKET_STATUS_WONTFIX)


def head_problem(repo, key, value, head):
    """One line when the ticket's `<key>:` value is not the head being merged, else None."""
    if not value:
        return f'{key}: no {key}: line; the head being merged ({gitrepo.short(head)}) has no record'
    found = ticket.named_commit(repo, value)
    if found is None:
        return f'{key}: {ticket.not_a_commit(value)}'
    if found != head:
        return f'{key}: {value} is not the head being merged ({gitrepo.short(head)})'
    return None


def acceptance_test_result(repo, parsed, head):
    """(problem, note) for the acceptance test rule: the file at the head equals the file at the
    `Red:` commit, or a `Red-changed:` line says why it changed or why there is no `Red:` line. At
    most one of the two is set."""
    reasons = '; '.join(parsed.red_changed)
    if parsed.red is None:
        if parsed.red_changed:
            return None, f'note: no Red: line; the ticket says why: {reasons}'
        return ('Red: no Red: line; the acceptance test cannot be checked '
                '(record the red commit with ticket red)'), None
    sha, path = parsed.red
    if not path:
        return f'Red: the line is not "<sha>{TICKET_FIELD_SEPARATOR}<test path>"', None
    path = path.replace('\\', '/')
    red = ticket.named_commit(repo, sha)
    if red is None:
        return f'Red: {ticket.not_a_commit(sha)}', None
    at_red = gitrepo.file_at(repo, red, path)
    if at_red is None:
        return f'Red: {path} is not in the red commit {gitrepo.short(red)}', None
    at_head = gitrepo.file_at(repo, head, path)
    if at_head == at_red:
        return None, None
    if parsed.red_changed:
        return None, f'note: {path} changed since its red commit {gitrepo.short(red)}; the ticket says why: {reasons}'
    what = 'is not in the head' if at_head is None else 'changed'
    return f'Test: {path} {what} since its red commit {gitrepo.short(red)} and the ticket has no Red-changed: line', None


def pre_merge(repo, parsed, head):
    """(problems, notes) for a ticket and the head being merged."""
    problems = [head_problem(repo, key, value, head)
                for key, value in (('Reviewed', parsed.reviewed), ('Verified', parsed.verified))]
    problem, note = acceptance_test_result(repo, parsed, head)
    problems.append(problem)
    return [line for line in problems if line], [note] if note else []


# ---------- stories ----------

STORIES_WARN_BYTES = 6 * 1024
DECISIONS_WARN_BYTES = 8 * 1024
AC_LINE = re.compile(r'^- (AC-\d+):')
D_LINE = re.compile(r'^- D-\d+:')
SPECIFY_LINE = re.compile(r'^\S+ \S+ specify:')
SPECIFY_IDS = re.compile(r'^\S+ \S+ specify: ACs: ([^;]*);')
D_TOKEN = re.compile(r'\bD-\d+')
BRACKETED = re.compile(r'\([^()]*\)|\[[^\[\]]*\]')
# The shapes below are the exact text of docs/formats.md; a test holds them to it.
AC_SHAPE = '- AC-1: <criterion>'
D_SHAPE = '- D-n: <decision>. Why: <one line>. Source: <where>'
SPECIFY_SHAPE = 'ACs: AC-1, AC-2, …;'
OWNER_SHAPE = '- <item> — owner: <unit, ticket or ADR>'
D_OWNER_SHAPE = '— owner: <unit, ticket or ADR>'
OWNER_MARKER = '— owner:'
TODO_KEY_SHAPE = 'TODO(<owner>, revisit YYYY-MM-DD)'
TODO_KEY = re.compile(r'TODO\([^(),]+, revisit \d{4}-\d{2}-\d{2}\)')
BACKTICKED = re.compile(r'`([^`]+)`')
TICKET_REF = re.compile(r'\bticket (\d+)\b')
ADR_REF = re.compile(r'\bADR-(\d{4})\b')
OWNER_HOME_DIRS = ('.anomaly', '.scratch')   # a unit folder is `<root>/<one of these>/<name>/`
ADR_GLOBS = ('docs/adr/{}-*.md', '.anomaly/*/adr/{}-*.md', '.scratch/*/adr/{}-*.md')
# A file path is an owner only when it is a ticket file or an ADR file, never any file of the checkout.
OWNER_FILE = re.compile(r'(?:\.anomaly|\.scratch)/[^/]+/tickets/\d+-[^/]+\.md|\.scratch/[^/]+/issues/\d+-[^/]+\.md|'
                        r'\.anomaly/adhoc/[^/]+\.md|(?:docs|(?:\.anomaly|\.scratch)/[^/]+)/adr/\d{4}-[^/]+\.md')


def owner_value(line):
    """The owner value of a line: the text after the first `— owner:`, ended at the first `. Why:` or
    `. Source:` (a decisions.md line goes on with them), or None when the line has no marker. A plain
    `owner:` in other text is ignored."""
    _, marker, owner = line.partition(OWNER_MARKER)
    return re.split(r'\. (?:Why|Source):', owner, maxsplit=1)[0] if marker else None


def owner_names_decision(line):
    """True when the owner value holds a D-n token outside brackets. A D-n in round or square brackets
    is a citation, not the owner."""
    owner = owner_value(line)
    return owner is not None and D_TOKEN.search(BRACKETED.sub('', owner)) is not None


def name_exists(root, name):
    """True when `name` is a unit folder (a bare name under `<root>/.anomaly/` or `<root>/.scratch/`, or the
    path `.anomaly/<name>`, `.scratch/<name>`), or the path of an existing ticket file or ADR file (OWNER_FILE).
    Any other file, a name with `..` or no path part, an absolute path, or a name the file system refuses
    (too long) names nothing."""
    path = Path(name)
    parts = path.parts
    if not parts or '..' in parts or path.is_absolute():
        return False
    try:
        if len(parts) == 1:
            return any((root / home / path).is_dir() for home in OWNER_HOME_DIRS)
        if len(parts) == 2 and parts[0] in OWNER_HOME_DIRS:
            return (root / path).is_dir()
        return OWNER_FILE.fullmatch(path.as_posix()) is not None and (root / path).is_file()
    except OSError:
        return False


def owner_exists(owner, folder):
    """True when the owner value carries a `TODO(<owner>, revisit YYYY-MM-DD)` key, or names something in
    the checkout (no git lookup): a unit folder, the path of a ticket or ADR file, `ticket NN`
    (`<folder>/tickets/NN-*.md`, only when the owner names no backticked unit) or `ADR-NNNN` (`docs/adr/`, or
    the `adr/` of any unit folder). `<root>` is the grandparent of the work-unit folder. A bracketed text is
    a citation and names nothing."""
    if TODO_KEY.search(owner):
        return True
    folder = Path(folder).resolve()
    root = folder.parent.parent
    plain = BRACKETED.sub('', owner)
    backticked = [name.strip() for name in BACKTICKED.findall(plain)]
    names = backticked + [plain.replace('`', '').strip().rstrip('.')]
    return (any(name_exists(root, name) for name in names)
            or (not backticked and any(ticket.find_blocker(folder / 'tickets', number)
                                       for number in TICKET_REF.findall(plain)))
            or any(any(root.glob(pattern.format(number))) for number in ADR_REF.findall(plain)
                   for pattern in ADR_GLOBS))


def read_optional(path):
    """The text of a file, or None when it is not there."""
    return files.read_input(path) if path.is_file() else None


def owner_missing(shape):
    """The tail of an error line for an owner that exists nowhere in the checkout and has no TODO key."""
    return (f'an owner must exist in the checkout (a unit folder, ticket NN, ADR-NNNN, or the path of a ticket or ADR file) '
            f'or carry {TODO_KEY_SHAPE}; a person or a skill needs the key and a placeholder is never an owner ({shape})')


def stories_errors(text, folder):
    """Errors for stories.md: duplicate AC ids and Out of scope lines with no `— owner:`, an owner that names a D-n
    outside brackets, or an owner that is not found in the checkout and has no TODO key (the work-unit
    `folder` resolves the names). Also the ids found."""
    errors, found, in_scope_out = [], {}, False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('#'):
            in_scope_out = line.strip().lower() == '## out of scope'
        match = AC_LINE.match(line)
        if match:
            ac = match.group(1)
            if ac in found:
                errors.append(f'stories.md:{number}: {ac} is already used on line {found[ac]}; '
                              f'each AC id is unique ({AC_SHAPE})')
            else:
                found[ac] = number
        elif in_scope_out and line.startswith('- ') and OWNER_MARKER not in line:
            errors.append(f'stories.md:{number}: an Out of scope line needs the marker — owner: ({OWNER_SHAPE})')
        elif in_scope_out and line.startswith('- ') and owner_names_decision(line):
            errors.append(f'stories.md:{number}: an owner is a unit, ticket or ADR, not a D-n ({OWNER_SHAPE})')
        elif in_scope_out and line.startswith('- ') and not owner_exists(owner_value(line), folder):
            errors.append(f'stories.md:{number}: {owner_missing(OWNER_SHAPE)}')
    return errors, found


def decisions_errors(text, folder):
    """Errors for decisions.md: a `- D-<n>:` line with no `Source:`, or whose `— owner:` names a D-n outside brackets
    or is not found in the checkout and has no TODO key. A `T-n` line needs no Source."""
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        if not D_LINE.match(line):
            continue
        if 'Source:' not in line:
            errors.append(f'decisions.md:{number}: a decision needs a Source: ({D_SHAPE})')
        elif owner_names_decision(line):
            errors.append(f'decisions.md:{number}: an owner is a unit, ticket or ADR, '
                          f'not a D-n ({D_OWNER_SHAPE})')
        elif (owner := owner_value(line)) is not None and not owner_exists(owner, folder):
            errors.append(f'decisions.md:{number}: {owner_missing(D_OWNER_SHAPE)}')
    return errors


def logged_ac_ids(text):
    """(ids, errors) for the `specify:` lines of log.md: ids maps each AC id to the number of the
    first line that names it, in order; a `specify:` line without the `ACs: ...;` shape is an error."""
    ids, errors = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        if not SPECIFY_LINE.match(line):
            continue
        match = SPECIFY_IDS.match(line)
        if not match:
            errors.append(f'log.md:{number}: a specify: line must start its text with the ids '
                          f'({SPECIFY_SHAPE})')
            continue
        for ac in re.findall(r'AC-\d+', match.group(1)):
            ids.setdefault(ac, number)
    return ids, errors


def stories(folder):
    """(errors, warnings) for a work-unit folder, each a list of one-line strings. A missing
    stories.md is an error line; a missing decisions.md or log.md is empty (no decisions, no
    recorded ids). Sizes over 6 KB (stories.md) and 8 KB (decisions.md) only warn."""
    folder = Path(folder)
    if not folder.is_dir():
        raise files.RecordError(f'{folder}: not a folder')
    errors, warnings = [], []
    stories_text = read_optional(folder / 'stories.md')
    decisions_text = read_optional(folder / 'decisions.md')
    log_text = read_optional(folder / 'log.md')
    if stories_text is None:
        errors.append('stories.md: the file is missing (a work unit keeps its stories in stories.md)')
    else:
        found_errors, found = stories_errors(stories_text, folder)
        errors.extend(found_errors)
        logged, log_errors = logged_ac_ids(log_text or '')
        errors.extend(log_errors)
        errors.extend(f'log.md:{number}: {ac} was named by a specify: line and is gone from stories.md; '
                      f'an AC id is never renumbered (a withdrawn AC stays in place with an '
                      f'"Amended <date>:" line)'
                      for ac, number in logged.items() if ac not in found)
        if len(stories_text.encode('utf-8')) > STORIES_WARN_BYTES:
            warnings.append('stories.md: over 6 KB; consider splitting the work unit')
    if decisions_text is not None:
        errors.extend(decisions_errors(decisions_text, folder))
        if len(decisions_text.encode('utf-8')) > DECISIONS_WARN_BYTES:
            warnings.append('decisions.md: over 8 KB; consider moving settled decisions out')
    return errors, warnings


# ---------- slice ----------

SLICE_WARN_BYTES = 5 * 1024
STATUS_WORDS = (TICKET_STATUS_READY, TICKET_STATUS_HUMAN, TICKET_STATUS_NEEDS_INFO, TICKET_STATUS_WONTFIX,
                TICKET_STATUS_IN_PROGRESS, TICKET_STATUS_DONE)
HUMAN_STATUS = re.compile(rf'{re.escape(TICKET_STATUS_HUMAN)} \(.+\)')
TICKET_NUMBER = re.compile(rf'^(\d{{{TICKET_NUMBER_DIGITS}}})-')
# A host:port right after `://` or `@` is not path:NN; a bare example.com:8080 is reported. The whole
# match is dropped (finditer does not restart inside it), so no tail of the host is reported.
# Known gap: `see @check.py:42` and a URL path `https://host/x/check.py:42` are skipped too.
# A match starts only at a token head (no path char, or one `/` that itself starts a token, before it).
LINE_ANCHOR = re.compile(r'(?<![\w.-])(?<![\w.-]/)(?:[\w.-]+/)*\.*[\w-][\w.-]*\.[A-Za-z]\w*:\d+\b')
HOST_PREFIXES = ('://', '@')


def line_anchor(body):
    """The first path:NN in a line that does not follow `://` or `@`, or None."""
    for match in LINE_ANCHOR.finditer(body):
        if not body.endswith(HOST_PREFIXES, 0, match.start()):
            return match
    return None


# The shapes below are the exact text of the Ticket block in docs/formats.md.
STATUS_SHAPE = 'Status: ready-for-agent | ready-for-human (<why>)'
BLOCKED_SHAPE = 'Blocked by: none | 01, 03'
COVERS_SHAPE = 'Covers: AC-2, AC-5 | none'
TESTS_SHAPE = 'Tests: <levels>'
JIRA_SHAPE = 'Jira: <key> | no-ticket'
TOUCHES_SHAPE = 'Touches: <paths and symbols, new ones marked, no line numbers>'
REPRO_SHAPE = 'Repro: <command>'
CLI_LINES = ('Result', 'Metrics', 'Reviewed', 'Verified', 'Red', 'Red-changed')   # written later by the CLI


def blocker_cycle(graph, start):
    """The path [start, ..., start] of a blocker cycle through `start`, or None. `graph` maps a ticket
    number to the numbers that block it."""
    stack, seen = [(start, [start])], set()
    while stack:
        node, path = stack.pop()
        for blocker in graph.get(node, ()):
            if blocker == start:
                return path + [start]
            if blocker not in seen:
                seen.add(blocker)
                stack.append((blocker, path + [blocker]))
    return None


def where(lines, key):
    """The 1-based number of the first line of this key."""
    return ticket.find_lines(lines, key)[0] + 1


def status_errors(lines, parsed):
    """(line number, message) pairs for a missing or wrong `Status:` line."""
    if not ticket.find_lines(lines, 'Status'):
        return [(1, f'no Status: line ({STATUS_SHAPE})')]
    raw = ticket.value_of(lines, 'Status')
    if parsed.status not in STATUS_WORDS:
        return [(where(lines, 'Status'), f'Status: "{raw}" is not a status word ({", ".join(STATUS_WORDS)})')]
    if parsed.status == TICKET_STATUS_HUMAN and not HUMAN_STATUS.fullmatch(raw):
        return [(where(lines, 'Status'), f'Status: "{raw}" gives no reason ({STATUS_SHAPE})')]
    return []


def blocked_errors(lines, parsed, empty_is_error=False):
    """(line number, message) pairs for a missing or unreadable `Blocked by:` line. With `empty_is_error`
    an empty value is reported as empty, not as unreadable."""
    if not parsed.has_blocked_line:
        return [(1, f'no Blocked by: line ({BLOCKED_SHAPE})')]
    if empty_is_error and not parsed.blocked_by.strip():
        return [(where(lines, 'Blocked by'), f'Blocked by: is empty ({BLOCKED_SHAPE})')]
    if parsed.blockers_unreadable:
        return [(where(lines, 'Blocked by'), f'Blocked by: "{parsed.blocked_by}" is not only two-digit '
                                             f'ticket numbers (NN) ({BLOCKED_SHAPE})')]
    return []


def key_errors(lines, keys):
    """(line number, message) pairs for each `(key, shape)` whose line is missing or empty."""
    errors = []
    for key, shape in keys:
        if not ticket.find_lines(lines, key):
            errors.append((1, f'no {key}: line ({shape})'))
        elif not ticket.value_of(lines, key).strip():
            errors.append((where(lines, key), f'{key}: is empty ({shape})'))
    return errors


def ticket_errors(name, text, parsed, folder, graph):
    """Errors for one ticket file: the missing or wrong lines, an unresolved blocker, a line anchor.
    Fills `graph` with the resolved blockers of the ticket, keyed by its number."""
    lines = ticket.split_lines(text)
    errors = [f'{name}:{number}: {message}'
              for number, message in status_errors(lines, parsed) + blocked_errors(lines, parsed)]
    if parsed.has_blocked_line and not parsed.blockers_unreadable:
        number = TICKET_NUMBER.match(name.rsplit('/', 1)[-1]).group(1)
        graph[number] = []
        for blocker in parsed.blockers:
            if ticket.find_blocker(folder, blocker) is None:
                errors.append(f'{name}:{where(lines, "Blocked by")}: blocked by {blocker}: no ticket file '
                              f'{blocker}-*.md in tickets/ ({BLOCKED_SHAPE})')
            else:
                graph[number].append(blocker)
    errors += [f'{name}:{number}: {message}'
               for number, message in key_errors(lines, (('Covers', COVERS_SHAPE), ('Tests', TESTS_SHAPE),
                                                         ('Jira', JIRA_SHAPE)))]
    skip = ticket.fenced(lines)
    for number, (body, _) in enumerate(lines, 1):
        match = None if number - 1 in skip or D_LINE.match(body) else line_anchor(body)
        if match:
            errors.append(f'{name}:{number}: {match.group(0)} is a path with a line number '
                          f'({TOUCHES_SHAPE})')
    return errors


def draft_errors(text):
    """The problems of a light-path ticket draft for `ticket adhoc --from` (formats.md § Ticket): a
    heading, the required lines (the same line checks as ticket_errors), `Status: ready-for-agent`, at
    least one AC checkbox and none of the lines the CLI writes later. Empty when the draft is valid."""
    lines, parsed = ticket.split_lines(text), ticket.parse(text)
    problems = []
    if not ticket.draft_title(lines):
        problems.append('no "# <title>" heading')
    if ticket.find_lines(lines, 'Status') and parsed.status != TICKET_STATUS_READY:
        problems.append(f'Status: "{ticket.value_of(lines, "Status")}" must be {TICKET_STATUS_READY}')
    else:
        problems += [message for _, message in status_errors(lines, parsed)]
    problems += [message for _, message in blocked_errors(lines, parsed, empty_is_error=True)]
    if parsed.blockers:
        problems.append(f'Blocked by: "{parsed.blocked_by}" names a ticket; a light-path draft has Blocked by: none')
    problems += [message for _, message in key_errors(lines, (('Covers', COVERS_SHAPE), ('Tests', TESTS_SHAPE),
                                                             ('Repro', REPRO_SHAPE)))]
    skip = ticket.fenced(lines)
    if not any(index not in skip and ticket.CHECKBOX.match(body) for index, (body, _) in enumerate(lines)):
        problems.append('no acceptance criterion: add a line like "- [ ] AC-1: <criterion>"')
    problems += [f'{key}: is written by the CLI later; remove it from the draft'
                 for key in CLI_LINES if ticket.find_lines(lines, key)]
    return problems


REPRO_OPERATOR = re.compile(r'[;|<>]|&&')


def draft_warnings(text):
    """The warnings for a draft that passed draft_errors: a `Repro:` value with a shell operator is not one
    plain command, and the test writer runs it as written."""
    repro = ticket.value_of(ticket.split_lines(text), 'Repro') or ''
    if REPRO_OPERATOR.search(repro):
        return ['Repro: should be one plain command (no ; && || | > <), because the test writer runs it as written']
    return []


def slice(folder):
    """(errors, warnings) for the tickets of a work-unit folder (`tickets/NN-slug.md`) and its
    stories.md: an AC in no ticket's Covers:, a missing Status:, Blocked by:, Covers:, Tests: or Jira:
    line, a Status: that is no status word, a blocker with no ticket file or in a cycle, a `path:NN`
    line anchor (fenced code blocks and copied `- D-n:` lines are not checked). A ticket over 5 KB only warns."""
    folder = Path(folder)
    if not folder.is_dir():
        raise files.RecordError(f'{folder}: not a folder')
    tickets_dir = folder / 'tickets'
    loaded = [(f'tickets/{path.name}', *ticket.load(path))
              for path in sorted(tickets_dir.glob('*.md')) if TICKET_NUMBER.match(path.name)]
    errors, warnings, graph, covered = [], [], {}, set()
    stories_text = read_optional(folder / 'stories.md')
    if stories_text is None:
        errors.append('stories.md: the file is missing (a work unit keeps its stories in stories.md)')
    else:
        covered = {ac for _, _, parsed in loaded for ac in parsed.covers}
        errors.extend(f'stories.md:{number}: {ac} is in no ticket\'s Covers: line ({COVERS_SHAPE})'
                      for ac, number in stories_errors(stories_text, folder)[1].items() if ac not in covered)
    for name, text, parsed in loaded:
        errors.extend(ticket_errors(name, text, parsed, tickets_dir, graph))
        if len(text.encode('utf-8')) > SLICE_WARN_BYTES:
            warnings.append(f'{name}: over 5 KB; consider splitting the ticket')
    for name, text, parsed in loaded:
        number = TICKET_NUMBER.match(name.rsplit('/', 1)[-1]).group(1)
        path = blocker_cycle(graph, number)
        if path:
            line = ticket.find_lines(ticket.split_lines(text), 'Blocked by')[0] + 1
            errors.append(f'{name}:{line}: blocker cycle {" -> ".join(path)} ({BLOCKED_SHAPE})')
    return errors, warnings


# ---------- the command line ----------

def register(commands, common):
    command = commands.add_parser('check', help='check the invariants the pipeline enforces')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    merge = actions.add_parser(
        'pre-merge', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 0 only when the ticket may be merged; name each failed invariant (exit 1)',
        description=('Exit 0 only when Reviewed: and Verified: both name the head being merged and the\n'
                     'acceptance test is unchanged since its Red: commit, or a Red-changed: line says why.\n'
                     'Each failed invariant is one line on stdout and the exit code is 1; an error is exit 2.\n'
                     'A Red-changed: line also excuses a missing Red: line (a docs-only ticket); the reason\n'
                     'is printed as a note: line. ticket red removes earlier Red-changed: lines when it\n'
                     'records the first Red: line or a different sha. Nothing is written except the index\'s\n'
                     'file stats (git update-index --refresh runs first); run it in the checkout that will merge.'))
    merge.add_argument('ticket', help='path of the ticket file')
    merge.add_argument('--head', default='HEAD',
                       help='the commit being merged: a commit id or a branch (default: HEAD of --repo)')
    merge.add_argument('--repo', help=gitrepo.REPO_HELP)
    merge.set_defaults(handler=run_pre_merge)
    check_stories = actions.add_parser(
        'stories', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 1 when stories.md or decisions.md of a work unit breaks its shape',
        description=('Check a work-unit folder against the shapes in docs/formats.md. Errors: a duplicate AC id,\n'
                     'an AC id that a specify: line of log.md named and stories.md no longer holds, a D-n line\n'
                     'with no Source:, an Out of scope line with no — owner: marker, an owner after — owner:\n'
                     'that names a D-n outside brackets, an owner (an Out of scope line, or a D-n line with\n'
                     '— owner:) that is not in the checkout (a unit folder, ticket NN, ADR-NNNN or a ticket or ADR file path)\n'
                     'and carries no TODO(<owner>, revisit YYYY-MM-DD) key.\n'
                     'Warnings: stories.md over 6 KB, decisions.md over 8 KB. Each is one line on stdout;\n'
                     'exit 1 on any error, 0 otherwise; an error (a folder that is not there) is one\n'
                     'anomaly: line and exit 2.'))
    check_stories.add_argument('folder', help='the work-unit folder (holds stories.md)')
    check_stories.set_defaults(handler=run_stories)
    check_slice = actions.add_parser(
        'slice', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 1 when the tickets of a work unit cannot be run by build',
        description=('Check the tickets/ of a work-unit folder against stories.md and docs/formats.md. Errors: an AC\n'
                     'in no ticket\'s Covers:, a ticket with no Status:, Blocked by:, Covers:, Tests: or Jira: line,\n'
                     'a Status: that is no status word, a blocker with no ticket file or in a cycle, a path:NN\n'
                     'line anchor (not in a fenced block or a copied - D-n: line; a host:port after :// or @\n'
                     'is not one, a bare example.com:8080 is; a path right after @ such as @check.py:42, or in a\n'
                     'URL path right after the host (no port) such as https://host/x/check.py:42, is skipped\n'
                     'too). Warning: a ticket over 5 KB.\n'
                     'Each is one line on stdout; exit 1 on any error, 0 otherwise; an error (a folder that is\n'
                     'not there) is one anomaly: line and exit 2.'))
    check_slice.add_argument('folder', help='the work-unit folder (holds stories.md and tickets/)')
    check_slice.set_defaults(handler=run_slice)


def print_check(word, errors, warnings, folder):
    """Print the errors, then the warnings, then a `<word> check passed` line when there is no error;
    the exit code: 1 on any error, 0 otherwise."""
    for line in errors:
        print(line)
    for line in warnings:
        print(f'warning: {line}')
    if errors:
        return 1
    print(f'{word} check passed for {Path(folder).name}')
    return 0


def run_stories(args, environ):
    return print_check('stories', *stories(args.folder), args.folder)


def run_slice(args, environ):
    return print_check('slice', *slice(args.folder), args.folder)


def run_pre_merge(args, environ):
    _, parsed = ticket.load(args.ticket)
    repo = gitrepo.repo_for(args.repo)
    head = gitrepo.require_commit(repo, args.head)
    gitrepo.refresh_index(repo)
    problems, notes = pre_merge(repo, parsed, head)
    if problems:
        for line in problems:
            print(line)
        return 1
    for line in notes:
        print(line)
    print(f'pre-merge check passed for {Path(args.ticket).name} at {gitrepo.short(head)}')
    return 0

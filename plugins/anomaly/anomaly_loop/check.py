"""check: the invariants the pipeline enforces from ticket files and git, as one command.

  pre-merge   exit 0 only when `Reviewed:` and `Verified:` both name the head being merged and the
              acceptance test is unchanged since its red commit (or the ticket notes why)
  pre-push    exit 0 only when `Reviewed:` and `Verified:` both name the current head: in the mr.md of a
              work-unit folder, or in an ad-hoc ticket; each stale or missing line is one line, exit 1
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
import glob
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import files, gitrepo, paths, ports, ticket
from .constants import (KEY_LINE_CORE, KEY_LINE_LEGACY, TICKET_ADHOC_DIR, TICKET_FIELD_SEPARATOR, TICKET_NUMBER_DIGITS, TICKET_STATUS_DONE,
                        TICKET_STATUS_HUMAN, TICKET_STATUS_IN_PROGRESS, TICKET_STATUS_NEEDS_INFO,
                        TICKET_STATUS_READY, TICKET_STATUS_WONTFIX)
from .records import is_date


def head_problem(repo, key, value, head, what='merged'):
    """One line when the ticket's `<key>:` value is not the head being `what` (merged, or pushed), else None."""
    if not value:
        return f'{key}: no {key}: line; the head being {what} ({gitrepo.short(head)}) has no record'
    found = ticket.named_commit(repo, value)
    if found is None:
        return f'{key}: {ticket.not_a_commit(value)}'
    if found != head:
        return f'{key}: {value} is not the head being {what} ({gitrepo.short(head)})'
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


def pre_push(repo, gate_lines, head):
    """The problems for the `(label, value)` gate lines and the head being pushed, one line each, in order;
    [] when every value names the head."""
    problems = [head_problem(repo, key, value, head, 'pushed') for key, value in gate_lines]
    return [line for line in problems if line]


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
TODO_KEY = re.compile(r'TODO\([^(),]+, revisit (\d{4}-\d{2}-\d{2})\)')   # the date must also be a real one
BACKTICKED = re.compile(r'`([^`]+)`')
TICKET_REF = re.compile(r'\bticket (\d+)\b(?: (of|in) `([^`]+)`)?')   # (number, 'of' or 'in' or '', unit named after it or '')
ADR_REF = re.compile(r'\bADR-(\d{4})\b')
# The folders that hold the tickets of a unit, by the home folder of the unit: only the old `.scratch` layout
# has `issues/`. A unit folder is `<root>/<one of these homes>/<name>/`.
TICKET_FOLDERS = {'.anomaly': ('tickets',), '.scratch': ('tickets', 'issues')}
OWNER_HOME_DIRS = tuple(TICKET_FOLDERS)
ADR_FOLDER_CORE = ports.core_default('adr_folder')[0]   # the `adr_folder` port's core default
ADR_GLOBS = ('.anomaly/*/adr/{}-*.md', '.scratch/*/adr/{}-*.md')   # the adr/ of every unit folder
# A file path is an owner only when it is a ticket file or an ADR file, never any file of the checkout. An ADR
# file in the `adr_folder` port's folder is matched by adr_file_name.
OWNER_FILE = re.compile(r'(?:\.anomaly|\.scratch)/[^/]+/tickets/\d+-[^/]+\.md|\.scratch/[^/]+/issues/\d+-[^/]+\.md|'
                        + re.escape(TICKET_ADHOC_DIR.as_posix()) + r'/[^/]+\.md|'
                        r'(?:\.anomaly|\.scratch)/[^/]+/adr/\d{4}-[^/]+\.md')


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


def relative_parts(name):
    """The path parts of `name`, or () when it has none, has `..` or has an anchor (a root or a drive, read
    the POSIX way and the Windows way, so the answer is the same on every platform)."""
    path = Path(name)
    anchored = PurePosixPath(name).anchor or PureWindowsPath(name).anchor
    return () if '..' in path.parts or anchored else path.parts


def unit_folders(root, name):
    """The existing unit folders `name` names: a bare name under `<root>/.anomaly/` and `<root>/.scratch/`, or
    the path `.anomaly/<name>`, `.scratch/<name>`. `.anomaly/adhoc/` only stores adhoc tickets and is no
    unit. A name the file system refuses (too long) names none."""
    parts = relative_parts(name)
    if len(parts) == 1:
        candidates = [root / home / name for home in OWNER_HOME_DIRS]
    elif len(parts) == 2 and parts[0] in OWNER_HOME_DIRS:
        candidates = [root / name]
    else:
        return []
    try:
        return [] if parts[-1] == TICKET_ADHOC_DIR.name else [path for path in candidates if path.is_dir()]
    except OSError:
        return []


def adr_folder_path(adr_folder):
    """The ADR folder as a repo-relative POSIX path with no trailing slash. A value that names no folder of the
    repo (no path part such as `.`, `..`, an absolute path or a URL) gives the core folder: an org that keeps
    its ADRs outside the repo gets `docs/adr` (ADR-0017)."""
    parts = () if '://' in adr_folder else relative_parts(adr_folder)
    return PurePosixPath(*(parts or relative_parts(ADR_FOLDER_CORE))).as_posix()


def adr_file_name(name, adr_folder):
    """True when `name` has the shape of an ADR file, `NNNN-*.md`, directly in the ADR folder."""
    return re.fullmatch(re.escape(adr_folder_path(adr_folder)) + r'/\d{4}-[^/]+\.md', name) is not None


def owner_file_exists(root, name, adr_folder=ADR_FOLDER_CORE):
    """True when `name` is the path of an existing ticket file or ADR file (OWNER_FILE, or a file in the
    `adr_folder`). Any other file, a name with `..` or no path part, an absolute path, or a name the file
    system refuses (too long) names nothing."""
    try:
        posix = Path(name).as_posix()
        return bool(relative_parts(name)) and (OWNER_FILE.fullmatch(posix) is not None
                                               or adr_file_name(posix, adr_folder)) \
            and (root / name).is_file()
    except OSError:
        return False


def adr_globs(number, adr_folder):
    """The glob patterns, relative to the repo root, of the ADR files `NNNN-*.md` for `number` (a digit string or a
    glob such as `[0-9][0-9][0-9][0-9]`): in the `adr_folder` and in the adr/ of every unit folder."""
    return [pattern.format(number) for pattern in ADR_GLOBS] + [f'{glob.escape(adr_folder_path(adr_folder))}/{number}-*.md']


def adr_exists(root, number, adr_folder):
    """True when `NNNN-*.md` for the ADR `number` is in the `adr_folder` or in the adr/ of a unit folder."""
    return any(any(root.glob(pattern)) for pattern in adr_globs(number, adr_folder))


def ticket_exists(root, folder, number, unit):
    """True when `tickets/NN-*.md` (or, in a `.scratch` unit, `issues/NN-*.md`) exists in the unit folder named
    by `unit` (a name or path, as in unit_folders), or in the checked work-unit `folder` when `unit` is empty.
    NN is padded to the ticket number width."""
    units = unit_folders(root, unit.strip()) if unit else [folder]
    padded = number.zfill(TICKET_NUMBER_DIGITS)
    return any(ticket.find_blocker(path / name, padded)
               for path in units for name in TICKET_FOLDERS.get(path.parent.name, ('tickets',)))


def owner_exists(owner, folder, adr_folder=ADR_FOLDER_CORE):
    """True when the owner value carries a `TODO(<owner>, revisit YYYY-MM-DD)` key with a real date, or names
    something in the checkout (no git lookup): a unit folder other than the checked one (a unit is never its
    own owner, also when its bare name is the name of the checked one), the path of a ticket or ADR file,
    `ticket NN` or `ADR-NNNN` (in the `adr_folder`, or the `adr/` of any unit folder). `ticket NN` is `tickets/NN-*.md`
    (or `issues/NN-*.md` in a `.scratch` unit) of the unit named by "of `unit`" right after it, else of the
    checked work-unit folder; "in `unit`" names no ticket. A ticket never passes on its unit alone, and a
    backticked unit beside a `ticket NN` counts only as a path to a ticket or ADR file. `<root>` is the
    grandparent of the work-unit folder. A bracketed text is a citation and names nothing."""
    if any(is_date(day) for day in TODO_KEY.findall(owner)):
        return True
    folder = Path(folder).resolve()
    root = folder.parent.parent
    plain = BRACKETED.sub('', owner)
    names = [name.strip() for name in BACKTICKED.findall(plain)] + [plain.replace('`', '').strip().rstrip('.')]
    refs = TICKET_REF.findall(plain)
    return (any(owner_file_exists(root, name, adr_folder)
                or not refs and name != folder.name
                and any(path.resolve() != folder for path in unit_folders(root, name))
                for name in names)
            or any(ticket_exists(root, folder, number, unit) for number, word, unit in refs if word != 'in')
            or any(adr_exists(root, number, adr_folder) for number in ADR_REF.findall(plain)))


def read_optional(path):
    """The text of a file, or None when it is not there."""
    return files.read_input(path) if path.is_file() else None


def owner_missing(shape):
    """The tail of an error line for an owner that exists nowhere in the checkout and has no TODO key."""
    return (f'an owner must exist in the checkout (a unit folder, ticket NN, ADR-NNNN, or the path of a ticket or ADR file) '
            f'or carry {TODO_KEY_SHAPE}; a person or a skill needs the key and a placeholder is never an owner ({shape})')


def ac_ids(text):
    """(ids, errors) for the `- AC-n:` lines of stories.md: ids maps each AC id to the number of the first
    line that holds it; a repeated id is an error. No owner is looked up."""
    ids, errors = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        match = AC_LINE.match(line)
        if not match:
            continue
        ac = match.group(1)
        if ac in ids:
            errors.append(f'stories.md:{number}: {ac} is already used on line {ids[ac]}; '
                          f'each AC id is unique ({AC_SHAPE})')
        else:
            ids[ac] = number
    return ids, errors


def uncovered_acs(text, parsed_tickets):
    """(AC id, line number) for each AC of a stories text (ac_ids) that no ticket's `Covers:` names, in file order.
    `parsed_tickets` are `ticket.Ticket` values. `check slice` and `frontier` both use it."""
    covered = {ac for parsed in parsed_tickets for ac in parsed.covers}
    return [(ac, number) for ac, number in ac_ids(text)[0].items() if ac not in covered]


def stories_errors(text, folder, look_up_owners=True, adr_folder=ADR_FOLDER_CORE):
    """Errors for stories.md: duplicate AC ids and Out of scope lines with no `— owner:`, an owner that names a D-n
    outside brackets, or an owner that is not found in the checkout and has no TODO key (the work-unit
    `folder` and the `adr_folder` resolve the names; `look_up_owners=False` skips that last check). Also the ids found."""
    found, errors = ac_ids(text)
    in_scope_out = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('#'):
            in_scope_out = line.strip().lower() == '## out of scope'
        if not in_scope_out or not line.startswith('- ') or AC_LINE.match(line):
            continue
        if OWNER_MARKER not in line:
            errors.append(f'stories.md:{number}: an Out of scope line needs the marker — owner: ({OWNER_SHAPE})')
        elif owner_names_decision(line):
            errors.append(f'stories.md:{number}: an owner is a unit, ticket or ADR, not a D-n ({OWNER_SHAPE})')
        elif look_up_owners and not owner_exists(owner_value(line), folder, adr_folder):
            errors.append(f'stories.md:{number}: {owner_missing(OWNER_SHAPE)}')
    return errors, found


def decisions_errors(text, folder, look_up_owners=True, adr_folder=ADR_FOLDER_CORE):
    """Errors for decisions.md: a `- D-<n>:` line with no `Source:`, or whose `— owner:` names a D-n outside brackets
    or is not found in the checkout and has no TODO key (`look_up_owners=False` skips that last check). A
    `T-n` line needs no Source."""
    errors = []
    for number, line in enumerate(text.splitlines(), 1):
        if not D_LINE.match(line):
            continue
        if 'Source:' not in line:
            errors.append(f'decisions.md:{number}: a decision needs a Source: ({D_SHAPE})')
        elif owner_names_decision(line):
            errors.append(f'decisions.md:{number}: an owner is a unit, ticket or ADR, '
                          f'not a D-n ({D_OWNER_SHAPE})')
        elif look_up_owners and (owner := owner_value(line)) is not None \
                and not owner_exists(owner, folder, adr_folder):
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


def stories(folder, adr_folder=ADR_FOLDER_CORE):
    """(errors, warnings) for a work-unit folder, each a list of one-line strings; `adr_folder` is the folder
    where an ADR owner is looked up besides the adr/ of a unit folder. A missing
    stories.md is an error line; a missing decisions.md or log.md is empty (no decisions, no
    recorded ids). Sizes over 6 KB (stories.md) and 8 KB (decisions.md) only warn. A folder that is not
    `<root>/.anomaly/<unit>` or `<root>/.scratch/<unit>` gets one layout error and no owner lookup, since
    `<root>` is found from that layout."""
    folder = Path(folder)
    if not folder.is_dir():
        raise files.RecordError(f'{folder}: not a folder')
    errors, warnings = [], []
    in_layout = folder.resolve().parent.name in OWNER_HOME_DIRS
    if not in_layout:
        errors.append('folder: a work unit is a folder at <root>/.anomaly/<unit> or <root>/.scratch/<unit>; '
                      'this one is not, so its owners cannot be looked up (move the folder there)')
    stories_text = read_optional(folder / 'stories.md')
    decisions_text = read_optional(folder / 'decisions.md')
    log_text = read_optional(folder / 'log.md')
    if stories_text is None:
        errors.append('stories.md: the file is missing (a work unit keeps its stories in stories.md)')
    else:
        found_errors, found = stories_errors(stories_text, folder, in_layout, adr_folder)
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
        errors.extend(decisions_errors(decisions_text, folder, in_layout, adr_folder))
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
KEY_VALUE_SHAPE = '<key> | no-ticket'   # the value of the key line, whatever the line is called
TOUCHES_SHAPE = 'Touches: <paths and symbols, new ones marked, no line numbers>'
REPRO_SHAPE = 'Repro: <command>'
HYPOTHESES_SHAPE = '1. <hypothesis>: confirmed | refuted, probe <output>'
HYPOTHESES_HEADING = re.compile(r'##\s+Hypotheses\s*$', re.IGNORECASE)
NUMBERED_ITEM = re.compile(r'\d+\.\s+\S')
RESULT_WORD = re.compile(r':\s*(?:confirmed|refuted)\b', re.IGNORECASE)
PROBE_WORD = re.compile(r'\bprobe\b', re.IGNORECASE)
HYPOTHESES_MIN, HYPOTHESES_MAX = 3, 5
CLI_LINES = ('Result', 'Metrics', 'Reviewed', 'Verified', 'Red', 'Red-changed')   # written later by the CLI


def key_shape(key_line):
    """The shape of the key line that `key_line` names; a `Jira:` line is still read in its place."""
    shape = f'{key_line}: {KEY_VALUE_SHAPE}'
    return shape if key_line == KEY_LINE_LEGACY else f'{shape}; a {KEY_LINE_LEGACY}: line is read too'


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
        return [(where(lines, 'Blocked by'), f'Blocked by: "{parsed.blocked_by}" {ticket.BLOCKED_UNREADABLE} '
                                             f'({BLOCKED_SHAPE})')]
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


def ticket_errors(name, text, parsed, folder, graph, key_line=KEY_LINE_CORE):
    """Errors for one ticket file: the missing or wrong lines, an unresolved blocker, a line anchor.
    The key line is the `key_line` line, or the `Jira:` line when the ticket has no such line.
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
                                                         (ticket.key_name(lines, key_line), key_shape(key_line))))]
    skip = ticket.fenced(lines)
    for number, (body, _) in enumerate(lines, 1):
        match = None if number - 1 in skip or D_LINE.match(body) else line_anchor(body)
        if match:
            errors.append(f'{name}:{number}: {match.group(0)} is a path with a line number '
                          f'({TOUCHES_SHAPE})')
    return errors


def hypotheses_errors(lines):
    """The problems of the `## Hypotheses` section of a draft (heading in any case): it is missing, it holds
    fewer than 3 or more than 5 numbered lines (`1. ...`; fenced code is not read), or a numbered line lacks
    `confirmed` or `refuted` (any case) right after a colon, or the word `probe`. The section ends at a
    heading or at the first non-blank line that is not a numbered item."""
    skip = ticket.fenced(lines)
    start = next((index for index, (body, _) in enumerate(lines)
                  if index not in skip and HYPOTHESES_HEADING.match(body)), None)
    if start is None:
        return [f'no "## Hypotheses" section of {HYPOTHESES_MIN} to {HYPOTHESES_MAX} numbered lines ({HYPOTHESES_SHAPE})']
    items = []
    for index in range(start + 1, len(lines)):
        body = lines[index][0]
        if index in skip or not body.strip():
            continue
        if not NUMBERED_ITEM.match(body):
            break
        items.append((index + 1, body))
    if not HYPOTHESES_MIN <= len(items) <= HYPOTHESES_MAX:
        return [f'Hypotheses: {len(items)} numbered lines, need {HYPOTHESES_MIN} to {HYPOTHESES_MAX}; the '
                f'section ends at a heading or the first non-blank line that is not a numbered item ({HYPOTHESES_SHAPE})']
    return [f'Hypotheses: line {number} needs confirmed or refuted after a colon and the word probe '
            f'({HYPOTHESES_SHAPE})'
            for number, body in items if not (RESULT_WORD.search(body) and PROBE_WORD.search(body))]


def draft_errors(text):
    """The problems of a light-path ticket draft for `ticket adhoc --from` (formats.md § Ticket): a
    heading, the required lines (the same line checks as ticket_errors), `Status: ready-for-agent`, at
    least one AC checkbox, a Hypotheses section (hypotheses_errors) and none of the lines the CLI writes
    later. Empty when the draft is valid."""
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
    problems += hypotheses_errors(lines)
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


def slice(folder, key_line=KEY_LINE_CORE):
    """(errors, warnings) for the tickets of a work-unit folder (`tickets/NN-slug.md`) and its
    stories.md: an AC in no ticket's Covers:, a missing Status:, Blocked by:, Covers:, Tests: or key
    line (the `key_line` line, or `Jira:`), a Status: that is no status word, a blocker with no ticket file or in a cycle, a `path:NN`
    line anchor (fenced code blocks and copied `- D-n:` lines are not checked). A ticket over 5 KB only warns."""
    folder = Path(folder)
    if not folder.is_dir():
        raise files.RecordError(f'{folder}: not a folder')
    tickets_dir = folder / 'tickets'
    loaded = [(f'tickets/{path.name}', *ticket.load(path, key_line))
              for path in sorted(tickets_dir.glob('*.md')) if TICKET_NUMBER.match(path.name)]
    errors, warnings, graph = [], [], {}
    stories_text = read_optional(folder / 'stories.md')
    if stories_text is None:
        errors.append('stories.md: the file is missing (a work unit keeps its stories in stories.md)')
    else:
        errors.extend(f'stories.md:{number}: {ac} is in no ticket\'s Covers: line ({COVERS_SHAPE})'
                      for ac, number in uncovered_acs(stories_text, (parsed for _, _, parsed in loaded)))
    for name, text, parsed in loaded:
        errors.extend(ticket_errors(name, text, parsed, tickets_dir, graph, key_line))
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
    push = actions.add_parser(
        'pre-push', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 0 only when the unit or ad-hoc ticket was reviewed and verified on the head; '
             'name each stale line (exit 1)',
        description=('Exit 0 only when Reviewed: and Verified: both name the current head of --repo. A work-unit\n'
                     'folder keeps them in its mr.md (mr reviewed, mr verified), an ad-hoc ticket in the ticket\n'
                     'itself (ticket reviewed, ticket verified). Each failed line is one line on stdout and the\n'
                     'exit code is 1: a missing line, a value that is not a commit, or a head that moved. A\n'
                     'missing or unreadable mr.md, or a target that is neither a work-unit folder nor an\n'
                     'ad-hoc ticket, is one anomaly: line and exit 2. Nothing is written.'))
    push.add_argument('target', help='a work-unit folder (reads mr.md in it) or an ad-hoc ticket file')
    push.add_argument('--repo', help=gitrepo.REPO_HELP)
    push.set_defaults(handler=run_pre_push)
    check_stories = actions.add_parser(
        'stories', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 1 when stories.md or decisions.md of a work unit breaks its shape',
        description=('Check a work-unit folder against the shapes in docs/formats.md. Errors: a duplicate AC id,\n'
                     'an AC id that a specify: line of log.md named and stories.md no longer holds, a D-n line\n'
                     'with no Source:, an Out of scope line with no — owner: marker, an owner after — owner:\n'
                     'that names a D-n outside brackets, an owner (an Out of scope line, or a D-n line with\n'
                     '— owner:) that is not in the checkout (a unit folder other than the checked one, ticket NN\n'
                     'or ticket NN of `<unit>` (never "in"; issues/ only in .scratch),\n'
                     'ADR-NNNN or a ticket or ADR file path; an ADR is looked up in the folder the adr_folder\n'
                     'port names, from the profile in --home, and in the adr/ of every unit folder)\n'
                     'and carries no TODO(<owner>, revisit YYYY-MM-DD) key with a real date, a work-unit folder\n'
                     'that is not <root>/.anomaly/<unit> or <root>/.scratch/<unit> (one error, no owner lookup).\n'
                     'Warnings: stories.md over 6 KB, decisions.md over 8 KB. Each is one line on stdout;\n'
                     'exit 1 on any error, 0 otherwise; an error (a folder that is not there) is one\n'
                     'anomaly: line and exit 2.'))
    check_stories.add_argument('folder', help='the work-unit folder (holds stories.md)')
    check_stories.set_defaults(handler=run_stories)
    check_slice = actions.add_parser(
        'slice', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 1 when the tickets of a work unit cannot be run by build',
        description=('Check the tickets/ of a work-unit folder against stories.md and docs/formats.md. Errors: an AC\n'
                     'in no ticket\'s Covers:, a ticket with no Status:, Blocked by:, Covers:, Tests: or key line\n'
                     '(the line the key_line port names, from the profile in --home; a Jira: line is read too),\n'
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
    adr_folder = ports.adr_folder(paths.resolve_home(args.home, environ))
    return print_check('stories', *stories(args.folder, adr_folder), args.folder)


def run_slice(args, environ):
    key_line = ports.key_line(paths.resolve_home(args.home, environ))
    return print_check('slice', *slice(args.folder, key_line), args.folder)


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


def run_pre_push(args, environ):
    from . import mr   # inside the function: mr imports this module
    found = mr.locate(args.target)
    if found.unit:
        if not found.state.is_file():
            raise files.RecordError(f'{found.state}: no MR file; `mr reviewed` and `mr verified` write it')
        state = mr.read_state(found.state)
        gate_lines = [(label, state.get(label)) for label in (mr.REVIEWED_LABEL, mr.VERIFIED_LABEL)]
    else:
        _, parsed = ticket.load(args.target)
        gate_lines = [(mr.REVIEWED_LABEL, parsed.reviewed), (mr.VERIFIED_LABEL, parsed.verified)]
    repo = gitrepo.repo_for(args.repo)
    head = gitrepo.require_commit(repo, 'HEAD')
    problems = pre_push(repo, gate_lines, head)
    if problems:
        for line in problems:
            print(line)
        return 1
    print(f'pre-push check passed for {Path(args.target).name} at {gitrepo.short(head)}')
    return 0

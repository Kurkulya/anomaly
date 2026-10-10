"""ticket: the one owner of every ticket line shape, and the only writer of ticket lines. It is also the
writer of the dated `Amended` lines of planning files (stories.md, decisions.md).

A ticket is a markdown file `.anomaly/<work-unit>/tickets/NN-<slug>.md` (or one file in
`.anomaly/adhoc/`). Its state lives in header lines, each plain (`Status: x`) or bold
(`**Status:** x`); both are read, and a rewritten line keeps its own shape.

  show        print the state lines; warn when `Blocked by:` is missing
  gate        exit 0 only when every blocker is `done` and the ticket is `ready-for-agent` (or `in-progress`)
  set-status  rewrite `Status:`; `in-progress` also writes `Metrics: started <t>`
  result      tick the ACs, write `Status: done`, `Result:` and `Metrics:`
  reviewed    add or replace `Reviewed: <sha>`        (additive line)
  verified    add or replace `Verified: <sha>`        (additive line)
  red         write `Red: <sha> · <test path>` (the first one, or a different sha, removes the earlier
              `Red-changed:` lines), or add `Red-changed: <reason>`  (additive lines)
  adhoc       write `.anomaly/adhoc/<date>-<slug>.md` under the main checkout from a task text or --from a checked draft
  amend       add `Amended <date>: <text>` at the end of a file, or --after an AC-n / D-n line of stories.md / decisions.md

Writing is a text edit: only the named lines change, every other byte (line endings, a missing
final newline) stays. A new line goes after the nearest line that comes before it in LINE_ORDER
and takes the line ending of that neighbour. Handlers never read the clock: `args.now` and
`args.today` come from the CLI; the git calls go through gitrepo. Lines inside a fenced code
block are examples: they are never read as state lines or checkboxes. A leading byte order mark
is kept on write and does not hide the first line.
"""
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from . import files, gitrepo, paths, ports, privacy, records
from .constants import (KEY_LINE_CORE, NO_START_WARNING, TICKET_ADHOC_DIR, TICKET_FIELD_SEPARATOR, TICKET_SLUG_MAX_CHARS,
                        TICKET_STATUS_DONE, TICKET_STATUS_HUMAN, TICKET_STATUS_IN_PROGRESS, TICKET_STATUS_NEEDS_INFO,
                        TICKET_STATUS_READY, TICKET_STATUS_UNKNOWN, TICKET_STATUS_WONTFIX, TICKET_START_UNKNOWN,
                        TICKET_NUMBER_DIGITS, TICKET_TIME_FORMAT, TICKET_TITLE_MAX_CHARS)
from .files import RecordError
from .records import require_one_line

LINE_ORDER = ('Status', 'Metrics', 'Reviewed', 'Verified', 'Red', 'Red-changed', 'Result')
HEADER_KEYS = (KEY_LINE_CORE, 'Covers', 'Blocked by', 'Tests', 'Model')   # where a line goes when none before it exists
SHOWN_KEYS = ('Status', 'Blocked by', 'Covers', KEY_LINE_CORE, 'Tests', 'Model', 'Repro', 'Base', 'Reviewed', 'Verified',
              'Red', 'Red-changed')   # Base: the work unit's integration branch, which build reads here;
                                      # KEY_LINE_CORE marks the slot of the key line, shown under the `key_line` name
IMPLEMENTER_ROLES = ('implement', 'implement_wide')   # the values of a ticket's `Model:` line: the implementer's model role
MODEL_DEFAULT = IMPLEMENTER_ROLES[0]                  # a ticket without the line runs on this role
METRIC_COUNTS = (('full suites', 'suites'), ('type-checks', 'type_checks'), ('reviewer passes', 'reviewer_passes'),
                 ('High', 'high'), ('fix rounds', 'fix_rounds'), ('changed lines', 'changed_lines'))   # Metrics: label, count
WAITS_FOR_PERSON = (TICKET_STATUS_HUMAN, TICKET_STATUS_NEEDS_INFO, TICKET_STATUS_WONTFIX)   # the statuses only a person moves on
STARTS_OR_RUNS = (TICKET_STATUS_READY, TICKET_STATUS_IN_PROGRESS, TICKET_STATUS_DONE)   # the statuses that do not wait
BOM = chr(0xFEFF)   # a byte order mark; written as a code point so the file holds no invisible character

LINE_SPLIT = re.compile(r'(\r\n|\n|\r)')
FENCE = re.compile(r'\s{0,3}(`{3,}|~{3,})')
NUMBERED_TITLE = re.compile(rf'#\s*[0-9]{{{TICKET_NUMBER_DIGITS}}}:\s*(.+?)\s*$')
HEADING = re.compile(r'#\s+(\S.*?)\s*$')
STATUS_WORD = re.compile(r'[\w-]+')
AC_ID = re.compile(r'AC-\d+')
AMEND_TARGET = re.compile(r'(?:AC|D)-\d+')
AMENDED_LINE = re.compile(r'(\s*)Amended \d{4}-\d{2}-\d{2}\b')
CHECKBOX = re.compile(r'(\s*[-*+]\s+\[)([ xX])(\]\s*\**AC-(\d+)(?!\d))')
STARTED = re.compile(r'\bstarted\s+(\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2})?)')
UNKNOWN_START = re.compile(rf'\bstarted\s+{re.escape(TICKET_START_UNKNOWN)}\b')
OPEN_ITEMS = re.compile(r'\bOpen(?:\s*\([^)]*\))?:\s*(.+)$')
BLOCKER_NUMBER = re.compile(rf'\b([0-9]{{{TICKET_NUMBER_DIGITS}}})\b')
BLOCKED_UNREADABLE = 'is not only two-digit ticket numbers (NN)'   # the end of every message about an unreadable Blocked by: value


# ---------- lines ----------

class Lines(list):
    """The lines of a text as [body, ending] pairs; `bom` is a byte order mark that began the text."""
    bom = ''


def split_lines(text):
    """The lines of `text` with their own endings; join_lines gives `text` back."""
    bom = BOM if text.startswith(BOM) else ''
    parts = LINE_SPLIT.split(text[len(bom):])
    lines = Lines([parts[i], parts[i + 1] if i + 1 < len(parts) else ''] for i in range(0, len(parts), 2))
    if lines and lines[-1] == ['', '']:
        lines.pop()
    lines.bom = bom
    return lines


def join_lines(lines):
    return lines.bom + ''.join(body + end for body, end in lines)


def fenced(lines):
    """Indexes of the lines inside a fenced code block, fence lines included. A fence is three or
    more backticks or tildes; it ends at a line of only that character, at least as long."""
    inside, marker = set(), None
    for index, (body, _) in enumerate(lines):
        match = FENCE.match(body)
        if marker is None:
            if match:
                marker = match.group(1)
                inside.add(index)
            continue
        inside.add(index)
        if match and set(body.strip()) == {marker[0]} and len(body.strip()) >= len(marker):
            marker = None
    return inside


def label(key):
    """Matches a header line of this key, plain or bold; group 1 is the label, group 2 the value."""
    return re.compile(rf'(\*\*{re.escape(key)}:\*\*|{re.escape(key)}:)[ \t]*(.*?)[ \t]*$')


def find_lines(lines, key):
    """Indexes of every line of this key outside fenced code blocks, in file order."""
    pattern, skip = label(key), fenced(lines)
    return [index for index, (body, _) in enumerate(lines) if index not in skip and pattern.match(body)]


def value_of(lines, key):
    """The first value of this key, or None when the file has no such line."""
    found = find_lines(lines, key)
    return label(key).match(lines[found[0]][0]).group(2) if found else None


def values_of(lines, key):
    pattern = label(key)
    return tuple(pattern.match(lines[index][0]).group(2) for index in find_lines(lines, key))


def line_ending(lines):
    return next((end for _, end in lines if end), '\n')


def insert_after(lines, index, body):
    """Insert one line after lines[index]. It takes that line's ending; when that line is the last
    one and has none, it gets the file's ending and the new line has none, so a missing final
    newline stays missing."""
    end = lines[index][1]
    if not end:
        lines[index][1] = line_ending(lines)
    lines.insert(index + 1, [body, end])


def anchor(lines, key):
    """The index after which a new line of this key goes: the last line of a key at or before it in
    LINE_ORDER, else the last header line, else the title."""
    before = LINE_ORDER[:LINE_ORDER.index(key) + 1] if key in LINE_ORDER else ()
    for keys in (before, HEADER_KEYS):
        found = [index for name in keys for index in find_lines(lines, name)]
        if found:
            return max(found)
    return 0


def put_line(lines, key, value):
    """Set the key's line to `value`: the first existing line keeps its label shape and ending;
    otherwise a plain line is added."""
    found = find_lines(lines, key)
    if found:
        body = lines[found[0]][0]
        match = label(key).match(body)
        gap = body[match.end(1):match.start(2)] or ' '
        lines[found[0]][0] = body[:match.end(1)] + gap + value
    elif lines:
        insert_after(lines, anchor(lines, key), f'{key}: {value}')
    else:
        lines.append([f'{key}: {value}', ''])


def add_line(lines, key, value):
    insert_after(lines, anchor(lines, key), f'{key}: {value}')


def remove_lines(lines, key):
    """Delete every line of this key outside fenced code blocks. When the last line of a file with no
    final newline goes, the line before it becomes the last and has no ending either."""
    for index in reversed(find_lines(lines, key)):
        end = lines[index][1]
        del lines[index]
        if not end and index > 0 and index == len(lines):
            lines[index - 1][1] = ''


# ---------- reading ----------

@dataclass(frozen=True)
class Ticket:
    title: str
    status: str                  # 'unknown' when there is no readable Status: line
    blocked_by: str              # the raw Blocked by: value
    has_blocked_line: bool
    blockers: tuple              # ticket numbers ('01', '02'); none for `None`
    blockers_unreadable: bool    # a Blocked by: value that is not `none` and holds no ticket number, or a
                                 # number outside the parentheses that is not two digits
    key: str                     # the first word of the `key_line` line
    covers: tuple                # AC ids, each once; none for `none`
    has_covers_line: bool
    tests: str
    reviewed: str
    verified: str
    red: tuple | None            # (sha, test path) or None
    red_changed: tuple           # one reason per Red-changed: line
    metrics: str
    started: str
    result: str
    has_result_line: bool
    open: str                    # the text after `Open:` or `Open (Low):` on the Result line
    model: str                   # the raw Model: value; MODEL_DEFAULT when there is no such line


def parse(text, slug='', key_line=KEY_LINE_CORE):
    """Read a ticket's text into its fields. Ports the old ticket.mjs rules, and reads `Blocked by:`
    plain as well as bold. The key is read from the `key_line` line."""
    lines = split_lines(text)
    skip = fenced(lines)
    bodies = [body for index, (body, _) in enumerate(lines) if index not in skip]
    title = next((m.group(1) for b in bodies if (m := NUMBERED_TITLE.match(b))), None) \
        or next((m.group(1) for b in bodies if (m := HEADING.match(b))), None) or slug

    status = STATUS_WORD.match(value_of(lines, 'Status') or '')
    blocked = value_of(lines, 'Blocked by')
    without_titles = re.sub(r'\([^)]*\)', '', blocked or '')
    says_none = blocked is None or re.search(r'\bnone\b', without_titles, re.I)
    blockers = () if says_none else tuple(BLOCKER_NUMBER.findall(without_titles))
    other_numbers = not says_none and any(len(number) != TICKET_NUMBER_DIGITS
                                           for number in re.findall(r'\b[0-9]+\b', without_titles))
    key = (value_of(lines, key_line) or '').split(None, 1)
    covers = value_of(lines, 'Covers') or ''
    covered = () if re.match(r'none\b', covers, re.I) else tuple(dict.fromkeys(AC_ID.findall(covers)))
    red = value_of(lines, 'Red')
    sha, _, path = red.partition(TICKET_FIELD_SEPARATOR) if red is not None else ('', '', '')
    metrics = value_of(lines, 'Metrics') or ''
    started = STARTED.search(metrics)
    result = value_of(lines, 'Result')
    open_items = OPEN_ITEMS.search(result or '')
    model = value_of(lines, 'Model')
    return Ticket(
        title=title, status=status.group(0) if status else TICKET_STATUS_UNKNOWN, blocked_by=blocked or '',
        has_blocked_line=blocked is not None, blockers=blockers,
        blockers_unreadable=not says_none and (not blockers or other_numbers), key=key[0] if key else '',
        covers=covered, has_covers_line=bool(covers.strip()), tests=value_of(lines, 'Tests') or '',
        reviewed=value_of(lines, 'Reviewed') or '', verified=value_of(lines, 'Verified') or '',
        red=(sha, path) if red is not None else None, red_changed=values_of(lines, 'Red-changed'),
        metrics=metrics, started=started.group(1) if started else '', result=result or '',
        has_result_line=result is not None, open=open_items.group(1) if open_items else '',
        model=MODEL_DEFAULT if model is None else model)


def state_lines(text, key_line=KEY_LINE_CORE):
    """The lines `ticket show` prints: each state line with bold markers dropped, in SHOWN_KEYS order;
    the key line is shown under the name the `key_line` port gives it."""
    lines = split_lines(text)
    shown = []
    for key in SHOWN_KEYS:
        key = key_line if key == KEY_LINE_CORE else key
        shown += [f'{key}: {value}'.rstrip() for value in values_of(lines, key)]
    return shown


def load(path, key_line=KEY_LINE_CORE):
    """(text, Ticket) of a ticket file, read as bytes so no line ending is translated."""
    text = read_text(path)
    return text, parse(text, slug=Path(path).stem, key_line=key_line)


def read_text(path, what='ticket'):
    """The file's text exactly as stored (a byte order mark kept, no line ending translated).
    `what` names the file in an error, for a caller that reads another line-edited file (the seam ledger)."""
    if str(path) == '-':
        raise RecordError(f'a {what} path of - would read standard input; give a file path')
    try:
        return files.read_input(path, keep_bom=True)
    except (FileNotFoundError, IsADirectoryError):
        raise RecordError(f'{what} file not found: {path}') from None


def find_blocker(folder, number):
    """The ticket file `<number>-*.md` beside the ticket, or None."""
    return next(iter(sorted(Path(folder).glob(f'{number}-*.md'))), None)


def unfinished_blockers(folder, parsed):
    """(number, status, file) for each blocker that is not done, in the order of `Blocked by:`. A blocker with
    no ticket file in `folder` has no status and no file (both None): it counts as not done."""
    unfinished = []
    for number in parsed.blockers:
        found = find_blocker(folder, number)
        status = load(found)[1].status if found else None
        if status != TICKET_STATUS_DONE:
            unfinished.append((number, status, found))
    return unfinished


def is_blocked(parsed, unfinished):
    """The gate rule, for `ticket gate` and `frontier`: a ticket is blocked when a blocker is not done
    (`unfinished`, from unfinished_blockers) or its `Blocked by:` value cannot be read."""
    return bool(unfinished) or parsed.blockers_unreadable


def waits(parsed):
    """The rule for `ticket gate` and `frontier`, an allow list: a ticket that is not `done` and not `in-progress`
    starts only when its status is `ready-for-agent`; any other status waits, whatever its blockers are."""
    return parsed.status not in STARTS_OR_RUNS


def wait_text(parsed):
    """The reason a ticket that waits is not started: `<status>, waits for a person` for `ready-for-human`,
    `needs-info` and `wontfix`; any other status (a typo, no readable `Status:` line) is named as not ready."""
    if parsed.status in WAITS_FOR_PERSON:
        return f'{parsed.status}, waits for a person'
    return f'status {parsed.status} is not {TICKET_STATUS_READY}'


def blocker_lines(path, unfinished):
    """One line per blocker that is not done (`unfinished`, from unfinished_blockers): its number, its status
    and its file."""
    name = Path(path).name
    return [f'blocked by {number}: no ticket file {number}-*.md next to {name}' if found is None
            else f'blocked by {number}: {status} ({found.name})'
            for number, status, found in unfinished]


# ---------- writing ----------

def check_sha(value, name='sha'):
    if not privacy.COMMIT_ID.fullmatch(value):
        raise RecordError(f'{name} must be a commit id in lowercase hex (7 to 12, 40 or 64 digits), got: {value}')
    return value


def named_commit(repo, value):
    """The full id of the commit a ticket line names, or None when the value is not a commit id or no
    commit of the repository has it."""
    return gitrepo.resolve_commit(repo, value) if privacy.COMMIT_ID.fullmatch(value) else None


def not_a_commit(value):
    """Why a ticket line's value names no commit: it is not a commit id, or no commit has it."""
    if not privacy.COMMIT_ID.fullmatch(value):
        return f'{value} is not a commit id'
    return f'{value} is not a commit of this repository'


def check_status(value):
    if not STATUS_WORD.fullmatch(value):
        raise RecordError(f'status must be one word of letters, digits, _ and -, got: {value}')
    return value


def require_status(lines):
    """Refuse a file with no Status: line: it is no ticket (a wrong path), so no ticket line goes into it."""
    if not find_lines(lines, 'Status'):
        raise RecordError('the ticket has no Status: line')


def set_status(text, status, now):
    """The text with `Status:` rewritten; `in-progress` also gets `Metrics: started <now>` unless the
    ticket already holds a start time (a resumed ticket keeps its first one)."""
    lines = split_lines(text)
    require_status(lines)
    put_line(lines, 'Status', check_status(status))
    metrics = value_of(lines, 'Metrics') or ''
    if status == TICKET_STATUS_IN_PROGRESS and not STARTED.search(metrics):
        started = f'started {now.strftime(TICKET_TIME_FORMAT)}'
        # a ticket closed with `started unknown` keeps the rest of its line (the counts) when it is reopened
        put_line(lines, 'Metrics', UNKNOWN_START.sub(started, metrics, count=1) if UNKNOWN_START.search(metrics)
                 else started)
    return join_lines(lines)


def record_sha(text, key, sha):
    """The text with one `Reviewed: <sha>` or `Verified: <sha>` line, added or replaced."""
    lines = split_lines(text)
    require_status(lines)
    put_line(lines, key, check_sha(sha))
    return join_lines(lines)


def record_red(text, sha, path):
    """The text with `Red: <sha> · <test path>`, added or replaced. A `Red-changed:` reason covers only
    the edits after the red commit it was written for, so a sha that differs from the one already
    recorded, or a first `Red:` line, starts a new red step and removes the earlier `Red-changed:`
    lines (a note written for "no Red line" ends when the red commit arrives). The same sha again
    keeps them; one id may be the start of the other (a short id and the full one)."""
    lines = split_lines(text)
    require_status(lines)
    current = parse(text).red
    if not current or not (current[0].startswith(sha) or sha.startswith(current[0])):
        remove_lines(lines, 'Red-changed')
    put_line(lines, 'Red', f'{check_sha(sha)}{TICKET_FIELD_SEPARATOR}{require_one_line("the test path", path)}')
    return join_lines(lines)


def record_red_changed(text, reason):
    """The text with one more `Red-changed: <reason>` line; a reason already there is not repeated."""
    lines = split_lines(text)
    require_status(lines)
    reason = require_one_line('the reason', reason)
    if reason not in values_of(lines, 'Red-changed'):
        add_line(lines, 'Red-changed', reason)
    return join_lines(lines)


def tick(lines, number, explicit):
    """Tick every unticked checkbox of AC-<number> outside fenced code blocks; an explicitly named AC
    with no checkbox is an error."""
    found, skip = False, fenced(lines)
    for index, line in enumerate(lines):
        match = None if index in skip else CHECKBOX.match(line[0])
        if match and int(match.group(4)) == number:
            found = True
            line[0] = match.group(1) + 'x' + line[0][match.end(2):]
    if explicit and not found:
        raise RecordError(f'no checkbox for AC-{number} in the ticket')


def close(text, branch, merge, open_items, now, counts, acs=()):
    """The text of a merged ticket: ACs ticked (the named ones, else those on `Covers:`),
    `Status: done`, `Metrics:` and `Result:`. `counts` holds suites, type_checks, reviewer_passes,
    high, fix_rounds and changed_lines; a count that is None or absent is left out of `Metrics:`
    (never written as 0). A ticket with no start time gets `started unknown`, not `now`: the merge
    time would make a ticket look as if it took no time."""
    lines = split_lines(text)
    require_status(lines)
    parsed = parse(text)
    for name in acs:
        if not AC_ID.fullmatch(name):
            raise RecordError(f'an AC is named like AC-12, got: {name}')
    for name in acs or parsed.covers:
        tick(lines, int(name[3:]), explicit=bool(acs))
    stamp = now.strftime(TICKET_TIME_FORMAT)
    put_line(lines, 'Status', TICKET_STATUS_DONE)
    metrics = [f'started {parsed.started or TICKET_START_UNKNOWN}', f'merged {stamp}']
    metrics += [f'{label} {counts[key]}' for label, key in METRIC_COUNTS if counts.get(key) is not None]
    put_line(lines, 'Metrics', TICKET_FIELD_SEPARATOR.join(metrics))
    put_line(lines, 'Result', TICKET_FIELD_SEPARATOR.join((
        require_one_line('the branch', branch), check_sha(merge, 'the merge'),
        f'Open: {require_one_line("the open items", open_items)}')))
    return join_lines(lines)


def metric_counts(parsed):
    """{key: count} for the counts of METRIC_COUNTS (`suites`, `type_checks`, ...) that the `Metrics:` line of a
    parsed ticket holds; a count the line lacks is not in the result. The reader of what `close` writes."""
    found = {}
    for label, key in METRIC_COUNTS:
        match = re.search(rf'\b{re.escape(label)} (\d+)\b', parsed.metrics)
        if match:
            found[key] = int(match.group(1))
    return found


def amend(text, today, note, after=None):
    """The text with one `Amended <date>: <note>` line. Without `after` it goes at the end of the file.
    With `after` (AC-n or D-n) it goes below that list item and below any `Amended` lines already under
    it, indented like them (else two spaces under a D-n, none under an AC-n, as in the planning files).
    The note and the id are checked before anything is changed."""
    note = require_one_line('the amend text', note)
    privacy.check_text('ticket amend', 'the text', note)
    line = f'Amended {today.isoformat()}: {note}'
    lines = split_lines(text)
    if after is None:
        if lines:
            insert_after(lines, len(lines) - 1, line)
        else:
            lines.append([line, '\n'])
        return join_lines(lines)
    if not AMEND_TARGET.fullmatch(after):
        raise RecordError(f'--after names an AC or a decision like AC-12 or D-3, got: {after}')
    item, skip = re.compile(rf'\s*[-*+]\s+\**{re.escape(after)}(?!\d)'), fenced(lines)
    target = next((index for index, (body, _) in enumerate(lines) if index not in skip and item.match(body)), None)
    if target is None:
        raise RecordError(f'no {after} line in the file')
    last, indent = target, '  ' if after.startswith('D-') else ''
    while last + 1 < len(lines) and last + 1 not in skip and (older := AMENDED_LINE.match(lines[last + 1][0])):
        last, indent = last + 1, older.group(1)
    insert_after(lines, last, indent + line)
    return join_lines(lines)


def slugify(text):
    plain = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '-', plain.lower()).strip('-')[:TICKET_SLUG_MAX_CHARS].rstrip('-') or 'task'


ADHOC_TITLE_PREFIX = 'Adhoc: '   # the start of the heading adhoc_ticket writes; `mr body` strips it from the summary


def adhoc_ticket(task, slug, today):
    """(file name, text) of a one-file ticket for a free-text task. The task is put on one line, so
    its text can never add a state line. The ticket has no key line."""
    task = ' '.join(task.split())
    if not task:
        raise RecordError('the task text is empty')
    check_slug(slug)
    title = task[:TICKET_TITLE_MAX_CHARS]
    text = (f'# {ADHOC_TITLE_PREFIX}{title}\n\nCovers: AC-1\nBlocked by: None\nStatus: {TICKET_STATUS_READY}\n\n'
            f'**What to build:** {task}\n\nAcceptance criteria:\n\n- [ ] AC-1: {task}\n')
    return f'{today.isoformat()}-{slug or slugify(task)}.md', text


def draft_title(lines):
    """The text after `# ` of the first heading outside fenced code blocks, or None."""
    skip = fenced(lines)
    return next((m.group(1) for i, (body, _) in enumerate(lines) if i not in skip and (m := HEADING.match(body))), None)


def check_slug(slug):
    """Refuse a `--slug` that is no slug or is too long; None (not given) passes."""
    if slug is not None and not records.is_slug(slug):
        raise RecordError(f'the slug is lowercase words joined by - (letters and digits), got: {slug}')
    if slug is not None and len(slug) > TICKET_SLUG_MAX_CHARS:
        raise RecordError(f'the slug is at most {TICKET_SLUG_MAX_CHARS} characters, got {len(slug)}')


# ---------- the command line ----------

def register(commands, common):
    command = commands.add_parser('ticket', help='read and edit .anomaly tickets: the one writer of ticket lines')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')

    def action(name, handler, help_text, file_help='path of the ticket file'):
        parser = actions.add_parser(name, parents=[common], help=help_text)
        parser.add_argument('ticket', help=file_help)
        parser.set_defaults(handler=handler)
        return parser

    action('show', run_show, 'print the state lines; warn when Blocked by: is missing')
    action('gate', run_gate, 'exit 0 only when every blocker is done and the ticket is ready-for-agent or in-progress; else say why (exit 1)')
    status = action('set-status', run_set_status, 'rewrite Status:; in-progress also writes Metrics: started')
    status.add_argument('status', help='one word, for example in-progress or done')
    result = action('result', run_result, 'tick the ACs, write Status: done, Result: and Metrics:')
    result.add_argument('--branch', required=True, help='the ticket branch that was merged')
    result.add_argument('--merge', help='merge commit: a commit id or any ref such as a branch '
                                        '(default: HEAD of --repo)')
    result.add_argument('--open', default='none', help='open items for the Result line (default: none)')
    result.add_argument('--ac', action='append', help='an AC to tick (repeatable; default: those on Covers:)')
    result.add_argument('--suites', type=records.count_option, help='full suite runs (left out of Metrics: when not passed)')
    result.add_argument('--type-checks', dest='type_checks', type=records.count_option,
                        help='type-checks (left out of Metrics: when not passed)')
    result.add_argument('--reviewer-passes', dest='reviewer_passes', type=records.count_option,
                        help='reviewer passes (left out of Metrics: when not passed)')
    result.add_argument('--high', type=records.count_option, help='High findings (left out of Metrics: when not passed)')
    result.add_argument('--fix-rounds', dest='fix_rounds', type=records.count_option,
                        help='fix rounds after review (left out of Metrics: when not passed)')
    result.add_argument('--changed-lines', dest='changed_lines', type=records.count_option,
                        help='lines added plus deleted by the merge (default: counted by git)')
    result.add_argument('--repo', help=gitrepo.REPO_HELP)
    for name, key in (('reviewed', 'Reviewed'), ('verified', 'Verified')):
        sha = action(name, run_sha, f'add or replace the {key}: line')
        sha.set_defaults(key=key)
        sha.add_argument('sha', help='the head that was checked (a commit of --repo; written in full)')
        sha.add_argument('--repo', help=gitrepo.REPO_HELP)
    red = action('red', run_red, 'write Red: <sha> · <test path> (the first one, or a different sha, '
                                 'drops the earlier Red-changed: lines), or add Red-changed: <reason>')
    red.add_argument('sha', nargs='?', help='the red commit (a commit of --repo; written in full)')
    red.add_argument('path', nargs='?', help='the acceptance test file')
    red.add_argument('--repo', help=gitrepo.REPO_HELP)
    red.add_argument('--changed', help='the reason the test file changed after its red commit')
    amended = action('amend', run_amend, 'add Amended <date>: <text> at the end of the file, or below an AC-n / D-n line',
                     'path of the ticket, stories.md or decisions.md')
    amended.add_argument('text', help='the note, one line (checked for private content)')
    amended.add_argument('--after', metavar='ID', help='an AC-n of stories.md or a D-n of decisions.md; the line goes '
                                                       'below it and below the Amended lines already under it')
    adhoc = actions.add_parser('adhoc', parents=[common],
                               help='write .anomaly/adhoc/<date>-<slug>.md under the main checkout from a task text '
                                    'or --from a checked draft')
    adhoc.add_argument('task', nargs='?', help='the task, in words (or give --from)')
    adhoc.add_argument('--from', dest='draft', metavar='DRAFT',
                       help='a checked light-path draft file, written unchanged (instead of the task text)')
    adhoc.add_argument('--slug', help='file name part (default: made from the task, or the draft title)')
    adhoc.add_argument('--repo', help=gitrepo.REPO_HELP)
    adhoc.set_defaults(handler=run_adhoc)


def edit(path, change):
    """Read the ticket, apply `change(text)` and save; a refusal names the file."""
    text = read_text(path)
    try:
        files.write_text(path, change(text))
    except RecordError as error:
        raise RecordError(f'{path}: {error}') from None
    except gitrepo.GitError as error:
        raise gitrepo.GitError(f'{path}: {error}') from None


def print_blocker_warnings(path, parsed):
    name = Path(path).name
    if not parsed.has_blocked_line:
        print(f'warning: no Blocked by: line in {name}; it is not known whether it is blocked')
    if parsed.blockers_unreadable:
        print(f'warning: Blocked by: "{parsed.blocked_by}" in {name} {BLOCKED_UNREADABLE}')


def run_show(args, environ):
    key_line = ports.key_line(paths.resolve_home(args.home, environ))
    text, parsed = load(args.ticket, key_line)
    for line in state_lines(text, key_line):
        print(line)
    print_blocker_warnings(args.ticket, parsed)
    return 0


def run_gate(args, environ):
    _, parsed = load(args.ticket)
    print_blocker_warnings(args.ticket, parsed)
    unfinished = unfinished_blockers(Path(args.ticket).parent, parsed)
    for line in blocker_lines(args.ticket, unfinished):
        print(line)
    if waits(parsed):
        print(wait_text(parsed))
        return 1
    return 1 if is_blocked(parsed, unfinished) else 0


def run_set_status(args, environ):
    edit(args.ticket, lambda text: set_status(text, args.status, args.now))
    return 0


def commit_in_repo(option, sha):
    """The full id of the commit `sha` names in the repository of a `--repo` option; the format is
    checked first, so a name such as `HEAD` or `-x` never reaches git."""
    check_sha(sha)
    repo = gitrepo.repo_for(option)
    found = named_commit(repo, sha)
    if found is None:
        raise gitrepo.GitError(not_a_commit(sha))
    return found


def run_sha(args, environ):
    edit(args.ticket, lambda text: record_sha(text, args.key, commit_in_repo(args.repo, args.sha)))
    return 0


def run_red(args, environ):
    if args.changed is not None:
        if args.sha or args.path:
            raise RecordError('give either <sha> <path> or --changed <reason>, not both')
        if args.repo:
            raise RecordError('--repo has no use with --changed: it only names the repository of <sha>')
        edit(args.ticket, lambda text: record_red_changed(text, args.changed))
    elif args.sha and args.path:
        edit(args.ticket, lambda text: record_red(text, commit_in_repo(args.repo, args.sha), args.path))
    else:
        raise RecordError('give <sha> <path>, or --changed <reason>')
    return 0


def run_result(args, environ):
    repo = gitrepo.repo_for(args.repo)
    merge = gitrepo.require_commit(repo, args.merge or 'HEAD')
    lines_changed = gitrepo.changed_line_count(repo, gitrepo.merge_range(merge)) if args.changed_lines is None \
        else args.changed_lines
    counts = dict(suites=args.suites, type_checks=args.type_checks, reviewer_passes=args.reviewer_passes,
                  high=args.high, fix_rounds=args.fix_rounds, changed_lines=lines_changed)
    has_start = bool(load(args.ticket)[1].started)
    edit(args.ticket, lambda text: close(text, args.branch, merge, args.open, args.now, counts, args.ac or ()))
    if not has_start:
        print(NO_START_WARNING)
    return 0


def draft_ticket(path, slug, today):
    """(file name, text, warnings) of an adhoc ticket from a draft file; a refusal names every problem."""
    text = read_text(path, 'draft')
    from . import check   # a lazy import: check.py imports this module at its top
    problems = check.draft_errors(text)
    if problems:
        raise RecordError(f'{path}: the draft is refused: ' + '; '.join(problems))
    check_slug(slug)
    name = f'{today.isoformat()}-{slug or slugify(draft_title(split_lines(text)))}.md'
    return name, text, check.draft_warnings(text)


def run_amend(args, environ):
    edit(args.ticket, lambda text: amend(text, args.today, args.text, args.after))
    return 0


def run_adhoc(args, environ):
    if args.draft is not None and args.task is not None:
        raise RecordError('--from and the task text are exclusive: give one')
    if args.draft is None and args.task is None:
        raise RecordError('give the task text, or --from <draft file>')
    name, text, warnings = draft_ticket(args.draft, args.slug, args.today) if args.draft is not None \
        else (*adhoc_ticket(args.task, args.slug, args.today), [])
    # a folder named with --repo may be outside git; the working folder must be in a repository
    path = gitrepo.shared_root(gitrepo.repo_for(args.repo, outside_git=bool(args.repo))) / TICKET_ADHOC_DIR / name
    if path.exists():
        raise RecordError(f'{path} already exists')
    files.write_text(path, text)
    for warning in warnings:
        print(f'warning: {warning}', file=sys.stderr)
    print(path)
    return 0

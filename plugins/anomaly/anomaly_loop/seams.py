"""seams: keep a seam ledger (`.anomaly/<work-unit>/seams.md`; the old `.scratch/<feature>/seams.md` is
read the same way until the switch-over) true after each merge.

  prune   list, and rewrite, the ledger lines that name a file the merge renamed, deleted or reshaped
  add     append one line: `- <name> · <owner file> · replaces <old way> (ticket NN)`

Both are pending the calibrate verdict of experiment `seam-ledger-goes-stale` (rule I34); the help
says "pending verdict" with no date, which would go stale.

A ledger line is `- <name> · <owner> · <rest>`; the owner part starts with the owner file (in
backticks or bare), and any further backticked names after it (`parse`, `Ticket`) are the names the
file is expected to still mention. A line "names" a file when its owner file is that path or the end
of it (a bare `paths.py` matches `plugins/x/paths.py`); when a bare name matches several changed
files and none has exactly that path, the line is `ambiguous`: it is listed and left alone. A merge
is read as the changes of the merge commit against its first parent:
- deleted  the file is gone: the line is removed
- renamed  the owner field takes the new path (a bare name keeps its form); no other field changes
- reshaped the file changed and no longer mentions one of the names the line lists (as a whole word;
           a heuristic, not a parse): the line is removed, because its claim is probably no longer
           true; `seams add` writes the new one
Every other line, and every byte of it, stays; so do lines that are not ledger lines. The ledger is
not tracked by git, so the removed lines are printed.
"""
import re
from pathlib import Path

from . import files, gitrepo, records, ticket
from .constants import SEAM_BULLET, SEAM_REPLACES, TICKET_FIELD_SEPARATOR, TICKET_NUMBER_DIGITS
from .files import RecordError

BACKTICKED = re.compile(r'`([^`]+)`')
NAME = re.compile(r'[A-Za-z_][\w.]*')
PENDING = 'pending verdict'


# ---------- reading a line ----------

def line_fields(body):
    """The fields of a ledger line (name, owner, rest), or None when the line is not one (a heading,
    a note)."""
    if not body.startswith(SEAM_BULLET):
        return None
    fields = body[len(SEAM_BULLET):].split(TICKET_FIELD_SEPARATOR)
    return fields if len(fields) >= 3 else None


def path_before(change):
    """The path a change had before the merge: the old path of a rename, else its path."""
    return change.old_path if change.status == 'R' else change.path


def owner_file(field):
    words = field.split()
    return words[0].strip('`') if words else ''


def listed_names(field):
    """The names a line lists for its owner file: the backticked parts after the path, each cut to its
    leading identifier (`resolve(home)` gives resolve, `RepoLayer.risk_patterns` gives risk_patterns)."""
    spans = BACKTICKED.findall(field)
    if spans and spans[0] == owner_file(field):
        spans = spans[1:]
    names = []
    for span in spans:
        found = NAME.match(span)
        if found:
            names.append(found.group(0).rstrip('.').split('.')[-1])
    return names


def has_name(text, name):
    """True when `name` is in `text` as a whole word (a name ending in `_` is a prefix, as in `TICKET_STATUS_*`)."""
    return re.search(rf'(?<!\w){re.escape(name)}' + ('' if name.endswith('_') else r'(?!\w)'), text) is not None


def names_path(owner, path):
    return bool(owner) and (path == owner or path.endswith('/' + owner))


# ---------- prune ----------

def judge(body, changes, content_at):
    """What the merge did to one ledger line: None, or (verb, detail, new body); a new body of None
    removes the line. `content_at(path)` is the text of a file as merged, or None."""
    fields = line_fields(body)
    if fields is None:
        return None
    field = fields[1]
    owner = owner_file(field)
    matches = [c for c in changes if c.status not in 'AC' and names_path(owner, path_before(c))]
    if not matches:
        return None
    exact = [c for c in matches if path_before(c) == owner]
    if len(matches) > 1 and not exact:
        return 'ambiguous', f'{owner} matches {", ".join(path_before(c) for c in matches)}', body
    change = (exact or matches)[0]
    if change.status == 'D':
        return 'deleted', change.path, None
    gone = [name for name in listed_names(field) if not has_name(content_at(change.path) or '', name)]
    if gone:
        return 'reshaped', f'{change.path} no longer mentions {", ".join(gone)}', None
    if change.status != 'R':
        return None
    prefix = change.old_path[:len(change.old_path) - len(owner)]
    moved = change.path[len(prefix):] if change.path.startswith(prefix) else change.path
    fields[1] = field.replace(owner, moved, 1)
    return 'renamed', f'{change.old_path} -> {change.path}', SEAM_BULLET + TICKET_FIELD_SEPARATOR.join(fields)


def prune(text, changes, content_at):
    """(new text, one report line per ledger line the merge made stale)."""
    lines, kept, report = ticket.split_lines(text), ticket.Lines(), []
    kept.bom = lines.bom
    for body, end in lines:
        verdict = judge(body, changes, content_at)
        if verdict is None:
            kept.append([body, end])
            continue
        verb, detail, new_body = verdict
        report.append(f'{verb}: {detail}: {body}')
        if new_body is not None:
            kept.append([new_body, end])
    return ticket.join_lines(kept), report


# ---------- add ----------

def ledger_line(name, owner, replaces, number):
    fields = []
    for label, value in (('name', name), ('owner file', owner), ('old way', replaces)):
        value = records.require_one_line(f'the {label}', value)
        if TICKET_FIELD_SEPARATOR in value:
            raise RecordError(f'the {label} cannot hold "{TICKET_FIELD_SEPARATOR.strip()}" between spaces: {value}')
        fields.append(value)
    records.check_ticket_number('the ticket', number)
    name, owner, replaces = fields
    return (f'{SEAM_BULLET}{name}{TICKET_FIELD_SEPARATOR}{owner}{TICKET_FIELD_SEPARATOR}'
            f'{SEAM_REPLACES} {replaces} (ticket {number})')


def append_line(text, line):
    """(new text, True) with the line as the last line; (text, False) when the same line is already there."""
    lines = ticket.split_lines(text)
    if any(body == line for body, _ in lines):
        return text, False
    if lines:
        ticket.insert_after(lines, len(lines) - 1, line)
    else:
        lines.append([line, '\n'])
    return ticket.join_lines(lines), True


# ---------- the command line ----------

def register(commands, common):
    command = commands.add_parser('seams', help=f'keep a seam ledger true after a merge ({PENDING})')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    prune_parser = actions.add_parser(
        'prune', parents=[common], help=f'list and rewrite the ledger lines a merge made stale ({PENDING})',
        description=('List, and rewrite, the ledger lines that name a file the merge renamed, deleted or '
                     f'reshaped (the file no longer mentions a name the line lists). {PENDING}, rule I34.'))
    prune_parser.add_argument('ledger', help='path of the seams.md file')
    prune_parser.add_argument('--merge', default='HEAD',
                              help='the merge commit, read against its first parent (default: HEAD of --repo)')
    prune_parser.add_argument('--repo', help=gitrepo.REPO_HELP)
    prune_parser.add_argument('--dry-run', action='store_true', dest='dry_run', help='list only; do not rewrite')
    prune_parser.set_defaults(handler=run_prune)
    add = actions.add_parser(
        'add', parents=[common], help=f'append one ledger line ({PENDING})',
        description=f'Append one line: - <name> · <owner file> · replaces <old way> (ticket NN). {PENDING}, rule I34.')
    add.add_argument('ledger', help='path of the seams.md file')
    add.add_argument('--name', required=True, help='what the seam is')
    add.add_argument('--owner', required=True, help='the owner file, with the names it owns in backticks')
    add.add_argument('--replaces', required=True, help='the old way this replaces')
    add.add_argument('--ticket', required=True, help=f'the ticket number, {TICKET_NUMBER_DIGITS} digits')
    add.set_defaults(handler=run_add)


def read_ledger(path, missing_ok=False):
    """The ledger text exactly as stored; '' for a missing file when `missing_ok` and its folder exists."""
    path = Path(path)
    if missing_ok and str(path) != '-' and not path.exists() and path.parent.is_dir():
        return ''
    return ticket.read_text(path, what='seam ledger')


def run_prune(args, environ):
    repo = gitrepo.repo_for(args.repo)
    merge = gitrepo.require_commit(repo, args.merge)
    text = read_ledger(args.ledger)
    changes = gitrepo.changed_files(repo, gitrepo.merge_range(merge))
    new_text, report = prune(text, changes, lambda path: gitrepo.file_at(repo, merge, path))
    for line in report:
        print(line)
    if not report:
        print('no ledger line names a file this merge renamed, deleted or reshaped')
    elif new_text != text and not args.dry_run:
        files.write_text(args.ledger, new_text)
    return 0


def run_add(args, environ):
    line = ledger_line(args.name, args.owner, args.replaces, args.ticket)
    new_text, added = append_line(read_ledger(args.ledger, missing_ok=True), line)
    if added:
        files.write_text(args.ledger, new_text)
    print(f'{"added" if added else "already listed"}: {line}')
    return 0

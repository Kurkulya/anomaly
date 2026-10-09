"""frontier: the tickets of a work unit that can start now.

  frontier <work unit folder>

Reads every ticket of the unit (`tickets/` in either layout, `issues/` in an old `.scratch` unit) and prints,
one line each, in ticket order:

  <ticket>: <status>                 a startable ticket: `ready-for-agent`, every blocker done
  <ticket>: in progress              a ticket that is in progress; it is neither startable nor blocked
  <ticket>: <status>, waits for a person   a ticket that is `ready-for-human`, `needs-info` or `wontfix`, whatever
                                     its blockers are (ticket.waits_for_person); it is neither startable nor blocked
  <ticket>: blocked by <NN> (<status>), ...   only when no ticket is startable: each open ticket that waits

Exit 0 when a ticket is startable, or a ticket is in progress (the unit is not stuck; the blocked lines are
printed when nothing is startable), or every ticket left waits for a person, or every ticket is done (one
`finished` line). Exit 1 when no ticket is startable, none is in progress and one is blocked by a ticket that is
not done. Exit 2 (one `anomaly:` line naming each ticket)
when a ticket that is not done has no `Blocked by:` line or names a blocker with no ticket file. A `warning:`
line follows for each AC of the unit's AC file (`spec.md` when the unit has one, else `stories.md`) that no
ticket's `Covers:` names.

The rule "every blocker is done" is `ticket.unfinished_blockers` and `ticket.is_blocked`, and the rule "waits for a
person" is `ticket.waits_for_person`, the ones `ticket gate` uses; the uncovered ACs are `check.uncovered_acs`, the one `check slice` uses; the ticket folders are
`check.TICKET_FOLDERS`.
"""
from pathlib import Path
from typing import NamedTuple

from . import check, files, ticket
from .constants import KEY_LINE_CORE, TICKET_STATUS_DONE, TICKET_STATUS_IN_PROGRESS
from .files import RecordError

AC_FILES = ('spec.md', 'stories.md')   # the files that hold the ACs, the first one that exists is read (ADR-0011)
START, RUNNING, BLOCKED, WAITING = 'start', 'running', 'blocked', 'waiting'


def unit_home(folder):
    """The name of the folder that holds the unit folder: `.anomaly` or `.scratch` in a layout."""
    return folder.resolve().parent.name


def tickets_folder(folder):
    """The folder of the unit that holds its tickets: the first of `check.TICKET_FOLDERS` for its layout."""
    names = check.TICKET_FOLDERS.get(unit_home(folder), ('tickets',))
    found = next((folder / name for name in names if (folder / name).is_dir()), None)
    if found is None:
        raise RecordError(f'{folder}: no {" or ".join(names)} folder')
    return found


def load_tickets(folder, key_line=KEY_LINE_CORE):
    """[(path, Ticket)] of the numbered ticket files in the folder, in ticket order; the key of each is read
    from the `key_line` line (ticket.key_name)."""
    return [(path, ticket.load(path, key_line)[1]) for path in sorted(folder.glob('*.md'))
            if check.TICKET_NUMBER.match(path.name)]


def blocked_text(parsed, unfinished):
    """Why a ticket waits: its unfinished blockers with their status, and a `Blocked by:` value that is unreadable."""
    reasons = []
    if unfinished:
        reasons.append('blocked by ' + ', '.join(f'{number} ({status})' for number, status, _ in unfinished))
    if parsed.blockers_unreadable:
        reasons.append(f'Blocked by: "{parsed.blocked_by}" {ticket.BLOCKED_UNREADABLE}')
    return '; '.join(reasons)


class Entry(NamedTuple):
    kind: str   # START, RUNNING, BLOCKED or WAITING
    line: str   # the line `frontier` prints for the ticket
    path: Path  # the ticket file


def classify(tickets_dir, tickets):
    """(entries, errors): entries is [Entry] in ticket order for each ticket that is not done; errors is
    one text per ticket that has no `Blocked by:` line or a blocker with no ticket file (such a ticket has no entry)."""
    entries, errors = [], []
    for path, parsed in tickets:
        if parsed.status == TICKET_STATUS_DONE:
            continue
        if not parsed.has_blocked_line:
            errors.append(f'{path.name}: no Blocked by: line')
            continue
        unfinished = ticket.unfinished_blockers(tickets_dir, parsed)
        missing = [number for number, _, found in unfinished if found is None]
        if missing:
            errors.append(f'{path.name}: no ticket file for blocker {", ".join(missing)}')
        elif parsed.status == TICKET_STATUS_IN_PROGRESS:
            entries.append(Entry(RUNNING, f'{path.stem}: in progress', path))
        elif ticket.waits_for_person(parsed):
            entries.append(Entry(WAITING, f'{path.stem}: {ticket.person_text(parsed)}', path))
        elif ticket.is_blocked(parsed, unfinished):
            entries.append(Entry(BLOCKED, f'{path.stem}: {blocked_text(parsed, unfinished)}', path))
        else:
            entries.append(Entry(START, f'{path.stem}: {parsed.status}', path))
    return entries, errors


def ac_file(folder):
    """The AC file of the unit folder: `spec.md` when the unit has one, else `stories.md` (ADR-0011); None when it
    has neither. The one pick `frontier` and `mr body` use."""
    return next((folder / name for name in AC_FILES if (folder / name).is_file()), None)


def ac_warnings(folder, tickets):
    """One warning line per AC of the unit's AC file that no ticket's `Covers:` names."""
    path = ac_file(folder)
    if path is None:
        return [f'warning: the unit has no {" or ".join(AC_FILES)}; the ACs are not checked']
    text = files.read_input(path)
    return [f'warning: {path.name}:{number}: {ac} is in no ticket\'s Covers: line'
            for ac, number in check.uncovered_acs(text, (parsed for _, parsed in tickets))]


def read(folder):
    """(tickets, entries) of a work-unit folder: every ticket as load_tickets gives it, and the classify entries
    of the tickets that are not done. An error of the unit or of a ticket (see classify) raises RecordError."""
    folder = Path(folder)
    if not folder.is_dir():
        raise RecordError(f'{folder}: not a folder')
    tickets_dir = tickets_folder(folder)
    tickets = load_tickets(tickets_dir)
    if not tickets:
        raise RecordError(f'{tickets_dir}: no ticket files NN-*.md')
    entries, errors = classify(tickets_dir, tickets)
    if errors:
        raise RecordError('; '.join(errors))
    return tickets, entries


def look(folder):
    """(lines, exit code) for a work-unit folder; an error raises RecordError."""
    folder = Path(folder)
    tickets, entries = read(folder)
    kinds = {entry.kind for entry in entries}
    if START in kinds:
        shown, code = (START, RUNNING, WAITING), 0
    elif BLOCKED in kinds:
        shown, code = (RUNNING, BLOCKED, WAITING), 0 if RUNNING in kinds else 1
    else:
        shown, code = (RUNNING, WAITING), 0
    lines = [entry.line for entry in entries if entry.kind in shown]
    if not entries:
        lines = [f'{folder.resolve().name}: finished, every ticket is done']
    return lines + ac_warnings(folder, tickets), code


def register(commands, common):
    command = commands.add_parser('frontier', parents=[common],
                                  help='list the tickets of a work unit that can start now (exit 1 when none can)')
    command.add_argument('folder', help='the work-unit folder (holds tickets/, or issues/ in an old .scratch unit)')
    command.set_defaults(handler=run_frontier)


def run_frontier(args, environ):
    lines, code = look(args.folder)
    for line in lines:
        print(line)
    return code

"""conduct: the helpers of the `conduct` skill.

  conduct status <work unit folder>     print the wave report: five lines, read-only

The wave report is, in this order (the label opens each line):

  done: <N>                            tickets with `Status: done`
  failed: <N> (<ticket>, ...)          tickets in progress with no `Result:` line: a run that stopped without a merge
  open: <N> (<ticket>, ...)            every other ticket that is not done and not failed: startable, blocked, and
                                       in progress with a `Result:` line; the three counts add up to the tickets
  next: <ticket>, ...                  the startable tickets (the `start` entries of frontier.classify)
  cost: ...                            the cost line of `worklog report` for the unit (worklog.cost_line)

The names and the count of a group are `0` and no names when it is empty; `next` says `none` when nothing can
start. The ticket rules are the ones `frontier` uses (frontier.read); a ticket that frontier reports as an error
(no `Blocked by:` line, a blocker with no ticket file) ends the command with exit 2 and prints no line. The work
unit key of the cost line is the name of the folder, as in `worklog add`; a unit with no work-unit line has no cost
line, which is an error of `worklog report` too (exit 2).
"""
from pathlib import Path

from . import frontier, paths, worklog
from .constants import TICKET_STATUS_DONE

LABELS = ('done', 'failed', 'open', 'next', 'cost')   # the order of the lines


def register(commands, common):
    command = commands.add_parser('conduct', help='the helpers of the conduct skill')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    status = actions.add_parser('status', parents=[common],
                                help='print the five-line wave report of a work unit: done, failed, open, next, '
                                     'cost (writes nothing)')
    status.add_argument('folder', help='the work-unit folder (holds tickets/)')
    status.set_defaults(handler=run_status)


def counted(names):
    """`<N> (<name>, ...)`, or just `0` for no names."""
    return f'{len(names)} ({", ".join(names)})' if names else '0'


def wave_lines(folder, home):
    """The five lines of the wave report for the unit folder; an error raises RecordError."""
    folder = Path(folder)
    tickets, entries = frontier.read(folder)
    parsed = dict(tickets)
    done = sum(ticket.status == TICKET_STATUS_DONE for ticket in parsed.values())
    failed = [entry for entry in entries
              if entry.kind == frontier.RUNNING and not parsed[entry.path].has_result_line]
    opened = [entry for entry in entries if entry not in failed]
    following = [entry.path.stem for entry in entries if entry.kind == frontier.START]
    cost = worklog.cost_line(worklog.read_report(home, folder.resolve().name))
    return [f'{LABELS[0]}: {done}',
            f'{LABELS[1]}: {counted([entry.path.stem for entry in failed])}',
            f'{LABELS[2]}: {counted([entry.path.stem for entry in opened])}',
            f'{LABELS[3]}: {", ".join(following) or "none"}',
            cost]


def run_status(args, environ):
    for line in wave_lines(args.folder, paths.resolve_home(args.home, environ)):
        print(line)
    return 0

"""progress: a work unit's current state as one JSON object, for a UI to draw (ADR-0025).

  progress --json --unit <name> [--repo <checkout>]     print one JSON line, read-only

The unit is the folder `.anomaly/<name>/` of the main checkout of the repository that holds `--repo` (default:
the working folder; gitrepo.shared_root, so a worktree reads the main checkout's units, ADR-0011). The object is
schema 1; its keys, in this order:

  schema      1
  unit        the unit name; `picked_by` is `unit-option`
  stage       {name, ended} of the unit's work-unit line with the newest `ended` (a tie: the later line in the
              file); null when no line has one
  wave        the number of `log.md` lines of stage `conduct` whose text starts with `wave `; 0 with no `log.md`
  counts      {done, failed, open}: numbers from conduct.wave_counts, the counts of `conduct status`
  next        the startable tickets (`NN-slug`), from conduct.wave_counts
  tickets     one object per ticket, in ticket order: slug, title, status, blocked_by (`NN` list), kind (`done`, or
              the frontier kind), reason (the frontier line without its `<NN-slug>: ` prefix; null for done), red,
              reviewed and verified (the line is there with a value), build_minutes (the minutes of the ticket's
              timed `build` lines, worklog.minutes_of; null when none is timed), high and fix_rounds (the
              `Metrics:` counts, ticket.metric_counts; null when absent)
  mr          {link, reviewed, verified}: the `MR:`, `Reviewed:` and `Verified:` values of `mr.md`
              (mr.read_state), each null when absent
  cost        {weighted_tokens, merged, build_minutes} of worklog.read_report; null when the unit has no
              work-unit line
  warnings    one text per ticket that cannot be loaded or classified; that ticket is left out

A name with no unit folder, or a value that is not one plain folder name (`.`, `..`, a path), prints only
`schema`, `unit` (null) and `warnings`. The work-unit lines are read only
through worklog.read_report (ADR-0014). Nothing is written and nothing leaves the machine. The JSON is
`json.dumps` with its default arguments: one line, ASCII escapes.
"""
import json
import re
from pathlib import Path

from . import check, conduct, files, frontier, gitrepo, log, mr, paths, ticket, worklog
from .constants import TICKET_ADHOC_DIR, TICKET_STATUS_DONE, WORKLOG_BUILD_STAGE
from .files import RecordError

SCHEMA = 1
UNITS_DIR = TICKET_ADHOC_DIR.parent   # `.anomaly`: the folder that holds the work-unit folders (ADR-0011)
PICKED_BY_OPTION = 'unit-option'
DONE_KIND = 'done'                    # the kind of a done ticket, which has no frontier entry
WAVE_STAGE, WAVE_TEXT = 'conduct', 'wave '   # a wave line of log.md: `<time> conduct: wave ...`
LOG_LINE = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2} ([^\s:]+): (.*)')   # the log.md line shape (log.py)


def register(commands, common):
    command = commands.add_parser('progress', parents=[common],
                                  help="print a work unit's stage, wave, tickets, MR gate and cost as one JSON "
                                       'object (writes nothing)')
    command.add_argument('--json', action='store_true', required=True, help='print JSON (the only form)')
    command.add_argument('--unit', required=True, help='the work-unit name: the folder under .anomaly/')
    command.add_argument('--repo', help=gitrepo.REPO_HELP)
    command.set_defaults(handler=run_progress)


def classified(folder):
    """(tickets, entries, warnings): each numbered ticket file loaded with ticket.load and classified alone with
    frontier.classify; a ticket that fails either is left out and named in a warning."""
    tickets_dir = frontier.tickets_folder(folder)
    tickets, entries, warnings = [], [], []
    for path in frontier.ticket_paths(tickets_dir):
        try:
            parsed = ticket.load(path)[1]
            found, errors = frontier.classify(tickets_dir, [(path, parsed)])
        except RecordError as error:
            warnings.append(f'{path.name}: {error}')
            continue
        if errors:
            warnings.extend(errors)
            continue
        tickets.append((path, parsed))
        entries.extend(found)
    return tickets, entries, warnings


def ticket_minutes(report, number):
    """The minutes of the ticket's timed `build` lines, or None when none is timed (or there is no report)."""
    if report is None:
        return None
    spans = [worklog.minutes_of(row) for row in report.rows
             if row.get('stage') == WORKLOG_BUILD_STAGE and row.get('ticket') == number]
    timed = [span for span in spans if span is not None]
    return sum(timed) if timed else None


def ticket_entry(path, parsed, entry, report):
    """The JSON object of one ticket; `entry` is its frontier Entry, None for a done ticket."""
    counts = ticket.metric_counts(parsed)
    return {
        'slug': path.stem,
        'title': parsed.title,
        'status': parsed.status,
        'blocked_by': list(parsed.blockers),
        'kind': DONE_KIND if entry is None else entry.kind,
        'reason': None if entry is None else entry.line.removeprefix(f'{path.stem}: '),
        'red': parsed.red is not None and any(parsed.red),
        'reviewed': bool(parsed.reviewed),
        'verified': bool(parsed.verified),
        'build_minutes': ticket_minutes(report, check.TICKET_NUMBER.match(path.name).group(1)),
        'high': counts.get('high'),
        'fix_rounds': counts.get('fix_rounds'),
    }


def last_stage(rows):
    """{name, ended} of the work-unit line with the newest `ended` (the text sorts in time order), the later line
    winning a tie; None when no line has one."""
    newest = None
    for row in rows:
        if row.get('ended') and (newest is None or row['ended'] >= newest['ended']):
            newest = row
    return None if newest is None else {'name': newest.get('stage'), 'ended': newest['ended']}


def wave_number(folder):
    """The number of `conduct` lines of the unit's log.md whose text starts with `wave `; 0 with no log.md."""
    path = folder / log.FILE_NAME
    if not path.is_file():
        return 0
    matches = (LOG_LINE.fullmatch(line) for line in files.read_input(path).splitlines())
    return sum(1 for match in matches
               if match and match.group(1) == WAVE_STAGE and match.group(2).startswith(WAVE_TEXT))


def unit_report(home, unit):
    """The worklog.read_report of the unit, or None when it has no work-unit line (read_report raises)."""
    try:
        return worklog.read_report(home, unit)
    except RecordError:
        return None


def build(folder, home):
    """The schema-1 object of the unit folder."""
    unit = folder.name
    tickets, entries, warnings = classified(folder)
    counts = conduct.wave_counts(tickets, entries)
    report = unit_report(home, unit)
    by_path = {entry.path: entry for entry in entries}
    state = mr.read_state(folder / mr.STATE_FILE)
    cost = None if report is None else {
        'weighted_tokens': report.weighted,
        'merged': report.merged,
        'build_minutes': report.build_minutes,
    }
    return {
        'schema': SCHEMA,
        'unit': unit,
        'picked_by': PICKED_BY_OPTION,
        'stage': None if report is None else last_stage(report.rows),
        'wave': wave_number(folder),
        'counts': {'done': counts['done'], 'failed': len(counts['failed']), 'open': len(counts['open'])},
        'next': counts['next'],
        'tickets': [ticket_entry(path, parsed, by_path.get(path), report) for path, parsed in tickets],
        'mr': {'link': state.get(mr.MR_LABEL), 'reviewed': state.get(mr.REVIEWED_LABEL),
               'verified': state.get(mr.VERIFIED_LABEL)},
        'cost': cost,
        'warnings': warnings,
    }


def is_folder_name(value):
    """True for one plain folder name: not empty, `.` or `..`, and no path separator or absolute path."""
    return value not in ('', '.', '..') and Path(value).name == value


def run_progress(args, environ):
    root = gitrepo.shared_root(Path(args.repo) if args.repo else Path.cwd())
    folder = root / UNITS_DIR / args.unit
    if not is_folder_name(args.unit):
        report = {'schema': SCHEMA, 'unit': None,
                  'warnings': [f'no work unit {args.unit}: not one folder name under {UNITS_DIR.as_posix()}/']}
    elif folder.is_dir():
        report = build(folder, paths.resolve_home(args.home, environ))
    else:
        report = {'schema': SCHEMA, 'unit': None, 'warnings': [f'no work unit {args.unit}: {folder} is not a folder']}
    print(json.dumps(report))
    return 0

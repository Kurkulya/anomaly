"""progress: a work unit's current state as one JSON object, for a UI to draw (ADR-0025).

  progress --json [--unit <name>] [--repo <checkout>]     print one JSON line, read-only

The unit is the folder `.anomaly/<name>/` of the main checkout of the repository that holds `--repo` (default:
the working folder; gitrepo.shared_root, so a worktree reads the main checkout's units, ADR-0011); a `--repo`
inside a `.anomaly/` folder starts from the folder that holds it. With no `--unit` the unit is picked, in this
order: a unit with a ticket whose `Base:` equals the current branch, else the unit whose key in place of
`<slug>` in the `branch` port pattern equals it (only when `<slug>` is the pattern's one placeholder), else the
unfinished unit with the newest `log.md` line; the `adhoc` folder is never a unit. The object is schema 1; its
keys, in this order:

  schema      1
  unit        the unit name; `picked_by` is `unit-option` (--unit), `branch` or `newest-log`
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
  warnings    one text per ticket that cannot be loaded or classified; that ticket is left out; when several units
              match the branch, one text that names the units not picked

A name with no unit folder, or a value that is not one plain folder name (`.`, `..`, a path), prints only
`schema`, `unit` (null) and `warnings`. The work-unit lines are read only
through worklog.read_report (ADR-0014). Nothing is written and nothing leaves the machine. The JSON is
`json.dumps` with its default arguments: one line, ASCII escapes.
"""
import json
import re
from pathlib import Path

from . import check, conduct, files, frontier, gitrepo, log, mr, paths, ports, records, ticket, worklog
from .constants import TICKET_ADHOC_DIR, WORKLOG_BUILD_STAGE
from .files import RecordError

SCHEMA = 1
UNITS_DIR = TICKET_ADHOC_DIR.parent   # `.anomaly`: the folder that holds the work-unit folders (ADR-0011)
PICKED_BY_OPTION, PICKED_BY_BRANCH, PICKED_BY_NEWEST_LOG = 'unit-option', 'branch', 'newest-log'
BRANCH_PORT, SLUG = 'branch', '<slug>'
PLACEHOLDER = re.compile(r'<[^<>]*>')
DONE_KIND = 'done'                    # the kind of a done ticket, which has no frontier entry
WAVE_STAGE, WAVE_TEXT = 'conduct', 'wave '   # a wave line of log.md: `<time> conduct: wave ...`


def register(commands, common):
    command = commands.add_parser('progress', parents=[common],
                                  help="print a work unit's stage, wave, tickets, MR gate and cost as one JSON "
                                       'object (writes nothing)')
    command.add_argument('--json', action='store_true', required=True, help='print JSON (the only form)')
    command.add_argument('--unit', help='the work-unit name: the folder under .anomaly/ (default: the unit is picked '
                                        'from the current branch, else the newest unfinished one)')
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
    winning a tie; a line whose `ended` is not such a time (records.is_ticket_time) is skipped; None when no line
    has one."""
    newest = None
    for row in rows:
        if records.is_ticket_time(row.get('ended')) and (newest is None or row['ended'] >= newest['ended']):
            newest = row
    return None if newest is None else {'name': newest.get('stage'), 'ended': newest['ended']}


def wave_number(folder):
    """The number of `conduct` lines of the unit's log.md whose text starts with `wave `; 0 with no log.md."""
    return sum(1 for _, stage, text in log.entries(folder) if stage == WAVE_STAGE and text.startswith(WAVE_TEXT))


def unit_report(home, unit):
    """The worklog.read_report of the unit, or None when it has no work-unit line (read_report raises)."""
    try:
        return worklog.read_report(home, unit)
    except RecordError:
        return None


def build(folder, home, picked_by):
    """The schema-1 object of the unit folder, picked in the way `picked_by` names."""
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
        'picked_by': picked_by,
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


def start_folder(folder):
    """The folder the repository is looked up from: the folder that holds the nearest `.anomaly/` folder above
    `folder` (git ignores the excluded `.anomaly/`, so gitrepo.find_repo finds no repository inside it), else
    `folder`."""
    resolved = folder.resolve()
    inside = next((parent for parent in (resolved, *resolved.parents) if parent.name == UNITS_DIR.name), None)
    return folder if inside is None else inside.parent


def unit_folders(root):
    """The work-unit folders of `root/.anomaly`, in name order; `adhoc` holds light-path tickets, not one unit."""
    units = root / UNITS_DIR
    if not units.is_dir():
        return []
    return [path for path in sorted(units.iterdir()) if path.is_dir() and not frontier.is_adhoc(path)]


def newest_log_time(folder):
    """The newest time of the unit's log.md lines, or '' when it has none."""
    return max((time for time, _, _ in log.entries(folder)), default='')


def has_base(folder, branch):
    """True when a ticket of the unit has a `Base:` value equal to `branch`."""
    return any(ticket.value_of(ticket.split_lines(files.read_input(path)), 'Base') == branch
               for path in frontier.ticket_paths(folder / check.TICKETS_DIR))


def slug_branch(pattern, unit):
    """The branch the `branch` port pattern gives for the unit key; None unless `<slug>` is the only placeholder
    the pattern holds (a pattern with `<type>` or `<key>` is not expanded), however often it repeats."""
    return pattern.replace(SLUG, unit) if set(PLACEHOLDER.findall(pattern)) == {SLUG} else None


def is_unfinished(folder):
    """True when the unit has no ticket, or a ticket not done, or one that cannot be loaded or classified."""
    if not frontier.ticket_paths(folder / check.TICKETS_DIR):
        return True
    _, entries, warnings = classified(folder)
    return bool(entries or warnings)


def pick_unit(root, branch, home):
    """(folder, picked_by, warnings) of the unit `progress` reports with no `--unit`, or None when no unit is
    picked. `branch` is the current branch: '' outside a repository or on a detached head (then no branch match
    runs)."""
    folders = unit_folders(root)
    if branch:
        matches = [folder for folder in folders if has_base(folder, branch)]
        if not matches:
            pattern = ports.port(ports.resolve(home), BRANCH_PORT).value
            matches = [folder for folder in folders if slug_branch(pattern, folder.name) == branch]
        if matches:
            times = {folder: newest_log_time(folder) for folder in matches}
            picked = max(matches, key=times.get)   # a tie: the first in name order
            others = [folder.name for folder in matches if folder != picked]
            warnings = [f'{", ".join(others)} also match branch {branch}'] if others else []
            return picked, PICKED_BY_BRANCH, warnings
    times = {folder: time for folder in folders if (time := newest_log_time(folder))}
    newest_first = sorted(times, key=times.get, reverse=True)   # a tie: the first in name order (the sort is stable)
    picked = next((folder for folder in newest_first if is_unfinished(folder)), None)
    return None if picked is None else (picked, PICKED_BY_NEWEST_LOG, [])


def unit_null(warnings):
    """The object with no unit: only `schema`, `unit` (null) and `warnings`."""
    return {'schema': SCHEMA, 'unit': None, 'warnings': warnings}


def picked_report(root, branch, home):
    """The report of the unit pick_unit picks; with none picked, `unit` is null."""
    picked = pick_unit(root, branch, home)
    if picked is None:
        return unit_null([])
    folder, picked_by, warnings = picked
    report = build(folder, home, picked_by)
    report['warnings'].extend(warnings)
    return report


def named_report(root, unit, home):
    """The report of the unit that `--unit` names."""
    folder = root / UNITS_DIR / unit
    if not is_folder_name(unit):
        return unit_null([f'no work unit {unit}: not one folder name under {UNITS_DIR.as_posix()}/'])
    if folder.is_dir():
        return build(folder, home, PICKED_BY_OPTION)
    return unit_null([f'no work unit {unit}: {folder} is not a folder'])


def run_progress(args, environ):
    start = start_folder(Path(args.repo) if args.repo else Path.cwd())
    root = gitrepo.shared_root(start)
    home = paths.resolve_home(args.home, environ)
    if args.unit is None:
        repo = gitrepo.find_repo(start)
        report = picked_report(root, '' if repo is None else mr.current_branch(repo), home)
    else:
        report = named_report(root, args.unit, home)
    print(json.dumps(report))
    return 0

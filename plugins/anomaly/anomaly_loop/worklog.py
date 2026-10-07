"""worklog: one line per pipeline stage run, so the cost of one work unit can be read per stage.

  worklog start K S [--ticket NN]                    stamp the start of stage S on work unit K
  worklog add --feature K --stage S --session ID     write the line when the stage ends
              [--docs FOLDER] [--ticket NN] [--mode M]
  worklog report K                                   print what work unit K cost, from home (read-only)

`add` appends {feature, stage, session, date, ended} to `work-units.jsonl` in home. The feature is
the work-unit key (the feature folder name, or the ad-hoc ticket's file name without `.md` on the
light path); the date is today's, from the clock the CLI hands every handler. Feature, stage and
session are single tokens (privacy.check_identifier, ADR-0003), so no value can add a line or a
separator. Earlier lines are never rewritten, and a run that is repeated adds its line again: the
file records runs. When home is inside a git repository only that file is committed (ADR-0001),
through observe.commit_home, which prints the one `commit:` line.

The measurement fields only add to that line, and no key of an earlier line is renamed (ADR-0012):

  ended      the CLI clock when `add` ran, in constants.TICKET_TIME_FORMAT, on every new line. The model
             passes no time, here or in `start`.
  started    the time `worklog start` stamped for the same key, stage and ticket. A start record is one
             {feature, stage, [ticket,] started} line in `worklog-starts.jsonl` in the data folder
             (throwaway, ADR-0001, like the lens tally), never in home. The file is append-only, like
             the tally: `add` writes a {feature, stage, [ticket,] consumed} line before the work-unit
             line (so a failed home write loses the start and the retry warns, and the home file never
             gets a line twice), and a start counts only when no such line follows it, so one start
             measures one `add`. After an `add`, a later `add` with no new `start` warns instead of
             reusing that start. A start that was never followed by an `add` (an abandoned one) is still
             read by the next `add` for the same key, stage and ticket, however long ago it was; see
             ADR-0012. Two `start`s in a row keep the later one. With no start record (or no data
             folder) the line is still written, without `started`, and stdout says
             constants.NO_START_WARNING; the exit code stays 0.
  doc_bytes  with `--docs FOLDER`: the byte total of the `.md` files (by file-name suffix, so case does
             not matter on Windows) in that folder and every sub-folder, summed here in Python (no shell
             pipe). A symbolic link is skipped.
  ticket     with `--ticket NN` (two digits, records.is_ticket_number) on stage `build` or `review`
             (constants.WORKLOG_TICKET_STAGES). On `review` one line is one review round.
  mode       on stage `review` only, with `--mode M` (one of constants.REVIEW_MODES, the modes of the
             review skill).

Matching rule: a start and an `add` belong together when their feature, stage and ticket are equal; a
start with `--ticket` is read only by an `add` with the same `--ticket`, and a start without one only
by an `add` without one. So parallel tickets of one feature do not share a start. `start --ticket` takes
the same stages and the same number check as `add`. A refused `add` writes nothing and keeps the start.

`report` joins the lines of one work unit with the rows of `metrics.jsonl` by session id and writes nothing,
not even a commit. A merged ticket is a ticket number on a `build` line (`anomaly:build` writes it after the
merge; `ended` is on every line, so it does not mark a merge). A unit with no ticket number on any line
(an ad-hoc unit) counts a `build` line as its one merged ticket. A ticket's minutes are `ended` minus `started`
of its `build` lines, and a line without a start adds none. Each session counts once, however many tickets
or stages it holds; the per-merged-ticket numbers are the unit total divided by the merged tickets, and
there is no per-ticket token number, because one session holds many tickets.
"""
from datetime import datetime

from . import files, observe, paths, privacy, records
from .constants import (COMMIT_SCOPE, METRICS_FILE, NO_START_WARNING, REVIEW_MODES, TICKET_TIME_FORMAT,
                        WORKLOG_BUILD_STAGE, WORKLOG_REVIEW_STAGE, WORKLOG_START_FILE, WORKLOG_TICKET_STAGES)
from .files import RecordError

LABEL = 'worklog'
TICKET_STAGES = ', '.join(WORKLOG_TICKET_STAGES)
UNIT_FIELDS = ('feature', 'stage', 'ticket')   # what ties a start to its add


def register(commands, common):
    command = commands.add_parser('worklog', help='record the pipeline stages run on a piece of work')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    add = actions.add_parser('add', parents=[common], help='append one work-unit line to work-units.jsonl in home')
    add.add_argument('--feature', required=True,
                     help='the work-unit key: a feature folder name or an ad-hoc ticket file name without .md')
    add.add_argument('--stage', required=True, help='the pipeline stage, one word, such as build or review')
    add.add_argument('--session', required=True, help='the session id (one word)')
    add.add_argument('--docs', help='a folder: the line gains doc_bytes, the bytes of its .md files '
                                    '(matched by suffix: case-insensitive on Windows), sub-folders included, '
                                    'symbolic links skipped')
    add.add_argument('--ticket', help=f'stages {TICKET_STAGES}: the ticket number NN; reads the start made '
                                      'with the same --ticket')
    add.add_argument('--mode', help=f'stage {WORKLOG_REVIEW_STAGE} only: the review mode, one of '
                                    f'{", ".join(REVIEW_MODES)}')
    add.set_defaults(handler=run_add)
    start = actions.add_parser('start', parents=[common],
                               help='stamp the start time of a stage (CLI clock) for the next `add` of the same '
                                    'key, stage and ticket')
    start.add_argument('key', help='the work-unit key, as --feature of `add`')
    start.add_argument('stage', help='the pipeline stage, one word, as --stage of `add`')
    start.add_argument('--ticket', help=f'stages {TICKET_STAGES}: the ticket number NN; only an `add` with the '
                                        'same --ticket reads this start (parallel tickets of one feature)')
    start.set_defaults(handler=run_start)
    report = actions.add_parser('report', parents=[common],
                                help='print what one work unit cost, from work-units.jsonl and metrics.jsonl in home '
                                     '(writes nothing)')
    report.add_argument('unit', help='the work-unit key, as --feature of `add`')
    report.set_defaults(handler=run_report)


def now_text(args):
    return args.now.strftime(TICKET_TIME_FORMAT)


def doc_bytes(folder):
    """The bytes of every `.md` file under `folder`, sub-folders included; symbolic links are skipped."""
    root = paths.expand(folder)
    if not root.is_dir():
        raise RecordError(f'{LABEL}: --docs is not a folder: {folder}')
    return sum(path.stat().st_size for path in root.rglob('*.md') if path.is_file() and not path.is_symlink())


def check_ticket(stage, ticket):
    """--ticket of `start` and `add`: a stage that takes one, and a bare ticket number, refused with the same
    `worklog: --ticket` text in both (records.work_unit_record checks the number again as a backstop)."""
    if ticket is None:
        return
    if stage not in WORKLOG_TICKET_STAGES:
        raise RecordError(f'{LABEL}: --ticket is for stages {TICKET_STAGES} only, not {stage}')
    records.check_ticket_number(f'{LABEL}: --ticket', ticket)


def check_mode(stage, mode):
    if mode is not None and stage != WORKLOG_REVIEW_STAGE:
        raise RecordError(f'{LABEL}: --mode is for stage {WORKLOG_REVIEW_STAGE} only, not {stage}')


def unit_key(feature, stage, ticket):
    """The fields that tie a `start` to its `add`; `ticket` is absent from a row that has none."""
    key = {'feature': feature, 'stage': stage}
    if ticket is not None:
        key['ticket'] = ticket
    return key


def started_at(rows, key):
    """The start time of `key` that no consumed line follows, or None. A later start replaces an earlier one."""
    started = None
    for row in rows:
        if tuple(row.get(name) for name in UNIT_FIELDS) == tuple(key.get(name) for name in UNIT_FIELDS):
            if 'consumed' in row:
                started = None
            elif records.is_ticket_time(row.get('started')):
                started = row['started']
    return started


def run_start(args, environ):
    home = paths.resolve_home(args.home, environ)
    privacy.check_identifier(LABEL, 'key', args.key)
    privacy.check_identifier(LABEL, 'stage', args.stage)
    check_ticket(args.stage, args.ticket)
    data = paths.resolve_data(args.data, environ, home)
    started = now_text(args)
    files.append_line(data / WORKLOG_START_FILE, {**unit_key(args.key, args.stage, args.ticket), 'started': started})
    print(f'start: {args.key} {args.stage} {started}')
    return 0


def run_add(args, environ):
    home = paths.resolve_home(args.home, environ)
    for key in ('feature', 'stage', 'session'):
        privacy.check_identifier(LABEL, key, getattr(args, key))
    check_ticket(args.stage, args.ticket)
    check_mode(args.stage, args.mode)
    bytes_total = None if args.docs is None else doc_bytes(args.docs)
    data = paths.resolve_optional_data(args.data, environ, home)
    start_path = None if data is None else data / WORKLOG_START_FILE
    key = unit_key(args.feature, args.stage, args.ticket)
    started = None if start_path is None else started_at(files.load_lines(start_path), key)
    ended = now_text(args)
    record = records.work_unit_record(args.feature, args.stage, args.session, args.today.isoformat(),
                                      started=started, ended=ended, doc_bytes=bytes_total,
                                      ticket=args.ticket, mode=args.mode)
    if started is not None:
        # the marker first: if it fails nothing is written and the start stays; if the home write fails
        # after it the start is lost and a retry warns, but the durable file never gets a line twice
        files.append_line(start_path, {**key, 'consumed': ended})
    path = records.append_work_unit(home, record)
    print(f'work unit: {args.feature} {args.stage}')
    print(observe.commit_home(home, [path], f'chore({COMMIT_SCOPE}): log work unit {args.feature} {args.stage}'))
    if started is None:
        print(NO_START_WARNING)
    return 0


def minutes_of(row):
    """Whole minutes from `started` to `ended` of a work-unit line, or None when it lacks either time."""
    if not (records.is_ticket_time(row.get('started')) and records.is_ticket_time(row.get('ended'))):
        return None
    span = datetime.strptime(row['ended'], TICKET_TIME_FORMAT) - datetime.strptime(row['started'], TICKET_TIME_FORMAT)
    return round(span.total_seconds() / 60)


def stage_lines(rows, adhoc):
    """One line per work-unit line, grouped by ticket (lines without one first), in file order inside a group.
    A `review` line is one review round, numbered within its ticket. In an ad-hoc unit a `build` line is
    printed as `adhoc build`."""
    lines, rounds = [], {}
    for row in sorted(rows, key=lambda row: row.get('ticket') or ''):
        text = f"ticket {row['ticket']} " if row.get('ticket') else ''
        if adhoc and row.get('stage') == WORKLOG_BUILD_STAGE:
            text = 'adhoc '
        text += str(row.get('stage'))
        if row.get('stage') == WORKLOG_REVIEW_STAGE:
            rounds[row.get('ticket')] = rounds.get(row.get('ticket'), 0) + 1
            text += f" round {rounds[row.get('ticket')]}"
        minutes = minutes_of(row)
        if minutes is None:
            text += f": no start time, ended {row.get('ended') or 'unknown'}"
        else:
            text += f": {row['started']} to {row['ended']}, {minutes} minutes"
        if row.get('mode'):
            text += f", mode {row['mode']}"
        if 'doc_bytes' in row:
            text += f", doc bytes {row['doc_bytes']}"
        lines.append(text)
    return lines


def run_report(args, environ):
    home = paths.resolve_home(args.home, environ)
    everything = records.load_work_units(home)
    rows = [row for row in everything if row.get('feature') == args.unit]
    if not rows:
        units = sorted({row['feature'] for row in everything if isinstance(row.get('feature'), str)})
        raise RecordError(f"{LABEL}: no lines for work unit {args.unit}; the units that exist: "
                          f"{', '.join(units) or 'none'}")
    measured = {row.get('session_id'): row for row in files.load_lines(home / METRICS_FILE)}
    held = {}   # each session of the unit once, with the tickets its lines name
    for row in rows:
        tickets = held.setdefault(row.get('session'), set())
        if row.get('ticket') is not None:
            tickets.add(row['ticket'])
    builds = [row for row in rows if row.get('stage') == WORKLOG_BUILD_STAGE]
    adhoc = all(row.get('ticket') is None for row in rows)   # no numbered ticket on any line: an ad-hoc unit
    merged = 1 if adhoc and builds else len({row['ticket'] for row in builds if row.get('ticket') is not None})
    spans = [minutes_of(row) for row in builds]
    unmeasured = [session for session in held if session not in measured]
    weighted = sum(records.number(measured[session].get('weighted')) or 0 for session in held if session in measured)
    print(f'work unit: {args.unit}, merged tickets {merged}, sessions {len(held)}')
    for line in stage_lines(rows, adhoc):
        print(line)
    print(f'sessions with more than one ticket: {sum(len(tickets) > 1 for tickets in held.values())}')
    if None in spans:
        print(f'build lines without a start time: {spans.count(None)} (they add no minutes)')
    if unmeasured:
        print(f'sessions without a metrics row: {len(unmeasured)} (left out of the cost; run `measure`)')
    cost = f'cost: weighted tokens {weighted:,.0f}'
    if merged:
        cost += (f', weighted tokens per merged ticket {weighted / merged:,.0f}'
                 f', minutes per merged ticket {sum(span or 0 for span in spans) / merged:,.1f}')
    print(cost)
    return 0

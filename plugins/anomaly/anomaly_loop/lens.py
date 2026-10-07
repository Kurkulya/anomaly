"""lens tally: count what each reviewer's findings came to, run by run, and hand one batch per session
to `observe apply`.

  lens tally add --session S --lens L --accepted N --rejected N [--revised N]   store one reviewer's counts over its rounds
  lens tally sum --session S                                                    sum a session's runs into one batch

`observe` keeps one lens line per lens per session (observe.record_lenses), so a review that runs
several times in a session cannot hand it each run: the runs are stored apart and summed once.
`add` appends {session, lens, accepted, rejected} to `lens-tally.jsonl` in the data folder, never in
home (the tally is throwaway until it is summed); `revised` (accepted findings whose fix differed
from the one the reviewer proposed, never more than accepted) is added only when it is passed. `sum`
adds up the runs of one session per lens, in the order the lenses first appeared, and writes
{"lenses": [...]} (the lens entries observe.py reads: session, lens, accepted, rejected, and revised
when at least one run of that lens had it; a run without it counts 0 there) to
`lens-batch-<session>.json` in the data folder; it prints that path and nothing else, and the review
skill then runs `observe apply --file <path>`. A session with no runs is an error (a mistyped session
id must not look like an empty review). The tally is never rewritten, so summing again gives the
same batch, and a lens already put into home is skipped by observe.

Session and lens names are single tokens (privacy.check_identifier, ADR-0003). The session also names
the batch file, so it holds no ":" either (privacy.check_file_token), in `add` as in `sum`. A lens is
one of the review lenses (allowed_names): each core reviewer under its short name (`anomaly:code` is
`code`) and each org reviewer under its adapter name, read from the `reviewers` port (ports.resolve),
and `plan`, the plan-gate reviewer.
"""
from . import files, paths, ports, privacy, records
from .constants import LENS_BATCH_FILE, LENS_TALLY_FILE
from .files import RecordError

LABEL = 'lens tally'
REVIEWERS_PORT = 'reviewers'
PLAN_LENS = 'plan'   # the plan-gate reviewer (`anomaly:plan`) is no port reviewer, so its lens is always allowed


def is_run(row):
    """True for a tally line that holds a lens name, two counts of 0 or more, and no revised count or a
    count of 0 or more."""
    return isinstance(row.get('lens'), str) and records.is_count(row.get('accepted')) \
        and records.is_count(row.get('rejected')) and ('revised' not in row or records.is_count(row['revised']))


def sum_runs(rows, session):
    """One {session, lens, accepted, rejected[, revised]} per lens: the counts of every run of `session`
    added up, in the order the lenses first appear; `revised` is there when a run of that lens had it.
    Lines of other sessions, and lines that are no run, are skipped."""
    totals = {}
    for row in rows:
        if row.get('session') == session and is_run(row):
            total = totals.setdefault(row['lens'], {'session': session, 'lens': row['lens'], 'accepted': 0,
                                                    'rejected': 0})
            total['accepted'] += row['accepted']
            total['rejected'] += row['rejected']
            if 'revised' in row:
                total['revised'] = total.get('revised', 0) + row['revised']
    return list(totals.values())


def lens_name(reviewer):
    """The lens of one reviewer of the `reviewers` port: a core reviewer under its short name
    (`anomaly:code` is `code`), an org reviewer under its adapter name."""
    return reviewer.split(':', 1)[1] if reviewer in ports.core_default(REVIEWERS_PORT) else reviewer


def core_lenses():
    """The lenses of the core reviewers, with no profile read."""
    return tuple(lens_name(reviewer) for reviewer in ports.core_default(REVIEWERS_PORT))


def allowed_names(home):
    """The lens names the `reviewers` port gives for the profile in `home`."""
    reviewers = ports.port(ports.resolve(home), REVIEWERS_PORT).values
    return tuple(dict.fromkeys((*(lens_name(reviewer) for reviewer in reviewers), PLAN_LENS)))


def check_names(session, lens=None):
    privacy.check_file_token(LABEL, 'session', session)
    if lens is not None:
        privacy.check_identifier(LABEL, 'lens', lens)


def check_lens(home, lens):
    """Refuse a lens that is not one of allowed_names(home), naming the allowed ones."""
    allowed = allowed_names(home)
    if lens not in allowed:
        raise RecordError(f'{LABEL}: lens {lens} is not a review lens; use one of: {", ".join(allowed)}')


def data_folder(args, environ):
    return paths.resolve_data(args.data, environ, paths.resolve_home(args.home, environ))


def register(commands, common):
    command = commands.add_parser('lens', help='count review findings per lens (see `lens tally`)')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    tally = actions.add_parser('tally', help='store the counts of each review run, then sum a session')
    steps = tally.add_subparsers(dest='step', required=True, metavar='step')
    add = steps.add_parser('add', parents=[common], help="store one reviewer's accepted and rejected counts over its rounds")
    add.add_argument('--session', required=True, help='the session id (one word)')
    add.add_argument('--lens', required=True,
                     help=f"the lens name: {', '.join(core_lenses())} or an org reviewer's adapter name")
    add.add_argument('--accepted', required=True, type=records.count_option,
                     help='findings accepted (fixed or kept as open)')
    add.add_argument('--rejected', required=True, type=records.count_option, help='findings rejected (judged wrong)')
    add.add_argument('--revised', type=records.count_option,
                     help='accepted findings whose fix differed from the proposed one (at most --accepted)')
    add.set_defaults(handler=run_add)
    total = steps.add_parser('sum', parents=[common],
                             help="sum a session's runs into one batch file for `observe apply`; prints its path")
    total.add_argument('--session', required=True, help='the session id (one word)')
    total.set_defaults(handler=run_sum)


def run_add(args, environ):
    check_names(args.session, args.lens)
    check_lens(paths.resolve_home(args.home, environ), args.lens)
    line = {'session': args.session, 'lens': args.lens, 'accepted': args.accepted, 'rejected': args.rejected}
    said = f'tally: {args.lens} accepted {args.accepted}, rejected {args.rejected}'
    if args.revised is not None:
        records.check_revised(LABEL, args.accepted, args.revised)
        line['revised'] = args.revised
        said += f', revised {args.revised}'
    data = data_folder(args, environ)
    files.append_line(data / LENS_TALLY_FILE, line)
    print(said)
    return 0


def run_sum(args, environ):
    check_names(args.session)
    data = data_folder(args, environ)
    lenses = sum_runs(files.load_lines(data / LENS_TALLY_FILE), args.session)
    if not lenses:
        raise RecordError(f'no lens runs for session {args.session} in {data / LENS_TALLY_FILE}: '
                          'run lens tally add after each review run')
    path = data / LENS_BATCH_FILE.format(session=args.session)
    files.write_text(path, files.dump({'lenses': lenses}) + '\n')
    print(path)
    return 0

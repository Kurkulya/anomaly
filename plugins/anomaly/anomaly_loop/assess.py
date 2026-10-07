"""assess: the deterministic half of judging a new link, text or opinion.

The skill reads and judges; this module does what must not vary:

  check   what an input's key is, whether it was assessed before (its earlier idea is shown
          instead of a new read), and else the open anomalies it could relate to
  record  writes `ideas/<slug>.md`; for the verdict `adopt` it also drafts an experiment on a
          new anomaly, or on an open anomaly that has none, and changes nothing else (the
          exception is `--already-applied`: lessons already built into the plugin need no draft)

Source keys. A link is stored as `https://host[:port]/path`: the scheme, `www.`, user name and
trailing slashes are dropped, and so is a plain `#anchor`. A query can hold tokens, so it is
never stored; it still tells pages apart, as a short digest of the query without tracking
parameters (`#q=<digest>`), and a routing fragment (`#/...`, `#!...`) the same way (`f=`).
So `watch?v=a` and `watch?v=b` are two keys, and a tracking parameter changes nothing.
A text or opinion is stored as
`text:` plus a digest of its words in lower case, so spacing, case and punctuation do not
matter. Both forms are stable: a stored key maps to itself.

The digest section lists parked ideas that are due to be looked at again: the revisit date has
come (on that day or later), or a related problem that is still open or reopened is now at the
nudge score or above while it was below it when the idea was assessed.
"""
import hashlib
import re
import unicodedata
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit

from . import ideas, observe, paths, privacy, profile, records, verdict
from .constants import (ASSESS_DEFAULT_IMPACT, ASSESS_DEFAULT_SCOPE, COMMIT_SCOPE, GUARD_HELP, LINK_DIGEST_LENGTH,
                        LINK_TRACKING_PARAMS, LINK_TRACKING_PREFIXES, NUDGE_MIN_SCORE, PARAGRAPH_MAX_CHARS,
                        SIGHTING_MAX_CHARS, TEXT_KEY_LENGTH, TEXT_KEY_PREFIX, UNKNOWN_REPO)
from .files import read_input
from .records import RecordError, is_date, is_whole

LINK = re.compile(r'https?://\S+|[^\s/@?#]+\.[a-z]{2,}(?:[/?#]\S*)?', re.IGNORECASE)
STORED_LINK_MARKS = re.compile(rf'q=[0-9a-f]{{{LINK_DIGEST_LENGTH}}}(?:&f=[0-9a-f]{{{LINK_DIGEST_LENGTH}}})?'
                               rf'|f=[0-9a-f]{{{LINK_DIGEST_LENGTH}}}')
STORED_TEXT_KEY = re.compile(re.escape(TEXT_KEY_PREFIX) + rf'[0-9a-f]{{{TEXT_KEY_LENGTH}}}')
DEFAULT_PORTS = (None, 80, 443)
DESCRIBING_OPTIONS = ('category', 'target', 'scope', 'impact', 'summary', 'fix')
EXPERIMENT_OPTIONS = ('expect', 'metric', 'guard')
ADOPTED_SIGHTING = 'raised by an idea that was assessed and adopted'
# The first sighting of an anomaly that an adopted idea creates: no repository (UNKNOWN_REPO) and the
# idea's slug in the session place, so the line has the shape every sighting has (records.sighting_line)
# and is a stable, unique id that no real session shares.
TEXT_OPTIONS = (('summary', PARAGRAPH_MAX_CHARS), ('fix', PARAGRAPH_MAX_CHARS), ('expect', SIGHTING_MAX_CHARS),
                ('metric', SIGHTING_MAX_CHARS), ('guard', SIGHTING_MAX_CHARS), ('target', SIGHTING_MAX_CHARS),
                ('scope', SIGHTING_MAX_CHARS))
ADOPT_OPTIONS = ('signature', *DESCRIBING_OPTIONS, *EXPERIMENT_OPTIONS, 'check_by')


# ---------- source keys ----------

def normalize_url(raw):
    parts = urlsplit(raw if '://' in raw else f'https://{raw}')
    try:
        host, port = parts.hostname, parts.port
    except ValueError:
        raise RecordError(f'{raw!r} is not a usable link') from None
    if not host:
        raise RecordError(f'{raw!r} is not a usable link')
    path = re.sub(r'/{2,}', '/', parts.path).rstrip('/')
    marks = page_marks(parts)
    return (f'https://{host.removeprefix("www.")}{"" if port in DEFAULT_PORTS else f":{port}"}{path}'
            + (f'#{marks}' if marks else ''))


def is_tracking(name):
    name = name.lower()
    return name in LINK_TRACKING_PARAMS or name.startswith(LINK_TRACKING_PREFIXES)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:LINK_DIGEST_LENGTH]


def page_marks(parts):
    """What besides host and path tells two pages apart, as digests only (the stored key never holds
    a query or a fragment): the query without tracking parameters, in sorted order, as `q=`; a
    routing fragment (`#/...` or `#!...`) as `f=`. A plain anchor is dropped. A fragment that is
    already such a mark, on a link without a query, is a stored key and is kept."""
    if not parts.query and STORED_LINK_MARKS.fullmatch(parts.fragment):
        return parts.fragment
    marks = []
    query = sorted(pair for pair in parse_qsl(parts.query, keep_blank_values=True) if not is_tracking(pair[0]))
    if query:
        marks.append('q=' + digest(urlencode(query)))
    if parts.fragment[:1] in ('/', '!') and parts.fragment:
        marks.append('f=' + digest(parts.fragment))
    return '&'.join(marks)


def text_key(raw):
    words = re.findall(r'\w+', unicodedata.normalize('NFKC', raw).casefold())
    if not words:
        raise RecordError('the input has no words to assess')
    return TEXT_KEY_PREFIX + hashlib.sha256(' '.join(words).encode('utf-8')).hexdigest()[:TEXT_KEY_LENGTH]


def source_key(raw):
    """The stored form of an input: a normalized link, or `text:<digest>` (see the module text)."""
    raw = (raw or '').strip()
    if STORED_TEXT_KEY.fullmatch(raw):
        return raw
    return normalize_url(raw) if LINK.fullmatch(raw) else text_key(raw)


def find_earlier(assessed, key):
    """The idea whose source has this key, or None."""
    for idea in assessed:
        try:
            if source_key(idea.source) == key:
                return idea
        except RecordError:
            continue
    return None


# ---------- reading input ----------

def option_text(value, file):
    """An option's text: the file's when a file is given, standard input for `-`, else the value
    (files.read_input reads the first two)."""
    if file is not None:
        return read_input(file)
    return read_input('-') if value == '-' else value


# ---------- check ----------

def show_idea(idea, home):
    out = ['assess: seen before', f'idea: {idea.slug}', f'file: {ideas.idea_path(home, idea.slug)}',
           f'source: {idea.source}', f'verdict: {idea.verdict}', f'assessed: {idea.assessed}']
    if idea.revisit:
        out.append(f'revisit: {idea.revisit}')
    if idea.related:
        out.append('related: ' + ', '.join(idea.related))
    return out + ([''] + idea.body.splitlines() if idea.body else [])


def show_candidates(anomalies):
    """One line per open or reopened anomaly, highest score first: what the input can relate to."""
    lines = []
    for anomaly in records.ranked(anomalies):
        extra = [anomaly.kind, anomaly.category] + ([anomaly.target] if anomaly.target else [])
        lines.append(f'- {anomaly.score}  {anomaly.signature} · ' + ' · '.join(extra))
    return lines


def run_check(args, environ):
    home = paths.resolve_home(args.home, environ)
    key = source_key(option_text(args.source, args.source_file))
    earlier = find_earlier(ideas.load_ideas(home), key)
    if earlier:
        lines = show_idea(earlier, home)
    else:
        lines = ['assess: new', f'key: {key}', 'open anomalies, highest score first:']
        lines += show_candidates(records.load_anomalies(home)) or ['- none']
    message = profile.missing_message(profile.load_profile(home))
    print('\n'.join(([message] if message else []) + lines))
    return 0


# ---------- record ----------

def adopted(args, anomalies, today):
    """The anomaly an adopted idea writes. Needs a signature and a complete
    experiment draft; a new anomaly is described by the options, an existing open one without an
    experiment only gets the draft."""
    missing = [name for name in ('signature', *EXPERIMENT_OPTIONS) if not (getattr(args, name) or '').strip()]
    if missing:
        raise RecordError('verdict adopt needs a drafted experiment: missing ' + ', '.join(f'--{n}' for n in missing))
    metric, guard = verdict.experiment_metrics('the drafted experiment', args.metric, args.guard)
    experiment = records.Experiment(expect=args.expect.strip(), metric=metric, guard=guard,
                                    check_by=args.check_by or '')
    existing = next((a for a in anomalies if a.signature == args.signature), None)
    given = [name for name in DESCRIBING_OPTIONS if getattr(args, name) is not None]
    if existing:
        if given:
            raise RecordError(f'anomaly {args.signature} already exists: the options '
                              + ', '.join(f'--{n}' for n in given) + ' describe a new anomaly')
        if not existing.active:
            raise RecordError(f'anomaly {args.signature} is {existing.status}: it takes no new experiment')
        if existing.experiment is not None:
            raise RecordError(f'anomaly {args.signature} already has an experiment')
        existing.experiment = experiment
        return existing
    missing = [name for name in ('category', 'summary', 'fix') if not (getattr(args, name) or '').strip()]
    if missing:
        raise RecordError('a new anomaly needs ' + ', '.join(f'--{n}' for n in missing))
    today_text = today.isoformat()
    return records.Anomaly(
        signature=args.signature, kind='problem', category=args.category, target=args.target or '',
        scope=args.scope or ASSESS_DEFAULT_SCOPE, impact=ASSESS_DEFAULT_IMPACT if args.impact is None else args.impact, occurrences=1,
        status='open', first_seen=today_text, last_seen=today_text, summary=args.summary.strip(),
        proposed_fix=args.fix.strip(), experiment=experiment,
        sightings=[records.sighting_line(today_text, UNKNOWN_REPO, args.slug, ADOPTED_SIGHTING)])


def check_privacy(args, key, body):
    """Refuse text that must not be stored (ADR-0003) before anything is written; the rules are privacy's.
    The body is checked line by line, a quoted line like any other."""
    label = f'idea {args.slug}'
    privacy.check_identifier(label, 'slug', args.slug)
    privacy.check_text(label, 'source', key, PARAGRAPH_MAX_CHARS)
    for entry in args.related or []:
        privacy.check_text(label, 'related', entry, SIGHTING_MAX_CHARS)
    for number, line in enumerate((line for line in body.splitlines() if line.strip()), start=1):
        privacy.check_text(label, f'body line {number}', line.strip(), PARAGRAPH_MAX_CHARS)
    if args.signature is not None:
        privacy.check_identifier(label, 'signature', args.signature)
    for name, limit in TEXT_OPTIONS:
        value = getattr(args, name)
        if value is not None:
            privacy.check_text(label, name, value, limit)


def run_record(args, environ):
    home = paths.resolve_home(args.home, environ)
    today = args.today
    body = (option_text(args.body, args.body_file) or '').strip()
    if not body:
        raise RecordError('the idea needs a body in your own words')
    given = [f'--{name}' for name in ADOPT_OPTIONS if getattr(args, name) is not None]
    if args.verdict != 'adopt' and (given or args.already_applied):
        raise RecordError('the options ' + ', '.join(given + ['--already-applied'] * args.already_applied)
                          + ' belong to the verdict adopt')
    if args.already_applied and given:
        raise RecordError('--already-applied means nothing is left to draft: leave out ' + ', '.join(given))
    key = source_key(option_text(args.source, args.source_file))
    check_privacy(args, key, body)
    assessed = ideas.load_ideas(home)
    earlier = find_earlier(assessed, key)
    if earlier and earlier.slug != args.slug:
        raise RecordError(f'this input has the same key as the idea {earlier.slug}: look at it with '
                          '`assess check`, nothing was written')
    if ideas.idea_path(home, args.slug).exists() and not args.replace:
        raise RecordError(f'idea {args.slug} exists: pass --replace to write it again')
    anomalies = records.load_anomalies(home)
    related = list(args.related or [])
    written = None
    if args.verdict == 'adopt' and not args.already_applied:
        written = adopted(args, anomalies, today)
        anomalies = [a for a in anomalies if a.signature != written.signature] + [written]
        related += [] if written.signature in related else [written.signature]
    scores = {a.signature: a.score for a in anomalies if a.signature in related}
    idea = ideas.Idea(slug=args.slug, source=key, assessed=today.isoformat(), verdict=args.verdict,
                      revisit=args.revisit or '', related=related, scores_at_assessment=scores, body=body)
    problems = ideas.validate_idea(idea)
    if problems:
        raise RecordError(f'idea {idea.slug}: ' + '; '.join(problems))
    paths_written = []
    if written is not None:
        paths_written = observe.write_anomalies(home, today, {a.signature: a for a in anomalies}, [written.signature])
        print(f'anomaly file: {paths_written[0]}')
    paths_written.append(ideas.write_idea(home, idea))
    print(f'idea: {paths_written[-1]}')
    print(observe.commit_home(home, paths_written, f'chore({COMMIT_SCOPE}): assess {idea.slug} ({idea.verdict})'))
    return 0


# ---------- the digest section ----------

def digest_section(context):
    open_anomalies = {a.signature: a for a in context.anomalies if a.active}
    rows = []
    for idea in context.ideas:
        if idea.verdict != 'park':
            continue
        reasons = []
        if is_date(idea.revisit) and date.fromisoformat(idea.revisit) <= context.today:
            reasons.append(f'revisit date {idea.revisit} reached')
        for signature, then in idea.scores_at_assessment.items():
            anomaly = open_anomalies.get(signature)
            if anomaly and anomaly.kind == 'problem' and is_whole(then) and then < NUDGE_MIN_SCORE <= anomaly.score:
                reasons.append(f'{signature} is now score {anomaly.score} (was {then} when assessed)')
        if reasons:
            rows.append((idea.revisit, idea.slug, reasons))
    if not rows:
        return []
    return ['## Parked ideas'] + [f'- {slug}: ' + '; '.join(reasons) for _, slug, reasons in sorted(rows)]


# ---------- the assess subcommand ----------

def one_of(parser, name, help_text):
    """Add --<name> (text) and --<name>-file (a UTF-8 file with the text): exactly one is required."""
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(f'--{name}', help=help_text)
    group.add_argument(f'--{name}-file', dest=f'{name}_file', help=f'a UTF-8 file that holds the {name} text')


def register(commands, common):
    command = commands.add_parser('assess', help='check an input against earlier ideas, or record an idea')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    check = actions.add_parser('check', parents=[common],
                               help='show the earlier idea for an input, else its key and the open anomalies')
    one_of(check, 'source', 'a link or a text; - reads standard input')
    check.set_defaults(handler=run_check)
    record = actions.add_parser('record', parents=[common], help='write ideas/<slug>.md')
    record.add_argument('--slug', required=True, help='lowercase words joined by hyphens')
    one_of(record, 'source', 'a link, a text, or the key that check printed; - reads standard input')
    record.add_argument('--verdict', required=True, help='adopt, trial, park or reject')
    record.add_argument('--revisit', help='date to look at a parked idea again (park only)')
    record.add_argument('--related', action='append', help='an anomaly signature or a target (repeatable)')
    one_of(record, 'body', 'the assessment in your own words; - reads standard input')
    record.add_argument('--replace', action='store_true', help='write over an idea with the same slug')
    record.add_argument('--already-applied', action='store_true', dest='already_applied',
                        help='verdict adopt for lessons that are already built into the plugin: '
                             'writes the idea and drafts no experiment')
    adopt = record.add_argument_group('adopt', 'a drafted experiment: on a new anomaly (describe it with '
                                               'category, summary and fix), or on an open one that has none')
    adopt.add_argument('--signature', help='the new anomaly, or an existing open one')
    adopt.add_argument('--category')
    adopt.add_argument('--target')
    adopt.add_argument('--scope', help=f'default {ASSESS_DEFAULT_SCOPE}')
    adopt.add_argument('--impact', type=int, help=f'1 to 3; default {ASSESS_DEFAULT_IMPACT}')
    adopt.add_argument('--summary', help='what is wrong today, one paragraph')
    adopt.add_argument('--fix', help='the proposed fix')
    adopt.add_argument('--expect', help='the expected effect')
    adopt.add_argument('--metric', help='exactly one primary metric, a name from `calibrate plan`')
    adopt.add_argument('--guard',
                       help=GUARD_HELP)
    adopt.add_argument('--check-by', dest='check_by', help='date; leave blank: it is set when the fix is made')
    record.set_defaults(handler=run_record)

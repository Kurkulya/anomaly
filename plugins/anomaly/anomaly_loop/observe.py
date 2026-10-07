"""The deterministic half of `observe`: record sightings, lens stats and a session-kind override.

The skill decides what happened and which existing anomaly (by root cause) a sighting belongs
to; this module makes the write safe. Two subcommands:

  observe list    one line per anomaly, so the skill can match by root cause (also prints the
                  missing-profile line, once)
  observe apply   one batch from a JSON file (or `-` for standard input), recorded in one step

A batch is {"sightings": [...], "lenses": [...], "kind": {...}}; every key is optional.
  sighting  signature, text, session, repo (optional); for a new anomaly also kind, category,
            scope, impact, summary, fix (a problem needs one) and optionally target. For an
            existing signature only `impact` can matter (it may raise the anomaly's impact); its
            other text stays as written.
  lens      session, lens, accepted, rejected; optionally revised (no more than accepted)
  kind      session, kind

The whole batch is checked before anything is written. Then: occurrences + 1, `last_seen` and a
new first line in `## Sightings` for a match (a `fixed` anomaly becomes `reopened`, a `wontfix`
one keeps its status), a new file otherwise; lens lines and the kind override are appended; the
index is regenerated (the reply then lists the top anomalies by score); and when home is inside a
git repository only the paths written, plus the index, are committed.

A session counts once per anomaly and once per lens: a second sighting or lens line from the same
session is skipped, so repeating a run does not inflate the counts.

Free text (sighting, summary, fix, target, scope) is the writer's own process wording: one short
line that privacy.privacy_problems finds nothing in. Repository, session and lens names are
single tokens (privacy.is_identifier), so no value can add a line or a separator to a sighting.
Anything refused is reworded by the writer, never silently altered.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import gitrepo, index, paths, privacy, profile, records
from .constants import (COMMIT_SCOPE, DIGEST_TOP, IMPACT_RANGE, INDEX_FILE, LENSES_FILE,
                        PARAGRAPH_MAX_CHARS, SESSION_KINDS_FILE, SIGHTING_MAX_CHARS, SUMMARY_CHARS,
                        UNKNOWN_REPO)
from .files import RecordError, read_input

SIGHTING_KEYS = ('signature', 'text', 'session', 'repo', 'kind', 'category', 'target', 'scope', 'impact',
                 'summary', 'fix')
LENS_KEYS = ('session', 'lens', 'accepted', 'rejected', 'revised')   # revised is optional
KIND_KEYS = ('session', 'kind')
BATCH_KEYS = ('sightings', 'lenses', 'kind')


# ---------- reading a batch ----------

@dataclass
class Sighting:
    signature: str
    text: str
    session: str
    repo: str = UNKNOWN_REPO
    kind: str = ''
    category: str = ''
    target: str = ''
    scope: str = ''
    impact: int | None = None
    summary: str = ''
    fix: str = ''


@dataclass
class Batch:
    sightings: list = field(default_factory=list)
    lenses: list = field(default_factory=list)
    kind: dict | None = None

    @property
    def empty(self):
        return not (self.sightings or self.lenses or self.kind)


def expect_object(value, label, keys):
    if not isinstance(value, dict):
        raise RecordError(f'{label} must be an object')
    unknown = sorted(set(value) - set(keys))
    if unknown:
        raise RecordError(f'{label} has unknown keys: {", ".join(unknown)} (known: {", ".join(keys)})')
    return value


def expect_text(item, key, label):
    value = item.get(key, '')
    if not isinstance(value, str):
        raise RecordError(f'{label}: {key} must be text')
    return value.strip()


def parse_sighting(item, number):
    label = f'sighting {number}'
    item = expect_object(item, label, SIGHTING_KEYS)
    text = {key: expect_text(item, key, label) for key in SIGHTING_KEYS if key != 'impact'}
    label = f'sighting {number} ({text["signature"] or "no signature"})'
    if not records.is_slug(text['signature']):
        raise RecordError(f'{label}: signature must be lowercase words joined by hyphens')
    for key in ('text', 'session'):
        if not text[key]:
            raise RecordError(f'{label}: {key} is required')
    for key, limit in (('text', SIGHTING_MAX_CHARS), ('summary', PARAGRAPH_MAX_CHARS),
                       ('fix', PARAGRAPH_MAX_CHARS), ('target', SIGHTING_MAX_CHARS),
                       ('scope', SIGHTING_MAX_CHARS)):
        privacy.check_text(label, key, text[key], limit)
    text['repo'] = text['repo'] or UNKNOWN_REPO
    for key in ('repo', 'session'):
        privacy.check_identifier(label, key, text[key])
    impact = item.get('impact')
    low, high = IMPACT_RANGE
    if impact is not None and not (records.is_whole(impact) and low <= impact <= high):
        raise RecordError(f'{label}: impact must be a whole number from {low} to {high}')
    return Sighting(impact=impact, **text)


def parse_lens(item, number, today):
    label = f'lens {number}'
    item = expect_object(item, label, LENS_KEYS)
    for key in ('session', 'lens'):
        privacy.check_identifier(label, key, item.get(key))
    return records.lens_record(item.get('session'), today, item.get('lens'), item.get('accepted'),
                               item.get('rejected'), item.get('revised'), label)


def parse_kind(item, today):
    item = expect_object(item, 'kind', KIND_KEYS)
    privacy.check_identifier('kind', 'session', item.get('session'))
    return records.session_kind_record(item.get('session'), item.get('kind'), today)


def parse_batch(data, today):
    """A Batch from the decoded JSON; the lens and kind entries are ready-to-append records."""
    data = expect_object(data, 'the batch', BATCH_KEYS)
    for key in ('sightings', 'lenses'):
        if not isinstance(data.get(key, []), list):
            raise RecordError(f'{key} must be a list')
    return Batch(
        sightings=[parse_sighting(item, n) for n, item in enumerate(data.get('sightings', []), 1)],
        lenses=[parse_lens(item, n, today.isoformat()) for n, item in enumerate(data.get('lenses', []), 1)],
        kind=parse_kind(data['kind'], today.isoformat()) if 'kind' in data else None)


def read_batch(source):
    text = read_input(source)
    try:
        return json.loads(text)
    except ValueError as error:
        raise RecordError(f'the batch is not valid JSON: {error}') from None


# ---------- recording ----------

def create_anomaly(sighting, today):
    problems = [f'{key} is required for a new anomaly' for key in ('kind', 'category', 'scope', 'summary')
                if not getattr(sighting, key)]
    if sighting.impact is None:
        problems.append('impact is required for a new anomaly')
    if sighting.kind == 'problem' and not sighting.fix:
        problems.append('fix is required for a new problem')
    if problems:
        raise RecordError(f'sighting for new anomaly {sighting.signature}: ' + '; '.join(problems))
    return records.Anomaly(
        signature=sighting.signature, kind=sighting.kind, category=sighting.category, target=sighting.target,
        scope=sighting.scope, impact=sighting.impact, occurrences=1, status='open', first_seen=today,
        last_seen=today, summary=sighting.summary, proposed_fix=sighting.fix, sightings=[])


def record_sightings(anomalies, sightings, today):
    """Apply the sightings to `anomalies` (signature -> Anomaly, changed in place; new ones added).

    Returns (lines to print, signatures written in order, number of sightings counted)."""
    lines, changed, counted = [], [], 0
    for sighting in sightings:
        anomaly = anomalies.get(sighting.signature)
        is_new = anomaly is None
        if is_new:
            anomaly = create_anomaly(sighting, today)
        elif any(records.sighting_session(line) == sighting.session for line in anomaly.sightings):
            lines.append(f'skipped: {anomaly.signature} already has a sighting from this session')
            continue
        else:
            anomaly.occurrences += 1
            anomaly.last_seen = today
            if sighting.impact is not None and sighting.impact > anomaly.impact:
                anomaly.impact = sighting.impact
        anomaly.sightings.insert(0, records.sighting_line(today, sighting.repo, sighting.session, sighting.text))
        anomalies[anomaly.signature] = anomaly
        if anomaly.signature not in changed:
            changed.append(anomaly.signature)
        counted += 1
        if is_new:
            lines.append(f'logged: {anomaly.signature} (new)')
            continue
        lines.append(f'logged: {anomaly.signature} (seen {anomaly.occurrences} times, score {anomaly.score})')
        if anomaly.status == 'fixed':
            anomaly.status = 'reopened'
            by = f' by {anomaly.fixed_by}' if anomaly.fixed_by else ''
            lines.append(f'reopened: {anomaly.signature} was fixed{by}; the fix did not hold')
        elif anomaly.status == 'wontfix':
            lines.append(f'wontfix: {anomaly.signature} keeps status wontfix; the sighting was added')
    return lines, changed, counted


def record_lenses(home, lens_records):
    """Lens lines to append and the lines to print; a session's lens is counted once."""
    known = {(row.get('session_id'), row.get('lens')) for row in records.load_lenses(home)}
    to_write, lines = [], []
    for record in lens_records:
        name, key = record['lens'], (record['session_id'], record['lens'])
        if not record['accepted'] and not record['rejected']:
            lines.append(f'skipped: lens {name} has no accepted or rejected findings')
        elif key in known:
            lines.append(f'skipped: lens {name} already logged for this session')
        else:
            known.add(key)
            to_write.append(record)
            revised = f', revised {record["revised"]}' if 'revised' in record else ''
            lines.append(f'lens: {name} logged (accepted {record["accepted"]}, rejected {record["rejected"]}{revised})')
    return to_write, lines


def record_kind(home, kind_record):
    """(record to append or None, line to print) for a session-kind override."""
    session, kind = kind_record['session_id'], kind_record['kind']
    current = records.load_session_kinds(home).get(session)
    if current and current['kind'] == kind:
        return None, f'kind: {session} is already {kind}'
    return kind_record, f'kind: {session} is now {kind}'


def commit_message(counted, signatures, lens_written, kind_written):
    parts = []
    if counted:
        parts.append(signatures[0] if counted == 1 else f'{counted} sightings')
    if lens_written:
        parts.append('lens stats')
    if kind_written:
        parts.append('session kind')
    return f'chore({COMMIT_SCOPE}): ' + (f'log {", ".join(parts)}' if parts else 'refresh the index')


def commit_home(home, written, message):
    """One line saying what happened to the commit of the paths written (ADR-0001)."""
    repo = gitrepo.find_repo(home)
    if repo is None:
        return 'commit: none, home is not in a git repository'
    try:
        commit = gitrepo.commit_paths(repo, written, message)
    except gitrepo.GitError as error:
        return f'commit: failed ({error}); the files are written'
    return f'commit: {commit[:7]}' if commit else 'commit: none, nothing changed'


def write_anomalies(home, today, anomalies, changed):
    """Write the `changed` anomalies (signatures, from `anomalies`: signature -> Anomaly, every record
    of home) and regenerate the index; returns the paths written, the index last. Every changed
    record is validated before anything is written. The one writer of anomaly files and the index
    for a command; commit the paths with commit_home after writing any other file of the run."""
    changed = list(dict.fromkeys(changed))
    for signature in changed:
        problems = records.validate_anomaly(anomalies[signature])
        if problems:
            raise RecordError(f'anomaly {signature}: ' + '; '.join(problems))
    written = [records.write_anomaly(home, anomalies[signature]) for signature in changed]
    index.write_index(home, today, list(anomalies.values()))
    return written + [Path(home) / INDEX_FILE]


def save_anomalies(home, today, anomalies, changed, message):
    """write_anomalies, then commit only those paths with `message`; returns the `commit:` line."""
    return commit_home(home, write_anomalies(home, today, anomalies, changed), message)


def apply_batch(home, batch, today):
    """Record the whole batch, regenerate the index, commit the paths written; returns the lines to print."""
    if batch.empty:
        return ['nothing to record']
    anomalies = {a.signature: a for a in records.load_anomalies(home, strict=True)}
    lines, changed, counted = record_sightings(anomalies, batch.sightings, today.isoformat())
    lens_records, lens_lines = record_lenses(home, batch.lenses)
    kind_record, kind_line = record_kind(home, batch.kind) if batch.kind else (None, None)

    written = write_anomalies(home, today, anomalies, changed)
    for record in lens_records:
        records.append_lens(home, record)
    if kind_record:
        records.append_session_kind(home, kind_record)
    written += [Path(home) / name for name, wrote in ((LENSES_FILE, lens_records),
                                                       (SESSION_KINDS_FILE, kind_record)) if wrote]

    ranked = records.ranked(anomalies.values())
    lines += lens_lines + ([kind_line] if kind_line else [])
    lines.append(index.backlog_line(anomalies.values()))
    lines += [f'top: {a.score} {a.signature}' for a in ranked[:DIGEST_TOP]]
    lines.append(commit_home(home, written, commit_message(counted, changed, lens_records, kind_record)))
    return lines


# ---------- the subcommands ----------

def summary_line(anomaly):
    first = anomaly.summary.splitlines()[0] if anomaly.summary else ''
    return first if len(first) <= SUMMARY_CHARS else first[:SUMMARY_CHARS].rstrip() + '...'


def list_lines(anomalies):
    active, done = records.ranked(anomalies), records.closed(anomalies)
    if not anomalies:
        return ['anomalies: none yet']
    lines = [f'anomalies: {len(anomalies)} ({len(active)} open, {len(done)} closed)']
    for a in active + done:
        lines.append(' | '.join((a.signature, a.kind, a.category, a.target or '-', a.scope, a.status,
                                 f'impact {a.impact}', f'seen {a.occurrences}', summary_line(a))))
    return lines


def register(commands, common):
    observe = commands.add_parser('observe', help='record sightings, lens stats and session kinds')
    actions = observe.add_subparsers(dest='action', required=True, metavar='action')
    listing = actions.add_parser('list', parents=[common],
                                 help='one line per anomaly, for matching a sighting by root cause')
    listing.set_defaults(handler=run_list)
    apply = actions.add_parser('apply', parents=[common],
                               help='record a batch of sightings, lens stats and a session kind')
    apply.add_argument('--file', required=True, help='batch JSON file, or - for standard input')
    apply.set_defaults(handler=run_apply)


def run_list(args, environ):
    home = paths.resolve_home(args.home, environ)
    message = profile.missing_message(profile.load_profile(home))
    if message:
        print(message)
    for line in list_lines(records.load_anomalies(home)):
        print(line)
    return 0


def run_apply(args, environ):
    home = paths.resolve_home(args.home, environ)
    batch = parse_batch(read_batch(args.file), args.today)
    for line in apply_batch(home, batch, args.today):
        print(line)
    return 0

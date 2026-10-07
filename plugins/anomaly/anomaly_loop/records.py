"""Records under home: anomaly files, and the lens and session-kind line files.

An anomaly is `anomalies/<signature>.md`: frontmatter (see FIELDS, plus an optional nested
`experiment` block), then the problem or win paragraph, a `## Proposed fix` section for
problems, any other sections as written, and `## Sightings` as `- ` lines, newest first.
Score is impact x occurrences, computed on read and never written.

A `# comment` (alone, or after a space) is dropped from the fixed-vocabulary fields only
(kind, category, numbers, status, effort, dates, experiment kind, declared_on, check_by and
result); free-text
fields keep a `#` as written. A field that is not a number where one is expected keeps its
text, so validation rejects it instead of reading a silent default.

`fixed_by` is written as `YYYY-MM-DD · <ref>` (the day the fix landed, then its commit or file) by
fixed_by_text, and read only by fix_date; an older value without a leading date stays valid and
simply has no fix date. The experiment's optional fields are written only when set, so files from
before them keep their shape: `kind` (a session kind), `skill` (the new skill of a switch-over,
ADR-0013), `declared_on` (the day `calibrate declare`
wrote it; a fix cannot be dated before it) and `reason` (the verdict's one-line reason). When a new
experiment replaces one, the old one becomes a line under `## Earlier experiments`
(archive_experiment, newest first, with the whole `fixed_by` and the reason), so a reverted attempt
is never lost.

Line files: `lenses.jsonl` holds {session_id, date, lens, accepted, rejected}, plus `revised` on the
lines that have it;
`session-kinds.jsonl` holds {session_id, kind, set_on}, and the last line per session wins;
`work-units.jsonl` holds {feature, stage, session, date, ended}, one line per pipeline stage run
(`ended` is on every new line; a line from before it has only the first four), plus `started`,
`doc_bytes`, `ticket` and `mode` on the lines that have them.
"""
import argparse
import dataclasses
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import frontmatter
from .constants import (ACTIVE_STATUSES, ANOMALIES_DIR, CATEGORIES, EFFORTS, EXPERIMENT_RESULTS,
                        FIXED_BY_SEPARATOR, IMPACT_RANGE, KINDS, LENSES_FILE, REVIEW_MODES, SESSION_KINDS,
                        SESSION_KINDS_FILE, SIGHTING_SEPARATOR, STATUSES, TICKET_NUMBER_DIGITS, TICKET_TIME_FORMAT,
                        WORK_UNITS_FILE)
from .files import RecordError, append_line, load_lines, read_input, write_lines

FIELDS = ('signature', 'kind', 'category', 'target', 'scope', 'impact', 'occurrences', 'effort', 'status',
          'first_seen', 'last_seen', 'fixed_by')
EXPERIMENT_FIELDS = ('expect', 'metric', 'guard', 'kind', 'skill', 'declared_on', 'check_by', 'result', 'reason')
EXPERIMENT_OPTIONAL_FIELDS = ('kind', 'skill', 'declared_on', 'reason')   # written only when set
VOCABULARY_FIELDS = ('kind', 'category', 'impact', 'occurrences', 'effort', 'status', 'first_seen', 'last_seen')
EXPERIMENT_VOCABULARY_FIELDS = ('kind', 'declared_on', 'check_by', 'result')
FIX_HEADING = 'Proposed fix'
SIGHTINGS_HEADING = 'Sightings'
EARLIER_HEADING = 'Earlier experiments'
NOT_CHECKED = 'not checked'
NOT_FIXED = 'not fixed'

SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
HEADING = re.compile(r'##\s+(.+?)\s*$')
INLINE_COMMENT = re.compile(r'(?:^|\s+)#.*$')
LEADING_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
FIX_DATE = re.compile(r'(\d{4}-\d{2}-\d{2})(?:' + re.escape(FIXED_BY_SEPARATOR) + r'.*)?', re.S)
COUNT_TEXT = re.compile(r'[0-9]+')


@dataclass
class Experiment:
    expect: str = ''
    metric: str = ''
    guard: str = ''
    kind: str = ''
    skill: str = ''
    declared_on: str = ''
    check_by: str = ''
    result: str = ''
    reason: str = ''


@dataclass
class Anomaly:
    """One anomaly as read. impact and occurrences hold the file's raw text when it is not a
    whole number, until validate_anomaly rejects it: code that does arithmetic on them (other
    than `score`) must validate first, or load with strict=True."""
    signature: str
    kind: str = ''
    category: str = ''
    target: str = ''
    scope: str = ''
    impact: int = 1
    occurrences: int = 1
    effort: str = ''
    status: str = 'open'
    first_seen: str = ''
    last_seen: str = ''
    fixed_by: str = ''
    experiment: Experiment | None = None
    summary: str = ''
    proposed_fix: str = ''
    sightings: list = field(default_factory=list)
    sections: list = field(default_factory=list)

    @property
    def score(self):
        """impact x occurrences; 0 while either is not a whole number (validation reports it)."""
        if not all(is_whole(n) for n in (self.impact, self.occurrences)):
            return 0
        return self.impact * self.occurrences

    @property
    def active(self):
        return self.status in ACTIVE_STATUSES


# ---------- shared checks ----------

def is_slug(value):
    return bool(SLUG.fullmatch(value or ''))


def is_date(value):
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def has_line_break(text):
    """True when `text` holds a line feed or a carriage return: either one starts a new line."""
    return '\n' in text or '\r' in text


def single_line_problems(values):
    return [f'{name} must be one line' for name, value in values if has_line_break(str(value))]


def require_one_line(name, value):
    """`value` without surrounding white space; a value that is empty or breaks the line is refused (unlike
    profile.one_line, which collapses white space)."""
    value = value.strip()
    if not value or has_line_break(value):
        raise RecordError(f'{name} must be one non-empty line')
    return value


def is_whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def number(value):
    """A real number, or None: text, booleans, NaN and infinities are not numbers."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def is_count(value):
    """True for a whole number of 0 or more: every count the loop stores (lens counts, ticket metrics,
    doc bytes)."""
    return is_whole(value) and value >= 0


def count_option(text):
    """The argparse type of every count option: ASCII digits only (str.isdigit also takes '٣' and '²'),
    then is_count."""
    value = int(text) if COUNT_TEXT.fullmatch(text) else None
    if value is None or not is_count(value):
        raise argparse.ArgumentTypeError(f'a whole number of 0 or more, got: {text}')
    return value


def to_int(value, default):
    """The number in a field; `default` when blank or absent; the raw text when not a number,
    so validation can name it instead of a silent default."""
    if value is None or not str(value).strip():
        return default
    try:
        return int(value)
    except ValueError:
        return value


# ---------- anomaly files ----------

def anomaly_path(home, signature):
    return Path(home) / ANOMALIES_DIR / f'{signature}.md'


def split_body(body):
    """Return (paragraph, [(heading, text), ...]) of a record body."""
    lead, sections, current = [], [], None
    for line in body.splitlines():
        heading = HEADING.match(line)
        if heading:
            current = (heading.group(1), [])
            sections.append(current)
        else:
            (current[1] if current else lead).append(line)
    return '\n'.join(lead).strip(), [(name, '\n'.join(lines).strip()) for name, lines in sections]


def parse_dash_list(content):
    """The items of a `- ` list, one per dash line; a non-blank line without the dash continues the
    previous item. Sightings and earlier experiments are such lists."""
    sightings = []
    for line in content.splitlines():
        if line.startswith('- '):
            sightings.append(line[2:].strip())
        elif line.strip():
            if sightings:
                sightings[-1] = f'{sightings[-1]} {line.strip()}'
            else:
                sightings.append(line.strip())
    return sightings


def parse_anomaly(text, signature=''):
    fields, body = frontmatter.split(text)
    for key in VOCABULARY_FIELDS:
        if key in fields:
            fields[key] = INLINE_COMMENT.sub('', fields[key])
    summary, sections = split_body(body)
    anomaly = Anomaly(
        signature=fields.get('signature') or signature, kind=fields.get('kind', ''),
        category=fields.get('category', ''), target=fields.get('target', ''), scope=fields.get('scope', ''),
        impact=to_int(fields.get('impact'), 1), occurrences=to_int(fields.get('occurrences'), 1),
        effort=fields.get('effort', ''), status=fields.get('status') or 'open',
        first_seen=fields.get('first_seen', ''), last_seen=fields.get('last_seen', ''),
        fixed_by=fields.get('fixed_by', ''), summary=summary)
    if 'experiment' in fields:
        nested = frontmatter.pairs(fields['experiment'])
        for key in EXPERIMENT_VOCABULARY_FIELDS:
            if key in nested:
                nested[key] = INLINE_COMMENT.sub('', nested[key])
        anomaly.experiment = Experiment(**{key: nested.get(key, '') for key in EXPERIMENT_FIELDS})
    for name, content in sections:
        if name.lower() == FIX_HEADING.lower():
            anomaly.proposed_fix = content
        elif name.lower() == SIGHTINGS_HEADING.lower():
            anomaly.sightings = parse_dash_list(content)
        else:
            anomaly.sections.append((name, content))
    return anomaly


def render_anomaly(anomaly):
    fields = [(key, getattr(anomaly, key)) for key in FIELDS]
    if anomaly.experiment is not None:
        fields.append(('experiment', {key: getattr(anomaly.experiment, key) for key in EXPERIMENT_FIELDS
                                      if key not in EXPERIMENT_OPTIONAL_FIELDS or getattr(anomaly.experiment, key)}))
    blocks = [[anomaly.summary]] if anomaly.summary else []
    if anomaly.kind == 'problem' or anomaly.proposed_fix:
        blocks.append([f'## {FIX_HEADING}'] + ([anomaly.proposed_fix] if anomaly.proposed_fix else []))
    blocks += [[f'## {name}'] + ([content] if content else []) for name, content in anomaly.sections]
    blocks.append([f'## {SIGHTINGS_HEADING}'] + [f'- {line}' for line in anomaly.sightings])
    lines = frontmatter.render(fields)
    for number, block in enumerate(blocks):
        lines += ([''] if number else []) + block
    return lines


def validate_anomaly(anomaly):
    """Problems that make the record invalid; an empty list means it can be written."""
    problems = []
    if not is_slug(anomaly.signature):
        problems.append(f'signature {anomaly.signature!r} must be lowercase words joined by hyphens')
    if anomaly.kind not in KINDS:
        problems.append(f'kind {anomaly.kind!r} must be one of {", ".join(KINDS)}')
    if anomaly.category not in CATEGORIES:
        problems.append(f'category {anomaly.category!r} must be one of {", ".join(CATEGORIES)}')
    low, high = IMPACT_RANGE
    if not is_whole(anomaly.impact) or not low <= anomaly.impact <= high:
        problems.append(f'impact {anomaly.impact!r} must be {low} to {high}')
    if not is_whole(anomaly.occurrences) or anomaly.occurrences < 1:
        problems.append(f'occurrences {anomaly.occurrences!r} must be 1 or more')
    if anomaly.effort not in ('',) + EFFORTS:
        problems.append(f'effort {anomaly.effort!r} must be blank or one of {", ".join(EFFORTS)}')
    if anomaly.status not in STATUSES:
        problems.append(f'status {anomaly.status!r} must be one of {", ".join(STATUSES)}')
    for key in ('first_seen', 'last_seen'):
        value = getattr(anomaly, key)
        if value and not is_date(value):
            problems.append(f'{key} {value!r} must be a date like 2026-10-04')
    scalars = [(key, getattr(anomaly, key)) for key in FIELDS]
    if anomaly.experiment is not None:
        if anomaly.experiment.result not in ('',) + EXPERIMENT_RESULTS:
            problems.append(f'experiment result {anomaly.experiment.result!r} must be blank or one of '
                            f'{", ".join(EXPERIMENT_RESULTS)}')
        if anomaly.experiment.kind not in ('',) + SESSION_KINDS:
            problems.append(f'experiment kind {anomaly.experiment.kind!r} must be blank or one of '
                            f'{", ".join(SESSION_KINDS)}')
        if anomaly.experiment.skill and anomaly.experiment.kind != 'build':
            problems.append(f'experiment skill {anomaly.experiment.skill!r} needs kind build: a switch-over '
                            'compares build sessions')
        for key in ('declared_on', 'check_by'):
            value = getattr(anomaly.experiment, key)
            if value and not is_date(value):
                problems.append(f'experiment {key} {value!r} must be a date like 2026-10-04')
        scalars += [(f'experiment.{key}', getattr(anomaly.experiment, key)) for key in EXPERIMENT_FIELDS]
    return problems + single_line_problems(scalars)


def read_anomaly(path):
    path = Path(path)
    return parse_anomaly(read_input(path), path.stem)


def load_anomalies(home, strict=False):
    """Every anomaly under home. With strict, any invalid file (including a file name that is
    not its signature) raises one RecordError naming each such file."""
    loaded, invalid = [], []
    for path in sorted((Path(home) / ANOMALIES_DIR).glob('*.md')):
        anomaly = read_anomaly(path)
        problems = validate_anomaly(anomaly) if strict else []
        if strict and anomaly.signature != path.stem:
            problems.append(f'signature {anomaly.signature!r} differs from the file name')
        if problems:
            invalid.append(f'{path}: ' + '; '.join(problems))
        loaded.append(anomaly)
    if invalid:
        raise RecordError('invalid anomaly records: ' + ' | '.join(invalid))
    return loaded


def write_anomaly(home, anomaly):
    problems = validate_anomaly(anomaly)
    if problems:
        raise RecordError(f'anomaly {anomaly.signature}: ' + '; '.join(problems))
    path = anomaly_path(home, anomaly.signature)
    write_lines(path, render_anomaly(anomaly))
    return path


def ranked(anomalies):
    """Open and reopened anomalies, highest score first, then the newest last_seen."""
    active = sorted((a for a in anomalies if a.active), key=lambda a: a.last_seen, reverse=True)
    return sorted(active, key=lambda a: a.score, reverse=True)


def closed(anomalies):
    return [a for a in anomalies if not a.active]


def is_due(anomaly, today):
    """True when the anomaly has an experiment whose check_by date is `today` or earlier, that
    has no result yet, and whose fix has been made (`fixed_by` is set): an experiment is declared
    before the change, so a draft without a fix is never due. An unusable check_by (blank, not
    a date) is never due."""
    experiment = anomaly.experiment
    if (experiment is None or experiment.result or not anomaly.fixed_by.strip()
            or not is_date(experiment.check_by)):
        return False
    return date.fromisoformat(experiment.check_by) <= today


def fixed_by_text(day, ref):
    """The `fixed_by` value for a fix that landed on `day` (a date) as `ref` (a commit or a file)."""
    ref = (ref or '').strip()
    if not ref:
        raise RecordError('a fix needs a reference: the commit or the file that holds it')
    return f'{day.isoformat()}{FIXED_BY_SEPARATOR}{ref}'


def fix_date(anomaly):
    """The day the fix landed, from a date-first `fixed_by`; None when blank or an older value
    without a leading date. The only reader of that date."""
    found = FIX_DATE.fullmatch(anomaly.fixed_by.strip())
    return date.fromisoformat(found.group(1)) if found and is_date(found.group(1)) else None


def earlier_experiments(anomaly):
    """(result, line) for each experiment archived under `## Earlier experiments`, newest first."""
    for name, content in anomaly.sections:
        if name.lower() == EARLIER_HEADING.lower():
            lines = parse_dash_list(content)
            return [(line.split(FIXED_BY_SEPARATOR, 1)[0], line) for line in lines]
    return []


def archived_reverts(anomaly):
    """The archived experiment lines whose result was `revert`, newest first."""
    return [line for result, line in earlier_experiments(anomaly) if result == 'revert']


def archive_experiment(anomaly):
    """Move the experiment and the fix it records into a line under `## Earlier experiments` (newest
    first), leaving the anomaly ready for a new experiment: no experiment and a blank `fixed_by`."""
    experiment = anomaly.experiment or Experiment()
    fixed = anomaly.fixed_by.strip()
    parts = [experiment.result or NOT_CHECKED, f'fixed {fixed}' if fixed else NOT_FIXED,
             f'metric {experiment.metric}', f'guard {experiment.guard}', f'expect {experiment.expect}']
    if experiment.skill:
        parts.append(f'skill {experiment.skill}')
    if experiment.reason:
        parts.append(f'reason {experiment.reason}')
    line = FIXED_BY_SEPARATOR.join(parts)
    for number, (name, content) in enumerate(anomaly.sections):
        if name.lower() == EARLIER_HEADING.lower():
            anomaly.sections[number] = (name, '\n'.join([f'- {line}', content]).strip())
            break
    else:
        anomaly.sections.append((EARLIER_HEADING, f'- {line}'))
    anomaly.experiment = None
    anomaly.fixed_by = ''


def sighting_line(day, repo, session, text):
    """A sighting line `date · repo · session · text`: the one writer of the format."""
    return SIGHTING_SEPARATOR.join((day, repo, session, text))


def sighting_session(line):
    """The session id of a sighting line written by sighting_line, else None (an older or
    hand-written line without that shape)."""
    parts = line.split(SIGHTING_SEPARATOR, 3)
    return parts[2] if len(parts) == 4 and parts[2] else None


def sighting_day(line):
    """The date a sighting line starts with, else None. The one reader of a sighting's date."""
    found = LEADING_DATE.match(line.strip())
    return date.fromisoformat(found.group(0)) if found and is_date(found.group(0)) else None


def merge_sightings(*groups):
    """All sighting lines once each (identical lines are one sighting), newest date first."""
    unique = list(dict.fromkeys(line for group in groups for line in group))

    def day(line):
        found = sighting_day(line)
        return found.isoformat() if found else ''
    return sorted(unique, key=day, reverse=True)


def merge_anomalies(kept, folded):
    """`kept` with the unseen sightings of `folded` added, or None when there are none.

    Occurrences are summed over sightings not already in `kept`: on a first merge (no sighting
    shared) the folded count is added whole, as it may be higher than its sighting lines; once the
    two share a sighting, the folded count is already in `kept` and only the new lines add to it.
    Impact is the higher one, first and last seen the widest span, a fixed record reopens, and a
    blank field takes the folded record's value."""
    known = set(kept.sightings)
    fresh = [line for line in dict.fromkeys(folded.sightings) if line not in known]
    if not fresh:
        return None
    first_merge = known.isdisjoint(folded.sightings)
    seen = [day for day in (kept.first_seen, kept.last_seen, folded.first_seen, folded.last_seen) if day]
    return dataclasses.replace(
        kept,
        occurrences=kept.occurrences + (max(folded.occurrences, len(fresh)) if first_merge else len(fresh)),
        sightings=merge_sightings(kept.sightings, fresh),
        impact=max(kept.impact, folded.impact),
        first_seen=min(seen, default=''),
        last_seen=max(seen, default=''),
        status='reopened' if kept.status == 'fixed' else kept.status,
        category=kept.category or folded.category, target=kept.target or folded.target,
        scope=kept.scope or folded.scope, effort=kept.effort or folded.effort,
        summary=kept.summary or folded.summary, proposed_fix=kept.proposed_fix or folded.proposed_fix)


# ---------- line files ----------

def check_revised(label, accepted, revised):
    """Refuse a revised count that is no count of 0 or more, or is more than `accepted`: it counts the
    accepted findings whose fix differed from the one the reviewer proposed, so it is a subset of them."""
    if not is_count(revised):
        raise RecordError(f'{label}: revised must be a whole number of 0 or more')
    if revised > accepted:
        raise RecordError(f'{label}: revised {revised} is more than accepted {accepted}; revised counts only '
                          'accepted findings whose fix differed from the proposed one')


def lens_record(session_id, day, lens, accepted, rejected, revised=None, label='a lens line'):
    """A lenses.jsonl line; `revised` is written only when given, so two-count lines keep their shape.
    `label` starts the error about a wrong revised count (the caller's name for the entry)."""
    if not session_id or not lens or not is_date(day) or not (is_count(accepted) and is_count(rejected)):
        raise RecordError('a lens line needs a session id, a date, a lens name and two counts of 0 or more')
    record = {'session_id': session_id, 'date': day, 'lens': lens, 'accepted': accepted, 'rejected': rejected}
    if revised is not None:
        check_revised(label, accepted, revised)
        record['revised'] = revised
    return record


def append_lens(home, record):
    append_line(Path(home) / LENSES_FILE, record)


def load_lenses(home):
    return load_lines(Path(home) / LENSES_FILE)


def is_ticket_number(value):
    """True for a bare ticket number: TICKET_NUMBER_DIGITS ASCII digits (NN), nothing around them."""
    return isinstance(value, str) and re.fullmatch(rf'[0-9]{{{TICKET_NUMBER_DIGITS}}}', value) is not None


def check_ticket_number(label, value):
    """Refuse a value that is not a bare ticket number (is_ticket_number); `label` names it in the message."""
    if not is_ticket_number(value):
        raise RecordError(f'{label} is {TICKET_NUMBER_DIGITS} ASCII digits (NN), got: {value!r}')


def is_ticket_time(value):
    """True for a time in the form a Metrics: line uses (TICKET_TIME_FORMAT)."""
    try:
        datetime.strptime(value, TICKET_TIME_FORMAT)
    except (TypeError, ValueError):
        return False
    return True


def work_unit_record(feature, stage, session, day, *, started=None, ended=None, doc_bytes=None, ticket=None,
                     mode=None):
    """One stage run on a work unit. The names are checked as identifiers by the writer (privacy).
    The measurement fields are additive: a key is written only when its value is given, so a line
    without them is the line this function made before they existed."""
    if not feature or not stage or not session or not is_date(day):
        raise RecordError('a work-unit line needs a feature, a stage, a session and a date')
    record = {'feature': feature, 'stage': stage, 'session': session, 'date': day}
    for key, value in (('started', started), ('ended', ended)):
        if value is not None:
            if not is_ticket_time(value):
                raise RecordError(f'a work-unit {key} time is like 2026-10-04 12:00, got: {value!r}')
            record[key] = value
    if doc_bytes is not None:
        if not is_count(doc_bytes):
            raise RecordError(f'a work-unit doc_bytes is a whole number of 0 or more, got: {doc_bytes!r}')
        record['doc_bytes'] = doc_bytes
    if ticket is not None:
        check_ticket_number('a work-unit ticket', ticket)
        record['ticket'] = ticket
    if mode is not None:
        if mode not in REVIEW_MODES:
            raise RecordError(f'a work-unit mode is one of {", ".join(REVIEW_MODES)}, got: {mode!r}')
        record['mode'] = mode
    return record


def append_work_unit(home, record):
    """Add the line to home's work-units file and return that file's path (for the commit)."""
    path = Path(home) / WORK_UNITS_FILE
    append_line(path, record)
    return path


def load_work_units(home):
    return load_lines(Path(home) / WORK_UNITS_FILE)


def session_kind_record(session_id, kind, set_on):
    if not session_id or kind not in SESSION_KINDS or not is_date(set_on):
        raise RecordError(f'a session kind line needs a session id, a kind ({", ".join(SESSION_KINDS)}) '
                          'and a date')
    return {'session_id': session_id, 'kind': kind, 'set_on': set_on}


def append_session_kind(home, record):
    append_line(Path(home) / SESSION_KINDS_FILE, record)


def load_session_kinds(home):
    """Session id -> its last valid line."""
    kinds = {}
    for row in load_lines(Path(home) / SESSION_KINDS_FILE):
        if row.get('session_id') and row.get('kind') in SESSION_KINDS:
            kinds[row['session_id']] = row
    return kinds

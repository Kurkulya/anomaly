"""The metric registry and the verdict of an experiment (ADR-0002), for calibrate.

Metric registry. An experiment names exactly one primary metric and one guard, each a name from
METRIC_NAMES (case and outer spaces do not matter; anything else is refused):
  - `weighted tokens`, `active minutes`, `interrupts`, `denials`: the trend metrics of one session
    (trends.METRICS), compared over sessions by the statistic trends.METRICS gives each (median or mean);
  - `weighted tokens without security`: a session's weighted tokens less the core security
    reviewer's (its `tokens_by_agent` entry), by the statistic of weighted tokens, so a switch-over
    leaves the new coverage out (ADR-0013). Registered here only, not a digest trend;
  - `model-weighted tokens per dispatch <agent>`, for any agent name (kept in its case): the agent's
    `model_weighted_by_agent` (each API call's weighted tokens times its model's factor,
    constants.MODEL_FACTORS) divided by its `subagents.by_type` count, by the statistic of weighted
    tokens. A session without a dispatch of the agent, with a call of the agent on a model with
    no factor (`unknown_model_by_agent`), or with a spawn without `.meta.json` (`skipped_spawns`,
    whose dispatch count is short) has no value: it is skipped, never read as 0; verify counts
    the second kind. Resolved by name in resolve_metric, so it is not in REGISTRY;
  - `sightings since the fix`: the anomaly's own sightings (the rare-event primary, judged by
    recurrence), and `<category> sightings` for each category (e.g. `rework sightings`,
    `late-catch sightings`): sightings of problems of that category. Sightings are rare, so they are
    compared as a rate: sightings per session.
User corrections and review misses reach the backlog as rework and late-catch sightings, so those
two are the usual guards. For every metric fewer is better.

A guard must be one of QUALITY_GUARDS and differ from the metric (experiment_metrics, checked when
assess drafts an experiment and when calibrate declares one).

Sighting windows. The backlog only knows sightings from its first sighting on: a window that starts
before the earliest sighting of any anomaly reads as unknown, not as zero. A fix can therefore be
judged on a sighting metric only from first_judgeable_fix_day on (the backlog's start plus
BASELINE_DAYS); before that, an experiment that would be inconclusive says the backlog does not
cover the baseline.

Verdict (ADR-0002, its gate replaced by ADR-0009). Sessions are split by trends.fix_windows: the
BASELINE_DAYS days before the fix day against the days after it, only sessions of the experiment's
kind when it has one; for a switch-over (an experiment with a `skill`) the sessions that did not run
the new skill against those since the fix that ran it and no other build skill, fall-backs counted
apart (trends.fix_windows, ADR-0013). Each reading carries the trends.Change of its two windows;
what a real change is, and when a reading is unknown, is decided by trends.real_change alone (see
there). Weighted tokens below means any tokens metric (is_token_metric). Here the
primary, and active minutes read next to weighted tokens, are tested both ways (permutation.TWO_WAY),
and the guard as a rise only (permutation.WORSE): a guard that fell, or that stayed at 0, is never
worse. A sighting metric tests the per-session counts; sightings that belong to no session of the
window count in the shown rate, not in the test. A sighting guard counts as worse only with
GUARD_MIN_SIGHTINGS sightings since the fix; with fewer it is thin. In order:
  1. the guard is worse: revert (the quality floor comes first);
  2. the primary is weighted tokens and active minutes are worse: revert (time before tokens);
  3. the primary is worse: revert;
  4. the primary is better, the guard is better or the same, and (for weighted tokens) active
     minutes are better or the same: keep;
  5. anything else: inconclusive. The first time, the check date moves EXPERIMENT_CHECK_DAYS out;
     when it comes again and the numbers still cannot say, the user decides (`decide`).
The rare-event primary `sightings since the fix` uses no count test and no baseline: 1 or 2 sightings
can never prove a fix (ADR-0009). Only a worse guard comes first (step 1); a guard that is unknown or
thin does not block, and the reason names it. Otherwise the anomaly's own sightings since the fix
decide: one or more is `revert` (it came back), none is `unproven` (kept, not proven). A backlog that
does not cover the baseline never makes it inconclusive.
The sightings of the anomaly since the fix (kind-filtered, counted once by sighting_counts) are always
shown, and so are its sightings on the fix day: they are in neither window, so the verdict does not
count them, even when one of them is the sighting that reopened the anomaly. `revert` reopens the
anomaly. Every reason ends with the rule that produced it, VERDICT_RULE (RARE_EVENT_RULE for the
rare-event primary), so a result written under the older 15% rule can be told apart.
"""
from collections import namedtuple
from dataclasses import dataclass
from datetime import timedelta
from math import ceil
from statistics import fmean

from . import permutation, records, trends
from .constants import (BASELINE_DAYS, CATEGORIES, GUARD_MIN_SIGHTINGS, QUALITY_GUARDS, RARE_EVENT_RULE,
                        SECURITY_REVIEWER, VERDICT_RULE)
from .files import RecordError

SIGHTINGS_SINCE_FIX = 'sightings since the fix'
THIN_TEXT = f'rose by fewer than {GUARD_MIN_SIGHTINGS} sightings'
TIME, TOKENS = 'active minutes', 'weighted tokens'
TOKENS_WITHOUT_SECURITY = 'weighted tokens without security'
PER_DISPATCH = 'model-weighted tokens per dispatch'   # the metric name is this and an agent name
TOKEN_NAMES = (TOKENS, TOKENS_WITHOUT_SECURITY)   # read with active minutes beside them; shown shortened


# ---------- the metric registry ----------

@dataclass(frozen=True)
class Metric:
    """A registered metric with the `statistic` (median or mean) of its window: a trend metric's is
    copied from trends.METRICS, a sighting metric's is the mean (the rate). `samples(context, anomaly,
    rows, days)` gives the trends.Window of the sessions `rows` that started in the window `days`
    (first day, last day), and `read` turns it into the window's trends.Sample. `per_session` is True
    for a metric read from each session's row, False for one that counts sightings. Fewer is better."""
    name: str
    statistic: object
    samples: object
    per_session: bool

    def read(self, context, anomaly, rows, days):
        return trends.sample(self.statistic, self.samples(context, anomaly, rows, days))


def row_metric(measure):
    return lambda context, anomaly, rows, days: trends.Window(trends.measured(rows, measure))


def weighted_without_security(row):
    """A row's weighted tokens less the security reviewer's entry in `tokens_by_agent` (keyed by the
    transcript's attributionAgent); a row without that entry, or without the table, keeps its whole
    weighted tokens: measure writes the table on every row, so no entry means no security tokens."""
    total = trends.weighted_tokens(row)
    table = row.get('tokens_by_agent')
    bucket = table.get(SECURITY_REVIEWER) if isinstance(table, dict) else None
    security = records.number(bucket.get('weighted')) if isinstance(bucket, dict) else None
    return None if total is None else total - (security or 0)


def per_agent_number(row, field, agent):
    """The number a row's `field` table (keyed by agent) holds for `agent`, or None."""
    table = row.get(field)
    return records.number(table.get(agent)) if isinstance(table, dict) else None


def dispatches_of(row, agent):
    """How often a row's session dispatched `agent` (`subagents.by_type`), or None without the table."""
    spawns = row.get('subagents')
    return per_agent_number(spawns, 'by_type', agent) if isinstance(spawns, dict) else None


def lacks_factor(row, agent):
    """True when a row's session has a call of `agent` on a model with no factor."""
    return bool(per_agent_number(row, 'unknown_model_by_agent', agent))


def has_spawn_without_meta(row):
    """True when a row has a spawn without `.meta.json` (`skipped_spawns`): measure counts its dispatch as
    `unknown`, but its calls still add to `model_weighted_by_agent`, so the agent's dispatch count is short."""
    return (records.number(row.get('skipped_spawns')) or 0) > 0


def model_weighted_per_dispatch(agent):
    """The measure of a row for the metric `model-weighted tokens per dispatch <agent>`: the agent's
    `model_weighted_by_agent` divided by its dispatches; None (no value, not 0) for a row without a
    dispatch of the agent or without the field (an older row), for a row whose agent had a call on
    a model with no factor (its sum would be short), and for a row with a spawn without `.meta.json`
    (its dispatch count would be short)."""
    def measure(row):
        dispatches, total = dispatches_of(row, agent), per_agent_number(row, 'model_weighted_by_agent', agent)
        if not dispatches or total is None or lacks_factor(row, agent) or has_spawn_without_meta(row):
            return None
        return total / dispatches
    return measure


def skipped_for_model(rows, agent):
    """How many of the sessions `rows` the metric of `agent` leaves out for a call on a model with
    no factor (a session without a dispatch of the agent, or with a spawn without `.meta.json`, is left
    out for that, not counted here)."""
    return sum(bool(dispatches_of(row, agent)) and lacks_factor(row, agent) and not has_spawn_without_meta(row)
               for row in rows)


def sighting_metric(lines_of):
    def samples(context, anomaly, rows, days):
        return sighting_counts(context, lines_of(context, anomaly), rows, days, experiment_kind(anomaly),
                               experiment_skill(anomaly))
    return samples


def own_sightings(context, anomaly):
    return anomaly.sightings


def category_sightings(category):
    def lines(context, anomaly):
        return [line for a in context.anomalies if a.kind == 'problem' and a.category == category
                for line in a.sightings]
    return lines


REGISTRY = {metric.name: metric for metric in (
    *(Metric(label, statistic, row_metric(measure), per_session=True)
      for label, measure, statistic in trends.METRICS),
    Metric(TOKENS_WITHOUT_SECURITY, {label: statistic for label, _, statistic in trends.METRICS}[TOKENS],
           row_metric(weighted_without_security), per_session=True),
    Metric(SIGHTINGS_SINCE_FIX, fmean, sighting_metric(own_sightings), per_session=False),
    *(Metric(f'{category} sightings', fmean, sighting_metric(category_sightings(category)), per_session=False)
      for category in CATEGORIES),
)}
METRIC_NAMES = (*REGISTRY, f'{PER_DISPATCH} <agent>')   # the last one stands for a metric per agent name


def per_dispatch_agent(name):
    """The agent of a resolved metric name `model-weighted tokens per dispatch <agent>`, else None."""
    return name[len(PER_DISPATCH) + 1:] if name.startswith(f'{PER_DISPATCH} ') else None


def is_token_metric(name):
    """True for a registered tokens metric (TOKEN_NAMES, or one per agent): read with active minutes."""
    return name in TOKEN_NAMES or per_dispatch_agent(name) is not None


def resolve_metric(name):
    text = ' '.join(str(name or '').split())
    metric = REGISTRY.get(text.lower())
    agent = text[len(PER_DISPATCH) + 1:]   # an agent name keeps its case; only one name is allowed
    if (metric is None and text.lower().startswith(f'{PER_DISPATCH} ') and ' ' not in agent
            and not agent.startswith('<')):   # `<agent>` is the placeholder of the metric list, not a name
        metric = Metric(f'{PER_DISPATCH} {agent}', REGISTRY[TOKENS].statistic,
                        row_metric(model_weighted_per_dispatch(agent)), per_session=True)
    if metric is None:
        raise RecordError(f'unknown metric {name!r}: name exactly one of: {", ".join(METRIC_NAMES)}')
    return metric


def experiment_metrics(label, metric, guard):
    """(metric name, guard name) as registered, for an experiment that is drafted or declared: both
    are registered names, the guard is one of QUALITY_GUARDS and differs from the metric. The one
    check of an experiment's pair, for assess and calibrate; RecordError otherwise."""
    metric, guard = resolve_metric(metric).name, resolve_metric(guard).name
    if metric == guard:
        raise RecordError(f'{label}: the guard must differ from the primary metric')
    if guard not in QUALITY_GUARDS:
        raise RecordError(f'{label}: the guard must be a quality signal, one of: {", ".join(QUALITY_GUARDS)}')
    return metric, guard


def experiment_kind(anomaly):
    return anomaly.experiment.kind if anomaly.experiment is not None else ''


def experiment_skill(anomaly):
    return anomaly.experiment.skill if anomaly.experiment is not None else ''


def is_sighting_metric(name):
    """True for a registered metric that counts sightings (its baseline needs the backlog)."""
    return not resolve_metric(name).per_session


def backlog_start(context):
    """The day of the earliest sighting of any anomaly, or None when there is none."""
    days = [day for a in context.anomalies for line in a.sightings if (day := records.sighting_day(line))]
    return min(days, default=None)


def first_judgeable_fix_day(context):
    """The first fix day whose BASELINE_DAYS before it the backlog covers, or None without a backlog."""
    began = backlog_start(context)
    return None if began is None else began + timedelta(days=BASELINE_DAYS)


def sighting_counts(context, lines, rows, days, kind, skill=''):
    """The trends.Window of sightings: the distinct sighting lines dated in `days`, each counted
    for the session of `rows` it names (metrics rows are keyed by session, so each session id has
    one slot). A line whose session is not in `rows`
    (it was not measured, or it started outside the window) is left out of the per-session counts
    but still counts in the rate, which is (counts + left out) / sessions. With a kind, a sighting
    from a measured session of another kind is left out of both. With a `skill` (a switch-over,
    whose two sides share their days) only a sighting from a session in `rows` counts: any other
    belongs to the other side, a fall-back, the fix day or no known side, so it is on neither side
    and nothing is left out. The window is not known without sessions, or when it starts before
    the backlog began (backlog_start)."""
    first, last = days
    kinds = {row.get('session_id'): trends.context_session_kind(context, row) for row in context.metrics_rows}
    slots = {}
    for index, row in enumerate(rows):
        slots.setdefault(row.get('session_id'), index)
    counts, left_out = [0] * len(rows), 0
    for line in dict.fromkeys(lines):
        day = records.sighting_day(line)
        session = records.sighting_session(line)
        if day is None or not first <= day <= last or (kind and kinds.get(session, kind) != kind):
            continue
        if skill and session not in slots:
            continue
        if session in slots:
            counts[slots[session]] += 1
        else:
            left_out += 1
    began = backlog_start(context)
    return trends.Window(counts, left_out, bool(rows) and began is not None and first >= began)


# ---------- the verdict ----------

Reading = namedtuple('Reading', 'name before after sightings change')
Reading.__doc__ = ('One metric around a fix: before and after are trends.Sample windows; sightings is '
                   'the number counted since the fix for a sighting metric, else None. For a reading judged '
                   'by the permutation test, change is the trends.Change of the windows (trends.real_change); '
                   'else None.')
Verdict = namedtuple('Verdict', 'result reason readings sightings_since fix_day_sightings fall_backs no_factor',
                     defaults=(None, None))
Verdict.__doc__ = ('The result and reason, the Readings, the sightings counts, for a switch-over the number '
                   'of fall-back sessions (in neither side), else None, and for a model-weighted tokens per '
                   'dispatch primary the number of sessions in the two windows left out for a call on a model '
                   'with no factor, else None.')


def is_rare_event(name):
    """True for the metric name `sightings since the fix` as a primary: judged by recurrence."""
    return name == SIGHTINGS_SINCE_FIX


def compare(reading):
    """`better`, `worse` or `same`, or `unknown` without enough sessions: the state of the reading's
    trends.Change, with the direction of the shown change for a real one. A reading without a Change
    (the rare-event primary) is judged by recurrence, not by this."""
    state = reading.change.state
    if state == trends.UNKNOWN:
        return 'unknown'
    if state == trends.NOT_MOVED:
        return 'same'
    return 'better' if reading.after.value < reading.before.value else 'worse'


def guard_look(guard):
    """compare() for the guard, except that a sighting guard with fewer than GUARD_MIN_SIGHTINGS
    sightings since the fix cannot be worse yet: it is `thin`."""
    look = compare(guard)
    if look == 'worse' and guard.sightings is not None and guard.sightings < GUARD_MIN_SIGHTINGS:
        return 'thin'
    return look


def why_guard_unjudged(guard, look):
    """Why the guard cannot be judged (for a `look` of `unknown` or `thin`), else None."""
    if look == 'thin':
        return f'it {THIN_TEXT}'
    return trends.why_unknown(guard.before, guard.after) if look == 'unknown' else None


def judge_rare_event(primary, guard, look, kind=''):
    """(result, reason) for the primary `sightings since the fix`, whose guard is not worse (`look` is
    the guard_look): `revert` when the anomaly came back, else `unproven`. The reading's sightings
    are the kind-filtered count since the fix, so with a `kind` the reason says which sessions
    were watched. A guard that could not be judged is named in either reason, not a block."""
    why = why_guard_unjudged(guard, look)
    named = f'; the guard {guard.name} could not be judged ({why})' if why else ''
    if primary.sightings:
        return 'revert', f'the anomaly came back after the fix ({SIGHTINGS_SINCE_FIX}: {primary.sightings}){named}'
    return 'unproven', f'no recurrence{f" in {kind} sessions" if kind else ""} since the fix{named}'


def judge(primary, guard, time=None, kind=''):
    """(result, reason) from the readings, in the order of the module doc (ADR-0002); a rare-event
    primary goes on to judge_rare_event once the guard is not worse. `time` is the active-minutes
    reading, given when the primary is a tokens metric (is_token_metric); `kind` is the experiment's session kind."""
    looks = {'primary': None if is_rare_event(primary.name) else compare(primary), 'guard': guard_look(guard),
             'time': compare(time) if time else None}
    if looks['guard'] == 'worse':
        return 'revert', f'the guard {guard.name} got worse; quality comes first'
    if is_rare_event(primary.name):
        return judge_rare_event(primary, guard, looks['guard'], kind)
    if looks['time'] == 'worse':
        return 'revert', f'{TIME} got worse; time comes before tokens'
    if looks['primary'] == 'worse':
        return 'revert', f'{primary.name} got worse'
    held = looks['guard'] in ('better', 'same') and looks['time'] in (None, 'better', 'same')
    if looks['primary'] == 'better' and held:
        return 'keep', f'{primary.name} made a {trends.MOVED} for the better and the guard held'
    if looks['guard'] == 'thin':
        return 'inconclusive', f'the guard {guard.name} {THIN_TEXT}; wait for more'
    if looks['time'] == 'unknown':
        why = trends.why_unknown(time.before, time.after)
        return 'inconclusive', f'{TIME} cannot be judged yet: {why}; time comes before tokens'
    for reading, look in ((primary, looks['primary']), (guard, looks['guard'])):
        if look == 'unknown':
            why = trends.why_unknown(reading.before, reading.after)
            return 'inconclusive', f'{reading.name} cannot be judged yet: {why}'
    return 'inconclusive', f'{primary.name} is {trends.NOT_MOVED}'


def verdict(context, anomaly):
    """The Verdict for the anomaly's experiment; RecordError when it cannot be measured."""
    experiment = anomaly.experiment
    if experiment is None:
        raise RecordError(f'anomaly {anomaly.signature} has no experiment')
    fix_day = records.fix_date(anomaly)
    if fix_day is None:
        raise RecordError(f'anomaly {anomaly.signature}: fixed_by {anomaly.fixed_by!r} has no fix date, so '
                          'there is no before and after; the user decides')
    primary, guard = resolve_metric(experiment.metric), resolve_metric(experiment.guard)
    metrics = [primary, guard] + ([REGISTRY[TIME]] if is_token_metric(primary.name) and guard.name != TIME else [])
    before, after = trends.fix_windows(context, fix_day, experiment.kind, experiment.skill)
    before_days, after_days = trends.fix_window_days(fix_day, context.today, experiment.skill)
    readings = []
    for metric in metrics:
        then = metric.read(context, anomaly, before, before_days)
        since = metric.read(context, anomaly, after, after_days)
        sightings = since.total if is_sighting_metric(metric.name) else None
        direction = permutation.WORSE if metric is guard else permutation.TWO_WAY
        rare = metric is primary and is_rare_event(metric.name)
        tested = None if rare else trends.real_change(then, since, metric.statistic, direction)
        readings.append(Reading(metric.name, then, since, sightings, tested))
    result, reason = judge(*readings, kind=experiment.kind)
    judgeable = first_judgeable_fix_day(context)
    uncovered = judgeable is None or fix_day < judgeable
    if result == 'inconclusive' and uncovered and any(is_sighting_metric(m.name) for m in metrics):
        reason = f'{trends.BACKLOG_GAP} the {BASELINE_DAYS} days before the fix' + (
            f' (it starts on {backlog_start(context)})' if judgeable else ' (it has no sightings yet)')
    own = (readings[0].sightings if is_rare_event(primary.name)
           else REGISTRY[SIGHTINGS_SINCE_FIX].read(context, anomaly, after, after_days).total)
    on_fix_day = [records.sighting_day(line) for line in dict.fromkeys(anomaly.sightings)].count(fix_day)
    rule = RARE_EVENT_RULE if is_rare_event(primary.name) else VERDICT_RULE
    skipped = (len(trends.fall_backs(context, fix_day, experiment.kind, experiment.skill))
               if experiment.skill else None)
    agent = per_dispatch_agent(primary.name)
    no_factor = None if agent is None else skipped_for_model(before + after, agent)
    return Verdict(result, f'{reason}; {rule}', readings, own, on_fix_day, skipped, no_factor)


def fix_day_line(anomaly, found):
    """The line about the anomaly's sightings on the fix day (in neither window), or None without any.
    A reopened anomaly with no sighting of any kind after the fix day was reopened by one of them:
    that is what observe reopens on, so the kind filter of found.sightings_since does not apply."""
    if not found.fix_day_sightings:
        return None
    fix_day = records.fix_date(anomaly)
    later = any(day is not None and day > fix_day for day in map(records.sighting_day, anomaly.sightings))
    reopened = anomaly.status == 'reopened' and not later
    return (f'- sightings on the fix day ({records.fix_date(anomaly)}): {found.fix_day_sightings}; in neither '
            'window, so the verdict does not count them' + ('; one of them reopened the anomaly' if reopened else ''))


def format_value(name, value):
    if value is None:
        return '-'
    return trends.size(value) if is_token_metric(name) else trends.plain(value, REGISTRY[name].statistic)


def reading_line(reading, role):
    """The values and sample sizes. A reading without a Change (the rare-event primary) adds the
    sightings since the fix and nothing else: no count test is used for it. For any other reading
    with enough sessions also the
    change (none from 0 to 0), the share of random splits (rounded up, so chance alone above
    its level never shows as the level or less), the verdict word, whether the tested
    sessions moved against the shown change, and how many sightings were left out of the test."""
    before, after = reading.before, reading.after
    line = (f'- {reading.name} ({role}): {format_value(reading.name, before.value)} (n={before.n}) before, '
            f'{format_value(reading.name, after.value)} (n={after.n}) since')
    found = reading.change
    if found is None:
        return f'{line}; {SIGHTINGS_SINCE_FIX}: {reading.sightings}'
    if found.state == trends.UNKNOWN:
        return line
    text = trends.relative_change(after.value, before.value)
    line += f', {text}' if text else ''
    line += f'; {ceil(round(found.chance * 100, 6))}% of random splits change this much → {found.state}'
    if found.opposed:
        line += '; the tested sessions moved the other way'
    left_out = before.left_out + after.left_out
    return line + (f'; sightings left out of the test: {left_out}' if left_out else '')

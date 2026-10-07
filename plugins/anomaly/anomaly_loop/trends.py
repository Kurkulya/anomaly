"""Digest sections for direction: trends per session kind, top skills, experiments due, their results, reverts.

`session_kind(row, overrides, build_skills, user_config)` is the one place a session's kind is
decided; `context_session_kind(context, row)` is the same call fed from a digest Context, for
code that has a context and needs one row. The kind is computed on read and never stored: a
`session-kinds.jsonl` override wins, then build skills used (`build`), then a working folder
under the user config folder (`config`), else `unknown`.
`fix_windows(context, fix_day, kind, skill)` is the one split of sessions around a fix (baseline
before, sessions after; for a switch-over, old-skill sessions against new-skill ones, `skill_side`),
and `experiment_due(context, anomaly)` the one rule for "an experiment is due"; the digest, the
nudge and calibrate all call them.
`real_change(before, after, statistic, direction)` is the one owner of "is this a real change"
(ADR-0009): the digest trend lines and the verdict of an experiment both call it.
All sections cost no model tokens and only read the context. Dates are in the clock of
`context.now`, the same clock as `context.today`.
"""
from collections import Counter, namedtuple
from datetime import date, datetime, timedelta
from functools import partial
from statistics import fmean, median

from . import metrics, permutation, profile
from .constants import (BASELINE_DAYS, DIGEST_TOP_SKILLS, EXPERIMENT_CHECK_SESSIONS, EXPERIMENT_RESULTS,
                        GUARD_LEVEL, REVERTED_FIX_CHARS, SESSION_KINDS, TREND_WINDOW_DAYS, VERDICT_LEVEL,
                        VERDICT_MIN_CHANGE, VERDICT_MIN_SAMPLES)
from .records import archived_reverts, fix_date, is_date, is_due, number

SIZE_UNITS = ((1_000_000, 'M', 1), (1_000, 'k', 0))   # (from, suffix, decimals)
DUE_BY_DATE = 'check date reached'                     # experiment_due reasons
DUE_FOR_DECISION = 'still inconclusive: the user decides'


def weighted_tokens(row):
    return number(row.get('weighted'))


def active_minutes(row):
    return number(row.get('active_min'))


def friction_count(row, *path):
    value = row.get('friction')
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return number(value)


def interrupts(row):
    return friction_count(row, 'interrupts')


def denials(row):
    return friction_count(row, 'denials', 'total')


# Trend metrics as (label, function of a row giving a number or None, statistic of a window: median or
# mean). The one place a trend metric's statistic is decided: the digest and the verdict registry read it.
# Interrupts are a mean: they are 0 in nearly every session, so their median never moves.
METRICS = (('weighted tokens', weighted_tokens, median), ('active minutes', active_minutes, median),
           ('interrupts', interrupts, fmean), ('denials', denials, median))
STATISTIC_WORDS = {median: 'median', fmean: 'mean'}   # a statistic as the digest header says it


# ---------- session kind ----------

def folder_key(text):
    """A folder as comparable text: one slash style, no trailing slash, and lower case for a
    Windows drive path (those are case-insensitive)."""
    key = str(text).replace('\\', '/').rstrip('/')
    return key.lower() if key[1:3] == ':/' else key


def is_under(folder, base):
    folder, base = folder_key(folder), folder_key(base)
    return bool(base) and (folder == base or folder.startswith(base + '/'))


def session_kind(row, overrides, build_skills, user_config):
    """The kind of one metrics row: one of constants.SESSION_KINDS. Never stored.

    `overrides` maps a session id to its session-kinds line (records.load_session_kinds),
    `build_skills` is profile.build_skills(profile), `user_config` the Claude Code user folder."""
    override = overrides.get(row.get('session_id'))
    if override:
        return override['kind']
    if set(build_skills) & metrics.skills_used(row):
        return 'build'
    cwd = row.get('cwd_first')
    if isinstance(cwd, str) and is_under(cwd, user_config):
        return 'config'
    return 'unknown'


def context_session_kind(context, row):
    """session_kind fed from a digest Context (reads only its session_kinds, profile and user_config)."""
    return session_kind(row, context.session_kinds, profile.build_skills(context.profile), context.user_config)


# ---------- windows ----------

def session_day(row, tz):
    """The day a session started, in the clock `tz`; None without a usable start time."""
    epoch = metrics.parse_ts(row.get('first_ts'))
    return None if epoch is None else datetime.fromtimestamp(epoch, tz).date()


def window_start(today, length):
    """The first day of a window of `length` days ending `today`, both ends included. The one
    N-day window rule: every window of the digest, the flags and calibrate starts here."""
    return today - timedelta(days=length - 1)


def rows_in_window(context, since):
    """(day, row) for the metrics rows whose session started from `since` to context.today, the
    day in the clock of context.now (session_day). Sessions without a usable start time, or
    after today, are in no window."""
    days = ((session_day(row, context.now.tzinfo), row) for row in context.metrics_rows)
    return [(day, row) for day, row in days if day is not None and since <= day <= context.today]


def windows(context):
    """(last window rows, the window before): TREND_WINDOW_DAYS each, the last one ending
    context.today (window_start, rows_in_window)."""
    recent_start = window_start(context.today, TREND_WINDOW_DAYS)
    previous_start = window_start(recent_start - timedelta(days=1), TREND_WINDOW_DAYS)
    rows = rows_in_window(context, previous_start)
    return [row for day, row in rows if day >= recent_start], [row for day, row in rows if day < recent_start]


# ---------- formatting ----------

def size(value):
    for threshold, suffix, places in SIZE_UNITS:
        if abs(value) >= threshold:
            return f'{value / threshold:.{places}f}{suffix}'
    return plain(value)


def plain(value, statistic=median):
    """The one rule that prints a number: a median has one decimal, a mean two (a mean is often below 1,
    so one decimal would show it as 0 beside a real change); trailing zeros are dropped."""
    places = 2 if STATISTIC_WORDS[statistic] == 'mean' else 1
    return f'{value:.{places}f}'.rstrip('0').rstrip('.')


def statistics_note():
    """The statistic of the trend metrics as header text: the usual one, then each metric that differs."""
    words = [(label, STATISTIC_WORDS[statistic]) for label, _, statistic in METRICS]
    usual = max((word for _, word in words), key=[word for _, word in words].count)
    others = ''.join(f'; {label}: {word}' for label, word in words if word != usual)
    return f'({usual}, n = sessions{others})'


# ---------- sections ----------

# What a metric read gives for one window: one value per session, the count of what belongs to no
# session of the window (only a sighting metric has any), and whether the window is known at all.
Window = namedtuple('Window', 'values left_out known', defaults=(0, True))


class Sample(namedtuple('Sample', 'value values left_out', defaults=(0,))):
    """A metric over the sessions of one window: `values` holds one value per session, `value` is
    the metric's statistic of them (computed by sample()). `left_out` counts what is in the value
    but belongs to no session of the window; only a sighting metric has any."""
    __slots__ = ()

    @property
    def n(self):
        """The sample size: the number of sessions with a value."""
        return len(self.values)

    @property
    def total(self):
        """The sum of the values and the left-out count: for a sighting metric, the sightings counted."""
        return sum(self.values) + self.left_out


def measured(rows, measure):
    """The values of `measure` over the rows that have the number."""
    return tuple(v for v in map(measure, rows) if v is not None)


def sample(statistic, window):
    """The Sample of a Window under `statistic` (median or mean); its value is None without values
    or when the window is not known. With a left-out count the value is the sighting rate instead:
    total / sessions, so what belongs to no session still counts."""
    found = Sample(None, tuple(window.values), window.left_out)
    if not window.known or not found.values:
        return found
    return found._replace(value=found.total / found.n if found.left_out else statistic(found.values))


def shown(value, show):
    return '-' if value is None else show(value)


def relative_change(recent, previous):
    """The change from the value `previous` to the value `recent` as text: `-50%`; from a zero
    `previous`, `from 0`, or no text when `recent` is zero too."""
    if not previous:
        return 'from 0' if recent else ''
    return f'{(recent - previous) / abs(previous) * 100:+.0f}%'


BACKLOG_GAP = 'the backlog does not cover'   # the one phrase for a window that starts before the backlog began


def why_unknown(before, after):
    """None when both windows are known and each has VERDICT_MIN_SAMPLES sessions or more, else why
    not: the one text of the reason a reading is unknown."""
    if min(before.n, after.n) < VERDICT_MIN_SAMPLES:
        return f'fewer than {VERDICT_MIN_SAMPLES} sessions on a side'
    if before.value is None or after.value is None:
        return f'{BACKLOG_GAP} its baseline'
    return None


UNKNOWN, MOVED, NOT_MOVED = 'unknown', 'real change', 'within noise'   # the state of a Change, and its verdict word
LEVELS = {permutation.TWO_WAY: VERDICT_LEVEL, permutation.WORSE: GUARD_LEVEL}   # the level of each direction

# The answer of real_change: `state` (UNKNOWN, MOVED or NOT_MOVED); `chance` is chance alone in the
# direction, None when UNKNOWN; `opposed` is True when chance alone is at the level or less but the
# tested change (the statistic of the per-session values since, minus before) goes against the shown
# change (left-out sightings made the shown one).
Change = namedtuple('Change', 'state chance opposed')


def real_change(before, after, statistic, direction=permutation.TWO_WAY):
    """The Change from the Sample `before` to the Sample `after` under `statistic` of the per-session
    values (never Sample.value, which also counts what was left out). UNKNOWN without enough
    sessions (why_unknown). MOVED only when chance alone in `direction` (permutation.chance_alone) is
    the level of the direction (LEVELS) or less, the tested change goes the way of the shown change,
    and the shown change is VERDICT_MIN_CHANGE or more; from a zero baseline any change meets it."""
    if why_unknown(before, after):
        return Change(UNKNOWN, None, False)
    chance = permutation.chance_alone(before.values, after.values, statistic, direction)
    shift = statistic(after.values) - statistic(before.values)
    shown = after.value - before.value
    low = chance <= LEVELS[direction]
    big = shown != 0 if before.value == 0 else abs(shown) / abs(before.value) >= VERDICT_MIN_CHANGE
    return Change(MOVED if low and shift * shown > 0 and big else NOT_MOVED, chance, low and shift * shown < 0)


def change_text(recent, previous, statistic):
    """The end of a trend line: empty below VERDICT_MIN_SAMPLES sessions in either window, else the
    relative change (none from 0 to 0) in brackets and the verdict word of real_change. Each of
    `recent` and `previous` is a Sample."""
    found = real_change(previous, recent, statistic)
    if found.state == UNKNOWN:
        return ''
    text = relative_change(recent.value, previous.value)
    return f'{f" ({text})" if text else ""} → {found.state}'


def trends_section(context):
    overrides, build_skills = context.session_kinds, profile.build_skills(context.profile)
    by_kind = {kind: ([], []) for kind in SESSION_KINDS}
    for index, group in enumerate(windows(context)):
        for row in group:
            by_kind[session_kind(row, overrides, build_skills, context.user_config)][index].append(row)
    lines = []
    for kind in SESSION_KINDS:
        now_rows, before_rows = by_kind[kind]
        if not now_rows and not before_rows:
            continue
        lines.append(f'**{kind}**')
        for label, measure, statistic in METRICS:
            show = size if measure is weighted_tokens else partial(plain, statistic=statistic)
            now, before = (sample(statistic, Window(measured(rows, measure))) for rows in (now_rows, before_rows))
            lines.append(f'- {label} {shown(now.value, show)} (n={now.n}) vs '
                         f'{shown(before.value, show)} (n={before.n}){change_text(now, before, statistic)}')
    if not lines:
        return []
    return [f'## Trends: last {TREND_WINDOW_DAYS} days vs the {TREND_WINDOW_DAYS} before {statistics_note()}'] + lines


def top_skills_section(context):
    recent, _ = windows(context)
    totals, sessions = {}, {}
    for row in recent:
        table = row.get('tokens_by_skill')
        for name, bucket in (table.items() if isinstance(table, dict) else ()):
            value = number(bucket.get('weighted')) if isinstance(bucket, dict) else None
            if value:
                totals[name] = totals.get(name, 0) + value
                sessions[name] = sessions.get(name, 0) + 1
    if not totals:
        return []
    top = sorted(totals, key=lambda name: (-totals[name], name))[:DIGEST_TOP_SKILLS]
    return [f'## Top skills by weighted tokens (last {TREND_WINDOW_DAYS} days)'] + [
        f'- {name}  {size(totals[name])} ({sessions[name]} session{"" if sessions[name] == 1 else "s"})'
        for name in top]


def experiment_line(context, anomaly):
    """One experiment as a list line: anomaly, target, metric, then the check date, or for a
    switch-over with a fix date its progress (switch_over_progress) in place of it."""
    experiment = anomaly.experiment
    head = f'- {anomaly.signature} · {anomaly.target or "no target"} · {experiment.metric or "no metric"}'
    fix_day = fix_date(anomaly)
    if experiment.skill and fix_day is not None:
        return f'{head} · {switch_over_progress(context, fix_day, experiment)}'
    return f'{head} · check by {experiment.check_by or "?"}'


def switch_over_progress(context, fix_day, experiment):
    """`n/20 <skill> sessions, m fall-backs` since the fix (fix_windows, fall_backs): a stalled
    switch-over shows here, since its check date never makes it due (ADR-0013)."""
    sessions = len(fix_windows(context, fix_day, experiment.kind, experiment.skill)[1])
    skipped = len(fall_backs(context, fix_day, experiment.kind, experiment.skill))
    return (f'{sessions}/{EXPERIMENT_CHECK_SESSIONS} {experiment.skill} sessions, '
            f'{skipped} fall-back{"" if skipped == 1 else "s"}')


# ---------- experiments: the fix windows and "due" ----------

def fix_window_days(fix_day, today, skill=''):
    """((first, last) baseline days, (first, last) days since the fix) for fix_windows. With a
    `skill` (a switch-over) the old side runs on to today, beside the new one."""
    first = fix_day - timedelta(days=BASELINE_DAYS)
    return ((first, today if skill else fix_day - timedelta(days=1)), (fix_day + timedelta(days=1), today))


OLD, NEW, FALL_BACK = 'old', 'new', 'fall-back'   # the sides of a switch-over session (skill_side)


def skill_side(context, row, skill):
    """The side of one session in a switch-over to `skill` (ADR-0013), each skill it used read by
    metrics.skills_used_each: NEW when it ran the skill and nothing else that a profile.build_skills
    name matches, FALL_BACK when another skill it ran matches one (a bare `build` in build_skills
    matches `other:build` beside `anomaly:build`), else OLD."""
    used = metrics.skills_used_each(row)
    if not any(skill in forms for forms in used):
        return OLD
    others = set(profile.build_skills(context.profile)) - {skill}
    return FALL_BACK if any(others & forms for forms in used if skill not in forms) else NEW


def fix_windows(context, fix_day, kind='', skill=''):
    """(baseline rows, rows since the fix) around a fix that landed on `fix_day`: the BASELINE_DAYS
    days before the fix day, and the days after it up to today, in the clock of context.now.
    The fix day itself is in neither: a date cannot say whether a session came before the fix or
    after it. With a `kind`, only sessions of that kind (context_session_kind) are kept.
    With a `skill` (a switch-over, ADR-0013) the skill splits, not the date: before is every OLD
    session (skill_side) of both windows, so the old skill's sessions beside the new one count;
    after is the NEW sessions since the fix. A FALL_BACK, and a NEW session before the fix day
    (a dogfood run), is in neither."""
    (before_first, before_last), (after_first, _) = fix_window_days(fix_day, context.today)
    before, after = [], []
    for day, row in rows_in_window(context, before_first):
        if kind and context_session_kind(context, row) != kind:
            continue
        side = skill_side(context, row, skill) if skill else None
        if day <= before_last:
            if side in (None, OLD):
                before.append(row)
        elif day >= after_first:
            if side in (None, NEW):
                after.append(row)
            elif side == OLD:
                before.append(row)
    return before, after


def fall_backs(context, fix_day, kind, skill):
    """The sessions since the fix that ran `skill` beside another build skill (skill_side)."""
    return [row for row in fix_windows(context, fix_day, kind)[1] if skill_side(context, row, skill) == FALL_BACK]


def experiment_due(context, anomaly):
    """Why the anomaly's experiment is due, or None. The one owner of "due" for the digest, the
    nudge and calibrate. Due means the fix has landed (`fixed_by` is set), and then either
      - no result yet, and the check date has come (records.is_due: DUE_BY_DATE), or
        EXPERIMENT_CHECK_SESSIONS sessions of the experiment's kind came after the fix day (this
        needs a kind and a date-first `fixed_by`, records.fix_date); or
      - the result is `inconclusive` and its moved check date has come (DUE_FOR_DECISION).
    A switch-over (an experiment with a `skill`, ADR-0013) is due by sessions only: the check date
    alone never makes it due, and only the after side of fix_windows, the sessions that ran the
    new skill, counts. An adopt draft (no `fixed_by`) is never due."""
    experiment = anomaly.experiment
    if experiment is None or not anomaly.fixed_by.strip():
        return None
    if experiment.result == 'inconclusive':
        moved = is_date(experiment.check_by) and date.fromisoformat(experiment.check_by) <= context.today
        return DUE_FOR_DECISION if moved else None
    if is_due(anomaly, context.today) and not experiment.skill:
        return DUE_BY_DATE
    fix_day = fix_date(anomaly)
    if experiment.result or not experiment.kind or fix_day is None:
        return None
    sessions = len(fix_windows(context, fix_day, experiment.kind, experiment.skill)[1])
    if sessions >= EXPERIMENT_CHECK_SESSIONS:
        return f'{sessions} {experiment.skill or experiment.kind} sessions since the fix'
    return None


def due_experiments(context):
    """(anomaly, reason) for every due experiment, the earliest check date first."""
    due = ((a, experiment_due(context, a)) for a in context.anomalies)
    return sorted(((a, reason) for a, reason in due if reason),
                  key=lambda item: (item[0].experiment.check_by, item[0].signature))


STALLED = f'stalled: due only after {EXPERIMENT_CHECK_SESSIONS} new-skill sessions'


def stalled_switch_overs(context):
    """Switch-overs whose check date has come but that are not due (fewer than
    EXPERIMENT_CHECK_SESSIONS new-skill sessions, ADR-0013), the earliest check date first, the
    same order as due_experiments: the check date only orders them, it never makes them due."""
    stalled = (a for a in context.anomalies
               if a.experiment is not None and a.experiment.skill and is_due(a, context.today)
               and experiment_due(context, a) is None)
    return sorted(stalled, key=lambda a: (a.experiment.check_by, a.signature))


def experiments_due_section(context):
    """The due experiments, then the stalled switch-overs, so a switch-over that never reaches its
    sessions still shows (with its progress, experiment_line)."""
    lines = [experiment_line(context, a) + ('' if reason == DUE_BY_DATE else f' · {reason}')
             for a, reason in due_experiments(context)]
    lines += [f'{experiment_line(context, a)} · {STALLED}' for a in stalled_switch_overs(context)]
    return ['## Experiments due'] + lines if lines else []


def experiment_results_section(context):
    """The current experiments counted by result, one line, always shown: `unproven` is its own count,
    never added to `keep`, and a blank result is `pending`. An anomaly without an experiment, and an
    archived earlier experiment, are not counted."""
    counts = Counter(a.experiment.result for a in context.anomalies if a.experiment is not None)
    first = ('keep', 'unproven')   # the two outcomes to read first; any other result follows, so a new one shows
    results = first + tuple(result for result in EXPERIMENT_RESULTS if result not in first)
    parts = [f'{result} {counts[result]}' for result in results] + [f'pending {counts[""]}']
    return ['## Experiment results', '- ' + ' · '.join(parts)]


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ''


def reverted_section(context):
    reverted = [a for a in context.anomalies if a.experiment is not None and a.experiment.result == 'revert']
    lines = []
    for anomaly in sorted(reverted, key=lambda a: (a.experiment.check_by, a.signature)):
        fix = first_line(anomaly.proposed_fix)
        if len(fix) > REVERTED_FIX_CHARS:
            fix = fix[:REVERTED_FIX_CHARS].rstrip() + '…'
        reason = anomaly.experiment.reason
        lines.append(experiment_line(context, anomaly) + (f' · fix: {fix}' if fix else '')
                     + (f' · reason: {reason}' if reason else ''))
    for anomaly in sorted(context.anomalies, key=lambda a: a.signature):
        lines += [f'- {anomaly.signature} · {anomaly.target or "no target"} · earlier: {line}'
                  for line in archived_reverts(anomaly)]
    return ['## Tried and reverted'] + lines if lines else []

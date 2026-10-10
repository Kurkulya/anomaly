"""calibrate: the deterministic half of the weekly review. The skill talks with the user; this
module ranks, records and judges, so the numbers never depend on the conversation.

  plan     housekeeping (near-duplicates, stale anomalies, due experiments, unused plugin skills,
           each from its owner's digest section) and the open problems grouped by scope
  effort   set the effort of one or more anomalies (`--set signature=S`)
  declare  write the experiment BEFORE the change: expect, one metric, one guard, check_by, kind,
           and for a switch-over the new skill (ADR-0013)
  fix      record the change AFTER it landed: `fixed_by` = `YYYY-MM-DD · <ref>`, status fixed; with
           `--addendum` the CLI makes the change itself, a line in an addenda file in home (ADR-0021)
  verify   judge a due experiment from the numbers and write its result
  decide   the user's result for an experiment the numbers could not judge
  close    mark anomalies wontfix (stale ones)
  merge    fold a near-duplicate into the anomaly that stays

Batches. Open and reopened problems are grouped: a `repo:` or `plugin:` scope is one batch;
any other scope (`global` and the like) is split by target, and problems without a target share one
`untargeted` batch. The groups are ranked by the summed score of the problems that can be fixed
now; inside a group the order is score, then the lower effort (S, M, L, then not set). A
workflow-category problem can be fixed only with score WORKFLOW_MIN_SCORE or more, or the
highest impact (workflow_gate): below that it is shown
as waiting and adds nothing to the sum. A problem whose target already had a reverted experiment
says so, and a target that a win with 2 or more sightings is about is marked as protected
from removal (flags.protected_by_win). With no plugin checkout (gitrepo.plugin_repo is None), a problem
whose target is a skill or agent of this plugin names its addenda file as the fix home (fix_home); a
skill in addenda.NO_ADDENDA has none, and any other part of the plugin is an upstream defect.

Declaring (ADR-0002). An experiment is declared before the change: one metric, one guard from
QUALITY_GUARDS, and `declared_on` = today; `fix` refuses a fix dated before it, and sets a blank
check_by to the fix day + EXPERIMENT_CHECK_DAYS. A target that is this plugin (`<plugin>:<skill>` in
any case, or a path inside the plugin folder or its checkout) needs --approved.

The metric registry and the verdict live in verdict.py.
"""
import copy
import sys
from collections import Counter, namedtuple
from datetime import date, timedelta
from pathlib import Path

from . import addenda, digest, flags, gitrepo, observe, privacy, profile, records, scans, trends, verdict
from .constants import (BASELINE_DAYS, COMMIT_SCOPE, EFFORTS, EXPERIMENT_CHECK_DAYS, EXPERIMENT_CHECK_SESSIONS,
                        GUARD_HELP, IMPACT_RANGE, QUALITY_GUARDS, SESSION_KINDS, SIGHTING_MAX_CHARS,
                        WORKFLOW_CATEGORIES, WORKFLOW_MIN_SCORE)
from .files import RecordError

MERGED_HEADING = 'Merged'
WHOLE_SCOPES = ('repo:', 'plugin:')   # scopes that are one batch each; any other scope is split by target
UNTARGETED = 'untargeted'
UPSTREAM_DEFECT = 'upstream defect: not one skill or agent of the plugin, so no addendum; report it upstream'
COMMIT_PREFIX = f'chore({COMMIT_SCOPE}): calibrate '


# ---------- batches ----------

ScopeBatch = namedtuple('ScopeBatch', 'scope total problems')


def workflow_gate(anomaly):
    """Why a workflow-category fix must wait, or None when it may be made."""
    if anomaly.category not in WORKFLOW_CATEGORIES or anomaly.score >= WORKFLOW_MIN_SCORE \
            or anomaly.impact == IMPACT_RANGE[1]:
        return None
    return f'a workflow fix needs score {WORKFLOW_MIN_SCORE} or more, or impact {IMPACT_RANGE[1]}'


def effort_rank(anomaly):
    return EFFORTS.index(anomaly.effort) if anomaly.effort in EFFORTS else len(EFFORTS)


def batch_key(anomaly):
    """The batch a problem belongs to (see the module doc)."""
    scope, target = anomaly.scope.strip(), anomaly.target.strip()
    if scope.startswith(WHOLE_SCOPES):
        return scope
    return f'target: {target}' if target else UNTARGETED


def batches(context):
    """Open and reopened problems in batches, best batch first."""
    groups = {}
    for anomaly in records.ranked(context.anomalies):
        if anomaly.kind == 'problem':
            groups.setdefault(batch_key(anomaly), []).append(anomaly)
    found = []
    for scope, problems in groups.items():
        problems.sort(key=lambda a: (-a.score, effort_rank(a), a.signature))
        total = sum(a.score for a in problems if workflow_gate(a) is None)
        found.append(ScopeBatch(scope, total, problems))
    return sorted(found, key=lambda batch: (-batch.total, batch.scope))


def reverted_attempts(anomalies):
    """(anomaly, text) for every reverted experiment, the current one and the archived ones."""
    found = []
    for anomaly in anomalies:
        experiment = anomaly.experiment
        if experiment is not None and experiment.result == 'revert':
            day = records.fix_date(anomaly)
            text = f'{experiment.metric}, fixed {day.isoformat() if day else "?"}'
            found.append((anomaly, text + (f'; {experiment.reason}' if experiment.reason else '')))
        found += [(anomaly, line) for line in records.archived_reverts(anomaly)]
    return found


def tried_before(anomalies, anomaly):
    """The reverted attempts on this anomaly or on its target."""
    target = anomaly.target.strip()
    return [f'{other.signature} reverted ({text})' for other, text in reverted_attempts(anomalies)
            if other.signature == anomaly.signature or (target and other.target.strip() == target)]


def problem_line(context, anomaly, plugin):
    """The plan's line of one problem; `plugin` is gitrepo.plugin_repo's answer."""
    marks = []
    gate = workflow_gate(anomaly)
    if gate:
        marks.append(f'waits: {gate}')
    experiment = anomaly.experiment
    if experiment is not None and not experiment.result and not anomaly.fixed_by.strip():
        marks.append(f'experiment drafted (metric {experiment.metric or "?"})')
    marks += [f'tried before: {text}' for text in tried_before(context.anomalies, anomaly)]
    target = anomaly.target.strip()
    wins = flags.protected_by_win(context, target, target) if target else 0
    if wins:
        marks.append(f'protected: a win with {wins} sightings is about this target; never remove it '
                     'without an explicit override')
    home = fix_home(context, target, plugin)
    if home:
        marks.append(home)
    head = (f'  - {anomaly.score} {anomaly.signature} · {anomaly.category} · effort {anomaly.effort or "?"}'
            f' · {anomaly.target or "no target"}')
    return ' · '.join([head] + marks)


HOUSEKEEPING = (flags.near_duplicates, flags.stale, trends.experiments_due_section, flags.unused_skills)


def recent_sessions_by_kind(context):
    """Kind -> number of sessions that started in the last BASELINE_DAYS days."""
    since = trends.window_start(context.today, BASELINE_DAYS)
    return Counter(trends.context_session_kind(context, row) for _, row in trends.rows_in_window(context, since))


def plan_lines(context):
    lines = ['## Housekeeping']
    tidy = digest.render(context, HOUSEKEEPING)
    lines += [f'#{line}' if line.startswith('## ') else line for line in tidy] or ['- nothing to tidy']
    lines += ['', '## Batches (summed score of the problems that can be fixed now)']
    found = batches(context)
    plugin = gitrepo.plugin_repo(context.plugin_root, context.profile)
    for number, batch in enumerate(found, start=1):
        count = flags.plural(len(batch.problems), 'problem')
        lines.append(f'{number}. {batch.scope} · score {batch.total} · {count}')
        lines += [problem_line(context, a, plugin) for a in batch.problems]
    if not found:
        lines.append('- no open problems')
    counts = recent_sessions_by_kind(context)
    lines += ['', 'metrics: ' + ', '.join(verdict.METRIC_NAMES), 'guards: ' + ', '.join(QUALITY_GUARDS),
              f'sessions in the last {BASELINE_DAYS} days: '
              + (', '.join(f'{kind} {counts[kind]}' for kind in SESSION_KINDS if counts[kind]) or 'none')]
    return lines


# ---------- writing ----------

def find(anomalies, signature):
    anomaly = anomalies.get(signature)
    if anomaly is None:
        raise RecordError(f'no anomaly {signature!r} in home')
    return anomaly


def check_date(label, value, today):
    if not records.is_date(value):
        raise RecordError(f'{label}: check_by {value!r} must be a date like {today.isoformat()}')
    if date.fromisoformat(value) < today:
        raise RecordError(f'{label}: check_by {value} has passed')
    return value


def only_one(values, what):
    values = [v for v in (values or []) if v is not None]
    if len(values) > 1:
        raise RecordError(f'name exactly one {what}, not {len(values)}: one change, one {what}')
    return values[0] if values else None


PluginPart = namedtuple('PluginPart', 'name agent unit')   # unit: the skill folder or agent file, else None


def plugin_part(context, target, plugin):
    """The part of this plugin a target is, or None when it is not this plugin. A target is this plugin
    when it is a path inside the plugin folder or its checkout's plugin folder (flags.target_path), or
    `<plugin name>:...` (flags.names_this_plugin). The part is a skill (`<plugin>:<skill>` or a path inside
    `skills/<skill>/`), an agent (`<plugin>:<agent>` or `agents/<agent>.md`), or else (name and unit None)
    plugin code or docs, or a `<plugin>:...` that names no skill or agent. After `<plugin>:` only the first
    word counts, so `anomaly:review step 10` is the review skill. `plugin` is gitrepo.plugin_repo's answer."""
    target = target.strip()
    if not target:
        return None
    root = Path(context.plugin_root)
    if flags.is_path(target):
        found = flags.target_path(context, target, plugin)
        folders = [root] + ([Path(plugin[1])] if plugin else [])
        base = next((f for f in folders if found is not None and found.resolve().is_relative_to(f.resolve())), None)
        if base is None:
            return None
        parts = found.resolve().relative_to(base.resolve()).parts
        if len(parts) >= 2 and parts[0] == 'skills' and (base / 'skills' / parts[1] / flags.SKILL_FILE).is_file():
            return PluginPart(parts[1], False, base / 'skills' / parts[1])
        if len(parts) == 2 and parts[0] == addenda.AGENTS and found.suffix == '.md' and found.is_file():
            return PluginPart(found.stem, True, found)
        return PluginPart(None, False, None)
    qualifier, colon, name = target.rpartition(':')
    if not (colon and flags.names_this_plugin(context, qualifier, plugin)):
        return None
    name = (name.split() or [''])[0]
    if (root / 'skills' / name / flags.SKILL_FILE).is_file():
        return PluginPart(name, False, root / 'skills' / name)
    if (root / addenda.AGENTS / f'{name}.md').is_file():
        return PluginPart(name, True, root / addenda.AGENTS / f'{name}.md')
    return PluginPart(None, False, None)


def changes_this_plugin(context, target):
    """True when the target is this plugin (plugin_part)."""
    if not target.strip():
        return False
    return plugin_part(context, target, gitrepo.plugin_repo(context.plugin_root, context.profile)) is not None


def takes_no_addenda(part):
    return not part.agent and part.name in addenda.NO_ADDENDA


def fix_home(context, target, plugin):
    """The plan's fix-home mark of a target with no plugin checkout (ADR-0021), or None: the addenda file
    (relative to home), or why there is none. With a checkout (`plugin` set) there is no mark."""
    part = None if plugin is not None else plugin_part(context, target, plugin)
    if part is None:
        return None
    if part.unit is None:
        return UPSTREAM_DEFECT
    if takes_no_addenda(part):
        return f'fix home: none, {part.name} takes no addenda'
    home = Path(context.home)
    return f'fix home: {addenda.addendum_path(home, part.name, part.agent).relative_to(home).as_posix()}'


def switch_over_text(kind, skill):
    """Which sessions a switch-over to `skill` compares (trends.fix_windows), as declare, fix and verify say it."""
    return (f'{kind} sessions since the fix that ran {skill} and no other build skill, against the {kind} '
            f'sessions that did not run it, from {BASELINE_DAYS} days before the fix to today; a fall-back '
            f'({skill} beside another build skill), the fix day and a sighting of no session on a side are '
            'in neither')


def writable(context):
    """signature -> Anomaly from a strict Context, for a command that reads the context and then
    writes: home is read once, and the records are copied so the context itself is never changed."""
    return {a.signature: copy.deepcopy(a) for a in context.anomalies}


Addendum = namedtuple('Addendum', 'path unit line')   # the addenda file, the skill folder or agent file, the rule


def checked_addendum(context, anomaly, label, line, environ):
    """The addendum `fix --addendum` writes for this anomaly, after its checks: the target is one skill
    (not one in addenda.NO_ADDENDA) or agent of this plugin, and the line is one clean line (privacy.check_text)
    that no live deny rule fully matches (scans.deny_regex)."""
    target = anomaly.target.strip()
    part = plugin_part(context, target, gitrepo.plugin_repo(context.plugin_root, context.profile))
    if part is None or part.unit is None:
        raise RecordError(f'{label}: an addendum adds to one skill or agent of this plugin; the target '
                          f'{target or "(none)"} is not `<plugin>:<skill>`, `<plugin>:<agent>` or a path inside one '
                          'skill folder or agent file')
    if takes_no_addenda(part):
        raise RecordError(f'{label}: {part.name} takes no addenda')
    line = line.strip()
    if not line:
        raise RecordError(f'{label}: --addendum is empty; give the rule in one line')
    privacy.check_text(label, 'addendum', line)
    for rule in scans.deny_rules(scans.settings_files(environ, sys.platform, Path.home())):
        regex = scans.deny_regex(rule)
        if regex is not None and regex.fullmatch(line):
            raise RecordError(f'{label}: the addendum is a whole command that the deny rule {rule} denies; '
                              'write the rule in words')
    return Addendum(addenda.addendum_path(context.home, part.name, part.agent), part.unit, line)


def write_addendum(home, signature, addendum):
    """Append the tagged line to its addenda file and commit that file alone; returns the lines to print."""
    tagged = addenda.append_line(addendum.path, addendum.line, signature, addenda.stamp(addendum.unit))
    return [f'addendum: {tagged}',
            observe.commit_home(home, [addendum.path], COMMIT_PREFIX + f'addendum for {signature}')]


# ---------- the subcommands ----------

def run_plan(args, environ):
    context = digest.context_from_args(args, environ)
    message = profile.missing_message(context.profile)
    lines = ([message] if message else []) + [f'profile file: {context.profile.path}', ''] + plan_lines(context)
    print('\n'.join(lines))
    return 0


def run_effort(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    home, anomalies = context.home, writable(context)
    changed = []
    for pair in args.set:
        signature, equals, effort = pair.partition('=')
        if not equals or effort not in EFFORTS:
            raise RecordError(f'--set {pair!r}: write signature=effort, the effort one of {", ".join(EFFORTS)}')
        find(anomalies, signature).effort = effort
        changed.append(signature)
    print('\n'.join(f'effort: {s} is {anomalies[s].effort}' for s in dict.fromkeys(changed)))
    print(observe.save_anomalies(home, args.today, anomalies, changed, COMMIT_PREFIX + 'set effort'))
    return 0


def run_declare(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    home, today = context.home, args.today
    anomalies = writable(context)
    anomaly = find(anomalies, args.signature)
    label = f'experiment for {anomaly.signature}'
    if anomaly.kind != 'problem':
        raise RecordError(f'{label}: only a problem gets a fix; {anomaly.signature} is a {anomaly.kind}')
    if not anomaly.active:
        raise RecordError(f'{label}: the anomaly is {anomaly.status}')
    gate = workflow_gate(anomaly)
    if gate:
        raise RecordError(f'{label}: {anomaly.category} is a workflow category, score {anomaly.score}; {gate}')
    current = anomaly.experiment
    if current is not None and not current.result and anomaly.fixed_by.strip():
        raise RecordError(f'{label}: an experiment is in flight since {anomaly.fixed_by}; verify it (or decide) first')
    if changes_this_plugin(context, anomaly.target) and not args.approved:
        raise RecordError(f'{label}: {anomaly.target} is part of this plugin; change it only after the '
                          "user's explicit yes, then pass --approved")
    draft = current if current is not None and not current.result else records.Experiment()
    expect = (args.expect if args.expect is not None else draft.expect).strip()
    metric = only_one(args.metric, 'primary metric') or draft.metric
    guard = only_one(args.guard, 'guard metric') or draft.guard
    if not expect:
        raise RecordError(f'{label}: --expect is required: the effect you expect, in one line')
    if not metric.strip():
        raise RecordError(f'{label}: --metric is required: exactly one primary metric')
    if not guard.strip():
        raise RecordError(f'{label}: --guard is required: exactly one guard metric that must not get worse')
    metric, guard = verdict.experiment_metrics(label, metric, guard)
    privacy.check_text(label, 'expect', expect, SIGHTING_MAX_CHARS)
    kind = args.kind if args.kind is not None else draft.kind
    if kind not in ('',) + SESSION_KINDS:
        raise RecordError(f'{label}: kind {kind!r} must be one of {", ".join(SESSION_KINDS)}')
    skill = (args.skill if args.skill is not None else draft.skill).strip()
    build_skills = profile.build_skills(context.profile)
    if skill and kind != 'build':
        named = '--skill' if args.skill is not None else (f'the drafted skill {skill} (clear it with '
                                                         "--skill '')")
        raise RecordError(f'{label}: {named} needs --kind build: a switch-over compares build sessions')
    if skill and skill not in build_skills:
        raise RecordError(f"{label}: --skill {skill} is not in the profile's build_skills "
                          f'({", ".join(build_skills) or "none"}); add it beside the old skill first')
    check_by = check_date(label, args.check_by, today) if args.check_by else (
        draft.check_by if records.is_date(draft.check_by) and draft.check_by >= today.isoformat() else '')
    if args.effort is not None:
        if args.effort not in EFFORTS:
            raise RecordError(f'{label}: effort {args.effort!r} must be one of {", ".join(EFFORTS)}')
        anomaly.effort = args.effort
    earlier = tried_before(anomalies.values(), anomaly)
    if (current is not None and current.result) or anomaly.fixed_by.strip():
        records.archive_experiment(anomaly)
    anomaly.experiment = records.Experiment(expect=expect, metric=metric, guard=guard, kind=kind, skill=skill,
                                            declared_on=today.isoformat(), check_by=check_by)
    lines = [f'declared: {anomaly.signature} · metric {metric} · guard {guard} · kind {kind or "any"} · '
             + (f'skill {skill} · due after {EXPERIMENT_CHECK_SESSIONS} {skill} sessions' if skill else
                f'check by {check_by or f"the fix day + {EXPERIMENT_CHECK_DAYS} days"}')]
    if skill:
        lines.append(f'switch-over: {switch_over_text(kind, skill)}')
    if kind:
        sessions = recent_sessions_by_kind(context)[kind]
        lines.append(f'kind: {sessions} {kind} sessions in the last {BASELINE_DAYS} days'
                     + ('' if sessions >= EXPERIMENT_CHECK_SESSIONS else
                        f'; fewer than {EXPERIMENT_CHECK_SESSIONS}, so before and after will be thin: '
                        "leave --kind out (declare again with --kind '') unless the user wants this kind"))
    sighting_metrics = [name for name in (metric, guard) if verdict.is_sighting_metric(name)]
    judgeable = verdict.first_judgeable_fix_day(context)
    if (sighting_metrics and not verdict.is_rare_event(metric)
            and (judgeable is None or judgeable > today)):
        began = verdict.backlog_start(context)
        lines.append(f'backlog: {" and ".join(sighting_metrics)} count sightings, and '
                     + (f'the backlog starts on {began}, so a fix can be judged on them only from {judgeable}'
                        if began else 'the backlog has no sightings yet, so they cannot be judged')
                     + '; until then the verdict stays inconclusive. Consider the guard interrupts, '
                       'and a number such as active minutes as the metric')
    lines += [f'tried before: {text}' for text in earlier]
    lines.append(observe.save_anomalies(home, today, anomalies, [anomaly.signature],
                                        COMMIT_PREFIX + f'declare {anomaly.signature}'))
    lines.append(f'next: make the change, then record it with `calibrate fix --signature {anomaly.signature} '
                 '--ref <commit or file>`')
    print('\n'.join(lines))
    return 0


def run_fix(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    home, today, anomalies = context.home, args.today, writable(context)
    anomaly = find(anomalies, args.signature)
    label = f'fix for {anomaly.signature}'
    experiment = anomaly.experiment
    if experiment is None or experiment.result:
        raise RecordError(f'{label}: no open experiment; declare one before the change (`calibrate declare`)')
    if anomaly.fixed_by.strip():
        raise RecordError(f'{label}: the fix is already recorded ({anomaly.fixed_by})')
    if not records.is_date(experiment.declared_on):
        raise RecordError(f'{label}: the experiment was not declared with `calibrate declare`; declare it first, '
                          'before the change')
    for value in (experiment.metric, experiment.guard):
        verdict.resolve_metric(value)
    day = date.fromisoformat(args.date) if args.date and records.is_date(args.date) else None
    if args.date and day is None:
        raise RecordError(f'{label}: --date {args.date!r} must be a date like {today.isoformat()}')
    day = day or today
    if day > today:
        raise RecordError(f'{label}: --date {day} is in the future')
    if day < date.fromisoformat(experiment.declared_on):
        raise RecordError(f'{label}: --date {day} is before the experiment was declared '
                          f'({experiment.declared_on}); a fix is declared before the change')
    addendum = None if args.addendum is None else checked_addendum(context, anomaly, label, args.addendum, environ)
    ref = args.ref if addendum is None else str(addendum.path)
    privacy.check_text(label, 'ref', ref.strip(), SIGHTING_MAX_CHARS)
    written = [] if addendum is None else write_addendum(home, anomaly.signature, addendum)
    anomaly.fixed_by = records.fixed_by_text(day, ref)
    anomaly.status = 'fixed'
    if not records.is_date(experiment.check_by):
        experiment.check_by = (day + timedelta(days=EXPERIMENT_CHECK_DAYS)).isoformat()
    if experiment.skill:
        lines = [f'fixed: {anomaly.signature} · fixed_by {anomaly.fixed_by} · due after '
                 f'{EXPERIMENT_CHECK_SESSIONS} {experiment.skill} sessions (the check date alone does not make a '
                 'switch-over due)', f'switch-over: {switch_over_text(experiment.kind, experiment.skill)}']
    else:
        lines = [f'fixed: {anomaly.signature} · fixed_by {anomaly.fixed_by} · check by {experiment.check_by}'
                 + (f' or after {EXPERIMENT_CHECK_SESSIONS} {experiment.kind} sessions' if experiment.kind else '')]
    lines.append(observe.save_anomalies(home, today, anomalies, [anomaly.signature],
                                        COMMIT_PREFIX + f'fix {anomaly.signature}'))
    print('\n'.join(written + lines))
    return 0


def write_result(anomaly, result, reason):
    anomaly.experiment.result = result
    anomaly.experiment.reason = reason
    if result == 'revert':
        anomaly.status = 'reopened'


def run_verify(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    anomalies = writable(context)
    seen = next((a for a in context.anomalies if a.signature == args.signature), None)
    if seen is None:
        raise RecordError(f'no anomaly {args.signature!r} in home')
    reason = trends.experiment_due(context, seen)
    if reason is None:
        raise RecordError(f'the experiment of {seen.signature} is not due')
    found = verdict.verdict(context, seen)
    roles = ('primary', 'guard', 'time before tokens')
    lines = [f'verify: {seen.signature} ({reason})']
    if seen.experiment.skill:
        lines.append(f'switch-over: {switch_over_text(seen.experiment.kind, seen.experiment.skill)}')
    lines += [verdict.reading_line(r, role) for r, role in zip(found.readings, roles)]
    if found.fall_backs is not None:
        lines.append(f'- fall-backs: {found.fall_backs} (in neither side)')
    if found.no_factor:
        lines.append(f'- sessions skipped for a model with no factor: {found.no_factor}')
    if found.no_meta:
        lines.append(f'- sessions skipped for a spawn without .meta.json: {found.no_meta}')
    if not verdict.is_rare_event(found.readings[0].name):
        lines.append(f'- {verdict.SIGHTINGS_SINCE_FIX}: {found.sightings_since}')
    on_fix_day = verdict.fix_day_line(seen, found)
    if on_fix_day:
        lines.append(on_fix_day)
    lines.append(f'result: {found.result} ({found.reason})')
    anomaly = anomalies[seen.signature]
    if found.result != 'inconclusive':
        write_result(anomaly, found.result, found.reason)
        reopened = '; the anomaly is reopened' if found.result == 'revert' else ''
        lines.append(f'written: result {found.result}{reopened}')
    elif reason == trends.DUE_FOR_DECISION:
        lines.append('still inconclusive after the moved check date: the user decides '
                     f'(`calibrate decide --signature {seen.signature} --result keep|revert`)')
        print('\n'.join(lines))
        return 0
    else:
        write_result(anomaly, 'inconclusive', found.reason)
        anomaly.experiment.check_by = (args.today + timedelta(days=EXPERIMENT_CHECK_DAYS)).isoformat()
        lines.append(f'written: result inconclusive; check date moved once, to {anomaly.experiment.check_by}')
    lines.append(observe.save_anomalies(context.home, args.today, anomalies, [anomaly.signature],
                                        COMMIT_PREFIX + f'verify {anomaly.signature}'))
    print('\n'.join(lines))
    return 0


def measurable(anomaly):
    try:
        verdict.resolve_metric(anomaly.experiment.metric)
        verdict.resolve_metric(anomaly.experiment.guard)
    except RecordError:
        return False
    return records.fix_date(anomaly) is not None


def run_decide(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    anomalies = writable(context)
    anomaly = find(anomalies, args.signature)
    reason = trends.experiment_due(context, anomaly)
    if reason is None:
        raise RecordError(f'the experiment of {anomaly.signature} is not due')
    if reason != trends.DUE_FOR_DECISION and measurable(anomaly):
        raise RecordError(f'the numbers can still judge {anomaly.signature}: run `calibrate verify` first')
    write_result(anomaly, args.result, 'decided by the user')
    print(f'decided: {anomaly.signature} result {args.result}' + ('; reopened' if args.result == 'revert' else ''))
    print(observe.save_anomalies(context.home, args.today, anomalies, [anomaly.signature],
                                 COMMIT_PREFIX + f'decide {anomaly.signature}'))
    return 0


def run_close(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    home, anomalies = context.home, writable(context)
    for signature in args.signature:
        anomaly = find(anomalies, signature)
        if not anomaly.active:
            raise RecordError(f'anomaly {signature} is already {anomaly.status}')
        anomaly.status = 'wontfix'
    print('\n'.join(f'closed: {s} is wontfix' for s in args.signature))
    print(observe.save_anomalies(home, args.today, anomalies, args.signature,
                                 COMMIT_PREFIX + 'close ' + ', '.join(args.signature)))
    return 0


def run_merge(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    home, anomalies = context.home, writable(context)
    kept, folded = find(anomalies, args.into), find(anomalies, args.source)
    if kept.signature == folded.signature or kept.kind != folded.kind or not (kept.active and folded.active):
        raise RecordError('merge needs two different open or reopened anomalies of the same kind')
    merged = records.merge_anomalies(kept, folded)
    if merged is not None:
        anomalies[kept.signature] = kept = merged
    folded.status = 'wontfix'
    folded.sections.append((MERGED_HEADING, f'Merged into {kept.signature} on {args.today.isoformat()}.'))
    print(f'merged: {folded.signature} into {kept.signature} (seen {kept.occurrences} times, score {kept.score})')
    print(observe.save_anomalies(home, args.today, anomalies, [kept.signature, folded.signature],
                                 COMMIT_PREFIX + f'merge {folded.signature} into {kept.signature}'))
    return 0


def register(commands, common):
    command = commands.add_parser('calibrate', help='plan, declare, fix and verify experiments for the weekly review')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    folders = digest.folder_options()

    def action(name, handler, help_text):
        parser = actions.add_parser(name, parents=[common, folders], help=help_text)
        parser.set_defaults(handler=handler)
        return parser

    action('plan', run_plan, 'housekeeping and the open problems grouped by scope')
    effort = action('effort', run_effort, 'set the effort of anomalies')
    effort.add_argument('--set', action='append', required=True, help='signature=S|M|L (repeatable)')
    declare = action('declare', run_declare, 'record an experiment before the change')
    declare.add_argument('--signature', required=True)
    declare.add_argument('--expect', help='the effect you expect, one line')
    declare.add_argument('--metric', action='append', help='exactly one primary metric (see `plan`)')
    declare.add_argument('--guard', action='append',
                         help=GUARD_HELP)
    declare.add_argument('--kind', help=f'the session kind it is measured on: {", ".join(SESSION_KINDS)}')
    declare.add_argument('--skill', help='a switch-over (needs --kind build): the new skill, named in build_skills '
                                         'beside the old one; compares the sessions that ran it with those that did not')
    declare.add_argument('--check-by', dest='check_by',
                         help=f'date; default: set by `fix` to the fix day + {EXPERIMENT_CHECK_DAYS} days')
    declare.add_argument('--effort', help=f'{", ".join(EFFORTS)}')
    declare.add_argument('--approved', action='store_true',
                         help="only after the user's explicit yes to changing this plugin")
    fix = action('fix', run_fix, 'record the change after it landed')
    fix.add_argument('--signature', required=True)
    change = fix.add_mutually_exclusive_group(required=True)
    change.add_argument('--ref', help='the commit or file that holds the change')
    change.add_argument('--addendum', help="the rule line to append to the target skill's or agent's addenda file "
                                           'in home; that file becomes the ref')
    fix.add_argument('--date', help='the day it landed (default today)')
    verify = action('verify', run_verify, 'judge a due experiment and write its result')
    verify.add_argument('--signature', required=True)
    decide = action('decide', run_decide, "write the user's result for an experiment the numbers cannot judge")
    decide.add_argument('--signature', required=True)
    decide.add_argument('--result', required=True, choices=('keep', 'revert'))
    close = action('close', run_close, 'mark anomalies wontfix')
    close.add_argument('--signature', action='append', required=True)
    merge = action('merge', run_merge, 'fold a near-duplicate into the anomaly that stays')
    merge.add_argument('--into', required=True, help='the anomaly that stays')
    merge.add_argument('--from', dest='source', required=True, help='the anomaly folded in (becomes wontfix)')


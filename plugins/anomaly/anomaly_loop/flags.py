"""Digest sections that say what needs attention: needs-rework targets, stale and near-duplicate
anomalies, how each review lens performs, and plugin skills nobody uses.

Every section is `section(context) -> list[str]` and leaves the context alone (see digest.py).

Needs-rework. Candidates are the distinct, non-blank `target` values of all anomalies.
A target is flagged when it has CHURN_MIN_COMMITS or more commits in the last CHURN_WINDOW_DAYS
days in its git repository, or REWORK_MIN_OPEN_PROBLEMS or more open or reopened problems. A target
without a repository counts only the problems. Where the repository is:
  - a path (it has a separator, starts with `~`, or is absolute) is the repository that holds it;
    a relative path is looked up under the user config folder, then the plugin folder, then the
    root of the plugin's checkout (target_path);
  - `plugin:skill` is that plugin's skill (the name matched in any case, names_this_plugin),
    `skill` a skill of this plugin (checked first) or of
    the user config folder; a plugin skill's repository comes from gitrepo.plugin_repo, a user
    skill's from the user config folder, and the history counted is that skill's folder;
  - a bare file name that exists under the user config or plugin folder is a path.
Anything else (free text, another plugin's skill) has no repository.

Grace: a target is exempt from the commit criterion when it was created or rewritten in the last
CHURN_GRACE_DAYS days. This is read from the commit days of its history alone: the newest run of
activity (commits no more than CHURN_RUN_GAP_DAYS apart) began within the grace period. A target
whose first commit is recent starts a run, and so does a target that comes back after a quiet
spell with new work, so one rule covers "created" and "rewritten". Steady patching is one long
run, which is exactly what is flagged. A target with no history has no grace. The grace never
hides open problems: REWORK_MIN_OPEN_PROBLEMS or more open or reopened problems always flag the target.

Stale: open or reopened problems seen once whose last_seen is more than STALE_DAYS days
old are offered as wontfix. Wins are left out: a win is not closed as wontfix.

Near-duplicates: two open or reopened anomalies of the same kind are paired when they share a
non-blank target and category and their summaries or their proposed fixes overlap by at least
NEAR_DUPLICATE_MIN_TEXT_OVERLAP (words of four or more letters), or when their signatures, split
into words, overlap by at least NEAR_DUPLICATE_MIN_OVERLAP. Overlap is shared words over all words
of both. A shared target and category alone is not enough: one busy file collects distinct
problems. Pairs that share a record are
printed as one group, with every reason that joined it, at most FLAGS_SHOW groups.

Lens rates: accepted over accepted plus rejected, summed over every line of lenses.jsonl.

Unused plugin skills: a skill folder of this plugin (a folder with a SKILL.md) qualifies
when it has been in the plugin for the whole UNUSED_DAYS window (its first commit is on or before
the window's first day, read with gitrepo.first_commit_date) and no measured session in the window
used it. Use is read in metrics.skills_used as the plugin-qualified name `plugin:skill`, or as the
bare name `skill` (a slash command typed without the plugin) unless the user config folder has a
skill of that name, which the bare name could then mean. Nothing is judged unless the measured sessions cover the window. A skill
with a win of two or more sightings is shown as protected, not proposed. Hooks are not
counted: transcripts do not record them.
"""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from . import gitrepo, metrics, paths, records, trends
from .constants import (CHURN_GRACE_DAYS, CHURN_MIN_COMMITS, CHURN_RUN_GAP_DAYS, CHURN_WINDOW_DAYS,
                        FLAGS_SHOW, NEAR_DUPLICATE_MIN_OVERLAP, NEAR_DUPLICATE_MIN_TEXT_OVERLAP,
                        REWORK_MIN_OPEN_PROBLEMS, STALE_DAYS, UNUSED_DAYS)

TEXT_WORD = re.compile(r'[a-z][a-z0-9_]{3,}')
SKILL_FILE = 'SKILL.md'
SAME_TARGET = 'same target and category'
SIMILAR_SIGNATURES = 'similar signatures'
MANIFEST = Path('.claude-plugin') / 'plugin.json'


def plural(number, word):
    return f'{number} {word}' + ('' if number == 1 else 's')


# ---------- shared by the flag sections ----------

def plugin_skills(plugin_root):
    """Names of the plugin's skills: the folders under skills/ that hold a SKILL.md."""
    folder = Path(plugin_root) / 'skills'
    if not folder.is_dir():
        return []
    return sorted(item.name for item in folder.iterdir() if (item / SKILL_FILE).is_file())


def plugin_name(plugin_root, plugin_folder):
    """The plugin's name from its manifest, else the name of its folder."""
    try:
        name = json.loads((Path(plugin_root) / MANIFEST).read_text(encoding='utf-8')).get('name')
    except (OSError, ValueError, AttributeError):
        name = None
    return name if isinstance(name, str) and name else Path(plugin_folder).name


def is_user_skill(context, name):
    """True when the user config folder has a skill folder of this name."""
    return (Path(context.user_config) / 'skills' / name / SKILL_FILE).is_file()


def plugin_repo_notice(context):
    """The one line that says the plugin-skill checks are skipped, when the plugin has skills but no repository."""
    if plugin_skills(context.plugin_root) and gitrepo.plugin_repo(context.plugin_root, context.profile) is None:
        return [gitrepo.PLUGIN_REPO_SKIPPED]
    return []


# ---------- needs-rework ----------

def is_path(target):
    return '/' in target or '\\' in target or target.startswith('~')


def target_path(context, target, plugin):
    """The file or folder a path target names, or None. An absolute path (after `~`) is taken as it
    is; a relative one is the first that exists under the user config folder, the plugin folder,
    then the root of the plugin's checkout (`plugin` is gitrepo.plugin_repo's answer). The one
    owner of this lookup."""
    found = paths.expand(target)
    if found.is_absolute():
        return found
    bases = [Path(context.user_config), Path(context.plugin_root)] + ([Path(plugin[0])] if plugin else [])
    return next((base / found for base in bases if (base / found).exists()), None)


def names_this_plugin(context, qualifier, plugin):
    """True when `qualifier` (the part before `:` of a target) is this plugin's name, in any case.
    The name is the manifest's, else the plugin folder's (that of the checkout when there is one)."""
    folder = plugin[1] if plugin else context.plugin_root
    return qualifier.strip().lower() == plugin_name(context.plugin_root, folder).lower()


def resolve_target(context, target, plugin):
    """(repository, path to count) for a target, or None. `plugin` is gitrepo.plugin_repo's answer."""
    plugin_skill = Path(context.plugin_root) / 'skills'
    user_skill = Path(context.user_config) / 'skills'
    if is_path(target):
        path = target_path(context, target, plugin)
        repo = gitrepo.find_repo(path) if path else None
        return (repo, path) if repo else None
    qualifier, colon, name = target.rpartition(':')
    if colon:
        if plugin is None or not names_this_plugin(context, qualifier, plugin):
            return None
        return (plugin[0], plugin[1] / 'skills' / name) if (plugin_skill / name / SKILL_FILE).is_file() else None
    if (plugin_skill / name / SKILL_FILE).is_file():
        return (plugin[0], plugin[1] / 'skills' / name) if plugin else None
    if is_user_skill(context, name):
        repo = gitrepo.find_repo(user_skill / name)
        return (repo, user_skill / name) if repo else None
    for base in (Path(context.user_config), Path(context.plugin_root)):
        if (base / name).is_file():
            repo = gitrepo.find_repo(base / name)
            return (repo, base / name) if repo else None
    return None


def current_run_start(commit_days):
    """The first day of the newest run of activity: commits no more than CHURN_RUN_GAP_DAYS apart."""
    newest_first = sorted(commit_days, reverse=True)
    start = newest_first[0]
    for day in newest_first[1:]:
        if (start - day).days > CHURN_RUN_GAP_DAYS:
            break
        start = day
    return start


def needs_rework(context):
    plugin = gitrepo.plugin_repo(context.plugin_root, context.profile)
    since = trends.window_start(context.today, CHURN_WINDOW_DAYS)
    grace_from = trends.window_start(context.today, CHURN_GRACE_DAYS)
    problems = Counter(a.target.strip() for a in context.anomalies if a.kind == 'problem' and a.active)
    flagged = []
    for target in sorted({a.target.strip() for a in context.anomalies} - {''}):
        located = resolve_target(context, target, plugin)
        commits = gitrepo.commit_count(*located, since, context.today) if located else 0
        if commits >= CHURN_MIN_COMMITS:
            history = gitrepo.commit_dates(*located)
            if history and current_run_start(history) >= grace_from:
                commits = 0
        open_problems = problems[target]
        if commits >= CHURN_MIN_COMMITS or open_problems >= REWORK_MIN_OPEN_PROBLEMS:
            flagged.append((target, commits, open_problems))
    flagged.sort(key=lambda item: (-item[1], -item[2], item[0]))
    lines = []
    for target, commits, open_problems in flagged:
        reasons = []
        if commits >= CHURN_MIN_COMMITS:
            reasons.append(f'{commits} commits in {CHURN_WINDOW_DAYS} days')
        if open_problems >= REWORK_MIN_OPEN_PROBLEMS:
            reasons.append(plural(open_problems, 'open problem'))
        lines.append(f'- {target}: ' + ', '.join(reasons))
    return ['## Needs rework'] + lines if lines else []


# ---------- stale and near-duplicates ----------

def stale(context):
    lines = []
    for a in sorted(context.anomalies, key=lambda a: (a.last_seen, a.signature)):
        if not (a.active and a.kind == 'problem' and a.occurrences == 1 and records.is_date(a.last_seen)):
            continue
        age = (context.today - date.fromisoformat(a.last_seen)).days
        if age > STALE_DAYS:
            lines.append(f'- {a.signature}: seen once, last on {a.last_seen} ({age} days ago); offer wontfix')
    return ['## Stale anomalies'] + lines if lines else []


def signature_overlap(first, second):
    words_a, words_b = set(first.split('-')), set(second.split('-'))
    return len(words_a & words_b) / len(words_a | words_b)


def text_overlap(first, second):
    words_a, words_b = set(TEXT_WORD.findall(first.lower())), set(TEXT_WORD.findall(second.lower()))
    return len(words_a & words_b) / len(words_a | words_b) if words_a and words_b else 0.0


def shares_text(first, second):
    return max(text_overlap(first.summary, second.summary),
               text_overlap(first.proposed_fix, second.proposed_fix)) >= NEAR_DUPLICATE_MIN_TEXT_OVERLAP


def near_duplicates(context):
    live = sorted((a for a in context.anomalies if a.active), key=lambda a: a.signature)
    parent = {a.signature: a.signature for a in live}

    def root(signature):
        while parent[signature] != signature:
            parent[signature] = parent[parent[signature]]
            signature = parent[signature]
        return signature

    found = []
    for number, first in enumerate(live):
        for second in live[number + 1:]:
            if first.kind != second.kind:
                continue
            reasons = set()
            if first.target.strip() and first.target.strip() == second.target.strip()                     and first.category == second.category and shares_text(first, second):
                reasons.add(SAME_TARGET)
            if signature_overlap(first.signature, second.signature) >= NEAR_DUPLICATE_MIN_OVERLAP:
                reasons.add(SIMILAR_SIGNATURES)
            if reasons:
                parent[root(second.signature)] = root(first.signature)
                found.append((first.signature, reasons))
    members, why = {}, {}
    for a in live:
        members.setdefault(root(a.signature), []).append(a.signature)
    for signature, reasons in found:
        why.setdefault(root(signature), set()).update(reasons)
    lines = [f'- {", ".join(group)}: ' + '; '.join(r for r in (SAME_TARGET, SIMILAR_SIGNATURES) if r in why[top])
             for top, group in sorted(members.items(), key=lambda item: item[1]) if len(group) > 1]
    if len(lines) > FLAGS_SHOW:
        lines = lines[:FLAGS_SHOW] + [f'- {len(lines) - FLAGS_SHOW} more groups']
    return ['## Near-duplicates'] + lines if lines else []


# ---------- lens accept rates ----------

def lens_rates(context):
    accepted, rejected, sessions = Counter(), Counter(), Counter()
    for row in context.lenses:
        lens, a, r = row.get('lens'), row.get('accepted'), row.get('rejected')
        if not (isinstance(lens, str) and lens and all(records.is_count(n) for n in (a, r))):
            continue
        accepted[lens] += a
        rejected[lens] += r
        sessions[lens] += 1
    lines = []
    for lens in sorted((l for l in sessions if accepted[l] + rejected[l]),
                       key=lambda l: (-(accepted[l] + rejected[l]), l)):
        total = accepted[lens] + rejected[lens]
        percent = round(100 * accepted[lens] / total)
        lines.append(f'- {lens}: {accepted[lens]} of {total} accepted ({percent}%) in '
                     f'{plural(sessions[lens], "session")}')
    return ['## Review lenses'] + lines if lines else []


# ---------- unused plugin skills ----------

def protected_by_win(context, name, qualified):
    """The occurrences of the biggest win about this skill, when it has 2 or more (else 0)."""
    wins = [a.occurrences for a in context.anomalies
            if a.kind == 'win' and a.target.strip() in (name, qualified) and records.is_whole(a.occurrences)]
    best = max(wins, default=0)
    return best if best >= 2 else 0


def unused_skills(context):
    plugin = gitrepo.plugin_repo(context.plugin_root, context.profile)
    names = plugin_skills(context.plugin_root)
    if plugin is None or not names:
        return []
    repo, folder = plugin
    since = trends.window_start(context.today, UNUSED_DAYS)
    heading = '## Unused plugin skills'
    sessions = trends.rows_in_window(context, date.min)
    if not any(day >= since for day, _ in sessions):
        return [heading, f'- not checked: no measured sessions in the last {UNUSED_DAYS} days']
    first_day = min(day for day, _ in sessions)
    if first_day > since:
        return [heading, f'- not checked: measured sessions start on {first_day}, after the '
                         f'{UNUSED_DAYS}-day window began ({since})']
    used = set()
    for day, row in sessions:
        if day >= since:
            used |= metrics.skills_used(row)
    prefix = plugin_name(context.plugin_root, folder)
    lines = []
    for name in names:
        qualified = f'{prefix}:{name}'
        start = gitrepo.first_commit_date(repo, folder / 'skills' / name)
        bare_counts = not is_user_skill(context, name)
        if start is None or start > since or qualified in used or (bare_counts and name in used):
            continue
        line = f'- {qualified}: no use in {UNUSED_DAYS} days (in the plugin since {start}); '
        wins = protected_by_win(context, name, qualified)
        lines.append(line + (f'not proposed: a win with {wins} sightings protects it unless you override'
                             if wins else 'propose removal'))
    return [heading] + lines if lines else []

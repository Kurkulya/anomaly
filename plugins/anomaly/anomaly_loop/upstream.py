"""upstream: a report from an installed copy to the plugin's owner, as a GitHub issue (ADR-0022).

  upstream defect <signature> [--comment <number> | --create] [--plugin-root <dir>] [--user-config <dir>]

The defect report (a plugin fault, no experiment) of the anomaly `<signature>`. Its title is
`[anomaly:<skill or agent>] <signature>`, or for a plugin-code target `[anomaly:<path from the plugin root>]`
(addenda.plugin_part names the skill or agent); its body holds the target, the anomaly's summary as the symptom
line, the installed version (the plugin root folder name: plugin.json has no version) and the signature.

  upstream tuning <signature> [--comment <number> | --create] [--plugin-root <dir>] [--user-config <dir>]

The tuning report (a kept addenda line, sent with its experiment's result) of the anomaly `<signature>`. It is
refused unless the anomaly is `fixed` (a reopened one: the fix did not hold), the experiment's result is in KEPT
(`keep`, or `unproven`: kept, not proven) and the addenda file its fix names still holds its tagged line
(tuning_source). Its title is that of a defect report on the same target (title_fields); its body holds the target,
the rule (the line without its tag), the verdict word, the recorded reason, the installed version, the signature,
then the readings as `calibrate verify` prints them, read today (`Readings as of <today>`: the record keeps no
verify day; verdict.reading_lines: the metric and the guard before the fix and since, n= the sessions on each side).

When `plugin_repo` resolves to a checkout (gitrepo.plugin_repo), the command prints CHECKOUT_SET and exits 1 with
nothing written: a checkout fixes the plugin through an MR. Else every run checks the report (checked_report, then
check_report: each field, and the agent name of a per-dispatch reading, passes privacy.check_text and names no
profile marker, scans.profile_markers, and no repo-layer name, scans.repo_layer_names; a hit refuses with no file
written and nothing redacted), writes it to `<home>/upstream/<signature>.defect.md` or
`<home>/upstream/<signature>.tuning.md` (a `Title:` line, a blank line, the body) and prints the path. The marker and
repo-layer check (in any case) reads only the text from outside the CLI (the symptom, the rule, the reason, the agent name of a
per-dispatch reading, verdict.per_dispatch_agent, the installed version folder and the signature), not the title,
target, verdict word, readings heading and the rest of each readings line, which the CLI composes; that text is also
refused when it holds a local path or the OS user name.

The target repository: `source.repo` of the installed copy's marketplace record (marketplace_repo) when its source is
GitHub, else the profile key `upstream_repo`; with neither, the command says no target repository is known and
exits 1, the file written.

The `upstream` port (profile key `upstream_tool`, constants.UPSTREAM_ADAPTERS): on its core default the command
prints the search link of the repository's GitHub issues and calls nothing. With `gh` it lists the open issues whose
title names the same target and offers an exact title hit as the +1. A second run acts, each after the user's yes:
`--comment <number>` adds a +1 comment to that issue, `--create` opens the issue from the file this run writes; either
appends `upstream <date> · <number>` under the anomaly's `## Addenda log` (addenda.log_line) and commits the anomaly.
Without either flag nothing is written to GitHub. When the Addenda log already holds an `upstream ` line, `--comment`
and `--create` are refused (exit 2) with nothing sent or written: a report goes once. A failed `gh` call is one
`anomaly:` line (exit 2).
"""
import argparse
import json
import re
from collections import namedtuple
from importlib import import_module
from pathlib import Path
from urllib.parse import quote_plus

from . import addenda, digest, files, flags, gh, gitrepo, observe, ports, privacy, profile, records, scans, verdict
from .constants import COMMIT_SCOPE, UPSTREAM_ADAPTERS
from .files import RecordError

ADAPTERS = {name: import_module(f'.{name}', __package__) for name in UPSTREAM_ADAPTERS}   # the module of each adapter
ADAPTER_ERRORS = tuple(module.ERROR for module in ADAPTERS.values())
UPSTREAM_DIR = 'upstream'                # <home>/upstream/<signature><suffix>: the issue text of a report
DEFECT_SUFFIX = '.defect.md'
TUNING_SUFFIX = '.tuning.md'
MARKETPLACES = Path('plugins') / 'known_marketplaces.json'   # in the Claude Code user folder
PREFIX = '[anomaly:{part}]'              # the start of a title: `<prefix> <signature>`
LABEL = 'upstream defect'
TUNING_LABEL = 'upstream tuning'
KEPT = ('keep', 'unproven')              # the experiment results a tuning report is sent for
VERSION_FIELD = 'Installed version'
READING_FIELD = 'Reading'                # the agent name of a per-dispatch reading, as check_report reads it
OUTSIDE_FIELDS = ('Symptom', 'Rule', 'Reason', READING_FIELD, VERSION_FIELD, 'Signature')   # see check_report
LOCAL_PATH = re.compile(r'(?<![\w./])(?:/[^\s/]+/[^\s/]|~/)|(?<![A-Za-z0-9])[A-Za-z]:[\\/]')   # see check_report
USER_NAME_KEYS = ('USER', 'USERNAME')    # the environment keys that hold the OS user name
GENERIC_USERS = frozenset({'root', 'user', 'admin', 'ubuntu', 'runner', 'vscode', 'codespace', 'node', 'docker',
                           'ec2-user', 'vagrant'})   # account names that name no person; see user_names
USER_NAME_MIN = 3                        # a shorter user name is not checked; see user_names
CHECKOUT_SET = 'a plugin checkout is set: fix it through an MR'
NO_REPOSITORY = ('no target repository is known: the marketplace record of this copy names no GitHub source and '
                 'the profile has no upstream_repo')
ISSUE_LINK = re.compile(r'.*/issues/(\d+)/?')
COMMIT_PREFIX = f'chore({COMMIT_SCOPE}): upstream '
LOG_WORD = 'upstream '                   # the start of the Addenda log line of a sent report


def part_word(context, target, label=LABEL):
    """What the title names after `anomaly:`: the skill or agent (addenda.plugin_part), or for plugin code the path
    from the plugin root. Any other target is refused (`label` starts the error): the report has no title for it."""
    part = addenda.plugin_part(context, target, None)
    if part is not None and part.name:
        return part.name
    if part is not None and flags.is_path(target):
        found = flags.target_path(context, target, None)
        root = Path(context.plugin_root).resolve()
        if found is not None and found.resolve().is_relative_to(root):
            return found.resolve().relative_to(root).as_posix()
    raise RecordError(f'{label}: the target {target or "(none)"} is not a skill, an agent or a file of this plugin')


def user_names(environ):
    """Patterns of the OS user name (USER_NAME_KEYS in `environ`) as a whole word in any case; none when unset.
    A generic account name (GENERIC_USERS, in any case) or a name under USER_NAME_MIN characters gives none: it
    names no person, and as a common word (`root cause`) it would refuse plain text."""
    names = {environ.get(key, '').strip() for key in USER_NAME_KEYS}
    names = {name for name in names if len(name) >= USER_NAME_MIN and name.lower() not in GENERIC_USERS}
    return [re.compile(rf'(?<!\w){re.escape(name)}(?!\w)', re.I) for name in sorted(names)]


def check_report(context, fields, environ, label=LABEL):
    """Refuse the report (ADR-0003: refuse, never redact; `label` starts the error) when a field fails
    privacy.check_text, or when a field from outside the CLI (OUTSIDE_FIELDS: the symptom, the rule, the reason, the
    agent name of a per-dispatch reading, the installed version folder and the signature, not the title and target
    the CLI composes; an installed version that is a commit id, privacy.COMMIT_ID, holds no name and is skipped, so
    a short repo-layer name such as `add` cannot match its hex) holds a profile marker (scans.profile_markers) or a
    repo-layer name (scans.repo_layer_names) in any case, by scans.marker_hits on the text and the names in lower
    case (marker_hits itself and the neutrality test stay case-sensitive: plugin files are text the plugin's own
    author writes, a report holds the user's words), a local path (LOCAL_PATH: `/x/y` or `~/` not
    right after a letter, digit, `_`, `.` or `/`, so also after a quote, a bracket or `=`, or a drive `X:\\` or
    `X:/`; a slash inside a word such as `and/or`, the `//` of a link and any one-segment path are none, so a slash
    command such as `/compact` and a path such as `/etc` are allowed) or the OS user name (user_names)."""
    names = scans.profile_markers(context.profile.values, context.plugin_root) | scans.repo_layer_names(context.home)
    lowered = {name.lower(): name for name in names}
    users = user_names(environ)
    for key, value in fields:
        privacy.check_text(label, key, value)
        if key not in OUTSIDE_FIELDS or (key == VERSION_FIELD and privacy.COMMIT_ID.fullmatch(value)):
            continue
        found = sorted(lowered[hit] for hit in scans.marker_hits(value.lower(), lowered))
        if found:
            raise RecordError(f'{label}: {key} names {", ".join(found)}, from the profile or the repo layer in home; '
                              'describe it in your own words')
        if LOCAL_PATH.search(value) or any(user.search(value) for user in users):
            raise RecordError(f'{label}: {key} holds a local path or the user name; describe it in your own words')


Report = namedtuple('Report', 'suffix word fields lines plus_one checked', defaults=((),))
Report.__doc__ = ('One report to send: the file suffix, the title word (part_word), the (key, text) fields with the '
                  'title first, the lines that follow the fields in the body as they are, the text of a +1 '
                  'comment, and the (key, text) pairs from outside the CLI that those lines hold, checked with the '
                  'fields but not written as fields.')


def installed_version(context):
    """The installed version: the plugin root folder name (plugin.json has no version)."""
    return Path(context.plugin_root).resolve().name


def title_fields(word, signature):
    """The Title and Target fields of either report; `word` is part_word's answer. The title names no lane: one
    signature is sent in one lane only."""
    return ('Title', f'{PREFIX.format(part=word)} {signature}'), ('Target', f'anomaly:{word}')


def defect_report(context, anomaly):
    """The defect report of the anomaly; RecordError when upstream defect refuses its target (part_word)."""
    word, version = part_word(context, anomaly.target.strip()), installed_version(context)
    fields = (*title_fields(word, anomaly.signature), ('Symptom', anomaly.summary), (VERSION_FIELD, version),
              ('Signature', anomaly.signature))
    return Report(DEFECT_SUFFIX, word, fields, (), f'+1: the same defect on the installed version {version}')


def tuning_source(context, anomaly):
    """(word, rule) of the anomaly's tuning report: the title word (part_word) and the rule of the line tagged with
    its signature (addenda.tagged_line, the rule without its tag) in the addenda file its fix names
    (addenda.addendum_file). RecordError when upstream tuning refuses it: the anomaly's status is not `fixed` (a
    reopened one: the fix did not hold), the experiment's result is not in KEPT (a revert, a result still
    `inconclusive` or none yet), no addenda file holds its line, or part_word refuses."""
    if anomaly.status != 'fixed':
        raise RecordError(f'{TUNING_LABEL}: {anomaly.signature} is {anomaly.status}, not fixed: the fix did not hold, '
                          'so its line is not sent')
    result = anomaly.experiment.result if anomaly.experiment is not None else ''
    if result not in KEPT:
        raise RecordError(f'{TUNING_LABEL}: the experiment of {anomaly.signature} has the result '
                          f'{result or "(none yet)"}; only a line kept with the result keep or unproven is sent')
    path = addenda.addendum_file(context.home, anomaly)
    line = None if path is None else addenda.tagged_line(path, anomaly.signature)
    if line is None:
        raise RecordError(f'{TUNING_LABEL}: no addenda file in home holds the line of {anomaly.signature}')
    return part_word(context, anomaly.target.strip(), TUNING_LABEL), addenda.TAGGED.fullmatch(line)['rule']


def tuning_report(context, anomaly):
    """The tuning report of the anomaly (tuning_source), its readings from verdict.verdict as of today (the record
    keeps no verify day); RecordError when upstream tuning refuses it."""
    word, rule = tuning_source(context, anomaly)
    found = verdict.verdict(context, anomaly)
    experiment, version = anomaly.experiment, installed_version(context)
    heading = f'Readings as of {context.today.isoformat()}'
    fields = (*title_fields(word, anomaly.signature), ('Rule', rule), ('Verdict', experiment.result),
              ('Reason', experiment.reason or '(none recorded)'), (VERSION_FIELD, version),
              ('Signature', anomaly.signature), (heading, 'before the fix and since; n= is the sessions on each side'))
    readings = tuple(f'  {line}' for line in verdict.reading_lines(found))   # nested under the Readings field
    agents = tuple((READING_FIELD, agent) for agent in map(verdict.per_dispatch_agent, (r.name for r in found.readings))
                   if agent is not None)   # the user part of a reading; the rest of its line is CLI text
    plus_one = f'+1: the same line, {experiment.result} on the installed version {version}'
    return Report(TUNING_SUFFIX, word, fields, readings, plus_one, agents)


ACTIONS = {'defect': (LABEL, defect_report), 'tuning': (TUNING_LABEL, tuning_report)}   # action: (label, compose)


def checked_report(context, anomaly, action, environ):
    """The report of `action` (ACTIONS) for the anomaly once check_report passed it: its fields and its checked
    pairs (the agent name of a per-dispatch reading); RecordError when the action refuses it, OSError when a file
    it reads cannot be read."""
    label, compose = ACTIONS[action]
    report = compose(context, anomaly)
    check_report(context, report.fields + report.checked, environ, label)
    return report


def write_report(home, signature, report):
    """Write the report file (`Title: <title>`, a blank line, one `- <key>: <text>` line per field, then the report's
    lines); returns (path, title, body)."""
    (_, title), *rest = report.fields
    body = '\n'.join([f'- {key}: {value}' for key, value in rest] + list(report.lines))
    path = Path(home) / UPSTREAM_DIR / f'{signature}{report.suffix}'
    files.write_text(path, f'Title: {title}\n\n{body}\n')
    return path, title, body


def marketplace_repo(user_config, plugin_root):
    """`source.repo` of the marketplace record of the installed copy when its source is GitHub, else None. The
    marketplace is the grandparent folder of the plugin root (`<config>/plugins/cache/<marketplace>/<plugin>/<version>`).
    A missing or unreadable record file, or an entry of another shape, gives None, as scans.deny_rules reads settings."""
    try:
        data = json.loads((Path(user_config) / MARKETPLACES).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    entry = data.get(Path(plugin_root).resolve().parent.parent.name) if isinstance(data, dict) else None
    source = entry.get('source') if isinstance(entry, dict) else None
    if isinstance(source, dict) and source.get('source') == 'github' and isinstance(source.get('repo'), str):
        return source['repo']
    return None


def target_repository(context, label=LABEL):
    """The repository the report goes to (marketplace_repo, else the profile's `upstream_repo`), or None; `label`
    starts the error of a value that is not owner/name."""
    found = marketplace_repo(context.user_config, context.plugin_root)
    if found is None:
        value = context.profile.values.get('upstream_repo')
        found = profile.one_line(value) if profile.is_set(value) else None
    if found is not None and not gh.PROJECT.fullmatch(found):
        raise RecordError(f'{label}: the target repository {found!r} is not owner/name')
    return found


def search_link(repo, prefix):
    """The link of the repository's open GitHub issues whose title holds `prefix`."""
    return f'https://{gh.HOST}/{repo}/issues?q=' + quote_plus(f'is:issue is:open in:title "{prefix}"')


def printable(text):
    """`text` without its non-printable characters (control and escape codes), so a title from GitHub cannot steer
    the terminal."""
    return ''.join(character for character in text if character.isprintable())


def search_lines(repo, issues, title, prefix):
    """The open issues whose title starts with `prefix`, an exact title hit marked as the +1 offer; each title is
    printed as printable() leaves it."""
    same = [(number, printable(text)) for number, text in issues if printable(text).strip().startswith(prefix)]
    if not same:
        return [f'no open issue of {repo} names {prefix}: run again with --create to open one']
    lines = [f'open issues of {repo} that name {prefix}:']
    for number, text in same:
        offer = f'  <- +1 offer, the exact signature: run again with --comment {number}' if text.strip() == title else ''
        lines.append(f'#{number} {text}{offer}')
    if all(text.strip() != title for _, text in same):
        lines.append('no exact signature hit: propose a match from these titles, then run again with '
                     '--comment <number> for a +1 or --create for a new issue')
    return lines


def issue_option(text):
    """The argparse type of --comment: records.count_option, and at least 1."""
    try:
        value = records.count_option(text)
    except argparse.ArgumentTypeError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f'an issue number of 1 or more, got: {text}')
    return value


def issue_number(link, label=LABEL):
    found = ISSUE_LINK.fullmatch(link)
    if found is None:
        raise RecordError(f'{label}: the issue link {link} has no issue number at its end')
    return int(found[1])


def sent_lines(anomaly):
    """The lines of the anomaly's `## Addenda log` that record a report sent upstream (LOG_WORD)."""
    return [line for line in addenda.log_lines(anomaly) if line.startswith(LOG_WORD)]


def run_report(args, environ, action):
    """The run of `upstream defect` and `upstream tuning` (the module text); `action` is a key of ACTIONS."""
    label = ACTIONS[action][0]
    context = digest.context_from_args(args, environ, strict=True)
    if gitrepo.plugin_repo(context.plugin_root, context.profile) is not None:
        print(CHECKOUT_SET)
        return 1
    name = ports.adapter_name(ports.resolve(context.home), 'upstream', UPSTREAM_ADAPTERS, 'upstream')
    if name is None and (args.comment is not None or args.create):
        raise RecordError(f'{label}: the upstream port is on its core default, so there is no tool to call '
                          '(set upstream_tool in the profile)')
    anomalies = addenda.writable(context)
    anomaly = addenda.find(anomalies, args.signature)
    sent = sent_lines(anomaly)
    if sent and (args.comment is not None or args.create):
        raise RecordError(f'{label}: {anomaly.signature} was already sent upstream ({sent[-1]}); a report goes once')
    report = checked_report(context, anomaly, action, environ)
    path, title, body = write_report(context.home, anomaly.signature, report)
    print(f'report: {path}')
    repo = target_repository(context, label)
    if repo is None:
        print(NO_REPOSITORY)
        return 1
    prefix = PREFIX.format(part=report.word)
    if name is None:
        print(f'search: {search_link(repo, prefix)}')
        return 0
    tool = ADAPTERS[name]
    if args.comment is not None:
        ports.call_tool(ADAPTER_ERRORS, tool.comment_issue, repo, args.comment, report.plus_one, environ=environ)
        number = args.comment
        print(f'+1 added to #{number}')
    elif args.create:
        link = ports.call_tool(ADAPTER_ERRORS, tool.create_issue, repo, title, body, environ=environ)
        number = issue_number(link, label)
        print(link)
    else:
        issues = ports.call_tool(ADAPTER_ERRORS, tool.list_issues, repo, prefix, environ=environ)
        print('\n'.join(search_lines(repo, issues, title, prefix)))
        return 0
    addenda.log_line(anomaly, f'{LOG_WORD}{args.today.isoformat()} · {number}')
    print(observe.save_anomalies(context.home, args.today, anomalies, [anomaly.signature],
                                 COMMIT_PREFIX + f'#{number} for {anomaly.signature}'))
    return 0


def run_defect(args, environ):
    return run_report(args, environ, 'defect')


def run_tuning(args, environ):
    return run_report(args, environ, 'tuning')


def register(commands, common):
    command = commands.add_parser('upstream', help='report a plugin fault or a kept addenda line from an installed '
                                                   'copy as a GitHub issue')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    for name, handler, help_text in (
            ('defect', run_defect, 'write the defect report of an anomaly, then search, +1 or create its issue'),
            ('tuning', run_tuning, 'write the tuning report of a kept addenda line with its result, then search, '
                                   '+1 or create its issue')):
        action = actions.add_parser(name, parents=[common, digest.folder_options()], help=help_text)
        action.add_argument('signature', help='the anomaly the report is about')
        act = action.add_mutually_exclusive_group()
        act.add_argument('--comment', type=issue_option, metavar='<number>',
                         help="only after the user's yes: add a +1 comment to this issue")
        act.add_argument('--create', action='store_true',
                         help="only after the user's yes: open the issue from the report file")
        action.set_defaults(handler=handler)

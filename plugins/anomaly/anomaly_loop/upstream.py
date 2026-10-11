"""upstream: a report from an installed copy to the plugin's owner, as a GitHub issue (ADR-0022).

  upstream defect <signature> [--comment <number> | --create] [--plugin-root <dir>] [--user-config <dir>]

The defect report (a plugin fault, no experiment) of the anomaly `<signature>`. Its title is
`[anomaly:<skill or agent>] <signature>`, or for a plugin-code target `[anomaly:<path from the plugin root>]`
(addenda.plugin_part names the skill or agent); its body holds the target, the anomaly's summary as the symptom
line, the installed version (the plugin root folder name: plugin.json has no version) and the signature.

When `plugin_repo` resolves to a checkout (gitrepo.plugin_repo), the command prints CHECKOUT_SET and exits 1 with
nothing written: a checkout fixes the plugin through an MR. Else every run checks the report (check_report: each line
passes privacy.check_text and names no profile marker, scans.profile_markers, and no repo-layer name,
scans.repo_layer_names; a hit refuses with no file written and nothing redacted), writes it to
`<home>/upstream/<signature>.defect.md` (a `Title:` line, a blank line, the body) and prints the path. The marker and
repo-layer check reads only the text from outside the CLI (the symptom, the installed version folder and the
signature), not the title and target the CLI composes; that text is also refused when it holds a local path or the OS
user name.

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
from importlib import import_module
from pathlib import Path
from urllib.parse import quote_plus

from . import addenda, digest, files, flags, gh, gitrepo, observe, ports, privacy, profile, records, scans
from .constants import COMMIT_SCOPE, UPSTREAM_ADAPTERS
from .files import RecordError

ADAPTERS = {name: import_module(f'.{name}', __package__) for name in UPSTREAM_ADAPTERS}   # the module of each adapter
ADAPTER_ERRORS = tuple(module.ERROR for module in ADAPTERS.values())
UPSTREAM_DIR = 'upstream'                # <home>/upstream/<signature>.defect.md: the issue text of a defect report
DEFECT_SUFFIX = '.defect.md'
MARKETPLACES = Path('plugins') / 'known_marketplaces.json'   # in the Claude Code user folder
PREFIX = '[anomaly:{part}]'              # the start of a title: `<prefix> <signature>`
LABEL = 'upstream defect'
VERSION_FIELD = 'Installed version'
OUTSIDE_FIELDS = ('Symptom', VERSION_FIELD, 'Signature')   # from outside the CLI: the user, a folder name
LOCAL_PATH = re.compile(r'(?<![\w./])(?:/[^\s/]+/[^\s/]|~/)|(?<![A-Za-z0-9])[A-Za-z]:[\\/]')   # see check_report
USER_NAME_KEYS = ('USER', 'USERNAME')    # the environment keys that hold the OS user name
CHECKOUT_SET = 'a plugin checkout is set: fix it through an MR'
NO_REPOSITORY = ('no target repository is known: the marketplace record of this copy names no GitHub source and '
                 'the profile has no upstream_repo')
ISSUE_LINK = re.compile(r'.*/issues/(\d+)/?')
COMMIT_PREFIX = f'chore({COMMIT_SCOPE}): upstream '
LOG_WORD = 'upstream '                   # the start of the Addenda log line of a sent report


def part_word(context, target):
    """What the title names after `anomaly:`: the skill or agent (addenda.plugin_part), or for plugin code the path
    from the plugin root. Any other target is refused: the report has no title for it."""
    part = addenda.plugin_part(context, target, None)
    if part is not None and part.name:
        return part.name
    if part is not None and flags.is_path(target):
        found = flags.target_path(context, target, None)
        root = Path(context.plugin_root).resolve()
        if found is not None and found.resolve().is_relative_to(root):
            return found.resolve().relative_to(root).as_posix()
    raise RecordError(f'{LABEL}: the target {target or "(none)"} is not a skill, an agent or a file of this plugin')


def user_names(environ):
    """Patterns of the OS user name (USER_NAME_KEYS in `environ`) as a whole word in any case; none when unset."""
    names = {environ.get(key, '').strip() for key in USER_NAME_KEYS} - {''}
    return [re.compile(rf'(?<!\w){re.escape(name)}(?!\w)', re.I) for name in sorted(names)]


def check_report(context, fields, environ):
    """Refuse the report (ADR-0003: refuse, never redact) when a field fails privacy.check_text, or when a field from
    outside the CLI (OUTSIDE_FIELDS: the symptom, the installed version folder and the signature, not the title and
    target lines the CLI composes; an installed version that is a commit id, privacy.COMMIT_ID, holds no name and is
    skipped, so a short repo-layer name such as `add` cannot match its hex) holds a profile marker
    (scans.profile_markers) or a repo-layer name (scans.repo_layer_names), by scans.marker_hits, a local path
    (LOCAL_PATH: `/x/y` or `~/` not right after a letter, digit, `_`, `.` or `/`, so also after a quote, a bracket or
    `=`, or a drive `X:\\` or `X:/`; a slash inside a word such as `and/or`, the `//` of a link and any one-segment
    path are none, so a slash command such as `/compact` and a path such as `/etc` are allowed) or the OS user name
    (user_names)."""
    names = scans.profile_markers(context.profile.values, context.plugin_root) | scans.repo_layer_names(context.home)
    users = user_names(environ)
    for key, value in fields:
        privacy.check_text(LABEL, key, value)
        if key not in OUTSIDE_FIELDS or (key == VERSION_FIELD and privacy.COMMIT_ID.fullmatch(value)):
            continue
        found = scans.marker_hits(value, names)
        if found:
            raise RecordError(f'{LABEL}: {key} names {", ".join(found)}, from the profile or the repo layer in home; '
                              'describe it in your own words')
        if LOCAL_PATH.search(value) or any(user.search(value) for user in users):
            raise RecordError(f'{LABEL}: {key} holds a local path or the user name; describe it in your own words')


def defect_fields(context, anomaly, word):
    """(key, text) of the defect report, the title first; `word` is part_word's answer."""
    return (('Title', f'{PREFIX.format(part=word)} {anomaly.signature}'), ('Target', f'anomaly:{word}'),
            ('Symptom', anomaly.summary), (VERSION_FIELD, Path(context.plugin_root).resolve().name),
            ('Signature', anomaly.signature))


def write_report(home, signature, fields):
    """Write the report file (`Title: <title>`, a blank line, one `- <key>: <text>` line per field); returns
    (path, title, body)."""
    (_, title), *rest = fields
    body = '\n'.join(f'- {key}: {value}' for key, value in rest)
    path = Path(home) / UPSTREAM_DIR / f'{signature}{DEFECT_SUFFIX}'
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


def target_repository(context):
    """The repository the report goes to (marketplace_repo, else the profile's `upstream_repo`), or None."""
    found = marketplace_repo(context.user_config, context.plugin_root)
    if found is None:
        value = context.profile.values.get('upstream_repo')
        found = profile.one_line(value) if profile.is_set(value) else None
    if found is not None and not gh.PROJECT.fullmatch(found):
        raise RecordError(f'{LABEL}: the target repository {found!r} is not owner/name')
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


def issue_number(link):
    found = ISSUE_LINK.fullmatch(link)
    if found is None:
        raise RecordError(f'{LABEL}: the issue link {link} has no issue number at its end')
    return int(found[1])


def run_defect(args, environ):
    context = digest.context_from_args(args, environ, strict=True)
    if gitrepo.plugin_repo(context.plugin_root, context.profile) is not None:
        print(CHECKOUT_SET)
        return 1
    name = ports.adapter_name(ports.resolve(context.home), 'upstream', UPSTREAM_ADAPTERS, 'upstream')
    if name is None and (args.comment is not None or args.create):
        raise RecordError(f'{LABEL}: the upstream port is on its core default, so there is no tool to call '
                          '(set upstream_tool in the profile)')
    anomalies = addenda.writable(context)
    anomaly = addenda.find(anomalies, args.signature)
    sent = [line for line in addenda.log_lines(anomaly) if line.startswith(LOG_WORD)]
    if sent and (args.comment is not None or args.create):
        raise RecordError(f'{LABEL}: {anomaly.signature} was already sent upstream ({sent[-1]}); a report goes once')
    word = part_word(context, anomaly.target.strip())
    fields = defect_fields(context, anomaly, word)
    check_report(context, fields, environ)
    path, title, body = write_report(context.home, anomaly.signature, fields)
    print(f'report: {path}')
    repo = target_repository(context)
    if repo is None:
        print(NO_REPOSITORY)
        return 1
    prefix = PREFIX.format(part=word)
    if name is None:
        print(f'search: {search_link(repo, prefix)}')
        return 0
    tool = ADAPTERS[name]
    if args.comment is not None:
        version = dict(fields)[VERSION_FIELD]
        ports.call_tool(ADAPTER_ERRORS, tool.comment_issue, repo, args.comment,
                        f'+1: the same defect on the installed version {version}', environ=environ)
        number = args.comment
        print(f'+1 added to #{number}')
    elif args.create:
        link = ports.call_tool(ADAPTER_ERRORS, tool.create_issue, repo, title, body, environ=environ)
        number = issue_number(link)
        print(link)
    else:
        issues = ports.call_tool(ADAPTER_ERRORS, tool.list_issues, repo, prefix, environ=environ)
        print('\n'.join(search_lines(repo, issues, title, prefix)))
        return 0
    addenda.log_line(anomaly, f'{LOG_WORD}{args.today.isoformat()} · {number}')
    print(observe.save_anomalies(context.home, args.today, anomalies, [anomaly.signature],
                                 COMMIT_PREFIX + f'#{number} for {anomaly.signature}'))
    return 0


def register(commands, common):
    command = commands.add_parser('upstream', help='report a plugin fault from an installed copy as a GitHub issue')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    defect = actions.add_parser('defect', parents=[common, digest.folder_options()],
                                help='write the defect report of an anomaly, then search, +1 or create its issue')
    defect.add_argument('signature', help='the anomaly the report is about')
    act = defect.add_mutually_exclusive_group()
    act.add_argument('--comment', type=issue_option, metavar='<number>',
                     help="only after the user's yes: add a +1 comment to this issue")
    act.add_argument('--create', action='store_true',
                     help="only after the user's yes: open the issue from the report file")
    defect.set_defaults(handler=run_defect)

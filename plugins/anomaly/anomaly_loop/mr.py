"""mr: the helpers of the `ship` skill.

  mr body <work unit folder | ad-hoc ticket> [--draft] [--docs-gate '<text>'] [--repo <dir>]

Writes the MR body to a file (bodies go through files, ADR-0007). The file starts with `Title: <type>(<key>): <summary>`
and a blank line; the body follows, in markdown (`## <Section>`). A work unit folder gives `<folder>/mr-body.md`; an
ad-hoc ticket gives the sibling file `<ticket name>.mr-body.md` in `.anomaly/adhoc/`; a file target outside that
folder is refused. Facts come only from the ticket files, the AC file (`spec.md` when the unit has one, else
`stories.md`, ADR-0011), `decisions.md` and, for an ad-hoc ticket, the commit subjects of its branch; never the diff.

The title: the type is `feat` (an ad-hoc ticket: the type before the first `/` of the branch name, when it is an
Angular type); the key is the first ticket key of the unit (else `no-ticket`); the summary is the first heading of
the AC file, or the title of the ad-hoc ticket, cut at a word so the title is under 70 characters.

A work unit body has these sections, each left out when it has no facts: Why (the `Why:` line of the AC file),
What changed (the title of each ticket that is `done`), Acceptance criteria (`n of m covered` by those tickets,
with the missing ids), Still open (their `Open:` items), Breaking changes (the `- Breaking:` and
`- D-n: Breaking:` lines of decisions.md), Tested, How to review. With `--draft` the body is two lines: the Why,
then `Work in progress` (one line when there is no Why).
An ad-hoc ticket body has Why (the ticket's `What to build:`) and What changed (the subjects of the commits on the
current branch that are not on the repo base).

A body holds no commit id, no table row and no attribution line (`plain`). A body over 2.5 KB prints one
`warning:` line and is still written. The file path is printed. A body line with a privacy problem
(`privacy.privacy_problems`) is an error that names its section (`check_privacy`); no file is written.

  mr put <work unit folder | ad-hoc ticket> [--repo <dir>]
  mr ready <work unit folder | ad-hoc ticket> [--repo <dir>]
  mr show <work unit folder | ad-hoc ticket> [--repo <dir>]
  mr reviewed <work unit folder> <ref> [--repo <dir>]
  mr verified <work unit folder> <ref> [--repo <dir>]

`put` reads the title from the first `Title:` line of the body file and the body from the lines after the blank line,
and opens a draft MR from the current branch to the base branch, or, when the MR file already has an `MR:` line,
replaces the body of that MR (the title stays). `put` runs `check_privacy` on the body file first. Before it replaces a
body, and before `ready` acts, the MR is viewed and must have the link of the `MR:` line and the current branch as its
source (`check_same_mr`). `ready` takes the draft state off and `show` prints the link and the state. The tool is the adapter the `mr` port names (constants.MR_ADAPTERS; an unknown value is an error naming
them), run for the project of the `origin` remote, which must be on the host of the adapter (`gh`: github.com,
`glab`: gitlab.com; any other host is an error, never guessed). With the port on its core default, or a repository
with no `origin`, `put` only prints the title and body and nothing leaves the machine; `ready` and `show` are
errors then. Without an `MR:` line, `ready` and `show` say to run `mr put` first.

The MR file holds the lines `MR: <link>`, `Reviewed: <sha>` and `Verified: <sha>`, in this order, and is written
only here: `put` sets the first, `reviewed` and `verified` set the others (the ref is resolved to a full commit id
through git), and each leaves the other lines as they were. A work unit folder keeps it as `<folder>/mr.md`; an
ad-hoc ticket as the sibling `<ticket name>.mr.md` in `.anomaly/adhoc/`, which holds only the `MR:` line: the gate
lines of an ad-hoc ticket are its own `Reviewed:` and `Verified:` lines (`ticket reviewed`, `ticket verified`), so
`reviewed` and `verified` refuse an ad-hoc ticket. A folder target must be a work unit folder (a folder in
`.anomaly/` or `.scratch/`, not `adhoc`).
"""
import re
import sys
from importlib import import_module
from pathlib import Path
from typing import NamedTuple

from . import check, constants, files, frontier, gitrepo, paths, ports, privacy, records, ticket
from .constants import TICKET_ADHOC_DIR, TICKET_STATUS_DONE
from .files import RecordError

BODY_FILE = 'mr-body.md'                 # in a work unit folder
ADHOC_SUFFIX = '.mr-body.md'             # after the name of an ad-hoc ticket, beside it
STATE_FILE = 'mr.md'                     # the MR link and the gate lines, in a work unit folder
ADHOC_STATE_SUFFIX = '.mr.md'            # after the name of an ad-hoc ticket, beside it
MR_LABEL, REVIEWED_LABEL, VERIFIED_LABEL = 'MR', 'Reviewed', 'Verified'
STATE_LABELS = (MR_LABEL, REVIEWED_LABEL, VERIFIED_LABEL)   # the lines of the MR file, in file order
ADAPTERS = {name: import_module(f'.{name}', __package__) for name in constants.MR_ADAPTERS}   # the module of each adapter
# (glab.py, gh.py): each has HOST, ERROR and create_mr, update_mr, ready_mr, view_mr
ADAPTER_ERRORS = tuple(module.ERROR for module in ADAPTERS.values())
TITLE_LINE = re.compile(r'Title:[ \t]*(\S.*?)[ \t]*')
MR_NUMBER = re.compile(r'.*/(\d+)/?')    # the end of a link: .../pull/7 or .../-/merge_requests/7
TITLE_MAX_CHARS = 70                     # a title is under this
BODY_WARN_BYTES = 2560                   # 2.5 KB
DEFAULT_TYPE = 'feat'
BRANCH_TYPES = ('feat', 'fix', 'docs', 'style', 'refactor', 'perf', 'test', 'build', 'ci', 'chore', 'revert')
NO_KEY = 'no-ticket'
WIP_LINE = 'Work in progress'
NO_CI_LINE = 'no CI ran'                 # said when the `ci` port is on its core default
COUNTED = ('suites', 'type_checks', 'reviewer_passes', 'high')   # the Metrics counts the Tested section sums (ticket.METRIC_COUNTS keys)
ATTRIBUTION = re.compile(r'\s*(?:co-authored-by:|generated with\b)', re.I)   # the start of an attribution line
COMMIT_ID = re.compile(rf'\b(?:{privacy.COMMIT_ID.pattern})\b')
BREAKING_LINE = re.compile(r'\s*[-*+]\s+(?:D-\d+:\s*)?Breaking:\s*(\S.*?)\s*$')   # `- Breaking: x` or `- D-n: Breaking: x`
DECISION_TAIL = re.compile(r'\.?\s+(?:Why|Source):.*$')   # the Why and Source of a `- D-n:` line, not part of the fact
NO_OPEN = re.compile(r'none\.?', re.I)
WHY_KEY = 'Why'
WHAT_TO_BUILD_KEY = 'What to build'


def register(commands, common):
    command = commands.add_parser('mr', help='the helpers of the ship skill')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    body = actions.add_parser('body', parents=[common],
                              help='write the MR body (Title: line, blank line, markdown) from the unit files; '
                                   'prints the file path')
    body.add_argument('target', help='a work-unit folder (writes mr-body.md in it) or an ad-hoc ticket file '
                                     '(writes <name>.mr-body.md beside it)')
    body.add_argument('--draft', action='store_true', help='a two-line body: the Why, then "Work in progress"')
    body.add_argument('--docs-gate', metavar='TEXT',
                      help='the docs-gate result for the Tested section, one line (work unit only)')
    body.add_argument('--repo', help=gitrepo.REPO_HELP)
    body.set_defaults(handler=run_body)
    for name, handler, help_text in (
            ('put', run_put, 'open the draft MR from the body file, or replace the body of the MR in mr.md; '
                             'prints the link (the core default prints the title and body)'),
            ('ready', run_ready, 'mark the MR of mr.md ready for review'),
            ('show', run_show, 'print the link and the state of the MR of mr.md')):
        action = actions.add_parser(name, parents=[common], help=help_text)
        action.add_argument('target', help='a work-unit folder (mr-body.md and mr.md in it) or an ad-hoc ticket file '
                                           '(<name>.mr-body.md and <name>.mr.md beside it)')
        action.add_argument('--repo', help=gitrepo.REPO_HELP)
        action.set_defaults(handler=handler)
    for label, handler in ((REVIEWED_LABEL, run_reviewed), (VERIFIED_LABEL, run_verified)):
        gate = actions.add_parser(label.lower(), parents=[common],
                                  help=f'write the {label}: line of mr.md with the full commit id of a ref')
        gate.add_argument('target', help='a work-unit folder (an ad-hoc ticket has its own line: ticket reviewed, '
                                         'ticket verified)')
        gate.add_argument('ref', help='a commit id, branch or tag; written as the full commit id')
        gate.add_argument('--repo', help=gitrepo.REPO_HELP)
        gate.set_defaults(handler=handler)


def plain(text):
    """A fact as the body shows it: one line, no commit id (a hex word with a digit and a letter a-f, in the
    shapes of privacy.COMMIT_ID), no `|` (so no table row); '' for a text that starts as an attribution line."""
    if ATTRIBUTION.match(text):
        return ''
    text = COMMIT_ID.sub(lambda found: '' if re.search(r'\d', found.group()) and re.search(r'[a-f]', found.group())
                         else found.group(), text)
    return ' '.join(re.sub(r'\(\s*\)', '', text.replace('|', '/')).split())


def facts(texts):
    """The non-empty `plain` forms of the texts."""
    return [fact for fact in map(plain, texts) if fact]


def title_line(kind, key, summary):
    """`<kind>(<key>): <summary>` with the summary cut at a word so the whole title is under TITLE_MAX_CHARS."""
    head = f'{kind}({key}): '
    room = TITLE_MAX_CHARS - 1 - len(head)
    summary = plain(summary)
    cut = ''
    for word in summary.split():
        if len(f'{cut} {word}'.strip()) > room:
            break
        cut = f'{cut} {word}'.strip()
    text = (cut or summary[:max(room, 0)]).rstrip(' -—:,;')
    if room < 1 or not text:
        raise RecordError(f'no title under {TITLE_MAX_CHARS} characters: the key "{key}" is too long, or there is '
                          'no summary')
    return head + text


def tested_lines(merged, docs_gate, resolution):
    """The facts of the Tested section: the counts summed over the merged tickets, the docs-gate result, and
    the no-CI line when the `ci` port is on its core default."""
    lines = []
    each = [ticket.metric_counts(parsed) for _, parsed in merged]
    counts = []
    for label, key in ticket.METRIC_COUNTS:
        found = [count[key] for count in each if key in count]
        if key in COUNTED and found:
            counts.append(f'{label} {sum(found)}')
    if counts:
        lines.append('Over the merged tickets: ' + ', '.join(counts))
    if docs_gate:
        lines.append(f'Docs gate: {docs_gate}')
    if ports.port(resolution, 'ci').is_default:
        lines.append(NO_CI_LINE)
    return facts(lines)


def unit_parts(folder, resolution, key_line, docs_gate):
    """(title, why, sections) of a work unit folder; sections is [(name, lines)] after the Why, in body order."""
    tickets = frontier.load_tickets(frontier.tickets_folder(folder), key_line)
    if not tickets:
        raise RecordError(f'{folder}: no ticket files NN-*.md')
    ac_path = frontier.ac_file(folder)
    if ac_path is None:
        raise RecordError(f'{folder}: no {" or ".join(frontier.AC_FILES)}')
    text = files.read_input(ac_path)
    merged = [(path, parsed) for path, parsed in tickets if parsed.status == TICKET_STATUS_DONE]
    ids, _ = check.ac_ids(text)
    missing = [ac for ac, _ in check.uncovered_acs(text, (parsed for _, parsed in merged))]
    criteria = [f'{len(ids) - len(missing)} of {len(ids)} covered'
                + (f'; missing: {", ".join(missing)}' if missing else '')] if ids else []
    decisions = check.read_optional(folder / 'decisions.md') or ''
    breaking = [found for found in map(BREAKING_LINE.match, decisions.splitlines()) if found]
    sections = [
        ('What changed', [f'- {fact}' for fact in facts(parsed.title for _, parsed in merged)]),
        ('Acceptance criteria', criteria),
        ('Still open', [f'- {fact} (ticket {path.name[:2]})' for path, parsed in merged
                        if not NO_OPEN.fullmatch(parsed.open.strip()) and (fact := plain(parsed.open))]),
        ('Breaking changes', [f'- {fact}' for fact in facts(DECISION_TAIL.sub('', found.group(1)) for found in breaking)]),
        ('Tested', [f'- {line}' for line in tested_lines(merged, docs_gate, resolution)]),
        ('How to review', [f'Review the merge commits one at a time, in order: {", ".join(p.stem for p, _ in merged)}.']
         if merged else []),
    ]
    key = next((parsed.key for _, parsed in tickets if parsed.key), NO_KEY)
    summary = ticket.draft_title(ticket.split_lines(text)) or folder.resolve().name
    why = plain(ticket.value_of(ticket.split_lines(text), WHY_KEY) or '')
    return title_line(DEFAULT_TYPE, key, summary), why, sections


def current_branch(repo):
    """The name of the current branch, '' on a detached head."""
    return gitrepo.run(repo, 'branch', '--show-current').stdout.strip()


def branch_type(repo):
    """The type before the first `/` of the current branch name when it is one of BRANCH_TYPES, else `feat`."""
    kind, slash, _ = current_branch(repo).partition('/')
    return kind if slash and kind in BRANCH_TYPES else DEFAULT_TYPE


def branch_subjects(repo, base):
    """The subjects of the commits on the current branch that are not on `base`, oldest first, merges left out."""
    done = gitrepo.run(repo, 'log', '--no-merges', '--reverse', '--format=%s', '--end-of-options', f'{base}..HEAD')
    return done.stdout.splitlines()


def adhoc_parts(path, repo, resolution, key_line):
    """(title, why, sections) of an ad-hoc ticket file."""
    text, parsed = ticket.load(path, key_line)
    why = plain(ticket.value_of(ticket.split_lines(text), WHAT_TO_BUILD_KEY) or '')
    subjects = branch_subjects(repo, resolution.layer.base.value)
    title = title_line(branch_type(repo), parsed.key or NO_KEY, parsed.title.removeprefix(ticket.ADHOC_TITLE_PREFIX))
    return title, why, [('What changed', [f'- {fact}' for fact in facts(subjects)])]


def render(title, why, sections, draft):
    """(file text, body): the file is the Title line, a blank line, then the body."""
    if draft:
        body = '\n'.join(([why] if why else []) + [WIP_LINE])
    else:
        blocks = ([('Why', [why])] if why else []) + sections
        body = '\n\n'.join('\n'.join([f'## {name}', '', *lines]) for name, lines in blocks if lines)
    return f'Title: {title}\n\n{body}\n', body


def check_privacy(label, body):
    """Refuse a body line that `privacy.privacy_problems` names (ADR-0003), naming the section it is in (the last
    `## ` heading before it; a draft body has none). It is the one check `mr body` runs before it writes the file
    and `mr put` runs on the file before it sends the body, which may have been edited by hand."""
    section = 'body'
    for line in body.splitlines():
        if line.startswith('## '):
            section = line[3:].strip()
        problems = privacy.privacy_problems(line)
        if problems:
            raise RecordError(f'{label}: the {section} section holds {" and ".join(problems)}; '
                              'describe it in your own words')


class Target(NamedTuple):
    """What an action works on: `unit` is True for a work unit folder, False for an ad-hoc ticket; `body` is the
    MR body file and `state` the MR file (mr.md) of that unit or ticket."""
    unit: bool
    body: Path
    state: Path


def locate(target):
    """The Target of a work unit folder or an ad-hoc ticket file (a file outside `.anomaly/adhoc/` is refused)."""
    target = Path(target)
    if target.is_dir():
        if frontier.unit_home(target) not in check.OWNER_HOME_DIRS or target.resolve().name == TICKET_ADHOC_DIR.name:
            raise RecordError(f'{target}: not a work-unit folder (a folder in {" or ".join(check.OWNER_HOME_DIRS)}, '
                              f'not {TICKET_ADHOC_DIR.name})')
        return Target(True, target / BODY_FILE, target / STATE_FILE)
    if not target.is_file():
        raise RecordError(f'{target}: not a work-unit folder or a ticket file')
    if target.resolve().parent.name != TICKET_ADHOC_DIR.name:
        raise RecordError(f'{target}: a ticket file must be an ad-hoc ticket (in {TICKET_ADHOC_DIR}); '
                          'give the work-unit folder for a unit')
    return Target(False, target.with_name(target.stem + ADHOC_SUFFIX), target.with_name(target.stem + ADHOC_STATE_SUFFIX))


def run_body(args, environ):
    home = paths.resolve_home(args.home, environ)
    key_line = ports.key_line(home)
    target = Path(args.target)
    docs_gate = None
    if args.docs_gate is not None:
        docs_gate = records.require_one_line('--docs-gate', args.docs_gate)
        privacy.check_text('mr body', '--docs-gate', docs_gate)
    found = locate(target)
    if found.unit:
        parts = unit_parts(target, ports.resolve(home), key_line, docs_gate)
    else:
        if docs_gate is not None:
            raise RecordError('--docs-gate is for a work unit: the light-path body has no Tested section')
        repo = gitrepo.repo_for(args.repo)
        parts = adhoc_parts(target, repo, ports.resolve(home, repo), key_line)
    text, body = render(*parts, args.draft)
    check_privacy('mr body', body)
    size = len(body.encode('utf-8'))
    files.write_text(found.body, text)
    print(found.body)
    if size > BODY_WARN_BYTES:
        print(f'warning: the body is {size} bytes, over 2.5 KB ({BODY_WARN_BYTES}); shorten it', file=sys.stderr)
    return 0


# ---------- put, ready, show, reviewed and verified ----------

def read_state(path):
    """{label: value} of the lines of the MR file that have a value; {} when the file is absent."""
    if not path.is_file():
        return {}
    lines = ticket.split_lines(ticket.read_text(path, 'MR file'))
    return {label: value for label in STATE_LABELS if (value := ticket.value_of(lines, label))}


def write_state(path, state):
    """The MR file: the lines of `state` in STATE_LABELS order."""
    files.write_text(path, ''.join(f'{label}: {state[label]}\n' for label in STATE_LABELS if label in state))


def read_title_and_body(path, target):
    """(title, body) of an MR body file: the title from the first `Title:` line, the body from the lines after the
    blank line that follows it."""
    if not path.is_file():
        raise RecordError(f'{path}: no MR body file; run `mr body {target}` first')
    lines = files.read_input(path).splitlines()
    title = TITLE_LINE.fullmatch(lines[0]) if lines else None
    if title is None or len(lines) < 2 or lines[1].strip():
        raise RecordError(f'{path}: the file does not start with a `Title: <text>` line and a blank line; '
                          f'run `mr body {target}` again')
    return title[1], '\n'.join(lines[2:]).strip()


def adapter_name(resolution):
    """The name of the MR tool the `mr` port names (checked against constants.MR_ADAPTERS), or None on the core default."""
    adapter = ports.port(resolution, 'mr')
    if adapter.is_default:
        return None
    if adapter.value not in constants.MR_ADAPTERS:
        raise RecordError(f'profile key mr_tool: unknown MR adapter {adapter.value!r} '
                          f'(accepted: {", ".join(constants.MR_ADAPTERS)})')
    return adapter.value


def project_of(repo, name):
    """The project of the `origin` remote for the adapter `name`, or None when there is no origin. An origin on
    another host than the adapter's (a self-hosted one too) is an error naming the host."""
    found = gitrepo.origin_host_project(repo)
    if found is None:
        return None
    host, project = found
    if host != ADAPTERS[name].HOST:
        raise RecordError(f'the origin remote is on {host}, but the {name} adapter works with {ADAPTERS[name].HOST} only')
    return project


def call(function, *args, **kwargs):
    """function(*args, **kwargs), with the error of an MR tool as a RecordError."""
    try:
        return function(*args, **kwargs)
    except ADAPTER_ERRORS as error:
        raise RecordError(str(error)) from None


def mr_number(link, state_file):
    found = MR_NUMBER.fullmatch(link)
    if found is None:
        raise RecordError(f'{state_file}: the MR line has no merge request number at the end of its link')
    return found[1]


def print_only(title, body, reason):
    """The core-default `put`: the title and the body for the user to paste; nothing leaves the machine."""
    print(f'Title: {title}\n\n{body}')
    print(f'note: nothing was sent: {reason}', file=sys.stderr)


def check_same_mr(tool, project, number, link, repo, environ):
    """Refuse (before a change) an MR line that is not this repository's MR of the current branch: the MR the
    origin project answers for `number` must have the link of the MR line, and its source branch must be the
    current branch. A link of another project, or a stale or hand-written one, never changes another MR."""
    shown, _, _, source = call(tool.view_mr, project, number, environ=environ)
    if shown.rstrip('/').lower() != link.rstrip('/').lower():
        raise RecordError(f'the MR line names {link}, but merge request {number} of the origin project is {shown}; '
                          'it is not an MR of this repository')
    branch = current_branch(repo)
    if source != branch:
        raise RecordError(f'the MR {link} has the source branch "{source}", but the current branch is '
                          f'"{branch or "(detached head)"}"; check out the branch of the MR')


def run_put(args, environ):
    home = paths.resolve_home(args.home, environ)
    found = locate(args.target)
    repo = gitrepo.repo_for(args.repo)
    resolution = ports.resolve(home, repo)
    name = adapter_name(resolution)
    title, body = read_title_and_body(found.body, args.target)
    check_privacy('mr put', body)
    if name is None:
        print_only(title, body, 'the mr port is on its core default')
        return 0
    project = project_of(repo, name)
    if project is None:
        print_only(title, body, 'the repository has no origin remote')
        return 0
    tool = ADAPTERS[name]
    state = read_state(found.state)
    if MR_LABEL in state:
        number = mr_number(state[MR_LABEL], found.state)
        check_same_mr(tool, project, number, state[MR_LABEL], repo, environ)
        call(tool.update_mr, project, number, body, environ=environ)
    else:
        branch = current_branch(repo)
        if not branch:
            raise RecordError('the head is detached: check out the branch of the work to open its MR')
        state[MR_LABEL] = call(tool.create_mr, project, title, body, branch, resolution.layer.base.value,
                               environ=environ)
        write_state(found.state, state)
    print(state[MR_LABEL])
    return 0


def existing_mr(args, environ):
    """(adapter module, project, number, link, repo) of the MR in the MR file, for `ready` and `show`."""
    home = paths.resolve_home(args.home, environ)
    found = locate(args.target)
    repo = gitrepo.repo_for(args.repo)
    name = adapter_name(ports.resolve(home, repo))
    if name is None:
        raise RecordError('the mr port is on its core default: there is no MR tool to call (set mr_tool in the profile)')
    link = read_state(found.state).get(MR_LABEL)
    if link is None:
        raise RecordError(f'{found.state}: no MR line; run `mr put {args.target}` first')
    project = project_of(repo, name)
    if project is None:
        raise RecordError('the repository has no origin remote: there is no MR to call')
    return ADAPTERS[name], project, mr_number(link, found.state), link, repo


def run_ready(args, environ):
    tool, project, number, link, repo = existing_mr(args, environ)
    check_same_mr(tool, project, number, link, repo, environ)
    call(tool.ready_mr, project, number, environ=environ)
    print(f'{link}\nstate: ready for review')
    return 0


def run_show(args, environ):
    tool, project, number, *_ = existing_mr(args, environ)
    link, state, draft, _ = call(tool.view_mr, project, number, environ=environ)
    print(f'{link}\nstate: {state}{", draft" if draft else ""}')
    return 0


def write_gate(args, label):
    found = locate(args.target)
    if not found.unit:
        raise RecordError(f'{args.target}: mr {label.lower()} is for a work-unit folder; an ad-hoc ticket keeps its '
                          f'own line: run `ticket {label.lower()} <ticket> <sha>`')
    sha = gitrepo.require_commit(gitrepo.repo_for(args.repo), args.ref)
    state = read_state(found.state)
    state[label] = sha
    write_state(found.state, state)
    print(f'{label}: {sha}')
    return 0


def run_reviewed(args, environ):
    return write_gate(args, REVIEWED_LABEL)


def run_verified(args, environ):
    return write_gate(args, VERIFIED_LABEL)

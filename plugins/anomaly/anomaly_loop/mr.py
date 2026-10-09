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
`warning:` line and is still written. The file path is printed.
"""
import re
import sys
from pathlib import Path

from . import check, files, frontier, gitrepo, paths, ports, privacy, records, ticket
from .constants import TICKET_ADHOC_DIR, TICKET_STATUS_DONE
from .files import RecordError

BODY_FILE = 'mr-body.md'                 # in a work unit folder
ADHOC_SUFFIX = '.mr-body.md'             # after the name of an ad-hoc ticket, beside it
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
    ac_file = next((name for name in frontier.AC_FILES if (folder / name).is_file()), None)
    if ac_file is None:
        raise RecordError(f'{folder}: no {" or ".join(frontier.AC_FILES)}')
    text = files.read_input(folder / ac_file)
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


def branch_type(repo):
    """The type before the first `/` of the current branch name when it is one of BRANCH_TYPES, else `feat`."""
    branch = gitrepo.run(repo, 'branch', '--show-current').stdout.strip()
    kind, slash, _ = branch.partition('/')
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
    """The file text: the Title line, a blank line, then the body."""
    if draft:
        body = '\n'.join(([why] if why else []) + [WIP_LINE])
    else:
        blocks = ([('Why', [why])] if why else []) + sections
        body = '\n\n'.join('\n'.join([f'## {name}', '', *lines]) for name, lines in blocks if lines)
    return f'Title: {title}\n\n{body}\n', len(body.encode('utf-8'))


def run_body(args, environ):
    home = paths.resolve_home(args.home, environ)
    key_line = ports.key_line(home)
    target = Path(args.target)
    docs_gate = None
    if args.docs_gate is not None:
        docs_gate = records.require_one_line('--docs-gate', args.docs_gate)
        privacy.check_text('mr body', '--docs-gate', docs_gate)
    if target.is_dir():
        parts = unit_parts(target, ports.resolve(home), key_line, docs_gate)
        out = target / BODY_FILE
    elif target.is_file():
        if target.resolve().parent.name != TICKET_ADHOC_DIR.name:
            raise RecordError(f'{target}: a ticket file must be an ad-hoc ticket (in {TICKET_ADHOC_DIR}); '
                              'give the work-unit folder for a unit')
        if docs_gate is not None:
            raise RecordError('--docs-gate is for a work unit: the light-path body has no Tested section')
        repo = gitrepo.repo_for(args.repo)
        parts = adhoc_parts(target, repo, ports.resolve(home, repo), key_line)
        out = target.with_name(target.stem + ADHOC_SUFFIX)
    else:
        raise RecordError(f'{target}: not a work-unit folder or a ticket file')
    text, size = render(*parts, args.draft)
    files.write_text(out, text)
    print(out)
    if size > BODY_WARN_BYTES:
        print(f'warning: the body is {size} bytes, over 2.5 KB ({BODY_WARN_BYTES}); shorten it', file=sys.stderr)
    return 0

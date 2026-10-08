"""check: the invariants the pipeline enforces from ticket files and git, as one command.

  pre-merge   exit 0 only when `Reviewed:` and `Verified:` both name the head being merged and the
              acceptance test is unchanged since its red commit (or the ticket notes why)
  stories     exit 1 when stories.md or decisions.md of a work unit breaks the shapes in
              docs/formats.md; oversize files only warn

`stories` prints each error as one line, `<file>:<line>: <problem> (<allowed shape>)`, then each
warning as `warning: <file>: ...`; it exits 1 on any error, 0 otherwise (clean prints one
`stories check passed` line), and 2 with one `anomaly:` line for a folder that is not there.

The next two paragraphs are about pre-merge only. Each failed invariant is one line on stdout, named by its ticket line (`Reviewed:`, `Verified:`,
`Red:`, `Test:`), and the exit code is 1, as for `ticket gate`; an error (a missing ticket, a head that
is not a commit) is one `anomaly:` line and exit 2. Nothing is written but the index's file stats:
`git update-index --refresh` runs first, so a file dirty by its stat only (for example a line-ending
change) cannot make the merge that follows refuse. A passing check prints a
`note:` line for a test file excused by `Red-changed:`, then one `passed` line. The ticket lines are read
with ticket.load; every commit id in them is normalised with git before it is compared, so a short
id equals the full one. The test file is read from git at the `Red:` commit and at the head.

A `Red-changed:` line excuses a change to the test file since the `Red:` commit, and also a missing
`Red:` line (a docs-only ticket has no acceptance test); the check then passes and prints the reason
as a `note:` line. The ticket keeps no order between its lines, so `ticket red` removes the earlier
`Red-changed:` lines when it records the first `Red:` line or a different sha: each reason covers
only the edits after the red commit it was written for.
"""
import argparse
import re
from pathlib import Path

from . import files, gitrepo, ticket
from .constants import TICKET_FIELD_SEPARATOR


def head_problem(repo, key, value, head):
    """One line when the ticket's `<key>:` value is not the head being merged, else None."""
    if not value:
        return f'{key}: no {key}: line; the head being merged ({gitrepo.short(head)}) has no record'
    found = ticket.named_commit(repo, value)
    if found is None:
        return f'{key}: {ticket.not_a_commit(value)}'
    if found != head:
        return f'{key}: {value} is not the head being merged ({gitrepo.short(head)})'
    return None


def acceptance_test_result(repo, parsed, head):
    """(problem, note) for the acceptance test rule: the file at the head equals the file at the
    `Red:` commit, or a `Red-changed:` line says why it changed or why there is no `Red:` line. At
    most one of the two is set."""
    reasons = '; '.join(parsed.red_changed)
    if parsed.red is None:
        if parsed.red_changed:
            return None, f'note: no Red: line; the ticket says why: {reasons}'
        return ('Red: no Red: line; the acceptance test cannot be checked '
                '(record the red commit with ticket red)'), None
    sha, path = parsed.red
    if not path:
        return f'Red: the line is not "<sha>{TICKET_FIELD_SEPARATOR}<test path>"', None
    path = path.replace('\\', '/')
    red = ticket.named_commit(repo, sha)
    if red is None:
        return f'Red: {ticket.not_a_commit(sha)}', None
    at_red = gitrepo.file_at(repo, red, path)
    if at_red is None:
        return f'Red: {path} is not in the red commit {gitrepo.short(red)}', None
    at_head = gitrepo.file_at(repo, head, path)
    if at_head == at_red:
        return None, None
    if parsed.red_changed:
        return None, f'note: {path} changed since its red commit {gitrepo.short(red)}; the ticket says why: {reasons}'
    what = 'is not in the head' if at_head is None else 'changed'
    return f'Test: {path} {what} since its red commit {gitrepo.short(red)} and the ticket has no Red-changed: line', None


def pre_merge(repo, parsed, head):
    """(problems, notes) for a ticket and the head being merged."""
    problems = [head_problem(repo, key, value, head)
                for key, value in (('Reviewed', parsed.reviewed), ('Verified', parsed.verified))]
    problem, note = acceptance_test_result(repo, parsed, head)
    problems.append(problem)
    return [line for line in problems if line], [note] if note else []


# ---------- stories ----------

STORIES_WARN_BYTES = 6 * 1024
DECISIONS_WARN_BYTES = 8 * 1024
AC_LINE = re.compile(r'^- (AC-\d+):')
D_LINE = re.compile(r'^- D-\d+:')
SPECIFY_LINE = re.compile(r'^\S+ \S+ specify:')
SPECIFY_IDS = re.compile(r'^\S+ \S+ specify: ACs: ([^;]*);')
# The shapes below are the exact text of docs/formats.md; a test holds them to it.
AC_SHAPE = '- AC-1: <criterion>'
D_SHAPE = '- D-n: <decision>. Why: <one line>. Source: <where>'
SPECIFY_SHAPE = 'ACs: AC-1, AC-2, …;'
OWNER_SHAPE = '- <item> — owner: <unit, ticket or ADR>'


def read_optional(path):
    """The text of a file, or None when it is not there."""
    return files.read_input(path) if path.is_file() else None


def stories_errors(text):
    """Errors for stories.md: duplicate AC ids and Out of scope lines with no owner. Also the ids found."""
    errors, found, in_scope_out = [], {}, False
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith('#'):
            in_scope_out = line.strip().lower() == '## out of scope'
        match = AC_LINE.match(line)
        if match:
            ac = match.group(1)
            if ac in found:
                errors.append(f'stories.md:{number}: {ac} is already used on line {found[ac]}; '
                              f'each AC id is unique ({AC_SHAPE})')
            else:
                found[ac] = number
        elif in_scope_out and line.startswith('- ') and 'owner:' not in line:
            errors.append(f'stories.md:{number}: an Out of scope line needs an owner ({OWNER_SHAPE})')
    return errors, found


def decisions_errors(text):
    """Errors for decisions.md: a `- D-<n>:` line with no `Source:`. A `T-n` line needs none."""
    return [f'decisions.md:{number}: a decision needs a Source: ({D_SHAPE})'
            for number, line in enumerate(text.splitlines(), 1)
            if D_LINE.match(line) and 'Source:' not in line]


def logged_ac_ids(text):
    """(ids, errors) for the `specify:` lines of log.md: ids maps each AC id to the number of the
    first line that names it, in order; a `specify:` line without the `ACs: ...;` shape is an error."""
    ids, errors = {}, []
    for number, line in enumerate(text.splitlines(), 1):
        if not SPECIFY_LINE.match(line):
            continue
        match = SPECIFY_IDS.match(line)
        if not match:
            errors.append(f'log.md:{number}: a specify: line must start its text with the ids '
                          f'({SPECIFY_SHAPE})')
            continue
        for ac in re.findall(r'AC-\d+', match.group(1)):
            ids.setdefault(ac, number)
    return ids, errors


def stories(folder):
    """(errors, warnings) for a work-unit folder, each a list of one-line strings. A missing
    stories.md is an error line; a missing decisions.md or log.md is empty (no decisions, no
    recorded ids). Sizes over 6 KB (stories.md) and 8 KB (decisions.md) only warn."""
    folder = Path(folder)
    if not folder.is_dir():
        raise files.RecordError(f'{folder}: not a folder')
    errors, warnings = [], []
    stories_text = read_optional(folder / 'stories.md')
    decisions_text = read_optional(folder / 'decisions.md')
    log_text = read_optional(folder / 'log.md')
    if stories_text is None:
        errors.append('stories.md: the file is missing (a work unit keeps its stories in stories.md)')
    else:
        found_errors, found = stories_errors(stories_text)
        errors.extend(found_errors)
        logged, log_errors = logged_ac_ids(log_text or '')
        errors.extend(log_errors)
        errors.extend(f'log.md:{number}: {ac} was named by a specify: line and is gone from stories.md; '
                      f'an AC id is never renumbered (a withdrawn AC stays in place with an '
                      f'"Amended <date>:" line)'
                      for ac, number in logged.items() if ac not in found)
        if len(stories_text.encode('utf-8')) > STORIES_WARN_BYTES:
            warnings.append('stories.md: over 6 KB; consider splitting the work unit')
    if decisions_text is not None:
        errors.extend(decisions_errors(decisions_text))
        if len(decisions_text.encode('utf-8')) > DECISIONS_WARN_BYTES:
            warnings.append('decisions.md: over 8 KB; consider moving settled decisions out')
    return errors, warnings


# ---------- the command line ----------

def register(commands, common):
    command = commands.add_parser('check', help='check the invariants the pipeline enforces')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    merge = actions.add_parser(
        'pre-merge', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 0 only when the ticket may be merged; name each failed invariant (exit 1)',
        description=('Exit 0 only when Reviewed: and Verified: both name the head being merged and the\n'
                     'acceptance test is unchanged since its Red: commit, or a Red-changed: line says why.\n'
                     'Each failed invariant is one line on stdout and the exit code is 1; an error is exit 2.\n'
                     'A Red-changed: line also excuses a missing Red: line (a docs-only ticket); the reason\n'
                     'is printed as a note: line. ticket red removes earlier Red-changed: lines when it\n'
                     'records the first Red: line or a different sha. Nothing is written except the index\'s\n'
                     'file stats (git update-index --refresh runs first); run it in the checkout that will merge.'))
    merge.add_argument('ticket', help='path of the ticket file')
    merge.add_argument('--head', default='HEAD',
                       help='the commit being merged: a commit id or a branch (default: HEAD of --repo)')
    merge.add_argument('--repo', help=gitrepo.REPO_HELP)
    merge.set_defaults(handler=run_pre_merge)
    check_stories = actions.add_parser(
        'stories', parents=[common], formatter_class=argparse.RawDescriptionHelpFormatter,
        help='exit 1 when stories.md or decisions.md of a work unit breaks its shape',
        description=('Check a work-unit folder against the shapes in docs/formats.md. Errors: a duplicate AC id,\n'
                     'an AC id that a specify: line of log.md named and stories.md no longer holds, a D-n line\n'
                     'with no Source:, an Out of scope line with no owner:. Warnings: stories.md over 6 KB,\n'
                     'decisions.md over 8 KB. Each is one line on stdout; exit 1 on any error, 0 otherwise;\n'
                     'an error (a folder that is not there) is one anomaly: line and exit 2.'))
    check_stories.add_argument('folder', help='the work-unit folder (holds stories.md)')
    check_stories.set_defaults(handler=run_stories)


def run_stories(args, environ):
    errors, warnings = stories(args.folder)
    for line in errors:
        print(line)
    for line in warnings:
        print(f'warning: {line}')
    if errors:
        return 1
    print(f'stories check passed for {Path(args.folder).name}')
    return 0


def run_pre_merge(args, environ):
    _, parsed = ticket.load(args.ticket)
    repo = gitrepo.repo_for(args.repo)
    head = gitrepo.require_commit(repo, args.head)
    gitrepo.refresh_index(repo)
    problems, notes = pre_merge(repo, parsed, head)
    if problems:
        for line in problems:
            print(line)
        return 1
    for line in notes:
        print(line)
    print(f'pre-merge check passed for {Path(args.ticket).name} at {gitrepo.short(head)}')
    return 0

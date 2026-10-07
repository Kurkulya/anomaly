"""check: the invariants the pipeline enforces from ticket files and git, as one command.

  pre-merge   exit 0 only when `Reviewed:` and `Verified:` both name the head being merged and the
              acceptance test is unchanged since its red commit (or the ticket notes why)

Each failed invariant is one line on stdout, named by its ticket line (`Reviewed:`, `Verified:`,
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
from pathlib import Path

from . import gitrepo, ticket
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

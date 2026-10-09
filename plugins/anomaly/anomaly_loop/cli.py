"""Command-line front of the anomaly plugin: a thin dispatcher over the subcommand registry.

  python scripts/anomaly.py <command> [--home DIR] [--data DIR] ...

Each area module that offers a subcommand exposes `register(commands, common)` and is named
once in COMMANDS; it adds its parser (with `parents=[common]`) and sets `handler`. A handler is `handler(args, environ) -> int`:
0 for success, or 1 for a negative result that is not an error (`ticket gate` with an open or unreadable
blocker, `check pre-merge` with a failed rule, `frontier` with no startable ticket, `ci` with a red job); `ci` also returns its own 3 (still running), 4 (the CI tool never answered:
it prints one `anomaly:` line itself) and 5 (no pipeline yet: a plain message, not an error),
documented in its help. 2 is only the error below, with one `anomaly:` line;
errors raise paths.PathError, records.RecordError, gitrepo.GitError, glab.CiError or OSError and are printed as
`anomaly: <message>` with exit 2. A usage error (an unknown command, a missing or bad option) is
printed the same way: Parser replaces argparse's usage block and its own exit.
Handlers never read the clock: `args.now` (aware datetime) and `args.today` (its date) are
set here, and tests pass `now`.
"""
import argparse
import os
import sys
from datetime import datetime
from importlib import import_module

from . import gitrepo, glab, paths, records

# Subcommand modules, by name, in help order.
COMMANDS = (
    'metrics',
    'index',
    'observe',
    'digest',
    'assess',
    'nudge',
    'calibrate',
    'ticket',
    'ports',
    'bench',
    'check',
    'seams',
    'ci',
    'risk',
    'lens',
    'worklog',
    'log',
    'frontier',
)


class UsageError(Exception):
    """A command line that does not parse; main prints it like any other error."""


class Parser(argparse.ArgumentParser):
    """argparse with the CLI error contract: a usage error raises UsageError instead of printing the
    usage and exiting. Subcommand parsers are made of the same class (add_subparsers uses the
    class of the parser it is called on)."""

    def error(self, message):
        raise UsageError(message)


def command_modules():
    return [import_module(f'.{name}', __package__) for name in COMMANDS]


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--home', help='home folder (durable loop data; default: env '
                                       f'CLAUDE_PLUGIN_OPTION_HOME, then {paths.DEFAULT_HOME})')
    common.add_argument('--data', help='throwaway state folder (default: env CLAUDE_PLUGIN_DATA; no fallback)')
    parser = Parser(prog='anomaly', description='Feedback loop helpers for Claude Code.')
    commands = parser.add_subparsers(dest='command', required=True, metavar='command')
    for module in command_modules():
        module.register(commands, common)
    return parser


def main(argv=None, environ=None, now=None):
    environ = os.environ if environ is None else environ
    try:
        args = build_parser().parse_args(argv)
    except UsageError as error:
        print(f'anomaly: {error}', file=sys.stderr)
        return 2
    args.now = now or datetime.now().astimezone()
    args.today = args.now.date()
    try:
        notice = paths.home_notice(args.home, environ)
        if notice:
            print(notice)
        return args.handler(args, environ)
    except (paths.PathError, records.RecordError, gitrepo.GitError, glab.CiError, OSError) as error:
        print(f'anomaly: {error}', file=sys.stderr)
        return 2

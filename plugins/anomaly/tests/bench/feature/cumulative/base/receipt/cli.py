"""The command line: `receipt total FILE`."""
import sys

from . import total


def main(argv):
    """Run one command; return the exit code."""
    if len(argv) != 2 or argv[0] != 'total':
        print('usage: receipt total FILE', file=sys.stderr)
        return 2
    with open(argv[1], encoding='utf-8') as handle:
        print(f'total: {total.total_of(handle.read())}')
    return 0

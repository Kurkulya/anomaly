"""The tally command line."""
import argparse

from . import counter, source


def build_parser():
    parser = argparse.ArgumentParser(prog='tally')
    commands = parser.add_subparsers(dest='command', required=True)
    count = commands.add_parser('count', help='count the lines or the words of a file')
    count.add_argument('file')
    count.add_argument('--words', action='store_true', help='count words instead of lines')
    count.add_argument('--verbose', action='store_true', help='print the file name before the count')
    return parser


def file_label(args):
    """The text printed before a count: the file name with --verbose, else nothing."""
    return f'{args.file}: ' if args.verbose else ''


def main(argv=None):
    """Print the count of one file."""
    args = build_parser().parse_args(argv)
    text = source.read_text(args.file)
    if args.words:
        number, unit = counter.count_words(text), 'words'
    else:
        number, unit = counter.count_lines(text), 'lines'
    print(f'{file_label(args)}{number} {unit}')
    return 0

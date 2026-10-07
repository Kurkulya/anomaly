"""The tally command line."""
import argparse

from . import counter, source


def build_parser():
    parser = argparse.ArgumentParser(prog='tally')
    commands = parser.add_subparsers(dest='command', required=True)
    count = commands.add_parser('count', help='count the lines or the words of a file')
    count.add_argument('file')
    count.add_argument('--by-word', action='store_true', help='count words instead of lines')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    text = source.read_text(args.file)
    number = counter.count_words(text) if args.by_word else counter.count_lines(text)
    print(number)
    return 0

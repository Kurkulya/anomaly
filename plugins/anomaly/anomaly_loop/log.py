"""log: the one writer of a work unit's `log.md` (docs/formats.md owns the line shape).

  log add FOLDER --stage S TEXT    append `<YYYY-MM-DD HH:MM> <stage>: <text>` to FOLDER/log.md

The time is the CLI clock in constants.TICKET_TIME_FORMAT; the model passes none. The file is made when
it is missing and its earlier bytes are kept as they are; the new line takes the file's line ending
(CRLF when the file holds one, else LF). A folder that does not exist, a stage that is not one word, and
text that is empty or breaks the line are refused with no write; the folder is never created. Any
existing folder is allowed, inside `.anomaly/` or `.scratch/` or not.
"""
from . import files, paths, privacy, records
from .constants import TICKET_TIME_FORMAT
from .files import RecordError

LABEL = 'log'
FILE_NAME = 'log.md'


def register(commands, common):
    command = commands.add_parser('log', help="write a work unit's log.md")
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    add = actions.add_parser('add', parents=[common], help='append one line to the log.md of a work-unit folder')
    add.add_argument('folder', help='the work-unit folder; it must exist')
    add.add_argument('--stage', required=True, help='the pipeline stage, one word, such as build or review')
    add.add_argument('text', help='the log text, one line')
    add.set_defaults(handler=run_add)


def line_ending(existing):
    return '\r\n' if '\r\n' in existing else '\n'


def run_add(args, environ):
    folder = paths.expand(args.folder)
    if not folder.is_dir():
        raise RecordError(f'{LABEL}: not a folder: {args.folder}')
    privacy.check_identifier(LABEL, 'stage', args.stage)
    if ':' in args.stage:
        raise RecordError(f'{LABEL}: stage must not hold ":"')
    text = records.require_one_line(f'{LABEL}: the text', args.text)
    path = folder / FILE_NAME
    existing = files.read_input(path, keep_bom=True) if path.is_file() else ''
    ending = line_ending(existing)
    if existing and not existing.endswith('\n'):
        existing += ending
    stamp = args.now.strftime(TICKET_TIME_FORMAT)
    files.write_text(path, f'{existing}{stamp} {args.stage}: {text}{ending}')
    print(f'log: {path}')
    return 0

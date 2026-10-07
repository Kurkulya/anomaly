"""log: the one writer of a work unit's `log.md` (docs/formats.md owns the line shape).

  log add FOLDER --stage S [--] TEXT    append `<YYYY-MM-DD HH:MM> <stage>: <text>` to FOLDER/log.md

The time is the CLI clock in constants.TICKET_TIME_FORMAT (worklog.now_text); the model passes none. The
file is made when it is missing and is only appended to, so earlier bytes (a byte order mark included) are
never rewritten. The new line takes the line ending the file already uses (ticket.line_ending: the first
one found, else LF); a last line without an ending gets one first. A folder that does not exist, a stage
that is not one word, and text that is empty or breaks the line are refused with no write; the folder is
never created. Any existing folder is allowed, inside `.anomaly/` or `.scratch/` or not.
"""
from . import files, paths, privacy, records, ticket, worklog
from .files import RecordError

LABEL = 'log'
FILE_NAME = 'log.md'


def register(commands, common):
    command = commands.add_parser('log', help="write a work unit's log.md")
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    add = actions.add_parser('add', parents=[common], help='append one line to the log.md of a work-unit folder')
    add.add_argument('folder', help='the work-unit folder; it must exist')
    add.add_argument('--stage', required=True, help='the pipeline stage, one word, such as build or review')
    add.add_argument('text', help='the log text, one line; put `--` before a text that starts with `-`')
    add.set_defaults(handler=run_add)


def run_add(args, environ):
    folder = paths.expand(args.folder)
    if not folder.is_dir():
        raise RecordError(f'{LABEL}: not a folder: {args.folder}')
    if not privacy.is_identifier(args.stage) or ':' in args.stage:   # a ":" would end the stage in the line
        raise RecordError(f'{LABEL}: stage must be one word of letters, digits and . _ - '
                          f'(at most {privacy.IDENTIFIER_MAX_CHARS} characters), with no spaces or line breaks')
    text = records.require_one_line(f'{LABEL}: the text', args.text)
    path = folder / FILE_NAME
    lines = ticket.split_lines(files.read_input(path, keep_bom=True)) if path.is_file() else []
    ending = ticket.line_ending(lines)
    separator = ending if lines and not lines[-1][1] else ''
    line = f'{separator}{worklog.now_text(args)} {args.stage}: {text}{ending}'
    files.append_text(path, line)
    print(f'log: {path}')
    return 0

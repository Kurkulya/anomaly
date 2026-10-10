"""A user's addenda files in home (ADR-0021): one file per plugin skill (`addenda/<skill>.md`) or agent
(`addenda/agents/<agent>.md`), each line one rule tied to one experiment, at most ADDENDA_MAX_LINES lines.

A line is written as `<rule> [exp: <signature> · <stamp>]`. The stamp is 8 hex characters of sha256 over
the text the line adds to: the sorted relative paths and bytes of every file in the skill folder, or the
bytes of the one agent file, so it changes only when that skill or agent changes.
"""
import hashlib
from pathlib import Path

from . import files
from .constants import ADDENDA_DIR, ADDENDA_MAX_LINES
from .files import RecordError

AGENTS = 'agents'          # the agent files of the plugin, and their addenda files in home
NO_ADDENDA = ('measure',)  # skills that take no addenda file
STAMP_CHARS = 8
TAG_OPEN, TAG_SEPARATOR, TAG_CLOSE = '[exp: ', ' · ', ']'   # the tag `[exp: <signature> · <stamp>]`


def addendum_path(home, name, agent=False):
    """The addenda file of the skill or agent `name` in home."""
    folder = Path(home) / ADDENDA_DIR
    return (folder / AGENTS if agent else folder) / f'{name}.md'


def stamp(target):
    """The stamp of a skill folder or of one agent file (see the module text)."""
    target = Path(target)
    digest = hashlib.sha256()
    if target.is_file():
        digest.update(target.read_bytes())
    else:
        found = sorted((item.relative_to(target).as_posix(), item) for item in target.rglob('*') if item.is_file())
        for relative, item in found:
            data = item.read_bytes()
            digest.update(f'{relative}\0{len(data)}\0'.encode('utf-8'))
            digest.update(data)
    return digest.hexdigest()[:STAMP_CHARS]


def read_lines(path):
    """The non-blank lines of an addenda file; [] when it is missing."""
    try:
        text = files.read_input(path)
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def append_line(path, line, signature, stamp):
    """Add `line` tagged with its experiment and stamp as the file's last line; returns the tagged line.
    A file that already holds ADDENDA_MAX_LINES lines, or a line of this experiment, raises RecordError and
    is not changed: one line is one experiment."""
    lines = read_lines(path)
    if any(f'{TAG_OPEN}{signature}{TAG_SEPARATOR}' in old for old in lines):
        raise RecordError(f'{path}: already holds a line of the experiment {signature}, and one line is one '
                          'experiment; remove the old line from this file first, then run the fix again')
    if len(lines) >= ADDENDA_MAX_LINES:
        raise RecordError(f'{path}: holds {len(lines)} lines, the cap of an addenda file is {ADDENDA_MAX_LINES}; '
                          'drop or upstream a line first')
    tagged = f'{line} {TAG_OPEN}{signature}{TAG_SEPARATOR}{stamp}{TAG_CLOSE}'
    files.write_lines(path, lines + [tagged])
    return tagged

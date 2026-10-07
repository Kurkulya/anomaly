"""Reading and writing loop files: JSON lines and atomic whole-file writes, UTF-8 with LF; and
the one reader of a UTF-8 text input (a record file, a batch, an option's file or standard input)."""
import json
import os
import sys
from pathlib import Path


class RecordError(ValueError):
    """A loop file or record that cannot be used as it is; the CLI prints it as `anomaly: ...`.
    Code outside this module uses it as records.RecordError."""


def read_input(source, keep_bom=False):
    """The text of `source`: standard input for `-`, else the file at that path. Read as bytes and
    decoded as UTF-8 (a byte order mark is ignored unless `keep_bom`, which leaves it as the
    first character, for a caller that writes the text back), so the console code page never
    matters and no line ending is translated; bytes that are not UTF-8 raise RecordError naming the
    source. A missing file raises OSError."""
    stdin = source == '-'
    data = sys.stdin.buffer.read() if stdin else Path(source).read_bytes()
    try:
        return data.decode('utf-8' if keep_bom else 'utf-8-sig')
    except UnicodeDecodeError as error:
        name = 'standard input' if stdin else str(source)
        raise RecordError(f'{name}: not UTF-8 text (byte {error.start})') from None


def write_text(path, text):
    """Replace the file with exactly this text, as UTF-8 with no line ending translation, in one
    step (temporary file, then rename). Missing parent folders are made."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(text.encode('utf-8'))
    os.replace(tmp, path)


def write_lines(path, lines):
    """Replace the file with these lines, each ending in LF, in one step."""
    write_text(path, ''.join(line + '\n' for line in lines))


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def load_lines(path):
    """JSON objects of a JSON-lines file; a missing file is empty and other non-blank lines are
    skipped. A file that is not UTF-8 raises RecordError naming it."""
    items = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    item = json.loads(line)
                except ValueError:
                    item = None
                if isinstance(item, dict):
                    items.append(item)
    except UnicodeDecodeError:
        raise RecordError(f'{path}: not UTF-8 text') from None
    except OSError:
        pass
    return items


def append_line(path, obj):
    """Add one JSON object as the last line; earlier lines are never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8', newline='\n') as f:
        f.write(dump(obj) + '\n')

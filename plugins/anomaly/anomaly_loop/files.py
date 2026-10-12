"""Reading and writing loop files: JSON lines, atomic whole-file writes and a raw `append_text` (UTF-8, no line
ending translation); and the one reader of a UTF-8 text input (a record file, a batch, an option's file or stdin)."""
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_POLL_SECONDS = 0.05


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


def append_text(path, text, *, no_follow=False):
    """Add this text at the end of the file, as UTF-8 with no line ending translation; earlier bytes are
    never rewritten. The file and its missing parent folders are made. With no_follow, a path that is a
    symlink is not opened (OSError, errno ELOOP) where the platform has os.O_NOFOLLOW."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if no_follow and hasattr(os, 'O_NOFOLLOW'):
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o666)
        with os.fdopen(fd, 'ab') as f:
            f.write(text.encode('utf-8'))
        return
    with open(path, 'ab') as f:
        f.write(text.encode('utf-8'))


@contextmanager
def file_lock(path, wait, stale):
    """Hold the lock file `path` for the block: yields True when this run made it (`O_CREAT|O_EXCL`, with a
    token of this run written into it), False when another run still held it after `wait` seconds (that
    lock is left in place). A lock whose age (now minus the lock path's own modification time, by lstat, so
    a symlink is aged by the link) is over `stale` seconds is removed each time one is found. After the
    first such removal of a call the lock is made again at once, even when `wait` is over; after a later
    one the run goes on as for a held lock: it waits one poll before the next try, or gives up when `wait`
    is over. A PermissionError while no lock file exists is tried once more after a short pause and then
    raised (a folder that cannot be written); with a lock file in place, where Windows also
    raises it for a file being deleted, it counts as a held lock. The lock is removed when the block ends,
    normally or by an exception, if it still holds this run's token; if it cannot be read or removed it is
    left for the stale rule. Missing parent folders are made."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = f'{os.getpid()}-{os.urandom(8).hex()}'
    deadline = time.monotonic() + wait
    held = retried = took_over = False
    while not held:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        except (FileExistsError, PermissionError) as error:
            if isinstance(error, PermissionError) and not path.exists():
                if retried:
                    raise
                retried = True
                time.sleep(LOCK_POLL_SECONDS)
                continue
            retried = removed = False
            try:
                if time.time() - path.lstat().st_mtime > stale:
                    path.unlink()
                    removed = True
            except (FileNotFoundError, PermissionError):
                pass
            if removed and not took_over:
                took_over = True
                continue
            if time.monotonic() >= deadline:
                break
            time.sleep(LOCK_POLL_SECONDS)
        else:
            try:
                try:
                    os.write(fd, token.encode('utf-8'))
                finally:
                    os.close(fd)
            except BaseException:
                try:
                    path.unlink()
                except OSError:
                    pass
                raise
            held = True
    try:
        yield held
    finally:
        if held:
            try:
                if path.read_text(encoding='utf-8') == token:
                    path.unlink()
            except (OSError, ValueError):
                pass

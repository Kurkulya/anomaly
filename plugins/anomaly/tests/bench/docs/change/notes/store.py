"""Reads and writes the notes file."""
import json

MAX_TITLE = 80
_cache = {}


def append_note(path, title, body):
    """Add one note as one line of the notes file."""
    if len(title) > MAX_TITLE:
        raise ValueError('the title is too long')
    with open(path, 'a', encoding='utf-8') as handle:
        handle.write(json.dumps({'title': title, 'body': body}) + '\n')
    _cache.pop(path, None)


def list_notes(path):
    """Every note, in the order of the file."""
    if path not in _cache:
        with open(path, encoding='utf-8') as handle:
            _cache[path] = [json.loads(line) for line in handle if line.strip()]
    return list(_cache[path])

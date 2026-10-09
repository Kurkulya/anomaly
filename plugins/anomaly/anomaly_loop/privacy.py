"""What may be stored in home as free text or as an identifier (ADR-0003).

Free text is the writer's own process wording. `privacy_problems` names what must not be in it:
a credential, a URL with a query string, an email address, pasted program output, or an opaque
string. An opaque string is found in a run of 20 or more characters made of letters, digits and
`+ / = _ . -`. The run is cut into segments at `/ . - _ =`, so paths, kebab-case names, settings
like NAME=value and camelCase identifiers are fine. The run is opaque when:
- one segment has 20 or more characters and mixes letters with digits, or
- the whole run has 32 or more characters and 3 or more segments that each mix letters with
  digits (a token built from short parts), or
- it looks like base64: letters and digits with a `+`, or with an `=` that is end padding or
  comes with a `/`.
Session ids (UUIDs) and git commit ids (40 or 64 hex characters, or a 7 to 12 character short
id) are identifiers that are allowed; any other long hex string is opaque. A long run of only
letters, or only digits, passes.
TODO(VK, revisit 2026-12-01): decide whether long single-class runs need a rule — see ADR-0003
The URL and email patterns of the prompt redaction (metrics.py) are reused as they are; this
module adds the rules a refusal needs.

`is_identifier` is the shape of a value that goes into a line of its own, such as a repository
name, a session id or a lens name: one token, no spaces or line breaks, no sighting separator.

`check_text` and `check_identifier` are the checks every writer of record text calls: they
raise a RecordError that names the field, so the writer can reword and try again.
"""
import re

from . import metrics
from .constants import IDENTIFIER_MAX_CHARS, SIGHTING_SEPARATOR
from .files import RecordError

CREDENTIAL = re.compile(r'(?<![A-Za-z])(?:password|passwd|pw|token|secret|api[_-]?key)\s*[:=]\s*\S+', re.I)
BEARER = re.compile(r'(?<![A-Za-z])bearer\s+(?=\S*[\d._~+/=-])\S{8,}', re.I)
COMMIT_ID = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}|[0-9a-f]{7,12}')
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
RUN = re.compile(r'[A-Za-z0-9+/=_.-]{20,}')
SEGMENT_BOUNDARY = re.compile(r'[/._=-]')
SEGMENT_MIN_CHARS = 20
PARTS_RUN_MIN_CHARS = 32
PARTS_RUN_MIN_SEGMENTS = 3
PADDING = re.compile(r'={1,2}$')
OUTPUT_SHAPES = (
    re.compile(r'Traceback \(most recent call last\)'),
    re.compile(r'File "[^"]+", line \d+'),
    re.compile(r'\bat \S+ \(\S+:\d+:\d+\)'),
    re.compile(r'\bat [\w$.]+\([\w$.]+:\d+\)'),
    re.compile(r'\b0x[0-9a-fA-F]{8,}\b'),
    re.compile(r'\x1b\['),
)
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]*')


def mixes_letters_and_digits(text):
    return any(c.isalpha() for c in text) and any(c.isdigit() for c in text)


def is_base64_like(run):
    return '+' in run or ('=' in run and ('/' in run or PADDING.search(run) is not None))


def is_opaque(run):
    """True for a run (see the module text) that looks like a key or token rather than a path or a name."""
    run = run.rstrip('.')
    if mixes_letters_and_digits(run) and is_base64_like(run):
        return True
    segments = [segment for segment in SEGMENT_BOUNDARY.split(run) if segment]
    if any(len(segment) >= SEGMENT_MIN_CHARS and mixes_letters_and_digits(segment)
           and not COMMIT_ID.fullmatch(segment) for segment in segments):
        return True
    return (len(run) >= PARTS_RUN_MIN_CHARS and len(segments) >= PARTS_RUN_MIN_SEGMENTS
            and all(mixes_letters_and_digits(segment) for segment in segments) and not UUID.fullmatch(run))


def privacy_problems(text):
    """Each reason this text must not be stored, in words and without repeats; empty when it is fine."""
    checks = (
        ('a URL with a query string', metrics.URL_QUERY.search(text)),
        ('an email address', metrics.EMAIL.search(text)),
        ('a credential', CREDENTIAL.search(text) or BEARER.search(text)),
        ('pasted program output', any(shape.search(text) for shape in OUTPUT_SHAPES)),
        ('a long opaque identifier', any(is_opaque(run) for run in RUN.findall(text))),
    )
    return [name for name, found in checks if found]


def is_identifier(value):
    return (isinstance(value, str) and len(value) <= IDENTIFIER_MAX_CHARS
            and IDENTIFIER.fullmatch(value) is not None and SIGHTING_SEPARATOR not in value)


def check_text(label, key, value, limit=None):
    """Refuse a free-text field that is not one short, clean line (ADR-0003). A `limit` of None sets
    no length limit (a note in a planning file, not a loop record)."""
    if '\n' in value or '\r' in value:
        raise RecordError(f'{label}: {key} must be one line, never pasted output')
    if limit is not None and len(value) > limit:
        raise RecordError(f'{label}: {key} is longer than {limit} characters; shorten it')
    problems = privacy_problems(value)
    if problems:
        raise RecordError(f'{label}: {key} holds {" and ".join(problems)}; describe it in your own words')


def check_identifier(label, key, value):
    """Refuse a repository, session or lens name that is not one plain token."""
    if not is_identifier(value):
        raise RecordError(f'{label}: {key} must be one word of letters, digits and . _ : - '
                          f'(at most {IDENTIFIER_MAX_CHARS} characters), with no spaces or line breaks')


def check_file_token(label, key, value):
    """check_identifier for a value that becomes part of a file name: a `:` is refused too, because
    Windows reads it as a stream name (`a:b` makes the file `a`)."""
    check_identifier(label, key, value)
    if ':' in value:
        raise RecordError(f'{label}: {key} must not hold ":" because it is part of a file name')

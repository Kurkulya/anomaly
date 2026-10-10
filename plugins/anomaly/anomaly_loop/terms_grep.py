"""terms-grep: fetch terms pages and grep them for clause words, as the evidence for an `Absent` label.

  terms-grep --terms '<word>,<phrase>' <url>... [--context N] [--word]    print the hits; nothing is written

Prints, per URL: the content type, the "last modified" or "effective" line if found, then
every hit of every term with --context characters on each side (default 300). Tags become
spaces and all whitespace (also &nbsp;) becomes one space before matching, so a term split by a
tag or a line break still matches. --word matches whole words only. A control character in the
page or in a FETCH FAILED note prints as `?` (pkg_facts.printable).

A failed fetch, an empty page, a page at or over pkg_facts.MAX_RESPONSE_BYTES or a non-HTML page
(a PDF) prints FETCH FAILED and the command exits with code 1, a negative result: that output
cannot prove absence. A very short page is likely built by JavaScript; the command warns, and the
page then needs a browser. --terms with no word, or a URL that is not http, https or file, is bad
input: one `anomaly:` line and exit 2 before anything is fetched.

Standard library only.
"""
import html
import http.client
import re
import urllib.parse
import urllib.request

from . import pkg_facts
from .files import RecordError

YEAR = r'\b(?:19|20)\d\d(?:[-/.]\d{1,2}){0,2}\b'   # ends a date excerpt: whitespace is collapsed, so no line end stops it
DATE_PATTERNS = [rf'[Ll]ast (?:modified|updated).{{0,40}}?{YEAR}', rf'[Ee]ffective (?:date|as of).{{0,40}}?{YEAR}',
                 rf'[Vv]ersion.{{0,40}}?{YEAR}', r'(?:[Ll]ast (?:modified|updated)|[Ee]ffective (?:date|as of)).{0,30}']
TEXT_TYPES = ('text/html', 'application/xhtml+xml', 'text/plain')
META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_.:-]+)""", re.I)
SHORT_PAGE = 2000
HIT_LIMIT = 6
# TODO(VK, revisit 2026-10-17): a file: URL reads any local file, and a redirect can reach loopback or internal
# hosts — see ADR-0020
SCHEMES = ('http', 'https', 'file')
COMMENT = re.compile(r'<!--.*?-->', re.S)
HIDDEN_NAMES = ('script', 'style', 'noscript', 'template')
HIDDEN_OPEN = re.compile(rf'<({"|".join(HIDDEN_NAMES)})\b', re.I | re.A)
HIDDEN_CLOSE = {name: re.compile(rf'</{name}\s*>', re.I | re.A) for name in HIDDEN_NAMES}
TAG = re.compile(r'<[^>]+>')


class FetchError(Exception):
    """The page cannot serve as evidence of absence."""


def fetch(url):
    """The page text, decoded with its declared charset: the HTTP header, then a <meta> tag, then UTF-8."""
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (research; terms-grep)'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read(pkg_facts.MAX_RESPONSE_BYTES)
            content_type = r.headers.get_content_type()
            charset = r.headers.get_content_charset()
    except (OSError, ValueError, http.client.HTTPException) as e:
        raise FetchError(str(e)) from e
    if len(body) >= pkg_facts.MAX_RESPONSE_BYTES:
        raise FetchError(f'page at or over {pkg_facts.MAX_RESPONSE_BYTES} bytes')
    if content_type not in TEXT_TYPES:
        raise FetchError(f'content type {content_type}, not HTML')
    if not body.strip():
        raise FetchError('empty body')
    if not charset:
        m = META_CHARSET.search(body[:4096])
        charset = m.group(1).decode('ascii') if m else 'utf-8'
    try:
        return content_type, body.decode(charset, errors='replace')
    except LookupError:
        return content_type, body.decode('utf-8', errors='replace')


def up_to_last(raw, regex, closer):
    """`regex` matches as spaces in `raw` up to the end of its last `closer`. No match can end past it, and
    leaving that tail out keeps the regex from scanning to the page end once per unclosed opener (quadratic
    on a page of them)."""
    end = raw.rfind(closer)
    end = 0 if end == -1 else end + len(closer)
    return regex.sub(' ', raw[:end]) + raw[end:]


def drop_hidden(raw):
    """Each script, style, noscript and template element as a space, as `<(name)\\b.*?</\\1\\s*>` would, in one
    pass: once a name has no closing tag left, its later openers are skipped, not each scanned to the page end."""
    parts, kept_from, at, unclosed = [], 0, 0, set()
    while (opener := HIDDEN_OPEN.search(raw, at)) is not None:
        name = opener[1].lower()
        closer = None if name in unclosed else HIDDEN_CLOSE[name].search(raw, opener.end())
        if closer is None:
            unclosed.add(name)
            at = opener.end()
        else:
            parts += [raw[kept_from:opener.start()], ' ']
            kept_from = at = closer.end()
    return ''.join(parts) + raw[kept_from:]


def clean(raw):
    """Visible text with tags as spaces and every whitespace run, &nbsp; included, as one space."""
    raw = up_to_last(raw, COMMENT, '-->')
    raw = drop_hidden(raw)
    raw = up_to_last(raw, TAG, '>')
    raw = html.unescape(raw)
    return re.sub(r'\s+', ' ', raw).strip()


def pattern(term, word):
    """A regex for the term: its spaces match any whitespace run; with `word`, both ends sit on a word boundary."""
    body = r'\s+'.join(re.escape(part) for part in term.split())
    return re.compile(rf'\b{body}\b' if word else body, re.I)


def register(commands, common):
    command = commands.add_parser('terms-grep', parents=[common],
                                  help='grep terms pages for clause words; the output is the evidence for an Absent label')
    command.add_argument('urls', nargs='+', metavar='url', help='page to fetch (http, https or file)')
    command.add_argument('--terms', required=True, help='comma-separated words or phrases to look for')
    command.add_argument('--context', type=int, default=300, help='characters shown on each side of a hit (default 300)')
    command.add_argument('--word', action='store_true', help='match whole words only')
    command.set_defaults(handler=run_terms_grep)


def run_terms_grep(args, environ):
    terms = [t.strip() for t in args.terms.split(',') if t.strip()]
    if not terms:
        raise RecordError('--terms needs at least one word')
    refused = [url for url in args.urls if urllib.parse.urlsplit(url).scheme.lower() not in SCHEMES]
    if refused:
        raise RecordError(f'{", ".join(refused)}: not an http, https or file URL')
    failed = False
    for url in args.urls:
        print('=' * 100)
        print(url)
        try:
            content_type, raw = fetch(url)
        except FetchError as e:
            print(pkg_facts.printable(f'FETCH FAILED: {e} (cannot prove absence)'))
            failed = True
            continue
        text = pkg_facts.printable(clean(raw))
        if not text:
            print('FETCH FAILED: no visible text (cannot prove absence)')
            failed = True
            continue
        short = '  (suspiciously short: JS-rendered page? cannot prove absence)' if len(text) < SHORT_PAGE else ''
        print(f'content type: {content_type}; chars after strip: {len(text)}{short}')
        for pat in DATE_PATTERNS:
            m = re.search(pat, text)
            if m:
                print('date line:', m.group(0))
                break
        for term in terms:
            hits = [m.span() for m in pattern(term, args.word).finditer(text)]
            print(f"\n--- '{term}': {len(hits)} hit(s)")
            for start, end in hits[:HIT_LIMIT]:
                print('   …', text[max(0, start - args.context): end + args.context], '…')
            if len(hits) > HIT_LIMIT:
                print(f'   (+{len(hits) - HIT_LIMIT} more)')
    return 1 if failed else 0

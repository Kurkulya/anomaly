"""The profile: environment facts that live outside the plugin, in <home>/profile.md.

Format: a frontmatter block (see frontmatter.py); an indented line continues the previous
value (used for `implementers`, one stack per line). Anything after the closing `---` is
ignored. A key is missing when it is absent, blank, or still a template placeholder such as
`<agent id>` (for a multi-line value, when every line is one). A profile that is not UTF-8 is
read as empty, and the missing-profile line says why, so the commands still run (ADR-0001).
"""
import re
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter
from .constants import BUILD_SKILLS, DEFAULT_TICKET_KEY, PROFILE_FILE
from .files import RecordError, read_input

PROFILE_KEYS = ('tracker', 'glossary_file', 'ticket_key', 'branch_pattern', 'commit_style',
                'implementers', 'mr_tool', 'verify_ui', 'issue_source')
OPTIONAL_KEYS = ('build_skills', 'plugin_repo', 'test_writers', 'conventions', 'reviewers', 'gather', 'ci',
                 'models')
PLACEHOLDER_LINE = re.compile(r'(?:[^:<>]+:\s*)?<[^<>]*>')


def parse_profile(text):
    return frontmatter.split(text)[0]


def is_placeholder(value):
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return bool(lines) and all(PLACEHOLDER_LINE.fullmatch(line) for line in lines)


def is_set(value):
    """True when a value counts as given: not absent, not blank, not only template placeholders."""
    return bool(value) and not is_placeholder(value)


def one_line(value):
    """A value on one line: each run of white space, line breaks included, becomes one space."""
    return ' '.join(value.split())


def list_names(value):
    """The names of a list value: separated by commas or lines, one pair of surrounding `[ ]` and a
    leading `- ` on a name dropped; a value or name that is not set (is_set) gives no name."""
    if not is_set(value):
        return ()
    value = value.strip()
    if value.startswith('[') and value.endswith(']'):
        value = value[1:-1]
    names = (item.strip().removeprefix('- ').strip() for line in value.splitlines() for item in line.split(','))
    return tuple(name for name in names if is_set(name))


def compile_ticket_key(value):
    try:
        return re.compile(value)
    except re.error:
        return None


@dataclass
class Profile:
    values: dict
    exists: bool
    path: Path = Path(PROFILE_FILE)
    unreadable: str = ''   # why an existing file could not be read; it is then read as empty

    @property
    def missing(self):
        return [key for key in PROFILE_KEYS if not is_set(self.values.get(key))]

    @property
    def invalid(self):
        value = self.values.get('ticket_key')
        return ['ticket_key'] if is_set(value) and compile_ticket_key(value) is None else []


def load_profile(home):
    path = Path(home) / PROFILE_FILE
    try:
        text = read_input(path)
    except OSError:
        return Profile(values={}, exists=False, path=path)
    except RecordError as error:
        return Profile(values={}, exists=True, path=path, unreadable=str(error))
    return Profile(values=parse_profile(text), exists=True, path=path)


def ticket_key_pattern(profile):
    value = profile.values.get('ticket_key')
    return (compile_ticket_key(value) if is_set(value) else None) or re.compile(DEFAULT_TICKET_KEY)


def build_skills(profile):
    """The skills that mark a session as build work: the profile's `build_skills` (names separated
    as list_names reads them, a leading `/` on a name dropped), else constants.BUILD_SKILLS (empty:
    no session is `build`). A blank value, or one that is only template placeholders, counts as not set."""
    names = (name.lstrip('/').strip() for name in list_names(profile.values.get('build_skills')))
    return tuple(name for name in names if name) or BUILD_SKILLS


def missing_message(profile):
    """One line naming the missing keys, or None when the profile is complete."""
    if not profile.missing and not profile.invalid:
        return None
    if profile.unreadable:
        head = f'{profile.unreadable}, so it is read as empty'
    else:
        head = str(profile.path) if profile.exists else f'not found at {profile.path}'
    parts = ['profile: ' + head]
    if profile.missing:
        parts.append('missing keys: ' + ', '.join(profile.missing))
    if profile.invalid:
        parts.append('ticket_key is not a valid pattern, the default is used')
    return '; '.join(parts)

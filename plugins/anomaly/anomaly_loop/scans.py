"""Scans of the environment that tests and runtime checks share: the deny-shape matcher, the profile's environment markers,
their match rule and the repo-layer names."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

from . import flags, frontmatter
from .constants import REPOS_DIR

MANAGED_DIRS = {   # as the Claude Code documentation on managed settings gives them
    'win32': Path('C:/Program Files/ClaudeCode'),            # documented, and read on this machine
    'darwin': Path('/Library/Application Support/ClaudeCode'),   # documented, unverified (not tried)
    'linux': Path('/etc/claude-code'),                       # documented (also WSL), unverified (not tried)
}   # any other platform has no managed folder here: only the user files are read
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:[-:][A-Za-z0-9]+)+')


def settings_files(environ, platform, user_home):
    """The user settings files and the managed settings files (with the `managed-settings.d` drop-ins).
    `user_home` is the OS user folder, not the anomaly home."""
    config = Path(environ.get('CLAUDE_CONFIG_DIR') or user_home / '.claude')
    managed = MANAGED_DIRS.get('linux' if platform.startswith('linux') else platform)
    files = [config / 'settings.json', config / 'settings.local.json']
    if managed is not None:
        files += [managed / 'managed-settings.json', *sorted((managed / 'managed-settings.d').glob('*.json'))]
    return files


def deny_rules(files):
    """The deny rules of the readable settings files; a missing or unreadable file adds none. The managed
    file starts with a byte order mark, so files are read as utf-8-sig."""
    rules = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        permissions = data.get('permissions') if isinstance(data, dict) else None
        found = permissions.get('deny') if isinstance(permissions, dict) else None
        rules += [rule for rule in found or [] if isinstance(rule, str)]
    return rules


def deny_regex(rule):
    """A `Bash(...)` deny rule as a regex over a whole command; None for any other rule. `*` matches any
    text; a trailing ` *` or the older `:*` also matches the bare command."""
    found = re.fullmatch(r'Bash\((.+)\)', rule)
    if not found or not found.group(1).strip('*'):
        return None
    pattern, tail = found.group(1), ''
    for suffix in (':*', ' *'):
        if pattern.endswith(suffix):
            pattern, tail = pattern[:-2], r'(?:\s.*)?'
            break
    return re.compile('.*'.join(re.escape(part) for part in pattern.split('*')) + tail, re.S)


def stack_values(value):
    """The values of a per-stack key without their stack names: each stack's value, then each line without a stack."""
    named, other = frontmatter.nested(value)
    return list(named.values()) + other


def is_this_plugins(identifier, plugin_root):
    """True for `<plugin>:<name>` qualified by this plugin's name, in any case (flags.names_this_plugin)."""
    qualifier, colon, _ = identifier.partition(':')
    return bool(colon) and flags.names_this_plugin(SimpleNamespace(plugin_root=plugin_root), qualifier, None)


def profile_markers(values, plugin_root):
    """Identifiers that name agents, tools and skills, with each '-' part of an agent id: every
    agent id in `implementers` and `test_writers` (the stack name is left out; stack lines are read
    as frontmatter.nested reads them, so a line without a stack keeps its whole id), every item of
    `build_skills`, `reviewers`, `gather` and `upstream_repo`, only the first identifier of `mr_tool`,
    `verify_ui`, `ci` and `upstream_tool` (the rest is prose, such as "or the built-in browser"), and
    the first identifier of each `conventions` value: 11 keys. An identifier holds a `-` or `:`, so of
    `upstream_repo` only such an owner or name becomes a marker, and a plain `owner/plugin` gives none.
    A name qualified by this plugin's own name (`<plugin>:<skill>`) is the plugin's, not an environment
    fact, so it is no marker."""
    found = []
    for key in ('implementers', 'test_writers'):
        for line in stack_values(values.get(key, '')):
            found += IDENTIFIER.findall(line)
    for key in ('build_skills', 'reviewers', 'gather', 'upstream_repo'):
        found += IDENTIFIER.findall(values.get(key, ''))
    for key in ('mr_tool', 'verify_ui', 'ci', 'upstream_tool'):
        found += IDENTIFIER.findall(values.get(key, ''))[:1]
    for line in stack_values(values.get('conventions', '')):
        found += IDENTIFIER.findall(line)[:1]
    found = [identifier for identifier in found if not is_this_plugins(identifier, plugin_root)]
    return set(found) | {part for identifier in found for part in identifier.split(':') if '-' in part}


def marker_hits(text, markers):
    """The markers that `text` holds, sorted: a case-sensitive substring match, the one rule for the
    neutrality test and the upstream report check (which case-folds the text and the markers first)."""
    return [marker for marker in sorted(markers) if marker in text]


def repo_layer_names(home):
    """The names of the repositories that have a repo-layer file in home (`<home>/repos/<name>.md`): repository
    names are environment facts too."""
    return {path.stem for path in (Path(home) / REPOS_DIR).glob('*.md')}

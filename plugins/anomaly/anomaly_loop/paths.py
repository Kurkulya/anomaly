"""Where the loop reads and writes.

home   durable data (metrics.jsonl, profile.md): option --home, env CLAUDE_PLUGIN_OPTION_HOME,
       then ~/.claude/anomaly.
data   throwaway state (scan state, prompt cache): option --data, then env CLAUDE_PLUGIN_DATA.
       There is no default, and a data folder inside home is an error: throwaway state must
       never land in home. Commands that can work without it use resolve_optional_data (None).
user config   the user's Claude Code folder: option, env ANOMALY_USER_CONFIG, then ~/.claude.
plugin root   this plugin's folder: option, env CLAUDE_PLUGIN_ROOT, then the folder that holds
              this package.

A leading ~ is expanded here, because a userConfig default is not known to be expanded by
Claude Code. A value that is only an unfilled placeholder such as ${user_config.home} counts
as unset, because a skill can reach the shell with its placeholders left as literal text.

TODO(VK, revisit 2026-11-15): check whether Claude Code expands ~ in a userConfig default; if it
does, drop the plugin's own expansion — see ADR-0001
"""
import os
import re
from pathlib import Path

DEFAULT_HOME = '~/.claude/anomaly'
DEFAULT_PROJECTS = '~/.claude/projects'
DEFAULT_USER_CONFIG = '~/.claude'
DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
HOME_ENV = 'CLAUDE_PLUGIN_OPTION_HOME'
DATA_ENV = 'CLAUDE_PLUGIN_DATA'
PROJECTS_ENV = 'ANOMALY_PROJECTS'
USER_CONFIG_ENV = 'ANOMALY_USER_CONFIG'
PLUGIN_ROOT_ENV = 'CLAUDE_PLUGIN_ROOT'
UNFILLED = re.compile(r'\$\{[^{}]*\}')


class PathError(Exception):
    pass


def is_unfilled(value):
    """True when the whole value is an unfilled plugin placeholder like ${...}."""
    return value is not None and UNFILLED.fullmatch(str(value).strip()) is not None


def first_value(*values):
    """First value that is set: not blank and not an unfilled plugin placeholder like ${...}."""
    for value in values:
        text = '' if value is None else str(value).strip()
        if text and not is_unfilled(text):
            return text
    return None


def expand(value):
    return Path(os.path.expanduser(value))


def resolve_home(option, environ):
    return expand(first_value(option, environ.get(HOME_ENV), DEFAULT_HOME))


def home_notice(option, environ):
    """One line when the --home option was an unfilled placeholder, naming the home used instead."""
    if not is_unfilled(option):
        return None
    return f'home: placeholder unfilled, using {resolve_home(option, environ)}'


def resolve_data(option, environ, home):
    value = first_value(option, environ.get(DATA_ENV))
    if value is None:
        raise PathError(f'no data folder: pass --data or set {DATA_ENV} '
                        '(scan state and the prompt cache are never written into home)')
    data = expand(value)
    if data.resolve().is_relative_to(Path(home).resolve()):
        raise PathError(f'data folder {data} is inside home {home}: '
                        'throwaway state must stay outside home')
    return data


def resolve_optional_data(option, environ, home):
    """The data folder like resolve_data, or None when none is given (for readers that can work without it)."""
    if first_value(option, environ.get(DATA_ENV)) is None:
        return None
    return resolve_data(option, environ, home)


def resolve_projects(option, environ):
    return expand(first_value(option, environ.get(PROJECTS_ENV), DEFAULT_PROJECTS))


def resolve_user_config(option, environ):
    return expand(first_value(option, environ.get(USER_CONFIG_ENV), DEFAULT_USER_CONFIG))


def resolve_plugin_root(option, environ):
    return expand(first_value(option, environ.get(PLUGIN_ROOT_ENV), DEFAULT_PLUGIN_ROOT))

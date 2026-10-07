"""The digest: a list of sections, each a function of one read-only Context returning lines.

A section returns [] when it has nothing to say, and is then left out. To add a section,
write a function of the context in its own module and name it in SECTIONS as
(module, function). The Context loads each kind of record once, on first use, and the same
objects are handed to every section: a section reads them and must never change them (or
write files), because the next section sees the same objects. `data` is the throwaway data
folder, or None when none was given: a section that needs it must cope with None.
Sections compute what they need in their own module; the Context stays a small set of
shared inputs.
"""
import argparse
from dataclasses import dataclass
from datetime import date, datetime
from functools import cached_property
from importlib import import_module
from pathlib import Path
from types import MappingProxyType

from . import ideas, paths, profile, records
from .constants import METRICS_FILE
from .files import load_lines

# Digest sections as (module, function), in output order. The trends come first so the digest
# opens with direction; the index section follows them.
SECTIONS = (
    ('trends', 'trends_section'),
    ('trends', 'top_skills_section'),
    ('trends', 'experiments_due_section'),
    ('trends', 'experiment_results_section'),
    ('trends', 'reverted_section'),
    ('index', 'digest_section'),
    ('assess', 'digest_section'),
    ('flags', 'plugin_repo_notice'),
    ('flags', 'needs_rework'),
    ('repeats', 'repeated_actions'),
    ('flags', 'stale'),
    ('flags', 'near_duplicates'),
    ('flags', 'lens_rates'),
    ('flags', 'unused_skills'),
)


def section_functions():
    return [getattr(import_module(f'.{module}', __package__), name) for module, name in SECTIONS]


@dataclass(frozen=True)
class Context:
    home: Path
    today: date
    now: datetime
    user_config: Path
    plugin_root: Path
    data: Path | None = None
    strict: bool = False

    @cached_property
    def anomalies(self):
        """Every anomaly; with `strict`, an invalid record is a RecordError (records.load_anomalies)."""
        return tuple(records.load_anomalies(self.home, strict=self.strict))

    @cached_property
    def ideas(self):
        return tuple(ideas.load_ideas(self.home))

    @cached_property
    def metrics_rows(self):
        return tuple(load_lines(self.home / METRICS_FILE))

    @cached_property
    def lenses(self):
        return tuple(records.load_lenses(self.home))

    @cached_property
    def session_kinds(self):
        return MappingProxyType(records.load_session_kinds(self.home))

    @cached_property
    def profile(self):
        return profile.load_profile(self.home)


def render(context, sections=None):
    out = []
    for section in section_functions() if sections is None else sections:
        lines = list(section(context))
        if lines:
            out += ([''] if out else []) + lines
    return out


# ---------- building a Context from the command line ----------

def folder_options():
    """A parent parser with --user-config and --plugin-root, for every command that builds a Context."""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--user-config', dest='user_config', help='the Claude Code user folder (default: env '
                        f'{paths.USER_CONFIG_ENV}, then {paths.DEFAULT_USER_CONFIG})')
    parser.add_argument('--plugin-root', dest='plugin_root', help='the plugin folder (default: env '
                        f'{paths.PLUGIN_ROOT_ENV}, then the installed plugin folder)')
    return parser


def context_from_args(args, environ, data=None, strict=False):
    """The Context for a command's arguments (home, folder_options, the injected clock). `data` is a
    data folder the command already resolved; without it the data folder is optional
    (paths.resolve_optional_data). `strict` makes an invalid anomaly record an error."""
    home = paths.resolve_home(args.home, environ)
    return Context(home=home, today=args.today, now=args.now,
                   user_config=paths.resolve_user_config(args.user_config, environ),
                   plugin_root=paths.resolve_plugin_root(args.plugin_root, environ),
                   data=data if data is not None else paths.resolve_optional_data(args.data, environ, home),
                   strict=strict)


# ---------- the digest subcommand ----------

def register(commands, common):
    command = commands.add_parser('digest', parents=[common, folder_options()],
                                  help='print the calibrate digest for home')
    command.set_defaults(handler=run_digest)


def run_digest(args, environ):
    lines = render(context_from_args(args, environ))
    print('\n'.join(lines))
    return 0

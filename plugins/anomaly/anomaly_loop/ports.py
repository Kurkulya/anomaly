"""`ports`: the one injection point of the pipeline (ADR-0007). It resolves the profile and the repo
layer into the adapter of every port, the repo-layer commands and the model roles.

resolve() returns that structure and render() turns it into lines; other commands call resolve(),
port() and command(), never the printer. resolve() reads only the profile: the repo layer is read
when `layer` or command() is first used, and its repository files only when a command is asked
for, so a broken repository file cannot break a caller that needs only ports or risk patterns.
Precedence: repo layer > profile adapters > core defaults; the profile holds no commands, and the
order inside the repo layer is in repolayer.py.

A profile value that is absent, blank or a template placeholder (profile.is_set) leaves its
port on the core default: an adapter is never guessed. Each port has one fixed mode
(constants.PORTS):
- replace: the profile value replaces the core default.
- add: the profile's names (profile.list_names) are listed after the core default's.
- extend: the profile's source is listed after the core default (the repo's own docs).
A per-stack port reads one `stack: adapter` line per stack (frontmatter.nested: a space after the
colon, so an id such as `pack:agent` is not read as a stack; a repeated stack keeps its last
value); a line without a stack is the adapter of the base line, which stands for every stack the
profile does not name. A replace port takes one such line: with more, resolve() keeps the first
and records a problem, and `ports` refuses to print (one `anomaly:` line). The `models` key holds one `role: model`
line per role; a role may be written with spaces or hyphens (`deep analysis` is `deep_analysis`).

Output: one line per entry, `<section> <name> = <value> [<source>]` (value empty when unresolved).
Sections, in order: `port` (name, or name.stack), `repo` (name, override, base), `command`, `app` and
`risk` (only what the override file sets), `model`.
"""
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from . import frontmatter, gitrepo, paths, profile, repolayer
from .constants import ADD, MODEL_ROLES, MODELS_KEY, PER_STACK_PORTS, PORTS, REPLACE
from .files import RecordError
from .profile import is_set, list_names, one_line
from .repolayer import Setting

CORE = repolayer.CORE_DEFAULT
PROFILE = 'profile'
CORE_AND_PROFILE = f'{CORE} + {PROFILE}'


@dataclass(frozen=True)
class Port:
    name: str
    mode: str           # constants.REPLACE, ADD or EXTEND
    values: tuple       # the core default's items, the adapter, or both in mode order
    source: str         # CORE, PROFILE or CORE_AND_PROFILE
    stack: str = ''     # '' for the line that stands for every stack not named

    @property
    def value(self):
        return ', '.join(self.values)

    @property
    def is_default(self):
        return self.source == CORE


@dataclass
class Resolution:
    ports: tuple                  # Port per table row; a per-stack port's stack lines follow its base line
    models: dict                  # role -> Setting
    home: Path
    folder: Path                  # a folder of the repository whose layer `layer` reads
    problems: tuple = ()          # profile mistakes `ports` refuses; the ports above keep a usable value

    @cached_property
    def layer(self):
        """The repo layer (repolayer.RepoLayer), read on first use."""
        return repolayer.read(self.folder, self.home)


def resolve(home, folder=None):
    """The ports and model roles from the profile in `home`, and the repo layer of the repository
    that holds `folder` (default: the current folder), read on first use."""
    values = profile.load_profile(home).values
    lines, problems = resolve_ports(values)
    return Resolution(ports=lines, models=resolve_models(values), home=Path(home),
                      folder=Path(folder) if folder else Path.cwd(), problems=problems)


def port(resolution, name, stack=''):
    """The port `name` for `stack`; a stack the profile does not name gets the port's base line."""
    lines = [line for line in resolution.ports if line.name == name]
    if not lines:
        raise KeyError(f'no port named {name}')
    return next((line for line in lines if line.stack == stack), lines[0])


def key_line(home):
    """The name of the ticket line that holds the key: the `key_line` port of the profile in `home`,
    without one trailing colon (a profile `key_line: Jira:` names the line `Jira`)."""
    return port(resolve(home), 'key_line').value.removesuffix(':')


def core_default(name):
    """The core default items of the port `name` (constants.PORTS), with no profile read."""
    for port_name, _, _, default in PORTS:
        if port_name == name:
            return default
    raise KeyError(f'no port named {name}')


def command(resolution, name):
    """The repo-layer command `name` (one of constants.REPO_COMMANDS) as a repolayer.Setting; an
    unresolved command has an empty value. A broken repository file raises its error here."""
    return resolution.layer.commands[name]


def resolve_ports(values):
    """(ports, problems) from the profile values, in table order."""
    lines, problems = [], []
    for name, mode, key, default in PORTS:
        value = values.get(key, '')
        if name in PER_STACK_PORTS:
            base, stacks = stack_lines(value)
            if mode == REPLACE and len(base) > 1:
                problems.append(f'profile key {key}: {len(base)} lines without a stack, but the {name} port '
                                'takes one adapter per stack; name the stacks (`stack: adapter`)')
                base = base[:1]
            lines.append(combined(name, mode, default, base) if base else Port(name, mode, default, CORE))
            lines += [combined(name, mode, default, (adapter,), stack) for stack, adapter in stacks.items()]
            continue
        adapters = list_names(value) if mode == ADD else ((one_line(value),) if is_set(value) else ())
        lines.append(combined(name, mode, default, adapters) if adapters else Port(name, mode, default, CORE))
    return tuple(lines), tuple(problems)


def combined(name, mode, default, adapters, stack=''):
    if mode == REPLACE:
        return Port(name, mode, adapters, PROFILE, stack)
    return Port(name, mode, default + adapters, CORE_AND_PROFILE, stack)


def stack_lines(value):
    """(base adapters, {stack: adapter}) of a per-stack value; values that are not set are left out."""
    named, other = frontmatter.nested(value)
    stacks = {stack: one_line(adapter) for stack, adapter in named.items() if is_set(adapter)}
    return tuple(one_line(line) for line in other if is_set(line)), stacks


def resolve_models(values):
    roles = {re.sub(r'[ _-]+', '_', role.lower()): one_line(model)
             for role, model in frontmatter.nested(values.get(MODELS_KEY, ''))[0].items() if is_set(model)}
    return {role: Setting(roles[role], PROFILE) if role in roles else Setting(default, CORE)
            for role, default in MODEL_ROLES}


def entry(section, name, value, source):
    return f'{section} {name} = {value} [{source}]' if value else f'{section} {name} = [{source}]'


def render(resolution):
    """The `ports` output lines."""
    layer = resolution.layer
    lines = [entry('port', f'{line.name}.{line.stack}' if line.stack else line.name, line.value, line.source)
             for line in resolution.ports]
    lines.append(entry('repo', 'name', layer.name, layer.name_source))
    lines.append(entry('repo', 'override', str(layer.override_path), 'found' if layer.override_found else 'absent'))
    lines.append(entry('repo', 'base', layer.base.value, layer.base.source))
    lines += [entry('command', name, setting.value, setting.source) for name, setting in layer.commands.items()]
    lines += [entry('app', name, setting.value, setting.source) for name, setting in layer.app.items()]
    lines += [entry('risk', 'pattern', pattern, repolayer.OVERRIDE) for pattern in layer.risk_patterns]
    lines += [entry('model', role, setting.value, setting.source) for role, setting in resolution.models.items()]
    return lines


# ---------- the ports subcommand ----------

def register(commands, common):
    command = commands.add_parser('ports', parents=[common],
                                  help='print the adapter of every port, the repo-layer commands and the model roles')
    command.add_argument('--repo', help=gitrepo.REPO_HELP)
    command.set_defaults(handler=run_ports)


def run_ports(args, environ):
    home = paths.resolve_home(args.home, environ)
    resolution = resolve(home, gitrepo.repo_for(args.repo, outside_git=True))
    if resolution.problems:
        raise RecordError('; '.join(resolution.problems))
    for line in render(resolution):
        print(line)
    return 0

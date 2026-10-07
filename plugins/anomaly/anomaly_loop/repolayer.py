"""The repo layer: the commands a repository documents itself, plus the personal override file
<home>/repos/<repo>.md (ADR-0007). Reading it writes nothing, neither in the repository nor in home.
The commands are run from the repository root (RepoLayer.root); `hook_path` is not a command but a
folder relative to that root; a resolved `hook_path` that is absolute, holds a space or leaves the
root with `..` is refused with a RecordError when the commands are read.

Precedence, highest first; within a tier the sources are read in the order listed:
1. Explicit: a line `<label>: `<text>`` in CLAUDE.md, then AGENTS.md (optionally a `- ` or `* `
   list item, the label optionally in bold; labels verify, e2e, install, codegen, and hook path
   written `hook path`, `hook_path`, `hook-path`, `hooks path`, in any case; no other text is
   read), then a package.json script or a Makefile target named exactly verify, e2e or codegen.
2. The override file.
3. Guessed, printed as `guessed from <file>`: a package.json script or Makefile target named
   `test`, `test:e2e` or `generate` (constants.GUESSED_SCRIPTS); install for package.json as the
   manager's frozen form that runs no package scripts (constants.FROZEN_INSTALLS; the manager
   follows the lockfile, constants.LOCKFILES; with no lockfile, constants.NO_LOCKFILE_INSTALL), or the
   Makefile target `deps`; for pubspec.yaml `<tool> test` and `<tool> pub get`, where the tool is
   `flutter` when it declares `sdk: flutter`, else `dart`, and the build_runner command as codegen
   when it names build_runner.
A command that no source names stays unresolved.

The override file is a frontmatter block (frontmatter.py): one key per name in
constants.REPO_COMMANDS, a `ui_check:` block with one `fact: value` line per app fact
(constants.APP_FACTS), and `risk_patterns:` with one `- <pattern>` line per extra risk pattern.
A blank value or a template placeholder counts as not set (profile.is_set).

The base branch (the branch `build` cuts the integration branch from): the override file's `base`
key (constants.BASE_KEY), else the branch origin's HEAD points at (gitrepo.origin_default_branch),
else constants.DEFAULT_BASE_BRANCH.

The repository name keys the override file: gitrepo.origin_name, else the folder name of
gitrepo.shared_root (the main checkout, so every worktree of a repository shares one file), else,
for a folder outside git, the folder's own name.
"""
import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from . import frontmatter, gitrepo, paths, profile
from .constants import (APP_FACTS, BASE_KEY, BUILD_RUNNER_CODEGEN, DEFAULT_BASE_BRANCH, DEFAULT_PACKAGE_MANAGER,
                        EXPLICIT_SCRIPTS, FROZEN_INSTALLS, GUESSED_SCRIPTS, INSTRUCTION_FILES, LOCKFILES, MAKE_INSTALL_TARGETS,
                        NO_LOCKFILE_INSTALL, REPO_COMMANDS, REPOS_DIR, RISK_PATTERNS_KEY)
from .files import RecordError, read_input
from .profile import one_line

OVERRIDE = 'override'
UNRESOLVED = 'unresolved'
GUESSED = 'guessed from'
GIT = 'git'
CORE_DEFAULT = 'core default'
LABEL_LINE = re.compile(r'\s*(?:[-*]\s+)?(?:\*\*)?(verify|e2e|install|codegen|hooks?[ _-]path)(?:\*\*)?\s*:'
                        r'\s*(?:\*\*)?\s*`([^`]+)`', re.IGNORECASE)
MAKE_RULE = re.compile(r'([A-Za-z0-9][A-Za-z0-9_. -]*?)\s*::?(?!:?=)')
FLUTTER_SDK = re.compile(r'^\s+sdk:\s*flutter\s*$', re.MULTILINE)
BUILD_RUNNER = re.compile(r'^\s+build_runner\s*:', re.MULTILINE)


@dataclass(frozen=True)
class Setting:
    value: str      # '' when unresolved
    source: str     # the file it came from, 'override', 'guessed from <file>' or 'unresolved'; for the base 'git' or 'core default'


@dataclass
class RepoLayer:
    root: Path              # the repository root, or the folder itself outside git; commands run here
    name: str
    name_source: str        # 'origin', 'checkout' or 'folder'
    override_path: Path
    override_found: bool
    app: dict               # the ui_check app facts the override file sets -> Setting
    risk_patterns: tuple    # extra risk patterns from the override file
    base: Setting           # the base branch, from the override file, git or the core default
    override: dict = field(default_factory=dict, repr=False)   # the override file's fields

    @cached_property
    def commands(self):
        """Every name in constants.REPO_COMMANDS -> Setting. The repository files are read on first
        use, so a reader of the other fields never fails on a broken repository file."""
        return resolve_commands(self.root, self.override)


def read(folder, home):
    """The repo layer of the repository that holds `folder` (a PathError when it is no folder). Only
    git and the override file are read here; the repository files wait for `commands`."""
    folder = Path(folder)
    if not folder.is_dir():
        raise paths.PathError(f'repository folder not found: {folder}')
    found = gitrepo.find_repo(folder)
    root = found or folder.resolve()
    name, name_source = repo_name(found, root)
    override_path = Path(home) / REPOS_DIR / f'{name}.md'
    override, override_found = read_override(override_path)
    facts = frontmatter.nested(override.get('ui_check', ''))[0]
    return RepoLayer(
        root=root, name=name, name_source=name_source, override_path=override_path, override_found=override_found,
        app={fact: Setting(one_line(facts[fact]), OVERRIDE) for fact in APP_FACTS if profile.is_set(facts.get(fact))},
        risk_patterns=tuple(item for item in frontmatter.items(override.get(RISK_PATTERNS_KEY, ''))
                            if profile.is_set(item)),
        base=base_branch(found, override), override=override)


def base_branch(found, override):
    """The base branch as a Setting: the override file's key, else origin's HEAD (`found` is the git
    root, or None outside git), else the core default."""
    if profile.is_set(override.get(BASE_KEY)):
        return Setting(one_line(override[BASE_KEY]), OVERRIDE)
    branch = gitrepo.origin_default_branch(found) if found else None
    return Setting(branch, GIT) if branch else Setting(DEFAULT_BASE_BRANCH, CORE_DEFAULT)


def resolve_commands(root, override):
    """Every name in constants.REPO_COMMANDS -> Setting: explicit sources, then the override file,
    then guessed ones, else unresolved."""
    sources = list(documented(root))
    commands = {}
    for source, explicit, _ in sources:
        for command, value in explicit.items():
            commands.setdefault(command, Setting(value, source))
    for command in REPO_COMMANDS:
        if profile.is_set(override.get(command)):
            commands.setdefault(command, Setting(one_line(override[command]), OVERRIDE))
    for source, _, guessed in sources:
        for command, value in guessed.items():
            commands.setdefault(command, Setting(value, f'{GUESSED} {source}'))
    hook = commands.get('hook_path')
    if hook and not is_inside(hook.value):
        raise RecordError(f'hook_path {hook.value!r} from {hook.source}: not a folder inside the repository '
                          '(it is absolute, holds a space, or leaves the root with ..)')
    return {command: commands.get(command, Setting('', UNRESOLVED)) for command in REPO_COMMANDS}


def is_inside(folder):
    """True when `folder` names a folder inside the repository root: relative (no leading `/`, `\\`,
    `~` or drive letter), without spaces, and without a `..` part."""
    return not (re.search(r'\s', folder) or re.match(r'[/\\~]|[A-Za-z]:', folder)
                or '..' in re.split(r'[/\\]', folder))


def repo_name(found, root):
    """(name, source) that keys the override file; `found` is the git root, or None outside git."""
    if found is None:
        return root.name, 'folder'
    name = gitrepo.origin_name(found)
    return (name, 'origin') if name else (gitrepo.shared_root(found).name, 'checkout')


def read_override(path):
    """(fields, found) of the override file; a missing file has no fields."""
    if not path.is_file():
        return {}, False
    return frontmatter.split(read_input(path))[0], True


def read_text(path):
    return read_input(path) if path.is_file() else None


def documented(root):
    """(source, explicit {command: text}, guessed {command: text}) per repository file, in order."""
    for name in INSTRUCTION_FILES:
        yield name, instruction_commands(read_text(root / name)), {}
    yield ('package.json', *package_commands(root))
    yield 'pubspec.yaml', {}, pubspec_commands(read_text(root / 'pubspec.yaml'))
    yield ('Makefile', *make_commands(read_text(root / 'Makefile')))


def instruction_commands(text):
    found = {}
    for line in (text or '').splitlines():
        match = LABEL_LINE.match(line)
        if match:
            label = match.group(1).lower()
            found.setdefault('hook_path' if label.startswith('hook') else label, match.group(2).strip())
    return found


def named(names, run):
    """(explicit, guessed) commands for the scripts or targets in `names`, each run as `run(name)`."""
    explicit = {command: run(command) for command in EXPLICIT_SCRIPTS if command in names}
    guessed = {command: run(name) for command, name in GUESSED_SCRIPTS if name in names}
    return explicit, guessed


def package_commands(root):
    path = root / 'package.json'
    text = read_text(path)
    if text is None:
        return {}, {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise RecordError(f'{path}: not valid JSON ({error.msg}, line {error.lineno})') from None
    scripts = data.get('scripts') if isinstance(data, dict) else None
    scripts = scripts if isinstance(scripts, dict) else {}
    locked = next((tool for lockfile, tool in LOCKFILES if (root / lockfile).is_file()), None)
    manager = locked or DEFAULT_PACKAGE_MANAGER
    explicit, guessed = named(scripts, lambda script: f'{manager} run {script}')
    return explicit, {'install': FROZEN_INSTALLS[locked] if locked else NO_LOCKFILE_INSTALL, **guessed}


def pubspec_commands(text):
    if text is None:
        return {}
    tool = 'flutter' if FLUTTER_SDK.search(text) else 'dart'
    found = {'verify': f'{tool} test', 'install': f'{tool} pub get'}
    if BUILD_RUNNER.search(text):
        found['codegen'] = BUILD_RUNNER_CODEGEN
    return found


def make_commands(text):
    if text is None:
        return {}, {}
    targets = set()
    for line in text.splitlines():
        rule = MAKE_RULE.match(line)
        if rule:
            targets.update(rule.group(1).split())
    explicit, guessed = named(targets, lambda target: f'make {target}')
    install = next((target for target in MAKE_INSTALL_TARGETS if target in targets), None)
    return explicit, {**guessed, **({'install': f'make {install}'} if install else {})}

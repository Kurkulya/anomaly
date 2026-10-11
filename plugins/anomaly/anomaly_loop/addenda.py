"""A user's addenda files in home (ADR-0021): one file per plugin skill (`addenda/<skill>.md`) or agent
(`addenda/agents/<agent>.md`), each line one rule tied to one experiment, at most ADDENDA_MAX_LINES lines.

A line is written as `<rule> [exp: <signature> · <stamp>]`. The stamp is 8 hex characters of sha256 over
the text the line adds to: the sorted relative paths and bytes of every file in the skill folder, or the
bytes of the one agent file, so it changes only when that skill or agent changes.

Which part of the plugin a target is (plugin_part) lives here too, with the anomaly copies a writer
changes (writable, find) and the addenda file an anomaly's fix names (addendum_file): calibrate and
upstream both read them, and upstream does not import calibrate.
"""
import copy
import hashlib
import re
from collections import namedtuple
from pathlib import Path

from . import files, flags, privacy
from .constants import ADDENDA_DIR, ADDENDA_MAX_LINES, FIXED_BY_SEPARATOR, PLUGIN_AGENTS_DIR, SKILL_AGENTS
from .files import RecordError
from .records import SLUG

AGENTS = 'agents'          # the agent files of the plugin, and their addenda files in home
NO_ADDENDA = ('measure',)  # skills that take no addenda file
STAMP_CHARS = 8
TAG_OPEN, TAG_SEPARATOR, TAG_CLOSE = '[exp: ', ' · ', ']'   # the tag `[exp: <signature> · <stamp>]`
TAG_SHAPE = f'{TAG_OPEN}<signature>{TAG_SEPARATOR}<stamp>{TAG_CLOSE}'
TAGGED = re.compile(   # a rule, then its tag, as one line
    rf'(?P<rule>.*\S) {re.escape(TAG_OPEN)}(?P<signature>{SLUG.pattern}){re.escape(TAG_SEPARATOR)}'
    rf'(?P<stamp>[0-9a-f]{{{STAMP_CHARS}}}){re.escape(TAG_CLOSE)}')
HEADER = 'Extra rules for {skill}. They add or narrow; the core rules and invariants win on a clash.'
HAND_OVER = 'add these lines to the brief of `anomaly:{agent}`'
LOG_HEADING = 'Addenda log'   # the anomaly section that records what happened to its addenda line
RECHECK_HEADING = '## Addenda to re-check'


def addendum_path(home, name, agent=False):
    """The addenda file of the skill or agent `name` in home."""
    folder = Path(home) / ADDENDA_DIR
    return (folder / AGENTS if agent else folder) / f'{name}.md'


def stamp(target):
    """The stamp of a skill folder or of one agent file (see the module text)."""
    target = Path(target)
    digest = hashlib.sha256()
    if target.is_file():
        digest.update(target.read_bytes())
    else:
        found = sorted((item.relative_to(target).as_posix(), item) for item in target.rglob('*') if item.is_file())
        for relative, item in found:
            data = item.read_bytes()
            digest.update(f'{relative}\0{len(data)}\0'.encode('utf-8'))
            digest.update(data)
    return digest.hexdigest()[:STAMP_CHARS]


def read_lines(path):
    """The non-blank lines of an addenda file; [] when it is missing."""
    try:
        text = files.read_input(path)
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def append_line(path, line, signature, stamp):
    """Add `line` tagged with its experiment and stamp as the file's last line; returns the tagged line.
    A file that already holds ADDENDA_MAX_LINES lines, or a line of this experiment, raises RecordError and
    is not changed: one line is one experiment."""
    lines = read_lines(path)
    if any(f'{TAG_OPEN}{signature}{TAG_SEPARATOR}' in old for old in lines):
        raise RecordError(f'{path}: already holds a line of the experiment {signature}, and one line is one '
                          'experiment; remove the old line from this file first, then run the fix again')
    if len(lines) >= ADDENDA_MAX_LINES:
        raise RecordError(f'{path}: holds {len(lines)} lines, the cap of an addenda file is {ADDENDA_MAX_LINES}; '
                          'drop or upstream a line first')
    tagged = f'{line} {TAG_OPEN}{signature}{TAG_SEPARATOR}{stamp}{TAG_CLOSE}'
    files.write_lines(path, lines + [tagged])
    return tagged


def is_tagged_with(line, signature):
    found = TAGGED.fullmatch(line)
    return found is not None and found['signature'] == signature


def tagged_line(path, signature):
    """The line of the file tagged with this experiment's signature (TAGGED), or None."""
    return next((line for line in read_lines(path) if is_tagged_with(line, signature)), None)


def remove_line(path, signature):
    """Remove the line tagged with this signature from the file and keep every other line as it is (blank lines
    are not kept, as in append_line); returns the removed line, or None when the file holds no such line and is
    not changed."""
    lines = read_lines(path)
    removed = next((line for line in lines if is_tagged_with(line, signature)), None)
    if removed is not None:
        files.write_lines(path, [line for line in lines if not is_tagged_with(line, signature)])
    return removed


def log_line(anomaly, line):
    """Append `line` as the last `- ` line of the anomaly's `## Addenda log`, which is added when missing; the
    one writer of that section."""
    for number, (name, content) in enumerate(anomaly.sections):
        if name.lower() == LOG_HEADING.lower():
            anomaly.sections[number] = (name, '\n'.join([content, f'- {line}']).strip())
            return
    anomaly.sections.append((LOG_HEADING, f'- {line}'))


def log_lines(anomaly):
    """The lines of the anomaly's `## Addenda log` without their `- `; [] when it has none."""
    for name, content in anomaly.sections:
        if name.lower() == LOG_HEADING.lower():
            return [line[2:].strip() for line in content.splitlines() if line.startswith('- ')]
    return []


def has_verdict(experiment):
    """True when the experiment has a verdict. A blank or `inconclusive` result is none: the experiment is still
    in flight (ADR-0002), so its line is not dropped yet."""
    return experiment is not None and experiment.result not in ('', 'inconclusive')


def addenda_files(home):
    """(path, name, agent) of every addenda file in home: the skills' files, then the agents', each by name."""
    folder = Path(home) / ADDENDA_DIR
    return ([(path, path.stem, False) for path in sorted(folder.glob('*.md'))]
            + [(path, path.stem, True) for path in sorted((folder / AGENTS).glob('*.md'))])


def home_relative(home, path):
    """A path inside home as the plan's fix-home mark and a `fixed_by` ref name it: relative, with `/`."""
    return Path(path).relative_to(Path(home)).as_posix()


def addendum_file(home, anomaly):
    """The addenda file in home that the anomaly's fix names (`fixed_by` = `<date> · addenda/...`), or None."""
    ref = anomaly.fixed_by.partition(FIXED_BY_SEPARATOR)[2].strip()
    return next((path for path, _, _ in addenda_files(home) if home_relative(home, path) == ref), None)


def not_read(path, error):
    """Why a file could not be read, as `not read (<reason>)`."""
    reason = getattr(error, 'strerror', None) or str(error).removeprefix(f'{path}: ')
    return f'not read ({reason})'


def file_block(path, heading):
    """`heading` and the tagged lines of one addenda file, then one warning when the file holds a line
    without its tag; [] for a missing or empty file. A file that cannot be read is one warning, not a stop."""
    try:
        lines = read_lines(path)
    except (RecordError, OSError) as error:
        return [f'warning: {path}: {not_read(path, error)}']
    tagged = [line for line in lines if TAGGED.fullmatch(line)]
    block = [heading, *tagged] if tagged else []
    if len(tagged) < len(lines):
        block.append(f'warning: {path}: lines without an {TAG_SHAPE} tag are not printed '
                     f'({len(lines) - len(tagged)} of {len(lines)})')
    return block


def print_addenda(home, skill):
    """Print the addendum of `skill` under HEADER, then the addendum of each agent it dispatches
    (SKILL_AGENTS) under HAND_OVER. With no addenda file, or for a skill in NO_ADDENDA, nothing is printed,
    not even an empty line."""
    if skill in NO_ADDENDA:
        return
    out = file_block(addendum_path(home, skill), HEADER.format(skill=skill))
    for agent in SKILL_AGENTS.get(skill, ()):
        out += file_block(addendum_path(home, agent, agent=True), HAND_OVER.format(agent=agent))
    if out:
        print('\n'.join(out))


# ---------- the re-check ----------

Recheck = namedtuple('Recheck', 'path note lines')   # an addenda file, why it is listed, its TAGGED matches to re-check


def scan_rechecks(home, plugin_root):
    """The addenda files to re-check: one whose target (`<plugin_root>/skills/<name>` with its SKILL.md, or
    `<plugin_root>/agents/<name>.md`) is gone, with all its tagged lines, and one with tagged lines whose stamp
    differs from the target's stamp now, with those lines. A file or target that cannot be read is listed with why."""
    found = []
    for path, name, agent in addenda_files(home):
        target = Path(plugin_root) / AGENTS / f'{name}.md' if agent else Path(plugin_root) / 'skills' / name
        part = f'the {"agent" if agent else "skill"} {name}'
        try:
            tagged = tuple(match for match in map(TAGGED.fullmatch, read_lines(path)) if match)
        except (RecordError, OSError) as error:
            found.append(Recheck(path, not_read(path, error), ()))
            continue
        if not (target if agent else target / flags.SKILL_FILE).is_file():
            found.append(Recheck(path, f'{part} is gone from the plugin', tagged))
            continue
        try:
            now = stamp(target)
        except OSError as error:
            found.append(Recheck(path, f'{part} {not_read(target, error)}', ()))
            continue
        changed = tuple(line for line in tagged if line['stamp'] != now)
        if changed:
            found.append(Recheck(path, f'{part} changed since these lines were written', changed))
    return tuple(found)


def recheck_section(context):
    """The addenda lines to re-check (scan_rechecks), each with `calibrate drop` once its experiment has a verdict
    (has_verdict), else with its check date; a line whose signature names no anomaly says so."""
    anomalies = {anomaly.signature: anomaly for anomaly in context.anomalies}
    lines = []
    for recheck in context.rechecks:
        lines.append(f'- {recheck.path}: {recheck.note}')
        for line in recheck.lines:
            signature, anomaly = line['signature'], anomalies.get(line['signature'])
            experiment = anomaly.experiment if anomaly is not None else None
            if anomaly is None:
                then = f'no anomaly {signature} in home'
            elif has_verdict(experiment):
                then = f"`calibrate drop {signature} --reason '<text>'`"
            else:
                then = f'no verdict yet, check by {(experiment.check_by if experiment else "") or "?"}'
            lines.append(f'  - {line[0]} · {then}')
    return [RECHECK_HEADING] + lines if lines else []


# ---------- which plugin part a target is, and the anomalies a writer changes ----------

PluginPart = namedtuple('PluginPart', 'name agent unit')   # unit: the skill folder or agent file, else None


def plugin_part(context, target, plugin):
    """The part of this plugin a target is, or None when it is not this plugin. A target is this plugin
    when it is a path inside the plugin folder or its checkout's plugin folder (flags.target_path), or
    `<plugin name>:...` (flags.names_this_plugin). The part is a skill (`<plugin>:<skill>` or a path inside
    `skills/<skill>/`), an agent (`<plugin>:<agent>` or `agents/<agent>.md`), or else (name and unit None)
    plugin code or docs, or a `<plugin>:...` that names no skill or agent. The qualifier ends at the first
    `:` and is read before any path, and after it only the first word counts, so `anomaly:review step 10:
    delta` and `anomaly:review asks and/or skips` are the review skill. `plugin` is gitrepo.plugin_repo's answer."""
    target = target.strip()
    if not target:
        return None
    root = Path(context.plugin_root)
    qualifier, colon, rest = target.partition(':')   # flags.resolve_target reads a target differently (paths first)
    if colon and flags.names_this_plugin(context, qualifier, plugin):
        name = (rest.split() or [''])[0]
        if not privacy.is_identifier(name) or ':' in name:
            return PluginPart(None, False, None)
        if (root / 'skills' / name / flags.SKILL_FILE).is_file():
            return PluginPart(name, False, root / 'skills' / name)
        if (root / PLUGIN_AGENTS_DIR / f'{name}.md').is_file():
            return PluginPart(name, True, root / PLUGIN_AGENTS_DIR / f'{name}.md')
        return PluginPart(None, False, None)
    if flags.is_path(target):
        found = flags.target_path(context, target, plugin)
        folders = [root] + ([Path(plugin[1])] if plugin else [])
        base = next((f for f in folders if found is not None and found.resolve().is_relative_to(f.resolve())), None)
        if base is None:
            return None
        parts = found.resolve().relative_to(base.resolve()).parts
        if len(parts) >= 2 and parts[0] == 'skills' and (base / 'skills' / parts[1] / flags.SKILL_FILE).is_file():
            return PluginPart(parts[1], False, base / 'skills' / parts[1])
        if len(parts) == 2 and parts[0] == PLUGIN_AGENTS_DIR and found.suffix == '.md' and found.is_file():
            return PluginPart(found.stem, True, found)
        return PluginPart(None, False, None)
    return None


def writable(context):
    """signature -> Anomaly from a strict Context, for a command that reads the context and then
    writes: home is read once, and the records are copied so the context itself is never changed."""
    return {a.signature: copy.deepcopy(a) for a in context.anomalies}


def find(anomalies, signature):
    anomaly = anomalies.get(signature)
    if anomaly is None:
        raise RecordError(f'no anomaly {signature!r} in home')
    return anomaly

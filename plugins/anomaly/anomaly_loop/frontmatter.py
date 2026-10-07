"""The `---` block at the top of a Markdown file, shared by the profile, the records and the ideas;
the tests read the skill and agent files with it too.

Each line is `key: value`; a key may hold hyphens (`allowed-tools`). A line that starts with a
space or tab continues the previous value (continuation lines are joined with newlines,
stripped). Lines starting with `#` are comments. One pair of matching outer quotes around a
value is removed. Without a closed block there are no fields and the whole text is body.
"""
import re

KEY_LINE = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*)\s*:(.*)$')
NESTED_LINE = re.compile(r'([A-Za-z0-9_][A-Za-z0-9_-]*)\s*:(.*)$')
NAMED_LINE = re.compile(r'([A-Za-z0-9_](?:[A-Za-z0-9_ -]*[A-Za-z0-9_])?)\s*:(?:\s+(.*)|\s*)')


def split(text):
    """Return (fields, body): the frontmatter values and the text after the closing `---`."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, text
    values, current = {}, None
    for number, line in enumerate(lines[1:], start=1):
        if line.strip() == '---':
            fields = {key: strip_quotes('\n'.join(parts).strip()) for key, parts in values.items()}
            return fields, '\n'.join(lines[number + 1:])
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if line[0] in ' \t':
            if current:
                values[current].append(line.strip())
            continue
        found = KEY_LINE.match(line)
        if found:
            current = found.group(1)
            values[current] = [found.group(2).strip()]
    return {}, text


def strip_quotes(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def pairs(value):
    """The `name: value` continuation lines of a nested value, as a dict (a name may hold hyphens)."""
    found = (NESTED_LINE.match(line) for line in value.splitlines())
    return {m.group(1): m.group(2).strip() for m in found if m}


def nested(value):
    """(pairs, other lines) of a nested value. A pair is a `name: value` line with a space (or the
    end of the line) after the colon; the name may hold spaces and hyphens. So an id with a colon
    inside, such as `pack:agent`, is never split: it is one of the other lines. A repeated name
    keeps its last value, as a repeated key does in `split`. Blank lines are skipped; every
    value and line is stripped."""
    found, other = {}, []
    for line in value.splitlines():
        line = line.strip()
        match = NAMED_LINE.fullmatch(line)
        if match:
            found[match.group(1)] = (match.group(2) or '').strip()
        elif line:
            other.append(line)
    return found, other


def items(value):
    """The `- item` continuation lines of a list value."""
    return [line[2:].strip() for line in value.splitlines() if line.startswith('- ')]


def render(fields):
    """Frontmatter lines for (key, value) pairs; a dict value nests, a list value is `- item` lines."""
    lines = ['---']
    for key, value in fields:
        if isinstance(value, dict):
            lines.append(f'{key}:')
            lines += [f'  {name}: {item}'.rstrip() for name, item in value.items()]
        elif isinstance(value, (list, tuple)):
            lines.append(f'{key}:')
            lines += [f'  - {item}' for item in value]
        else:
            lines.append(f'{key}: {value}'.rstrip())
    lines.append('---')
    return lines

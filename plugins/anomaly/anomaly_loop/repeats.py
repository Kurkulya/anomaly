"""The digest section for repeated actions.

An action is a candidate when it was seen REPEAT_MIN_SIGHTINGS or more times in at least
REPEAT_MIN_SESSIONS sessions within the last REPEAT_WINDOW_DAYS days (today included). Four kinds:
  - prompt: a human prompt from the prompt cache under the data folder, normalized (lower case,
    punctuation trimmed at word edges, numbers and ids replaced as in metrics.normalize_atom).
    Prompts shorter than REPEAT_MIN_PROMPT_WORDS words, prompts that start a slash command
    (metrics.COMMAND_NAME) and prompts that start with `<` (harness or command markup such as
    `<system-reminder>`, which older cache lines still hold) are not counted. A prompt is
    printed cut to PROMPT_SHOW_CHARS characters. Without a data folder the kind is skipped, and
    when the section has other lines it says so;
  - command shape: `bash_shapes` of the metrics rows, without the READ_ONLY_SHAPES (commands that
    only read are not worth automating) and without shapes that only set a shell variable
    (`S=<str>`, or `B=<str> branch)` in rows scanned before metrics.normalize_shape dropped a
    command substitution value).
    Shapes are ranked by the number of sessions, then by times seen, because one long session
    can repeat a command many times;
  - tool trigram: `tool_trigrams` of the metrics rows. Rows scanned before that field existed
    have none and are skipped. A trigram of one tool three times (`Read>Read>Read`) is a loop,
    not a sequence, and is left out;
  - slash command: `slash_commands` of the metrics rows, only the ones that are a skill: a
    `plugin:skill` name (built-in commands have no colon), or a bare name that is a skill of this
    plugin or of the user config folder. Other bare names (`/reload-plugins`) are built-ins.
A row belongs to the window by the day its session started, a prompt by the day it was written,
both in the clock of the digest's context (trends.session_day).

Each candidate names the lightest form that fits and why. The forms, lightest first, are script,
hook or lint rule, pointer, skill and agent; this section proposes the first four, and never an
agent (that is for isolating context, which calibrate decides with the user). The pick is a rule
of thumb that calibrate may overrule:
  command shape -> script; tool trigram -> hook or lint rule; slash command -> pointer;
  prompt -> pointer when it has at most REPEAT_POINTER_MAX_WORDS words, else skill.
"""
import re
from collections import Counter, defaultdict

from . import metrics, records, trends
from .constants import (FLAGS_SHOW, PROMPT_CACHE_FILE, PROMPT_SHOW_CHARS, READ_ONLY_SHAPES, REPEAT_MIN_PROMPT_WORDS,
                        REPEAT_MIN_SESSIONS, REPEAT_MIN_SIGHTINGS, REPEAT_POINTER_MAX_WORDS, REPEAT_WINDOW_DAYS)
from .files import load_lines
from .flags import is_user_skill, plugin_skills

EDGE_PUNCTUATION = '.,;:!?"\'()[]{}'
ASSIGNMENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*=<str>')   # metrics.normalize_word's form of NAME=value

FORMS = {
    'command shape': ('script', 'the same command is typed again and again, so a small script or alias '
                                'runs it with no model step'),
    'tool trigram': ('hook or lint rule', 'the same tool sequence repeats; a hook can run it on its own '
                                          'and a lint rule can enforce its result'),
    'slash command': ('pointer', 'it is typed by hand each time; one line in a steering file can tell '
                                 'the agent to run it at the right moment'),
}
SHORT_PROMPT = ('pointer', 'a short instruction said again and again fits one line in a steering file')
LONG_PROMPT = ('skill', 'a long instruction repeated word for word is a procedure; a skill loads '
                        'only when it is needed')


def lightest_form(kind, text):
    """(form, why) for one kind of repeated action; `text` is the action (its length decides for a prompt)."""
    if kind == 'prompt':
        return SHORT_PROMPT if len(text.split()) <= REPEAT_POINTER_MAX_WORDS else LONG_PROMPT
    return FORMS[kind]


def normalize_prompt(text):
    """A prompt as comparable words: lower case, edge punctuation off, ids and numbers replaced."""
    words = (word.strip(EDGE_PUNCTUATION) for word in text.casefold().split())
    return ' '.join(metrics.normalize_atom(word) for word in words if word)


def tally_rows(rows, field):
    """key -> (times seen, sessions seen in) over one counter field of the metrics rows."""
    counts, sessions = Counter(), defaultdict(set)
    for number, row in enumerate(rows):
        table = row.get(field)
        for key, times in (table.items() if isinstance(table, dict) else ()):
            if records.is_whole(times) and times > 0:
                counts[key] += times
                sessions[key].add(row.get('session_id') or f'row {number}')
    return {key: (counts[key], len(sessions[key])) for key in counts}


def tally_prompts(context, since):
    counts, sessions = Counter(), defaultdict(set)
    for number, entry in enumerate(load_lines(context.data / PROMPT_CACHE_FILE)):
        text, day = entry.get('text'), trends.session_day({'first_ts': entry.get('ts')}, context.now.tzinfo)
        if (not isinstance(text, str) or text.lstrip().startswith('<') or metrics.COMMAND_NAME.search(text)
                or not day or not since <= day <= context.today):
            continue
        prompt = normalize_prompt(text)
        if len(prompt.split()) >= REPEAT_MIN_PROMPT_WORDS:
            counts[prompt] += 1
            sessions[prompt].add(entry.get('session_id') or f'prompt {number}')
    return {key: (counts[key], len(sessions[key])) for key in counts}


def shown(text):
    return text if len(text) <= PROMPT_SHOW_CHARS else text[:PROMPT_SHOW_CHARS - 1] + '…'


def is_read_only(shape):
    return any(shape == prefix or shape.startswith(prefix + ' ') for prefix in READ_ONLY_SHAPES)


def is_assignment(shape):
    """True for a shape that only sets a shell variable: `NAME=<str>` alone, or followed by the rest
    of a command substitution cut into words (the last word ends with `)`). `NAME=<str> cmd ...`
    runs cmd and is a command."""
    words = shape.split()
    return bool(words) and ASSIGNMENT.fullmatch(words[0]) is not None and (
        len(words) == 1 or words[-1].endswith(')'))


def is_skill_name(context, command):
    """True for a slash command that is a skill: `/plugin:skill`, or a bare name of a skill of this
    plugin or the user config folder (anything else bare is a built-in command)."""
    name = command.lstrip('/')
    return ':' in name or name in plugin_skills(context.plugin_root) or is_user_skill(context, name)


def candidate_lines(kind, tally, by_sessions=False):
    found = sorted(((key, times, sessions) for key, (times, sessions) in tally.items()
                    if times >= REPEAT_MIN_SIGHTINGS and sessions >= REPEAT_MIN_SESSIONS),
                   key=lambda item: (-item[2], -item[1], item[0]) if by_sessions else (-item[1], -item[2], item[0]))
    lines = []
    for key, times, sessions in found[:FLAGS_SHOW]:
        form, why = lightest_form(kind, key)
        text = shown(key) if kind == 'prompt' else key
        lines.append(f'- {kind} "{text}": {times} times in {sessions} sessions; lightest form: {form}, because {why}')
    if len(found) > FLAGS_SHOW:
        lines.append(f'- {len(found) - FLAGS_SHOW} more {kind}s')
    return lines


def repeated_actions(context):
    since = trends.window_start(context.today, REPEAT_WINDOW_DAYS)
    rows = [row for _, row in trends.rows_in_window(context, since)]
    lines = [] if context.data is None else candidate_lines('prompt', tally_prompts(context, since))
    shapes = {key: value for key, value in tally_rows(rows, 'bash_shapes').items()
              if not (is_read_only(key) or is_assignment(key))}
    lines += candidate_lines('command shape', shapes, by_sessions=True)
    trigrams = {key.replace('>', ' > '): value for key, value in tally_rows(rows, 'tool_trigrams').items()
                if len(set(key.split('>'))) > 1}
    lines += candidate_lines('tool trigram', trigrams)
    commands = {key: value for key, value in tally_rows(rows, 'slash_commands').items()
                if is_skill_name(context, key)}
    lines += candidate_lines('slash command', commands)
    if lines and context.data is None:
        lines.append('- prompts not checked: no data folder, so no prompt cache')
    return ['## Repeated actions'] + lines if lines else []

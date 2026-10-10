"""Session metrics scanner.

Streams Claude Code transcripts (<projects>/<project>/<session>.jsonl, plus
<session>/subagents/agent-*.jsonl rolled into their parent) and upserts one row per main
session into the metrics file under home. Human prompts go, redacted and cut to 200 chars,
into the prompt cache under the data folder (local only, pruned after 30 days).

Counting rules: one API call is written as several entries sharing message.id, so usage is
de-duplicated by (file, message.id) with the MAX of each field. Tools, skills, friction and
time cover the main file and its subagents; prompts, slash commands, titles, branches and
cwd come from the main file only.

Tool trigrams (`tool_trigrams`: the top MAX_TRIGRAMS runs of three consecutive tool uses, written
`A>B>C`) are counted per transcript, in the order the tools were first used, and added up over
the main file and its subagents: a trigram never spans two files. Rows written before this field
existed (older rows) lack it; `measure --full` fills it for the transcripts still on disk.
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import paths, profile
from .constants import (ACTIVE_GAP_SECONDS, LONG_PROMPT_FACTORS, LONG_PROMPT_TOKENS, METRICS_FILE,
                        MODEL_FACTORS, PROMPT_CACHE_DAYS, PROMPT_CACHE_FILE, STATE_FILE)
from .files import dump, load_lines, write_lines
from .records import number

# Relative price ratios per token kind (input = 1); only the ratios matter here.
# TODO(VK, revisit 2026-12-01): re-check the weights against current list prices — see ADR-0002
WEIGHTS = {'input': 1, 'cache_write': 1.25, 'cache_read': 0.1, 'output': 5}
USAGE_FIELDS = {'input': 'input_tokens', 'cache_write': 'cache_creation_input_tokens',
                'cache_read': 'cache_read_input_tokens', 'output': 'output_tokens'}

MAX_BRANCHES = 20
MAX_SHAPES = 15
MAX_TRIGRAMS = 15
PROMPT_CHARS = 200
PROMPT_SOURCE_CHARS = 2000

COMMAND_NAME = re.compile(r'<command-name>\s*/?([^<\s]+)\s*</command-name>')
INTERRUPT_PREFIX = '[Request interrupted by user'
NOT_PROMPT_PREFIXES = ('<local-command-', '<bash-', '<system-reminder>')


# ---------- reading ----------

def iter_entries(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if not line.strip() or line.startswith('{"type":"file-history-'):
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                yield entry


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def list_sessions(root):
    """Yield (project_dir_name, main_transcript, [subagent transcripts])."""
    for project in sorted(p for p in root.iterdir() if p.is_dir()):
        for main in sorted(project.glob('*.jsonl')):
            subs = sorted((project / main.stem / 'subagents').glob('agent-*.jsonl'))
            yield project.name, main, subs


def meta_path(spawn):
    """The `.meta.json` file beside the transcript `spawn` of a subagent."""
    return spawn.with_suffix('.meta.json')


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


# ---------- redaction and command shapes ----------

SECRET_KEYWORD = re.compile(r'(?<![A-Za-z])(password|token|secret|bearer)(?![A-Za-z])[^\n]*', re.I)
URL_QUERY = re.compile(r'(https?://[^\s?#]*)\?\S*')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+')
LONG_RUN = re.compile(r'[A-Za-z0-9+/=_-]{20,}')
WORDY_RUN = re.compile(r'[a-z]+(?:[-/_][a-z]+)+')
HEX_ID = re.compile(r'(?<![A-Za-z0-9])(?=[0-9a-f]*\d)[0-9a-f]{7,}(?![A-Za-z0-9])')
NUMBER = re.compile(r'(?<![A-Za-z0-9])\d+')
# NAME=$(...) as a word: the command substitution (one level of nesting, or unclosed to the end of
# the line) is the variable's value, not the command, so the shape keeps only NAME=<str>.
SUBSTITUTED_VALUE = re.compile(r'(?<!\S)([A-Za-z_][A-Za-z0-9_]*=)\$\((?:[^()]|\([^()]*\))*(?:\)|$)')


def scrub_runs(text, placeholder):
    """Replace 20+ char base64/hex-like runs; keep readable kebab-case words and paths."""
    return LONG_RUN.sub(
        lambda m: m.group(0) if WORDY_RUN.fullmatch(m.group(0)) else placeholder, text)


def redact(text):
    text = SECRET_KEYWORD.sub(lambda m: m.group(1) + ' <redacted>', text)
    text = URL_QUERY.sub(r'\1?<query>', text)
    text = EMAIL.sub('<email>', text)
    return scrub_runs(text, '<redacted>')


def normalize_atom(word):
    word = scrub_runs(word, '<id>')
    word = HEX_ID.sub('<id>', word)
    return NUMBER.sub('<id>', word)


def normalize_path(word):
    parts = [p for p in word.replace('\\', '/').split('/') if p]
    prefix = '/' if word.startswith(('/', '\\')) else ''
    return f'{prefix}{normalize_atom(parts[0]) if parts else ""}/<path>'


def normalize_word(word):
    env = re.match(r'([A-Za-z_][A-Za-z0-9_]*)=', word)
    if env:
        return env.group(1) + '=<str>'
    if word.startswith('-'):
        name, sep, _ = word.partition('=')
        return normalize_atom(name) + ('=<str>' if sep else '')
    if '/' in word or '\\' in word:
        return normalize_path(word)
    return normalize_atom(word)


def normalize_shape(command):
    """First three words of the first simple command, with values replaced by placeholders."""
    if not isinstance(command, str) or not command.strip():
        return ''
    line = command.strip().splitlines()[0]
    line = re.sub(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'', '<str>', line)
    line = re.sub(r'["\'].*$', '<str>', line)
    line = SUBSTITUTED_VALUE.sub(r'\1<str>', line)
    while True:
        stripped = re.match(r'\s*cd\s+\S+\s*(?:&&|;)\s*(.*)$', line)
        if not stripped:
            break
        line = stripped.group(1)
    line = re.split(r'&&|\|\||;|\|', line, maxsplit=1)[0]
    return ' '.join(normalize_word(w) for w in line.split()[:3])


# ---------- per-session accumulation ----------

def new_bucket():
    return dict.fromkeys(USAGE_FIELDS, 0)


def add_bucket(target, source):
    for key in USAGE_FIELDS:
        target[key] += source[key]


def weighted(bucket):
    return round(sum(WEIGHTS[k] * bucket[k] for k in WEIGHTS), 2)


def with_weighted(bucket):
    return {**bucket, 'weighted': weighted(bucket)}


def bucket_for(table, key):
    return table.setdefault(key, new_bucket())


def model_factor(model, tokens):
    """The price factor of one API call (MODEL_FACTORS, with the long-prompt tier of LONG_PROMPT_FACTORS),
    from the family word in `model` and the call's `tokens` bucket; None for a model with no factor."""
    family = next((name for name in MODEL_FACTORS if name in model.lower()), None)
    if family is None:
        return None
    prompt = tokens['input'] + tokens['cache_write'] + tokens['cache_read']
    if prompt > LONG_PROMPT_TOKENS:
        return LONG_PROMPT_FACTORS.get(family, MODEL_FACTORS[family])
    return MODEL_FACTORS[family]


class Accumulator:
    def __init__(self):
        self.epochs = []
        self.first = self.last = None
        self.tokens = {'main': {}, 'subagent': {}}
        self.by_skill, self.by_agent = {}, {}
        self.tools, self.skills, self.shapes = Counter(), Counter(), Counter()
        self.trigrams = Counter()
        self.slash = Counter()
        self.questions = self.prompts = 0
        self.branches, self.cwds = [], []
        self.title = self.agent_name = None
        self.interrupts = self.hook_blocks = self.policy_blocks = self.compactions = 0
        self.denial_kinds, self.denial_tools, self.denial_pairs = Counter(), Counter(), Counter()
        self.subagent_meta = []
        self.model_weighted, self.unknown_models = Counter(), Counter()
        self.skipped_entries = self.skipped_spawns = 0

    def add_ts(self, value):
        epoch = parse_ts(value)
        if epoch is None:
            return
        self.epochs.append(epoch)
        if self.first is None or epoch < self.first[0]:
            self.first = (epoch, value)
        if self.last is None or epoch > self.last[0]:
            self.last = (epoch, value)

    def add_context(self, entry):
        branch, cwd = entry.get('gitBranch'), entry.get('cwd')
        if branch and branch not in self.branches:
            self.branches.append(branch)
        if cwd and cwd not in self.cwds:
            self.cwds.append(cwd)
        if 'customTitle' in entry:
            self.title = entry['customTitle']
        if 'agentName' in entry:
            self.agent_name = entry['agentName']

    def add_call(self, call, scope):
        add_bucket(bucket_for(self.tokens[scope], call['model']), call['tokens'])
        for table, key in ((self.by_skill, call['skill']), (self.by_agent, call['agent'])):
            if key:
                add_bucket(bucket_for(table, key), call['tokens'])
        if call['agent']:
            factor = model_factor(call['model'], call['tokens'])
            self.model_weighted[call['agent']] += 0 if factor is None else weighted(call['tokens']) * factor
            if factor is None:
                self.unknown_models[call['agent']] += 1

    def add_trigrams(self, names):
        """Count the runs of three consecutive tool names of one transcript (in first-use order)."""
        for first, second, third in zip(names, names[1:], names[2:]):
            self.trigrams[f'{first}>{second}>{third}'] += 1

    def add_denial(self, kind, tool):
        self.denial_kinds[kind] += 1
        self.denial_tools[tool] += 1
        self.denial_pairs[f'{kind}:{tool}'] += 1


def content_blocks(message):
    content = message.get('content') if isinstance(message, dict) else None
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}]
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def result_text(block):
    content = block.get('content')
    if isinstance(content, list):
        content = '\n'.join(b.get('text', '') for b in content if isinstance(b, dict))
    return content.lstrip() if isinstance(content, str) else ''


def read_call(entry, message, calls):
    """Add the usage of an assistant entry to `calls` (one call per message id). Returns True when the
    entry is skipped for a missing `model` or `usage`; a `<synthetic>` entry is skipped without being counted."""
    usage = message.get('usage')
    model = message.get('model')
    if model == '<synthetic>':
        return False
    if not isinstance(usage, dict) or not model:
        return True
    key = message.get('id') or entry.get('uuid') or id(entry)
    call = calls.setdefault(key, {'model': model, 'tokens': new_bucket(), 'skill': None, 'agent': None})
    for field, source in USAGE_FIELDS.items():
        value = usage.get(source)
        if isinstance(value, int):
            call['tokens'][field] = max(call['tokens'][field], value)
    call['skill'] = call['skill'] or entry.get('attributionSkill')
    call['agent'] = call['agent'] or entry.get('attributionAgent')
    return False


def read_tool_uses(acc, message, is_main, tool_names):
    for block in content_blocks(message):
        if block.get('type') != 'tool_use' or block.get('id') in tool_names:
            continue
        name = block.get('name') or 'unknown'
        tool_names[block.get('id')] = name
        acc.tools[name] += 1
        tool_input = block.get('input') if isinstance(block.get('input'), dict) else {}
        if name == 'Skill' and tool_input.get('skill'):
            acc.skills[str(tool_input['skill']).lstrip('/')] += 1
        elif name == 'Bash':
            shape = normalize_shape(tool_input.get('command'))
            if shape:
                acc.shapes[shape] += 1
        elif name == 'AskUserQuestion' and is_main:
            acc.questions += 1


def read_results(acc, entry, results, tool_names):
    kind = entry.get('toolDenialKind')
    if kind:
        for block in results or [{}]:
            acc.add_denial(kind, tool_names.get(block.get('tool_use_id'), 'unknown'))
    for block in results:
        if not block.get('is_error'):
            continue
        text = result_text(block)
        if text.startswith('PreToolUse:'):
            acc.hook_blocks += 1
        elif text.startswith('Blocked:') or 'Enterprise policy' in text:
            acc.policy_blocks += 1


def human_prompt_text(entry, blocks):
    """Text of a real human prompt, or None for tool results, meta, summaries and bot input."""
    origin = entry.get('origin')
    kind = origin.get('kind') if isinstance(origin, dict) else origin
    if kind not in (None, 'human') or entry.get('isMeta') or entry.get('isCompactSummary'):
        return None
    if entry.get('isSidechain') or any(b.get('type') == 'tool_result' for b in blocks):
        return None
    text = '\n'.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
    if not text.strip() or text.lstrip().startswith(NOT_PROMPT_PREFIXES + (INTERRUPT_PREFIX,)):
        return None
    return text


def read_user(acc, entry, is_main, tool_names, prompts, session_id):
    blocks = content_blocks(entry.get('message'))
    results = [b for b in blocks if b.get('type') == 'tool_result']
    if any(b.get('type') == 'text' and str(b.get('text', '')).startswith(INTERRUPT_PREFIX) for b in blocks):
        acc.interrupts += 1
    read_results(acc, entry, results, tool_names)
    text = human_prompt_text(entry, blocks) if is_main else None
    if text is None:
        return
    acc.prompts += 1
    command = COMMAND_NAME.search(text)
    if command:
        acc.slash['/' + command.group(1)] += 1
        return
    prompts.append({'session_id': session_id, 'ts': entry.get('timestamp'),
                    'text': redact(text[:PROMPT_SOURCE_CHARS])[:PROMPT_CHARS]})


def scan_file(acc, path, is_main, session_id, prompts):
    calls, tool_names = {}, {}
    try:
        for entry in iter_entries(path):
            acc.add_ts(entry.get('timestamp'))
            if is_main:
                acc.add_context(entry)
            kind = entry.get('type')
            if kind == 'assistant':
                message = entry.get('message') if isinstance(entry.get('message'), dict) else {}
                acc.skipped_entries += read_call(entry, message, calls)
                read_tool_uses(acc, message, is_main, tool_names)
            elif kind == 'user':
                read_user(acc, entry, is_main, tool_names, prompts, session_id)
            elif kind == 'system' and entry.get('subtype') == 'compact_boundary':
                acc.compactions += 1
    except OSError:
        return
    acc.add_trigrams(list(tool_names.values()))
    for call in calls.values():
        acc.add_call(call, 'main' if is_main else 'subagent')


def span_seconds(epochs):
    """Whole seconds from the earliest to the latest of `epochs`; 0 for fewer than two."""
    return round(max(epochs) - min(epochs)) if len(epochs) > 1 else 0


def subagent_summary(subs, spans):
    """Counts and seconds of the spawn files `subs`; `spans` holds the seconds of each, as
    `span_seconds` gave them."""
    by_type, by_model, stopped = Counter(), Counter(), 0
    seconds_by_type, seconds_by_model = Counter(), Counter()
    for path, seconds in zip(subs, spans, strict=True):
        meta = load_json(meta_path(path), {})
        meta = meta if isinstance(meta, dict) else {}
        agent_type = meta.get('agentType') or 'unknown'
        model = meta.get('model') or 'unknown'
        by_type[agent_type] += 1
        by_model[model] += 1
        seconds_by_type[agent_type] += seconds
        seconds_by_model[model] += seconds
        stopped += bool(meta.get('stoppedByUser'))
    return {'count': len(subs), 'by_type': dict(by_type), 'by_model': dict(by_model),
            'stopped_by_user': stopped, 'seconds_by_type': dict(seconds_by_type),
            'seconds_by_model': dict(seconds_by_model)}


def active_seconds(epochs):
    ordered = sorted(epochs)
    gaps = (b - a for a, b in zip(ordered, ordered[1:]))
    return sum(g for g in gaps if g <= ACTIVE_GAP_SECONDS)


def ranked(counter):
    return dict(counter.most_common())


def build_row(acc, session_id, project_dir, ticket_key):
    keys = []
    for branch in acc.branches:
        keys += [m.group(0) for m in ticket_key.finditer(branch) if m.group(0) and m.group(0) not in keys]
    total = new_bucket()
    for scope in acc.tokens.values():
        for bucket in scope.values():
            add_bucket(total, bucket)
    by_skill = sorted(((k, with_weighted(v)) for k, v in acc.by_skill.items()),
                      key=lambda kv: kv[1]['weighted'], reverse=True)
    by_agent = sorted(((k, with_weighted(v)) for k, v in acc.by_agent.items()),
                      key=lambda kv: kv[1]['weighted'], reverse=True)
    return {
        'session_id': session_id,
        'project_dir': project_dir,
        'cwd_first': acc.cwds[0] if acc.cwds else None,
        'cwd_count': len(acc.cwds),
        'first_ts': acc.first[1],
        'last_ts': acc.last[1],
        'wall_min': round((acc.last[0] - acc.first[0]) / 60, 1),
        'active_min': round(active_seconds(acc.epochs) / 60, 1),
        'branches': acc.branches[:MAX_BRANCHES],
        'ticket_keys': keys,
        'title': acc.title,
        'agent_name': acc.agent_name,
        'tokens': acc.tokens,
        'weighted': weighted(total),
        'tokens_by_skill': dict(by_skill),
        'tokens_by_agent': dict(by_agent),
        'model_weighted_by_agent': {k: round(acc.model_weighted[k], 4) for k, _ in by_agent},
        'unknown_model_by_agent': ranked(acc.unknown_models),
        'subagents': acc.subagent_meta,
        'skipped_entries': acc.skipped_entries,
        'skipped_spawns': acc.skipped_spawns,
        'tools': ranked(acc.tools),
        'skills_invoked': ranked(acc.skills),
        'slash_commands': ranked(acc.slash),
        'bash_shapes': dict(acc.shapes.most_common(MAX_SHAPES)),
        'tool_trigrams': dict(acc.trigrams.most_common(MAX_TRIGRAMS)),
        'friction': {
            'interrupts': acc.interrupts,
            'denials': {'total': sum(acc.denial_kinds.values()), 'by_kind': ranked(acc.denial_kinds),
                        'by_tool': ranked(acc.denial_tools), 'by_kind_tool': ranked(acc.denial_pairs)},
            'hook_blocks': acc.hook_blocks,
            'policy_blocks': acc.policy_blocks,
            'compactions': acc.compactions,
        },
        'ask_user_questions': acc.questions,
        'human_prompts': acc.prompts,
    }


def summarize_session(session_id, project_dir, main, subs, ticket_key):
    """Return (row, prompts); row is None when the transcript holds no timestamps. A file that breaks
    partway through reading counts the part read."""
    acc, prompts = Accumulator(), []
    scan_file(acc, main, True, session_id, prompts)
    spans = []
    for path in subs:
        start = len(acc.epochs)
        scan_file(acc, path, False, session_id, prompts)
        spans.append(span_seconds(acc.epochs[start:]))
    acc.subagent_meta = subagent_summary(subs, spans)
    acc.skipped_spawns = sum(not meta_path(path).exists() for path in subs)
    if acc.first is None:
        return None, prompts
    return build_row(acc, session_id, project_dir, ticket_key), prompts


# ---------- incremental scan ----------

def file_stamp(path):
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


def session_stamp(main, subs):
    stamp = {str(main): file_stamp(main)}
    for sub in subs:
        stamp[str(sub)] = file_stamp(sub)
        meta = meta_path(sub)
        if meta.exists():
            stamp[str(meta)] = file_stamp(meta)
    return stamp


def prune_prompts(prompts, replaced, now):
    cutoff = (now - timedelta(days=PROMPT_CACHE_DAYS)).timestamp()
    kept = [p for p in prompts if p.get('session_id') not in replaced]
    return [p for p in kept if (parse_ts(p.get('ts')) or 0) >= cutoff]


def scan(projects, out_path, state_path, cache_path, *, now, ticket_key, full=False):
    old_state = {} if full else load_json(state_path, {})
    rows = {r['session_id']: r for r in load_lines(out_path) if 'session_id' in r}
    new_state, replaced, new_prompts = {}, set(), []
    processed = skipped = 0
    for project_dir, main, subs in list_sessions(projects):
        session_id = main.stem
        try:
            stamp = session_stamp(main, subs)
        except OSError:
            continue
        previous = old_state.get(str(main))
        if previous and previous.get('files') == stamp and (not previous.get('row') or session_id in rows):
            new_state[str(main)] = previous
            skipped += 1
            continue
        row, prompts = summarize_session(session_id, project_dir, main, subs, ticket_key)
        if row:
            rows[session_id] = row
        replaced.add(session_id)
        new_prompts += prompts
        new_state[str(main)] = {'files': stamp, 'row': row is not None}
        processed += 1
    ordered = sort_rows(rows.values())
    write_lines(out_path, [dump(r) for r in ordered])
    cache = prune_prompts(load_lines(cache_path), replaced, now) + prune_prompts(new_prompts, set(), now)
    write_lines(cache_path, [dump(p) for p in cache])
    write_lines(state_path, [dump(new_state)])
    return {'processed': processed, 'skipped': skipped, 'rows': len(ordered)}


def sort_rows(rows):
    """Metrics rows in file order: oldest first_ts first, rows without one last."""
    return sorted(rows, key=lambda r: (r.get('first_ts') is None, r.get('first_ts') or ''))


def sum_subagent_seconds(rows, key):
    """The seconds of `subagents.<key>` (`seconds_by_type` or `seconds_by_model`) added up per name over the
    rows that carry it; a value that is not a number is left out."""
    total = Counter()
    for r in rows:
        subagents = r.get('subagents')
        seconds_by = subagents.get(key) if isinstance(subagents, dict) else None
        if isinstance(seconds_by, dict):
            total.update({name: seconds for name, seconds in seconds_by.items() if number(seconds) is not None})
    return dict(total)


def summarize_rows(rows):
    """Row count, first and last timestamp, total weighted tokens and subagent seconds by agent
    type and by model (each summed over the rows that carry `subagents.seconds_by_type` or
    `subagents.seconds_by_model`), and the entries and spawns measure could not read
    (`skipped_entries`, `skipped_spawns`; a row without the field adds 0) of the metrics rows."""
    starts = [r['first_ts'] for r in rows if r.get('first_ts')]
    ends = [r['last_ts'] for r in rows if r.get('last_ts')]
    return {'rows': len(rows), 'first_ts': min(starts) if starts else None,
            'last_ts': max(ends) if ends else None,
            'weighted': round(sum(number(r.get('weighted')) or 0 for r in rows), 2),
            'seconds_by_type': sum_subagent_seconds(rows, 'seconds_by_type'),
            'seconds_by_model': sum_subagent_seconds(rows, 'seconds_by_model'),
            'skipped_entries': sum(number(r.get('skipped_entries')) or 0 for r in rows),
            'skipped_spawns': sum(number(r.get('skipped_spawns')) or 0 for r in rows)}


def skills_used_each(row):
    """The name forms of each skill a session used, one frozenset per name of `skills_invoked`
    and `slash_commands` in row order, by the rule of skills_used (that set is their union). For
    telling one skill from another the session ran beside it, e.g. a switch-over's fall-back."""
    found = []
    for field in ('skills_invoked', 'slash_commands'):
        for name in row.get(field) or ():
            text = name.strip().lstrip('/').strip() if isinstance(name, str) else ''
            if text:
                found.append(frozenset((text, text.rpartition(':')[2])) - {''})
    return found


def skills_used(row):
    """The skills a session used, as one set of names: `skills_invoked` plus `slash_commands`.

    A name is written without its leading `/`, so `/name` and `name` are the same skill. A
    plugin-qualified `plugin:name` is in the set as written and also as the bare `name`, so a
    bare name (a profile build_skills entry) matches the skill from any plugin, while a
    qualified name matches only that plugin's skill. Rows without the fields give an empty set.

    For membership checks only ("was this skill used"): the set holds both name forms and the
    built-in commands too, so it must not be counted or ranked. Rank skills by the row's
    `tokens_by_skill`."""
    return frozenset().union(*skills_used_each(row))


# ---------- the measure subcommand ----------

def register(commands, common):
    measure = commands.add_parser('measure', parents=[common],
                                  help='scan transcripts into per-session metrics under home')
    measure.add_argument('--full', action='store_true', help='re-read every session, not only changed ones')
    measure.add_argument('--projects', help='transcript root (default: env ANOMALY_PROJECTS, '
                                            f'then {paths.DEFAULT_PROJECTS})')
    measure.set_defaults(handler=run_measure)


def day(timestamp):
    try:
        return datetime.fromisoformat(timestamp).date().isoformat()
    except (TypeError, ValueError):
        return 'none'


def run_measure(args, environ):
    home = paths.resolve_home(args.home, environ)
    data = paths.resolve_data(args.data, environ, home)
    projects = paths.resolve_projects(args.projects, environ)
    if not projects.is_dir():
        raise paths.PathError(f'transcript folder not found: {projects}')
    loaded = profile.load_profile(home)
    out_path = home / METRICS_FILE
    result = scan(projects=projects, out_path=out_path, state_path=data / STATE_FILE,
                  cache_path=data / PROMPT_CACHE_FILE, full=args.full,
                  now=args.now, ticket_key=profile.ticket_key_pattern(loaded))
    totals = summarize_rows(load_lines(out_path))
    print(f"metrics: processed {result['processed']}, skipped {result['skipped']}, rows {result['rows']}")
    print(f"range: {day(totals['first_ts'])} to {day(totals['last_ts'])}")
    print(f"weighted tokens: {totals['weighted']:,.0f}")
    if totals['seconds_by_type']:
        by_seconds = sorted(totals['seconds_by_type'].items(), key=lambda item: (-item[1], item[0]))
        print('subagent seconds: ' + ', '.join(f'{name} {seconds}' for name, seconds in by_seconds))
    if totals['seconds_by_model']:
        by_seconds = sorted(totals['seconds_by_model'].items(), key=lambda item: (-item[1], item[0]))
        print('subagent seconds by model: ' + ', '.join(f'{name} {seconds}' for name, seconds in by_seconds))
    if totals['skipped_entries'] or totals['skipped_spawns']:
        print(f"not measured: {totals['skipped_entries']} assistant entries without model or usage, "
              f"{totals['skipped_spawns']} spawns without .meta.json")
    print(f'file: {out_path}')
    message = profile.missing_message(loaded)
    if message:
        print(message)
    return 0

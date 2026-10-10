"""`bench score`: score the finding lines of 1 to 3 runs of a reviewer agent against a fixture's
planted-defect list (the folders under tests/bench/, one per agent).

The defect list is JSON: `{"fixture": <name>, "defects": [...], "decoys": [...]}`. A defect has an
`id`, a `min_severity` (Blocker, High or Medium), and `places` (`{"file", "lines": [first, last]}`,
the file as the reviewed repository has it, the lines as the changed file has them) and/or a
`rule` id (rules mode). It may carry a `category` (an OWASP 2021 label such as `A03`, or a list of
them, security) and `unverified: true` (found only by a finding marked unverified). A decoy is
correct code that looks wrong: an `id`, `places` and/or a `rule`.

A finding line is the one every agent prints (AC-55):
`- [<severity>] <path>:<line> — <problem> — fix: <fix> — <observed|unverified>`; the line is split
at the last ` — fix: `; text after the state word (`unverified (not run)`, no em dash in it) is
ignored. Other lines are prose and are ignored. A line that starts like a finding (a bullet, `*`,
`+`, `1.` or `- **`, then a severity word in brackets, in any case) but has another shape is
refused, so a broken line cannot turn into a silent miss; a bracket word that is not a severity
(`- [Done]`, `- [README](...)`) is prose.

Scoring (AC-14), per run:
- A finding matches a defect when it names the planted file with a line inside the planted range
  plus or minus BENCH_WINDOW, or quotes the defect's rule id as a whole token in its problem or fix.
- found: a finding of Medium or higher matches the defect (and, for an `unverified` defect, is
  marked unverified); found at min severity: such a finding is at least the defect's min severity.
- category right: a found defect with a `category` that a matching finding names in its problem
  text: the first OWASP label (`A03`, `A03:2021`, `A03-Injection`, `OWASP-A03`; a one-digit `A3`
  only as `OWASP-A3` or `A3:2021`, because a bare `A1` is as likely a cell) or public category
  name (`Injection`) there, whichever stands first.
- false High: a Blocker or High that matches no planted defect; one that matches a decoy is named.
With several runs each number is the median over the runs (the mean of the two for two runs).

`bench facts` scores the answers of 1 to 3 runs of a reader agent against a facts list
(`tests/bench/facts/facts.json`): `{"fixture": <name>, "questions": [...], "facts": [...],
"decoys": [...]}`. A question has an `id`, a `kind` (`call-chain`, `moved-claim` or `none-callers`)
and its `ask` text; an expected fact or a decoy (a plausible wrong answer) has an `id`, the `question`
it answers and `places`, written as above. An answer line is `- <path>:<line> — <fact>`; a bullet
that holds a `<path>:<digits>` place and an em dash but has another shape (a backticked path, a line
range, bold) is refused; every other line is prose. An answer names a place of an item by the rule above, so the finding-line parser is
not used. Per run: the expected facts found, the ones missed, and each decoy hit; with several runs
the median of the counts.
"""
import json
import re
from dataclasses import dataclass
from statistics import median

from . import files, flags, trends
from .constants import (BENCH_FALSE_HIGH, BENCH_FOUND_FLOOR, BENCH_MAX_RUNS, BENCH_WINDOW, FINDING_SEVERITIES,
                        FINDING_STATES, OWASP_2021)
from .files import RecordError

SEVERITY_WORDS = '|'.join(FINDING_SEVERITIES)
RANK = {name: number for number, name in enumerate(FINDING_SEVERITIES)}
FINDING = re.compile(
    rf'^\s*-\s+\[(?P<severity>{SEVERITY_WORDS})\]\s+(?P<path>\S.*?):(?P<line>\d+)\s+—\s+'
    r'(?P<problem>.*)\s+—\s+fix:\s*(?P<fix>.*?)\s+—\s+(?P<state>' + '|'.join(FINDING_STATES) + r')(?:[\s(.,;:][^—]*)?$')
LOOKS_LIKE_FINDING = re.compile(rf'^\s*(?:[-*+]|\d+[.)])\s+(?:\*\*)?\[(?:{SEVERITY_WORDS})\]', re.IGNORECASE)
LABEL = re.compile(   # A03 and A10 stand bare; a one-digit A3 needs the OWASP prefix or the :2021 suffix (A1 is a cell)
    r'(?<!\w)(?:OWASP[- ]?A(?P<prefixed>0?[1-9]|10)|A(?P<bare>0[1-9]|10)|A(?P<suffixed>[1-9])(?=:2021))(?!\w)')
LABELS = tuple(label for label, _ in OWASP_2021)
CATEGORY_NAME = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(name) for _, name in OWASP_2021) + r')(?!\w)',
                           re.IGNORECASE)
LABEL_OF_NAME = {name.casefold(): label for label, name in OWASP_2021}
SHAPE = ('- [<severity>] <path>:<line> <dash> <problem> <dash> fix: <fix> <dash> <observed|unverified>, '
         'where <dash> is an em dash (U+2014)')
FACT_KINDS = ('call-chain', 'moved-claim', 'none-callers')
ANSWER = re.compile(r'^\s*-\s+(?P<path>[^\s`*]+):(?P<line>\d+)\s+—\s+(?P<fact>\S.*?)\s*$')
LOOKS_LIKE_ANSWER = re.compile(r'^\s*-\s+.*\S:\d+.*—')
ANSWER_SHAPE = ('- <path>:<line> <dash> <fact>, with a bare path and one line number (no backticks, no range, '
                'no bold), where <dash> is an em dash (U+2014)')


@dataclass(frozen=True)
class Place:
    file: str
    first: int
    last: int


@dataclass(frozen=True)
class Item:
    """A planted defect or a decoy."""
    id: str
    places: tuple
    rule: str = ''
    min_severity: str = ''
    category: tuple = ()
    unverified: bool = False


@dataclass(frozen=True)
class Fixture:
    name: str
    defects: tuple
    decoys: tuple


@dataclass(frozen=True)
class Question:
    id: str
    kind: str
    ask: str


@dataclass(frozen=True)
class Facts:
    name: str
    questions: tuple
    facts: tuple   # Items: the expected facts
    decoys: tuple


@dataclass(frozen=True)
class Answer:
    path: str
    line: int
    fact: str


@dataclass(frozen=True)
class FactsRun:
    found: tuple
    decoy_hits: tuple


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    line: int
    problem: str
    fix: str
    state: str

    @property
    def category(self):
        return category_of(self.problem)


@dataclass(frozen=True)
class FalseHigh:
    finding: Finding
    decoy: str


@dataclass(frozen=True)
class Run:
    found: tuple
    at_min: tuple
    category_right: tuple
    missed: tuple
    false_high: tuple


def category_of(text):
    """The OWASP 2021 label (`A03`) of the first label or public category name in `text`; '' when it
    holds none."""
    found = []
    label = LABEL.search(text)
    if label:
        found.append((label.start(), f'A{int(label["prefixed"] or label["bare"] or label["suffixed"]):02d}'))
    name = CATEGORY_NAME.search(text)
    if name:
        found.append((name.start(), LABEL_OF_NAME[name.group().casefold()]))
    return min(found)[1] if found else ''


def normal(path):
    """A path with forward slashes and no leading `./`."""
    path = path.replace('\\', '/')
    while path.startswith('./'):
        path = path[2:]
    return path


def parse_place(source, where, place):
    lines = place.get('lines') if isinstance(place, dict) else None
    ints = isinstance(lines, list) and len(lines) == 2 and all(type(n) is int for n in lines)
    if not (isinstance(place, dict) and isinstance(place.get('file'), str) and place['file'] and ints
            and 1 <= lines[0] <= lines[1]):
        raise RecordError(f'{source}: {where}: a place is {{"file": <path>, "lines": [first, last]}}, '
                          'with 1 <= first <= last')
    return Place(normal(place['file']), lines[0], lines[1])


def parse_item(source, kind, number, raw, planted):
    where = f'{kind}[{number}]'
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not raw['id']:
        raise RecordError(f'{source}: {where}: needs an id')
    where = f'{kind} {raw["id"]}'
    places = raw.get('places', [])
    if not isinstance(places, list):
        raise RecordError(f'{source}: {where}: places is a list')
    places = tuple(parse_place(source, where, place) for place in places)
    rule = raw.get('rule', '')
    if not isinstance(rule, str):
        raise RecordError(f'{source}: {where}: rule is text')
    if not places and not rule:
        raise RecordError(f'{source}: {where}: needs places or a rule id')
    if not planted:
        return Item(raw['id'], places, rule)
    severity = raw.get('min_severity')
    if severity not in RANK or RANK[severity] > RANK[BENCH_FOUND_FLOOR]:
        allowed = ', '.join(name for name in FINDING_SEVERITIES if RANK[name] <= RANK[BENCH_FOUND_FLOOR])
        raise RecordError(f'{source}: {where}: min_severity is one of {allowed}')
    category = raw.get('category', ())
    category = (category,) if isinstance(category, str) else category
    if not isinstance(category, (list, tuple)) or ('category' in raw and not category) \
            or any(label not in LABELS for label in category):
        raise RecordError(f'{source}: {where}: category is an OWASP 2021 label such as A03, or a list of them')
    category = tuple(category)
    if not isinstance(raw.get('unverified', False), bool):
        raise RecordError(f'{source}: {where}: unverified is true or false')
    return Item(raw['id'], places, rule, severity, category, raw.get('unverified', False))


def load_fixture(source):
    """The Fixture in the defect list `source`; a list that does not fit raises RecordError."""
    text = files.read_input(source)
    try:
        data = json.loads(text)
    except ValueError as error:
        raise RecordError(f'{source}: not JSON ({error})') from None
    if not isinstance(data, dict):
        raise RecordError(f'{source}: the defect list is a JSON object with "defects" and "decoys"')
    groups = {}
    for kind, planted in (('defects', True), ('decoys', False)):
        raw = data.get(kind, [] if kind == 'decoys' else None)
        if not isinstance(raw, list) or (planted and not raw):
            raise RecordError(f'{source}: "{kind}" is a list{" with at least one entry" if planted else ""}')
        groups[kind] = tuple(parse_item(source, kind, number, item, planted) for number, item in enumerate(raw))
    ids = [item.id for item in groups['defects'] + groups['decoys']]
    for ident in sorted(set(ids)):
        if ids.count(ident) > 1:
            raise RecordError(f'{source}: the id {ident} is used twice')
    return Fixture(str(data.get('fixture') or source), groups['defects'], groups['decoys'])


def parse_findings(text, source):
    """The finding lines of one run's text. Prose is skipped; a line that starts like a finding but
    does not have the shape raises RecordError naming `source` and its line number."""
    if not text.strip():
        raise RecordError(f'{source}: no text')
    findings = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = FINDING.match(line)
        if match:
            findings.append(Finding(match['severity'], match['path'], int(match['line']), match['problem'],
                                    match['fix'], match['state']))
        elif LOOKS_LIKE_FINDING.match(line):
            raise RecordError(f'{source}:{number}: not a finding line; the shape is {SHAPE}')
    return findings


def names_rule(rule, finding):
    return bool(re.search(rf'(?<![\w-]){re.escape(rule)}(?![\w-])', f'{finding.problem} {finding.fix}'))


def matches(item, finding):
    """True when the finding names a place of the item (file, line within the range plus or minus the
    window) or quotes the item's rule id."""
    path = normal(finding.path)
    for place in item.places:
        if (path == place.file or path.endswith('/' + place.file)) \
                and place.first - BENCH_WINDOW <= finding.line <= place.last + BENCH_WINDOW:
            return True
    return bool(item.rule) and names_rule(item.rule, finding)


def score_run(fixture, findings):
    """The Run of these findings against the fixture."""
    found, at_min, category_right = [], [], []
    for defect in fixture.defects:
        hits = [finding for finding in findings
                if RANK[finding.severity] <= RANK[BENCH_FOUND_FLOOR] and matches(defect, finding)
                and (finding.state == 'unverified' or not defect.unverified)]
        if not hits:
            continue
        found.append(defect.id)
        if any(RANK[finding.severity] <= RANK[defect.min_severity] for finding in hits):
            at_min.append(defect.id)
        if any(finding.category in defect.category for finding in hits):
            category_right.append(defect.id)
    false_high = []
    for finding in findings:
        if finding.severity in BENCH_FALSE_HIGH and not any(matches(defect, finding) for defect in fixture.defects):
            decoy = next((item.id for item in fixture.decoys if matches(item, finding)), '')
            false_high.append(FalseHigh(finding, decoy))
    missed = tuple(defect.id for defect in fixture.defects if defect.id not in found)
    return Run(tuple(found), tuple(at_min), tuple(category_right), missed, tuple(false_high))


def render(fixture, runs):
    """The output lines: the fixture, one line for each run (false Highs indented under it), then the
    median of each count."""
    total = len(fixture.defects)
    lines = [f'fixture {fixture.name}: {flags.plural(total, "planted defect")}, '
             f'{flags.plural(len(fixture.decoys), "decoy")}']
    for position, run in enumerate(runs, start=1):
        missed = f'missed {len(run.missed)}' + (f' ({", ".join(run.missed)})' if run.missed else '')
        lines.append(f'run {position}: found {len(run.found)}, found at min severity {len(run.at_min)}, '
                     f'{missed}, false High {len(run.false_high)}')
        for hit in run.false_high:
            lines.append(f'  false High: {hit.finding.path}:{hit.finding.line}'
                         + (f' (decoy {hit.decoy})' if hit.decoy else ''))

    def middle(field):
        return trends.plain(median(len(getattr(run, field)) for run in runs))

    lines.append(f'median of {flags.plural(len(runs), "run")}')
    lines.append(f'found: {middle("found")} of {total}')
    lines.append(f'found at min severity: {middle("at_min")} of {total}')
    lines.append(f'missed: {middle("missed")} of {total}')
    lines.append(f'false High: {middle("false_high")}')
    if any(defect.category for defect in fixture.defects):
        lines.append(f'category right: {middle("category_right")} of {total}')
    return lines


def parse_questions(source, raw):
    if not isinstance(raw, list) or not raw:
        raise RecordError(f'{source}: "questions" is a list with at least one entry')
    questions = []
    for number, entry in enumerate(raw):
        where = f'questions[{number}]'
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not entry['id']:
            raise RecordError(f'{source}: {where}: needs an id')
        where = f'question {entry["id"]}'
        if entry.get('kind') not in FACT_KINDS:
            raise RecordError(f'{source}: {where}: kind is one of {", ".join(FACT_KINDS)}')
        if not isinstance(entry.get('ask'), str) or not entry['ask'].strip():
            raise RecordError(f'{source}: {where}: ask is the text of the question')
        questions.append(Question(entry['id'], entry['kind'], entry['ask']))
    return tuple(questions)


def parse_fact_items(source, kind, raw, questions):
    """The expected facts or the decoys of a facts list: each has an id, the id of its question and places."""
    if not isinstance(raw, list) or (kind == 'facts' and not raw):
        raise RecordError(f'{source}: "{kind}" is a list{" with at least one entry" if kind == "facts" else ""}')
    items = []
    for number, entry in enumerate(raw):
        where = f'{kind}[{number}]'
        if not isinstance(entry, dict) or not isinstance(entry.get('id'), str) or not entry['id']:
            raise RecordError(f'{source}: {where}: needs an id')
        where = f'{kind} {entry["id"]}'
        if entry.get('question') not in [question.id for question in questions]:
            raise RecordError(f'{source}: {where}: question is the id of one of the questions')
        places = entry.get('places')
        if not isinstance(places, list) or not places:
            raise RecordError(f'{source}: {where}: places is a list with at least one place')
        items.append(Item(entry['id'], tuple(parse_place(source, where, place) for place in places)))
    return tuple(items)


def load_facts(source):
    """The Facts in the facts list `source`; a list that does not fit raises RecordError."""
    text = files.read_input(source)
    try:
        data = json.loads(text)
    except ValueError as error:
        raise RecordError(f'{source}: not JSON ({error})') from None
    if not isinstance(data, dict):
        raise RecordError(f'{source}: the facts list is a JSON object with "questions", "facts" and "decoys"')
    questions = parse_questions(source, data.get('questions'))
    facts = parse_fact_items(source, 'facts', data.get('facts'), questions)
    decoys = parse_fact_items(source, 'decoys', data.get('decoys', []), questions)
    ids = [item.id for item in questions + facts + decoys]
    for ident in sorted(set(ids)):
        if ids.count(ident) > 1:
            raise RecordError(f'{source}: the id {ident} is used twice')
    return Facts(str(data.get('fixture') or source), questions, facts, decoys)


def parse_answers(text, source):
    """The answer lines of one run's text. Prose is skipped; a line that starts like an answer (a bullet
    with a `<path>:<digits>` place and an em dash) but does not have the shape raises RecordError naming
    `source` and its line number."""
    if not text.strip():
        raise RecordError(f'{source}: no text')
    answers = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = ANSWER.match(line)
        if match:
            answers.append(Answer(match['path'], int(match['line']), match['fact']))
        elif LOOKS_LIKE_ANSWER.match(line):
            raise RecordError(f'{source}:{number}: not an answer line; the shape is {ANSWER_SHAPE}')
    return answers


def score_facts(facts, answers):
    """The FactsRun of these answers against the facts list: the expected facts an answer names a place
    of, and the decoys an answer names a place of."""
    return FactsRun(tuple(item.id for item in facts.facts if any(matches(item, answer) for answer in answers)),
                    tuple(item.id for item in facts.decoys if any(matches(item, answer) for answer in answers)))


def render_facts(facts, runs):
    """The output lines: the fixture, one line for each run, then the median of each count."""
    total = len(facts.facts)

    def counted(word, ids):
        return f'{word} {len(ids)}' + (f' ({", ".join(ids)})' if ids else '')

    lines = [f'fixture {facts.name}: {flags.plural(len(facts.questions), "question")}, '
             f'{flags.plural(total, "expected fact")}, {flags.plural(len(facts.decoys), "decoy")}']
    for position, run in enumerate(runs, start=1):
        missed = tuple(item.id for item in facts.facts if item.id not in run.found)
        lines.append(f'run {position}: {counted("found", run.found)}, {counted("missed", missed)}, '
                     f'{counted("decoy hits", run.decoy_hits)}')

    def middle(field):
        return trends.plain(median(len(getattr(run, field)) for run in runs))

    lines.append(f'median of {flags.plural(len(runs), "run")}')
    lines.append(f'found: {middle("found")} of {total}')
    lines.append(f'decoy hits: {middle("decoy_hits")}')
    return lines


def register(commands, common):
    command = commands.add_parser('bench', help='score a reviewer or reader agent against a bench fixture')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')
    score = actions.add_parser('score', parents=[common],
                               help='found, found at min severity, missed and false High of 1 to 3 runs (the median)')
    score.add_argument('defects', help="the fixture's defect list (defects.json)")
    score.add_argument('findings', nargs='+',
                       help='one file of finding lines for each run, one to three (- reads standard input)')
    score.set_defaults(handler=run_score)
    facts = actions.add_parser('facts', parents=[common],
                               help='expected facts found and decoys hit by 1 to 3 answer runs (the median)')
    facts.add_argument('facts', help="the fixture's facts list (facts.json)")
    facts.add_argument('answers', nargs='+',
                       help='one file of answer lines for each run, one to three (- reads standard input)')
    facts.set_defaults(handler=run_facts)


def run_score(args, environ):
    if len(args.findings) > BENCH_MAX_RUNS:
        raise RecordError(f'bench score takes 1 to {BENCH_MAX_RUNS} runs, got {len(args.findings)}')
    fixture = load_fixture(args.defects)
    runs = [score_run(fixture, parse_findings(files.read_input(source), source)) for source in args.findings]
    for line in render(fixture, runs):
        print(line)
    return 0


def run_facts(args, environ):
    if len(args.answers) > BENCH_MAX_RUNS:
        raise RecordError(f'bench facts takes 1 to {BENCH_MAX_RUNS} runs, got {len(args.answers)}')
    facts = load_facts(args.facts)
    results = [score_facts(facts, parse_answers(files.read_input(source), source)) for source in args.answers]
    for line in render_facts(facts, results):
        print(line)
    return 0

"""Idea records: `ideas/<slug>.md` under home, one assessed proposal from outside each.

Frontmatter: slug, source, assessed, verdict, revisit (park only), related (anomaly
signatures and targets, one `- ` line each) and scores_at_assessment (signature: the
anomaly's score when the idea was assessed, so a later rise past the nudge threshold can be
seen). The body is the writer's own short text, with at most one short quote of the source:
a block of `> ` lines or a double or curly single-quoted span of IDEA_QUOTE_MIN_WORDS words or more
(a shorter quoted span is a term, not a quote), at most IDEA_QUOTE_MAX_WORDS words long.
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter
from .constants import IDEA_QUOTE_MAX_WORDS, IDEA_QUOTE_MIN_WORDS, IDEAS_DIR, VERDICTS
from .files import write_lines
from .files import read_input
from .records import RecordError, is_date, is_slug, is_whole, single_line_problems, to_int

SCALAR_FIELDS = ('slug', 'source', 'assessed', 'verdict', 'revisit')
QUOTED_SPAN = re.compile(r'"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’')


@dataclass
class Idea:
    slug: str
    source: str = ''
    assessed: str = ''
    verdict: str = ''
    revisit: str = ''
    related: list = field(default_factory=list)
    scores_at_assessment: dict = field(default_factory=dict)
    body: str = ''


def idea_path(home, slug):
    return Path(home) / IDEAS_DIR / f'{slug}.md'


def parse_idea(text, slug=''):
    fields, body = frontmatter.split(text)
    scores = frontmatter.pairs(fields.get('scores_at_assessment', ''))
    return Idea(slug=fields.get('slug') or slug, source=fields.get('source', ''),
                assessed=fields.get('assessed', ''), verdict=fields.get('verdict', ''),
                revisit=fields.get('revisit', ''), related=frontmatter.items(fields.get('related', '')),
                scores_at_assessment={name: to_int(score, '') for name, score in scores.items()},
                body=body.strip())


def render_idea(idea):
    fields = [(key, getattr(idea, key)) for key in SCALAR_FIELDS]
    fields += [('related', idea.related), ('scores_at_assessment', idea.scores_at_assessment)]
    return frontmatter.render(fields) + ([idea.body] if idea.body else [])


def quotes(body):
    """The quoted passages of a body: each run of consecutive `> ` lines (one wrapped quote), and each
    double or curly single-quoted span long enough to be a quote."""
    found, in_block = [], False
    for line in body.splitlines():
        if line.startswith('>'):
            text = line[1:].strip()
            if in_block:
                found[-1] += ' ' + text
            else:
                found.append(text)
            in_block = True
            continue
        in_block = False
        spans = (next(group for group in match.groups() if group) for match in QUOTED_SPAN.finditer(line))
        found += [span for span in spans if len(span.split()) >= IDEA_QUOTE_MIN_WORDS]
    return found


def quote_problems(body):
    found = quotes(body)
    problems = []
    if len(found) > 1:
        problems.append(f'body holds {len(found)} quotes; at most one short quote of the source is allowed')
    if any(len(quote.split()) > IDEA_QUOTE_MAX_WORDS for quote in found):
        problems.append(f'the quote must be at most {IDEA_QUOTE_MAX_WORDS} words')
    return problems


def validate_idea(idea):
    problems = []
    if not is_slug(idea.slug):
        problems.append(f'slug {idea.slug!r} must be lowercase words joined by hyphens')
    if idea.verdict not in VERDICTS:
        problems.append(f'verdict {idea.verdict!r} must be one of {", ".join(VERDICTS)}')
    if not is_date(idea.assessed):
        problems.append(f'assessed {idea.assessed!r} must be a date like 2026-10-04')
    if idea.verdict == 'park' and not is_date(idea.revisit):
        problems.append('revisit must be a date when the verdict is park')
    if idea.verdict != 'park' and idea.revisit:
        problems.append('revisit is only set when the verdict is park')
    unknown = [name for name in idea.scores_at_assessment if name not in idea.related]
    if unknown:
        problems.append('scores_at_assessment names that are not in related: ' + ', '.join(unknown))
    if not all(is_whole(s) for s in idea.scores_at_assessment.values()):
        problems.append('scores_at_assessment values must be whole numbers')
    values = [(key, getattr(idea, key)) for key in SCALAR_FIELDS] + [('related', r) for r in idea.related]
    return problems + single_line_problems(values) + quote_problems(idea.body)


def read_idea(path):
    path = Path(path)
    return parse_idea(read_input(path), path.stem)


def load_ideas(home):
    return [read_idea(path) for path in sorted((Path(home) / IDEAS_DIR).glob('*.md'))]


def write_idea(home, idea):
    problems = validate_idea(idea)
    if problems:
        raise RecordError(f'idea {idea.slug}: ' + '; '.join(problems))
    path = idea_path(home, idea.slug)
    write_lines(path, render_idea(idea))
    return path

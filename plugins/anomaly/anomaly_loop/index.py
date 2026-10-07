"""The backlog index: home/INDEX.md generated from home/anomalies/, and its digest section.

Open and reopened anomalies are one table ranked by score, then the newest last_seen;
fixed and wontfix ones are listed under `## Closed`. An invalid record stops the index.
"""
from pathlib import Path

from . import paths, records
from .constants import ANOMALIES_DIR, DIGEST_TOP, INDEX_FILE
from .files import write_lines


def cell(value):
    return str(value).replace('|', '\\|')


def backlog_summary(anomalies, separator=' · '):
    """'N open · M closed': the one place that counts the backlog."""
    return f'{len(records.ranked(anomalies))} open{separator}{len(records.closed(anomalies))} closed'


def backlog_line(anomalies):
    """The `index: N open, M closed` line the index and observe commands print."""
    return f'index: {backlog_summary(anomalies, ", ")}'


def render_index(anomalies, today):
    active, done = records.ranked(anomalies), records.closed(anomalies)
    out = [
        '# Anomaly backlog',
        '',
        f'Generated {today.isoformat()} by `anomaly index`. Do not edit by hand.',
        f'{backlog_summary(anomalies)} · score = impact × occurrences',
        '',
        '| Score | Anomaly | Kind | Category | Target | Scope | Impact | Seen | Effort | Last seen | Status |',
        '|---|---|---|---|---|---|---|---|---|---|---|',
    ]
    for a in active:
        link = f'[{a.signature}]({ANOMALIES_DIR}/{a.signature}.md)'
        values = (a.score, link, a.kind, a.category, a.target, a.scope, a.impact, a.occurrences,
                  a.effort or '?', a.last_seen, a.status)
        out.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    if done:
        out += ['', '## Closed', '']
        out += [f'- [{a.signature}]({ANOMALIES_DIR}/{a.signature}.md) — {a.status} {a.fixed_by}'.rstrip()
                for a in done]
    return '\n'.join(out) + '\n'


def write_index(home, today, anomalies=None):
    """Write INDEX.md; reads and validates the anomalies unless they are passed in."""
    if anomalies is None:
        anomalies = records.load_anomalies(home, strict=True)
    text = render_index(anomalies, today)
    write_lines(Path(home) / INDEX_FILE, text.splitlines())
    return text


def digest_section(context):
    active = records.ranked(context.anomalies)
    lines = ['## Backlog', backlog_summary(context.anomalies)]
    return lines + [f'- {a.score}  {a.signature}' for a in active[:DIGEST_TOP]]


# ---------- the index subcommand ----------

def register(commands, common):
    command = commands.add_parser('index', parents=[common],
                                  help=f'regenerate {INDEX_FILE} in home from {ANOMALIES_DIR}/')
    command.set_defaults(handler=run_index)


def run_index(args, environ):
    home = paths.resolve_home(args.home, environ)
    anomalies = records.load_anomalies(home, strict=True)
    write_index(home, args.today, anomalies)
    print(backlog_line(anomalies))
    print(f'file: {home / INDEX_FILE}')
    return 0

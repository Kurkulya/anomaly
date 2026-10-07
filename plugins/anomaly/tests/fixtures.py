"""Shared test fixtures: synthetic transcripts and records, the default ticket-key pattern, a CLI
runner, a digest context and a temporary git repository."""
import contextlib
import io
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from anomaly_loop import cli, digest, files, gitrepo, profile, records

SID = '11111111-aaaa-bbbb-cccc-000000000001'
TICKET_KEY = profile.ticket_key_pattern(profile.Profile(values={}, exists=False))
NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)


def run_cli(*argv, environ=None, now=NOW):
    """Run the CLI in-process with an injected clock; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv), environ={} if environ is None else environ, now=now)
    return code, out.getvalue(), err.getvalue()


PLUGIN = Path(__file__).resolve().parent.parent
BENCH = PLUGIN / 'tests' / 'bench'   # the seeded-defect fixtures, one folder per reviewer agent


def plugin_files(root):
    """Every file under `root` (the plugin folder, or a copy of its shape), sorted, without caches."""
    return [f for f in sorted(root.rglob('*')) if f.is_file() and '__pycache__' not in f.parts]


def ts(minute, second=0, hour=10, day=1):
    return f'2026-10-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}.000Z'


def assistant(when, msg_id, model='claude-opus-4', inp=100, out=10, cache_read=1000,
              cache_write=50, tools=(), branch='main', cwd='/w', **extra):
    content = [{'type': 'tool_use', 'id': i, 'name': n, 'input': inp_} for i, n, inp_ in tools]
    content = content or [{'type': 'text', 'text': 'reply'}]
    entry = {
        'type': 'assistant', 'timestamp': when, 'cwd': cwd, 'gitBranch': branch,
        'requestId': 'req-' + msg_id, 'uuid': 'u-' + msg_id + when,
        'message': {
            'id': msg_id, 'model': model, 'content': content,
            'usage': {'input_tokens': inp, 'output_tokens': out,
                      'cache_read_input_tokens': cache_read,
                      'cache_creation_input_tokens': cache_write},
        },
    }
    entry.update(extra)
    return entry


def user(when, text, **extra):
    entry = {'type': 'user', 'timestamp': when, 'cwd': '/w', 'gitBranch': 'main',
             'message': {'role': 'user', 'content': text}}
    entry.update(extra)
    return entry


def result(when, tool_use_id, text, is_error=False, **extra):
    block = {'type': 'tool_result', 'tool_use_id': tool_use_id, 'content': text}
    if is_error:
        block['is_error'] = True
    return user(when, [block], **extra)


def write_jsonl(path, entries, raw_lines=()):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        for e in entries:
            f.write(json.dumps(e) + '\n')
        for line in raw_lines:
            f.write(line + '\n')


def anomaly_text(signature, impact, occurrences, status='open', last_seen='2026-10-01', kind='problem',
                 category='tool-economy   # comment', sightings=('2026-10-01 · demo · s1 · seen once',)):
    """A new-format anomaly file; the category carries a trailing comment like a hand edit would."""
    lines = ['---', f'signature: {signature}', f'kind: {kind}', f'category: {category}', 'target:',
             'scope: global', f'impact: {impact}', f'occurrences: {occurrences}', 'effort:',
             f'status: {status}', 'first_seen: 2026-09-01', f'last_seen: {last_seen}', 'fixed_by:', '---',
             'What went wrong.', '', '## Proposed fix', 'Change the thing.', '', '## Sightings']
    return '\n'.join(lines + [f'- {s}' for s in sightings]) + '\n'


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def write_build_skills_profile(home, skills='implement, run-tickets'):
    """A profile that names the build skills (the plugin ships none), for tests that count build sessions."""
    write_text(Path(home) / 'profile.md', f'---\nbuild_skills: {skills}\n---\n')


def write_anomaly_text(home, signature, *args, **kwargs):
    """Write anomaly_text(signature, ...) as home's anomaly file, the way a hand edit would; returns the path."""
    path = Path(home) / 'anomalies' / f'{signature}.md'
    write_text(path, anomaly_text(signature, *args, **kwargs))
    return path


def context(home, **overrides):
    """A digest Context over `home` with the fixture clock; the user config, plugin and data folders
    default to `user-config`, `plugin` and `data` beside home (the data folder is created)."""
    home = Path(home)
    data = home.parent / 'data'
    data.mkdir(parents=True, exist_ok=True)
    values = dict(home=home, today=NOW.date(), now=NOW, user_config=home.parent / 'user-config',
                  plugin_root=home.parent / 'plugin', data=data)
    values.update(overrides)
    return digest.Context(**values)


class GitFixture:
    """A temporary git repository with a local identity and explicit commit dates, so history
    tests never read the clock or depend on the user's git configuration."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.git('init', '-q')
        for key, value in (('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid'),
                           ('commit.gpgsign', 'false')):
            self.git('config', key, value)

    def git(self, *args, when=None):
        env = {key: value for key, value in os.environ.items() if key not in gitrepo.REDIRECTING_ENV}
        if when is not None:
            env['GIT_AUTHOR_DATE'] = env['GIT_COMMITTER_DATE'] = f'{when.isoformat()}T12:00:00+00:00'
        done = subprocess.run(['git', *args], cwd=self.root, env=env, capture_output=True,
                              text=True, encoding='utf-8', check=True)
        return done.stdout

    def write(self, relative, text):
        write_text(self.root / relative, text)

    def commit(self, relative_paths, message, when):
        """Stage and commit only these paths, dated `when` (a date); returns the commit id."""
        self.git('add', '--', *relative_paths)
        self.git('commit', '-q', '-m', message, '--only', '--', *relative_paths, when=when)
        return self.git('rev-parse', 'HEAD').strip()

    def status(self):
        return self.git('status', '--porcelain', '--untracked-files=all').splitlines()


def observed(signature='slow-check', **changes):
    """One sighting as the observe skill hands it over (a new problem unless the changes say otherwise)."""
    values = dict(signature=signature, kind='problem', category='automated-checks', target='scripts/check.sh',
                  scope='repo:demo', impact=2, summary='The check runs every test twice.',
                  fix='Run the fast suite first.', text='the check took long again', repo='demo', session=SID)
    values.update(changes)
    return values


def write_batch(path, **batch):
    """An observe batch file (sightings, lenses, kind) as JSON; returns the path."""
    write_text(Path(path), json.dumps(batch))
    return Path(path)


def metrics_row(session_id, day, weighted=1000.0, active_min=10.0, interrupts=0, denials=0, skills=(),
                slash=(), cwd='/w', by_skill=None, hour=10, **fields):
    """A metrics row with the fields the digest trends read, named as metrics.build_row names them.
    `day` is a date or ISO text; `by_skill` maps a skill name to its weighted tokens; any other
    field given (bash_shapes, first_ts ...) is set as it is."""
    row = {'session_id': session_id, 'cwd_first': cwd, 'first_ts': f'{day}T{hour:02d}:00:00.000Z',
           'last_ts': f'{day}T{hour:02d}:30:00.000Z', 'weighted': weighted, 'active_min': active_min,
           'friction': {'interrupts': interrupts, 'denials': {'total': denials}},
           'skills_invoked': {name: 1 for name in skills}, 'slash_commands': {name: 1 for name in slash},
           'tokens_by_skill': {name: {'weighted': value} for name, value in (by_skill or {}).items()}}
    row.update(fields)
    return row


def write_experiment_anomaly(home, signature, target='demo-skill', metric='active minutes', check_by='',
                             result='', proposed_fix='Change the thing.\nSecond line.', kind='', guard='rework',
                             declared_on='', skill='', **anomaly_fields):
    """An anomaly file with an experiment block, written through the records owner; any other
    Anomaly field (status, fixed_by, last_seen ...) can be set by keyword. The fix counts as made
    (fixed_by is set), because an experiment without a fix is never due. `kind` is the experiment's
    session kind; `declared_on` the day it was declared; `skill` the new skill of a switch-over."""
    from anomaly_loop import records
    experiment = records.Experiment(expect='faster', metric=metric, guard=guard, kind=kind, skill=skill,
                                    declared_on=declared_on, check_by=check_by, result=result)
    fields = dict(signature=signature, kind='problem', category='tool-economy', target=target, scope='global',
                  proposed_fix=proposed_fix, first_seen='2026-09-01', last_seen='2026-10-01',
                  fixed_by='2026-09-10', experiment=experiment)
    fields.update(anomaly_fields)
    return records.write_anomaly(home, records.Anomaly(**fields))


def write_idea_file(home, slug='an-idea', **changes):
    """Write a valid parked idea file under home (changes override the fields); returns its path."""
    from anomaly_loop import ideas
    values = dict(slug=slug, source='https://example.com/post', assessed='2026-09-01', verdict='park',
                  revisit='2026-12-01', related=[], scores_at_assessment={}, body='In my own words.')
    values.update(changes)
    return ideas.write_idea(home, ideas.Idea(**values))


def write_anomaly_with(home, signature, **fields):
    """Write a valid anomaly under home (default: an open problem, impact 1, seen once) with these
    fields changed, for example kind='win', target='deploy', occurrences=3; returns the Anomaly."""
    values = dict(signature=signature, kind='problem', category='tool-economy', impact=1, occurrences=1,
                  status='open', first_seen='2026-09-01', last_seen='2026-10-01', summary='What went wrong.',
                  proposed_fix='Change the thing.', sightings=['2026-10-01 · demo · s1 · seen once'])
    values.update(fields)
    anomaly = records.Anomaly(**values)
    records.write_anomaly(home, anomaly)
    return anomaly


def write_metrics_rows(home, rows):
    files.write_lines(Path(home) / 'metrics.jsonl', [files.dump(row) for row in rows])


def assert_cli_error(test, result, *fragments):
    """The CLI error contract on a run_cli result: exit 2, one `anomaly: ` line on stderr that holds
    every fragment, and no traceback."""
    code, out, err = result
    test.assertEqual(code, 2, (out, err))
    test.assertEqual(len(err.strip().splitlines()), 1, err)
    test.assertTrue(err.startswith('anomaly: '), err)
    for fragment in fragments:
        test.assertIn(fragment, err)
    test.assertNotIn('Traceback', out + err)

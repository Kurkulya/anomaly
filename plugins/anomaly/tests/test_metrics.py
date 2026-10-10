import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from anomaly_loop import metrics
from tests.fixtures import SID, TICKET_KEY, assistant, result, run_cli, ts, user, write_jsonl

# Secret-looking keywords are assembled at runtime so no fixture looks like a real credential.
PW = 'pass' + 'word'
TK = 'TO' + 'KEN'
BR = 'Bear' + 'er'
FAKE_KEY = 'gh' + 'p_' + 'A1b2C3d4E5f6G7h8I9j0K1l2'


def without(entry, field):
    """A copy of an assistant entry with `field` ('model' or 'usage') missing from its message."""
    entry = json.loads(json.dumps(entry))
    del entry['message'][field]
    return entry


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.projects = self.root / 'projects'
        self.proj = self.projects / 'C--Work-demo'
        self.out = self.root / 'home' / 'metrics.jsonl'
        self.state = self.root / 'state' / 'scan.json'
        self.cache = self.root / 'data' / 'cache' / 'prompts.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def main_path(self, sid=SID):
        return self.proj / f'{sid}.jsonl'

    def session(self, entries, sid=SID, raw_lines=()):
        write_jsonl(self.main_path(sid), entries, raw_lines)

    def subagent(self, name, entries, meta=None, sid=SID):
        base = self.proj / sid / 'subagents'
        write_jsonl(base / f'{name}.jsonl', entries)
        if meta is not None:
            (base / f'{name}.meta.json').write_text(json.dumps(meta), encoding='utf-8')

    def summarize(self, sid=SID):
        subs = sorted((self.proj / sid / 'subagents').glob('agent-*.jsonl'))
        return metrics.summarize_session(sid, self.proj.name, self.main_path(sid), subs, TICKET_KEY)

    def scan(self, **kwargs):
        defaults = dict(projects=self.projects, out_path=self.out, state_path=self.state,
                        cache_path=self.cache, now=datetime(2026, 10, 4, tzinfo=timezone.utc),
                        ticket_key=TICKET_KEY)
        defaults.update(kwargs)
        return metrics.scan(**defaults)

    def read_rows(self):
        return [json.loads(l) for l in self.out.read_text(encoding='utf-8').splitlines()]

    def read_cache(self):
        if not self.cache.exists():
            return []
        return [json.loads(l) for l in self.cache.read_text(encoding='utf-8').splitlines()]


class TokensTest(Base):
    def test_dedupes_by_message_id_and_takes_max_output(self):
        self.session([
            assistant(ts(0), 'm1', out=5),
            assistant(ts(0, 1), 'm1', out=20),
            assistant(ts(0, 2), 'm1', out=12),
            assistant(ts(1), 'm2', out=7, inp=10, cache_read=0, cache_write=0),
            assistant(ts(2), 'm3', model='<synthetic>', out=999),
        ])
        row, _ = self.summarize()
        bucket = row['tokens']['main']['claude-opus-4']
        self.assertEqual(bucket, {'input': 110, 'cache_write': 50, 'cache_read': 1000, 'output': 27})
        self.assertNotIn('<synthetic>', row['tokens']['main'])
        self.assertEqual(row['skipped_entries'], 0)   # a <synthetic> entry is not counted as skipped
        expected = 110 * 1 + 50 * 1.25 + 1000 * 0.1 + 27 * 5
        self.assertAlmostEqual(row['weighted'], expected)

    def test_same_message_id_in_different_files_is_not_merged(self):
        self.session([assistant(ts(0), 'm1', out=5)])
        self.subagent('agent-a1', [assistant(ts(1), 'm1', out=8)], {'agentType': 'x', 'model': 'sonnet'})
        row, _ = self.summarize()
        self.assertEqual(row['tokens']['main']['claude-opus-4']['output'], 5)
        self.assertEqual(row['tokens']['subagent']['claude-opus-4']['output'], 8)

    def test_unparseable_lines_are_skipped(self):
        self.session([assistant(ts(0), 'm1', out=5)], raw_lines=['{not json', '', '[1,2]'])
        row, _ = self.summarize()
        self.assertEqual(row['tokens']['main']['claude-opus-4']['output'], 5)

    def test_tokens_by_skill_and_agent(self):
        self.session([
            assistant(ts(0), 'm1', out=10, attributionSkill='interview', attributionAgent='Explore'),
            assistant(ts(1), 'm2', out=10, attributionSkill='interview'),
            assistant(ts(2), 'm3', out=10),
        ])
        row, _ = self.summarize()
        skill = row['tokens_by_skill']['interview']
        self.assertEqual(skill['output'], 20)
        self.assertEqual(skill['input'], 200)
        self.assertAlmostEqual(skill['weighted'], 200 + 100 * 1.25 + 2000 * 0.1 + 20 * 5)
        self.assertEqual(list(row['tokens_by_agent']), ['Explore'])

    def test_an_assistant_entry_without_model_or_usage_is_counted_as_skipped_in_any_file(self):
        self.session([
            assistant(ts(0), 'm1', out=5),
            without(assistant(ts(1), 'm2', out=999), 'model'),
            without(assistant(ts(2), 'm3', out=999), 'usage'),
            assistant(ts(3), 'm4', model='<synthetic>', out=999),
        ])
        self.subagent('agent-a1', [without(assistant(ts(4), 's1', out=999), 'usage')],
                      {'agentType': 'Explore', 'model': 'sonnet'})
        row, _ = self.summarize()
        self.assertEqual((row['skipped_entries'], row['skipped_spawns']), (3, 0))
        self.assertEqual(row['tokens']['main']['claude-opus-4']['output'], 5)


class ModelWeightedTest(Base):
    """`model_weighted_by_agent`: per agent (the key of `tokens_by_agent`), the weighted tokens of each
    API call times the factor of the call's model; `unknown_model_by_agent`: per agent, the calls on a
    model with no factor. A call with the default fixture tokens weighs CALL."""
    CALL = 100 * 1 + 50 * 1.25 + 1000 * 0.1 + 10 * 5

    def call(self, agent, model, msg_id, minute=0, **tokens):
        return assistant(ts(minute), msg_id, model=model, attributionAgent=agent, **tokens)

    def test_a_call_counts_with_the_factor_of_its_models_family(self):
        self.session([self.call('a-haiku', 'claude-haiku-4-5', 'h1'),
                      self.call('a-sonnet', 'claude-sonnet-5', 's1', 1),
                      self.call('a-opus', 'claude-opus-4', 'o1', 2),
                      self.call('a-fable', 'claude-fable-5', 'f1', 3),
                      self.call('a-bedrock', 'us.anthropic.claude-sonnet-4-5-v1:0', 'b1', 4)])
        row, _ = self.summarize()
        found = row['model_weighted_by_agent']
        self.assertEqual(sorted(found), sorted(row['tokens_by_agent']))
        for agent, factor in (('a-haiku', 0.05), ('a-sonnet', 1), ('a-opus', 2), ('a-fable', 5), ('a-bedrock', 1)):
            self.assertAlmostEqual(found[agent], self.CALL * factor, msg=agent)
        self.assertEqual(row['unknown_model_by_agent'], {})

    def test_a_haiku_call_with_a_prompt_over_100k_tokens_counts_at_the_higher_factor(self):
        at_line = dict(inp=50000, cache_write=25000, cache_read=25000, out=0)   # prompt of exactly 100000
        weighted = 50000 + 25000 * 1.25 + 25000 * 0.1
        self.session([self.call('a-at', 'claude-haiku-4-5', 'h1', **at_line),
                      self.call('a-over', 'claude-haiku-4-5', 'h2', 1, **{**at_line, 'cache_read': 25001}),
                      self.call('a-sonnet', 'claude-sonnet-5', 's1', 2, **{**at_line, 'cache_read': 25001})])
        row, _ = self.summarize()
        found = row['model_weighted_by_agent']
        self.assertAlmostEqual(found['a-at'], weighted * 0.05, delta=0.1)
        self.assertAlmostEqual(found['a-over'], (weighted + 0.1) * 0.25, delta=0.1)
        self.assertAlmostEqual(found['a-sonnet'], weighted + 0.1, delta=0.1)   # only haiku has a tier

    def test_an_agents_value_is_the_sum_over_its_calls_each_with_its_own_factor(self):
        self.session([self.call('anomaly:facts', 'claude-sonnet-5', 's1', out=10),
                      self.call('anomaly:facts', 'claude-opus-4', 'o1', 1, out=20),
                      self.call('anomaly:facts', 'claude-haiku-4-5', 'h1', 2, out=30),
                      self.call('Explore', 'claude-opus-4', 'o2', 3, out=10)])
        self.subagent('agent-a1', [self.call('anomaly:facts', 'claude-opus-4', 'o3', 4, out=0)],
                      {'agentType': 'anomaly:facts', 'model': 'opus'})
        row, _ = self.summarize()

        def weigh(out):
            return 100 + 50 * 1.25 + 1000 * 0.1 + out * 5
        found = row['model_weighted_by_agent']
        self.assertAlmostEqual(found['anomaly:facts'],
                               weigh(10) * 1 + weigh(20) * 2 + weigh(30) * 0.05 + weigh(0) * 2)
        self.assertAlmostEqual(found['Explore'], weigh(10) * 2)

    def test_a_call_on_a_model_with_no_factor_is_counted_for_its_agent_once_per_call(self):
        self.session([self.call('anomaly:facts', 'claude-mystery-1', 'x1', out=5),
                      self.call('anomaly:facts', 'claude-mystery-1', 'x1', 1, out=20),   # same API call, another entry
                      self.call('anomaly:facts', 'claude-mystery-1', 'x2', 2),
                      self.call('anomaly:facts', 'claude-sonnet-5', 's1', 3),
                      self.call('Explore', 'claude-sonnet-5', 's2', 4),
                      self.call('anomaly:facts', '<synthetic>', 'y1', 5)])
        row, _ = self.summarize()
        self.assertEqual(row['unknown_model_by_agent'], {'anomaly:facts': 2})


class MeasureLineTest(Base):
    """The summary line of `measure` about what it could not read: it starts with `not measured:` and
    holds the count of assistant entries without model or usage, then the count of spawns without
    .meta.json, as the only numbers in it."""

    def measure(self):
        _, out, _ = run_cli('measure', '--home', str(self.root / 'home'), '--data', str(self.root / 'data'),
                            '--projects', str(self.projects))
        return [line for line in out.splitlines() if line.startswith('not measured:')]

    def the_line(self):
        lines = self.measure()
        self.assertEqual(len(lines), 1, 'expected one `not measured:` line')
        return lines[0]

    def test_one_line_holds_both_counts(self):
        self.session([assistant(ts(0), 'm1'), without(assistant(ts(1), 'm2'), 'usage'),
                      without(assistant(ts(2), 'm3'), 'usage'), without(assistant(ts(3), 'm4'), 'model')])
        self.subagent('agent-a1', [assistant(ts(4), 's1')])
        self.subagent('agent-a2', [assistant(ts(5), 's2')])
        self.subagent('agent-a3', [assistant(ts(6), 's3')], {'agentType': 'Explore', 'model': 'sonnet'})
        self.assertEqual(re.findall(r'\d+', self.the_line()), ['3', '2'])

    def test_the_line_shows_a_zero_for_the_count_that_is_not_above_0(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1')])
        self.assertEqual(re.findall(r'\d+', self.the_line()), ['0', '1'])

    def test_no_line_when_both_counts_are_0(self):
        self.session([assistant(ts(0), 'm1'), assistant(ts(1), 'm2', model='<synthetic>')])
        self.subagent('agent-a1', [assistant(ts(2), 's1')], {'agentType': 'Explore', 'model': 'sonnet'})
        self.assertEqual(self.measure(), [])


class SummarizeRowsTest(unittest.TestCase):
    def test_a_row_without_the_skipped_fields_adds_0_to_the_sums(self):
        older = {}   # a row written before the fields existed lacks them
        found = metrics.summarize_rows([older, {'skipped_entries': 2, 'skipped_spawns': 1}])
        self.assertEqual((found['skipped_entries'], found['skipped_spawns']), (2, 1))


class SubagentTest(Base):
    def test_subagents_roll_into_parent_with_meta_counts(self):
        self.session([assistant(ts(0), 'm1', out=10)])
        self.subagent('agent-a1', [assistant(ts(1), 's1', model='claude-sonnet-5', out=30),
                                   assistant(ts(2, 30), 's1b', model='claude-sonnet-5', out=0)],
                      {'agentType': 'Explore', 'model': 'sonnet', 'stoppedByUser': False, 'spawnDepth': 1})
        self.subagent('agent-a2', [assistant(ts(3), 's2', model='claude-sonnet-5', out=40),
                                   assistant(ts(3, 10), 's2b', model='claude-sonnet-5', out=0)],
                      {'agentType': 'Explore', 'model': 'sonnet', 'stoppedByUser': True, 'spawnDepth': 1})
        self.subagent('agent-a3', [assistant('2026-10-01T10:05:00.000Z', 's3', out=1),
                                   assistant('2026-10-01T10:05:30.600Z', 's3b', out=0)],
                      {'agentType': 'general-purpose', 'model': 'opus', 'stoppedByUser': False})
        row, _ = self.summarize()
        self.assertEqual(row['tokens']['subagent']['claude-sonnet-5']['output'], 70)
        self.assertEqual(row['tokens']['main']['claude-opus-4']['output'], 10)
        self.assertEqual(row['subagents'], {
            'count': 3,
            'by_type': {'Explore': 2, 'general-purpose': 1},
            'by_model': {'sonnet': 2, 'opus': 1},
            'stopped_by_user': 1,
            # a1 ran 90 s and a2 10 s; a3 ran 30.6 s, rounded to a whole second
            'seconds_by_type': {'Explore': 100, 'general-purpose': 31},
            'seconds_by_model': {'sonnet': 100, 'opus': 31},
        })
        self.assertEqual(row['skipped_spawns'], 0)   # every spawn here has a .meta.json

    def test_subagent_files_are_not_listed_as_sessions(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1')], {'agentType': 'x', 'model': 'haiku'})
        listed = list(metrics.list_sessions(self.projects))
        self.assertEqual(len(listed), 1)
        project, main, subs = listed[0]
        self.assertEqual((project, main.name, len(subs)), ('C--Work-demo', f'{SID}.jsonl', 1))

    def test_subagent_without_meta_counts_as_unknown(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1')])
        row, _ = self.summarize()
        self.assertEqual(row['subagents']['by_type'], {'unknown': 1})
        self.assertEqual(row['skipped_spawns'], 1)

    def test_a_spawn_without_meta_adds_its_seconds_to_unknown(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1'), assistant(ts(1, 20), 's2')])
        row, _ = self.summarize()
        self.assertEqual(row['subagents'].get('seconds_by_type'), {'unknown': 20})
        self.assertEqual(row['subagents'].get('seconds_by_model'), {'unknown': 20})

    def test_a_spawn_with_fewer_than_two_parseable_timestamps_adds_zero_seconds_but_is_counted(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1')], {'agentType': 'Plan', 'model': 'haiku'})
        self.subagent('agent-a2', [assistant('not-a-time', 's2'), assistant(ts(2), 's3')],
                      {'agentType': 'Plan', 'model': 'haiku'})
        self.subagent('agent-a3', [{**assistant(ts(3), 's4'), 'timestamp': None}, assistant(ts(3), 's5'),
                                   assistant(ts(3, 45), 's6')],
                      {'agentType': 'Explore', 'model': 'sonnet'})
        row, _ = self.summarize()
        subagents = row['subagents']
        self.assertEqual((subagents['count'], subagents['by_type'], subagents['by_model']),
                         (3, {'Plan': 2, 'Explore': 1}, {'haiku': 2, 'sonnet': 1}))
        self.assertEqual(subagents.get('seconds_by_type'), {'Plan': 0, 'Explore': 45})
        self.assertEqual(subagents.get('seconds_by_model'), {'haiku': 0, 'sonnet': 45})

    def test_a_spawn_file_that_cannot_be_read_adds_zero_seconds_but_is_counted(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1'), assistant(ts(1, 20), 's2')],
                      {'agentType': 'Explore', 'model': 'sonnet'})
        base = self.proj / SID / 'subagents'
        (base / 'agent-a2.jsonl').mkdir()  # opening a folder raises OSError on every platform
        (base / 'agent-a2.meta.json').write_text(json.dumps({'agentType': 'Plan', 'model': 'haiku'}),
                                                 encoding='utf-8')
        row, _ = self.summarize()
        subagents = row['subagents']
        self.assertEqual((subagents['count'], subagents['by_type']), (2, {'Explore': 1, 'Plan': 1}))
        self.assertEqual(subagents.get('seconds_by_type'), {'Explore': 20, 'Plan': 0})
        self.assertEqual(subagents.get('seconds_by_model'), {'sonnet': 20, 'haiku': 0})

    def test_subagent_tool_use_counts_but_not_human_prompts(self):
        self.session([user(ts(0), 'hello'), assistant(ts(0, 5), 'm1', tools=[('t1', 'Read', {})])])
        self.subagent('agent-a1', [user(ts(1), 'task prompt'),
                                   assistant(ts(2), 's1', tools=[('t2', 'Read', {}), ('t3', 'Grep', {})])],
                      {'agentType': 'Explore', 'model': 'sonnet'})
        row, _ = self.summarize()
        self.assertEqual(row['tools'], {'Read': 2, 'Grep': 1})
        self.assertEqual(row['human_prompts'], 1)


class TimeTest(Base):
    def test_active_minutes_ignore_gaps_over_five_minutes(self):
        self.session([
            user(ts(0), 'a'), assistant(ts(1), 'm1'), assistant(ts(2), 'm2'),
            assistant(ts(30), 'm3'), assistant(ts(31), 'm4'), assistant(ts(36), 'm5'),
        ])
        row, _ = self.summarize()
        self.assertEqual(row['first_ts'], ts(0))
        self.assertEqual(row['last_ts'], ts(36))
        self.assertEqual(row['wall_min'], 36.0)
        # 2 (first block) + 1 + 5 (second block); the 28 min gap is ignored
        self.assertEqual(row['active_min'], 8.0)

    def test_subagent_timestamps_extend_the_timeline(self):
        self.session([assistant(ts(0), 'm1'), assistant(ts(20), 'm2')])
        self.subagent('agent-a1', [assistant(ts(4), 's1'), assistant(ts(8), 's2'), assistant(ts(12), 's3'),
                                   assistant(ts(16), 's4')], {'agentType': 'x', 'model': 'haiku'})
        row, _ = self.summarize()
        self.assertEqual(row['wall_min'], 20.0)
        self.assertEqual(row['active_min'], 20.0)


class ContextTest(Base):
    def test_branches_cwd_and_ticket_keys(self):
        self.session([
            assistant(ts(0), 'm1', branch='feat/ABC-12/mfa', cwd='/a'),
            assistant(ts(1), 'm2', branch='main', cwd='/a'),
            assistant(ts(2), 'm3', branch='feat/ABC-12/mfa', cwd='/b'),
            assistant(ts(3), 'm4', branch='fix/XYZ-3/y-and-ABC-9', cwd='/b'),
            assistant(ts(4), 'm5', branch='', cwd='/b'),
        ])
        row, _ = self.summarize()
        self.assertEqual(row['branches'], ['feat/ABC-12/mfa', 'main', 'fix/XYZ-3/y-and-ABC-9'])
        self.assertEqual(row['ticket_keys'], ['ABC-12', 'XYZ-3', 'ABC-9'])
        self.assertEqual((row['cwd_first'], row['cwd_count']), ('/a', 2))
        self.assertEqual(row['project_dir'], 'C--Work-demo')
        self.assertEqual(row['session_id'], SID)

    def test_ticket_key_pattern_from_profile_replaces_the_default(self):
        self.session([assistant(ts(0), 'm1', branch='feat/PRJ42/x-ABC-12'),
                      assistant(ts(1), 'm2', branch='fix/PRJ7')])
        row, _ = metrics.summarize_session(SID, self.proj.name, self.main_path(), [],
                                           ticket_key=re.compile(r'PRJ\d+'))
        self.assertEqual(row['ticket_keys'], ['PRJ42', 'PRJ7'])

    def test_ticket_key_pattern_with_a_group_still_returns_whole_matches(self):
        self.session([assistant(ts(0), 'm1', branch='feat/PRJ42/x')])
        row, _ = metrics.summarize_session(SID, self.proj.name, self.main_path(), [],
                                           ticket_key=re.compile(r'(PRJ)(\d+)'))
        self.assertEqual(row['ticket_keys'], ['PRJ42'])

    def test_empty_matches_are_not_ticket_keys(self):
        self.session([assistant(ts(0), 'm1', branch='feat/PRJ42/x'), assistant(ts(1), 'm2', branch='main')])
        row, _ = metrics.summarize_session(SID, self.proj.name, self.main_path(), [],
                                           ticket_key=re.compile(r'PRJ\d+|[A-Z]*'))
        self.assertEqual(row['ticket_keys'], ['PRJ42'])

    def test_scan_applies_the_ticket_key_pattern(self):
        self.session([assistant(ts(0), 'm1', branch='feat/PRJ42/x')])
        self.scan(ticket_key=re.compile(r'PRJ\d+'))
        self.assertEqual(self.read_rows()[0]['ticket_keys'], ['PRJ42'])

    def test_branches_capped_at_twenty(self):
        self.session([assistant(ts(i), f'm{i}', branch=f'b{i}') for i in range(30)])
        row, _ = self.summarize()
        self.assertEqual(len(row['branches']), 20)
        self.assertEqual(row['branches'][0], 'b0')

    def test_last_title_and_agent_name_win(self):
        self.session([
            {'type': 'custom-title', 'customTitle': 'first', 'sessionId': SID},
            assistant(ts(0), 'm1'),
            {'type': 'custom-title', 'customTitle': 'second', 'sessionId': SID},
            {'type': 'agent-name', 'agentName': 'alpha', 'sessionId': SID},
            {'type': 'agent-name', 'agentName': 'beta', 'sessionId': SID},
        ])
        row, _ = self.summarize()
        self.assertEqual((row['title'], row['agent_name']), ('second', 'beta'))


class ToolsTest(Base):
    def test_tool_skill_and_question_counts(self):
        self.session([
            assistant(ts(0), 'm1', tools=[('t1', 'Bash', {'command': 'git status'}),
                                          ('t2', 'Skill', {'skill': 'interview'})]),
            assistant(ts(1), 'm2', tools=[('t3', 'Skill', {'skill': 'interview'}),
                                          ('t4', 'Skill', {'skill': 'build'}),
                                          ('t5', 'AskUserQuestion', {'questions': []})]),
            assistant(ts(2), 'm3', tools=[('t6', 'Bash', {'command': 'git status'})]),
        ])
        row, _ = self.summarize()
        self.assertEqual(row['tools'], {'Bash': 2, 'Skill': 3, 'AskUserQuestion': 1})
        self.assertEqual(row['skills_invoked'], {'interview': 2, 'build': 1})
        self.assertEqual(row['ask_user_questions'], 1)

    def test_bash_shapes_ranked_and_capped(self):
        cmds = ['git status'] * 3 + ['git log -n 5'] * 2 + [f'tool{i} run' for i in range(20)]
        entries = [assistant(ts(i), f'm{i}', tools=[(f't{i}', 'Bash', {'command': c})])
                   for i, c in enumerate(cmds)]
        self.session(entries)
        row, _ = self.summarize()
        shapes = row['bash_shapes']
        self.assertEqual(len(shapes), 15)
        self.assertEqual(list(shapes.items())[:2], [('git status', 3), ('git log -n', 2)])


class ShapeTest(unittest.TestCase):
    def shape(self, cmd):
        return metrics.normalize_shape(cmd)

    def test_keeps_first_three_words(self):
        self.assertEqual(self.shape('git commit -m message extra words'), 'git commit -m')

    def test_replaces_quoted_strings_and_paths(self):
        self.assertEqual(self.shape('grep "needle in haystack" src/deep/file.ts'), 'grep <str> src/<path>')
        self.assertEqual(self.shape('cat /c/data/me/x.txt'), 'cat /c/<path>')
        self.assertEqual(self.shape('ls C:\\Work\\repo\\src'), 'ls C:/<path>')

    def test_drops_numbers_hashes_and_uuids(self):
        self.assertEqual(self.shape('git show 3f2a9c1d7b'), 'git show <id>')
        self.assertEqual(self.shape('git log -n 50'), 'git log -n')
        self.assertEqual(self.shape('kill 12345 678'), 'kill <id> <id>')
        self.assertEqual(self.shape('curl 123e4567-e89b-12d3-a456-426614174000'), 'curl <id>')
        self.assertEqual(self.shape('python3 script.py'), 'python3 script.py')

    def test_flag_values_and_env_assignments_are_not_kept(self):
        self.assertEqual(self.shape('curl --header=abc123 x'), 'curl --header=<str> x')
        self.assertEqual(self.shape(f'{TK}=abcdef123456 npm test'), f'{TK}=<str> npm test')

    def test_long_secret_like_words_are_not_kept(self):
        shape = self.shape(f'curl -u {FAKE_KEY} url')
        self.assertNotIn(FAKE_KEY, shape)
        self.assertNotIn('A1b2C3d4', shape)
        self.assertIn('<id>', shape)

    def test_skips_cd_prefix_and_cuts_at_control_operators(self):
        self.assertEqual(self.shape('cd /c/Work/app && npm run test | tail -5'), 'npm run test')
        self.assertEqual(self.shape('git status; git diff'), 'git status')
        self.assertEqual(self.shape('cd /c/Work/app'), 'cd /c/<path>')

    def test_a_command_substitution_as_a_variable_value_is_dropped(self):
        self.assertEqual(self.shape('B=$(git rev-parse --abbrev-ref HEAD)'), 'B=<str>')
        self.assertEqual(self.shape('B=$(git branch | grep x) && echo $B'), 'B=<str>')
        self.assertEqual(self.shape('N=$(wc -l < $(ls f)) ; echo $N'), 'N=<str>')
        self.assertEqual(self.shape('B=$(git log --format=%H \\'), 'B=<str>')
        self.assertEqual(self.shape('V=$(cat v) npm test'), 'V=<str> npm test')
        self.assertEqual(self.shape('TK=x npm test'), 'TK=<str> npm test')

    def test_multiline_uses_first_line_only(self):
        self.assertEqual(self.shape('git commit -F - <<EOF\nbody line\nEOF'), 'git commit -F')

    def test_unterminated_quote_is_dropped(self):
        self.assertEqual(self.shape('echo "never closed text'), 'echo <str>')

    def test_empty_and_non_string(self):
        self.assertEqual(self.shape(''), '')
        self.assertEqual(self.shape(None), '')


class FrictionTest(Base):
    def test_friction_counts(self):
        self.session([
            assistant(ts(0), 'm1', tools=[('t1', 'Bash', {'command': 'rm x'}), ('t2', 'Edit', {})]),
            result(ts(1), 't1', 'denied', is_error=True, toolDenialKind='permission-rule'),
            result(ts(1, 1), 't2', 'no', is_error=True, toolDenialKind='user-rejected'),
            user(ts(2), [{'type': 'text', 'text': '[Request interrupted by user for tool use]'}]),
            user(ts(3), [{'type': 'text', 'text': '[Request interrupted by user]'}]),
            user(ts(3, 5), '[Request interrupted by user]'),
            assistant(ts(4), 'm2', tools=[('t3', 'Bash', {'command': 'git push'}),
                                          ('t4', 'Bash', {'command': 'x'}),
                                          ('t5', 'Bash', {'command': 'y'}),
                                          ('t6', 'Read', {})]),
            result(ts(5), 't3', 'PreToolUse:Bash hook error: nope', is_error=True),
            result(ts(5, 1), 't4', 'Blocked: use another tool', is_error=True),
            result(ts(5, 2), 't5', 'Denied by Enterprise policy setting', is_error=True),
            result(ts(5, 3), 't6', 'PreToolUse: appears in a normal result', is_error=False),
            {'type': 'system', 'subtype': 'compact_boundary', 'timestamp': ts(6)},
            {'type': 'system', 'subtype': 'compact_boundary', 'timestamp': ts(7)},
            {'type': 'system', 'subtype': 'other', 'timestamp': ts(8)},
            result(ts(9), 'unknown-id', 'x', is_error=True, toolDenialKind='permission-rule'),
        ])
        row, _ = self.summarize()
        f = row['friction']
        self.assertEqual(f['interrupts'], 3)
        self.assertEqual(f['hook_blocks'], 1)
        self.assertEqual(f['policy_blocks'], 2)
        self.assertEqual(f['compactions'], 2)
        self.assertEqual(f['denials']['total'], 3)
        self.assertEqual(f['denials']['by_kind'], {'permission-rule': 2, 'user-rejected': 1})
        self.assertEqual(f['denials']['by_tool'], {'Bash': 1, 'Edit': 1, 'unknown': 1})
        self.assertEqual(f['denials']['by_kind_tool']['permission-rule:Bash'], 1)

    def test_clean_session_has_zero_friction(self):
        self.session([user(ts(0), 'hi'), assistant(ts(1), 'm1')])
        row, _ = self.summarize()
        self.assertEqual(row['friction'], {
            'interrupts': 0,
            'denials': {'total': 0, 'by_kind': {}, 'by_tool': {}, 'by_kind_tool': {}},
            'hook_blocks': 0, 'policy_blocks': 0, 'compactions': 0})


class PromptTest(Base):
    def test_human_prompts_and_slash_commands(self):
        self.session([
            user(ts(0), 'first prompt'),
            user(ts(1), 'human tagged', origin={'kind': 'human'}),
            user(ts(2), 'meta', isMeta=True),
            user(ts(3), 'summary of earlier', isCompactSummary=True),
            user(ts(4), 'bg done', origin={'kind': 'task-notification'}),
            user(ts(5), '<local-command-stdout>ok</local-command-stdout>'),
            result(ts(6), 't1', 'out'),
            user(ts(7), '[Request interrupted by user]'),
            user(ts(8), '<command-message>sample-skill</command-message>\n<command-name>/sample-skill</command-name>'),
            user(ts(9), '<command-name>/sample-skill</command-name><command-args>x</command-args>'),
            user(ts(10), '<command-name>clear</command-name>'),
            user(ts(11), '<system-reminder>\nThe date has changed.\n</system-reminder>'),
        ])
        row, prompts = self.summarize()
        self.assertEqual(row['human_prompts'], 5)
        self.assertEqual(row['slash_commands'], {'/sample-skill': 2, '/clear': 1})
        self.assertEqual([p['text'] for p in prompts], ['first prompt', 'human tagged'])
        self.assertEqual(prompts[0], {'session_id': SID, 'ts': ts(0), 'text': 'first prompt'})

    def test_a_harness_reminder_is_not_a_prompt(self):
        self.session([user(ts(0), '  <system-reminder>Context left: 10%.</system-reminder>')])
        row, prompts = self.summarize()
        self.assertEqual((row['human_prompts'], prompts), (0, []))

    def test_a_slash_command_counts_as_a_prompt_but_is_not_cached(self):
        self.session([user(ts(0), '<command-message>tidy</command-message>\n<command-name>/tidy</command-name>'
                                  '\n<command-args>the whole repo</command-args>')])
        row, prompts = self.summarize()
        self.assertEqual((row['human_prompts'], row['slash_commands'], prompts), (1, {'/tidy': 1}, []))

    def test_prompt_text_is_truncated_to_200_chars(self):
        self.session([user(ts(0), 'word ' * 100)])
        _, prompts = self.summarize()
        self.assertEqual(len(prompts[0]['text']), 200)


class RedactTest(unittest.TestCase):
    def test_long_token_runs_removed(self):
        text = metrics.redact('key abcDEF0123456789abcdef0123456789 end')
        self.assertNotIn('0123456789abcdef', text)
        self.assertIn('end', text)

    def test_hex_and_base64_runs(self):
        for secret in ('deadbeef' * 5, 'QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=', 'a1B2c3D4e5F6g7H8i9J0k1'):
            self.assertNotIn(secret, metrics.redact(f'x {secret} y'))

    def test_short_words_and_plain_paths_kept(self):
        self.assertEqual(metrics.redact('fix the login bug in src/app'), 'fix the login bug in src/app')
        self.assertIn('shared-team-policy-repo/plugins', metrics.redact('see shared-team-policy-repo/plugins now'))

    def test_emails_removed(self):
        text = metrics.redact('mail someone.name@example.org please')
        self.assertNotIn('@', text)
        self.assertIn('please', text)

    def test_url_query_removed_but_path_kept(self):
        text = metrics.redact('open https://example.com/a/b?code=abc&state=xyz now')
        self.assertIn('https://example.com/a/b', text)
        self.assertNotIn('code=', text)
        self.assertIn('now', text)

    def test_text_after_secret_keywords_dropped_on_same_line_only(self):
        text = metrics.redact(
            f'use the {PW} hunter2 here\nnext line stays\n{BR} abc.def\nmy API_{TK}=xyz1\nok')
        self.assertNotIn('hunter2', text)
        self.assertNotIn('abc.def', text)
        self.assertNotIn('xyz1', text)
        self.assertIn('next line stays', text)
        self.assertTrue(text.rstrip().endswith('ok'))

    def test_keyword_inside_other_words_is_not_a_trigger(self):
        self.assertEqual(metrics.redact('reduce tokens per session'), 'reduce tokens per session')

    def test_secret_in_prompt_cache_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proj = root / 'projects' / 'p'
            write_jsonl(proj / f'{SID}.jsonl', [user(ts(0), f'login with {PW} hunter2 ok')])
            metrics.scan(projects=root / 'projects', out_path=root / 'm.jsonl', state_path=root / 's.json',
                         cache_path=root / 'c.jsonl', now=datetime(2026, 10, 4, tzinfo=timezone.utc),
                         ticket_key=TICKET_KEY)
            lines = (root / 'c.jsonl').read_text(encoding='utf-8')
            self.assertNotIn('hunter2', lines)
            self.assertIn('login with', lines)


class ScanTest(Base):
    def test_incremental_scan_skips_unchanged_and_upserts_changed(self):
        self.session([user(ts(0), 'one'), assistant(ts(1), 'm1', out=5)])
        other = '22222222-aaaa-bbbb-cccc-000000000002'
        self.session([user(ts(0, hour=9), 'other'), assistant(ts(1, hour=9), 'o1', out=1)], sid=other)

        first = self.scan()
        self.assertEqual((first['processed'], first['skipped'], first['rows']), (2, 0, 2))
        rows = self.read_rows()
        self.assertEqual([r['session_id'] for r in rows], [other, SID])  # sorted by first_ts

        second = self.scan()
        self.assertEqual((second['processed'], second['skipped'], second['rows']), (0, 2, 2))

        with open(self.main_path(), 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(assistant(ts(2), 'm2', out=95)) + '\n')
        third = self.scan()
        self.assertEqual((third['processed'], third['skipped'], third['rows']), (1, 1, 2))
        rows = {r['session_id']: r for r in self.read_rows()}
        self.assertEqual(rows[SID]['tokens']['main']['claude-opus-4']['output'], 100)
        self.assertEqual(rows[other]['tokens']['main']['claude-opus-4']['output'], 1)

    def test_changed_subagent_file_triggers_reprocess(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1', out=3)], {'agentType': 'x', 'model': 'haiku'})
        self.scan()
        self.subagent('agent-a1', [assistant(ts(1), 's1', out=3), assistant(ts(2), 's2', out=4)],
                      {'agentType': 'x', 'model': 'haiku'})
        again = self.scan()
        self.assertEqual(again['processed'], 1)
        self.assertEqual(self.read_rows()[0]['tokens']['subagent']['claude-opus-4']['output'], 7)

    def test_full_scan_reprocesses_everything(self):
        self.session([assistant(ts(0), 'm1')])
        self.scan()
        again = self.scan(full=True)
        self.assertEqual((again['processed'], again['skipped']), (1, 0))

    def test_full_scan_backfills_spawn_seconds_into_rows_written_before(self):
        self.session([assistant(ts(0), 'm1')])
        self.subagent('agent-a1', [assistant(ts(1), 's1'), assistant(ts(2), 's2')],
                      {'agentType': 'Explore', 'model': 'sonnet'})
        self.scan()
        old_rows = self.read_rows()
        for row in old_rows:
            row['subagents'].pop('seconds_by_type', None)
            row['subagents'].pop('seconds_by_model', None)
        self.out.write_text(''.join(json.dumps(row) + '\n' for row in old_rows), encoding='utf-8')

        self.assertEqual(self.scan()['skipped'], 1)
        self.assertNotIn('seconds_by_type', self.read_rows()[0]['subagents'])

        self.scan(full=True)
        subagents = self.read_rows()[0]['subagents']
        self.assertEqual(subagents.get('seconds_by_type'), {'Explore': 60})
        self.assertEqual(subagents.get('seconds_by_model'), {'sonnet': 60})
        self.assertEqual((subagents['count'], subagents['by_type'], subagents['by_model']),
                         (1, {'Explore': 1}, {'sonnet': 1}))

    def test_state_without_matching_row_forces_reprocess(self):
        self.session([assistant(ts(0), 'm1')])
        self.scan()
        self.out.unlink()
        again = self.scan()
        self.assertEqual(again['processed'], 1)
        self.assertEqual(len(self.read_rows()), 1)

    def test_output_is_utf8_lf_one_json_per_line(self):
        self.session([{'type': 'custom-title', 'customTitle': 'caf\u00e9 \u2192 ok', 'sessionId': SID},
                      assistant(ts(0), 'm1')])
        self.scan()
        raw = self.out.read_bytes()
        self.assertNotIn(b'\r', raw)
        self.assertTrue(raw.endswith(b'\n'))
        self.assertEqual(json.loads(raw.decode('utf-8'))['title'], 'caf\u00e9 \u2192 ok')

    def test_session_without_timestamps_produces_no_row_but_is_remembered(self):
        self.session([{'type': 'custom-title', 'customTitle': 't', 'sessionId': SID}])
        first = self.scan()
        self.assertEqual(first['rows'], 0)
        self.assertEqual(self.scan()['skipped'], 1)

    def test_prompt_cache_prunes_old_and_replaces_per_session(self):
        self.session([user('2026-08-01T10:00:00.000Z', 'ancient'), user(ts(0, day=3), 'recent one'),
                      assistant(ts(1, day=3), 'm1')])
        stale = {'session_id': 'gone', 'ts': '2026-07-01T00:00:00.000Z', 'text': 'stale'}
        keep = {'session_id': 'keep', 'ts': '2026-10-02T00:00:00.000Z', 'text': 'kept'}
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text('\n'.join(json.dumps(x) for x in (stale, keep)) + '\n', encoding='utf-8')
        self.scan()
        texts = sorted(r['text'] for r in self.read_cache())
        self.assertEqual(texts, ['kept', 'recent one'])
        with open(self.main_path(), 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(user(ts(5, day=3), 'newer')) + '\n')
        self.scan()
        texts = sorted(r['text'] for r in self.read_cache())
        self.assertEqual(texts, ['kept', 'newer', 'recent one'])

    def test_cli_rejects_missing_command(self):
        code, _, err = run_cli()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith('anomaly: '))


class SkillsUsedTest(unittest.TestCase):
    def test_skills_invoked_and_slash_commands_give_one_set_of_bare_names(self):
        row = {'skills_invoked': {'alpha': 2, 'beta': 1}, 'slash_commands': {'/gamma': 3, '/alpha': 1}}
        self.assertEqual(metrics.skills_used(row), {'alpha', 'beta', 'gamma'})

    def test_a_name_with_and_without_the_slash_is_the_same_skill(self):
        row = {'skills_invoked': {'/delta': 1}, 'slash_commands': {'/delta': 1}}
        self.assertEqual(metrics.skills_used(row), {'delta'})

    def test_a_plugin_qualified_name_counts_as_itself_and_as_its_bare_name(self):
        row = {'skills_invoked': {'pack:epsilon': 1}, 'slash_commands': {'/pack:zeta': 1}}
        used = metrics.skills_used(row)
        self.assertEqual(used, {'pack:epsilon', 'epsilon', 'pack:zeta', 'zeta'})
        self.assertNotIn('other:epsilon', used)

    def test_a_bare_name_does_not_count_as_a_qualified_one(self):
        self.assertNotIn('pack:eta', metrics.skills_used({'slash_commands': {'/eta': 1}}))

    def test_rows_without_the_fields_or_with_odd_values_give_an_empty_set(self):
        for row in ({}, {'skills_invoked': None, 'slash_commands': None}, {'skills_invoked': {'': 1, ' ': 1, 7: 1}},
                    {'slash_commands': {'/': 1}}):
            self.assertEqual(metrics.skills_used(row), frozenset())

    def test_list_values_from_older_rows_are_read_like_the_counted_form(self):
        self.assertEqual(metrics.skills_used({'skills_invoked': ['theta'], 'slash_commands': ['/iota']}),
                         {'theta', 'iota'})


if __name__ == '__main__':
    unittest.main()

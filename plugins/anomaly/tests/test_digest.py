import dataclasses
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from anomaly_loop import addenda, digest, ideas, index, profile, records
from tests.fixtures import anomaly_text, context, run_cli, write_experiment_anomaly, write_text


class DigestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.context = context(self.home)


class RegistryTest(DigestCase):
    def test_ships_with_the_index_section_and_every_entry_resolves_to_a_function(self):
        self.assertIn(('index', 'digest_section'), digest.SECTIONS)
        self.assertIn(index.digest_section, digest.section_functions())
        self.assertIn(('addenda', 'recheck_section'), digest.SECTIONS)
        self.assertIn(addenda.recheck_section, digest.section_functions())
        self.assertTrue(all(callable(section) for section in digest.section_functions()))

    def test_sections_run_in_order_empty_ones_skipped_blank_line_between(self):
        def first(context):
            return ['## First', f'today {context.today}']

        def nothing(context):
            return []

        def last(context):
            return ['## Last']
        self.assertEqual(digest.render(self.context, (first, nothing, last)),
                         ['## First', 'today 2026-10-04', '', '## Last'])

    def test_context_is_read_only_and_loads_records_on_demand(self):
        write_text(self.home / 'anomalies' / 'a.md', anomaly_text('a', 2, 2))
        write_text(self.home / 'metrics.jsonl', '{"session_id":"s1"}\n')
        write_text(self.home / 'session-kinds.jsonl', '{"session_id":"s1","kind":"build","set_on":"2026-10-01"}\n')
        self.assertEqual([a.signature for a in self.context.anomalies], ['a'])
        self.assertIsInstance(self.context.anomalies, tuple)
        self.assertEqual(self.context.metrics_rows, ({'session_id': 's1'},))
        self.assertEqual(self.context.session_kinds['s1']['kind'], 'build')
        self.assertEqual((self.context.ideas, self.context.lenses), ((), ()))
        self.assertFalse(self.context.profile.exists)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self.context.today = date(2000, 1, 1)
        with self.assertRaises(TypeError):
            self.context.session_kinds['s2'] = {}

    def test_each_kind_of_record_is_loaded_once(self):
        loaders = {'anomalies': (records, 'load_anomalies'), 'ideas': (ideas, 'load_ideas'),
                   'lenses': (records, 'load_lenses'), 'session_kinds': (records, 'load_session_kinds'),
                   'profile': (profile, 'load_profile'), 'metrics_rows': (digest, 'load_lines'),
                   'rechecks': (addenda, 'scan_rechecks')}
        for attribute, (module, name) in loaders.items():
            with self.subTest(attribute=attribute), \
                    mock.patch.object(module, name, wraps=getattr(module, name)) as loader:
                getattr(self.context, attribute)
                getattr(self.context, attribute)
                self.assertEqual(loader.call_count, 1)

    def test_context_carries_the_user_config_and_plugin_folders(self):
        self.assertEqual(self.context.user_config, self.home.parent / 'user-config')
        self.assertEqual(self.context.plugin_root, self.home.parent / 'plugin')
        self.assertEqual(context(self.home, plugin_root=Path('elsewhere')).plugin_root, Path('elsewhere'))

    def test_context_carries_the_data_folder_and_it_may_be_absent(self):
        self.assertTrue(self.context.data.is_dir())
        self.assertNotEqual(self.context.data, self.home)
        self.assertIsNone(context(self.home, data=None).data)


class IndexSectionTest(DigestCase):
    def test_backlog_counts_and_top_three_by_score(self):
        for signature, impact, occurrences in (('a', 1, 1), ('b', 3, 2), ('c', 2, 2), ('d', 1, 3)):
            write_text(self.home / 'anomalies' / f'{signature}.md', anomaly_text(signature, impact, occurrences))
        write_text(self.home / 'anomalies' / 'z.md', anomaly_text('z', 3, 3, status='fixed'))
        self.assertEqual(index.digest_section(self.context),
                         ['## Backlog', '4 open · 1 closed', '- 6  b', '- 4  c', '- 3  d'])

    def test_empty_backlog_says_so(self):
        self.assertEqual(index.digest_section(self.context), ['## Backlog', '0 open · 0 closed'])


class RecheckSectionTest(DigestCase):
    """AC-16 and AC-17: an addenda line whose target changed since the line was written, or whose target
    is gone, is listed under re-check."""
    STALE = '0a1b2c3d'   # a stamp that is not the stamp of any file the tests write

    def setUp(self):
        super().setUp()
        self.plugin = self.home.parent / 'plugin'
        write_text(self.plugin / 'skills' / 'observe' / 'SKILL.md', '# observe\n')
        write_text(self.plugin / 'skills' / 'research' / 'SKILL.md', '# research\n')

    def line(self, name, text, signature, stamp, agent=False, check_by='2026-10-01', **experiment):
        """A line in the addenda file of the skill or agent `name`, with its experiment on record."""
        addenda.append_line(addenda.addendum_path(self.home, name, agent=agent), text, signature, stamp)
        write_experiment_anomaly(self.home, signature, target=f'anomaly:{name}', check_by=check_by,
                                 fixed_by=f'2026-09-10 · addenda/{"agents/" if agent else ""}{name}.md', **experiment)

    def section(self):
        return addenda.recheck_section(self.context)

    def test_a_line_whose_stamp_differs_from_its_targets_hash_is_listed_with_the_drop_command(self):
        current = addenda.stamp(self.plugin / 'skills' / 'observe')
        self.line('observe', 'Ask which repo first.', 'stale-one', self.STALE, result='keep')
        self.line('observe', 'Name the file first.', 'fresh-one', current, result='keep')
        lines = self.section()
        out = '\n'.join(lines)
        self.assertIn('re-check', lines[0].lower())
        self.assertIn('Ask which repo first.', out)
        self.assertIn("calibrate drop stale-one --reason '<text>'", out)
        self.assertNotIn('fresh-one', out)
        self.assertNotIn('Name the file first.', out)

    def test_a_stale_line_whose_experiment_has_no_result_shows_its_check_date_not_the_drop_command(self):
        self.line('research', 'Cite the source.', 'in-flight', self.STALE, check_by='2026-10-25')
        lines = self.section()
        self.assertTrue(any('in-flight' in line and '2026-10-25' in line for line in lines), lines)
        self.assertNotIn('calibrate drop', '\n'.join(lines))

    def test_an_addenda_file_whose_skill_or_agent_is_gone_is_listed_naming_the_missing_target(self):
        self.line('gone-skill', 'Ask which repo first.', 'skill-line', self.STALE, result='keep')
        self.line('gone-agent', 'Name the file first.', 'agent-line', self.STALE, agent=True, result='keep')
        out = '\n'.join(self.section())
        self.assertIn('the skill gone-skill is gone from the plugin', out)
        self.assertIn('the agent gone-agent is gone from the plugin', out)


class DigestCommandTest(DigestCase):
    def test_digest_prints_registered_sections_with_the_injected_date(self):
        def dated(context):
            return [f'home {context.home.name}, today {context.today}']
        with mock.patch.object(digest, 'SECTIONS', (('index', 'digest_section'),)), \
                mock.patch.object(index, 'digest_section', dated):
            code, out, err = run_cli('digest', '--home', str(self.home),
                                     now=datetime(2026, 11, 2, tzinfo=timezone.utc))
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(out, 'home home, today 2026-11-02\n')

    def test_digest_passes_the_user_config_and_plugin_folders_to_sections(self):
        def folders(context):
            return [context.user_config.name, context.plugin_root.name]
        environ = {'CLAUDE_PLUGIN_ROOT': str(Path(self.tmp.name) / 'env-plug')}
        with mock.patch.object(digest, 'SECTIONS', (('index', 'digest_section'),)), \
                mock.patch.object(index, 'digest_section', folders):
            _, out, _ = run_cli('digest', '--home', str(self.home), '--user-config',
                                str(Path(self.tmp.name) / 'opt-cfg'), environ=environ)
        self.assertEqual(out.splitlines(), ['opt-cfg', 'env-plug'])

    def test_digest_passes_the_data_folder_to_sections(self):
        def folder(context):
            return [context.data.name]
        with mock.patch.object(digest, 'SECTIONS', (('index', 'digest_section'),)), \
                mock.patch.object(index, 'digest_section', folder):
            _, from_option, _ = run_cli('digest', '--home', str(self.home), '--data',
                                        str(Path(self.tmp.name) / 'opt-data'))
            _, from_env, _ = run_cli('digest', '--home', str(self.home),
                                     environ={'CLAUDE_PLUGIN_DATA': str(Path(self.tmp.name) / 'env-data')})
        self.assertEqual((from_option, from_env), ('opt-data\n', 'env-data\n'))

    def test_digest_without_a_data_folder_gives_sections_none(self):
        def folder(context):
            return [repr(context.data)]
        with mock.patch.object(digest, 'SECTIONS', (('index', 'digest_section'),)), \
                mock.patch.object(index, 'digest_section', folder):
            code, out, _ = run_cli('digest', '--home', str(self.home))
        self.assertEqual((code, out), (0, 'None\n'))

    def test_the_calibrate_addendum_is_the_last_thing_the_digest_prints(self):
        """AC-13: the output without an addenda file stays as it was, and the addendum follows it."""
        _, before, _ = run_cli('digest', '--home', str(self.home))
        addenda.append_line(addenda.addendum_path(self.home, 'calibrate'), 'Read the backlog top down.',
                            'skipped-top', '0a1b2c3d')
        code, after, err = run_cli('digest', '--home', str(self.home))
        self.assertEqual((code, err), (0, ''))
        self.assertTrue(before.strip(), before)
        self.assertTrue(after.startswith(before), after)
        self.assertIn('Read the backlog top down.', after.rstrip().splitlines()[-1])

    def test_digest_refuses_a_data_folder_inside_home(self):
        code, out, err = run_cli('digest', '--home', str(self.home), '--data', str(self.home / 'state'))
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('anomaly: data folder'))


class ContextBuilderTest(DigestCase):
    def args(self, *argv):
        import argparse
        parser = argparse.ArgumentParser(parents=[digest.folder_options()])
        for name in ('--home', '--data'):
            parser.add_argument(name)
        args = parser.parse_args(list(argv))
        args.now = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
        args.today = args.now.date()
        return args

    def test_the_folders_come_from_the_options_then_the_environment(self):
        root = Path(self.tmp.name)
        args = self.args('--home', str(self.home), '--user-config', str(root / 'uc'))
        built = digest.context_from_args(args, {'CLAUDE_PLUGIN_ROOT': str(root / 'plug')})
        self.assertEqual((built.home, built.user_config, built.plugin_root, built.data, built.today),
                         (self.home, root / 'uc', root / 'plug', None, date(2026, 10, 4)))

    def test_a_resolved_data_folder_is_used_as_given(self):
        data = Path(self.tmp.name) / 'data'
        built = digest.context_from_args(self.args('--home', str(self.home)), {}, data=data)
        self.assertEqual(built.data, data)

    def test_a_strict_context_refuses_an_invalid_record(self):
        write_text(self.home / 'anomalies' / 'bad.md', anomaly_text('bad', 9, 1))
        loose = digest.context_from_args(self.args('--home', str(self.home)), {})
        self.assertEqual(len(loose.anomalies), 1)
        strict = digest.context_from_args(self.args('--home', str(self.home)), {}, strict=True)
        with self.assertRaises(records.RecordError):
            strict.anomalies


if __name__ == '__main__':
    unittest.main()

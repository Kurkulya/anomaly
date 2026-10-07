import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anomaly_loop import paths


class PathsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fake_user_folder = {'HOME': self.tmp.name, 'USERPROFILE': self.tmp.name}
        patcher = mock.patch.dict(os.environ, fake_user_folder)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)


class HomeTest(PathsBase):
    def test_option_wins_over_env_and_default(self):
        env = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_home(str(self.root / 'from-option'), env), self.root / 'from-option')

    def test_env_wins_over_default(self):
        env = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_home(None, env), self.root / 'from-env')

    def test_default_is_claude_anomaly_under_the_user_folder(self):
        self.assertEqual(paths.resolve_home(None, {}), self.root / '.claude' / 'anomaly')

    def test_tilde_is_expanded_in_option_env_and_default(self):
        expected = self.root / '.claude' / 'anomaly'
        self.assertEqual(paths.resolve_home('~/.claude/anomaly', {}), expected)
        self.assertEqual(paths.resolve_home(None, {'CLAUDE_PLUGIN_OPTION_HOME': '~/.claude/anomaly'}), expected)
        self.assertEqual(paths.resolve_home('~', {}), self.root)

    def test_blank_values_count_as_unset(self):
        env = {'CLAUDE_PLUGIN_OPTION_HOME': '  '}
        self.assertEqual(paths.resolve_home('', env), self.root / '.claude' / 'anomaly')


    def test_unfilled_placeholder_counts_as_unset_and_falls_through_to_default(self):
        self.assertEqual(paths.resolve_home('${user_config.home}', {}), self.root / '.claude' / 'anomaly')

    def test_unfilled_placeholder_falls_through_to_env(self):
        env = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_home('${user_config.home}', env), self.root / 'from-env')

    def test_placeholder_only_counts_when_it_is_the_whole_value(self):
        self.assertEqual(paths.resolve_home('${user_config.home}/x', {}), Path('${user_config.home}/x'))


class DataTest(PathsBase):
    def setUp(self):
        super().setUp()
        self.home = self.root / 'home'

    def test_option_wins_over_env(self):
        env = {'CLAUDE_PLUGIN_DATA': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_data(str(self.root / 'from-option'), env, self.home),
                         self.root / 'from-option')

    def test_env_is_used_without_option(self):
        env = {'CLAUDE_PLUGIN_DATA': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_data(None, env, self.home), self.root / 'from-env')

    def test_tilde_is_expanded(self):
        self.assertEqual(paths.resolve_data('~/state', {}, self.home), self.root / 'state')

    def test_no_data_folder_is_an_error_naming_both_sources(self):
        with self.assertRaises(paths.PathError) as raised:
            paths.resolve_data(None, {}, self.home)
        message = str(raised.exception)
        self.assertIn('--data', message)
        self.assertIn('CLAUDE_PLUGIN_DATA', message)

    def test_unfilled_placeholder_is_an_error_not_a_folder_name(self):
        with self.assertRaises(paths.PathError):
            paths.resolve_data('${CLAUDE_PLUGIN_DATA}', {}, self.home)

    def test_blank_data_value_is_an_error(self):
        with self.assertRaises(paths.PathError):
            paths.resolve_data('  ', {'CLAUDE_PLUGIN_DATA': ''}, self.home)

    def test_data_inside_or_equal_to_home_is_an_error(self):
        for data in (self.home / 'state', self.home, self.home / 'a' / '..' / 'b'):
            with self.assertRaises(paths.PathError) as raised:
                paths.resolve_data(str(data), {}, self.home)
            self.assertIn('inside home', str(raised.exception))

    def test_data_next_to_home_is_fine(self):
        self.assertEqual(paths.resolve_data(str(self.root / 'home-data'), {}, self.home),
                         self.root / 'home-data')


class OptionalDataTest(PathsBase):
    def setUp(self):
        super().setUp()
        self.home = self.root / 'home'

    def test_unset_blank_or_unfilled_data_is_none(self):
        for option, env in ((None, {}), ('  ', {'CLAUDE_PLUGIN_DATA': ''}), ('${CLAUDE_PLUGIN_DATA}', {})):
            self.assertIsNone(paths.resolve_optional_data(option, env, self.home))

    def test_a_given_folder_resolves_like_the_required_one(self):
        env = {'CLAUDE_PLUGIN_DATA': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_optional_data(None, env, self.home), self.root / 'from-env')
        self.assertEqual(paths.resolve_optional_data(str(self.root / 'opt'), env, self.home), self.root / 'opt')

    def test_a_given_folder_inside_home_is_still_an_error(self):
        with self.assertRaises(paths.PathError):
            paths.resolve_optional_data(str(self.home / 'state'), {}, self.home)


class NoticeTest(PathsBase):
    def test_unfilled_home_option_names_the_folder_used_instead(self):
        env = {'CLAUDE_PLUGIN_OPTION_HOME': str(self.root / 'from-env')}
        self.assertEqual(paths.home_notice('${user_config.home}', env),
                         f"home: placeholder unfilled, using {self.root / 'from-env'}")
        self.assertEqual(paths.home_notice(' ${x} ', {}),
                         f"home: placeholder unfilled, using {self.root / '.claude' / 'anomaly'}")

    def test_no_notice_for_a_real_blank_or_absent_option(self):
        for option in (str(self.root / 'h'), '', None, '${user_config.home}/x'):
            self.assertIsNone(paths.home_notice(option, {}))

    def test_is_unfilled_is_the_rule_first_value_uses(self):
        self.assertTrue(paths.is_unfilled('${a}'))
        self.assertFalse(paths.is_unfilled('${a}/b'))
        self.assertFalse(paths.is_unfilled(None))
        self.assertIsNone(paths.first_value('${a}', None, ' '))


class ProjectsTest(PathsBase):
    def test_option_env_then_default(self):
        self.assertEqual(paths.resolve_projects('~/t', {}), self.root / 't')
        self.assertEqual(paths.resolve_projects(None, {'ANOMALY_PROJECTS': str(self.root / 'p')}), self.root / 'p')
        self.assertEqual(paths.resolve_projects(None, {}), self.root / '.claude' / 'projects')
        self.assertEqual(paths.resolve_projects('${projects}', {}), self.root / '.claude' / 'projects')


class UserConfigTest(PathsBase):
    def test_option_env_then_the_claude_folder_under_the_user_folder(self):
        self.assertEqual(paths.resolve_user_config('~/cfg', {}), self.root / 'cfg')
        env = {'ANOMALY_USER_CONFIG': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_user_config(None, env), self.root / 'from-env')
        self.assertEqual(paths.resolve_user_config(None, {}), self.root / '.claude')
        self.assertEqual(paths.resolve_user_config('${user_config.x}', {}), self.root / '.claude')


class PluginRootTest(PathsBase):
    def test_option_env_then_the_folder_that_holds_the_package(self):
        self.assertEqual(paths.resolve_plugin_root('~/p', {}), self.root / 'p')
        env = {'CLAUDE_PLUGIN_ROOT': str(self.root / 'from-env')}
        self.assertEqual(paths.resolve_plugin_root(None, env), self.root / 'from-env')
        package_parent = Path(paths.__file__).resolve().parent.parent
        self.assertEqual(paths.resolve_plugin_root(None, {}), package_parent)
        self.assertEqual(paths.resolve_plugin_root('${CLAUDE_PLUGIN_ROOT}', {}), package_parent)
        self.assertTrue((package_parent / '.claude-plugin' / 'plugin.json').is_file())


if __name__ == '__main__':
    unittest.main()

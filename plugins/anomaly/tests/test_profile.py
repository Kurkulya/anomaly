import re
import shutil
import tempfile
import unittest
from pathlib import Path

from anomaly_loop import constants, profile

FULL = r"""---
# comment lines are ignored
tracker: local markdown files
glossary_file: CONTEXT.md
ticket_key: PRJ\d+
branch_pattern: <type>/<key>/<slug>
commit_style: <type>(<key>): <summary>
implementers:
  stack-a: agent-one
  stack-b: agent-two
mr_tool: some-skill
verify_ui: some-checker
issue_source: a tracker, read-only
---

Free text below the frontmatter is ignored.
"""


class ParseTest(unittest.TestCase):
    def test_reads_key_value_lines_and_ignores_comments_and_body(self):
        values = profile.parse_profile(FULL)
        self.assertEqual(values['tracker'], 'local markdown files')
        self.assertEqual(values['commit_style'], '<type>(<key>): <summary>')
        self.assertEqual(values['ticket_key'], r'PRJ\d+')
        self.assertNotIn('Free', ' '.join(values))

    def test_indented_lines_continue_the_previous_key(self):
        values = profile.parse_profile(FULL)
        self.assertEqual(values['implementers'], 'stack-a: agent-one\nstack-b: agent-two')

    def test_text_without_frontmatter_has_no_keys(self):
        self.assertEqual(profile.parse_profile('tracker: x\n'), {})
        self.assertEqual(profile.parse_profile(''), {})

    def test_unclosed_frontmatter_has_no_keys(self):
        self.assertEqual(profile.parse_profile('---\ntracker: x\n'), {})

    def test_one_pair_of_matching_outer_quotes_is_removed(self):
        text = '\n'.join(['---', 'a: "x y"', r"b: 'PRJ\d+'", "c: \"x'", 'd: "', 'e: ""', '---'])
        values = profile.parse_profile(text)
        self.assertEqual(values['a'], 'x y')
        self.assertEqual(values['b'], r'PRJ\d+')
        self.assertEqual(values['c'], "\"x'")
        self.assertEqual(values['d'], '"')
        self.assertEqual(values['e'], '')

    def test_crlf_line_endings_are_accepted(self):
        values = profile.parse_profile(FULL.replace('\n', '\r\n'))
        self.assertEqual(values['mr_tool'], 'some-skill')


class LoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, text):
        (self.home / 'profile.md').write_text(text, encoding='utf-8', newline='\n')

    def test_complete_profile_has_no_missing_keys_and_no_message(self):
        self.write(FULL)
        loaded = profile.load_profile(self.home)
        self.assertTrue(loaded.exists)
        self.assertEqual(loaded.missing, [])
        self.assertIsNone(profile.missing_message(loaded))

    def test_missing_and_blank_keys_are_listed_in_template_order_in_one_line(self):
        self.write('---\ntracker: x\nglossary_file:\nmr_tool: y\n---\n')
        loaded = profile.load_profile(self.home)
        self.assertEqual(loaded.missing, ['glossary_file', 'ticket_key', 'branch_pattern', 'commit_style',
                                          'implementers', 'verify_ui', 'issue_source'])
        message = profile.missing_message(loaded)
        self.assertEqual(len(message.splitlines()), 1)
        self.assertTrue(message.startswith('profile: '))
        self.assertIn('glossary_file, ticket_key', message)
        self.assertNotIn('tracker,', message)

    def test_absent_file_reports_every_key_and_the_expected_path(self):
        loaded = profile.load_profile(self.home)
        self.assertFalse(loaded.exists)
        self.assertEqual(loaded.missing, list(profile.PROFILE_KEYS))
        message = profile.missing_message(loaded)
        self.assertEqual(len(message.splitlines()), 1)
        self.assertIn(str(self.home / 'profile.md'), message)
        for key in profile.PROFILE_KEYS:
            self.assertIn(key, message)

    def test_optional_build_skills_is_never_reported_missing(self):
        self.write(FULL)
        self.assertNotIn('build_skills', profile.load_profile(self.home).missing)
        self.assertNotIn('build_skills', profile.PROFILE_KEYS)
        self.assertIn('build_skills', profile.OPTIONAL_KEYS)

    def test_shipped_template_copied_unchanged_is_not_complete(self):
        template = Path(__file__).resolve().parent.parent / 'templates' / 'profile.md'
        shutil.copy(template, self.home / 'profile.md')
        loaded = profile.load_profile(self.home)
        self.assertEqual(loaded.missing, ['implementers', 'mr_tool', 'verify_ui', 'issue_source'])
        self.assertEqual(loaded.invalid, [])
        self.assertEqual(profile.ticket_key_pattern(loaded).pattern, constants.DEFAULT_TICKET_KEY)

    def test_placeholder_values_count_as_missing(self):
        self.write('\n'.join([
            '---', 'tracker: <where>', 'glossary_file: CONTEXT.md', 'mr_tool: <skill or command>',
            'implementers:', '  a: <agent id>', '  b: <agent id>', 'verify_ui: do <this> now',
            'issue_source:', '  a: <x>', '  b: real-agent', '---']))
        missing = profile.load_profile(self.home).missing
        for key in ('tracker', 'mr_tool', 'implementers'):
            self.assertIn(key, missing)
        for key in ('glossary_file', 'verify_ui', 'issue_source'):
            self.assertNotIn(key, missing)

    def test_utf8_bom_does_not_empty_the_profile(self):
        (self.home / 'profile.md').write_bytes(b'\xef\xbb\xbf' + FULL.encode('utf-8'))
        loaded = profile.load_profile(self.home)
        self.assertEqual(loaded.missing, [])
        self.assertEqual(loaded.values['tracker'], 'local markdown files')

    def test_a_profile_that_is_not_utf8_reads_as_empty_and_the_line_says_why(self):
        (self.home / 'profile.md').write_bytes(b'---\ntracker: caf\xe9\n---\n')
        loaded = profile.load_profile(self.home)
        self.assertEqual(loaded.missing, list(profile.PROFILE_KEYS))
        message = profile.missing_message(loaded)
        self.assertEqual(len(message.splitlines()), 1)
        self.assertTrue(message.startswith(f'profile: {self.home / "profile.md"}: not UTF-8 text'), message)
        self.assertIn('read as empty', message)
        self.assertIn('missing keys: tracker', message)

    def test_nine_required_keys(self):
        self.assertEqual(len(profile.PROFILE_KEYS), 9)


class TicketKeyTest(unittest.TestCase):
    def pattern(self, text):
        return profile.ticket_key_pattern(profile.Profile(values=profile.parse_profile(text), exists=True))

    def test_default_is_the_generic_shape(self):
        pattern = profile.ticket_key_pattern(profile.Profile(values={}, exists=False))
        self.assertEqual(pattern.findall('feat/ABC-123/x and XY9-7'), ['ABC-123', 'XY9-7'])
        self.assertEqual(pattern.pattern, constants.DEFAULT_TICKET_KEY)

    def test_profile_value_overrides_the_default(self):
        pattern = self.pattern('---\nticket_key: PRJ\\d+\n---\n')
        self.assertIsInstance(pattern, re.Pattern)
        self.assertEqual(pattern.findall('feat/PRJ42/ABC-12'), ['PRJ42'])

    def test_quoted_value_matches_like_the_unquoted_pattern(self):
        pattern = self.pattern('---\nticket_key: "PRJ\\d+"\n---\n')
        self.assertEqual(pattern.findall('feat/PRJ42/x'), ['PRJ42'])

    def test_placeholder_value_falls_back_to_default(self):
        self.assertEqual(self.pattern('---\nticket_key: <regex>\n---\n').pattern, constants.DEFAULT_TICKET_KEY)

    def test_blank_value_falls_back_to_default(self):
        self.assertEqual(self.pattern('---\nticket_key:\n---\n').pattern, constants.DEFAULT_TICKET_KEY)

    def test_invalid_pattern_falls_back_to_default_and_is_reported(self):
        loaded = profile.Profile(values=profile.parse_profile('---\nticket_key: [oops\n---\n'), exists=True)
        self.assertEqual(profile.ticket_key_pattern(loaded).pattern, constants.DEFAULT_TICKET_KEY)
        self.assertIn('ticket_key', profile.missing_message(loaded))


class BuildSkillsTest(unittest.TestCase):
    def skills(self, text):
        return profile.build_skills(profile.Profile(values=profile.parse_profile(text), exists=True))

    def test_default_is_the_constant_without_a_profile_or_a_key(self):
        self.assertEqual(profile.build_skills(profile.Profile(values={}, exists=False)), constants.BUILD_SKILLS)
        self.assertEqual(self.skills('---\ntracker: x\n---\n'), constants.BUILD_SKILLS)

    def test_a_comma_list_overrides_the_default(self):
        self.assertEqual(self.skills('---\nbuild_skills: alpha, beta ,gamma\n---\n'),
                         ('alpha', 'beta', 'gamma'))

    def test_a_line_list_overrides_the_default_with_or_without_dashes(self):
        self.assertEqual(self.skills('---\nbuild_skills:\n  alpha\n  - beta\n---\n'), ('alpha', 'beta'))

    def test_a_slash_in_front_of_a_name_is_dropped_and_a_qualified_name_is_kept(self):
        self.assertEqual(self.skills('---\nbuild_skills: /alpha, pack:beta\n---\n'), ('alpha', 'pack:beta'))

    def test_one_pair_of_square_brackets_around_the_list_is_dropped(self):
        self.assertEqual(self.skills('---\nbuild_skills: [alpha, beta]\n---\n'), ('alpha', 'beta'))
        self.assertEqual(self.skills('---\nbuild_skills: [ /alpha ]\n---\n'), ('alpha',))

    def test_blank_and_placeholder_values_are_not_set(self):
        for text in ('build_skills:', 'build_skills: ,  ,', 'build_skills: []', 'build_skills: <skill-a>',
                     'build_skills:\n  <skill-a>\n  <skill-b>'):
            with self.subTest(text=text):
                self.assertEqual(self.skills(f'---\n{text}\n---\n'), constants.BUILD_SKILLS)

    def test_the_shipped_template_sets_no_build_skills(self):
        template = Path(profile.__file__).resolve().parent.parent / 'templates' / 'profile.md'
        self.assertEqual(self.skills(template.read_text(encoding='utf-8')), ())


class IsSetTest(unittest.TestCase):
    def test_absent_blank_and_placeholder_values_are_not_set(self):
        for value in (None, '', '<agent id>', 'stack-a: <agent id>\nstack-b: <agent id>'):
            with self.subTest(value=value):
                self.assertFalse(profile.is_set(value))

    def test_a_real_value_is_set_even_with_a_placeholder_inside(self):
        for value in ('agent-one', 'do <this> now', 'stack-a: <agent id>\nstack-b: real-agent'):
            with self.subTest(value=value):
                self.assertTrue(profile.is_set(value))


class ListNamesTest(unittest.TestCase):
    def test_names_separated_by_commas_or_lines_with_or_without_dashes(self):
        self.assertEqual(profile.list_names('alpha, beta ,gamma'), ('alpha', 'beta', 'gamma'))
        self.assertEqual(profile.list_names('alpha\n- beta\ngamma, delta'), ('alpha', 'beta', 'gamma', 'delta'))

    def test_one_pair_of_square_brackets_is_dropped(self):
        self.assertEqual(profile.list_names('[alpha, pack:beta]'), ('alpha', 'pack:beta'))

    def test_blank_placeholder_values_and_placeholder_items_give_no_names(self):
        for value in (None, '', ' ,  ,', '[]', '<agent id>'):
            with self.subTest(value=value):
                self.assertEqual(profile.list_names(value), ())
        self.assertEqual(profile.list_names('alpha, <agent id>'), ('alpha',))


if __name__ == '__main__':
    unittest.main()

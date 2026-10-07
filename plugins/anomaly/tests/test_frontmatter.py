import unittest

from anomaly_loop import frontmatter

SKILL = """---
description: Review one diff.
allowed-tools: Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)
disable-model-invocation: true
---
# body
"""


class HyphenatedKeyTest(unittest.TestCase):
    def test_a_key_with_hyphens_is_read_like_any_other(self):
        fields, body = frontmatter.split(SKILL)
        self.assertEqual(fields['allowed-tools'], 'Bash(python "${CLAUDE_PLUGIN_ROOT}/scripts/anomaly.py" *)')
        self.assertEqual(fields['disable-model-invocation'], 'true')
        self.assertEqual(fields['description'], 'Review one diff.')
        self.assertEqual(body, '# body')

    def test_continuation_lines_belong_to_the_hyphenated_key_that_precedes_them(self):
        fields, _ = frontmatter.split('---\nname: a\nallowed-tools:\n  - Read\n  - Grep\nother: x\n---\n')
        self.assertEqual(frontmatter.items(fields['allowed-tools']), ['Read', 'Grep'])
        self.assertEqual(fields['name'], 'a')
        self.assertEqual(fields['other'], 'x')

    def test_a_key_must_still_start_with_a_letter_or_underscore(self):
        fields, _ = frontmatter.split('---\n-bad: 1\n9bad: 2\nok-key: 3\n_ok: 4\n---\n')
        self.assertEqual(fields, {'ok-key': '3', '_ok': '4'})


class UnchangedBehaviourTest(unittest.TestCase):
    def test_underscore_keys_nested_pairs_and_items_read_as_before(self):
        text = ('---\nfirst_seen: 2026-09-01\nexperiment:\n  expect: faster\n  check-by: 2026-10-25\n'
                'related:\n  - a\n  - b\n---\nBody.\n')
        fields, body = frontmatter.split(text)
        self.assertEqual(fields['first_seen'], '2026-09-01')
        self.assertEqual(frontmatter.pairs(fields['experiment']), {'expect': 'faster', 'check-by': '2026-10-25'})
        self.assertEqual(frontmatter.items(fields['related']), ['a', 'b'])
        self.assertEqual(body, 'Body.')

    def test_text_without_a_closed_block_has_no_fields(self):
        self.assertEqual(frontmatter.split('allowed-tools: x\n'), ({}, 'allowed-tools: x\n'))
        self.assertEqual(frontmatter.split('---\nallowed-tools: x\n'), ({}, '---\nallowed-tools: x\n'))


class NestedTest(unittest.TestCase):
    def test_a_pair_needs_a_space_after_the_colon_so_an_id_with_a_colon_stays_whole(self):
        self.assertEqual(frontmatter.nested('web: my-agent\npack:agent\nmobile: kit:m-agent'),
                         ({'web': 'my-agent', 'mobile': 'kit:m-agent'}, ['pack:agent']))

    def test_a_name_may_hold_spaces_and_hyphens_and_an_empty_value_is_a_pair(self):
        self.assertEqual(frontmatter.nested('deep analysis: model-z\nstack-b:\ntheme_key: k'),
                         ({'deep analysis': 'model-z', 'stack-b': '', 'theme_key': 'k'}, []))

    def test_a_repeated_name_keeps_its_last_value_and_blank_lines_are_skipped(self):
        self.assertEqual(frontmatter.nested('web: one\n\n  \nweb: two\nplain line'),
                         ({'web': 'two'}, ['plain line']))

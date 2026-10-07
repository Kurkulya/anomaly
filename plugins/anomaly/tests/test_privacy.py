import unittest

from anomaly_loop import privacy
from anomaly_loop.files import RecordError
from tests.fixtures import SID

SHA1 = 'a' * 20 + '0123456789abcdef0123'
SHA256 = '0123456789abcdef' * 4
HEX_RUN = '0123456789abcdef' * 5


class PrivacyProblemsTest(unittest.TestCase):
    def test_plain_process_wording_is_accepted(self):
        for text in ('token cost grew after the review', 'password reset step was manual',
                     'secret scan hook was slow', 'Bearer header missing', 'Bearer authorization was absent',
                     'read plugins/anomaly/anomaly_loop/cli.py and https://example.com/docs',
                     f'session {SID} ran long', f'fixed in commit {SHA1}', f'fixed in {SHA256}',
                     'commit abc1234 broke it', 'the token budget ran out'):
            with self.subTest(text=text):
                self.assertEqual(privacy.privacy_problems(text), [])

    def test_real_looking_paths_names_and_urls_are_accepted(self):
        for text in ('~/.config/skills/build/SKILL.md', 'plugins/anomaly/skills/observe/SKILL.md',
                     'useResizeObserverCallbackHandler', 'https://git.example/group/project/-/merge_requests/123',
                     r'C:\Work\some-folder\a-rather-long-file-name.md', 'a-rather-long-kebab-case-name-here',
                     'set CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000 for builds',
                     'set NODE_OPTIONS=--max-old-space-size=8192 for builds'):
            with self.subTest(text=text):
                self.assertEqual(privacy.privacy_problems(text), [])

    def test_credentials_in_assignment_form_are_refused(self):
        for name in ('pw', 'passwd', 'password', 'token', 'secret', 'apikey', 'api_key', 'API-KEY'):
            for joiner in (': ', '=', ' = '):
                with self.subTest(name=name, joiner=joiner):
                    self.assertIn('a credential', privacy.privacy_problems(f'sent {name}{joiner}example-value'))
        for text in ('Authorization: Bearer example12345', 'sent Bearer eyJhbGciOiJIUzI1NiJ9.example'):
            with self.subTest(text=text):
                self.assertIn('a credential', privacy.privacy_problems(text))

    def test_query_urls_and_emails_are_refused(self):
        for text in ('opened https://example.com/page?code=example and failed', 'asked jane.doe@example.com'):
            with self.subTest(text=text[:30]):
                self.assertTrue(privacy.privacy_problems(text))

    def test_opaque_strings_are_refused_alone_or_inside_a_path(self):
        for text in ('key ' + 'A1b2C3d4' * 5, 'z' * 25 + '1', 'plugins/' + 'A1b2C3d4' * 5 + '/x.md',
                     'Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MDEyMw==', 'ab12+cd34/ef56' * 3,
                     'Zm9vYmFyYmF6cXV4MTIz/NDU2Nzg5MDEyMwx='):
            with self.subTest(text=text[:30]):
                self.assertTrue(privacy.privacy_problems(text))

    def test_secrets_built_from_short_mixed_parts_are_refused(self):
        parts = ('abcd1234', 'efgh5678', 'ijkl9012', 'mnop3456', 'qrst7890')
        for text in ('-'.join(parts), '_'.join(parts), 'abcd1234efg.ijkl9012mno.qrst3456uvw',
                     'token abcd1234-efgh5678-ijkl9012-mnop3456-qrst7890 leaked'):
            with self.subTest(text=text):
                self.assertTrue(privacy.privacy_problems(text))

    def test_a_uuid_and_short_mixed_parts_in_a_name_are_accepted(self):
        for text in (SID, 'a1-b2-c3', 'step1.part2.stage3', 'long-name-with-v2-and-step3-and-part4'):
            with self.subTest(text=text):
                self.assertEqual(privacy.privacy_problems(text), [])

    def test_a_long_run_of_only_letters_or_only_digits_passes_as_a_known_gap(self):
        for text in ('q' * 40, '7' * 40):
            self.assertEqual(privacy.privacy_problems(text), [])

    def test_hex_strings_are_opaque_except_git_commit_ids(self):
        for length in (20, 24, 32, 39, 41, 63, 65):
            with self.subTest(length=length):
                self.assertTrue(privacy.privacy_problems(HEX_RUN[:length]))
        for text in (SHA1, SHA256, '0123456789ab', 'abc1234'):
            with self.subTest(text=text):
                self.assertEqual(privacy.privacy_problems(text), [])

    def test_pasted_output_is_refused(self):
        for text in ('Traceback (most recent call last):', 'File "x.py", line 3, in <module>',
                     'at Object.run (/a/b.js:10:5)', 'at com.example.Run.main(Run.java:42)',
                     'ptr 0x7ffd12345678 crashed', '\x1b[31mfailed\x1b[0m'):
            with self.subTest(text=text):
                self.assertTrue(privacy.privacy_problems(text))

    def test_each_problem_is_named_once_in_words(self):
        problems = privacy.privacy_problems('mail a@b.example and pw: example and a@c.example')
        self.assertEqual(len(problems), len(set(problems)))
        self.assertTrue(all(isinstance(p, str) and p for p in problems))


class WrapperTest(unittest.TestCase):
    def test_check_text_names_the_field_and_the_reason(self):
        for value, limit, reason in (('a\nb', 300, 'one line'), ('x ' * 20, 10, 'longer than 10'),
                                     ('mail a@b.example', 300, 'email')):
            with self.subTest(value=value):
                with self.assertRaises(RecordError) as caught:
                    privacy.check_text('sighting 1', 'text', value, limit)
                message = str(caught.exception)
                self.assertTrue(message.startswith('sighting 1: text '))
                self.assertIn(reason, message)

    def test_check_text_accepts_clean_text_and_returns_nothing(self):
        self.assertIsNone(privacy.check_text('sighting 1', 'text', 'plain wording', 300))

    def test_check_identifier_names_the_field(self):
        self.assertIsNone(privacy.check_identifier('lens 1', 'lens', 'reviewer-a'))
        with self.assertRaises(RecordError) as caught:
            privacy.check_identifier('lens 1', 'lens', 'Jane Doe')
        self.assertTrue(str(caught.exception).startswith('lens 1: lens '))


class FileTokenTest(unittest.TestCase):
    def test_an_identifier_without_a_colon_is_a_file_token(self):
        self.assertIsNone(privacy.check_file_token('lens tally', 'session', SID))
        self.assertIsNone(privacy.check_file_token('lens tally', 'session', 'my-repo.v2_a'))

    def test_a_colon_is_refused_by_name_because_it_cannot_be_part_of_a_file_name(self):
        with self.assertRaises(RecordError) as caught:
            privacy.check_file_token('lens tally', 'session', 'plugin:code')
        self.assertTrue(str(caught.exception).startswith('lens tally: session '))
        self.assertIn(':', str(caught.exception))

    def test_everything_check_identifier_refuses_is_refused_here_too(self):
        for value in ('', 'a b', 'x' * 81, '-lead'):
            with self.subTest(value=value), self.assertRaises(RecordError):
                privacy.check_file_token('lens tally', 'session', value)


class IdentifierTest(unittest.TestCase):
    def test_names_ids_and_dotted_repo_names_are_identifiers(self):
        for value in (SID, 'my-repo.v2', 'Track_Web.app', 'plugin:code-reviewer', 'a', 's-1'):
            with self.subTest(value=value):
                self.assertTrue(privacy.is_identifier(value))

    def test_blank_multiline_spaced_separator_long_or_odd_values_are_not(self):
        for value in ('', 'a b', 'x\n- injected \u00b7 line', 'a \u00b7 b', 'x' * 81, '-lead', 'a?b=c', None, 5):
            with self.subTest(value=value):
                self.assertFalse(privacy.is_identifier(value))


if __name__ == '__main__':
    unittest.main()

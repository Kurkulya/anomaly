"""The `gh` wrapper (anomaly_loop.gh): an argument list and no shell, the body on standard input, one try per call,
and an error type for every failure. `subprocess.run` is faked, so no test starts a real `gh`."""
import subprocess
import unittest
from unittest import mock

from anomaly_loop import gh

LINK = 'https://example.com/owner/repo/pull/7'


def done(stdout='', code=0, stderr=''):
    return subprocess.CompletedProcess(['gh'], code, stdout, stderr)


class GhTest(unittest.TestCase):
    def test_the_tool_runs_with_an_argument_list_no_shell_and_the_body_on_standard_input(self):
        with mock.patch('subprocess.run', return_value=done(LINK + '\n')) as run:
            link = gh.create_mr('owner/repo', 'feat(K-1): a title', 'line one\nline two', 'feat/x', 'main')
        self.assertEqual(link, LINK)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'pr', 'create'])
        self.assertIn('--draft', command)
        self.assertEqual(command[command.index('--body-file') + 1], '-')
        self.assertNotIn('line one\nline two', command)
        self.assertEqual(run.call_args.kwargs['input'], 'line one\nline two')
        self.assertFalse(run.call_args.kwargs.get('shell'))

    def test_a_body_is_replaced_through_the_rest_api_with_the_body_on_standard_input(self):
        """gh 2.46 `gh pr edit` fails on the deprecated Projects classic query; the REST call does not use it."""
        with mock.patch('subprocess.run', return_value=done('{}')) as run:
            gh.update_mr('owner/repo', 7, 'line one\nline two')
        command = run.call_args.args[0]
        self.assertEqual(command, ['gh', 'api', '--hostname', 'github.com', '-X', 'PATCH', 'repos/owner/repo/pulls/7',
                                   '-F', 'body=@-'])
        self.assertNotIn('line one\nline two', command)
        self.assertEqual(run.call_args.kwargs['input'], 'line one\nline two')
        self.assertFalse(run.call_args.kwargs.get('shell'))

    def test_a_failed_call_is_one_error_with_the_message_of_the_tool_and_is_not_repeated(self):
        with mock.patch('subprocess.run', return_value=done(code=1, stderr='HTTP 502: bad gateway')) as run:
            with self.assertRaisesRegex(gh.GhError, 'HTTP 502: bad gateway'):
                gh.ready_mr('owner/repo', 7)
        self.assertEqual(run.call_count, 1)

    def test_a_missing_tool_is_an_error_that_says_so(self):
        with mock.patch('subprocess.run', side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(gh.GhError, 'not installed'):
                gh.update_mr('owner/repo', 7, 'body')

    def test_view_reads_the_link_state_and_draft_flag_and_refuses_another_shape(self):
        answer = '{"url": "%s", "state": "OPEN", "isDraft": true, "headRefName": "feat/x"}' % LINK
        with mock.patch('subprocess.run', return_value=done(answer)):
            self.assertEqual(gh.view_mr('owner/repo', 7), (LINK, 'open', True, 'feat/x'))
        with mock.patch('subprocess.run', return_value=done('[1]')):
            with self.assertRaisesRegex(gh.GhError, 'unknown shape'):
                gh.view_mr('owner/repo', 7)


ISSUE_LINK = 'https://example.com/owner/repo/issues/42'


class GhIssueTest(unittest.TestCase):
    """The issue calls of the `upstream` port (ticket 05). Names this file chooses: `list_issues(project, prefix)`
    answers a list of (number, title); `comment_issue(project, number, body)`; `create_issue(project, title, body)`
    answers the link of the new issue."""

    def test_open_issues_are_listed_with_an_argument_list_and_read_as_number_and_title(self):
        answer = '[{"number": 3, "title": "[anomaly:observe] a"}, {"number": 5, "title": "[anomaly:facts] b"}]'
        with mock.patch('subprocess.run', return_value=done(answer)) as run:
            found = gh.list_issues('owner/repo', '[anomaly:observe]')
        self.assertEqual(found, [(3, '[anomaly:observe] a'), (5, '[anomaly:facts] b')])
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'issue', 'list'])
        self.assertEqual(command[command.index('--repo') + 1], 'owner/repo')
        self.assertEqual(command[command.index('--search') + 1], 'in:title "[anomaly:observe]"')   # M3: narrowed
        if '--state' in command:
            self.assertEqual(command[command.index('--state') + 1], 'open')
        self.assertFalse(run.call_args.kwargs.get('shell'))

    def test_an_answer_that_is_not_a_list_of_issues_is_an_error(self):
        for answer in ('{}', '[1]', '[{"number": 3}]', 'not json'):
            with self.subTest(answer=answer):
                with mock.patch('subprocess.run', return_value=done(answer)):
                    with self.assertRaises(gh.GhError):
                        gh.list_issues('owner/repo', '[anomaly:observe]')

    def test_a_comment_names_the_issue_and_the_project_and_carries_the_body_without_a_shell(self):
        with mock.patch('subprocess.run', return_value=done()) as run:
            gh.comment_issue('owner/repo', 12, '+1 from another user')
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'issue', 'comment'])
        self.assertIn('12', command)
        self.assertEqual(command[command.index('--repo') + 1], 'owner/repo')
        self.assertTrue('+1 from another user' in command or run.call_args.kwargs.get('input') == '+1 from another user')
        self.assertFalse(run.call_args.kwargs.get('shell'))

    def test_a_new_issue_is_created_from_a_body_file_and_answers_its_link(self):
        """D-18: `gh issue create --body-file`; the body is never an argument."""
        with mock.patch('subprocess.run', return_value=done(ISSUE_LINK + '\n')) as run:
            link = gh.create_issue('owner/repo', '[anomaly:observe] a', 'line one\nline two')
        self.assertEqual(link, ISSUE_LINK)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'issue', 'create'])
        self.assertEqual(command[command.index('--repo') + 1], 'owner/repo')
        self.assertEqual(command[command.index('--title') + 1], '[anomaly:observe] a')
        self.assertIn('--body-file', command)
        self.assertNotIn('line one\nline two', command)
        self.assertFalse(run.call_args.kwargs.get('shell'))

    def test_a_create_that_prints_no_link_is_an_error(self):
        with mock.patch('subprocess.run', return_value=done('created\n')):
            with self.assertRaises(gh.GhError):
                gh.create_issue('owner/repo', 'a title', 'a body')

    def test_a_failed_issue_call_is_one_error_with_the_message_of_the_tool_and_is_not_repeated(self):
        calls = (lambda: gh.list_issues('owner/repo', '[anomaly:observe]'),lambda: gh.comment_issue('owner/repo', 12, '+1'),
                 lambda: gh.create_issue('owner/repo', 'a title', 'a body'))
        for call in calls:
            with self.subTest(call=call):
                with mock.patch('subprocess.run', return_value=done(code=1, stderr='HTTP 502: bad gateway')) as run:
                    with self.assertRaisesRegex(gh.GhError, 'HTTP 502: bad gateway'):
                        call()
                self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()

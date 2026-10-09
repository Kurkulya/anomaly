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


if __name__ == '__main__':
    unittest.main()

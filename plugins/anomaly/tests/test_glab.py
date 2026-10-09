"""The CI tool wrapper (anomaly_loop.glab): an argument list and no shell, the JSON read in Python,
retries on network errors only, and an error type for every failure. `subprocess.run` is faked,
so no test starts a real CI tool or sleeps."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from anomaly_loop import constants, glab


def done(stdout='', code=0, stderr=''):
    return subprocess.CompletedProcess(['glab'], code, stdout, stderr)


class RunTest(unittest.TestCase):
    def test_the_tool_runs_with_an_argument_list_and_no_shell(self):
        with mock.patch('subprocess.run', return_value=done('{}')) as run:
            glab.run('api', 'projects/a%2Fb')
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[1:], ['api', 'projects/a%2Fb'])
        self.assertFalse(run.call_args.kwargs.get('shell'))

    def test_the_per_user_install_is_used_when_the_given_environment_names_one_and_it_is_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / 'Programs' / 'glab' / 'glab.exe'
            installed.parent.mkdir(parents=True)
            installed.write_text('', encoding='utf-8')
            self.assertEqual(glab.executable({'LOCALAPPDATA': tmp}), str(installed))
            with mock.patch('subprocess.run', return_value=done('{}')) as run:
                glab.run('api', 'x', environ={'LOCALAPPDATA': tmp})
            self.assertEqual(run.call_args.args[0][0], str(installed))

    def test_the_given_environment_is_the_one_the_tool_runs_in(self):
        with mock.patch('subprocess.run', return_value=done('{}')) as run:
            environ = {'PATH': 'p', 'GITLAB_HOST': 'example.invalid'}
            glab.run('api', 'x', environ=environ)
            self.assertEqual(run.call_args.kwargs['env'], environ)
            self.assertIsNot(run.call_args.kwargs['env'], environ)
            glab.run('api', 'x')
            self.assertIsNone(run.call_args.kwargs.get('env'))

    def test_glab_comes_from_the_path_when_the_given_environment_has_no_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / 'Programs' / 'glab' / 'glab.exe'
            installed.parent.mkdir(parents=True)
            installed.write_text('', encoding='utf-8')
            other = tempfile.mkdtemp(dir=tmp)
            with mock.patch.dict(os.environ, {'LOCALAPPDATA': tmp}):
                for environ in ({}, {'LOCALAPPDATA': other}):
                    with self.subTest(environ=environ):
                        self.assertEqual(glab.executable(environ), 'glab')

    def test_a_missing_tool_is_a_ci_error_that_says_so(self):
        with mock.patch('subprocess.run', side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(glab.CiError, 'not installed'):
                glab.run('api', 'x')

    def test_a_tool_that_cannot_start_is_a_ci_error(self):
        with mock.patch('subprocess.run', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(glab.CiError, 'denied'):
                glab.run('api', 'x')


class CallTest(unittest.TestCase):
    def setUp(self):
        self.pauses = []
        patcher = mock.patch('anomaly_loop.glab.pause', self.pauses.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def answers(self, *items):
        patcher = mock.patch('anomaly_loop.glab.run', side_effect=list(items))
        self.run = patcher.start()
        self.addCleanup(patcher.stop)

    def test_json_is_read_here(self):
        self.answers(done('[{"id": 1}]'))
        self.assertEqual(glab.api('p'), [{'id': 1}])
        self.run.assert_called_once_with('api', 'p', environ=None)

    def test_network_errors_are_retried_with_a_growing_pause_then_succeed(self):
        self.answers(done(code=1, stderr='dial tcp: i/o timeout'), done(code=1, stderr='502 Bad Gateway'),
                     done('{"ok": true}'))
        self.assertEqual(glab.api('p'), {'ok': True})
        self.assertEqual(self.pauses, [constants.CI_RETRY_SECONDS, 2 * constants.CI_RETRY_SECONDS])

    def test_network_errors_on_every_try_are_unreachable_after_exactly_the_attempts(self):
        self.answers(*[done(code=1, stderr='connection reset by peer')] * constants.CI_ATTEMPTS)
        with self.assertRaisesRegex(glab.CiUnreachable, 'connection reset'):
            glab.api('p')
        self.assertEqual(self.run.call_count, constants.CI_ATTEMPTS)
        self.assertEqual(len(self.pauses), constants.CI_ATTEMPTS - 1)

    def test_a_status_code_in_the_wording_of_the_tool_is_a_network_error_but_a_number_in_a_name_is_not(self):
        self.answers(done(code=1, stderr='glab: HTTP 503'), done('[]'))
        self.assertEqual(glab.api('p'), [])
        self.assertEqual(len(self.pauses), 1)
        self.pauses.clear()
        self.answers(done(code=1, stderr='404 Not Found: pipeline 500 does not exist'))
        with self.assertRaises(glab.CiError) as caught:
            glab.api('p')
        self.assertNotIsInstance(caught.exception, glab.CiUnreachable)
        self.assertEqual(self.pauses, [])

    def test_an_unreachable_error_is_a_ci_error_so_the_cli_always_reports_it(self):
        self.assertTrue(issubclass(glab.CiUnreachable, glab.CiError))

    def test_other_failures_are_not_retried(self):
        self.answers(done(code=1, stderr='404 Not Found'))
        with self.assertRaises(glab.CiError) as caught:
            glab.api('p')
        self.assertNotIsInstance(caught.exception, glab.CiUnreachable)
        self.assertEqual((self.run.call_count, self.pauses), (1, []))

    def test_the_failure_reason_is_one_short_line(self):
        self.answers(done(code=1, stderr='first\nsecond ' + 'x' * 500))
        with self.assertRaises(glab.CiError) as caught:
            glab.api('p')
        message = str(caught.exception)
        self.assertNotIn('\n', message)
        self.assertLess(len(message), 300)

    def test_a_success_that_is_not_json_is_a_ci_error(self):
        self.answers(done('<html>login</html>'))
        with self.assertRaisesRegex(glab.CiError, 'JSON'):
            glab.api('p')

    def test_text_returns_the_plain_output(self):
        self.answers(done('line 1\nline 2\n'))
        self.assertEqual(glab.text('p'), 'line 1\nline 2\n')


class MergeRequestTest(unittest.TestCase):
    def setUp(self):
        self.pauses = []
        patcher = mock.patch('anomaly_loop.glab.pause', self.pauses.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def answers(self, *items):
        patcher = mock.patch('anomaly_loop.glab.run', side_effect=list(items))
        self.run = patcher.start()
        self.addCleanup(patcher.stop)

    def test_create_sends_a_draft_titled_request_with_each_value_as_one_argument(self):
        self.answers(done('{"web_url": "https://example.com/g/p/-/merge_requests/7"}'))
        link = glab.create_mr('g/sub p', 'feat(K-1): t', 'line one\nline two', 'feat/x', 'main')
        self.assertEqual(link, 'https://example.com/g/p/-/merge_requests/7')
        args = self.run.call_args.args
        self.assertEqual(args[:4], ('api', 'projects/g%2Fsub%20p/merge_requests', '--method', 'POST'))
        self.assertIn('title=Draft: feat(K-1): t', args)
        self.assertIn('description=line one\nline two', args)

    def test_a_write_is_not_repeated_after_a_network_error(self):
        self.answers(done(code=1, stderr='dial tcp: i/o timeout'))
        with self.assertRaisesRegex(glab.CiError, 'timeout'):
            glab.update_mr('g/p', 7, 'body')
        self.assertEqual((self.run.call_count, self.pauses), (1, []))

    def test_ready_is_an_error_when_the_mutation_answers_errors(self):
        self.answers(done('{"data": {"mergeRequestSetDraft": {"errors": []}}}'),
                     done('{"data": {"mergeRequestSetDraft": {"errors": ["not allowed"]}}}'))
        glab.ready_mr('g/p', 7)
        with self.assertRaisesRegex(glab.CiError, 'not allowed'):
            glab.ready_mr('g/p', 7)

    def test_view_reads_the_link_state_and_draft_flag(self):
        self.answers(done('{"web_url": "u", "state": "opened", "draft": true, "source_branch": "feat/x"}'))
        self.assertEqual(glab.view_mr('g/p', 7), ('u', 'open', True, 'feat/x'))

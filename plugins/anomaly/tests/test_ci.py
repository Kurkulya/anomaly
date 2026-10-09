"""`ci watch` and `ci log`: the CI pipeline read through the CI tool's wrapper (anomaly_loop.glab), run
in-process against a temporary home and a temporary git repository. The tool is faked at the wrapper,
so no test calls a real CI tool or sleeps."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from anomaly_loop import cli
from tests.fixtures import GitFixture, assert_cli_error, run_cli, write_text

PROJECT = 'projects/group%2Fsub%2Fproject'
NETWORK_ERROR = 'Get "https://example.com/api/v4/projects": dial tcp: i/o timeout'
PASSED, FAILED, ERROR, RUNNING, DEAD, NO_PIPELINE = 0, 1, 2, 3, 4, 5


def done(stdout='', code=0, stderr=''):
    return subprocess.CompletedProcess(['glab'], code, stdout, stderr)


def answer(data):
    return done(json.dumps(data))


def job(name, status='success', allow_failure=False, duration=12.4, job_id=1):
    return {'id': job_id, 'name': name, 'status': status, 'allow_failure': allow_failure, 'duration': duration}


class FakeGlab:
    """Stands for the wrapper's `run`: answers by API path from queues (the last answer of a queue
    repeats); records every call and every pause."""

    def __init__(self):
        self.routes, self.calls, self.environs, self.pauses = {}, [], [], []

    def on(self, path, *answers):
        self.routes[path] = list(answers)

    def run(self, *args, environ=None):
        self.calls.append(args)
        self.environs.append(environ)
        queue = self.routes.get(args[-1])
        if queue is None:
            raise AssertionError(f'unexpected CI tool call: {args}')
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    def paths(self):
        return [call[-1] for call in self.calls]


class CiCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'home'
        self.home.mkdir()
        self.repo = GitFixture(self.root / 'demo')
        self.repo.write('a.txt', 'a\n')
        self.sha = self.repo.commit(['a.txt'], 'one', date(2026, 10, 1))
        self.repo.git('remote', 'add', 'origin', 'git@gitlab.com:group/sub/project.git')
        self.fake = FakeGlab()

    def use_glab(self):
        """Fake the CI tool at its wrapper; raises when the wrapper does not exist yet."""
        for target, replacement in (('anomaly_loop.glab.run', self.fake.run),
                                    ('anomaly_loop.glab.pause', self.fake.pauses.append)):
            patcher = mock.patch(target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_ci(self, value='glab'):
        write_text(self.home / 'profile.md', f'---\nci: {value}\n---\n')

    def pipeline(self, jobs_answers, pipeline_id=7, source='push'):
        """One pipeline for the repo's head commit with the job lists the poll will see in turn."""
        self.use_glab()
        self.fake.on(f'{PROJECT}/pipelines?sha={self.sha}&per_page=10', answer([{'id': pipeline_id, 'source': source}]))
        self.fake.on(f'{PROJECT}/pipelines/{pipeline_id}/jobs?per_page=100',
                     *[answer(jobs) for jobs in jobs_answers])

    def ci(self, *argv, folder=None, environ=None):
        return run_cli('ci', *argv, '--home', str(self.home), '--repo', str(folder or self.repo.root),
                       environ=environ)


class NoGateTest(CiCase):
    def test_with_no_ci_adapter_both_commands_print_no_ci_gate_and_exit_0_without_calling_anything(self):
        for action in ('watch', 'log'):
            with self.subTest(action=action):
                code, out, err = self.ci(action, 'HEAD')
                self.assertEqual((code, out.strip(), err), (0, 'no CI gate', ''))

    def test_a_placeholder_adapter_counts_as_none(self):
        self.set_ci('<your CI tool>')
        code, out, err = self.ci('watch', 'HEAD')
        self.assertEqual((code, out.strip(), err), (0, 'no CI gate', ''))

    def test_no_gate_needs_neither_a_git_repository_nor_a_valid_ref(self):
        outside = self.root / 'plain'
        outside.mkdir()
        code, out, _ = self.ci('watch', 'no-such-ref', folder=outside)
        self.assertEqual((code, out.strip()), (0, 'no CI gate'))

    def test_an_unknown_adapter_is_one_anomaly_line_and_exit_2(self):
        self.set_ci('carrier-pigeon')
        for action in ('watch', 'log'):
            with self.subTest(action=action):
                code, out, err = self.ci(action, 'HEAD')
                assert_cli_error(self, (code, out, err), 'carrier-pigeon', 'glab')
                self.assertEqual(out, '')


class WatchTest(CiCase):
    def setUp(self):
        super().setUp()
        self.set_ci()

    def test_a_finished_green_pipeline_lists_its_jobs_and_exits_0(self):
        self.pipeline([[job('build'), job('test', duration=61.6)]])
        code, out, err = self.ci('watch', 'HEAD')
        self.assertEqual((code, err), (PASSED, ''))
        lines = out.splitlines()
        self.assertEqual(lines[0], 'pipeline 7')
        self.assertTrue(lines[1].startswith('build') and 'success' in lines[1] and lines[1].endswith('12 s'), lines[1])
        self.assertTrue(lines[2].startswith('test') and lines[2].endswith('62 s'), lines[2])

    def test_the_tool_is_called_with_an_argument_list_and_its_json_is_read_here(self):
        self.pipeline([[job('build')]])
        self.ci('watch', 'HEAD')
        self.assertEqual(self.fake.calls, [
            ('api', f'{PROJECT}/pipelines?sha={self.sha}&per_page=10'),
            ('api', f'{PROJECT}/pipelines/7/jobs?per_page=100')])

    def test_the_merge_request_pipeline_of_the_commit_is_used_over_a_newer_push_pipeline(self):
        self.use_glab()
        self.fake.on(f'{PROJECT}/pipelines?sha={self.sha}&per_page=10',
                     answer([{'id': 9, 'source': 'push'}, {'id': 8, 'source': 'merge_request_event'}]))
        self.fake.on(f'{PROJECT}/pipelines/8/jobs?per_page=100', answer([job('test')]))
        code, out, _ = self.ci('watch', 'HEAD')
        self.assertEqual((code, out.splitlines()[0]), (PASSED, 'pipeline 8'))

    def test_a_blocking_failed_job_exits_1_and_a_failed_allow_failure_job_does_not(self):
        self.pipeline([[job('build'), job('e2e', 'failed')]])
        self.assertEqual(self.ci('watch', 'HEAD')[0], FAILED)
        self.fake.on(f'{PROJECT}/pipelines/7/jobs?per_page=100',
                     answer([job('build'), job('lint', 'failed', allow_failure=True)]))
        code, out, _ = self.ci('watch', 'HEAD')
        self.assertEqual(code, PASSED)
        self.assertIn('failed (allow_failure)', out)

    def test_it_polls_until_no_job_is_active_then_exits_by_the_result(self):
        self.pipeline([[job('build', 'running')], [job('build', 'running')], [job('build', 'success')]])
        code, out, _ = self.ci('watch', 'HEAD')
        self.assertEqual(code, PASSED)
        self.assertEqual(self.fake.pauses, [30, 30])
        self.assertIn('success', out)

    def test_a_pipeline_still_running_at_the_time_limit_exits_3_and_says_to_run_it_again(self):
        self.pipeline([[job('build', 'pending')]])
        code, out, err = self.ci('watch', 'HEAD', '--max-min', '1')
        self.assertEqual((code, err), (RUNNING, ''))
        self.assertIn('still running', out)
        self.assertEqual(self.fake.pauses, [30, 30])

    def test_a_pipeline_given_by_number_needs_neither_git_nor_a_remote(self):
        outside = self.root / 'plain'
        outside.mkdir()
        self.use_glab()
        self.fake.on(f'{PROJECT}/pipelines/42/jobs?per_page=100', answer([job('build')]))
        code, out, _ = self.ci('watch', '42', '--pipeline', '--project', 'group/sub/project', folder=outside)
        self.assertEqual((code, out.splitlines()[0]), (PASSED, 'pipeline 42'))

    def test_a_watch_reports_the_job_statuses_and_never_reads_a_trace(self):
        self.pipeline([[job('e2e', 'failed', job_id=5)]])
        code, out, _ = self.ci('watch', 'HEAD')
        self.assertEqual(code, FAILED)
        self.assertIn('e2e', out)
        self.assertFalse([path for path in self.fake.paths() if path.endswith('/trace')])

    def test_a_job_that_did_not_succeed_and_is_not_allowed_to_fail_blocks_whatever_its_status(self):
        for status in ('failed', 'canceled', 'manual', 'something-new'):
            with self.subTest(status=status):
                self.pipeline([[job('build'), job('deploy', status)]])
                code, out, _ = self.ci('watch', 'HEAD')
                self.assertEqual(code, FAILED)
                self.assertIn(status, out)

    def test_success_and_skipped_pass_and_an_allowed_failure_of_any_kind_does_not_block(self):
        self.pipeline([[job('build'), job('docs', 'skipped'), job('lint', 'canceled', allow_failure=True),
                        job('deploy', 'manual', allow_failure=True)]])
        self.assertEqual(self.ci('watch', 'HEAD')[0], PASSED)

    def test_a_running_job_is_still_running_not_blocking(self):
        self.pipeline([[job('build'), job('deploy', 'manual'), job('test', 'running')]])
        self.assertEqual(self.ci('watch', 'HEAD', '--max-min', '0')[0], RUNNING)

    def test_a_pipeline_held_by_a_blocking_manual_job_is_blocked_not_running(self):
        for later in ('created', 'scheduled'):
            with self.subTest(later=later):
                self.pipeline([[job('build'), job('deploy', 'manual'), job('verify', later)]])
                for action in ('watch', 'log'):
                    code, out, _ = self.ci(action, 'HEAD')
                    self.assertEqual(code, FAILED)
                    self.assertNotIn('still running', out)
                self.assertEqual(self.fake.pauses, [])

    def test_a_manual_job_that_may_fail_does_not_hold_the_pipeline(self):
        self.pipeline([[job('build'), job('deploy', 'manual', allow_failure=True), job('verify', 'created')]])
        self.assertEqual(self.ci('watch', 'HEAD', '--max-min', '0')[0], RUNNING)

    def test_a_blocking_manual_job_beside_a_job_that_is_working_is_still_running(self):
        for working in ('running', 'pending', 'preparing', 'waiting_for_resource'):
            with self.subTest(working=working):
                self.pipeline([[job('deploy', 'manual'), job('test', working), job('verify', 'created')]])
                self.assertEqual(self.ci('watch', 'HEAD', '--max-min', '0')[0], RUNNING)

    def test_a_commit_with_no_pipeline_yet_has_its_own_exit_code_and_says_so_without_an_error_line(self):
        self.use_glab()
        self.fake.on(f'{PROJECT}/pipelines?sha={self.sha}&per_page=10', answer([]))
        for action in ('watch', 'log'):
            with self.subTest(action=action):
                code, out, err = self.ci(action, 'HEAD')
                self.assertEqual((code, err), (NO_PIPELINE, ''))
                self.assertTrue(out.startswith('no pipeline yet for ') and out.count('\n') == 1, out)

    def test_a_pipeline_list_in_an_unknown_shape_is_an_error_not_no_pipeline(self):
        self.use_glab()
        for data in ({'message': 'oops'}, [{'source': 'push'}], None):
            with self.subTest(data=data):
                self.fake.on(f'{PROJECT}/pipelines?sha={self.sha}&per_page=10', answer(data))
                self.assertEqual(self.ci('watch', 'HEAD')[0], ERROR)

    def test_a_digits_only_target_is_a_ref_unless_the_pipeline_option_says_it_is_a_number(self):
        self.repo.git('tag', '1234567')
        self.pipeline([[job('build')]])
        self.assertEqual(self.ci('watch', '1234567')[0], PASSED)
        self.assertEqual(self.fake.paths()[0], f'{PROJECT}/pipelines?sha={self.sha}&per_page=10')

    def test_the_pipeline_option_reads_the_target_as_a_number_and_refuses_anything_else(self):
        self.use_glab()
        self.fake.on(f'{PROJECT}/pipelines/42/jobs?per_page=100', answer([job('build')]))
        code, out, _ = self.ci('watch', '42', '--pipeline')
        self.assertEqual((code, out.splitlines()[0]), (PASSED, 'pipeline 42'))
        code, out, err = self.ci('watch', 'HEAD', '--pipeline')
        assert_cli_error(self, (code, out, err))
        self.assertEqual(out, '')

    def test_the_default_time_limit_is_about_eight_minutes_of_polls(self):
        self.pipeline([[job('build', 'running')]])
        code, _, _ = self.ci('watch', 'HEAD')
        self.assertEqual((code, len(self.fake.pauses)), (RUNNING, 16))

    def test_a_remote_that_is_not_a_known_host_asks_for_the_project_and_never_prints_the_url(self):
        self.repo.git('remote', 'set-url', 'origin', 'secret-user@git.example.com:g/p.git')
        self.use_glab()
        code, out, err = self.ci('watch', 'HEAD')
        assert_cli_error(self, (code, out, err), '--project')
        self.assertEqual(out, '')
        self.assertNotIn('secret-user', err)

    def test_a_host_that_only_contains_gitlab_com_is_not_gitlab_com(self):
        self.repo.git('remote', 'set-url', 'origin', 'git@www.gitlab.com:g/p.git')
        self.use_glab()
        code, out, err = self.ci('log', 'HEAD')
        assert_cli_error(self, (code, out, err), '--project')
        self.assertEqual(self.fake.calls, [])

    def test_an_unknown_ref_is_one_anomaly_line_and_exit_2(self):
        self.use_glab()
        code, out, err = self.ci('watch', 'no-such-ref')
        assert_cli_error(self, (code, out, err), 'no-such-ref')
        self.assertEqual(out, '')


class NetworkFailureTest(CiCase):
    """A network failure never reads as green: it is retried, and a watch that gives up never exits 0."""

    def setUp(self):
        super().setUp()
        self.set_ci()
        self.jobs_path = f'{PROJECT}/pipelines/7/jobs?per_page=100'

    def test_a_network_error_is_retried_and_the_watch_goes_on(self):
        self.pipeline([[job('build')]])
        self.fake.on(self.jobs_path, done(code=1, stderr=NETWORK_ERROR), answer([job('build')]))
        code, out, _ = self.ci('watch', 'HEAD')
        self.assertEqual(code, PASSED)
        self.assertEqual(self.fake.paths().count(self.jobs_path), 2)
        self.assertEqual(len(self.fake.pauses), 1)

    def test_a_network_error_in_the_middle_of_a_watch_is_retried_too(self):
        self.pipeline([[job('build', 'running')]])
        self.fake.on(self.jobs_path, answer([job('build', 'running')]), done(code=1, stderr=NETWORK_ERROR),
                     answer([job('build', 'failed')]))
        self.assertEqual(self.ci('watch', 'HEAD')[0], FAILED)

    def test_a_tool_that_never_answers_gives_up_with_its_own_exit_code_never_0(self):
        self.pipeline([[job('build')]])
        self.fake.on(self.jobs_path, done(code=1, stderr=NETWORK_ERROR))
        for action in ('watch', 'log'):
            with self.subTest(action=action):
                code, out, err = self.ci(action, 'HEAD')
                self.assertEqual(code, DEAD)
                self.assertNotIn('success', out)
                self.assertTrue(err.startswith('anomaly: ') and err.count('\n') == 1, err)
                self.assertIn('i/o timeout', err)
        self.assertGreater(self.fake.paths().count(self.jobs_path), 2)

    def test_a_failure_that_is_not_the_network_is_not_retried_and_exits_2(self):
        self.pipeline([[job('build')]])
        self.fake.on(self.jobs_path, done(code=1, stderr='glab: 401 Unauthorized'))
        code, out, err = self.ci('watch', 'HEAD')
        assert_cli_error(self, (code, out, err), '401')
        self.assertEqual(out, '')
        self.assertEqual(self.fake.paths().count(self.jobs_path), 1)
        self.assertEqual(self.fake.pauses, [])

    def test_an_answer_that_is_not_json_or_not_a_job_list_is_an_error_never_green(self):
        self.pipeline([[job('build')]])
        for text in ('', 'not json', '{"message": "oops"}', 'null'):
            with self.subTest(text=text):
                self.fake.on(self.jobs_path, done(text))
                code, out, err = self.ci('watch', 'HEAD')
                assert_cli_error(self, (code, out, err))
                self.assertEqual(out, '')

    def test_a_job_without_an_id_is_an_error_not_a_trace_read_of_job_none(self):
        self.pipeline([[job('build')]])
        broken = job('test', 'failed')
        del broken['id']
        self.fake.on(self.jobs_path, answer([broken]))
        code, out, err = self.ci('log', 'HEAD')
        assert_cli_error(self, (code, out, err))
        self.assertEqual(out, '')
        self.assertFalse([path for path in self.fake.paths() if path.endswith('/trace')])

    def test_an_empty_job_list_is_not_green(self):
        self.pipeline([[]])
        assert_cli_error(self, self.ci('watch', 'HEAD'), 'no jobs')


class LogTest(CiCase):
    def setUp(self):
        super().setUp()
        self.set_ci()

    def test_a_log_reads_the_pipeline_once_without_waiting_and_exits_like_a_watch(self):
        self.pipeline([[job('build', 'running')]])
        code, out, _ = self.ci('log', 'HEAD')
        self.assertEqual((code, self.fake.pauses), (RUNNING, []))
        self.assertIn('running', out)
        self.fake.on(f'{PROJECT}/pipelines/7/jobs?per_page=100', answer([job('build')]))
        self.assertEqual(self.ci('log', 'HEAD')[0], PASSED)

    def test_a_log_prints_the_failure_lines_of_every_failed_job_without_colours_and_timestamps(self):
        trace = '\n'.join(['2026-10-01T10:00:00.000000Z 00O step_script',
                           '2026-10-01T10:00:01.000000Z 01E \x1b[31m FAIL \x1b[0m src/a.test.ts > adds',
                           ' Test Files  1 failed (1)', 'plain output line',
                           'ERROR: Job failed: exit code 1'])
        self.pipeline([[job('build'), job('test', 'failed', job_id=5)]])
        self.fake.on(f'{PROJECT}/jobs/5/trace', done(trace))
        code, out, _ = self.ci('log', 'HEAD')
        self.assertEqual(code, FAILED)
        self.assertIn('--- test (job 5) ---', out)
        self.assertIn('FAIL  src/a.test.ts > adds', out)
        self.assertIn(' Test Files  1 failed (1)', out)
        self.assertIn('ERROR: Job failed: exit code 1', out)
        self.assertNotIn('\x1b', out)
        self.assertNotIn('2026-10-01T', out)
        self.assertNotIn('plain output line', out)
        self.assertNotIn('step_script', out)

    def test_a_log_shows_at_most_forty_failure_lines_per_job(self):
        self.pipeline([[job('test', 'failed', job_id=5)]])
        self.fake.on(f'{PROJECT}/jobs/5/trace', done(''.join(f' FAIL  case {n}\n' for n in range(60))))
        out = self.ci('log', 'HEAD')[1]
        self.assertEqual(out.count(' FAIL '), 40)

    def test_a_green_pipeline_reads_no_trace(self):
        self.pipeline([[job('build')]])
        self.ci('log', 'HEAD')
        self.assertFalse([path for path in self.fake.paths() if path.endswith('/trace')])

    def test_a_trace_that_cannot_be_read_is_one_note_per_job_and_the_exit_code_stays_the_jobs(self):
        self.pipeline([[job('test', 'failed', job_id=5), job('e2e', 'failed', job_id=6)]])
        self.fake.on(f'{PROJECT}/jobs/5/trace', done(code=1, stderr='glab: 404 Not Found'))
        self.fake.on(f'{PROJECT}/jobs/6/trace', done(code=1, stderr=NETWORK_ERROR))
        code, out, err = self.ci('log', 'HEAD')
        self.assertEqual(code, FAILED)
        self.assertEqual(err, '')
        notes = [line for line in out.splitlines() if line.startswith('note:')]
        self.assertEqual(len(notes), 2, out)
        self.assertIn('test', notes[0])
        self.assertIn('404', notes[0])
        self.assertIn('e2e', notes[1])

    def test_the_environment_of_the_command_reaches_the_tool_wrapper(self):
        self.pipeline([[job('test', 'failed', job_id=5)]])
        self.fake.on(f'{PROJECT}/jobs/5/trace', done(' FAIL  a\n'))
        environ = {'LOCALAPPDATA': 'somewhere'}
        self.ci('log', 'HEAD', environ=environ)
        self.assertEqual(len(self.fake.environs), 3)
        self.assertTrue(all(one == environ for one in self.fake.environs), self.fake.environs)


class UsageTest(CiCase):
    def help_text(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main([*argv, '--help'], environ={})
        return out.getvalue()

    def test_ci_is_registered_once_with_a_watch_and_a_log_action(self):
        self.assertEqual(cli.COMMANDS.count('ci'), 1)
        text = self.help_text('ci')
        self.assertIn('watch', text)
        self.assertIn('log', text)

    def test_the_help_documents_every_exit_code(self):
        for action in ('watch', 'log'):
            with self.subTest(action=action):
                text = self.help_text('ci', action)
                for code in ('0', '1', '2', '3', '4', '5'):
                    self.assertRegex(text, rf'(?m)^\s*{code}\s')

    def test_the_help_of_watch_promises_about_the_time_limit_not_a_hard_bound(self):
        text = ' '.join(self.help_text('ci', 'watch').split())
        self.assertIn('about', text)
        self.assertNotIn('at most', text)

    def test_a_missing_target_is_one_anomaly_line_and_exit_2(self):
        code, out, err = run_cli('ci', 'watch', '--home', str(self.home))
        assert_cli_error(self, (code, out, err))
        self.assertEqual(out, '')

    def test_the_time_limit_must_be_a_finite_number_of_minutes_or_more(self):
        self.set_ci()
        self.use_glab()
        for value in ('inf', '1e400', 'nan', '-1', 'soon'):
            with self.subTest(value=value):
                code, out, err = self.ci('watch', 'HEAD', f'--max-min={value}')
                assert_cli_error(self, (code, out, err))
                self.assertEqual(out, '')

    def test_watch_has_no_failures_option_because_a_log_is_read_only_through_ci_log(self):
        code, out, err = self.ci('watch', 'HEAD', '--failures')
        assert_cli_error(self, (code, out, err))
        self.assertEqual(out, '')

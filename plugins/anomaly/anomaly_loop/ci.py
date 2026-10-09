"""`ci watch` and `ci log`: read the CI pipeline of a commit through the `ci` port.

The port's adapter comes from ports.resolve (profile only). No adapter prints "no CI gate" and
exits 0, before anything else runs; a value that is not in constants.CI_ADAPTERS is an error
(never guessed). The CI tool is called only through glab.py, with argument lists, and its JSON is
read here. A pipeline is found by commit (or ref) in the project of the `origin` remote, or, with
`--pipeline`, by its number; the newest merge request pipeline of the commit wins over a newer
branch pipeline, which runs only the static checks. `ci watch` reports job statuses; the failure
lines of a job trace are read only through `ci log`.

A job that is not active and is not allowed to fail must have succeeded (or been skipped): a
failed, canceled or blocked (manual) job is a red pipeline, whatever its status word. A blocking
manual job with nothing working (only `created` or `scheduled` jobs behind it) holds the pipeline
for a person: that is red too, not "still running", so a watch neither waits nor reads it as green.

Exit codes (EXIT_CODES is the help text):
  0 passed   1 a blocking job did not succeed   2 error (an `anomaly:` line)   3 still running
  4 the CI tool did not answer after the retries (a dead watch): never 0
  5 no pipeline for the commit yet: nothing to gate, which is not an error (a plain message)
The time limit of `ci watch` counts polls, not the clock (handlers never read it), so it is
"about" the minutes asked for: the time of the tool calls comes on top.
"""
import argparse
import math
import re
import sys
from urllib.parse import quote

from . import constants, gitrepo, glab, paths, ports
from .files import RecordError

NO_GATE = 'no CI gate'
ACTIVE = frozenset({'created', 'pending', 'running', 'preparing', 'waiting_for_resource', 'scheduled'})
WORKING = frozenset({'pending', 'running', 'preparing', 'waiting_for_resource'})   # a runner has or wants the job
SETTLED_OK = frozenset({'success', 'skipped'})   # a settled job that does not block, with allow_failure aside
PIPELINE_NUMBER = re.compile(r'[0-9]+')
COLOUR = re.compile(r'\x1b\[[0-9;]*m')
RUNNER_STAMP = re.compile(r'^\S+Z \d+[OE] ?')     # the runner's timestamp and stream prefix on a trace line
FAILURE_LINE = re.compile(r' FAIL |Failed Tests|Test Files |Tests {2}|✘|\d+\) \[|ERROR: Job failed')

EXIT_CODES = f"""exit codes:
  {constants.CI_PASSED}  every blocking job succeeded (or was skipped); also: no CI gate
  {constants.CI_FAILED}  a blocking job did not succeed: it failed, was canceled, or is manual and holds the pipeline
  2  an error: one `anomaly:` line (unknown adapter, a tool failure that is not the network, an unknown answer)
  {constants.CI_RUNNING}  a job is still running: run the command again
  {constants.CI_DEAD}  the CI tool did not answer after {constants.CI_ATTEMPTS} tries (a dead watch): one `anomaly:` line, never green
  {constants.CI_NO_PIPELINE}  no pipeline for the commit yet: a plain message, not an error; push, then run it again
"""


class NoPipeline(Exception):
    """The commit has no pipeline yet."""


def is_active(jobs):
    return any(job['status'] in ACTIVE for job in jobs)


def is_held(jobs):
    """True when a blocking manual job holds the pipeline: no job is working, so the jobs that are
    still `created` or `scheduled` wait behind it for a person, not for the runners."""
    return (any(not job.get('allow_failure') and job['status'] == 'manual' for job in jobs)
            and not any(job['status'] in WORKING for job in jobs))


def is_waiting(jobs):
    """True when a job is active and the pipeline is not held: running again later can change the result."""
    return is_active(jobs) and not is_held(jobs)


def blocking_bad(jobs):
    """True when a settled job that may not fail did not succeed (failed, canceled, blocked, unknown)."""
    return any(not job.get('allow_failure') and job['status'] not in ACTIVE | SETTLED_OK for job in jobs)


def pick_pipeline(pipelines):
    """The id of the newest merge request pipeline in `pipelines` (newest first), else of the newest one."""
    chosen = next((one for one in pipelines if one.get('source') == 'merge_request_event'), pipelines[0])
    return chosen['id']


def format_job(job):
    allow = ' (allow_failure)' if job.get('allow_failure') else ''
    duration = job.get('duration')
    seconds = '-' if duration is None else f'{int(duration + 0.5)} s'
    return ' '.join([job['name'].ljust(22), f'{job["status"]}{allow}'.ljust(30), seconds])


def failure_lines(trace):
    """The summary and failure lines of a job trace, without colour codes and runner timestamps."""
    lines = (RUNNER_STAMP.sub('', line) for line in COLOUR.sub('', trace).split('\n'))
    return [line for line in lines if FAILURE_LINE.search(line)]


def remote_project(repo):
    """The `group/project` path of the repository's `origin` remote when it is on gitlab.com (never printed with
    the URL); no origin, another host or a URL with no host is the error that asks for `--project`."""
    try:
        found = gitrepo.origin_host_project(repo)
    except gitrepo.GitError:
        found = None
    if found is None or found[0] != glab.HOST:
        raise gitrepo.GitError('cannot read the project from the origin remote: pass --project <group/project>')
    return found[1]


def locate(args, environ):
    """(project API path, pipeline id) of the target: a commit or ref, or with --pipeline a number."""
    if args.pipeline and not PIPELINE_NUMBER.fullmatch(args.target):
        raise glab.CiError(f'--pipeline needs a pipeline number, not {args.target!r}')
    repo = None if args.project and args.pipeline else gitrepo.repo_for(args.repo)   # a number in a named project needs no git
    api = f'projects/{quote(args.project or remote_project(repo), safe="")}'
    if args.pipeline:
        return api, int(args.target)
    sha = gitrepo.require_commit(repo, args.target)
    pipelines = glab.api(f'{api}/pipelines?sha={sha}&per_page=10', environ)
    if not isinstance(pipelines, list) or not all(isinstance(one, dict) and 'id' in one for one in pipelines):
        raise glab.CiError(f'the CI tool answered a pipeline list in an unknown shape for {gitrepo.short(sha)}')
    if not pipelines:
        raise NoPipeline(f'no pipeline yet for {gitrepo.short(sha)}: push first, or retry in a few seconds')
    return api, pick_pipeline(pipelines)


def read_jobs(api, pipeline, environ):
    """The jobs of the pipeline; an answer that is not a list of jobs is an error, never a green pipeline."""
    jobs = glab.api(f'{api}/pipelines/{pipeline}/jobs?per_page=100', environ)
    if not isinstance(jobs, list) or not all(isinstance(job, dict) and {'id', 'name', 'status'} <= job.keys()
                                             for job in jobs):
        raise glab.CiError(f'pipeline {pipeline}: the CI tool answered a job list in an unknown shape')
    if not jobs:
        raise glab.CiError(f'pipeline {pipeline} has no jobs')
    return jobs


def print_failures(api, jobs, environ):
    """The failure lines of each failed job; a trace that cannot be read is one note, not a new exit code."""
    for job in (job for job in jobs if job['status'] == 'failed'):
        print(f'\n--- {job["name"]} (job {job["id"]}) ---')
        try:
            trace = glab.text(f'{api}/jobs/{job["id"]}/trace', environ)
        except glab.CiError as error:
            print(f'note: the log of job {job["name"]} ({job["id"]}) could not be read: {error}')
            continue
        for line in failure_lines(trace)[:constants.CI_TRACE_LINES]:
            print(line)


def look(args, environ, polls, failures):
    """Print the pipeline (waiting up to `polls` polls while a job is active) and return the exit code."""
    api, pipeline = locate(args, environ)
    jobs = read_jobs(api, pipeline, environ)
    for _ in range(polls):
        if not is_waiting(jobs):
            break
        glab.pause(constants.CI_POLL_SECONDS)
        jobs = read_jobs(api, pipeline, environ)
    print(f'pipeline {pipeline}')
    for job in jobs:
        print(format_job(job))
    if failures:
        print_failures(api, jobs, environ)
    if is_waiting(jobs):
        print('still running: run again to keep waiting')
        return constants.CI_RUNNING
    return constants.CI_FAILED if blocking_bad(jobs) else constants.CI_PASSED


def gate(args, environ, polls, failures):
    """Run `look` when the `ci` port has an adapter; no adapter is "no CI gate"."""
    adapter = ports.port(ports.resolve(paths.resolve_home(args.home, environ)), 'ci')
    if adapter.is_default:
        print(NO_GATE)
        return constants.CI_PASSED
    if adapter.value not in constants.CI_ADAPTERS:
        raise RecordError(f'profile key ci: unknown CI adapter {adapter.value!r} '
                          f'(accepted: {", ".join(constants.CI_ADAPTERS)})')
    try:
        return look(args, environ, polls, failures)
    except glab.CiUnreachable as error:
        print(f'anomaly: ci {args.action}: {error}', file=sys.stderr)
        return constants.CI_DEAD
    except NoPipeline as error:
        print(error)
        return constants.CI_NO_PIPELINE


def run_watch(args, environ):
    return gate(args, environ, math.ceil(args.max_min * 60 / constants.CI_POLL_SECONDS), failures=False)


def run_log(args, environ):
    return gate(args, environ, 0, failures=True)


def minutes(text):
    try:
        value = float(text)
    except ValueError:
        value = -1
    if not (math.isfinite(value) and value >= 0):
        raise argparse.ArgumentTypeError(f'{text!r} is not a finite number of minutes (0 or more)')
    return value


# ---------- the ci subcommand ----------

def register(commands, common):
    command = commands.add_parser('ci', help='watch the CI pipeline of a commit, or read its failure log')
    actions = command.add_subparsers(dest='action', required=True, metavar='action')

    def action(name, handler, help_text):
        parser = actions.add_parser(name, parents=[common], help=help_text, description=help_text,
                                    epilog=EXIT_CODES, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument('target', help='a commit or a ref (with --pipeline: a pipeline number); a commit uses '
                                           'its newest merge request pipeline, else its newest pipeline')
        parser.add_argument('--pipeline', action='store_true', help='the target is a pipeline number')
        parser.add_argument('--project', help='the group/project path (default: read from the origin remote)')
        parser.add_argument('--repo', help=gitrepo.REPO_HELP)
        parser.set_defaults(handler=handler)
        return parser

    watch = action('watch', run_watch, 'list the jobs, waiting while one is running for about --max-min '
                                       'minutes, and exit by the result')
    watch.add_argument('--max-min', dest='max_min', type=minutes, default=constants.CI_DEFAULT_MAX_MIN,
                       help=f'wait for about this many minutes (default {constants.CI_DEFAULT_MAX_MIN}, under a '
                            'foreground command limit; the time of the tool calls comes on top; use a larger '
                            'value for a background run)')
    action('log', run_log, 'list the jobs once, with the failure lines of each failed job')

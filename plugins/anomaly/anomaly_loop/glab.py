"""The one place the plugin runs the CI tool (the `glab` adapter of the `ci` port), beside gitrepo.py,
the one place it runs git, and in the same style: every call is a subprocess with an argument list
(never a shell string), and a failure raises an error the CLI prints as `anomaly: <message>` (exit 2).
The merge request calls of the `glab` adapter of the `mr` port are at the end of this file.

The tool's JSON is read here, in Python. A call that fails with a network error is retried
(constants.CI_ATTEMPTS tries); when every try fails the error is CiUnreachable, which `ci watch`
and `ci log` turn into their own exit code, so that a dead watch can never read as a green
pipeline. Any other failure is a plain CiError and is not retried. Nothing here reads the clock:
the pause between tries is `pause`, so tests replace it.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

from . import constants

# What a failed call says when the network, not the request, is at fault (timeouts, resets, DNS,
# TLS, and the gateway statuses). Unverified against glab's own wording: a failure it does not
# match is a plain CiError, which also never reads as green, only without the retries.
NETWORK_ERROR = re.compile(
    r'time(?:d)?[ -]?out|deadline exceeded|connection (?:refused|reset|closed|aborted)|no such host|dial tcp'
    r'|network is unreachable|temporary failure|name resolution|tls handshake|\beof\b|broken pipe'
    r'|\bHTTP[ /]?(?:429|5\d\d)\b|bad gateway|service unavailable|gateway time-?out|too many requests'
    r'|internal server error',
    re.IGNORECASE)
REASON_MAX_CHARS = 200


class CiError(Exception):
    """The CI tool is missing, failed, or answered something that is not usable."""


class CiUnreachable(CiError):
    """The CI tool kept failing with network errors on every try."""


ERROR = CiError                      # the error of this adapter, as `mr` names it for every MR adapter


def executable(environ=None):
    """The glab program: on Windows the per-user install folder when glab is there, else `glab` on
    PATH. `environ` is the environment the tool runs in; the install is looked up in it too
    (default: the process's)."""
    local = (os.environ if environ is None else environ).get('LOCALAPPDATA')
    if local:
        installed = Path(local) / 'Programs' / 'glab' / 'glab.exe'
        if installed.is_file():
            return str(installed)
    return 'glab'


def run(*args, environ=None):
    """Run `glab <args>` in `environ` (a copy of it as the tool's environment; default: the process's);
    returns the completed process (text output, UTF-8). A non-zero exit is not an error here: call()
    reads it."""
    try:
        return subprocess.run([executable(environ), *args], capture_output=True, text=True,
                              encoding='utf-8', errors='replace',
                              env=None if environ is None else dict(environ))
    except FileNotFoundError:
        raise CiError('glab is not installed or not on PATH') from None
    except OSError as error:
        raise CiError(f'cannot run glab: {error}') from None


def pause(seconds):
    time.sleep(seconds)


def reason(done):
    """What a failed call said, on one line and cut short."""
    text = ' '.join((done.stderr or done.stdout or f'exit code {done.returncode}').split())
    return text[:REASON_MAX_CHARS]


def call(path, environ=None):
    """The output text of `glab api <path>`, with network errors retried."""
    detail = ''
    for attempt in range(1, constants.CI_ATTEMPTS + 1):
        done = run('api', path, environ=environ)
        if done.returncode == 0:
            return done.stdout
        detail = reason(done)
        if not NETWORK_ERROR.search(detail):
            raise CiError(f'glab api failed: {detail}')
        if attempt < constants.CI_ATTEMPTS:
            pause(constants.CI_RETRY_SECONDS * attempt)
    raise CiUnreachable(f'the CI tool did not answer after {constants.CI_ATTEMPTS} tries: {detail}')


def api(path, environ=None):
    """The JSON answer of `glab api <path>`, parsed."""
    try:
        return json.loads(call(path, environ))
    except ValueError:
        raise CiError(f'glab api {path} did not answer with JSON') from None


def text(path, environ=None):
    """The plain-text answer of `glab api <path>` (a job's trace)."""
    return call(path, environ)


# ---------- merge requests (the `glab` adapter of the `mr` port) ----------

HOST = 'gitlab.com'                  # the only origin host this adapter works with
DRAFT_PREFIX = 'Draft: '             # the REST API has no draft field: a title that starts so is a draft
READY_MUTATION = ('mutation($path: ID!, $iid: String!) '
                  '{ mergeRequestSetDraft(input: {projectPath: $path, iid: $iid, draft: false}) { errors } }')


def send(path, fields, method=None, environ=None):
    """Run `glab api <path> [--method M] -f key=value ...` once and return the answer text. A write is never
    retried (a repeat after a network error could make a second merge request); a failure is a CiError that says
    what the tool said. The values go from Python as one argument each."""
    args = ['api', path] + (['--method', method] if method else [])
    for key, value in fields:
        args += ['-f', f'{key}={value}']
    done = run(*args, environ=environ)
    if done.returncode != 0:
        raise CiError(f'glab api failed: {reason(done)}')
    return done.stdout


def mr_path(project, number=None):
    """The API path of the merge requests of `project` (`group/project`), or of one of them."""
    base = f'projects/{quote(project, safe="")}/merge_requests'
    return base if number is None else f'{base}/{number}'


def parse(answer, what):
    try:
        return json.loads(answer)
    except ValueError:
        raise CiError(f'glab api {what} did not answer with JSON') from None


def create_mr(project, title, body, source, target, environ=None):
    """Open a draft merge request in `project` from branch `source` to `target`; returns its link."""
    answer = parse(send(mr_path(project), [('source_branch', source), ('target_branch', target),
                                           ('title', DRAFT_PREFIX + title), ('description', body)],
                        method='POST', environ=environ), 'merge request create')
    if not isinstance(answer, dict) or not answer.get('web_url'):
        raise CiError('glab api did not answer a merge request with a link')
    return answer['web_url']


def update_mr(project, number, body, environ=None):
    """Replace the description of merge request `number`."""
    send(mr_path(project, number), [('description', body)], method='PUT', environ=environ)


def ready_mr(project, number, environ=None):
    """Take the draft state off merge request `number` (the GraphQL mutation `mergeRequestSetDraft`: the REST API
    can only do it by rewriting the title)."""
    answer = parse(send('graphql', [('query', READY_MUTATION), ('path', project), ('iid', number)],
                        environ=environ), 'merge request ready')
    if not isinstance(answer, dict):
        raise CiError('glab api answered the merge request change in an unknown shape')
    data = answer.get('data') if isinstance(answer.get('data'), dict) else {}
    result = data.get('mergeRequestSetDraft')
    problems = answer.get('errors') or (result.get('errors') if isinstance(result, dict) else None)
    if problems:
        raise CiError(f'glab api failed: {" ".join(json.dumps(problems).split())[:REASON_MAX_CHARS]}')
    if not isinstance(result, dict):
        raise CiError(f'glab api did not answer a result for merge request {number}: it may still be a draft')


def view_mr(project, number, environ=None):
    """(link, state, is_draft, source branch) of merge request `number`; the state is `open`, `closed`, `merged` or
    `locked`."""
    answer = api(mr_path(project, number), environ)
    try:
        return (answer['web_url'], {'opened': 'open'}.get(answer['state'], answer['state']), bool(answer['draft']),
                answer['source_branch'])
    except (KeyError, TypeError):
        raise CiError(f'glab api answered merge request {number} in an unknown shape') from None

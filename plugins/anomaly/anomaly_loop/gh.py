"""The one place the plugin runs `gh` (the `gh` adapter of the `mr` port), beside glab.py and gitrepo.py and in the
same style: every call is a subprocess with an argument list (never a shell string), and a failure raises a
GhError with the tool's own message, which `mr` turns into one `anomaly: <message>` line (exit 2).

The MR calls are `gh pr create --draft`, `gh api -X PATCH repos/<project>/pulls/<number>`, `gh pr ready` and
`gh pr view --json`. The body goes to the tool on its standard input (`--body-file -`, or `-F body=@-` for the REST
call), so it is never an argument and never a file left behind. A write is tried once: a repeat after a network error
could make a second pull request.
"""
import json
import re
import subprocess

from . import glab

HOST = 'github.com'                  # the only origin host this adapter works with
LINK = re.compile(r'https?://\S+')
PROJECT = re.compile(r'[^/\s]+/[^/\s]+')   # a GitHub project is `owner/name`; a longer path is a GitLab group shape


class GhError(Exception):
    """gh is missing, failed, or answered something that is not usable."""


ERROR = GhError                      # the error of this adapter, as `mr` names it for every MR adapter


def run(*args, environ=None, input=None):
    """Run `gh <args>` in `environ` (a copy of it as the tool's environment; default: the process's) with `input`
    as its standard input; returns the completed process (text output, UTF-8). A non-zero exit is not an error
    here: call() reads it."""
    try:
        return subprocess.run(['gh', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                              env=None if environ is None else dict(environ), input=input)
    except FileNotFoundError:
        raise GhError('gh is not installed or not on PATH') from None
    except OSError as error:
        raise GhError(f'cannot run gh: {error}') from None


def call(*args, environ=None, input=None):
    """The output text of `gh <args>`; a failed call is a GhError that says what the tool said."""
    done = run(*args, environ=environ, input=input)
    if done.returncode != 0:
        raise GhError(f'gh failed: {glab.reason(done)}')
    return done.stdout


def check_project(project):
    """Refuse a project that is not exactly `owner/name`, before any call."""
    if not PROJECT.fullmatch(project):
        raise GhError(f'the origin project "{project}" is not owner/name, the only shape the gh adapter works with')


def create_mr(project, title, body, source, target, environ=None):
    """Open a draft pull request in `project` from branch `source` to `target`; returns its link."""
    check_project(project)
    out = call('pr', 'create', '--repo', project, '--draft', '--title', title, '--head', source, '--base', target,
               '--body-file', '-', environ=environ, input=body)
    links = LINK.findall(out)
    if not links:
        raise GhError('gh pr create did not print the link of the pull request')
    return links[-1]


def update_mr(project, number, body, environ=None):
    """Replace the body of pull request `number`, through the REST API. `gh pr edit` is not used: on gh 2.46 it fails
    on the deprecated Projects classic GraphQL query, which the REST call does not make. `-F body=@-` reads the body
    from standard input."""
    check_project(project)
    call('api', '--hostname', HOST, '-X', 'PATCH', f'repos/{project}/pulls/{number}', '-F', 'body=@-',
         environ=environ, input=body)


def ready_mr(project, number, environ=None):
    """Mark pull request `number` ready for review."""
    check_project(project)
    call('pr', 'ready', str(number), '--repo', project, environ=environ)


def view_mr(project, number, environ=None):
    """(link, state, is_draft, source branch) of pull request `number`; the state is `open`, `closed` or `merged`."""
    check_project(project)
    out = call('pr', 'view', str(number), '--repo', project, '--json', 'url,state,isDraft,headRefName', environ=environ)
    try:
        answer = json.loads(out)
        return answer['url'], answer['state'].lower(), bool(answer['isDraft']), answer['headRefName']
    except (ValueError, KeyError, TypeError, AttributeError):
        raise GhError(f'gh answered pull request {number} in an unknown shape') from None

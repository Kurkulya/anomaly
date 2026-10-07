"""The one place the plugin runs the CI tool (the `glab` adapter of the `ci` port), beside gitrepo.py,
the one place it runs git, and in the same style: every call is a subprocess with an argument list
(never a shell string), and a failure raises an error the CLI prints as `anomaly: <message>` (exit 2).

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

"""Report the commit this service was built from."""
import subprocess

from . import auth
from .routes import send_json


def handle_version(handler, query):
    if not auth.require_session(handler):
        return
    done = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True)
    send_json(handler, 200, {'commit': done.stdout.strip()})

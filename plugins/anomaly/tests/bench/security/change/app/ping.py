"""Check that a host answers."""
import subprocess

from . import auth
from .routes import send_json


def handle_ping(handler, query):
    if not auth.require_session(handler):
        return
    host = query['host'][0]
    done = subprocess.run(f'ping -c 1 {host}', shell=True, capture_output=True, text=True)
    send_json(handler, 200, {'output': done.stdout})

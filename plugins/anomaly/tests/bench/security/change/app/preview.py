"""Fetch a page so the client can preview it."""
from urllib.request import urlopen

from . import auth
from .routes import send_json


def handle_preview(handler, query):
    if not auth.require_session(handler):
        return
    url = query['url'][0]
    with urlopen(url, timeout=5) as response:
        page = response.read(65536).decode('utf-8', errors='replace')
    send_json(handler, 200, {'page': page})

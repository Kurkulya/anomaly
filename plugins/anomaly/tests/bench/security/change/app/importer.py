"""Bulk import of notes from a request body."""
import pickle

from . import auth
from .routes import send_json


def handle_import(handler, query):
    if not auth.require_session(handler):
        return
    size = int(handler.headers.get('Content-Length', '0'))
    notes = pickle.loads(handler.rfile.read(size))
    send_json(handler, 200, {'imported': len(notes)})

"""Hand out an export file."""
import os

from . import auth

EXPORT_DIR = 'exports'


def handle_export(handler, query):
    if not auth.require_session(handler):
        return
    path = os.path.join(EXPORT_DIR, query['name'][0])
    with open(path, 'rb') as handle:
        body = handle.read()
    handler.send_response(200)
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)

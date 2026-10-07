"""The routes every deployment has, and the helper that sends a JSON answer."""
import json

from . import auth, db


def send_json(handler, status, payload):
    body = json.dumps(payload).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_health(handler, query):
    send_json(handler, 200, {'ok': True})


def handle_note(handler, query):
    if not auth.require_session(handler):
        return
    note = db.find_note(db.connect(), int(query['id'][0]))
    send_json(handler, 200 if note else 404, {'note': note})

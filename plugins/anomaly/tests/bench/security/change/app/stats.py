"""Counts for the status page."""
from . import db
from .routes import send_json


def handle_stats(handler, query):
    conn = db.connect()
    total = conn.execute('SELECT COUNT(*) FROM notes').fetchone()[0]
    send_json(handler, 200, {'notes': total})

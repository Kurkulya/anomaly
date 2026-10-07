"""Search the notes by a word in the title."""
from . import auth, db
from .routes import send_json


def handle_search(handler, query):
    if not auth.require_session(handler):
        return
    word = query['q'][0]
    sql = f"SELECT id, title FROM notes WHERE title LIKE '%{word}%'"
    rows = db.connect().execute(sql).fetchall()
    send_json(handler, 200, {'notes': rows})

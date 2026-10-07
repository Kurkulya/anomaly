"""Add a note."""
from . import auth, db, webhook
from .routes import send_json

NOTE_COLUMNS = ('title', 'body')


def insert_note(conn, values):
    """Insert one note; `values` follows NOTE_COLUMNS."""
    marks = ', '.join('?' for _ in NOTE_COLUMNS)
    conn.execute(f'INSERT INTO notes ({", ".join(NOTE_COLUMNS)}) VALUES ({marks})', values)
    conn.commit()


def handle_add(handler, query):
    if not auth.require_session(handler):
        return
    insert_note(db.connect(), [query['title'][0], query['body'][0]])
    webhook.notify({'title': query['title'][0]})
    send_json(handler, 201, {'ok': True})

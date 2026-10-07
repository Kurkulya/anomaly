"""The notes table."""
import sqlite3

DATABASE = 'notes.db'


def connect():
    return sqlite3.connect(DATABASE)


def find_note(conn, note_id):
    """One note by id, or None."""
    return conn.execute('SELECT id, title, body FROM notes WHERE id = ?', (note_id,)).fetchone()

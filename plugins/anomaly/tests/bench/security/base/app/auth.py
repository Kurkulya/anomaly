"""The session check that every route except the health check calls first."""

SESSIONS = set()


def is_valid(session_id):
    """True when `session_id` was issued by a sign-in and is still held."""
    return session_id in SESSIONS


def require_session(handler):
    """Answer 401 and return False when the request carries no valid session."""
    if not is_valid(handler.headers.get('X-Session', '')):
        handler.send_error(401)
        return False
    return True

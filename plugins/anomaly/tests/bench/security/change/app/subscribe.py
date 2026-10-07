"""Let a member ask for the weekly summary."""
import logging

from . import auth
from .routes import send_json

log = logging.getLogger(__name__)


def handle_subscribe(handler, query):
    if not auth.require_session(handler):
        return
    email = query['email'][0]
    log.info('weekly summary requested for %s', email)
    send_json(handler, 200, {'subscribed': True})

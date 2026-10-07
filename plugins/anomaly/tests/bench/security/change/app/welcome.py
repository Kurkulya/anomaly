"""A welcome page."""
import html

from . import auth


def handle_welcome(handler, query):
    if not auth.require_session(handler):
        return
    name = html.escape(query['name'][0])
    page = f'<html><body><h1>Welcome {name}</h1></body></html>'.encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(page)))
    handler.end_headers()
    handler.wfile.write(page)

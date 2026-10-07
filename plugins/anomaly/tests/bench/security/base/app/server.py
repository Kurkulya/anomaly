"""The HTTP entry point."""
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, routes

ROUTES = {
    '/health': routes.handle_health,
    '/note': routes.handle_note,
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        route = ROUTES.get(parsed.path)
        if route is None:
            self.send_error(404)
            return
        route(self, parse_qs(parsed.query))


def run():
    logging.basicConfig(level=logging.DEBUG if config.DEBUG else logging.INFO)
    HTTPServer((config.HOST, config.PORT), Handler).serve_forever()

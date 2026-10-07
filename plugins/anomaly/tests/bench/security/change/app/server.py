"""The HTTP entry point."""
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import (config, exports, hello, importer, notes, ping, preview, routes, search, stats, subscribe, version,
               welcome)

GET_ROUTES = {
    '/health': routes.handle_health,
    '/note': routes.handle_note,
    '/search': search.handle_search,
    '/add': notes.handle_add,
    '/ping': ping.handle_ping,
    '/version': version.handle_version,
    '/export': exports.handle_export,
    '/preview': preview.handle_preview,
    '/stats': stats.handle_stats,
    '/subscribe': subscribe.handle_subscribe,
    '/hello': hello.handle_hello,
    '/welcome': welcome.handle_welcome,
}
POST_ROUTES = {
    '/import': importer.handle_import,
}


class Handler(BaseHTTPRequestHandler):
    def answer(self, table):
        parsed = urlparse(self.path)
        route = table.get(parsed.path)
        if route is None:
            self.send_error(404)
            return
        route(self, parse_qs(parsed.query))

    def do_GET(self):
        self.answer(GET_ROUTES)

    def do_POST(self):
        self.answer(POST_ROUTES)


def run():
    logging.basicConfig(level=logging.DEBUG if config.DEBUG else logging.INFO)
    HTTPServer((config.HOST, config.PORT), Handler).serve_forever()

"""Settings read from config/app.ini."""
import configparser

_parser = configparser.ConfigParser()
_parser.read('config/app.ini')

HOST = _parser.get('server', 'host', fallback='127.0.0.1')
PORT = _parser.getint('server', 'port', fallback=8080)
DEBUG = _parser.getboolean('server', 'debug', fallback=False)

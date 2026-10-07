"""Tell the partner service about a new note."""
import json
import ssl
from urllib.request import Request, urlopen

PARTNER_URL = 'https://partner.example.com/hooks/notes'


def notify(note):
    """Post `note` to the partner service and return the HTTP status."""
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    request = Request(PARTNER_URL, data=json.dumps(note).encode('utf-8'),
                      headers={'Content-Type': 'application/json'})
    return urlopen(request, context=context, timeout=5).status

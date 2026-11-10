"""Owner-only outbound WhatsApp via the pinned Hermes loopback bridge.

No session keys are read here. A failed POST is ambiguous and must never be
automatically retried; only failures established before sending are retryable.
"""
import json
from pathlib import Path
import re
import urllib.error
import urllib.request

CONFIG = Path('/var/lib/personal-agent-data/whatsapp.json')
SESSION = '/var/lib/personal-agent/.hermes/whatsapp/session'
BASE = 'http://127.0.0.1:3000'


class WhatsAppUnavailable(Exception):
    seconds = 60


class WhatsApp:
    def __init__(self, config=CONFIG):
        self.config = Path(config)

    def send(self, text, nonce, image_url=None):
        try:
            config = json.loads(self.config.read_text())
            jid = config['owner_jid']
            if not config.get('enabled') or not re.fullmatch(r'[1-9][0-9]{6,14}@s\.whatsapp\.net', jid):
                raise ValueError('Invalid owner routing')
            # Never adopt a different profile/account's bridge on this port.
            with urllib.request.urlopen(BASE+'/health', timeout=5) as response:
                health = json.load(response)
            if health.get('status') != 'connected' or health.get('session') != SESSION:
                raise ValueError('Expected WhatsApp session is unavailable')
        except (OSError, ValueError, KeyError, TypeError):
            raise WhatsAppUnavailable('WhatsApp is not connected; no send attempted') from None
        if image_url:
            # Keep remote downloads out of the privileged transport. Native
            # Hermes replies can attach images; outbox updates include the link.
            text += '\n'+image_url
        body = json.dumps({'chatId':jid, 'message':text}).encode()
        request = urllib.request.Request(BASE+'/send', data=body,
            headers={'Content-Type':'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                result = json.load(response)
        except (OSError, ValueError):
            raise RuntimeError('WhatsApp send outcome unconfirmed; reconcile before retry') from None
        if not result.get('success') or not result.get('messageId'):
            raise RuntimeError('WhatsApp send acknowledgement missing; reconcile before retry')
        return str(result['messageId'])


def status():
    """Credential-free status for the private monitor, not the phone number."""
    try:
        config = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return {'state':'not_paired'}
    if not config.get('enabled'):
        return {'state':'disabled'}
    try:
        with urllib.request.urlopen(BASE+'/health', timeout=2) as response:
            health = json.load(response)
        state = health.get('status','unavailable') if health.get('session') == SESSION else 'wrong_session'
    except (OSError, ValueError):
        state = 'disconnected'
    return {'state':state, 'mode':config.get('mode'), 'scope':'owner messages and forwards'}

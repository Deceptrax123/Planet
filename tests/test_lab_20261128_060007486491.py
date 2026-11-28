import io
import json
import unittest
from unittest.mock import patch

from app import whatsapp_delivery as delivery


class WhatsAppJsonShapeTests(unittest.TestCase):
    malformed = (None, [], 'text', 0, True)
    config = {
        'enabled': True,
        'owner_jid': '12345678901@s.whatsapp.net',
        'mode': 'owner',
    }

    def health(self, **changes):
        value = {'status': 'connected', 'session': delivery.SESSION}
        value.update(changes)
        return value

    def mock_transport(self, values):
        remaining = iter(values)

        def respond(*args, **kwargs):
            return io.StringIO(json.dumps(next(remaining)))

        return patch.object(delivery.urllib.request, 'urlopen', side_effect=respond)

    def assert_requests(self, opened, methods):
        self.assertEqual(opened.call_count, len(methods))
        actual = []
        for call in opened.call_args_list:
            request = call.args[0]
            if isinstance(request, str):
                self.assertEqual(request, delivery.BASE + '/health')
                actual.append('GET')
            else:
                self.assertEqual(request.full_url, delivery.BASE + '/send')
                actual.append(request.get_method())
        self.assertEqual(actual, methods)

    def test_invalid_send_configuration_never_contacts_bridge(self):
        for value in self.malformed:
            with self.subTest(value=value):
                with patch.object(delivery.Path, 'read_text', return_value=json.dumps(value)):
                    with self.mock_transport([]) as opened:
                        with self.assertRaisesRegex(delivery.WhatsAppUnavailable, 'no send attempted'):
                            delivery.WhatsApp().send('hello', 'nonce')
                        self.assert_requests(opened, [])

    def test_invalid_health_never_posts(self):
        for value in self.malformed:
            with self.subTest(value=value):
                with patch.object(delivery.Path, 'read_text', return_value=json.dumps(self.config)):
                    with self.mock_transport([value]) as opened:
                        with self.assertRaisesRegex(delivery.WhatsAppUnavailable, 'no send attempted'):
                            delivery.WhatsApp().send('hello', 'nonce')
                        self.assert_requests(opened, ['GET'])

    def test_invalid_acknowledgement_requires_reconciliation_after_one_post(self):
        for value in self.malformed:
            with self.subTest(value=value):
                with patch.object(delivery.Path, 'read_text', return_value=json.dumps(self.config)):
                    with self.mock_transport([self.health(), value]) as opened:
                        with self.assertRaisesRegex(RuntimeError, 'reconcile before retry'):
                            delivery.WhatsApp().send('hello', 'nonce')
                        self.assert_requests(opened, ['GET', 'POST'])

    def test_invalid_status_configuration_is_not_paired(self):
        for value in self.malformed:
            with self.subTest(value=value):
                with patch.object(delivery.Path, 'read_text', return_value=json.dumps(value)):
                    with self.mock_transport([]) as opened:
                        self.assertEqual(delivery.status(), {'state': 'not_paired'})
                        self.assert_requests(opened, [])

    def test_invalid_status_health_is_disconnected(self):
        for value in self.malformed:
            with self.subTest(value=value):
                with patch.object(delivery.Path, 'read_text', return_value=json.dumps(self.config)):
                    with self.mock_transport([value]) as opened:
                        self.assertEqual(delivery.status(), {
                            'state': 'disconnected',
                            'mode': 'owner',
                            'scope': 'owner messages and forwards',
                        })
                        self.assert_requests(opened, ['GET'])

    def test_successful_delivery_preserves_payload_and_message_id(self):
        with patch.object(delivery.Path, 'read_text', return_value=json.dumps(self.config)):
            with self.mock_transport([self.health(), {'success': True, 'messageId': 'message-1'}]) as opened:
                self.assertEqual(delivery.WhatsApp().send('hello', 'nonce'), 'message-1')
                self.assert_requests(opened, ['GET', 'POST'])
                request = opened.call_args_list[1].args[0]
                self.assertEqual(json.loads(request.data), {
                    'chatId': self.config['owner_jid'], 'message': 'hello',
                })

    def test_connected_and_wrong_session_status_controls(self):
        for session, expected in ((delivery.SESSION, 'connected'), ('other-session', 'wrong_session')):
            with self.subTest(expected=expected):
                with patch.object(delivery.Path, 'read_text', return_value=json.dumps(self.config)):
                    with self.mock_transport([self.health(session=session)]) as opened:
                        self.assertEqual(delivery.status(), {
                            'state': expected,
                            'mode': 'owner',
                            'scope': 'owner messages and forwards',
                        })
                        self.assert_requests(opened, ['GET'])

    def test_wrong_session_blocks_delivery(self):
        with patch.object(delivery.Path, 'read_text', return_value=json.dumps(self.config)):
            with self.mock_transport([self.health(session='other-session')]) as opened:
                with self.assertRaises(delivery.WhatsAppUnavailable):
                    delivery.WhatsApp().send('hello', 'nonce')
                self.assert_requests(opened, ['GET'])

    def test_disabled_configuration_controls(self):
        config = dict(self.config, enabled=False)
        with patch.object(delivery.Path, 'read_text', return_value=json.dumps(config)):
            with self.mock_transport([]) as opened:
                self.assertEqual(delivery.status(), {'state': 'disabled'})
                with self.assertRaises(delivery.WhatsAppUnavailable):
                    delivery.WhatsApp().send('hello', 'nonce')
                self.assert_requests(opened, [])


if __name__ == '__main__':
    unittest.main()

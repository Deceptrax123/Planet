from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
import importlib.util
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from assistant_store import Store
from reminder_scheduler import Scheduler
from whatsapp_delivery import WhatsApp, WhatsAppUnavailable, SESSION

spec=importlib.util.spec_from_file_location('configure_whatsapp',Path(__file__).resolve().parents[1]/'configure-whatsapp.py')
setup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class PairingRecognitionTests(unittest.TestCase):
    def test_signed_qr_account_is_recognized_when_legacy_registered_flag_is_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'creds.json').write_text(json.dumps({'registered':False,'account':{'test':'signed-account'},'me':{'id':'919876543210:4@s.whatsapp.net'}}))
            with patch.object(setup,'SESSION',root):
                self.assertEqual(setup.linked_phone(),'919876543210')

    def test_flag_without_signed_identity_is_not_a_completed_pairing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'creds.json').write_text(json.dumps({'registered':True}))
            with patch.object(setup,'SESSION',root):self.assertIsNone(setup.linked_phone())


class WhatsAppDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name)
        self.when=datetime(2026,11,9,5,tzinfo=timezone.utc)
        self.discord=Mock();self.discord.send.return_value='discord-message'
        self.whatsapp=Mock();self.whatsapp.send.return_value='whatsapp-message'
        self.scheduler=Scheduler(self.store,self.discord,self.whatsapp)

    def tearDown(self):
        self.tmp.cleanup()

    def reminder(self, channel='whatsapp'):
        return self.store.add_reminder('Meetup deadline',self.when.isoformat(),'owner request','test-key',delivery_channel=channel)

    def test_channels_are_isolated_and_default_stays_discord(self):
        self.reminder()
        self.scheduler.tick(self.when)
        self.whatsapp.send.assert_called_once();self.discord.send.assert_not_called()
        self.scheduler.tick(self.when+timedelta(seconds=15))
        self.whatsapp.send.assert_called_once()
        with self.assertRaises(ValueError):self.reminder('discord')

    def test_disconnected_bridge_waits_without_falling_back_or_losing_reminder(self):
        self.reminder()
        self.whatsapp.send.side_effect=WhatsAppUnavailable()
        self.scheduler.tick(self.when)
        with self.store.connect() as db:
            self.assertEqual(db.execute('select status from outbox').fetchone()[0],'retry')
        self.discord.send.assert_not_called()
        self.whatsapp.send.side_effect=None
        self.scheduler.tick(self.when+timedelta(seconds=61))
        self.assertEqual(self.store.reminders()[0]['status'],'sent')

    def test_uncertain_send_is_never_blindly_repeated(self):
        self.reminder()
        self.whatsapp.send.side_effect=RuntimeError('WhatsApp send outcome unconfirmed')
        self.scheduler.tick(self.when)
        self.scheduler.tick(self.when+timedelta(minutes=5))
        self.whatsapp.send.assert_called_once()
        with self.store.connect() as db:
            self.assertEqual(db.execute('select status from outbox').fetchone()[0],'ambiguous')

    def test_preexisting_reminder_and_outbox_migrate_to_discord(self):
        self.reminder('discord')
        # Simulate the prior schema without dropping the actual reminder.
        with self.store.connect() as db:
            db.execute('alter table reminders drop column delivery_channel')
            db.execute('alter table outbox drop column delivery_channel')
        migrated=Store(self.tmp.name)
        self.assertEqual(migrated.reminders()[0]['delivery_channel'],'discord')

    def config(self):
        path=Path(self.tmp.name)/'whatsapp.json'
        path.write_text(json.dumps({'enabled':True,'owner_jid':'919876543210@s.whatsapp.net'}))
        return path

    def response(self,payload):
        import io
        return io.BytesIO(json.dumps(payload).encode())

    def test_foreign_bridge_is_rejected_before_send(self):
        with patch('whatsapp_delivery.urllib.request.urlopen',return_value=self.response({'status':'connected','session':'/another/account'})) as call:
            with self.assertRaises(WhatsAppUnavailable):WhatsApp(self.config()).send('Test','nonce')
        self.assertEqual(call.call_count,1)

    def test_recipient_is_always_configured_owner(self):
        with patch('whatsapp_delivery.urllib.request.urlopen',side_effect=[self.response({'status':'connected','session':SESSION}),self.response({'success':True,'messageId':'sent-id'})]) as call:
            self.assertEqual(WhatsApp(self.config()).send('Test','nonce'),'sent-id')
        body=json.loads(call.call_args.args[0].data)
        self.assertEqual(body['chatId'],'919876543210@s.whatsapp.net')

    def test_post_timeout_is_ambiguous_and_contains_no_credentials(self):
        with patch('whatsapp_delivery.urllib.request.urlopen',side_effect=[self.response({'status':'connected','session':SESSION}),TimeoutError('private response')]):
            with self.assertRaisesRegex(RuntimeError,'unconfirmed'):WhatsApp(self.config()).send('Test','nonce')


if __name__=='__main__':unittest.main()

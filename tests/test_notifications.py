from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from assistant_store import Store
from reminder_scheduler import Scheduler
UTC=timezone.utc

class Notifications(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.when=datetime(2026,11,9,5,tzinfo=UTC);self.sent=[]
  class Sender:
   def send(inner,text,nonce):self.sent.append(text);return 'test-message'
  self.scheduler=Scheduler(self.store,Sender())
 def tearDown(self):self.temp.cleanup()
 def notify(self,key='event',at=None,priority='important',expires=None):
  at=at or self.when
  with patch('assistant_store.now_iso',return_value=at.isoformat()):
   return self.store.notify_owner('A useful test alert',key,'https://example.com/verified-event','A sourced action is due soon',(expires or at+timedelta(hours=2)).isoformat(),priority)
 def test_same_event_across_agents_delivers_once(self):
  self.assertEqual(self.notify()['status'],'queued');self.assertEqual(self.notify()['status'],'duplicate')
  self.scheduler.tick(self.when);self.scheduler.tick(self.when+timedelta(seconds=30));self.assertEqual(len(self.sent),1)
 def test_owner_authorized_outreach_can_arrive_at_night(self):
  at=datetime(2026,11,9,18,tzinfo=UTC)
  self.assertEqual(self.notify(at=at)['status'],'queued')
  self.scheduler.tick(at);self.assertEqual(len(self.sent),1)
 def test_distinct_updates_have_no_quota_or_cooldown(self):
  for n in range(7):self.assertEqual(self.notify(str(n))['status'],'queued')
  self.scheduler.tick(self.when);self.assertEqual(len(self.sent),7)
 def test_expired_alert_is_not_delivered_after_delay(self):
  self.notify();self.scheduler.tick(self.when+timedelta(hours=3));self.assertEqual(self.sent,[])
 def test_alert_crossing_2300_still_delivers(self):
  at=datetime(2026,11,9,17,29,tzinfo=UTC)
  self.notify(at=at);self.scheduler.tick(at+timedelta(minutes=2));self.assertEqual(len(self.sent),1)
 def test_casual_starters_have_no_daily_or_weekly_quota(self):
  for n in range(4):
   with patch('assistant_store.now_iso',return_value=self.when.isoformat()):
    result=self.store.notify_owner('A friendly test starter',str(n),'owner-request:proactive-conversation','Owner invited natural conversation',(self.when+timedelta(hours=1)).isoformat(),kind='conversation')
    self.assertEqual(result['status'],'queued')
 def test_private_image_addresses_rejected(self):
  with patch('assistant_store.now_iso',return_value=self.when.isoformat()):
   with self.assertRaises(ValueError):
    self.store.notify_owner('Test','image','https://example.com/event','Test',(self.when+timedelta(hours=1)).isoformat(),image_url='https://127.0.0.1/private.png')
 def test_image_embed_keeps_owner_target_and_nonce(self):
  from reminder_scheduler import Discord
  from unittest.mock import Mock
  with self.store.connect() as db:db.execute("INSERT INTO metadata VALUES ('discord_dm_channel','owner-dm')")
  sender=Discord('test-token',self.store);sender.api=Mock(return_value={'id':'message'})
  sender.send('Picture','nonce',image_url='https://example.com/picture.png')
  args=sender.api.call_args.args
  self.assertEqual(args[0],'/channels/owner-dm/messages')
  self.assertEqual(args[1]['embeds'][0]['image']['url'],'https://example.com/picture.png')
  self.assertTrue(args[1]['enforce_nonce'])

if __name__=='__main__':unittest.main()

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from research_broker import Backend
from research_remote import visible, project


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.backend=Backend(self.tmp.name)
        self.backend.report=lambda *args:None
    def tearDown(self):self.tmp.cleanup()
    def submit(self,**kwargs):
        args=dict(host='petase-design',project='/home/owner/research',prompt='Analyze test data',title='Test task',
                  owner_request='Fictional unit test request',idempotency_key='test-task',notify_completion=False)
        args.update(kwargs)
        with patch('research_broker.Path.exists',return_value=False):return self.backend.research_submit(**args)
    def test_submit_is_durable_and_idempotent(self):
        first=self.submit();second=self.submit()
        self.assertEqual(first,second)
        with self.assertRaises(ValueError):self.submit(prompt='Different experiment')
        self.assertEqual(self.backend.research_task(first['id'])['state'],'queued')
    def test_no_remote_execution_during_submission(self):
        with patch.object(self.backend,'remote',side_effect=AssertionError('must be asynchronous')):
            self.assertEqual(self.submit()['state'],'queued')
    def test_requires_owner_evidence_and_allowlisted_host(self):
        for kwargs in [dict(owner_request=''),dict(host='world-models-mahesh'),dict(engine='shell'),dict(timeout_minutes=0)]:
            with self.assertRaises(ValueError):self.submit(**kwargs)
    def test_cancellation_before_dispatch_prevents_launch(self):
        task=self.submit()
        self.backend.research_cancel(task['id'])
        with patch.object(self.backend,'remote',side_effect=AssertionError('cancelled job cannot start')):
            self.backend.tick()
        self.assertEqual(self.backend.research_task(task['id'])['state'],'cancelled')
    def test_connection_loss_never_reports_success_and_retries_are_bounded(self):
        task=self.submit()
        with patch.object(self.backend,'remote',side_effect=ValueError('login required')) as remote:
            for _ in range(5):self.backend.tick()
        self.assertEqual(remote.call_count,3)
        self.assertEqual(self.backend.research_task(task['id'])['state'],'connection_lost')
    def test_owner_identity_must_match_workforce_pool_and_subject(self):
        valid='principal://iam.googleapis.com/locations/global/workforcePools/lossfunk-researchers/subject/srinitishsri@gmail.com'
        with patch.object(self.backend,'cloud',return_value=valid):self.assertEqual(self.backend.identity(),valid)
        with patch.object(self.backend,'cloud',return_value=valid.replace('srinitishsri','Srinitishsri')):self.backend.identity()
        for wrong in [valid.replace('srinitishsri','mahesh'),valid.replace('lossfunk-researchers','other-pool')]:
            with patch.object(self.backend,'cloud',return_value=wrong):
                with self.assertRaises(ValueError):self.backend.identity()
    def test_dispatched_queue_is_distinct_and_cancelled_remotely(self):
        task=self.submit()
        with patch.object(self.backend,'remote',return_value={'state':'queued','job_id':task['id']}):self.backend.tick()
        self.assertEqual(self.backend.research_task(task['id'])['state'],'starting')
        with patch.object(self.backend,'remote',return_value={'state':'cancelled'}) as remote:
            self.backend.research_cancel(task['id'])
        self.assertEqual(remote.call_args.args[1]['action'],'cancel')
    def test_logs_exclude_hidden_reasoning_and_redact_visible_tokens(self):
        self.assertIsNone(visible({'type':'item.completed','item':{'type':'reasoning','text':'private'}}))
        self.assertIsNone(visible({'type':'assistant','message':{'content':[{'type':'thinking','thinking':'private'}]}}))
        event=visible({'type':'assistant','message':{'content':[{'type':'text','text':'access_token=secret123'}]}})
        self.assertNotIn('secret123',event['text'])
    def test_completion_alert_is_retried_and_only_acknowledged_when_queued(self):
        task=self.submit(notify_completion=True)
        with patch.object(self.backend,'remote',return_value={'state':'done'}),patch('research_broker.request',side_effect=ValueError('temporary unavailable')):
            self.backend.tick()
        with patch('research_broker.request',return_value={'status':'queued'}) as send:
            self.backend.tick();self.backend.tick()
        self.assertEqual(send.call_count,1)
    def test_project_rejects_credentials_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as home:
            root=Path(home);(root/'project').mkdir();(root/'.ssh').mkdir();(root/'escape').symlink_to('/tmp')
            with patch('research_remote.Path.home',return_value=root):
                self.assertEqual(project(str(root/'project')),root/'project')
                for p in [root,root/'.ssh',root/'escape']:
                    with self.assertRaises(ValueError):project(str(p))


if __name__=='__main__':unittest.main()

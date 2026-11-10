import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import mission_control as m


class LogTests(unittest.TestCase):
    def test_visible_events_only_and_secret_redaction(self):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);logs=home/'codex/sessions';logs.mkdir(parents=True)
            path=logs/'test.jsonl'
            rows=[{'type':'response_item','payload':{'type':'reasoning','summary':[{'text':'HIDDEN'}]}},
                  {'type':'response_item','payload':{'type':'message','role':'assistant','channel':'analysis','content':[{'type':'output_text','text':'HIDDEN'}]}},
                  {'type':'response_item','payload':{'type':'message','role':'assistant','channel':'final','content':[{'type':'output_text','text':'Visible answer'}]}},
                  {'type':'response_item','payload':{'type':'function_call','name':'test','arguments':'{"authorization":"Bearer abcdefghijklmnopqrstuvwxyz"}'}},
                  {'type':'event_msg','payload':{'type':'task_complete'}}]
            path.write_text('\n'.join(json.dumps(r) for r in rows))
            with patch.object(m,'HOME',home):
                events=m.tail_events(path)
                self.assertEqual(len(events),3)
                text=json.dumps(events)
                self.assertNotIn('HIDDEN',text)
                self.assertNotIn('abcdefghijklmnopqrstuvwxyz',text)
                self.assertIn('Visible answer',text)
                outside=home/'auth.json';outside.write_text('{}')
                self.assertEqual(m.tail_events(outside),[])

    def test_parent_graph_and_completion_are_from_actual_events(self):
        row={'id':'test','source':json.dumps({'subagent':{'thread_spawn':{'parent_thread_id':'parent'}}}),'rollout_path':'path','title':'Test','agent_role':'research','model':'gpt-6.1-sol'}
        with patch.object(m,'thread_rows',return_value=[row]),patch.object(m,'tail_events',return_value=[{'kind':'task_started'},{'kind':'task_complete'}]):
            item=m.threads()[0]
        self.assertEqual(item['parent_id'],'parent');self.assertEqual(item['state'],'done')

    def test_invalid_log_id_cannot_select_a_file(self):
        with self.assertRaises(ValueError):m.logs('../../auth.json')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();p=Path(self.temp.name)/'password';p.write_text('test-password')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),m.Handler)
        self.port=self.server.server_address[1]
        self.patches=[patch.object(m,'PORT',self.port),patch.object(m,'PASSWORD',p)]
        for patcher in self.patches:patcher.start()
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for patcher in self.patches:patcher.stop()
        self.temp.cleanup()

    def call(self,path,headers=None,data=None):
        headers=headers or {}
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}'+path,headers=headers,data=data)
        try:
            with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,None

    def auth(self):return {'Authorization':'Basic '+base64.b64encode(b'ji-eun:test-password').decode()}

    def test_private_api_requires_authentication(self):
        self.assertEqual(self.call('/api/state')[0],401)
        with patch.object(m,'snapshot',return_value={'ok':True}):
            self.assertEqual(self.call('/api/state',self.auth()),(200,{'ok':True}))

    def test_rebinding_host_and_cross_origin_controls_rejected(self):
        h=self.auth();h['Host']='attacker.example';self.assertEqual(self.call('/api/state',h)[0],403)
        self.assertEqual(self.call('/api/control',self.auth(),b'{"action":"pause"}')[0],403)

    def test_only_unprivileged_fixed_controls_allowed(self):
        h=self.auth();h['Origin']=f'http://127.0.0.1:{self.port}'
        with patch.object(m.subprocess,'run') as run:
            self.assertEqual(self.call('/api/control',h,b'{"action":"stop"}')[0],400)
            run.assert_not_called()


if __name__=='__main__':unittest.main()

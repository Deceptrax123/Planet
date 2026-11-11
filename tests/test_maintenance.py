import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
service=load('maintenance_service',ROOT/'maintenance/service.py')

class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.backend=service.Backend(self.root)
        self.data={'id':'c_'+'a'*24,'digest':'source-a','base_release':'initial','state':'ready','test_passed':True,'protected_changes':[],'changed_files':['app/a.py'],'reviews':[]}
        self.backend.save(self.data)
    def review(self,reviewer,thread,verdict='approve'):
        return self.backend.review(self.data['id'],reviewer,'gpt-6.1-sol',thread,verdict,'Inspected exact source and its regression coverage.')
    def test_paths_cannot_escape_or_touch_credentials(self):
        for path in ['../app/x.py','/etc/sudoers','app/../control.py','app//x.py','app/./x.py','.ssh/key.pem','.hermes/config.yaml','app/x.key']:
            with self.subTest(path=path),self.assertRaises(ValueError):service.source_path(path)
    def test_root_code_and_stdlib_shadow_modules_cannot_deploy(self):
        for path in ['app/control.py','app/backup.py','app/shared_sync.py','app/subprocess.py','app/pathlib.py','app/sitecustomize.py','maintenance/service.py','systemd/root.service']:
            self.assertIsNone(service.destination(path))
        self.assertEqual(service.destination('app/capability.py'),service.PREFIX/'app/capability.py')
    def test_two_real_distinct_reviews_required(self):
        self.review('ji-an','a'*32)
        with self.assertRaises(ValueError):self.backend.deploy(self.data['id'])
        self.review('sol-reviewer','a'*32) # same native thread replaces earlier attestation
        self.assertEqual(len(self.backend.load(self.data['id'])['reviews']),1)
        self.review('ji-an','b'*32)
        result=self.backend.deploy(self.data['id']);self.assertEqual(result['state'],'queued')
    def test_rejection_failed_checks_and_stale_source_block_deploy(self):
        self.review('ji-an','a'*32);self.review('sol-reviewer','b'*32,'request_changes')
        with self.assertRaises(ValueError):self.backend.deploy(self.data['id'])
        self.review('sol-reviewer','b'*32)
        for field,value in [('test_passed',False),('protected_changes',['maintenance/service.py']),('base_release','other')]:
            data=self.backend.load(self.data['id']);original=data[field];data[field]=value;self.backend.save(data)
            with self.assertRaises(ValueError):self.backend.deploy(self.data['id'])
            data[field]=original;self.backend.save(data)
    def test_reviews_are_bound_to_source_digest(self):
        self.review('ji-an','a'*32);self.review('sol-reviewer','b'*32)
        data=self.backend.load(self.data['id']);data['digest']='different';self.backend.save(data)
        with self.assertRaises(ValueError):self.backend.deploy(self.data['id'])
    def test_restart_recovers_both_deploy_and_rollback_directions(self):
        for restore_new in [False,True]:
            journal={'candidate_id':self.data['id'],'changes':[{'path':'app/a.py','old':'old','new':'new'}],'previous':{'id':'previous'},'restore_new':restore_new}
            service.atomic(self.root/'transaction.json',json.dumps(journal))
            with patch.object(service.Backend,'write_targets') as write,patch.object(service.Backend,'restart'),patch.object(service.Backend,'stop'),patch.object(service.Backend,'wait_health'):
                backend=service.Backend(self.root)
            write.assert_called_once_with(journal['changes'],rollback=not restore_new)
            self.assertEqual(backend.active['id'],'previous');self.assertFalse((self.root/'transaction.json').exists())
    def test_health_failure_restores_previous_code_and_metadata(self):
        service.atomic(self.root/'candidates'/self.data['id']/'changes.json',json.dumps([{'path':'app/a.py','old':'old','new':'new'}]))
        self.backend.active={'id':self.data['id']};self.data['state']='rollback_queued';self.backend.save(self.data)
        with patch.object(self.backend,'idle',return_value=True),patch.object(self.backend,'health',side_effect=[False]*75+[True]),patch.object(self.backend,'restart'),patch.object(self.backend,'stop') as stop,patch.object(self.backend,'write_targets') as writes,patch.object(self.backend,'report'),patch.object(service.subprocess,'run'),patch.object(service.time,'sleep'):
            with self.assertRaises(ValueError):self.backend.apply(self.data['id'],rollback=True)
        self.assertEqual(stop.call_count,2)
        self.assertEqual(writes.call_args_list[0].args[1],True)
        self.assertEqual(writes.call_args_list[1].kwargs['rollback'],False)
        self.assertEqual(self.backend.active['id'],self.data['id'])
        self.assertEqual(self.backend.load(self.data['id'])['state'],'deployed')
    def test_queued_rollback_rechecks_active_release_before_stopping(self):
        self.data['state']='rollback_queued';self.backend.save(self.data)
        service.atomic(self.root/'candidates'/self.data['id']/'changes.json','[]')
        self.backend.active={'id':'newer-release'}
        with patch.object(self.backend,'idle',return_value=True),patch.object(self.backend,'stop') as stop:
            with self.assertRaisesRegex(ValueError,'stale'):self.backend.apply(self.data['id'],rollback=True)
        stop.assert_not_called()
    def test_queued_operations_preserve_pending_recovery_journal(self):
        # A prior release already failed to restore. Another job was queued earlier.
        journal={'candidate_id':self.data['id'],'changes':[{'path':'app/a.py','old':'known-good','new':'bad'}],'previous':{'id':'initial'}}
        text=json.dumps(journal);service.atomic(self.root/'transaction.json',text)
        for rollback in [False,True]:
            with patch.object(self.backend,'stop') as stop,patch.object(self.backend,'idle',return_value=True):
                with self.assertRaisesRegex(ValueError,'Pending recovery'):self.backend.apply(self.data['id'],rollback=rollback)
            stop.assert_not_called();self.assertEqual((self.root/'transaction.json').read_text(),text)
        result=self.backend.recover_pending();self.assertTrue(result['queued'])
        self.assertEqual(self.backend.jobs.get_nowait(),('recover',self.data['id']))
    def test_owner_stop_prevents_deployment_and_health_restart(self):
        (self.root/'OWNER_STOPPED').write_text('Owner stop')
        self.assertFalse(self.backend.idle())
        with self.assertRaisesRegex(ValueError,'Owner stopped'):self.backend.deploy(self.data['id'])
        with patch.object(service.subprocess,'run') as command:
            with self.assertRaisesRegex(ValueError,'owner stopped'):self.backend.restart()
        command.assert_not_called()
    def test_real_process_is_replaced_when_failed_release_is_restored(self):
        import subprocess,time
        root=self.root;source=root/'app/capability.py';source.parent.mkdir();source.write_text('old')
        observed=root/'observed';processes=[]
        class ProcessBackend(service.Backend):
            def stop(inner):
                for process in processes:
                    if process.poll() is None:process.terminate();process.wait(timeout=5)
            def restart(inner):
                observed.unlink(missing_ok=True)
                process=subprocess.Popen([service.sys.executable,'-I','-c',
                    'from pathlib import Path;import os,time;value=Path('+repr(str(source))+').read_text();Path('+repr(str(observed))+').write_text(value+":"+str(os.getpid()));time.sleep(30)'])
                processes.append(process)
            def write_targets(inner,changes,rollback=False):source.write_text(changes[0]['old' if rollback else 'new'])
            def idle(inner):return True
            def wait_health(inner):
                for _ in range(100):
                    if observed.exists():break
                    time.sleep(.01)
                else:raise ValueError('Fixture process did not start')
                if observed.read_text().startswith('new:'):raise ValueError('Reject fixture release')
            def report(inner,*args,**kwargs):pass
        backend=ProcessBackend(root);backend.restart();backend.wait_health();first=observed.read_text()
        service.atomic(root/'candidates'/self.data['id']/'changes.json',json.dumps([{'path':'app/capability.py','old':'old','new':'new'}]))
        try:
            with patch.object(service,'PREFIX',root):
                with self.assertRaisesRegex(ValueError,'Reject fixture'):backend.apply(self.data['id'])
            self.assertTrue(observed.read_text().startswith('old:'));self.assertNotEqual(first,observed.read_text())
            self.assertEqual(source.read_text(),'old');self.assertEqual(backend.active['id'],'initial')
            self.assertIsNotNone(processes[-2].poll())
            self.assertFalse((root/'transaction.json').exists())
        finally:backend.stop()
    def test_symlink_deployment_target_rejected(self):
        prefix=self.root/'prefix';(prefix/'app').mkdir(parents=True);(prefix/'app/a.py').symlink_to(self.root/'elsewhere')
        # Ownership validation also rejects this fixture when the tests are nonroot.
        with patch.object(service,'PREFIX',prefix),self.assertRaises(ValueError):self.backend.write_targets([{'path':'app/a.py','old':None,'new':'x'}])

if __name__=='__main__':unittest.main()

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
import assistant_mcp as mcp
from assistant_store import Store

class ValidationTests(unittest.TestCase):
    def test_invalid_values_never_reach_broker(self):
        cases=[('memory_record',{'topic':'routine','text':'test','source':'unit test','confirmed':'false'}),
               ('memory_record',{'topic':'routine','text':'test','source':'unit test','confidence':float('nan')}),
               ('memory_record',{'topic':'routine','text':'test','source':'unit test','confidence':float('inf')}),
               ('memory_record',{'topic':'routine','text':'test','source':'unit test','recurrence':{'weekdays':[True]}}),
               ('memory_record',{'topic':'routine','text':'test','source':'unit test','recurrence':{'weekdays':[7]}}),
               ('memory_context',{'query':'test','limit':True}),('memory_context',{'query':'test','limit':31}),
               ('reminder_list',[]),('reminder_list',None)]
        with patch.object(mcp,'request') as broker:
            for name,args in cases:
                with self.subTest(name=name,args=args),self.assertRaises(ValueError):mcp.handle({'method':'tools/call','params':{'name':name,'arguments':args}})
            broker.assert_not_called()
    def test_valid_nested_arguments_reach_broker_unchanged(self):
        args={'topic':'routine','text':'Test routine','source':'Unit test','confirmed':False,'confidence':0.5,'recurrence':{'weekdays':[0,6]}}
        with patch.object(mcp,'request',return_value={}) as broker:
            mcp.handle({'method':'tools/call','params':{'name':'memory_record','arguments':args}})
        broker.assert_called_once_with('memory_record',args)
    def test_store_rejects_truthy_strings(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with self.assertRaises(ValueError):store.remember('routine','Test','Unit test',confirmed='false')
            with self.assertRaises(ValueError):store.add_reminder('Test','2026-11-20T10:00:00Z','Unit test','key',allow_quiet='false')
    def test_non_object_jsonrpc_rejected(self):
        for value in [[],None,False,'request']:
            with self.assertRaises(ValueError):mcp.handle(value)

if __name__=='__main__':unittest.main()

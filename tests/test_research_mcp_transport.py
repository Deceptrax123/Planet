"""Regression: research tools must not inherit the short memory socket deadline."""
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import assistant_mcp
from assistant_broker import request


class ResearchTransportTests(unittest.TestCase):
    def test_probe_survives_a_slow_broker_response(self):
        with tempfile.TemporaryDirectory() as directory:
            path=directory+'/broker.sock'
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
                server.bind(path);server.listen()
                def answer():
                    with server.accept()[0] as client:
                        client.recv(10000)
                        time.sleep(.12)
                        try:client.sendall(b'{"result":{"state":"ready"}}\n')
                        except BrokenPipeError:pass
                worker=threading.Thread(target=answer);worker.start()
                def short_default(method,args=None,timeout=.03):
                    return request(method,args,socket_path=path,timeout=timeout)
                with patch('assistant_mcp.request',side_effect=short_default):
                    result=assistant_mcp.handle({'method':'tools/call','params':{'name':'research_probe','arguments':{'host':'petase-design'}}})
                worker.join(2)
                self.assertFalse(result.get('isError'),result)
                self.assertEqual(json.loads(result['content'][0]['text'])['state'],'ready')


if __name__=='__main__':unittest.main()

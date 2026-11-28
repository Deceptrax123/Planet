import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class BrokerRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Stub the dependency before loading the real facade: no broker or network.
        source = Path(__file__).resolve().parents[1] / 'app' / 'assistant_mcp.py'
        broker = types.ModuleType('assistant_broker')
        broker.request = Mock(side_effect=AssertionError('Unexpected broker call'))
        spec = importlib.util.spec_from_file_location('routing_subject', source)
        cls.subject = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'assistant_broker': broker}):
            spec.loader.exec_module(cls.subject)

    def test_routing_arguments_timeout_and_response(self):
        cases = [
            ('research_probe', {'host': 'test-host'}, {'timeout': 130}),
            ('memory_context', {'query': 'test topic'}, {}),
        ]
        for name, arguments, expected_keywords in cases:
            with self.subTest(tool=name):
                original_arguments = dict(arguments)
                result = {'ok': True, 'value': 'Unicode: café'}
                with patch.object(self.subject, 'request', return_value=result) as broker:
                    response = self.subject.handle({
                        'method': 'tools/call',
                        'params': {'name': name, 'arguments': arguments},
                    })
                broker.assert_called_once_with(name, original_arguments, **expected_keywords)
                self.assertEqual(arguments, original_arguments)
                self.assertNotIn('isError', response)
                self.assertEqual(len(response['content']), 1)
                self.assertEqual(response['content'][0]['type'], 'text')
                self.assertEqual(json.loads(response['content'][0]['text']), result)

    def test_invalid_arguments_never_reach_broker(self):
        cases = [
            ('research_probe', {}),
            ('research_probe', {'host': 123}),
            ('memory_context', {}),
            ('memory_context', {'query': 'topic', 'unexpected': True}),
        ]
        for name, arguments in cases:
            with self.subTest(tool=name, arguments=arguments):
                with patch.object(self.subject, 'request') as broker:
                    with self.assertRaises(ValueError):
                        self.subject.handle({
                            'method': 'tools/call',
                            'params': {'name': name, 'arguments': arguments},
                        })
                    broker.assert_not_called()


if __name__ == '__main__':
    unittest.main()

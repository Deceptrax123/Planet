"""Offline constructor cleanup regressions; proposed, not executed.

Claim: failures after Popen attempt independent resource cleanup while
preserving the original exception. Cleanup remains best effort; a second
wait timeout can leave the child unreaped. Live model defaults are unchanged.
"""
import subprocess
import unittest
from unittest.mock import Mock, call, patch

from app.codex_rpc import CodexRPC


class InitializationFailure(Exception):
    pass


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.process = Mock()
        self.selector = Mock()
        self.popen_patch = patch('app.codex_rpc.subprocess.Popen',
                                 return_value=self.process)
        self.selector_patch = patch('app.codex_rpc.selectors.DefaultSelector',
                                    return_value=self.selector)
        self.call_patch = patch.object(CodexRPC, 'call', return_value={})
        self.send_patch = patch.object(CodexRPC, 'send')
        self.popen = self.popen_patch.start()
        self.factory = self.selector_patch.start()
        self.rpc_call = self.call_patch.start()
        self.send = self.send_patch.start()
        for patcher in (self.popen_patch, self.selector_patch,
                        self.call_patch, self.send_patch):
            self.addCleanup(patcher.stop)

    def fail_at(self, stage, error):
        targets = {
            'selector': self.factory,
            'register': self.selector.register,
            'initialize': self.rpc_call,
            'initialized': self.send,
        }
        targets[stage].side_effect = error

    def assert_failure(self, stage='initialize'):
        original = InitializationFailure(stage)
        self.fail_at(stage, original)
        with self.assertRaises(InitializationFailure) as caught:
            CodexRPC(binary='offline-fake')
        self.assertIs(caught.exception, original)
        self.process.terminate.assert_called_once_with()
        self.process.stdin.close.assert_called_once_with()
        self.process.stdout.close.assert_called_once_with()

    def test_each_initialization_failure_releases_acquired_resources(self):
        # Separate instances prevent mock state from hiding duplicate cleanup.
        for stage in ('selector', 'register', 'initialize', 'initialized'):
            with self.subTest(stage=stage):
                self.process.reset_mock(return_value=True, side_effect=True)
                self.selector.reset_mock(return_value=True, side_effect=True)
                self.factory.reset_mock(side_effect=True)
                self.rpc_call.reset_mock(side_effect=True)
                self.send.reset_mock(side_effect=True)
                self.assert_failure(stage)
                self.process.wait.assert_called_once_with(timeout=10)
                self.process.kill.assert_not_called()
                if stage == 'selector':
                    self.selector.close.assert_not_called()
                else:
                    self.selector.close.assert_called_once_with()

    def test_selector_close_failure_does_not_prevent_process_cleanup(self):
        self.selector.close.side_effect = OSError('close failed')
        self.assert_failure()
        self.process.wait.assert_called_once_with(timeout=10)

    def test_terminate_failure_does_not_prevent_wait(self):
        self.process.terminate.side_effect = OSError('terminate failed')
        self.assert_failure()
        self.process.wait.assert_called_once_with(timeout=10)

    def test_wait_timeout_kills_and_waits_again(self):
        self.process.wait.side_effect = [
            subprocess.TimeoutExpired('offline-fake', 10), 0]
        self.assert_failure()
        self.process.kill.assert_called_once_with()
        self.assertEqual(self.process.wait.call_args_list,
                         [call(timeout=10), call(timeout=10)])

    def test_cleanup_failures_preserve_original_exception(self):
        self.selector.close.side_effect = OSError('selector failed')
        self.process.terminate.side_effect = OSError('terminate failed')
        self.process.wait.side_effect = [
            subprocess.TimeoutExpired('offline-fake', 10),
            subprocess.TimeoutExpired('offline-fake', 10)]
        self.process.kill.side_effect = OSError('kill failed')
        self.process.stdin.close.side_effect = OSError('stdin failed')
        self.assert_failure()
        self.process.kill.assert_called_once_with()
        self.assertEqual(self.process.wait.call_count, 2)

    def test_unexpected_wait_failure_preserves_original_exception(self):
        self.process.wait.side_effect = OSError('wait failed')
        self.assert_failure()

    def test_success_keeps_resources_open_and_completes_handshake(self):
        client = CodexRPC(binary='offline-fake')
        self.assertIs(client.process, self.process)
        self.selector.register.assert_called_once()
        self.rpc_call.assert_called_once_with('initialize', {
            'clientInfo': {'name': 'personal-assistant-monitor',
                           'version': '1.0.0'},
            'capabilities': {'experimentalApi': True},
        })
        self.send.assert_called_once_with(
            {'method': 'initialized', 'params': {}})
        self.selector.close.assert_not_called()
        self.process.terminate.assert_not_called()
        self.process.wait.assert_not_called()
        self.process.kill.assert_not_called()
        self.process.stdin.close.assert_not_called()
        self.process.stdout.close.assert_not_called()


if __name__ == '__main__':
    unittest.main()

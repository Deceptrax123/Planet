import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


def load_notifications():
    candidates = (
        Path(__file__).resolve().parent / 'test_notifications.py',
        Path.cwd() / 'tests' / 'test_notifications.py',
    )
    source = next((path for path in candidates if path.is_file()), None)
    if source is None:
        raise FileNotFoundError('Cannot locate tests/test_notifications.py')
    spec = importlib.util.spec_from_file_location('notifications_under_review', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ImageNonceRegression(unittest.TestCase):
    def test_image_notification_forwards_expected_nonce(self):
        module = load_notifications()
        from reminder_scheduler import Discord

        original_send = Discord.send
        observed = []

        def checked_send(sender, *args, **kwargs):
            result = original_send(sender, *args, **kwargs)
            payload = sender.api.call_args.args[1]
            observed.append(payload)
            self.assertEqual(payload['nonce'], 'nonce')
            self.assertTrue(payload['enforce_nonce'])
            return result

        case = module.Notifications('test_image_embed_keeps_owner_target_and_nonce')
        with patch.object(Discord, 'send', checked_send):
            result = unittest.TestResult()
            case.run(result)
        self.assertEqual(result.errors, [], str(result.errors))
        self.assertEqual(result.failures, [], str(result.failures))
        self.assertEqual(len(observed), 1)


if __name__ == '__main__':
    unittest.main()

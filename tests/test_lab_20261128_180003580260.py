import sys
import unittest
from pathlib import Path


class AmbiguousSendRegression(unittest.TestCase):
    def test_ambiguous_send_is_attempted_only_once(self):
        root = Path(__file__).resolve().parent
        while not (root / "tests" / "test_assistant.py").is_file():
            if root.parent == root:
                self.fail("Could not locate tests/test_assistant.py")
            root = root.parent

        import importlib.util
        source = root / "tests" / "test_assistant.py"
        spec = importlib.util.spec_from_file_location("assistant_tests_under_review", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        case = module.ReminderTests("test_ambiguous_transport_failure_is_not_blindly_retried")
        result = unittest.TestResult()
        calls = []
        previous_profile = sys.getprofile()

        def profile(frame, event, arg):
            if (event == "call" and frame.f_code.co_name == "fail"
                    and Path(frame.f_code.co_filename).resolve() == source.resolve()
                    and frame.f_code.co_qualname.endswith(
                        "test_ambiguous_transport_failure_is_not_blindly_retried.<locals>.fail")):
                calls.append(None)

        try:
            sys.setprofile(profile)
            case.run(result)
        finally:
            sys.setprofile(previous_profile)

        self.assertTrue(result.wasSuccessful(), f"Existing test failed: {result.errors + result.failures}")
        self.assertEqual(len(calls), 1, "An ambiguous send must not be attempted again")


if __name__ == "__main__":
    unittest.main()

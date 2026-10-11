import unittest

from clean_arch.application.log_policy import classify


class LogPolicyTests(unittest.TestCase):
    def test_quest_success_goes_to_quest_pane(self):
        result = classify("Квест здано (task=17384)")
        self.assertEqual(result.pane, "quest")
        self.assertEqual(result.color, "success")
        self.assertIn("ok_return", result.actions)

    def test_connection_line_stays_out_of_quest_pane(self):
        result = classify("Connected to server")
        self.assertEqual(result.pane, "connection")
        self.assertEqual(result.color, "default")

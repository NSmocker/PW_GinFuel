import struct
import unittest

from clean_arch.application.session_client import SessionClient


class SessionCorrelationTests(unittest.TestCase):
    def test_login_only_does_not_start_keepalive(self):
        events = []
        client = SessionClient("host", 1, events.append)
        client.run_login_only()
        self.assertFalse(client.stop_event.is_set())
        self.assertIn("Disconnecting", events[-1].text)

    def test_task_reply_correlation_checks_task_id_and_type(self):
        client = SessionClient("host", 1, lambda event: None)
        payload = struct.pack("<I", 3) + struct.pack("<BH", 2, 17064)
        reply = (client.GAME_CMD_TASK_NOTIFY, payload)
        self.assertTrue(client.reply_matches_task(reply, 17064))
        self.assertTrue(client.reply_confirms_task(reply, 17064, 2))
        self.assertFalse(client.reply_matches_task(reply, 17384))
        self.assertFalse(client.reply_confirms_task(reply, 17064, 1))

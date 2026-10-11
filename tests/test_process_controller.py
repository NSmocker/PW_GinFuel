import unittest

from clean_arch.domain.models import SessionMode, SessionSettings
from clean_arch.infrastructure.process_controller import WorkerProcess


class ProcessControllerTests(unittest.TestCase):
    def test_start_failure_becomes_a_gui_event(self):
        controller = WorkerProcess("worker_entry.py", "missing-directory")
        controller.start(SessionSettings("config", "credentials",
                                         SessionMode.WORLD))
        events = list(controller.poll())
        self.assertEqual(len(events), 1)
        self.assertIn("Worker start failed", events[0].text)

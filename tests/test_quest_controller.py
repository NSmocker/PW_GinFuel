import threading
import unittest

from clean_arch.application.quest_controller import QuestController


class FakeClient:
    def __init__(self):
        self.stop_event = threading.Event()
        self.nearby_npcs = {101: 22485}
        self.logs = []
        self.returned = False

    def log(self, message, ok=True):
        self.logs.append(message)

    def npc_hello(self, npc_id):
        return (70, b"")

    def task_check_finish(self, task_id):
        return None

    def task_return(self, task_id):
        self.returned = True
        return (106, b"")

    def task_accept(self, task_id):
        return None


class QuestControllerTests(unittest.TestCase):
    def test_npc_template_resolution_is_independent_of_transport(self):
        client = FakeClient()
        controller = QuestController(client, 17384, 15870,
                                      npc_template_id=22485)
        self.assertEqual(controller._resolve_npc(), 101)

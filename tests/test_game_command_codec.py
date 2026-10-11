import struct
import unittest

from clean_arch.infrastructure.game_command_codec import (
    task_accept, task_check_finish, task_matter, task_return)


class GameCommandCodecTests(unittest.TestCase):
    def test_task_commands_match_current_wire_shapes(self):
        self.assertEqual(task_return(17384),
                         struct.pack("<HiIii", 37, 6, 8, 17384, 0))
        self.assertEqual(task_accept(15870),
                         struct.pack("<HiIiii", 37, 7, 12, 15870, 0, 0))
        self.assertEqual(task_matter(17064),
                         struct.pack("<HiIi", 37, 8, 4, 17064))

    def test_check_finish_is_explicitly_packed_three_byte_variant(self):
        self.assertEqual(task_check_finish(17064),
                         struct.pack("<HIBH", 49, 3, 1, 17064))

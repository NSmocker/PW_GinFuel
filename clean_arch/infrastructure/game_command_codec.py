"""Pure serializers for the little-endian game command payloads."""

from __future__ import annotations

import struct


GAME_CMD_NPC_HELLO = 35
GAME_CMD_NPC_SERVE = 37
GAME_CMD_TASK_NOTIFY = 49
SERVICE_TASK_RETURN = 6
SERVICE_TASK_ACCEPT = 7
SERVICE_TASK_MATTER = 8
TASK_CLT_NOTIFY_CHECK_FINISH = 1


def npc_hello(npc_id: int) -> bytes:
    return struct.pack("<Hi", GAME_CMD_NPC_HELLO, npc_id)


def task_return(task_id: int, choice: int = 0) -> bytes:
    return struct.pack("<HiIii", GAME_CMD_NPC_SERVE,
                       SERVICE_TASK_RETURN, 8, task_id, choice)


def task_accept(task_id: int, storage_id: int = 0,
                refresh_item: int = 0) -> bytes:
    return struct.pack("<HiIiii", GAME_CMD_NPC_SERVE,
                       SERVICE_TASK_ACCEPT, 12, task_id, storage_id,
                       refresh_item)


def task_matter(task_id: int) -> bytes:
    return struct.pack("<HiIi", GAME_CMD_NPC_SERVE,
                       SERVICE_TASK_MATTER, 4, task_id)


def task_check_finish(task_id: int) -> bytes:
    """Serialize the currently deployed packed native-compatible format.

    The upstream documentation describes a four-byte base structure, while
    the deployed client currently uses the packed three-byte form. Keeping
    this choice in one function makes the wire decision explicit and testable.
    """
    return struct.pack("<HIBH", GAME_CMD_TASK_NOTIFY, 3,
                       TASK_CLT_NOTIFY_CHECK_FINISH, task_id)

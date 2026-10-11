"""Quest state machine kept independent from transport and GUI."""

from __future__ import annotations

import time


class QuestController:
    def __init__(self, client, return_id: int, accept_id: int,
                 pending_id: int = 17064, cycles: int = 0,
                 retry_minutes: int = 5, command_delay: float = 1.5,
                 npc_id: int = 0, npc_template_id: int = 0):
        self.client = client
        self.return_id = return_id
        self.accept_id = accept_id or return_id
        self.pending_id = pending_id
        self.cycles = cycles
        self.retry_seconds = max(60, retry_minutes * 60)
        self.command_delay = command_delay
        self.npc_id = npc_id
        self.npc_template_id = npc_template_id

    def _resolve_npc(self) -> int:
        if self.npc_id:
            return self.npc_id
        deadline = time.monotonic() + 5
        while not self.client.nearby_npcs and not self.client.stop_event.is_set():
            if time.monotonic() >= deadline:
                break
            self.client.stop_event.wait(0.2)
        if self.npc_template_id:
            return next((object_id for object_id, template_id
                         in self.client.nearby_npcs.items()
                         if template_id == self.npc_template_id), 0)
        if len(self.client.nearby_npcs) == 1:
            return next(iter(self.client.nearby_npcs))
        return 0

    def _wait_task(self) -> bool:
        self.client.log(f"Waiting task {self.pending_id} active; AFK mode "
                         "(CHECK_FINISH every 3s)")
        while not self.client.stop_event.is_set():
            reply = self.client.task_check_finish(self.pending_id)
            if self.client.reply_confirms_task(reply, self.pending_id, 2):
                self.client.log(f"Waiting task {self.pending_id} completed by server")
                return True
            if self.client.stop_event.wait(3):
                return False
        return False

    def run(self) -> None:
        npc_id = self._resolve_npc()
        if not npc_id:
            self.client.log("No NPC resolved to open the quest service", ok=False)
            return
        self.client.npc_hello(npc_id)
        if self.client.stop_event.wait(self.command_delay):
            return
        completed_cycles = 0
        while not self.client.stop_event.is_set():
            if self.cycles and completed_cycles >= self.cycles:
                self.client.log(f"Quest cycle finished ({completed_cycles} completed)")
                return
            self.client.task_check_finish(self.pending_id)
            if self.client.stop_event.wait(self.command_delay): return
            if self.client.task_return(self.return_id):
                completed_cycles += 1
                self.client.log(f"Квест здано (task={self.return_id})")
                if self.client.stop_event.wait(self.command_delay): return
                if self.client.task_accept(self.accept_id):
                    self.client.log(f"Квест взято (task={self.accept_id})")
                    self._wait_task()
                continue
            if self.client.stop_event.wait(self.command_delay): return
            if self.client.task_accept(self.accept_id):
                self.client.log(f"Квест взято (task={self.accept_id})")
                self._wait_task()
                continue
            deadline = time.monotonic() + self.retry_seconds
            while time.monotonic() < deadline and not self.client.stop_event.is_set():
                if self.client.task_check_finish(self.pending_id):
                    break
                if self.client.stop_event.wait(3): return

"""Application-facing GNET session client.

The client owns session sequencing and game reply correlation. TCP framing,
crypto, compression, and binary decoding are injected infrastructure services.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import queue
import struct
import sys
import threading
import time
from collections.abc import Callable

from clean_arch.domain.models import LogLine
from clean_arch.infrastructure.identity import build_fingerprint, build_machine_info
from clean_arch.infrastructure.protocol_ids import (
    HANDLE_BEGIN, PROTOCOL_ACCOUNTLOGINRECORD, PROTOCOL_CHALLENGE,
    PROTOCOL_COLLECTCLIENTMACHINEINFO, PROTOCOL_ENTERWORLD,
    PROTOCOL_ERRORINFO, PROTOCOL_GAMEDATASEND, PROTOCOL_KEEPALIVE,
    PROTOCOL_KEYEXCHANGE, PROTOCOL_ONLINEANNOUNCE, PROTOCOL_RESPONSE,
    PROTOCOL_ROLELIST, PROTOCOL_ROLELIST_RE, PROTOCOL_SELECTROLE,
    PROTOCOL_SELECTROLE_RE, SID_INVALID)
from clean_arch.infrastructure.protocol_catalog import load_catalog
from clean_arch.infrastructure.parsed_data import ParsedData
from clean_arch.infrastructure.string_tables import load_game_string_tables
from clean_arch.infrastructure.transport import FramedTransport
from clean_arch.infrastructure.wire import (
    Buffer, MppcDecompress, ProtocolError, Rc4, Role, i32, octets, read_role,
    u32)


class SessionClient:
    GAME_CMD_TASK_NOTIFY = 106
    GAME_CMD_ERROR_MESSAGE = 25
    GAME_CMD_NPC_INFO_LIST = 9
    GAME_CMD_NPC_GREETING = 70
    GAME_CMD_NPC_HELLO = 35
    GAME_CMD_NPC_SERVE = 37
    GAME_CMD_GET_ALL_DATA = 39
    SERVICE_TASK_RETURN = 6
    SERVICE_TASK_ACCEPT = 7
    SERVICE_TASK_MATTER = 8
    UNSOLICITED_GAME_CMDS = {GAME_CMD_NPC_INFO_LIST}

    def __init__(self, host: str, port: int,
                 emit: Callable[[LogLine], None], timeout: float = 10.0,
                 source_root: str | None = None,
                 game_client_root: str | None = None,
                 elements_root: str | None = None,
                 tasks_root: str | None = None):
        self.emit = emit
        self.transport = FramedTransport(host, port, timeout)
        self.catalog = load_catalog(source_root) if source_root else load_catalog()
        self.string_tables = (load_game_string_tables(game_client_root)
                              if game_client_root else {})
        self.parsed_data = ParsedData(elements_root, tasks_root)
        self.username = ""
        self.password = b""
        self.user_id = 0
        self.local_sid = 0
        self.roles: list[Role] = []
        self.stop_event = threading.Event()
        self.game_request_lock = threading.Lock()
        self.game_replies: queue.Queue = queue.Queue()
        self.game_reply_timeout = 10.0
        self.package_send_cooldown = 5.0
        self._cooldown_lock = threading.Lock()
        self._cooldown_changed = threading.Event()
        self._last_game_send = 0.0
        self.nearby_npcs: dict[int, int] = {}
        self.error_messages: dict[int, str] = {}

    def log(self, message: str, ok: bool = True) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.emit(LogLine(f"[{stamp}] [{'OK ' if ok else 'FAIL'}] {message}"))

    def connect(self) -> None:
        self.transport.connect()
        self.log("Connected")

    def close(self) -> None:
        self.stop_event.set()
        self.transport.close()

    def send_protocol(self, protocol_type: int, body: bytes = b"") -> None:
        self.transport.send(protocol_type, body)
        self.log(f"C2S protocol {protocol_type}: "
                 f"{self.catalog.protocol_name(protocol_type)} "
                 f"(body={len(body)} bytes)")

    def receive_protocol(self) -> tuple[int, Buffer]:
        protocol_type, body = self.transport.receive()
        self.log(f"S2C protocol {protocol_type}: "
                 f"{self.catalog.protocol_name(protocol_type)} "
                 f"(body={len(body.data)} bytes)")
        return protocol_type, body

    def login(self, username: str, password: str) -> None:
        username = username.lower()
        self.username = username
        self.password = password.encode()
        protocol_type, challenge = self.receive_protocol()
        if protocol_type != PROTOCOL_CHALLENGE:
            raise ProtocolError(f"expected Challenge, got {protocol_type}")
        nonce = challenge.octets()
        version = challenge.u32()
        algorithm = challenge.i8()
        edition = challenge.octets()
        challenge.u8()
        self.log(f"Challenge received (nonce={len(nonce)} bytes, version={version}, "
                 f"algo={algorithm}, edition={len(edition)} bytes)")
        if algorithm == 0:
            digest = hashlib.md5(username.encode() + self.password).digest()
            response = hmac.new(digest, nonce, hashlib.md5).digest()
        else:
            response = hashlib.sha256(self.password).digest()
        fingerprint = bytearray(build_fingerprint())
        key = b"\x24\x48\x64\x32"
        for index in range(len(fingerprint)):
            fingerprint[index] ^= key[index % len(key)]
        self.send_protocol(PROTOCOL_RESPONSE,
                           octets(username.encode()) + octets(response) +
                           b"\x00" + octets(bytes(fingerprint)))
        while True:
            protocol_type, body = self.receive_protocol()
            if protocol_type == PROTOCOL_KEYEXCHANGE:
                server_nonce = body.octets()
                truncated = server_nonce[:16]
                identity = username.encode()
                send_key = hmac.new(identity, response + server_nonce,
                                     hashlib.md5).digest()
                receive_key = hmac.new(identity, response + truncated,
                                        hashlib.md5).digest()
                self.transport.set_crypto(Rc4(send_key), Rc4(receive_key),
                                          MppcDecompress())
                self.send_protocol(PROTOCOL_KEYEXCHANGE,
                                   octets(truncated) + b"\x01")
                self.log("Key exchange completed")
            elif protocol_type == PROTOCOL_ERRORINFO:
                error_code = body.i32()
                info = body.octets().decode("utf-8", errors="replace")
                raise ProtocolError(f"server error {error_code}: {info}")
            elif protocol_type == PROTOCOL_ONLINEANNOUNCE:
                self.user_id = body.i32()
                self.local_sid = body.u32()
                self.log(f"Authenticated (user id {self.user_id})")
                machine_info = build_machine_info()
                self.send_protocol(PROTOCOL_COLLECTCLIENTMACHINEINFO,
                                   i32(self.user_id) + octets(machine_info))
                self.log(f"Machine info sent ({len(machine_info)} bytes)")
                return
            else:
                raise ProtocolError(f"unexpected login protocol {protocol_type}")

    def get_roles(self) -> list[Role]:
        self.send_protocol(PROTOCOL_ROLELIST,
                           i32(self.user_id) + u32(SID_INVALID) + i32(HANDLE_BEGIN))
        roles: list[Role] = []
        while True:
            protocol_type, body = self.receive_protocol()
            if protocol_type == PROTOCOL_ACCOUNTLOGINRECORD:
                continue
            if protocol_type != PROTOCOL_ROLELIST_RE:
                raise ProtocolError(f"expected RoleList_Re, got {protocol_type}")
            result = body.i32()
            handle = body.i32()
            response_user_id = body.i32()
            body.u32()
            count = body.compact_uint()
            if result != 0:
                raise ProtocolError(f"RoleList_Re failed with result {result}")
            if response_user_id != self.user_id:
                raise ProtocolError("RoleList_Re user id mismatch")
            roles.extend(read_role(body) for _ in range(count))
            if handle == HANDLE_BEGIN:
                break
            self.send_protocol(PROTOCOL_ROLELIST,
                               i32(self.user_id) + u32(SID_INVALID) + i32(handle))
        self.roles = roles
        return roles

    def enter_world(self, role: Role) -> None:
        self.send_protocol(PROTOCOL_SELECTROLE, i32(role.roleid) + b"\x00")
        protocol_type, body = self.receive_protocol()
        if protocol_type != PROTOCOL_SELECTROLE_RE:
            raise ProtocolError(f"expected SelectRole_Re, got {protocol_type}")
        result = body.i32()
        body.octets()
        if result != 0:
            raise ProtocolError(f"SelectRole_Re failed with result {result}")
        self.send_protocol(PROTOCOL_ENTERWORLD,
                           i32(role.roleid) + i32(-1) + i32(0) + i32(0) +
                           i32(0) + u32(0))
        self.log(f"EnterWorld sent for {role.name} ({role.roleid})")

    def start_keepalive(self) -> None:
        threading.Thread(target=self._keepalive_loop, daemon=True,
                         name="clean-keepalive").start()

    def _keepalive_loop(self) -> None:
        while not self.stop_event.wait(15):
            try:
                self.send_protocol(PROTOCOL_KEEPALIVE, b"\x00")
            except (OSError, ProtocolError):
                return

    def set_cooldown(self, value: float) -> None:
        with self._cooldown_lock:
            self.package_send_cooldown = max(0.1, value)
        self._cooldown_changed.set()

    def start_control_channel(self) -> None:
        threading.Thread(target=self._control_loop, daemon=True,
                         name="clean-cooldown-control").start()

    def _control_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                return
            if not line:
                return
            parts = line.strip().split()
            if len(parts) != 2 or parts[0].upper() != "COOLDOWN":
                continue
            try:
                value = float(parts[1])
            except ValueError:
                continue
            if not math.isfinite(value):
                continue
            self.set_cooldown(value)
            self.log(f"Package send cooldown set to {max(0.1, value):g}s")

    def _wait_game_slot(self) -> bool:
        while not self.stop_event.is_set():
            with self._cooldown_lock:
                remaining = self.package_send_cooldown - (
                    time.monotonic() - self._last_game_send)
            if remaining <= 0:
                with self._cooldown_lock:
                    if time.monotonic() - self._last_game_send >= self.package_send_cooldown:
                        self._last_game_send = time.monotonic()
                        return True
            else:
                self._cooldown_changed.wait(min(remaining, 0.25))
                self._cooldown_changed.clear()
        return False

    def send_game_command(self, data: bytes, label: str,
                          timeout: float | None = None, confirm=None):
        timeout = self.game_reply_timeout if timeout is None else timeout
        with self.game_request_lock:
            if not self._wait_game_slot():
                return None
            while True:
                try: self.game_replies.get_nowait()
                except queue.Empty: break
            self.send_protocol(PROTOCOL_GAMEDATASEND, octets(data))
            command = int.from_bytes(data[:2], "little") if len(data) >= 2 else -1
            self.log(f"C2S game {command}: "
                     f"{self.catalog.command_name('C2S', command)}; {label}")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    reply = self.game_replies.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    break
                if reply[0] in self.UNSOLICITED_GAME_CMDS:
                    continue
                if confirm is None or confirm(reply):
                    return reply
            self.log(f"No reply or confirmation for {label}", ok=False)
            return None

    def npc_hello(self, npc_id: int):
        return self.send_game_command(struct.pack("<Hi", 35, npc_id),
                                      f"NPC hello (npc={npc_id})",
                                      confirm=lambda reply: reply[0] == 70)

    def task_return(self, task_id: int, choice: int = 0):
        data = struct.pack("<HiIii", 37, 6, 8, task_id, choice)
        return self.send_game_command(data, f"Task return (task={task_id})",
                                      confirm=lambda reply: self.reply_confirms_task(reply, task_id, 2))

    def task_accept(self, task_id: int):
        data = struct.pack("<HiIiii", 37, 7, 12, task_id, 0, 0)
        return self.send_game_command(data, f"Task accept (task={task_id})",
                                      confirm=lambda reply: self.reply_confirms_task(reply, task_id, 1))

    def task_check_finish(self, task_id: int):
        data = struct.pack("<HIBH", 49, 3, 1, task_id)
        return self.send_game_command(data, f"Task check finish (task={task_id})",
                                      timeout=1.0,
                                      confirm=lambda reply: self.reply_confirms_task(reply, task_id, 2))

    def task_matter(self, task_id: int):
        data = struct.pack("<HiIi", 37, 8, 4, task_id)
        return self.send_game_command(
            data, f"Task matter (task={task_id})",
            confirm=lambda reply: self.reply_matches_task(reply, task_id))

    def is_task_active(self, task_id: int) -> bool:
        reply = self.task_matter(task_id)
        if not reply or reply[0] != self.GAME_CMD_TASK_NOTIFY:
            self.log(f"Could not check waiting task {task_id}", ok=False)
            return False
        body = self._task_notify_body(reply[1])
        if len(body) < 3:
            self.log(f"Could not decode waiting task {task_id}", ok=False)
            return False
        active = (struct.unpack_from("<H", body, 1)[0] == task_id
                  and body[0] in (1, 3, 6))
        self.log(f"Waiting task {task_id}: "
                 + ("active; AFK mode" if active else "not active"))
        return active

    def reply_confirms_task(self, reply, task_id: int, notify_type: int) -> bool:
        body = self._task_notify_body(reply[1]) if self.reply_matches_task(
            reply, task_id) else b""
        return len(body) >= 3 and body[0] == notify_type

    def reply_matches_task(self, reply, task_id: int) -> bool:
        if not reply or reply[0] != self.GAME_CMD_TASK_NOTIFY:
            return False
        body = self._task_notify_body(reply[1])
        return len(body) >= 3 and struct.unpack_from("<H", body, 1)[0] == task_id

    @staticmethod
    def _task_notify_body(payload: bytes) -> bytes:
        if len(payload) < 4:
            return b""
        size = struct.unpack_from("<I", payload, 0)[0]
        return payload[4:4 + size]

    def handle_game_data(self, data: bytes) -> None:
        if len(data) < 2:
            return
        command = struct.unpack_from("<H", data, 0)[0]
        payload = data[2:]
        self.log(f"S2C game {command}: "
             f"{self.catalog.command_name('S2C', command)} "
             f"(payload={len(payload)} bytes)")
        if command == self.GAME_CMD_TASK_NOTIFY:
            body = self._task_notify_body(payload)
            if len(body) >= 3:
                meanings = {1: "added (accepted)", 2: "removed (returned)",
                            3: "given up", 5: "finished (ready to return)",
                            6: "error code"}
                task_id = struct.unpack_from("<H", body, 1)[0]
                self.log(f"Task notify: task={task_id} "
                         f"{meanings.get(body[0], f'type {body[0]}')}")
        elif command == self.GAME_CMD_ERROR_MESSAGE and len(payload) >= 4:
            code = struct.unpack_from("<i", payload, 0)[0]
            text = self.error_messages.get(code, "no decoding")
            localized = (self.string_tables.get("ingame", {}).get(code)
                         or self.string_tables.get("loginui", {}).get(code))
            self.log(f"Server error message: code {code} "
                     f"({self.catalog.error_name(code)}; "
                     f"{localized or text})", ok=False)
        elif command == self.GAME_CMD_NPC_INFO_LIST:
            self._handle_npc_info_list(payload)
        elif command == self.GAME_CMD_NPC_GREETING:
            self.log("NPC greeting received (service open)")
        self.game_replies.put((command, payload))

    def _handle_npc_info_list(self, payload: bytes) -> None:
        if len(payload) < 2:
            return
        count = struct.unpack_from("<H", payload, 0)[0]
        for base_size in (35, 36):
            entries = self._walk_npc_entries(payload[2:], count, base_size)
            if entries is not None:
                for object_id, template_id in entries:
                    self.nearby_npcs[object_id] = template_id
                return
        self.log(f"NPC info list ({count} entries) could not be parsed", ok=False)

    @staticmethod
    def _walk_npc_entries(data: bytes, count: int, base_size: int):
        state_offset = base_size - 8
        entries = []
        position = 0
        for _ in range(count):
            if position + base_size > len(data):
                return None
            object_id, template_id = struct.unpack_from("<ii", data, position)
            state = struct.unpack_from("<i", data, position + state_offset)[0]
            size = base_size
            if state & 0x40: size += 24
            if state & 0x1000: size += 4
            if state & 0x2000:
                if position + size + 1 > len(data): return None
                size += 1 + data[position + size]
            if state & 0x40000000:
                if position + size + 4 > len(data): return None
                extra = struct.unpack_from("<i", data, position + size)[0]
                size += 4 + extra * 5
            if state & 0x8000: size += 4
            if position + size > len(data): return None
            entries.append((object_id, template_id))
            position += size
        return entries if len(data) - position <= 8 else None

    def run_login_only(self) -> None:
        """Finish the login-only workflow without keeping the socket alive.

        The caller has already authenticated and loaded the role list. This
        mode is used only to force the account out of the world, so retaining
        a background KeepAlive connection serves no purpose.
        """
        self.log("Login completed; world not entered. Disconnecting.")

    def run_world(self, quest_controller=None) -> None:
        self.start_keepalive()
        self.log("In the world. KeepAlive active; Ctrl+C to disconnect.")
        self.send_protocol(PROTOCOL_GAMEDATASEND,
                           octets(struct.pack("<HBBB", 39, 1, 1, 0)))
        self.log("GetAllData sent (pack, equip)")
        if quest_controller is not None:
            threading.Thread(target=quest_controller.run, daemon=True,
                             name="clean-quest").start()
        while not self.stop_event.is_set():
            protocol_type, body = self.receive_protocol()
            if protocol_type == PROTOCOL_KEEPALIVE:
                continue
            if protocol_type == PROTOCOL_GAMEDATASEND:
                self.handle_game_data(body.octets())
            else:
                self.log(f"Received protocol type {protocol_type} (unhandled)")

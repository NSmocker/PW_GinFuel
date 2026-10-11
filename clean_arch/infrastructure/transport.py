"""TCP transport and outer protocol framing."""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable

from .wire import Buffer, MppcDecompress, ProtocolError, Rc4, compact_uint


class FramedTransport:
    """Serialize framed messages and decode encrypted streaming input."""

    def __init__(self, host: str, port: int, timeout: float = 10.0,
                 max_body_size: int = 8 * 1024 * 1024,
                 socket_factory: Callable = socket.create_connection):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.max_body_size = max_body_size
        self.socket_factory = socket_factory
        self.sock: socket.socket | None = None
        self.receive_buffer = bytearray()
        self.send_cipher: Rc4 | None = None
        self.receive_cipher: Rc4 | None = None
        self.decompressor: MppcDecompress | None = None
        self.send_lock = threading.Lock()
        self.state_lock = threading.Lock()

    def connect(self) -> None:
        connection = self.socket_factory((self.host, self.port), self.timeout)
        connection.settimeout(self.timeout)
        with self.state_lock:
            self.sock = connection

    def close(self) -> None:
        with self.state_lock:
            connection = self.sock
            self.sock = None
        if connection is not None:
            connection.close()

    def set_crypto(self, send_cipher: Rc4, receive_cipher: Rc4,
                   decompressor: MppcDecompress) -> None:
        self.send_cipher = send_cipher
        self.receive_cipher = receive_cipher
        self.decompressor = decompressor

    def send(self, protocol_type: int, body: bytes = b"") -> None:
        if len(body) > self.max_body_size:
            raise ProtocolError("protocol body exceeds configured limit")
        with self.send_lock:
            with self.state_lock:
                connection = self.sock
            if connection is None:
                raise ProtocolError("not connected")
            frame = compact_uint(protocol_type) + compact_uint(len(body)) + body
            if self.send_cipher:
                frame = self.send_cipher.update(frame)
            connection.sendall(frame)

    def _receive_bytes(self, minimum: int) -> None:
        while len(self.receive_buffer) < minimum:
            with self.state_lock:
                connection = self.sock
            if connection is None:
                raise ProtocolError("not connected")
            chunk = connection.recv(1)
            if not chunk:
                raise ConnectionError("server closed the connection")
            if self.receive_cipher:
                chunk = self.receive_cipher.update(chunk)
            if self.decompressor:
                chunk = self.decompressor.update(chunk)
            self.receive_buffer.extend(chunk)

    def receive(self) -> tuple[int, Buffer]:
        while True:
            if self.receive_buffer:
                try:
                    probe = Buffer(bytes(self.receive_buffer))
                    protocol_type = probe.compact_uint()
                    body_size = probe.compact_uint()
                    if body_size > self.max_body_size:
                        raise ProtocolError("protocol body exceeds configured limit")
                    body = probe.raw(body_size)
                except ProtocolError as error:
                    if "exceeds configured limit" in str(error):
                        raise
                    body = None
                if body is not None:
                    del self.receive_buffer[:probe.pos]
                    return protocol_type, Buffer(body)
            self._receive_bytes(len(self.receive_buffer) + 1)

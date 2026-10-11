"""Pure wire-protocol primitives for the GNET session.

This module has no socket, GUI, configuration, or legacy-client imports.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class ProtocolError(RuntimeError):
    pass


class Buffer:
    def __init__(self, data: bytes = b""):
        self.data = data
        self.pos = 0

    def need(self, size: int) -> None:
        if size < 0 or self.pos + size > len(self.data):
            raise ProtocolError("incomplete protocol body")

    def raw(self, size: int) -> bytes:
        self.need(size)
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def u8(self) -> int:
        return self.raw(1)[0]

    def i8(self) -> int:
        return struct.unpack(">b", self.raw(1))[0]

    def u32(self) -> int:
        return struct.unpack(">I", self.raw(4))[0]

    def i32(self) -> int:
        return struct.unpack(">i", self.raw(4))[0]

    def compact_uint(self) -> int:
        first = self.u8()
        if first < 0x80:
            return first
        if first < 0xC0:
            return ((first << 8) | self.u8()) & 0x3FFF
        if first < 0xE0:
            return ((first << 24) | (self.u8() << 16) |
                    (self.u8() << 8) | self.u8()) & 0x1FFFFFFF
        return self.u32()

    def octets(self) -> bytes:
        return self.raw(self.compact_uint())


def compact_uint(value: int) -> bytes:
    if not 0 <= value <= 0xFFFFFFFF:
        raise ValueError("CompactUINT value out of range")
    if value < 0x80:
        return bytes((value,))
    if value < 0x4000:
        return struct.pack(">H", value | 0x8000)
    if value < 0x20000000:
        return struct.pack(">I", value | 0xC0000000)
    return b"\xE0" + struct.pack(">I", value)


def octets(value: bytes) -> bytes:
    return compact_uint(len(value)) + value


def i32(value: int) -> bytes:
    return struct.pack(">i", value)


def u32(value: int) -> bytes:
    return struct.pack(">I", value)


class Rc4:
    def __init__(self, key: bytes):
        if not key:
            raise ValueError("RC4 key must not be empty")
        self.perm = list(range(256))
        j = 0
        for i in range(256):
            j = (j + self.perm[i] + key[i % len(key)]) & 0xFF
            self.perm[i], self.perm[j] = self.perm[j], self.perm[i]
        self.i = 0
        self.j = 0

    def update(self, data: bytes) -> bytes:
        result = bytearray(data)
        for index in range(len(result)):
            self.i = (self.i + 1) & 0xFF
            self.j = (self.j + self.perm[self.i]) & 0xFF
            self.perm[self.i], self.perm[self.j] = (
                self.perm[self.j], self.perm[self.i])
            result[index] ^= self.perm[
                (self.perm[self.i] + self.perm[self.j]) & 0xFF]
        return bytes(result)


class MppcDecompress:
    """Streaming translation of the native 8192-byte MPPC history codec."""

    HIST = 8192

    def __init__(self):
        self.history = bytearray(self.HIST)
        self.histptr = 0
        self.l = 0
        self.adjust_l = 0
        self.rptr = 0
        self.adjust_rptr = 0
        self.blen = 0
        self.blen_total = 0
        self.legacy_in = bytearray()

    def _fetch(self) -> int:
        self.rptr += self.l >> 3
        self.l &= 7
        chunk = self.legacy_in[self.rptr:self.rptr + 4]
        return (int.from_bytes(chunk.ljust(4, b"\0"), "big") << self.l) & 0xFFFFFFFF

    def _passbits(self, count: int) -> bool:
        self.l += count
        self.blen += count
        if self.blen < self.blen_total:
            return True
        self.l = self.adjust_l
        self.rptr = self.adjust_rptr
        return False

    def update(self, data: bytes) -> bytes:
        self.legacy_in.extend(data)
        self.blen_total = len(self.legacy_in) * 8 - self.l
        self.rptr = 0
        self.blen = 7
        out = bytearray()
        histhead = self.histptr
        while self.blen_total > self.blen:
            self.adjust_l = self.l
            self.adjust_rptr = self.rptr
            value = self._fetch()
            if value < 0x80000000:
                if not self._passbits(8): break
                self.history[self.histptr] = (value >> 24) & 0xFF
                self.histptr += 1
                continue
            if value < 0xC0000000:
                if not self._passbits(9): break
                self.history[self.histptr] = ((value >> 23) | 0x80) & 0xFF
                self.histptr += 1
                continue
            if value >= 0xF0000000:
                if not self._passbits(10): break
                offset = (value >> 22) & 0x3F
                if offset == 0:
                    advance = 8 - (self.l & 7)
                    if advance < 8 and not self._passbits(advance): break
                    out.extend(self.history[histhead:self.histptr])
                    if self.histptr == self.HIST: self.histptr = 0
                    histhead = self.histptr
                    continue
            elif value >= 0xE0000000:
                if not self._passbits(12): break
                offset = ((value >> 20) & 0xFF) + 64
            else:
                if not self._passbits(16): break
                offset = ((value >> 16) & 0x1FFF) + 320
            value = self._fetch()
            if value < 0x80000000:
                if not self._passbits(1): break
                length = 3
            elif value < 0xC0000000:
                if not self._passbits(4): break
                length = 4 | ((value >> 28) & 3)
            elif value < 0xE0000000:
                if not self._passbits(6): break
                length = 8 | ((value >> 26) & 7)
            elif value < 0xF0000000:
                if not self._passbits(8): break
                length = 16 | ((value >> 24) & 15)
            elif value < 0xF8000000:
                if not self._passbits(10): break
                length = 32 | ((value >> 22) & 0x1F)
            elif value < 0xFC000000:
                if not self._passbits(12): break
                length = 64 | ((value >> 20) & 0x3F)
            elif value < 0xFE000000:
                if not self._passbits(14): break
                length = 128 | ((value >> 18) & 0x7F)
            elif value < 0xFF000000:
                if not self._passbits(16): break
                length = 256 | ((value >> 16) & 0xFF)
            elif value < 0xFF800000:
                if not self._passbits(18): break
                length = 0x200 | ((value >> 14) & 0x1FF)
            elif value < 0xFFC00000:
                if not self._passbits(20): break
                length = 0x400 | ((value >> 12) & 0x3FF)
            elif value < 0xFFE00000:
                if not self._passbits(22): break
                length = 0x800 | ((value >> 10) & 0x7FF)
            elif value < 0xFFF00000:
                if not self._passbits(24): break
                length = 0x1000 | ((value >> 8) & 0xFFF)
            else:
                self.l = self.adjust_l
                self.rptr = self.adjust_rptr
                break
            if self.histptr - offset < 0 or self.histptr + length > self.HIST:
                break
            for index in range(length):
                self.history[self.histptr + index] = self.history[
                    self.histptr + index - offset]
            self.histptr += length
        out.extend(self.history[histhead:self.histptr])
        if self.rptr:
            del self.legacy_in[:self.rptr]
        return bytes(out)


@dataclass(frozen=True)
class Role:
    roleid: int
    name: str
    level: int
    gender: int
    race: int
    occupation: int


def read_role(buffer: Buffer) -> Role:
    roleid = buffer.i32()
    gender, race, occupation = buffer.u8(), buffer.u8(), buffer.u8()
    level = buffer.i32()
    buffer.i32()
    name = buffer.octets()
    buffer.octets()
    equipment_count = buffer.compact_uint()
    for _ in range(equipment_count):
        buffer.u32(); buffer.i32(); buffer.i32(); buffer.i32(); buffer.octets()
        for _ in range(5): buffer.i32()
    buffer.i8()
    for _ in range(3): buffer.i32()
    for _ in range(3): buffer.raw(4)
    buffer.i32()
    for _ in range(2): buffer.octets()
    for _ in range(2): buffer.i32()
    buffer.octets(); buffer.octets()
    if buffer.pos < len(buffer.data): buffer.octets()
    display_name = ""
    if len(name) >= 2 and len(name) % 2 == 0 and not any(name[1::2]):
        display_name = name.decode("utf-16-le").rstrip("\0")
    if not display_name:
        display_name = name.decode("utf-8", errors="replace").rstrip("\0")
    return Role(roleid, display_name, level, gender, race, occupation)

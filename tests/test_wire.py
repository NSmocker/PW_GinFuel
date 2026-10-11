import unittest

from clean_arch.infrastructure.wire import Buffer, Rc4, compact_uint


class WireTests(unittest.TestCase):
    def test_compact_uint_boundaries_round_trip(self):
        values = [0, 0x7F, 0x80, 0x3FFF, 0x4000,
                  0x1FFFFFFF, 0x20000000, 0xFFFFFFFF]
        self.assertEqual([Buffer(compact_uint(value)).compact_uint()
                          for value in values], values)

    def test_rc4_stream_is_symmetric_across_chunks(self):
        encryptor = Rc4(b"key")
        decryptor = Rc4(b"key")
        encrypted = encryptor.update(b"clean") + encryptor.update(b" wire")
        self.assertEqual(decryptor.update(encrypted[:2]) +
                         decryptor.update(encrypted[2:]), b"clean wire")

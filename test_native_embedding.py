import struct
import unittest

from native_embedding import embedding_owner


def _text(raw):
    return bytes([0xa0 + len(raw)]) + raw if len(raw) < 32 else bytes([0xd9, len(raw)]) + raw


def embedding(track_id=b'123', **overrides):
    sample = b'\xca' + struct.pack('>f', 0.5)
    vector = b'\xdc\x00\x40' + sample * 64
    fields = {
        'd2': _text(track_id), 'd3': _text(b'A' * 32), 'd4': sample,
        'd5': b'\x91' + vector, 'd6': vector, 'd7': b'\x92' + sample * 2,
        'd8': sample, 'd9': b'\x7f', 'd10': b'\x00',
        'd11': b'\xcb' + struct.pack('>d', 125), 'd12': sample,
    }
    fields.update(overrides)
    # The native producer can reorder fields or use either allowed string encoding.
    return b'\x81\xd9\x09embedding\x8b' + b''.join(
        _text(key.encode()) + value for key, value in reversed(fields.items())
    )


class NativeEmbeddingTests(unittest.TestCase):
    def test_recognizes_canonical_id_and_unassigned_profile(self):
        for track_id in (b'0', b'1', b'123', b'1' * 20):
            with self.subTest(track_id=track_id):
                self.assertEqual(embedding_owner(embedding(track_id)), track_id.decode())

    def test_requires_every_field_and_finite_vectors(self):
        valid = embedding()
        for data in (
            valid.replace(b'\xa2d3', b'\xa2d2'), valid.replace(b'd10', b'd13'),
            embedding(d4=b'\xcb' + struct.pack('>d', float('nan'))),
            embedding(d6=b'\xdc\x00\x40' + (b'\xca' + struct.pack('>f', float('inf'))) * 64),
            embedding(d3=_text(b'h' * 32)), embedding(d7=b'\x91'), embedding(d9=b'\xff'),
            embedding(d5=b'\x90'), embedding(d5=b'\xdc\xff\xff'), valid + b'\0',
            valid + bytes(1024 * 1024),
        ):
            self.assertIsNone(embedding_owner(data))
        for length in range(len(valid)):
            self.assertIsNone(embedding_owner(valid[:length]))
        for owner in (b'', b'00', b'001', b'-1', b'1' * 21, b'\xff'):
            self.assertIsNone(embedding_owner(embedding(owner)))

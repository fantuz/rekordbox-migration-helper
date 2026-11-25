"""Generated desktop ANLZ records exercise whole-grid editing without personal music."""
import hashlib
import struct
import unittest

from native_grid import plan_grid_nudge, xml_grid_beats
from test_asset_formats import anlz_file, pqtz_section, pssi_section, section
from test_native_embedding import embedding


def media(path='/Contents/test.wav'):
    encoded = (path + '\0').encode('utf-16-be')
    return section('PPTH', struct.pack('>I', len(encoded)), encoded)


RECORDS = [(3, 12403, 221), (4, 12403, 711), (1, 12399, 1191), (2, 12399, 1681)]
MIRROR = section(
    'PQT2', struct.pack('>III', 0, 0x02000002, 0) +
    struct.pack('>HHIHHI', *RECORDS[0], *RECORDS[-1]) +
    struct.pack('>II', 4, sum(sum(entry) for entry in RECORDS)) + bytes(8),
    struct.pack('>HHHH', 2, 125, 540, 999),
)
CLEARED = section('PQT2', struct.pack('>III', 0, 0x02000002, 0) + bytes(32))


class GridNudgeTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            'DAT': anlz_file(media(), pqtz_section(RECORDS, shift=5)),
            'EXT': anlz_file(media(), MIRROR, pssi_section()),
            '2EX': anlz_file(media()),
            '3EX': embedding(b'22'),
        }

    def plan(self, files=None, ms=1, **extra):
        return plan_grid_nudge(self.files if files is None else files, ms, track_id='22', **extra)

    def test_byte_exact_shift_and_repeat(self):
        changes, facts = self.plan()
        expected = [(bar, bpm, ms + 1) for bar, bpm, ms in RECORDS]
        self.assertEqual(changes, {'DAT': anlz_file(media(), pqtz_section(expected, shift=5)),
                                   'EXT': anlz_file(media(), CLEARED, pssi_section())})
        self.assertEqual(facts, dict(beats=4, first_ms=226, last_ms=1686, mirror='populated',
                                     cleared_entries=4, shift_ms=1, media_path='/Contents/test.wav'))
        second, facts = self.plan(self.files | changes, ms=-1)
        self.assertEqual(second, {'DAT': self.files['DAT']})
        self.assertEqual(facts['mirror'], 'cleared')

    def test_absent_table_and_signed_xml(self):
        changes, facts = self.plan({'DAT': self.files['DAT']})
        self.assertEqual(set(changes), {'DAT'})
        self.assertEqual(facts['mirror'], 'absent')
        self.assertEqual(list(xml_grid_beats(changes['DAT'])), [(b, t, ms + 6) for b, t, ms in RECORDS])
        self.assertEqual(list(xml_grid_beats(anlz_file())), [])
        self.assertEqual(list(xml_grid_beats(anlz_file(pqtz_section(entries=())))), [])

    def test_checks_native_mirror_before_clearing(self):
        for at in (12, 16, 20, 24, 32, 40, 44, 48, 56):
            bad = bytearray(MIRROR)
            bad[at] ^= 0x80
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.plan(self.files | {'EXT': anlz_file(media(), bytes(bad))})
        with self.assertRaises(ValueError):
            self.plan(self.files | {'EXT': anlz_file(media(), MIRROR, MIRROR)})

    def test_rejects_duplicate_timestamps_unknown_sections_and_media_mismatch(self):
        invalid = (pqtz_section([(1, 12800, 7), (2, 12800, 7)]),
                   pqtz_section([(9, 12000, 16)]), pqtz_section([(1, 0, 8)]),
                   pqtz_section(RECORDS) + pqtz_section(RECORDS),
                   section('PQT9'), pqtz_section(RECORDS, extra=bytes(4)))
        for tag in invalid:
            with self.subTest(tag=tag[:12]), self.assertRaises(ValueError):
                list(xml_grid_beats(anlz_file(tag)))
        for patch in ({'DAT': anlz_file(media(), pqtz_section(RECORDS), section('ABCD'))},
                      {'2EX': anlz_file(media(), pqtz_section(RECORDS))},
                      {'EXT': anlz_file(media('/Contents/other.wav'), MIRROR)},
                      {'4EX': b'new'}, {'3EX': b'unknown'}, {'3EX': embedding(b'12')}):
            with self.subTest(keys=list(patch)), self.assertRaises(ValueError):
                self.plan(self.files | patch)

    def test_timestamp_bounds_and_unassigned_embedding(self):
        for rows, shift, delta in (([(1, 12000, 0)], 5, -1),
                                   ([(1, 12000, 1)], -1, -1),
                                   ([(1, 12000, 0xffffffff)], 0, 1)):
            with self.assertRaises(ValueError):
                self.plan({'DAT': anlz_file(media(), pqtz_section(rows, shift=shift))}, ms=delta)
        for offset in (0, True, 0.5, '1', -2, 2, 2**33):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.plan(ms=offset)
        sentinel = embedding(b'0')
        files = self.files | {'3EX': sentinel}
        with self.assertRaises(ValueError):
            self.plan(files)
        with self.assertRaises(ValueError):
            self.plan(files, registered_embedding_sha256='0' * 64)
        self.assertIn('DAT', self.plan(files, registered_embedding_sha256=hashlib.sha256(sentinel).hexdigest())[0])

"""Desktop ANLZ grid nudges on supplied backup bytes. This module does no filesystem I/O."""
import hashlib
import struct

from asset_formats import anlz_sections, inspect_anlz
from native_embedding import embedding_owner

MAX_FILE_BYTES = 64 * 1024**2
MAX_SET_BYTES = 256 * 1024**2
MAX_BEATS = 1_000_000
BEAT = struct.Struct('>HHI')
DESKTOP_PQT2 = 0x02000002
KNOWN_TAGS = frozenset('PPTH PVBR PVB2 PQTZ PQT2 PWAV PWV2 PWV3 PWV4 PWV5 PWV6 PWV7 PWVC PCOB PCO2 PSSI PVDI'.split())


def _unique(sections, tag, required=False):
    matches = [section for section in sections if section['tag'] == tag]
    if len(matches) > 1 or (required and not matches):
        raise ValueError(f'Expected one {tag} section')
    return matches[0] if matches else None


def _pqtz(data, section):
    start = section['offset']
    if section['header_bytes'] != 24 or data[start + 12:start + 18] != b'\x00\x00\x00\x00\x00\x08':
        raise ValueError('Unsupported PQTZ header revision')
    shift, count = struct.unpack_from('>hI', data, start + 18)
    if count > MAX_BEATS or section['bytes'] != 24 + BEAT.size * count:
        raise ValueError('Invalid or excessive PQTZ beat count')
    return shift, memoryview(data)[start + 24:start + section['bytes']]


def _records(body, header_shift):
    previous = -1
    for beat, bpm100, ms in BEAT.iter_unpack(body):
        if not 1 <= beat <= 4 or not bpm100 or ms <= previous or ms + header_shift < 0:
            raise ValueError('PQTZ contains an invalid beat, tempo or timestamp')
        yield beat, bpm100, ms
        previous = ms


def xml_grid_beats(data):
    """Yield (beat in bar, hundredths of BPM, effective milliseconds) for XML export."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError('DAT exceeds the analysis size limit')
    sections, state, detail = anlz_sections(data, len(data))
    if state != 'recognized':
        raise ValueError(detail)
    if any(s['tag'].startswith('PQT') and s['tag'] != 'PQTZ' for s in sections):
        raise ValueError('Unsupported timing section in DAT')
    grid = _unique(sections, 'PQTZ')
    if grid:
        shift, body = _pqtz(data, grid)
        for beat, bpm100, ms in _records(body, shift):
            yield beat, bpm100, ms + shift


def _media_path(data, section):
    start, size = section['offset'], section['bytes']
    if (section['header_bytes'] != 16 or size < 20 or size % 2 or size > 65552
            or struct.unpack_from('>I', data, start + 12)[0] != size - 16):
        raise ValueError('Invalid PPTH media path')
    value = data[start + 16:start + size].decode('utf-16-be')
    if not value.endswith('\0') or '\0' in value[:-1]:
        raise ValueError('Invalid PPTH path terminator')
    return value[:-1]


def _check_mirror(ext, section, body, checksum):
    """Compare the two boundary records and checksum against every raw DAT record."""
    start, length = section['offset'], section['bytes']
    if section['header_bytes'] != 56 or struct.unpack_from('>I', ext, start + 16)[0] != DESKTOP_PQT2:
        raise ValueError('Only desktop PQT2 revision 0x02000002 supports this nudge')
    if length == 56:  # inspect_anlz checked the canonical empty header.
        return 'cleared'
    count = len(body) // BEAT.size
    expected = struct.pack('>II', count, checksum & 0xffffffff)
    if (length != 56 + 2 * count or ext[start + 24:start + 32] != body[:8]
            or ext[start + 32:start + 40] != body[-8:] or ext[start + 40:start + 48] != expected):
        raise ValueError('Secondary beat table does not match the DAT beat count, boundaries or checksum')
    return 'populated'


def plan_grid_nudge(files, offset_ms, *, track_id, registered_embedding_sha256=None):
    """Return modified siblings and a summary of a reviewed uniform whole-millisecond shift.

    The caller supplies a complete same-stem inventory. An optional registration digest
    must come from an independent native owner, path, size and checksum check.
    """
    if type(offset_ms) is not int or offset_ms not in (-1, 1):
        raise ValueError('Choose a one-millisecond whole-grid nudge to the left or right')
    if 'DAT' not in files or set(files) - {'DAT', 'EXT', '2EX', '3EX'}:
        raise ValueError('Missing DAT or unsupported analysis companion')
    if any(not isinstance(b, bytes) or len(b) > MAX_FILE_BYTES for b in files.values()) or sum(map(len, files.values())) > MAX_SET_BYTES:
        raise ValueError('Analysis file set exceeds the size limit or has invalid contents')

    media_paths = set()
    grids = {}
    for ext, data in files.items():
        if ext == '3EX' and not data.startswith(b'PMAI'):
            owner = embedding_owner(data)
            if owner is None:
                raise ValueError('Unrecognized .3EX embedding')
            if owner == '0':
                if registered_embedding_sha256 != hashlib.sha256(data).hexdigest():
                    raise ValueError('Unassigned .3EX needs a matching native file registration')
            elif owner != str(track_id):
                raise ValueError('The .3EX embedding belongs to another native track')
            continue
        if not data.startswith(b'PMAI\x00\x00\x00\x1c'):
            raise ValueError(f'Unsupported {ext} analysis container')
        evidence = inspect_anlz(data, len(data), {})
        if evidence['validation'] != 'recognized':
            raise ValueError(f"{ext}: {evidence['detail']}")
        sections = evidence['sections']
        grid_tag = {'DAT': 'PQTZ', 'EXT': 'PQT2'}.get(ext)
        for s in sections:
            tag = s['tag']
            if tag not in KNOWN_TAGS or (tag.startswith('PQT') and tag != grid_tag):
                raise ValueError(f'Unsupported or misplaced {tag} section in {ext}')
        if grid_tag:
            grids[ext] = _unique(sections, grid_tag, required=(ext == 'DAT'))
        media_paths.add(_media_path(data, _unique(sections, 'PPTH', required=True)))
    if len(media_paths) != 1:
        raise ValueError('Analysis companions refer to different media paths')

    dat, section = files['DAT'], grids['DAT']
    header_shift, body = _pqtz(dat, section)
    beats = len(body) // BEAT.size
    if not beats:
        raise ValueError('The primary beat table is empty')
    changed = bytearray(dat)
    checksum = 0
    for index, (beat, bpm100, ms) in enumerate(_records(body, header_shift)):
        shifted = ms + offset_ms
        if not 0 <= shifted <= 0xffffffff or shifted + header_shift < 0:
            raise ValueError('Shift exceeds the native timestamp range')
        checksum += beat + bpm100 + ms
        struct.pack_into('>I', changed, section['offset'] + 28 + BEAT.size * index, shifted)
    changes = {'DAT': bytes(changed)}
    state = 'absent'
    mirror = grids.get('EXT')
    if mirror:
        ext = files['EXT']
        state = _check_mirror(ext, mirror, body, checksum)
        if state == 'populated':
            start, length = mirror['offset'], mirror['bytes']
            altered = bytearray(ext)
            altered[start + 24:start + length] = bytes(32)
            struct.pack_into('>I', altered, start + 8, 56)
            struct.pack_into('>I', altered, 8, len(altered))
            changes['EXT'] = bytes(altered)
    first = BEAT.unpack_from(body)[2] + header_shift
    last = BEAT.unpack_from(body, len(body) - BEAT.size)[2] + header_shift
    return changes, dict(beats=beats, first_ms=first, last_ms=last, shift_ms=offset_ms,
                         mirror=state, cleared_entries=beats if state == 'populated' else 0,
                         media_path=media_paths.pop())

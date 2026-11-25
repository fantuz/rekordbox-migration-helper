"""Read the track ID from the observed desktop .3EX MessagePack profile."""
import math
import re
import struct


class _Reader:
    """Consume only the MessagePack primitives used in the known embedding layout."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    def byte(self):
        value = self.data[self.pos]
        self.pos += 1
        return value

    def text(self):
        tag = self.byte()
        if 0xa0 <= tag <= 0xbf:
            size = tag - 0xa0
        elif tag == 0xd9:
            size = self.byte()
        else:
            raise ValueError
        end = self.pos + size
        if end > len(self.data):
            raise ValueError
        value = self.data[self.pos:end]
        self.pos = end
        return value

    def array_size(self):
        tag = self.byte()
        if 0x90 <= tag <= 0x9f:
            return tag - 0x90
        if tag == 0xdc:
            size, = struct.unpack_from('>H', self.data, self.pos)
            self.pos += 2
            return size
        raise ValueError

    def number(self):
        tag = self.byte()
        if tag == 0xca:
            fmt, size = '>f', 4
        elif tag == 0xcb:
            fmt, size = '>d', 8
        else:
            raise ValueError
        value, = struct.unpack_from(fmt, self.data, self.pos)
        if not math.isfinite(value):
            raise ValueError
        self.pos += size

    def vector(self, width):
        if self.array_size() != width:
            raise ValueError
        for _ in range(width):
            self.number()


def embedding_owner(data):
    """Return the ASCII ID, '0' for unassigned, or None for an unknown layout."""
    if not isinstance(data, bytes) or len(data) > 1024 * 1024:
        return None
    reader = _Reader(data)
    try:
        if reader.byte() != 0x81 or reader.text() != b'embedding' or reader.byte() != 0x8b:
            return None
        owner = None
        seen = set()
        for _ in range(11):
            key = reader.text()
            if key in seen:
                return None
            seen.add(key)
            if key == b'd2':
                value = reader.text()
                if not re.fullmatch(rb'0|[1-9][0-9]{0,19}', value):
                    return None
                owner = value.decode('ascii')
            elif key == b'd3':
                if not re.fullmatch(rb'[0-9a-fA-F]{32}', reader.text()):
                    return None
            elif key in (b'd4', b'd8', b'd11', b'd12'):
                reader.number()
            elif key == b'd5':
                rows = reader.array_size()
                # The shortest row contains a three-byte array header and 64 float32s.
                if not 1 <= rows <= (len(data) - reader.pos) // (3 + 64 * 5):
                    return None
                for _ in range(rows):
                    reader.vector(64)
            elif key in (b'd6', b'd7'):
                reader.vector(64 if key == b'd6' else 2)
            elif key in (b'd9', b'd10'):
                if reader.byte() > 0x7f:
                    return None
            else:
                return None
        return owner if reader.pos == len(data) else None
    except (IndexError, ValueError, struct.error):
        return None

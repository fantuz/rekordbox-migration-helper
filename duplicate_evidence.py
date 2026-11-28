"""Compare saved recording metadata without inspecting or modifying audio."""
import re

from cloud_file_status import lexical_path
from migration_readiness import finite
from storage_sizes import byte_count


EVIDENCE_KEYS = (
    'isrc_agrees', 'isrc_differs', 'duration_close', 'duration_differs',
    'size_agrees', 'size_differs', 'extension_differs',
)
DURATION_TOLERANCE_SECONDS = 2


def isrc_key(value):
    """Canonicalize the usual compact and hyphenated recording identifiers."""
    if not isinstance(value, str):
        return None
    key = value.strip().replace('-', '')
    if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}[0-9]{7}', key, flags=re.IGNORECASE | re.ASCII):
        return key.upper()
    return None


def extension(track):
    path = lexical_path(track.get('current_path'))
    return path.suffix.casefold() if path is not None and path.suffix else None


def recorded_comparisons(tracks):
    """Require complete capture for agreement and two known values for a difference."""
    durations = [finite(t.get('duration', t.get('duration_seconds'))) for t in tracks]
    captured = [value for value in durations if value is not None]
    spread = max(captured) - min(captured) if len(captured) >= 2 else None
    sizes = {byte_count(t.get('size', t.get('size_bytes')), minimum=1) for t in tracks}
    isrcs = {isrc_key(t.get('isrc')) for t in tracks}
    extensions = {extension(t) for t in tracks}
    multiple = len(tracks) >= 2
    return {
        'duration_spread': spread,
        'evidence': {
            'isrc_agrees': multiple and len(isrcs) == 1 and None not in isrcs,
            'isrc_differs': len(isrcs - {None}) > 1,
            'duration_close': spread is not None and len(captured) == len(tracks) and spread <= DURATION_TOLERANCE_SECONDS,
            'duration_differs': spread is not None and spread > DURATION_TOLERANCE_SECONDS,
            'size_agrees': multiple and len(sizes) == 1 and None not in sizes,
            'size_differs': len(sizes - {None}) > 1,
            'extension_differs': len(extensions - {None}) > 1,
        },
    }

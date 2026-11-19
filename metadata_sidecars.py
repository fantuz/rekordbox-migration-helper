"""Conservative filename hints for optional, reversible view filtering.

These helpers never inspect files, decode audio, contact a provider or remove
records. A directory named contents_* is ordinary library data, not a sidecar.
"""
from urllib.parse import unquote, urlsplit


NOTE = 'Filename hints only; no files are removed or changed.'
PATH_FIELDS = ('filename', 'current_path', 'xml_location', 'original_path', 'name', 'path', 'path_lower')
EXACT_NAMES = frozenset(('.ds_store', 'desktop.ini', 'thumbs.db'))


def enabled(value=False):
    if value in (False, None, '', '0', 'false'):
        return False
    if value in (True, '1', 'true'):
        return True
    raise ValueError('Choose a supported metadata-sidecar display filter')


def leaf_name(value):
    if not isinstance(value, str) or not value or '\x00' in value:
        return None
    if value.casefold().startswith('file:'):
        try:
            value = unquote(urlsplit(value).path)
        except ValueError:
            return None
    value = value.replace('\\', '/')
    if not value or value.endswith('/'):
        return None
    leaf = value.rsplit('/', 1)[-1]
    return leaf if leaf not in ('.','..') and not (len(leaf)==2 and leaf[0].isalpha() and leaf[1]==':') else None


def is_name_sidecar(value):
    leaf=leaf_name(value)
    if leaf is None:return False
    return leaf.casefold() in EXACT_NAMES or leaf.startswith('._') and len(leaf) > 2


def is_sidecar(record):
    if not isinstance(record,dict):return False
    # Prefer the observed/current filename over stale alternate references.
    # An old AppleDouble path must not hide a valid relocated audio file.
    for field in PATH_FIELDS:
        value=record.get(field)
        if leaf_name(value) is not None:return is_name_sidecar(value)
    return False


def select(rows, hide=False):
    hiding = enabled(hide)
    rows = list(rows)
    marked = [is_sidecar(row) for row in rows]
    recognized = sum(marked)
    return ([row for row, sidecar in zip(rows, marked) if not (hiding and sidecar)],
            summary(len(rows), recognized, hiding))


def summary(total, recognized, hide=False):
    hiding = enabled(hide)
    return {'enabled': hiding, 'recognized': recognized, 'excluded': recognized if hiding else 0,
            'total': total, 'note': NOTE}

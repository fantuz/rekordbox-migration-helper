"""Check detached database/WAL pairs before giving them to a native reader.

SQLite before 3.54.0 can expose page-cache memory for a crafted pair with
different database and WAL page sizes (CVE-2026-119375). The currently packaged
SQLCipher wheel still includes an older SQLite. These checks are deliberately
independent of the reader version and only run on the app's private copies.
SQLite remains responsible for WAL frame checksums and committed transactions.
"""
from contextlib import closing
from pathlib import Path


def _page_size(value):
    return isinstance(value, int) and 512 <= value <= 65536 and value & (value - 1) == 0


def validate_private_wal(path, plaintext):
    """Reject malformed/mismatched WAL headers before any WAL-aware connection.

    Encrypted databases hide the page-size header. Probe only the base file
    through the existing immutable reader, which ignores sibling journals.
    Never use this helper as an excuse to connect to a selected live library.
    """
    path = Path(path)
    wal = path.with_name(path.name + '-wal')
    if wal.is_symlink():
        raise ValueError('The private database WAL must be an ordinary file')
    if not wal.exists():
        return
    if not wal.is_file():
        raise ValueError('The private database WAL must be an ordinary file')
    with wal.open('rb') as stream:
        header = stream.read(32)
    # SQLite can create an empty WAL before the first write.
    if not header:
        return
    journal = path.with_name(path.name + '-journal')
    if journal.is_symlink() or (journal.exists() and not journal.is_file()):
        raise ValueError('The private database rollback journal must be an ordinary file')
    if journal.exists() and journal.stat().st_size:
        raise ValueError('The private database has both a WAL and a rollback journal; close rekordbox and capture the library again')
    if (len(header) != 32 or int.from_bytes(header[:4], 'big') not in (0x377F0682, 0x377F0683)
            or int.from_bytes(header[4:8], 'big') != 3007000):
        raise ValueError('The private database has an invalid or truncated WAL header; capture it again after closing rekordbox')
    wal_size = int.from_bytes(header[8:12], 'big')
    if not _page_size(wal_size):
        raise ValueError('The private database WAL has an invalid page size')
    if plaintext:
        with path.open('rb') as stream:
            database_header = stream.read(18)
        if len(database_header) != 18 or database_header[:16] != b'SQLite format 3\x00':
            raise ValueError('The private database has an invalid SQLite header')
        database_size = int.from_bytes(database_header[16:18], 'big')
        if database_size == 1:
            database_size = 65536
    else:
        from engine import open_master
        with closing(open_master(path.resolve())) as database:
            # Force key/header verification while the immutable connection
            # still excludes the untrusted WAL from recovery.
            database.execute('SELECT count(*) FROM sqlite_schema').fetchone()
            # Some SQLCipher builds return this pragma as decimal text.
            # Normalize it before comparing with the binary WAL header.
            try:
                database_size = int(database.execute('PRAGMA page_size').fetchone()[0])
            except (TypeError, ValueError, IndexError, OverflowError):
                raise ValueError('The private database page size could not be determined') from None
    if not _page_size(database_size) or database_size != wal_size:
        raise ValueError('The private database and WAL page sizes differ; close rekordbox and capture the library again')

"""Synthetic paired Library Backup ZIP and XML for native-grid integration tests."""
from contextlib import closing
from hashlib import md5
import struct
import zipfile

from native_export import mutable_copy
from test_asset_formats import anlz_file, pqtz_section, section
from test_native_embedding import embedding


def grid_files(offset_ms=0, *, clear_mirror=False):
    """Independent expected bytes for a two-beat DAT and its desktop mirror."""
    beats = ((1, 12000, 125 + offset_ms), (2, 12000, 625 + offset_ms))
    media = '/Music/Night Signal.wav\0'.encode('utf-16-be')
    path = section('PPTH', struct.pack('>I', len(media)), media)
    if clear_mirror:
        mirror = section('PQT2', struct.pack('>III', 0, 0x02000002, 0) + bytes(32))
    else:
        ends = b''.join(struct.pack('>HHI', *beat) for beat in beats)
        header = struct.pack('>III', 0, 0x02000002, 0) + ends
        header += struct.pack('>II', len(beats), sum(map(sum, beats))) + bytes(8)
        mirror = section('PQT2', header, struct.pack('>HH', 120, 860))
    return {
        'ANLZ0000.DAT': anlz_file(path, pqtz_section(beats)),
        'ANLZ0000.EXT': anlz_file(path, mirror),
        'ANLZ0000.2EX': anlz_file(path),
        'ANLZ0000.3EX': embedding(b'0'),
    }


def create_grid_fixture(root, offset_ms=0):
    root.mkdir(parents=True, exist_ok=True)
    backup = root / 'Night Signal.zip'
    xml = root / 'Night Signal.xml'
    master = root / 'master.db'
    prefix = 'PIONEER/USBANLZ/P001/000002BD'
    native_path = '/' + prefix + '/ANLZ0000.DAT'
    files = grid_files(offset_ms)
    with closing(mutable_copy(master)) as db:
        db.executescript("""
            CREATE TABLE djmdContent(ID TEXT PRIMARY KEY, Title TEXT, ArtistID TEXT, FileSize INTEGER,
                Length INTEGER, Rating INTEGER, Commnt TEXT, DeviceID TEXT, ServiceID INTEGER,
                FolderPath TEXT, OrgFolderPath TEXT, AnalysisDataPath TEXT, ImagePath TEXT,
                DJPlayCount INTEGER, rb_local_deleted INTEGER, StockDate TEXT, created_at TEXT,
                Analysed INTEGER, BitRate INTEGER, SampleRate INTEGER, BitDepth INTEGER, BPM INTEGER,
                ReleaseYear INTEGER, AlbumID TEXT, ComposerID TEXT, GenreID TEXT, LabelID TEXT);
            CREATE TABLE djmdArtist(ID TEXT, Name TEXT);
            INSERT INTO djmdArtist VALUES ('fixture-artist', 'Studio Example');
            CREATE TABLE djmdAlbum(ID TEXT, Name TEXT);
            CREATE TABLE djmdGenre(ID TEXT, Name TEXT);
            CREATE TABLE djmdLabel(ID TEXT, Name TEXT);
            CREATE TABLE djmdCue(ID TEXT, ContentID TEXT, rb_local_deleted INTEGER);
            CREATE TABLE contentCue(ContentID TEXT, Cues TEXT, rb_local_deleted INTEGER);
            CREATE TABLE contentFile(ContentID TEXT, Path TEXT, Size INTEGER, Hash TEXT, rb_local_deleted INTEGER);
            CREATE TABLE djmdPlaylist(ID TEXT, Name TEXT, Attribute INTEGER, rb_local_deleted INTEGER);
            CREATE TABLE djmdSongPlaylist(ContentID TEXT, PlaylistID TEXT, rb_local_deleted INTEGER);
            CREATE TABLE djmdHistory(ID TEXT, DateCreated TEXT, rb_local_deleted INTEGER);
            CREATE TABLE djmdSongHistory(ContentID TEXT, HistoryID TEXT, rb_local_deleted INTEGER);
        """)
        db.execute("""INSERT INTO djmdContent
            (ID, Title, ArtistID, FileSize, Length, FolderPath, AnalysisDataPath, BPM, rb_local_deleted)
            VALUES ('701', 'Night Signal', 'fixture-artist', 1024, 180, '/Music/Night Signal.wav', ?, 12000, 0)""",
            (native_path,))
        for name, raw in files.items():
            db.execute('INSERT INTO contentFile VALUES (?, ?, ?, ?, 0)',
                       ('701', '/' + prefix + '/' + name, len(raw), md5(raw, usedforsecurity=False).hexdigest()))
        db.commit()
    with zipfile.ZipFile(backup, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(master, 'master.db')
        archive.writestr('contents.xml', '<ROOT><VALUE name="CONTENT_NUM" val="1"/></ROOT>')
        for name, raw in files.items():
            archive.writestr(prefix + '/' + name, raw)
    xml.write_text('''<DJ_PLAYLISTS><PRODUCT Version="7.2.0"/><COLLECTION Entries="1">
        <TRACK TrackID="701" Name="Night Signal" Artist="Studio Example" Size="1024" TotalTime="180"
               AverageBpm="120.00" Location="file://localhost/Music/Night%20Signal.wav"/>
        </COLLECTION></DJ_PLAYLISTS>''', encoding='utf-8')
    return dict(xml=xml, backup=backup, master=master, files=files, track_id='701',
                analysis_path=native_path, archive_prefix=prefix)

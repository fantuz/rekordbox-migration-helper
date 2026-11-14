# Serato interoperability draft

Library intelligence can generate a detached ZIP containing `_Serato_/database V2`, `_Serato_/Subcrates/*.crate`, a manifest and test instructions. It is a format experiment awaiting validation in a real Serato installation. It is not a verified full library migration.

## Included and omitted

- Basic recorded paths, title, artist, album, genre, BPM, key, year, label, composer, comment and duration when captured.
- Static captured playlist membership and order, including repeated entries; missing or out-of-volume paths are listed as omissions.
- Folder names are sanitized and playlist IDs contribute a stable suffix. Overlong hierarchy filenames are shortened to one crate name.
- Duplicate paths become one database record; crate membership can still refer to that path.
- Cues, loops, beatgrids, waveforms, ratings, history and smart-playlist rules are not transferred.
- No audio files or embedded audio tags are read or written. Existing Serato and rekordbox databases are not opened or overwritten.
- The selected root and paths are not verified on disk. Limits are 100,000 track records, 10,000 playlists and 64 MB of encoded database/crate data.

Choose the music volume root: for example `C:/` on Windows or `/Volumes/DJ` on macOS. POSIX paths use the root supplied by the user, including `/` where appropriate. Paths on other volumes are omitted. Generate separate drafts for separate volumes.

Extract to a staging directory and inspect the manifest. Test only with Serato closed and a backed-up, disposable Serato library. External-drive libraries normally place `_Serato_` at the volume root; the primary library normally uses Music/`_Serato_`. The helper does not install or merge the draft. Compare visible track counts, Unicode names, paths, metadata and crate order before relying on it.

## Format evidence and licensing

The independent encoder uses four ASCII tag bytes, a big-endian 32-bit payload byte length, UTF-16BE text and nested object chunks. The database and crate headers differ. Synthetic tests independently walk chunk lengths and inspect Unicode, volume-relative paths and crate order. These tests establish encoding properties, not acceptance by the Serato application.

References reviewed:

- [SpinTools/seratoparser](https://github.com/SpinTools/seratoparser), MIT: database/crate parsing.
- [Dj-Library-migration-tool](https://github.com/scanmydata/Dj-Library-migration-tool), MIT: an independent migration project and Serato writer; its application-validation limits must also be respected.
- [Mixxx Serato database format notes](https://github.com/mixxxdj/mixxx/wiki/serato_database_format): example crate structures and path conventions.
- [Kerrick Staley's decoder gist](https://gist.github.com/kerrickstaley/8eb04988c02fa7c62e75c4c34c04cf02): corroborates length-prefixed chunks, UTF-16BE strings and nested objects. It is a decoder, not proof that a generated library will import. No explicit license was visible, so its code is not copied.
- [Serato: what is database V2?](https://support.serato.com/hc/en-us/articles/204194250-What-is-the-DatabaseV2-file).

No code from those projects or the gist is vendored in this bridge. The project's own implementation remains under its existing license.

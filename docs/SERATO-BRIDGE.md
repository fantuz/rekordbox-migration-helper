# Serato interoperability draft

Library intelligence can generate a detached ZIP containing `_Serato_/database V2`, `_Serato_/Subcrates/*.crate`, a manifest and test instructions. It is a format experiment awaiting validation in a real Serato installation. It is not a verified full library migration.

## Included and omitted

- Basic recorded paths, title, artist, album, genre, BPM, key, year, label, composer, comment and duration when captured.
- Static captured playlist membership and order, including repeated entries; missing or out-of-volume paths are listed as omissions.
- Folder and playlist components share stable ID suffixes, with empty parent crates included. Long or cyclic hierarchies fall back to top-level names with explicit warnings.
- Duplicate paths become one database record; every crate uses the retained path spelling. Windows path comparisons ignore case; POSIX comparisons preserve case.
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

## Preview and independent readback

Choose a saved collection and volume root, then select **Preview Serato export**. Review track and crate counts, metadata coverage, omitted records, omitted playlist entries and hierarchy/order warnings. Up to 100 rows per section are displayed; the ZIP manifest retains the full report. Changing the source or root clears the preview and acknowledgment. The preview does not check the audio filesystem.

A separate strict Python decoder reads the encoded database and each crate before either preview or download. It checks chunk boundaries, UTF-16, metadata values, exact crate sequence and references to existing exported database records. Malformed output prevents download. This is an independent implementation inside this project, not an external Serato certification. The manifest keeps `serato_import_verified: false`.

## Disposable application test

Generate a tiny fixture on the computer where Serato will be tested:

```sh
python packaging/create_serato_fixture.py --output /absolute/path/to/new-test-folder
```

The output directory must be new. The generator creates three invented records, three one-second silent WAV files and a detached ZIP. There is no copyrighted recording or real catalogue data. Run the generator again after changing computers or locations; paths refer to the exact generated files. Generated databases and audio are not included in application releases.

With Serato closed, use a disposable test library or spare test volume and preserve any existing `_Serato_` folder. Follow the staging instructions above. Record the Serato version, operating system and volume layout, then check:

1. Three tracks are visible and point to the generated silent files.
2. Accents, Japanese text and emoji remain intact.
3. The nested **Order and repetitions** crate appears under **Synthetic tests**.
4. The intended sequence is track 2, track 0, track 1, track 0. Record whether Serato preserves or removes the repeated entry.
5. Close and reopen Serato; recheck names, paths and crate structure.

A failed check is useful compatibility evidence. Do not treat successful binary readback alone as a successful migration.

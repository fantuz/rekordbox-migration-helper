# Serato interoperability draft

Library intelligence can generate a detached ZIP containing `_Serato_/database V2`, `_Serato_/Subcrates/*.crate`, a manifest and test instructions. It is a format experiment awaiting validation in a real Serato installation. It is not a verified full library migration.

## Serato 4.x compatibility warning

**Serato's current support documentation labels `database V2` as [LEGACY], associated with versions before 4.0.0.** The current Serato folder primarily uses `Subcrates` for static crates and `Smartcrates` for rule-based crates, but a valid legacy `database V2` file does not establish that Serato 4.x will ingest its track records. The separate older Serato DatabaseV2 article is historical background rather than a verified specification for recent releases.

Therefore this exporter must be treated as an **unverified legacy-format research draft**, not a 4.x library importer. Do not copy its output into any existing working Serato library, or assume binary readback implies that tracks will become visible. Record a real Serato version and test on a disposable library or volume before broadening format coverage.

References: [Official Serato folder layout, including legacy markers](https://support.serato.com/hc/en-us/articles/204022904-What-is-in-the-Serato-folder), [legacy DatabaseV2 description](https://support.serato.com/hc/en-us/articles/204194250-What-is-the-DatabaseV2-file), [Smart Crates](https://support.serato.com/hc/en-us/articles/360001447715-Library-Smart-Crates).

### Newer library layout evidence (Serato 4.x)

Serato's [official library-transfer guide](https://support.serato.com/hc/en-us/articles/202305054-Backing-up-and-moving-your-library-to-a-new-computer) says a complete move must preserve both the user's Music/`_Serato_` folder **and** the separate **Serato/Library** directory, plus the audio files themselves. This Library directory is under `~/Library/Application Support/Serato/` on macOS and `%LOCALAPPDATA%/Serato/` on Windows. The official [auto-backup guide](https://support.serato.com/hc/en-us/articles/227561667-Library-Auto-Backup) describes newer `Serato/Library/Backups` snapshots and their overwrite/recovery semantics.

Third-party research describes `master.sqlite` and `root.sqlite` inside the 4.x Library folder, including WAL sidecars and crate/asset records. The available research **disagrees about which file is the authoritative writable store**: [MixGoat's September 2026 guide](https://www.mixgoat.com/guides/serato-library-files-explained) describes `master.sqlite` as live; [serato-crates-sync internals](https://github.com/LegendT/serato-crates-sync/blob/main/docs/internals.md) describes `root.sqlite` as an authoritative revision-tracked space with aggregation into `master.sqlite`. Neither is an official schema contract. Consequently, the helper must not write either file until a version-pinned sample, WAL-aware transaction semantics, schema and round-trip behavior have been validated.

A future **read-only 4.x discovery phase** should identify which stores exist, capture file and journal metadata, inventory tables and relationships from a stable private copy, and compare results against application counts. It must not merge, checkpoint or replace an active Serato database. Cue, loop and grid migration additionally needs explicit source/audio-tag handling and independent test fixtures.

### Cross-platform target path profiles

The detached legacy draft now accepts an explicit target path profile: **Auto**, **Windows** or **macOS**. On Linux, both targets are explicitly treated as **simulated path conventions**, not evidence of an installed/running Serato application. An optional target music volume root can differ from the source volume: for example source `C:/`, target `/Volumes/DJ`. Only volume-relative track paths are encoded; they retain their internal folder hierarchy, which must actually be copied to the chosen destination before testing. This does not invent file existence or translate drive letters automatically. Preview and ZIP manifest identify the source and target roots, target OS profile and whether it was simulated. The generated ZIP remains an **unverified legacy database V2 and static crate draft**, not a Serato 4.x SQLite database.

Official Serato paths: on Windows, `%USERPROFILE%/Music/_Serato_` and `%LOCALAPPDATA%/Serato/Library`; on macOS, `~/Music/_Serato_` and `~/Library/Application Support/Serato/Library`. External volumes typically carry `_Serato_` at their root. The newer `Serato/Library` folder is shown as a *location hint only*: our ZIP does not write its modern SQLite content.

Auto uses a recognized entered target root first, falling back to an unambiguous recorded Windows drive root or macOS `/Volumes/<drive>` source root. A bare source `/` or a Linux mount path does not automatically mean macOS: choose the Windows/macOS profile explicitly. The helper's host OS never determines the destination. An explicit Windows or macOS selection with no compatible root offers `C:/` or `/Volumes/DJ`; a compatible custom root is retained. Windows targets require a drive root, and macOS targets require `/` or `/Volumes/<drive>`. Source roots remain independent. The preview and manifest include up to five mapped destination path examples; encoded database paths stay volume-relative.

Case aliases on a Windows source still share one exported record. Distinct POSIX source paths that would collide on a Windows destination are different: the conflicting record and its playlist references are omitted with `target_path_collision`, so no playlist silently points to a different file. Review and resolve these filenames before migration. macOS path comparisons remain case-sensitive; the actual destination filesystem may differ.

### Suggested compatibility milestones

1. **Real-application acceptance:** import the existing synthetic three-track fixture into isolated installations of Serato 3.x and 4.x, recording application version, OS, library layout, errors and what Serato actually displays.
2. **Modern format research:** document any 4.x library changes and supported interchange routes before attempting to write or replace its native library.
3. **Safe portability first:** investigate standard M3U playlist export and path relocation reports; keep crate metadata and application-specific analysis separately identified.
4. **Advanced metadata last:** investigate cues, loops, grids, ratings and smart-crate rules only after round-trip, version-specific and data-loss validation. Never automatically promote incomplete conversions to full migration.



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

# Prepare a computer or version migration

Start **Migrate a library** on the home page for a saved checklist and source/destination comparison. The Workbench helps inventory, review and compare library copies before a move. It does not transfer a cloud account or replace rekordbox's native conversion/restore process.

1. In rekordbox, finish synchronization and create a fresh **Backup Library** backup plus collection XML consecutively. Keep an untouched backup outside the Workbench. Back up audio separately if it is excluded; preserve required analysis assets as well.
2. Use Source analyzer or import the pair. Save a Library lab snapshot and history snapshot before cleanup. Audit analysis assets and actual music locations; cloud placeholders need local availability for byte verification or playback.
3. On a new computer, plan destination media paths, drive letters/volume names and cloud-provider setup. Media inventory and reference staging help prepare destination references; a recorded path does not prove the file is present on the target.
4. Review duplicates, cues, ratings and staged metadata. Generate edited XML/native ZIP copies only after acknowledging your untouched backup. Native ZIP generation is experimental and currently gated to v7 inputs.
5. Test the generated files in a separate target library with Cloud Library Sync paused. Confirm track counts, media resolution, playlists, cue/grid behavior, history and playback in rekordbox before replacing a working library or rejoining sync.
6. Capture the target library and compare Lab snapshots for cue, rating and playlist changes. Keep reports, decisions and optional HTML/minisite summaries for future review.

For version changes, distinguish XML interchange from native conversion. A v5 XML can provide global statistics and metadata without decoding `.edb`. Convert a copy with rekordbox when modern native analysis is needed. AlphaTheta says v6 → v7 does not require conversion; this does not establish backward export or a supported downgrade. Genuine old-version validation and a fully recorded native restore checklist remain outstanding. A Windows 11 restore was reported as successful by the maintainer, with an approximately recalled rekordbox version and no recorded ZIP/XML route. See [Compatibility](COMPATIBILITY.md) and [format sources](FORMAT-SOURCES.md).

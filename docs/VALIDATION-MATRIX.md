# Validation evidence and remaining samples

A packaged application starting successfully, a database passing automated checks, and a library restoring correctly inside rekordbox are different results. Record them separately. **Unknown** means that evidence is unavailable; it does not mean a failure or a successful test.

| Area | Current evidence | What remains to establish |
| --- | --- | --- |
| v5 XML collection | XML metadata reader, statistics and automated interchange tests | A consented genuine v5 XML fixture with recorded expected track, playlist and metadata counts |
| v5 native `.edb` | Format detection and file inventory | No legacy record decoder; conversion of a copy with rekordbox remains the route to modern native analysis |
| v6 desktop native library | Modern-family schema checks and synthetic SQLite/SQLCipher tests | Genuine v6 source/backup fixtures, exact versions and comparison against counts visible in rekordbox |
| v7 desktop native library | Genuine v7 backup analysis on Linux plus automated database/archive checks | Broader exact-version fixtures and a recorded native restore checklist for each claimed platform/version |
| Windows restore | Maintainer reports successful use and restore on Windows 11; recalled rekordbox version approximately **7.2.19** | Exact version, restore route (**native ZIP or XML is unspecified**) and cue/grid/playlist/tag/file checks were not recorded. This remains a user report, not certification |
| macOS applications | Native packaged startup checks on Intel and Apple Silicon CI runners | A licensed rekordbox restore test and recorded checklist on each architecture; startup is not a restore test |
| Linux portable application | Native startup and bundled-runtime checks on CI | Linux has no native rekordbox application; mounted Windows/macOS libraries require the user to mount the filesystem and select a path |
| Cloud Copy / Move | Conservative path, inventory, hash and storage logic with synthetic fixtures | Consented real Dropbox and Google Drive examples of both choices, including available and online-only files. Database records alone cannot prove the user's Copy/Move choice |
| Classic USB Device Library | Detects `export.pdb` | Genuine fixtures and an implemented record decoder before claiming record-level comparison or conversion |
| OneLibrary / Device Library Plus | Detects `exportLibrary.db` | Genuine fixtures, including a device containing both library families; no record-level decoder or converter is currently claimed |
| Analysis assets / STEMS | Inventory and relationships within explicitly selected scopes | Genuine asset examples and ownership/readiness validation; an extension or filename alone does not prove a track has playable stems or that an asset is safe to delete |

The [compatibility guide](COMPATIBILITY.md) defines the supported operations. The [format sources](FORMAT-SOURCES.md) distinguish official interchange specifications from implementation observations.

## Contribute evidence without publishing a private library

Start with [validation-result-template.json](validation-result-template.json). Copy it outside the application inputs, fill only observed results, and leave untested fields as `null` or `not_checked`. Record the exact application build, source commit, operating system and rekordbox version shown by the application. Add the test date and the route used; a remembered version should be marked approximate.

A useful contribution is a small report with counts, screenshots containing no private information, and checksums of files you keep locally. Do not commit full personal libraries, music, credentials, cloud account details, file paths containing usernames or private playlist/history names. A genuine fixture should use a small test library whose redistribution is permitted. Discuss its scope before sharing it, and use synthetic audio or music you may lawfully redistribute if audio is necessary. A hash identifies bytes; it does not authorize their publication.

For v6, include representative tracks with known metadata and playlists, record baseline counts in rekordbox, and compare the read-only report. For cloud tests, record the provider and the user's known Copy/Move choice, which folders were selected, which files were physically available, and whether cloud placeholders were present. Check both duplicate database records and duplicate physical files. Do not infer one from the other.

For Classic/OneLibrary device fixtures, record the exporting rekordbox version, device filesystem, present database filenames and whether both families coexist. Detection is the present test scope. Decoding or conversion requires separate implementation and fixture validation.

## Native restore checklist

1. Create a fresh untouched **Backup Library** backup and a consecutive **Export Collection in XML format** export. Preserve audio separately when excluded from the ZIP. Record baseline counts and a few known cue/grid/rating/playlist examples.
2. Review the planned changes in the Workbench. Record its version and commit, the generated archive's checksum and the expected record changes. The HTML summary is a report, not a restorable library backup.
3. Test on an isolated destination/library. Keep the original library and backups safe. Pause cloud synchronization for the isolated test so that restoring does not become an uncontrolled cloud reconciliation.
4. Record the exact route: **File → Library → Restore Library** for a generated native ZIP, or the separate **rekordbox xml** import route for XML. XML import is not a second mandatory step after restoring a ZIP. A native restore can replace the destination collection.
5. Check that rekordbox opens without errors. Compare collection counts and expected duplicate reductions, playlist membership and order, track file availability, ratings, comments, colours, cue labels/positions and beatgrids. Open and play representative retained tracks. Check analysis/history only where the source and selected route carry them.
6. Mark each check independently. Record errors and mismatches, including unknown or unavailable data. A result from a handful of representative tracks is a sample, not a guarantee covering every track.
7. Resume cloud synchronization only when the isolated result is understood. Record any reconciliation effects separately. Keep the original backup until satisfied with the destination library.

Publicly describe results with their limits, for example: “User-reported native ZIP restore on this exact version; 12 representative tracks checked.” Never turn a startup test or an approximate recollection into a fully verified compatibility claim.

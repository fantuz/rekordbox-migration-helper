# Further library checks worth building

The 0.5 preview now implements snapshot cue/rating/playlist comparisons, conservative metadata variant suggestions, analysis asset audits and configurable genre/BPM preparation coverage in **Library lab**. See [the implementation guide](LIBRARY-LAB.md). The table also includes future work; it is not a list of fully implemented features.

Official support documentation and release notes describe missing files, inconsistent device playlists and analysis issues. These are useful problem families, not a measured ranking of issue frequency. The proposals below do not diagnose a particular library from symptoms alone.

| Problem or question | Evidence the tool can use | Useful result | Priority / effort |
| --- | --- | --- | --- |
| Broken paths and relocation collisions | Recorded/current/original paths, selected-folder inventory, size and explicit hashes | One explainable relocation plan, collisions held for review | High; extend existing inventory |
| Duplicate records versus extra cloud/local files | Active track graph, path aliases, hashes, allocated bytes | Distinguish database cleanup from potential storage savings | Already available read-only; real cloud fixtures needed |
| Cue/grid changes between backups | Recording match, cue timestamps/labels, beatgrid signatures, ratings and playlists | Regression report showing lost preparation before a restore | High; medium |
| Metadata spelling and coverage gaps | Normalized artist/genre/album labels, year, duration, bitrate and format | Review clusters for aliases, missing fields and unlikely values | High; small–medium; do not rewrite tags automatically |
| Missing analysis assets or stale owners | Track-to-analysis relationships, asset inventory, source scopes | Explain absent versus unreferenced analysis and estimate footprint | Existing read-only foundation; medium for safe cleanup plans |
| Half/double-tempo disagreements | BPM and grid differences inside matched recordings | Review probable octave disagreements without erasing hand-edited grids | Medium; medium; audio confirmation may be necessary |
| USB playlists diverge by device format | Matched classic/OneLibrary export fixtures, IDs and playlist order | Report tracks/playlists present in only one device library | Later; substantial decoder/fixture work |
| Export readiness for a specific player | Hardware-supported formats, sample rates, filenames, actual file presence | A per-device preparation checklist with explicit rule versions | Medium; medium plus ongoing compatibility maintenance |
| Collection coverage and usage patterns | Genres, BPM, duration, plays, ratings, dates and playlist membership | Find neglected tracks, long sets/samples and unprepared subcollections | Offline explorer foundation now available |
| Unexpected library drift | Consecutive snapshots, stable IDs/hashes, row counts and metadata changes | Incremental audit history and restore comparisons | Medium; medium; local SQLite is sufficient for libraries of this scale |

The next useful sequence is a snapshot-diff report, metadata-normalization suggestions, then an export-readiness report. Audio fingerprinting or similarity embeddings could help with renamed/re-encoded files later, but require explicit audio reads, more dependencies and a separate confidence model. Saved preview-waveform agreement is candidate evidence, not proof of identical audio.

SQLite indexes and incremental scans can support much larger collections than the current sample without a hosted “big data” system. Keep extraction, evidence, proposed decisions and applied exports separate. Count unknown/unscanned data explicitly and show how every suggested change was derived.

Sources: [rekordbox FAQ](https://rekordbox.com/en/support/faq/rekordbox7/), [release notes](https://rekordbox.com/en/support/releasenote/), [official OneLibrary/Device Library notice](https://alphatheta.com/en/information/important-notice-for-customers-using-usb-devices-with-our-dj-equipment/), [official Cloud Library Sync guide](https://cdn.rekordbox.com/files/20251202174725/rekordbox7.2.8_cloud_library_sync_operation_guide_EN.pdf).

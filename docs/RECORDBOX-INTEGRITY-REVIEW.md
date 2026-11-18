# Recordbox integrity review — 17 November 2026

This review covers [fantuz/recordbox at `2cbe1de9`](https://github.com/fantuz/recordbox/tree/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988), compared with the previously inspected `755efdcf`: 17 commits, 61 changed files, 28,174 added and 2,888 removed lines. The review includes database and XML behavior, identity, cues, playlists, paths, device import/export, backup/recovery, analysis and STEMS. Recordbox is a separate implementation; its internal database and caches are distinct from native rekordbox formats.

Evidence has three levels here: directly inspected source behavior; independently checked public binary layouts; and implementation claims that still require fixtures or application/player acceptance. The Rust application, model inference and physical players were not run during this review. Source-derived identity probes translate the relevant rules into Python; they demonstrate the rules' limitations, not an end-to-end Recordbox run.

## Changes implemented in Library Workbench

| Gap | Resulting behavior | Validation |
| --- | --- | --- |
| Every non-PMAI `ANLZ*.3EX` was called corrupt | Non-PMAI variants remain Unsupported. A MessagePack `embedding` prefix is retained only as a signature hint. PMAI files still receive their existing checks, including malformed PMAI under a `.3EX` name. | Invented valid/invalid/truncated MessagePack-shaped inputs; folder/ZIP parity and saved evidence in Playwright. |
| PQT2 payloads were opaque | The observed 56-byte-header revision `0x01000002` checks its beat count against body length and every fractional value against 0–999 microseconds within a millisecond. Unknown revisions remain undecoded; incomplete prefixes remain Not checked. Stored checksums are exposed as unverified. | Independent regeneration of two public sections; invented malformed counts/fractions, unknown revisions and bounded-prefix regressions. |
| Active-loop switches were invisible during snapshot comparison | Known 0/1 states are compared independently from cue positions and annotations. Missing or unknown states are counted separately for each snapshot and do not become assumed changes. | Both switch directions, representation normalization, position changes and real-server report filtering/download. |
| Playlist moves and type conversions were invisible | Comparison reports captured parent, folder and smart/manual changes. Unique UUID matches precede guarded ID/name matches; matched parent identities prevent false moves when IDs are renumbered. | Reused/renumbered IDs, root moves, unresolved parents, missing type evidence, duplicate membership and manual/smart conversion. |
| Some captured performance metadata was omitted | Comparisons also expose title, BPM, key spelling, play count and analyzed-status changes when both values are available. | Before/after evidence, known zero/false values, unavailable values and Playwright. |

The new comparison checks join the existing Chromium, Firefox and WebKit pipeline. The Chromium workflow also checks analysis variants in folders/ZIPs and verifies saved comparison evidence after an actual server restart. All browser data and binary fixtures generated in CI are synthetic. These changes inspect evidence; they do not rewrite audio, native databases or analysis files.

Resuming the cloud exposed two export API fixtures that changed the data directory without changing the managed temporary workspace. On machines where `/tmp` and the checkout are separate filesystems, their export rename failed. Those fixtures now own and clean both paths together, matching the actual launcher; the real-server export/restart workflow passed independently. No production export behavior was changed for this fixture isolation correction.

## Audio identity: highest-priority follow-up

[Device import](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/device_import.rs#L29) reuses an existing destination when its size matches, without comparing bytes. Its copy path checks the number of bytes copied but does not have the export path's SHA-256 read-back check. Different same-length files can therefore satisfy the reuse rule.

[Device export](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/usb.rs#L1137) considers a source changed if its size differs or its modification time exceeds the destination's by more than two seconds. Metadata failures return false. The foreign-row matcher also uses size, folder/name and tag hints. Reused files bypass `copy_durable` and its content comparison. A file changed in place, copied with preserved timestamps, or replaced with equal-length content can be missed even with recopy enabled.

The source-derived probes used different 100-byte files and timestamps within one second: the export change rule returned false and the import size rule allowed reuse. Filename/size and timestamps should identify candidates; they should not establish identical audio. Workbench's existing Storage audit already separates candidates from explicit SHA-256 verification. A stronger future device audit should retain source/destination hashes, source stamps before and after reading, and association confidence separately from catalog IDs and titles.

## Publication, recovery and file confinement

The [journaled writer](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/usb.rs#L2550) writes and flushes both temporary catalogs, records `P`, then publishes them with two renames. This makes `P` the boundary between rollback and completing publication. Deletions are journaled before that boundary and applied afterward. A newly copied file also receives a source/destination SHA-256 check. These are useful patterns to retain.

However, [recovery](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/usb.rs#L943) discards several publication/restoration errors, removes the journal and returns a completed/undone message. A failed rename or missing replacement backup can therefore leave recovery evidence unavailable while the message claims success. `run_guarded` also describes rollback unconditionally after a panic, although a published journal calls for completion.

Recovery consumes paths from the journal. `C` removal and `R` restoration join these paths without an explicit confinement check; the deletion helper's prefix check is lexical. Parent components, absolute names and symlink destinations need dedicated validation. This is a source finding; no destructive recovery or exploit was executed.

Required follow-up tests: interruption before/after `P`, between catalog renames, during deletion and during recovery itself; missing backup, full/read-only destination and failed rename; repeated recovery; mixed-generation catalog detection; and path confinement. Failed recovery should preserve the journal and report the actual outcome. Catalog header recognition alone cannot prove an export transaction completed.

## Backup and database integrity

[Recordbox backup format 1](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/backup.rs#L1) contains `manifest.json`, `library.db`, optional preferences/artwork and optional music. It is not a native rekordbox `master.db` backup. `VACUUM INTO` includes committed WAL content; restore checks SQLite integrity, upgrades a staged copy and creates a safety snapshot before applying the online backup. These protections are substantive improvements.

Remaining checks should cover:

- Manifest format/schema/count agreement, bounded extraction, duplicate members, missing entries and declared missing music.
- Schema/table/column expectations and foreign-key/orphan checks in addition to SQLite `integrity_check`, which does not establish relationship completeness.
- Existing music: restore skips existing paths without proving their contents match the backup. Add-only restoration is different from restoring the backed-up audio state.
- Destination selection and confinement: music targets are absolute paths from the manifest, while artwork is flattened to basenames. Validate destinations, symlinks and name collisions before writing.
- Cancellation/retry and full-disk behavior, including staging artifacts and existing temporary names.

Workbench currently inventories/checksums ZIP evidence without extracting it. It must not imply that a verified archive is a tested restore or classify Recordbox's own library as a native rekordbox database.

[The library schema](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/db.rs#L39) is version 3, with histories, tag-list membership and matching relationships. Future-schema rejection and pre-upgrade snapshots are valuable. Column migrations use a transaction, but initial table/index setup precedes it. The [XML import workflow](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/library_ext.rs#L1398) ignores several begin/write/commit errors. Failure injection should test atomic track/grid/cue/playlist import and report partial outcomes accurately.

## Analysis evidence and precision

### PQT2

The [new implementation](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/anlz.rs#L174) derives a PQT2 header from PQTZ entries: first/last entries, count, a wrapping sum of beat number + BPM×100 + whole milliseconds, and one u16 fraction per beat. It cuts whole milliseconds and stores the remainder separately. The implementation explicitly says the first/last interpretation for multi-tempo files is an assumption.

Independent probes used two previously downloaded public [rekordcrate fixtures at `68cd702e`](https://github.com/Holzhaus/rekordcrate/tree/68cd702e9c78bde4b9eab477e0a7547a0cb69768/data/complete_export/demo_tracks). Reconstructing each header from PQTZ and retaining the fixture's own fractions reproduced its entire PQT2 section byte for byte. Both have constant tempo. This validates those examples, not an exhaustive vendor specification; the ledger's additional 100 private files were not available here.

| Local fixture alias | Beats | DAT SHA-256 | EXT SHA-256 |
| --- | --- | --- | --- |
| `1` | 368 | `b938b44af10da3d33ff7c352fb605be353219f009be35ab0c3a3313508bbcacf` | `e5fbc932a0f22869bc66f6f8228fabc912fb159c4fdcee3ae34b6e8b98465de8` |
| `2` | 257 | `b9aeb37d559042629512754612b20fda9e4614e9c64c6b934d4055f15209c0e8` | `837ac9acbcf19b19d489d8650acfff1e638330aded9433dca7b491f27c1956ea` |

Before this change, altering only a PQT2 beat count left Workbench's framing result Recognized. The new known-revision count check catches that inconsistency in both files. Cross-file checksum verification still needs unambiguous PQTZ association; selected files are not associated merely because their basenames agree.

The source's [real-file PQT2 test](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/usb_fix_test.rs#L414) discovers optional local oracle files. Without those files it can check zero real sections and still finish successfully. Conformance jobs should pin available fixture provenance and assert a nonzero expected case count; a green synthetic suite alone cannot reproduce the ledger's 102-file claim.

### Extended cues and `.3EX`

Recordbox interprets PCP2 offsets 30/32 as fractional microseconds and 36/38 as a beat-loop ratio, with seek information in the tail. The [public ExtendedCue definition](https://github.com/Holzhaus/rekordcrate/blob/68cd702e9c78bde4b9eab477e0a7547a0cb69768/src/anlz.rs#L365) supports the loop numerator/denominator fields but still labels the fractional fields unknown. Seek data and exact loop precision need populated independent fixtures. Workbench retains existing cue milliseconds/comments and does not enforce these newly inferred fields as a universal specification. Legacy active-loop flags and extended cue annotations remain complementary evidence.

There is also a preservation gap in Recordbox's own [cue reader/fingerprint](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/anlz.rs#L589): when PCO2 groups are present, parsing returns before the legacy active-loop flags are read; its fingerprint omits `active_loop`. A switch of only that flag can therefore be invisible to its player-edit detection. Workbench's binary inspector already retains legacy and extended groups separately, and its snapshot comparison now checks captured active-loop states explicitly.

The [`.3EX` reader](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/usb.rs#L1117) checks only a MessagePack map/key prefix. Even a malformed value passes that sniff. The ledger's embedding vectors are not separated audio, and no supplied fixture establishes native STEMS readiness or USB/player use. Workbench therefore retains an Unsupported result even when the prefix matches.

## Catalogs, settings and device workflows

- **Classic versus OneLibrary:** Recordbox still does not update `exportLibrary.db`; classic catalog changes can leave a different catalog view on players. Its unused-file inventory correctly stops when OneLibrary or an interrupted-export journal is present. A future cleanup check must account for every catalog that could reference a file.
- **Hot Cue Bank Lists:** the new library-side bank feature has eight slots. Device export layouts remain unestablished. This does not redefine the native library's A–P hot-cue Kind mapping or prove bank-list migration support.
- **Device properties:** `/.Recordbox/props.json` is the application's own state. Background color/device settings kept there do not prove player-visible OneLibrary properties changed. Retain settings-file CRC evidence separately from player acceptance.
- **Unknown tables:** preserving unknown DeviceSQL pages is preferable to inventing empty replacements, but it does not prove their references remain valid after track IDs change.
- **Strings and units:** the 255-character string cap is Recordbox's writer policy based on observed rows, not a demonstrated universal vendor limit. Whole-second duration rounding and multi-tempo row BPM remain uncertain. Preserve imported key spelling and separate detector indices from stored key names.

## Playlists, XML, paths and history

The new playlist-file support includes UTF-16 BOM text, UTF-8/Latin-1 M3U input, PLS, relative locations and file URLs. Useful workflow fixtures include duplicate tracks in order, empty folders, duplicate names in separate folders, orphan/cyclic parent references, remote file hosts, Windows/UNC paths, escaped Unicode and filenames containing line/tab delimiters. A text export's visible columns cannot be assumed to preserve cues, analysis or every native field.

XML import/export preserves raw extension elements while corresponding fingerprints are unchanged. Round-trip checks should separately assert source IDs, metadata, tempo anchors, cues/loops and unknown elements after an edit. A display title, filename or recycled numeric ID is not durable track identity. The new missing-file relocation flow still selects by name and size; ambiguity handling is useful but does not prove correct audio.

Path normalization depends on the target filesystem: HFS+ decomposition, NFC elsewhere, case behavior and UTF-16 name lengths need explicit profiles. The FAT32 file-size limit is distinct from a particular player's total-path limit. Do not convert these observations into a universal 255-character or eight-hot-cue rule.

Unexpected Unicode input deserves additional failure cases: [audio metadata reading](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/importer.rs#L59) slices a release-date string at byte 4 after checking only its byte length, and [analysis-name discovery](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/export/usb.rs#L1034) similarly slices a directory entry's first four bytes. A multibyte character spanning that boundary is a Rust string-slice panic case. These paths should reject/ignore malformed dates and unrelated filenames safely; the Rust panic was not executed in this review.

History and play count are separate evidence. Recordbox credits a play after 60 seconds or, for shorter tracks, its bounded 90% threshold. A saved zero count therefore does not prove a track was never auditioned. Validate repeated history entries, playlist order, absent tracks, date/time units and atomic history/count updates independently.

## STEMS: improved engine, unresolved association

The previous observation that the engine was unchanged no longer applies at this revision. HTDemucs/Metal code changed substantially; the default recommendation is now base HTDemucs, fine-tuned checkpoints have full hashes, and cache writes use buffered conversion, flush and rename.

The [cache contract](https://github.com/fantuz/recordbox/blob/2cbe1de9bca9042dbab0676c6866ce1f6dcc1988/app/src/stems/mod.rs#L480) remains `PDSTEMS1`: four planar stereo PCM16 sources, 44.1 kHz, a frame count and no source/model association metadata. Workbench's existing bounded reader remains applicable. Source-derived probes confirm that changed same-length bytes within one timestamp second reuse its cache key. Model ID is in the filename, but weight digests and engine/settings revisions are absent from cache identity.

Existing checkpoint files are skipped by the downloader; `model_ready` checks size rather than rechecking their hashes. Whole-track allocation, linear resampling and PCM16 clipping remain relevant to resource and quality validation. Better kernels, a successful cache round trip or sum-to-mix behavior do not independently certify separation quality, reference-engine parity or native rekordbox readiness.

## Next validation priorities

1. Verify audio identity during device reuse and relocation, using same-length/different-content fixtures and source mutation during reads.
2. Exercise recovery failures around the publication boundary, retaining journals until the actual outcome is established.
3. Validate backup manifests, database relationships and confined restoration, including existing-but-different audio.
4. Obtain independent multi-tempo PQT2, populated extended-loop, MessagePack `.3EX`, mixed-catalog and player-edited bank-list fixtures.
5. Measure model quality and cache association separately from binary structure and inference speed.

The new Workbench regressions address demonstrated omissions without importing unsupported native writers or assuming that every claim in Recordbox's research ledger has independent verification.

## Update reviewed on 18 November 2026

The fork advanced another 12 commits to [`2b809082`](https://github.com/fantuz/recordbox/tree/2b809082d65173ce32e1f43ff363833ace71e431).
Most changes implement player audio, effects, mixer, sampler and sequencer behavior.
They do not establish a new native library or STEMS serialization format.

- The [native importer](https://github.com/fantuz/recordbox/blob/2b809082d65173ce32e1f43ff363833ace71e431/app/src/rbimport.rs)
  now checks the tables and columns it consumes before import, with history optional.
  This supports checking capabilities before promising a workflow. Its required schema
  belongs to its importer; it is not a universal requirement to reject every older
  rekordbox library. Workbench retains separate core compatibility and optional evidence.
  The paired importer now also checks its consumed schema before catalog creation,
  naming missing tables/fields instead of leaking a raw lookup error. Regressions
  verify retry safety, original-byte preservation and case-insensitive content fields.
- [Beat-grid half/double operations](https://github.com/fantuz/recordbox/blob/2b809082d65173ce32e1f43ff363833ace71e431/app/src/model.rs)
  now preserve tempo changes and depend on the first beat's phase. A half/double BPM
  disagreement alone cannot prove grid or cue equivalence. Workbench continues to
  report the disagreement for review and preserves the source anchors and cues.
  No automatic tempo normalization or unverified grid writer was introduced.
- The [STEMS cache](https://github.com/fantuz/recordbox/blob/2b809082d65173ce32e1f43ff363833ace71e431/app/src/stems/mod.rs)
  can now remove old `.stems` files to enforce a disk budget, protecting the file just
  written. A previously present cache may later be evicted. Workbench now includes
  this lifecycle advisory in recognized `PDSTEMS1` evidence: retention remains unknown,
  and cache absence cannot establish lost music, a damaged database or missing native
  preparation. A synthetic regression checks that these distinctions remain explicit.
- STEMS mute/solo transitions in preferences changed, including three-part instrument
  grouping and the message shown before analysis is ready. These are runtime player
  states, not additional proof that a cache belongs to a source, has the right model
  weights or works in native rekordbox. They do not justify new readiness assumptions.

This is a pinned static source review. The claimed traced vendor addresses, native
player behavior and inference-quality assertions were not independently executed.
No third-party implementation code or personal libraries were copied into Workbench.

# Workspace, browsing, export references and enrichment delivery

## Executive assessment

PR #53 builds on merged PR #51 and the recovered PR #52. It addresses the six requested areas and adds the agreed export-reference review and metadata filters in the same PR.

The Linux failure was a mismatch between database discovery and audio resolution: finding a Windows database on NTFS did not resolve its drive-letter music paths. Source-scoped **Audio folders** now provide local access for playback, File health and MusicBrainz eligibility. Those aliases never rewrite captured metadata or become export references automatically.

The follow-up audit found two export gaps: advanced recovery could silently use the local file URI when no export prefix was supplied, and destination checks could depend on a path assumption rather than the source library. Recovery now requires a destination prefix before staging. A shared export-reference validator checks manual edits, saved inventory staging, export preflight and both real output writers.

This is a code delivery, not a release or a certification of an import into the Rekordbox application. Original libraries and audio are not rewritten by these mapping or enrichment review features.

## Scope and evidence

| Area | Delivered behavior | Regression evidence |
| --- | --- | --- |
| Workspace reliability and safety | Identity/revision checks held under the workspace lock; stale actions cannot alter another loaded workspace; explicit reload guidance | Raw-client tests for stale Undo, relocation, acknowledgement, rename and export, missing revisions and lock cleanup |
| Import recovery | Interrupted partial cleanup, same-session retry, completed-file reuse, lost-response recovery, concurrent-upload rejection, capacity/cancellation handling and analysis deduplication | Disconnect, finalization failure, capacity, cancellation, partial-file and retry-status tests |
| Failed import publication | A new workspace becomes active only after its saved state succeeds; failed worker submission leaves no phantom task | Injected publication and worker-submission failures |
| Consistent browsing | Complete-result ordering before paging, typed numeric ordering, stable ties and missing-last ordering; source/filter/sort retention and browser navigation | Cross-page API regressions and browser navigation/reload checks |
| MusicBrainz review | Alternative recording retrieval, explicit edition selection, separate recording/release year, album staging and provenance; stale review rejection | No-network provider fixtures for approval, release matching, failed retrieval, disabled access, consent, stale revisions and preservation of later manual edits |
| Mounted audio access | Explicit drive/folder mapping, URI/Unicode/case handling, mount identity checks, cache/scan invalidation and shared playback/eligibility resolver | Synthetic mounted-folder tests, unavailable/replaced roots, symlink/traversal and ambiguous-case cases; browser playback availability |
| Exported references | Source-based Windows/macOS target, explicit choice for mixed/unknown paths, preserved original references, validated deliberate edits and no local-URI recovery fallback | Real XML and encrypted ZIP output readback; original bytes and captured paths remain unchanged; cross-platform and stale-inventory rejection |
| Metadata flags | Colored zero-duration and zero-size filters for captured duplicate review and DJ insights, independent of playability; complete-result counts | Zeros beyond the first page, unknown-versus-zero distinction, healthy comparison siblings retained, CSV filtering and browser reload |
| DJ insights | Four additional transparent preparation/discovery filters | Exact fixture membership and browser selection for each perspective |

## Local access and exported references

| Source library references | Helper access example | Default export target |
| --- | --- | --- |
| Windows `D:/Music/Track.wav` | Linux `/media/max/MusicDisk/Music/Track.wav` | Windows, retaining the recorded reference |
| Windows `D:/Music/Track.wav` | macOS `/Volumes/WindowsDisk/Music/Track.wav` | Windows, retaining the recorded reference |
| macOS `/Volumes/DJ/Music/Track.wav` | A separately mounted directory on Linux | macOS, retaining the recorded reference |
| Mixed or unrecognized references | Any readable local mapping | Choose Windows or macOS explicitly |

The helper can run on Linux; Rekordbox destinations are Windows or macOS. Mounting a Windows filesystem on a Mac does not make the library a macOS library. Hardware brand does not determine the destination.

In **Prepare export → Exported references**, keep **Auto** when detection is unambiguous. Changing the selection is not path conversion: incompatible surviving references must be deliberately reviewed in **File references** before export. Existing saved relocation edits are revalidated at export. Linux mount paths and known playback aliases are rejected as new destination references. Export manifests record the target and the source-path evidence.

For advanced Media inventory recovery, enter a local search folder and a separate exported-reference prefix, such as `file://localhost/D:/Music`. Scanning without the prefix remains possible, but its matches cannot be staged until the destination has been supplied and the scan repeated.

## Practical Linux workflow

1. Keep the NTFS volume mounted.
2. Open MusicBrainz or File health and expand **Audio folders**.
3. Map the recorded Windows prefix to its actual Linux directory, for example `D:/Music` to `/media/max/MusicDisk/Music`. Use the paths on your machine.
4. Check example paths and save the mapping.
5. Re-scan File health and make a fresh MusicBrainz preview.
6. Review **Exported references** before generating XML/ZIP. Retain the Windows target for a Windows library.

## New quick filters

**Zero-duration** means a saved duration of exactly zero. **Zero-size** means a saved size of exactly zero. Missing or unknown values are excluded. The amber/rose badges have text labels and visible selected/focus states; color is supplemental. These are metadata warnings, not a claim that an audio file is physically empty or unplayable. A playable record can have either flag. Duplicate review keeps the other records in each matching group available for comparison.

DJ insights offers these additional perspectives, which can be combined with the metadata flags:

| Perspective | Exact rule |
| --- | --- |
| Missing BPM or key | BPM missing/unknown, or saved musical key blank/unknown |
| Played but unprepared | Positive usage in the selected evidence and zero recorded manual cues |
| Favourites needing cues | At least four personal stars and zero recorded manual cues |
| Long tracks / mixes | Recorded duration of at least ten minutes; duration alone does not identify a mix |

## Validation and limits

All execution, tests, browser automation and package builds run on GitHub Actions. The suite contains 391 unit/API tests covering Linux, Windows and both macOS architectures. Browser checks cover Chromium, Firefox and WebKit with invented metadata and generated silence. MusicBrainz tests use mocked responses or a seeded client cache and make no provider requests. See the final PR checks for execution results at the reviewed commit.

The PR gate requires source checks, browser checks, five package artifacts, native startup checks and package/source consistency. No release is published by this PR.

- Real NTFS mount permissions and the user's disk layout require confirmation on the user's machine; CI uses synthetic local folders.
- Local availability means a readable supported file, not certified audio decoding. Codec and browser support still matter.
- Metadata flags use captured values; refresh the capture after a source-side correction. Physical file-health results remain separate.
- MusicBrainz alternative and release lists are bounded. No automatic selection claims an exact album edition, and personal stars remain manual.
- Actual Rekordbox/Serato restore acceptance, OS code signing and live provider availability remain outside this change.
- Repository rules are documented in [REPOSITORY-SAFEGUARDS.md](REPOSITORY-SAFEGUARDS.md); this PR does not enable account/repository settings.

## Review map

`workspace_safety.py` and `upload_recovery.py` contain the workspace boundaries; `audio_paths.py` centralizes local access; `export_references.py` validates logical destinations; `result_order.py` implements complete-result ordering; `musicbrainz_review.py` owns recording/release approval and provenance. `track_flags.py` defines the zero metadata criteria. Browser acceptance includes `packaging/check_delivery_ui.py` and `packaging/check_reference_flags_ui.py`. User-facing instructions are in [INTERFACE.md](INTERFACE.md).

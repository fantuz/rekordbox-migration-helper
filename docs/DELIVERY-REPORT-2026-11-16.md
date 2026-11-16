# Workspace, browsing and enrichment delivery

## Executive assessment

PR #53 builds on merged PR #51 and the recovered PR #52. It addresses all six requested areas in one reviewable change. The key Linux failure was a mismatch between database discovery and audio resolution: mounting a Windows database did not translate its recorded drive-letter audio paths. Source-scoped Audio folders now provide that translation consistently for playback, file health and MusicBrainz eligibility.

This PR is a code delivery, not a release or a certification of an import into the Rekordbox application. Original libraries and audio are not rewritten by the new mapping or enrichment review features.

## Scope and evidence

| Area | Delivered behavior | Regression evidence |
| --- | --- | --- |
| Workspace reliability and safety | Identity/revision checks held under the workspace lock; stale actions cannot alter another loaded workspace; explicit reload guidance | Raw-client tests for stale Undo, relocation, acknowledgement, rename and export, missing revisions and lock cleanup |
| Import recovery | Interrupted partial cleanup, same-session retry, completed-file reuse, lost-response recovery, concurrent-upload rejection, capacity/cancellation handling and analysis deduplication | Disconnect, finalization failure, capacity, cancellation, partial-file and retry-status tests |
| Failed import publication | A new workspace becomes active only after its saved state succeeds; failed worker submission leaves no phantom task | Injected publication and worker-submission failures |
| Consistent browsing | Complete-result ordering before paging, typed numeric ordering, stable ties and missing-last ordering; source/filter/sort retention and browser navigation | Cross-page API regressions and browser navigation/reload checks |
| MusicBrainz review | Alternative recording retrieval, explicit edition selection, separate recording/release year, album staging and provenance; stale review rejection | No-network provider fixtures for approval, release matching, failed retrieval, disabled access, consent, stale revisions and preservation of later manual edits |
| Linux/Windows audio | Explicit drive/folder mapping, URI/Unicode/case handling, mount identity checks, cache/scan invalidation and shared playback/eligibility resolver | Synthetic mounted-folder tests, unavailable/replaced roots, symlink/traversal and ambiguous-case cases; browser playback availability |

## Practical Linux workflow

1. Keep the NTFS volume mounted.
2. Open MusicBrainz or File health and expand **Audio folders**.
3. Map the recorded Windows prefix to its actual Linux directory, for example `D:/Music` to `/media/max/MusicDisk/Music`. These are examples; use the paths on your machine.
4. Check example paths and save the mapping.
5. Re-scan File health and make a fresh MusicBrainz preview.

Mappings support access on this computer. They do not rewrite the destination paths in a library export; migration reference edits remain a separate deliberate action.

## Validation and limits

All execution, tests, benchmarks, browser automation and package builds are performed on GitHub Actions. The 381 unit/API tests cover Linux, Windows and both macOS architectures. Browser checks cover Chromium, Firefox and WebKit with invented metadata and generated silence; MusicBrainz tests use mocked responses or a seeded client cache and make no provider requests.

The release gate still requires all source checks, browser checks, five package artifacts, native startup checks and package/source consistency. Final CI results are recorded in PR #53.

- The user's actual NTFS mount and default media player require a local smoke check after installation. Synthetic mapped-folder tests do not establish behavior for every NTFS driver or mount configuration.
- “Playable” means a readable regular file with a supported audio suffix. It is not a codec/decode guarantee; launching always rechecks the file.
- Case-insensitive fallback searches at most 4,096 entries per directory; exact path matches do not have that limit. An oversized ambiguous lookup remains unverified.
- Mapping a disconnected/replaced mount requires review; reconnect it and save the mapping again if its device identity changes.
- Provider release lists are bounded. No automatic selection claims an exact album edition, and personal stars remain manual.
- Actual Rekordbox/Serato restore acceptance, OS code signing and live provider availability remain outside this change.

## Review map

`workspace_safety.py` and `upload_recovery.py` contain the new safety boundaries; `audio_paths.py` centralizes local path mapping; `result_order.py` implements typed ordering; `musicbrainz_review.py` owns recording/release approval and provenance. The browser acceptance scenario is `packaging/check_delivery_ui.py`. User-facing instructions are in [INTERFACE.md](INTERFACE.md).

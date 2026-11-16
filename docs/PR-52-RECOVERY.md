# PR #52 recovery and combined feature report

## Baseline and recovery

PR #51 was merged as `837bc9ec6e60cc23df416e184c1586e9f8ff005b`.
The original PR #52 ended at `27790ae12ebeb2ff90452f3aaa4bc87e399333ef`.
Both started from `41b12e588b503269c9886fbe9ee890aaef01798e` and independently changed the same areas. Their broad scope overlapped, but their behavior did not fully overlap. Describing #52 as entirely redundant was inaccurate.

The recovered #52 incorporates current main and preserves both histories in a merge commit. The resulting changes are additive to #51, with corrections described below. No branch history is discarded.

## Feature decisions

| Area | Final behavior | Origin and decision |
| --- | --- | --- |
| Full-batch sorting | Sort before selecting each 50-row page; stable ties; missing values last in either direction | Retain both PRs' common foundation |
| Sort criteria | Original order, title, artist, genre, match status, confidence, candidate title, year, community rating, saved file status | Union of #51 and #52 |
| Sort controls | One complete selector plus column buttons and direction control; accessible labels identify the criterion | Expose criteria previously available only through the API |
| Sort persistence | Retain selection across pagination, background refresh, new batch previews and browser reloads | Preserve #52's preview behavior and explicitly persist preferences |
| File Health | Read saved evidence for the batch snapshot; unscanned tracks are Unchecked; include scan time in API rows | Recover #52 |
| Live playback | Playback buttons continue checking current availability; they do not overwrite the saved status column | Correct #52's visible-status/sort mismatch |
| Auto Serato target | Infer from an explicit destination root, then source convention | Retain #51; correct #52's source-only Auto inference |
| Platform defaults | Preserve compatible roots, otherwise offer a compatible source root or C:/ / /Volumes/DJ | Recover and refine #52 |
| Root validation | Windows drive roots; macOS / or /Volumes/<drive>; reject relative, traversal and control-character target paths | Recover #52's stricter target semantics |
| Destination examples | Show up to five mapped paths in the preview and manifest | Recover #52 and make examples visible in the UI |
| Path collisions | Preserve source aliases, but report and omit distinct POSIX paths that collide on a Windows target, including affected playlist references | Recover target awareness and avoid incorrect relinking |
| Serato implementation | Retain separate serato_paths.py module and #51's API field names | Keep #51's organization |
| README screenshots | Retain the already merged identical WebP files, provenance and source packaging | No duplicate assets |
| Languages | Translate the new sort controls, status explanation and path-example labels in all supported languages | Retain localization coverage |
| Release metadata | VERSION and published releases are unchanged | This is a code recovery, not a new release |

## Evidence and validation

All execution is performed in GitHub Actions using synthetic fixtures. The recovery adds:

- Full 125-row pagination and numeric/candidate/status sorting tests.
- Stable ties, NaN/infinity handling and missing/Unchecked-last tests in both directions.
- Snapshot-scoped File Health evidence and unchanged source snapshot checks.
- Destination-based Auto detection, cross-platform defaults, invalid-root rejection and mapped paths.
- A case-sensitive source to Windows collision test that verifies crate entries are not redirected.
- Browser checks for page-two ordering, refresh, reverse direction, the full sort selector, persistent preferences, saved-versus-live status separation, target switching, examples and preview invalidation.

Existing tests from #51 are retained. Required CI includes Linux, Windows, macOS Intel and Apple Silicon source checks; Chromium, Firefox and WebKit; native packaging and archive parity; and security checks.

The exact completed run results are recorded in the PR description after CI finishes. This document describes implemented behavior and test scope; it does not claim that a pending run has passed.

## Remaining limits

- Saved File Health evidence reflects the last explicit scan. Run File Health again to refresh that evidence; playback buttons can legitimately show newer availability.
- Serato output remains a detached legacy database V2/static-crate draft. It does not write a live Serato or rekordbox database, copy audio, or implement Serato 4.x SQLite migration.
- Binary readback validates the generated format, not acceptance in a real Serato installation.
- macOS comparisons preserve case; actual destination filesystem case behavior requires real-device validation.
- Colliding distinct paths require user resolution before relying on an export; omissions are shown in the preview and manifest.

See [PR #51](https://github.com/fantuz/rekordbox-migration-helper/pull/51) and [recovered PR #52](https://github.com/fantuz/rekordbox-migration-helper/pull/52).

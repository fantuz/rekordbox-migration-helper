# Changelog

## Unreleased

## 1.1.3 — 2026-11-16

This patch makes import retries and metadata editing safer, keeps failed saves from changing the working session, and distinguishes missing metadata from genuine zero values.

- Retry failed or cancelled import analysis with a fresh catalog and publish it only after successful analysis, retaining uploaded inputs and the previous active workspace.
- Reject stale manual metadata saves, resets, bulk normalization and MusicBrainz staging using persistent edit revisions. Bind export approval to those revisions and capture values, history and provenance consistently.
- Restore working decisions, references, names, acknowledgements and derived policy state when saving fails. Preserve the prior inventory file when publication fails.
- Preserve unknown duration and size values through XML/ZIP catalog import, snapshots, statistics and zero-value filters; keep explicit numeric zero distinct from missing metadata.
- Align repository safeguard documentation and the main ruleset template with the verified active configuration, including required checks, native CodeQL protection and no bypass actors.

- Automatically publish reviewed version bumps after the main build and security checks pass, reusing validated packages and rejecting changed source commits, missing release notes or existing tags. Retain the manual release workflow for recovery.

Upgrade notes: reload open browser tabs after updating so they receive the current metadata edit revision. Older imported catalogs that already stored unknown duration or size as zero cannot recover that distinction automatically; reimport the original XML and ZIP to rebuild those values accurately.

## 1.1.2 — 2026-11-16

This update improves editing libraries through Linux mounts while preserving Windows/macOS export destinations, and makes workspace recovery and library review more reliable.

- Bind active-workspace actions to the reviewed workspace and revision, reject stale tabs, and retain the previous workspace when import publication fails.
- Recover interrupted uploads, reuse completed files when retrying the same selection, and deduplicate analysis submissions.
- Add source-scoped Audio folders mappings for Windows libraries on Linux/macOS mounts, shared by playback, File health and MusicBrainz eligibility. Local access mappings never rewrite original metadata or exported references.
- Separate exported Windows/macOS references from local playback aliases. Infer the target from recorded paths, validate deliberate destination edits at staging and in both writers, and require an explicit recovery export prefix. Mixed or unknown sources require a target choice.
- Constrain new local audio mappings to server-selected home/data folders, detected volumes or explicitly configured audio roots; reject sibling-prefix and symlink escapes. Resolve the CodeQL path findings and replace the browser test's URL-prefix assertion with exact parsed-origin checks.
- Sort full filtered collections before pagination across metadata, history, insights and intelligence results; retain per-tab sources, filters and sort choices through navigation and reload.
- Complete MusicBrainz batch sorting, including candidate, confidence, year, community rating and saved file-status criteria. Preserve sort choices through previews and refreshes; keep saved File health evidence distinct from current playback availability.
- Review alternative MusicBrainz recordings and select an explicit release for album or release-year staging. Retain provenance and invalidate stale approvals without changing personal stars.
- Add colored zero-duration and zero-size metadata filters to captured duplicate review and DJ insights, preserving unknown values and comparison siblings. Refresh duplicate availability badges after local mapping changes.
- Add DJ insight perspectives for missing BPM/key, played tracks without manual cues, four-star favourites without manual cues, and tracks at least ten minutes long.
- Add Windows/macOS target profiles to the detached Serato legacy-format draft, including source-aware defaults, validated roots and mapped path examples. Report destination collisions and omit affected records and playlist references instead of linking them to another file. Serato application acceptance remains unverified.
- Complete translations and dynamic language switching for the new MusicBrainz, File health, journal, offline sharing and target-path controls across the supported interface languages.
- Include the user-provided MusicBrainz and library-bubble README screenshots in the verified source package, with their documented provenance.
- Extend failure regressions and browser acceptance for mapped playback, export references, navigation, filters and reviewed enrichment. Document repository safeguards and the separate CodeQL findings check. See the [delivery report](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.2/docs/DELIVERY-REPORT-2026-11-16.md).

## 1.1.1 — 2026-11-15

This update adds advanced relocation and makes current-library enrichment, queued batches and workflow results easier to use.

- Add opt-in advanced relocation in Media inventory: bounded local folder searches, renamed-file tag/duration matching, ranked candidate evidence, unresolved filters, recovery reports, and backup guidance. Stage and undo reviewed unique references in export copies; recheck candidates and reject stale results. No live library or audio deletion is performed.
- Keep MusicBrainz batches visible in queue order with individual progress and recent completed results. Retry stalled browser status requests, prioritize the running batch in the banner, and release queue reservations when a job is cancelled before its worker starts.
- Rename the enrichment section to Enrich current library. Default to the loaded XML/ZIP environment, offer connected Rekordbox sources, and prepare their metadata locally in the same workflow. Block new batches without an available collection while retaining historical results for review.
- Default new batches to playable tracks, with a deliberate unavailable-audio override, excluded counts, and a second availability check before new provider lookups. Show loading, empty and retry states in category dropdowns; share concurrent requests and cache immutable target lists.
- Keep MusicBrainz progress visible while scrolling, open results directly, preserve dismissal until the queue changes, and respect reduced motion. Add compact side-by-side Rekordbox and Serato export cards on Files & workflow.
- Scroll Browse playlist results into view in Library intelligence and move keyboard focus to the new list without leaving the page.
- Move Chart to playlist into the Library intelligence tool grid as its sixth card, retaining explicit fetch/review controls and bounded result scrolling.

## 1.1.0 — 2026-11-15

This update brings whole-collection sorting, clearer file-health evidence, queued MusicBrainz enrichment, instant personal-star edits, offline bubble charts and opt-in source journal monitoring.

- Sort saved native duplicate-review and file-reference results across the complete filtered collection before pagination. Keep stable page boundaries, accessible headings and loading feedback.
- Add a Playable? column and Not playable filter to File health, with global indexed sorting. Missing and Inaccessible count as No; Unverified and unchecked records remain distinct. Give file-status badges clearer coloured outlines.
- Queue up to eight independently approved MusicBrainz batches through one shared provider worker, with aggregate progress and cancellation. Broaden text matching with bounded fallback searches and up to 20 candidates while retaining exact ISRC lookup and manual match approval. Acoustic fingerprinting is not included.
- Add instant 0–5 personal-star controls alongside the existing colour palette. Save and reset working edits without unlocking advanced fields; captured sources and original audio remain unchanged.
- Add interactive, keyboard-accessible offline bubble charts to shared HTML explorers and minisites using the existing disclosed metadata. Public summaries remain aggregate-only. Restrict page navigation to known local destinations.
- Add off-by-default DB/WAL/journal activity monitoring for saved modern source captures. Wait for stable file metadata before a new private snapshot, throttle refreshes, and discard stale responses after monitoring or selection changes. This detects file activity, not uncommitted transactions or guaranteed live database consistency.
- Increase optional recursive source inventory to 1,000,000 entries or 120 seconds while preserving depth limits, cancellation and unknown evidence for unscanned files.
- Document Serato 4.x library-layout evidence and the limits of the legacy-format draft exporter. Serato 4.x import compatibility remains unverified.
- Extend synthetic regression coverage for global sorting, enrichment queues, instant ratings, offline navigation and delayed journal responses; close the journal test's SQLite connection before Windows cleanup.

## 1.0.9 — 2026-11-15

This stable update adds sortable results and whole-library file-health investigations, simplifies targeted MusicBrainz enrichment, and improves snapshot edition timestamps and playlist/file availability evidence. Source music and rekordbox libraries remain unchanged.

- Add accessible click-to-sort headers to bounded result tables, with a file-status column beside local playback controls. Sorting in paged tables affects displayed rows; File health uses indexed, library-wide server sorting.
- Add opt-in, cancellable local File health scans with SQLite-backed status totals, search, filtering and global sorting. Distinguish not-yet-checked records from scanned Unverified evidence; no original media or database is modified.
- Simplify MusicBrainz enrichment with a quick target selector for balanced genres, deterministic random, specific genre/album/year/playlist and missing metadata, plus explanatory parameters and unchanged consent/staging safeguards.
- Fix storage-reconnection focus refresh to bypass the SQLite audio-status cache (with focus-event throttling); distinguish absent native playlist membership from genuinely empty playlist collections and keep unknown membership counts unverified.
- Record exact snapshot save times with timezone-aware UTC timestamps and display local date/time/zone across snapshot selectors, keeping older date-only records compatible.

## 1.0.8 — 2026-11-15

Improve local-library access, compact navigation guidance, MusicBrainz enrichment, duplicate review density, and persistent advisory file-health evidence. No changes are made to original audio or Rekordbox databases.

- Add bounded SQLite-backed local audio-file evidence shared by playback availability and duplicate comparisons. Display playable, missing, inaccessible and unverified classifications with a refresh action and advisory filtering; no source modifications or automatic deletions.
- Consolidate temporary-copy and page-specific information banners into the shared, responsive header between titles and selectors. The Play history, Collection statistics and Library lab explanations retain translated content and working help links behind Details.
- Highlight the local-library entry on the home page and shared header; use category-only, smaller multiline bubble labels.
- Add shared loading feedback after 200 ms, elapsed time and a one-second waiting notice, with a clearer message after 30 seconds without a response or progress change. Keep background status checks quiet and clear feedback after completion, cancellation or failure.
- Remove the permanent selection-like accent from Saved investigations; mark only the current sidebar page as active, preserving a distinct keyboard focus outline.
- Give MusicBrainz a dedicated page under Enrich, with its own snapshot selector and consistent shortcuts, journey steps and background result links.
- Give captured-library duplicate candidates more width and denser rows, compare records in compact cards, and keep review actions above the records.

## 1.0.7 — 2026-11-15

Features already included in the previously published v1.0.7 release are recorded here rather than attributed to v1.0.8.

- Add Japanese, Arabic with right-to-left layout, European Portuguese and Brazilian Portuguese to the web interface and offline explorers; preserve regional preferences and mixed-script library metadata.
- Connect captured master.db sources to statistics, native duplicate review, recorded file references and saved play history without requiring XML/ZIP imports.
- Add granular, reversible saved-investigation cleanup with dependency previews and restore support.
- Space the shared collection label and selector, emphasize the direct snapshot action, and reduce the temporary-copy banner to one sentence.
- Test native source switching, unknown metadata, history ordering, cleanup/restore and immutable inputs with synthetic regression fixtures.
- Hardened database discovery and direct-file selection, with explicit legacy v5 companion-file inspection and stricter XML ratings/key handling.
- Added larger resumable MusicBrainz background pilots, saved-batch progress and separate tag evidence.
- Added playlist contents, collection lenses, repeated-history detail, reviewed ListenBrainz chart M3U8 export and a detached Serato database/crate draft.
- Added local default-player controls across live track views, compact metric cards and colour-coded navigation.
- Added a maintained factual README feature inventory and synthetic interface screenshots generated by GitHub browser checks.
- Limited screenshot examples to 12 explicitly invented records; release verification rejects audio files and recognized library databases.
- Keep duplicate review in split panes or an accessible side drawer, retain its actions in view, and bring chart/report actions and investigation previews ahead of long lists.


## 1.0.2 — 2026-11-13

This update adds guided library workflows, clearer access to advanced tools and shareable offline summaries with explicit privacy choices.

- Add resumable migration and integrity journeys with explicit evidence states and shared collection context.
- Promote offline sharing with public aggregate, selected-list and private presets, field disclosure and XML-only input.
- Make snapshot comparison, metadata editing and MusicBrainz easier to discover with labelled accent cards.
- Add playlist-overlap, saved-session progression, collection-evolution and staged-duplicate-impact views.
- Add per-operation cooperative cancellation, cached duplicate pagination and 33k/100k GitHub performance checks.
- Reuse verified release artifacts only for the exact trusted main commit and version, and cache the pinned Linux runtime.
- Add 139 translated interface messages across German, French, Italian, Spanish, Greek, Polish, Czech and Russian, keeping all nine interface languages complete.
- Refresh validation guidance and distinguish user-reported success from unverified compatibility.

## 1.0.1 — 2026-11-13

This update adds a self-contained Linux application, clearer review of duplicate groups and step-by-step instructions for preparing and restoring library copies.

- Self-contained Linux x86-64 TAR.GZ with bundled Python/dependencies, a glibc 2.28 build baseline, Ubuntu 22.04 executable checks and an XDG workspace. Linux source remains available.
- Five-archive release verification and download tables include the new native Linux package.
- Source discovery reads location fields from rekordbox Agent options and saved preferences, finds external Master folders, and maps Windows/Mac profile hints inside user-mounted volumes without mounting disks or exposing unrelated options.
- Multi-copy review lists all members, supports donor exclusions, previews accumulated cue/rating conflicts and direct-match requirements, and stages compatible donors with reversible batch history.
- Prominent, translated ZIP/XML creation and restore instructions link to a bundled step-by-step guide. The guide distinguishes native restore from alternative XML import and explains separate audio preservation.
- English interface and Markdown spelling checks run in GitHub CI. Native builds run independently, with macOS 26 used for Apple Silicon validation. A Windows 11 restore report is recorded with the approximate user-recalled version and its limits.

## 1.0.0 — 2026-11-13

The first 1.0 milestone brings the current library analysis, cleanup preparation and migration tools together in Windows x64, Mac Intel, Mac Apple Silicon and Linux source downloads. Native rekordbox ZIP restoration remains experimental and needs an isolated Windows restore test.

- Library tools include duplicate/cue review, reference and cloud-copy checks, snapshot comparison, analysis/STEMS audits, history browsing and genre/BPM preparation coverage.
- DJ insights, tonality/tempo statistics and offline HTML/ZIP metadata explorers support reviewing a collection without sharing audio or private comments.
- Nine interface languages, retained decisions/reports and acknowledged temporary-copy cleanup support repeatable local workflows. MusicBrainz remains an optional, explicitly enabled proof of concept.
- Release notes now list all six downloads directly: four platform archives, checksums and the complete commit log with full messages. Linked commit summaries include merged branches and a comparison with the previous stable release.

- Colour cloud: explicit loaded-library capture, visible source/loading/empty states, bounded group-detail calculations and a large-library regression.
- Bubble maps: expanded canvas, stable wider circle spacing and a fixed horizontal category-detail panel.
- Readability: grouped, resizable text navigation, compact header, balanced summary cards and larger duplicate-review controls and comparison details.
- File view: comments open directly, labelled colour palette saves without unlocking, and private export recaps retain saves and resets. Working colour edits map to verified native IDs or documented XML RGB values.
- Language changes preserve inspected comparisons, keeper choices and draft options; removed comparisons use a valid fallback.
- Centred operation progress blocks navigation during long tasks. Native ZIP copying and verification report progress inside large members.
- Download badges follow the project platform layout; new package/artifact names omit the preview suffix and release notes generate platform links.
- Additional translation-catalogue, locale/storage, responsive-layout and three-engine browser checks run on GitHub alongside native package validation.

## 0.4.5 — 2026-11-13

- DJ Insights: most/least played, preparation opportunities, rediscovery and repeatable random picks, with separate saved-count, history-entry and session evidence.
- Interactive library bubbles and Colour cloud: drill into genre families, artists, years, musical keys and saved track colours; size by track count, recorded usage or duration; save a personal colour legend and export SVG/CSV reports.
- Tonality & tempo: saved-key coverage, BPM histograms, mean/median/range and duration statistics. Unknown values stay explicit.
- Per-track File view: freely staged Comments in a collapsed editor, with explicit unlocking for other metadata and guarded XML/native-copy export.
- Library lab: snapshot cue/rating/playlist comparison, metadata consistency, collection coverage and analysis/STEMS asset audits. Retained snapshots also support play-history browsing and offline HTML/ZIP metadata explorers.
- Opt-in MusicBrainz proof of concept: bounded sampling, selectable request pacing, separate local evidence and a disable flag. No background provider queries.
- Temporary analysis copies are removed on acknowledged shutdown; reports, review decisions, comments and deliberate exports remain available.
- Automatic native builds for pull requests and `main`, automatic preview releases for version tags, a web release form, checked package/source digests and dependency audits. Windows x64, Mac Intel, Mac Apple Silicon and Linux source downloads are included.

Native ZIP restoration inside a licensed Windows rekordbox instance still needs real-world validation. Mac packages are ad-hoc signed and are not notarized. Keep an untouched rekordbox backup before preparing transformed copies. Private libraries and audio are not distributed.

## 0.4.0 — 2026-11-12

Initial public portable preview: local library analysis, duplicate/cue review, copy preparation and Windows/macOS/Linux packages. Later library-lab and DJ-insight features are included in 0.4.5.

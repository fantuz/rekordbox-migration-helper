# Changelog

## Unreleased

## 1.2.0 — 2026-11-19

This release connects Library Workbench to Dropbox for cloud-file verification and individually approved downloads into the normal local Dropbox folder.

- Add a dedicated Dropbox connector page with browser-based OAuth/PKCE, public app-key setup and registration guidance. Offer supported operating-system credential storage or a session-only connection; Workbench does not collect Dropbox passwords or app secrets.
- Map a detected local Dropbox folder to an authorized account, remote folder and namespace. Check saved library paths through bounded, paginated metadata listings without reading audio or changing sync settings. Keep unseen entries unverified when a listing is incomplete, and preserve prior evidence after a failed recheck.
- Browse indexed remote evidence with whole-collection status filters, Unicode search and pagination. Keep local availability separate from remote presence and invalidate evidence when the account, source or folder mappings change.
- Download one absent file after a short-lived filename, destination and size confirmation. Recheck the account, library, mapping and remote revision; verify byte count and Dropbox content hash; stage outside the Dropbox tree; and publish the complete file without overwriting existing files or placeholders. Existing cloud placeholders retain the individual Play confirmation flow.
- Add the Dropbox setup and confirmation interface in all 13 supported languages, a File health shortcut, reviewed screenshots and the registration guide. Harden credential cleanup, callback-log redaction, profile isolation and folder-boundary checks.
- Expand metadata, consent, transfer-failure and filesystem integrity tests, plus real-HTTP Dropbox workflows in Chromium, Firefox and WebKit. Stabilize the existing OneTagger persistence browser test by completing its background poll before a deliberate reload, retaining all error assertions.

Release scope: [PR #77](https://github.com/fantuz/rekordbox-migration-helper/pull/77). Dropbox account access requires a registered public app key and browser authorization on the computer running Workbench. Automated provider responses are synthetic; live account, team-namespace and desktop selective-sync behavior remain unverified. Google Drive account integration remains deferred; its existing local discovery and File health filters remain available. Downloads require existing local parent folders and same-filesystem private staging, and are limited to 8 GiB per file. Dropbox controls reconciliation of the final local file; Workbench does not start bulk downloads or change sync policy. Library snapshots, captured references and original databases remain unchanged. Reload open browser tabs after upgrading. See the [Dropbox setup guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.2.0/docs/DROPBOX-CONNECTOR.md) and [cloud file-health guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.2.0/docs/CLOUD-FILE-HEALTH.md).

## 1.1.11 — 2026-11-19

This release makes cloud-file checks safer, streamlines collection exploration, and gives OneTagger bridge its own enrichment page.

- Give OneTagger bridge its own Enrich sidebar page and direct Workflow map entry. Keep its snapshot picker in the compact header controls, provide Audio folders on the bridge, and preserve selections when navigating between enrichment tools.
- Add colored Dropbox and Google Drive path filters to File health, metadata-only cloud-placeholder evidence, and fresh single-track confirmation before opening cloud-managed audio. Absent cloud paths retain unknown remote availability; scans neither open audio nor query providers.
- Move Collection context and tool snapshots into two default-collapsed orange/pink controls above the page header, retaining their selectors and actions, including inside expanded Bubble maps.
- Align every Bubble filter in one responsive panel, keep numeric ranges together, summarize active criteria, and collapse after successful Apply. Preserve unapplied drafts when changing key display.
- Display recognized musical keys alphabetically, in Camelot or Open Key notation, grouping equivalent tags without rewriting their source values. Share the preference with key filters, tonality tables, File view and Library intelligence sessions; retain source-format counts.
- Add release-year and saved-genre histograms to Collection statistics and a compact shared Hide unknown choice. Exclusions apply independently per chart, preserve known zero values and show displayed/excluded totals.
- Extend real-server browser regressions and synthetic cloud-attribute, cache-migration, key-grouping and playback-consent tests. Document Dropbox metadata API and local-client limitations; actual remote presence and hydration remain unverified.

Release scope: [PR #75](https://github.com/fantuz/rekordbox-migration-helper/pull/75) and [PR #76](https://github.com/fantuz/rekordbox-migration-helper/pull/76). Cloud labels and placeholder attributes are local evidence; Dropbox/Google Drive account authorization and remote file-presence checks are not implemented. Scans do not open audio, while opening a cloud-managed track requires fresh individual confirmation. Key display changes preserve original tags. Native rekordbox restoration and actual Windows/macOS cloud hydration remain unverified. Reload open browser tabs after upgrading. See the [cloud file-health guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.11/docs/CLOUD-FILE-HEALTH.md), [interface guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.11/docs/INTERFACE.md) and [OneTagger handoff guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.11/docs/AUDIO-MATCHING-AND-ONETAGGER.md).

## 1.1.10 — 2026-11-18

This release makes library preparation and recovery easier to follow, adds local cloud-location discovery, and improves Library bubbles navigation.

- Start new sessions on a clickable workflow map connecting inputs, transformation, enrichment, verification and outputs. Returning views and direct links remain available, with guidance about the evidence each feature needs.
- Offer metadata preparation after native, XML-only or paired XML+ZIP loading. Reuse the matching saved collection snapshot, preserve the selected source for queued work, and keep optional file-availability scanning unchecked. Bubbles and File health require no additional manual Rekordbox export.
- Clarify which loaded XML+ZIP workspace Media inventory searches. Remove incorrect search folders without deleting files, group optional path mappings, restore successful search roots, identify previous results after settings change, and keep drafts separate by workspace. Checking a restored destination requires loading that destination.
- Put bubble counters before filters, grouping controls and clickable breadcrumbs. Open legend categories with a click or Enter/Space, preview evidence on hover/focus, and show 15 complete desktop rows with contrasting scrollbars and a translated scroll hint. Keep zero-area categories accessible and preserve source metadata and circle-area ratios. Let shared header controls wrap at intermediate desktop widths.
- Discover Dropbox and Google Drive locations from bounded local configuration and operating-system registrations, including custom Dropbox team/customer folders and multiple accounts. Skip unavailable or online-only roots and links; do not sign in, mount drives, move music or start a scan automatically. Users can inspect locations and explicitly select search roots or a library folder.
- Suggest possible relocated library folders from recorded database paths and matching trailing directory components, retaining ambiguity and unknown identity. No old path means no relocation claim; path similarity does not verify database or audio identity. Library discovery remains separate from audio-reference relocation. Keep detected roots within the existing server-selected audio-access boundaries and handle Windows path casing and macOS system aliases.
- Check the paired importer's consumed tables/columns before catalog creation, with readable errors, case-insensitive content fields and safe retry/source-preservation regressions. Incorporate the latest pinned Recordbox findings: `PDSTEMS1` caches may be evicted, sampler/sequence WAV files are derived audio, and runtime FX/preferences do not establish native fields, STEMS readiness or migration equivalence.
- Extend real-server Chromium, Firefox and WebKit coverage for preparation, inventory, cloud discovery, keyboard/mouse bubble navigation, responsive/RTL layouts and unchanged source bytes. Check scrollbar contrast and wheel scrolling across native scrollbar policies. Keep new controls translated across all 13 interface languages and refresh synthetic workflow screenshots.
- Use the standard Ubuntu archive for browser/compiler dependency downloads, including hosted-runner mirror-list files, to avoid regional mirror stalls while retaining all source, native-package and security gates.

Release scope: merged [PR #72](https://github.com/fantuz/rekordbox-migration-helper/pull/72) and [PR #73](https://github.com/fantuz/rekordbox-migration-helper/pull/73), together with prior improvements. File health checks accessibility of nonempty readable audio files; Advanced Media inventory separately reads tags/duration. Neither establishes full decoding, audio identity or native STEMS readiness. See the [workflow guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.10/docs/WORKFLOWS.md), [cloud discovery guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.10/docs/CLOUD-DISCOVERY.md) and [Recordbox integrity review](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.10/docs/RECORDBOX-INTEGRITY-REVIEW.md). Reload open browser tabs after upgrading to receive the updated interface.

## 1.1.9 — 2026-11-17

This release adds reviewed label/composer imports and a real OneTagger producer-to-importer test, and includes the report-review and integrity improvements shipped in 1.1.8.

- Accept version-2 OneTagger reports with optional label and composer values. New selection manifests request version 2; version-1 reports and older producers remain supported with their original five fields. Missing tags never authorize clearing library values.
- Independently read label/composer, offer unchecked field choices and stage only explicitly approved values. Apply those values through XML Label/Composer and native LabelID/ComposerID lookups with independent export verification. Composer support reads existing tags; it does not add composer lookup to providers.
- Reduce repeated metadata reads when several library IDs reference the same file. Reuse a read only within the current import or staging operation, validate file state on every reuse and recheck it before committing. Read shared native artist/composer lookups once during export verification.
- Require a pinned production OneTagger batch to produce actual JSON for the Helper importer in CI. Test version 2, legacy negotiation, provider fallback, cancellation, explicit staging and stale-file rejection with an offline provider. A separate 500-reference regression verifies read reuse and invalidation after file changes.
- Retain the 1.1.8 review protections: bounded raw JSON, provider/run evidence, partial outcomes, explicit field approval, stale-review blocking, private review downloads and saved evidence across restarts, with controls in all 13 interface languages.
- Retain the 1.1.8 integrity checks for active-loop and captured metadata changes, playlist moves and type conversions, renumbered parent IDs, non-PMAI `.3EX` variants and bounded PQT2 counts/fractions. Keep unsupported evidence and native STEMS readiness explicit.
- Extend Chromium, Firefox and WebKit checks for label/composer while retaining version-1 fixtures. The source archive includes both shared report fixtures and the producer-to-importer test runner.

New release scope: merged [PR #70](https://github.com/fantuz/rekordbox-migration-helper/pull/70), together with all prior improvements. Only approved metadata fields are staged by the Helper; personal stars, BPM, musical key, grids, cues, play counts, playlists, references and audio bytes remain outside these handoff edits. A compatible OneTagger producer is required for version-2 fields. See the [versioned results guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.9/docs/ONETAGGER-RESULTS.md) and [integrity review](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.9/docs/RECORDBOX-INTEGRITY-REVIEW.md). Offline provider tests do not certify live matching, native restoration or physical players.

## 1.1.8 — 2026-11-17

This published release introduced verified OneTagger report review and broader preparation-workflow integrity checks.

- Extend snapshot comparisons to known active-loop switches, captured title/BPM/key/play-count/analyzed values, playlist moves and folder/smart/manual conversions. Resolve parent identities across renumbered IDs and retain unknown evidence without assuming a change.
- Keep non-PMAI `.3EX` variants Unsupported instead of falsely reporting corruption. Check the observed PQT2 revision's count/body agreement and fractional ranges; retain checksum and unsupported semantics as unverified.
- Add synthetic regressions and real-server Playwright checks for comparison filters/downloads, duplicate playlist members, folder/ZIP format parity and saved reports across restart. Document the broader [Recordbox integrity review](docs/RECORDBOX-INTEGRITY-REVIEW.md), public fixture evidence and outstanding identity/recovery/backup/STEMS questions.
- Import version-1 OneTagger tagging-results JSON into the existing field-review workflow. Require the exact saved selection, membership and paths; independently verify final file state and tags. Retain application/run identity, before/after tags, fallback-provider evidence and partial/cancelled outcomes without automatically staging edits.
- Accept bounded raw JSON files, reject duplicate keys and nonfinite numbers, and read year components from stored release dates. Add review downloads, verification counts and outdated-review notices. Recheck selected files before committing staged fields and roll back changes if files changed during staging.
- Translate the new controls across all 13 interface languages and extend shared-fixture, API and real-server Playwright checks for report import, stale evidence, explicit field selection, input preservation and restart recovery. Personal stars, cues, grids, BPM, keys, playlist membership and recorded references remain outside this report-import contract.

Release scope: merged PRs #67, #68 and #69. Published from `eaef775`; this changelog section records the already published release without changing its tag or packages.

## 1.1.7 — 2026-11-17

This update adds STEMS workflow checks for containers, provider caches and source eligibility, with saved evidence reports and expanded cross-platform validation.

- Add **Library lab → STEMS workflows** with source-only advisories or selected folder/ZIP inspection, declared session/engine/model profiles and provider-specific Apple Music/Spotify restrictions. Preserve private native service evidence without guessing numeric provider IDs; missing evidence stays Unknown.
- Recognize NI-style `.stem.m4a`/`.stem.mp4` containers using bounded metadata, stereo track/enable flags, sample rates and presentation/edit-list checks. Keep sample-entry types, codec-profile uncertainty, generic multistream files and native acceptance distinct.
- Inspect RB Stems Plus cache markers, eight-channel FLAC STREAMINFO, RBD1/RBD2 descriptors, preparation manifests and retention sets. Check expected chunks per cache root/ZIP, source metadata changes and declared model/profile mismatches; report unavailable locations and support rechecking after reconnect. Never combine split caches to claim completeness.
- Add five globally applied report filters, full filtered downloads, translations across all 13 interface languages and a documented evidence profile. Extend unit/API and existing real-server Playwright pipeline checks for STEMS workflows, pagination, stale/missing/split caches, cancellation, scope/privacy boundaries, disconnect/reconnect and saved reports across restart.
- Correct explicitly selected source-root aliases on macOS and close prefix probes before metadata parsing on Windows so replacement checks can run. Keep budget-limited cache headers Not checked and unread expected chunks Unknown instead of reporting corruption or missing chunks.

Release scope: merged [PR #65](https://github.com/fantuz/rekordbox-migration-helper/pull/65). Native STEMS readiness remains Unknown; consistent manifests and recognized structures do not establish audio identity, separation quality or hardware compatibility. See the [STEMS workflow guide](https://github.com/fantuz/rekordbox-migration-helper/blob/v1.1.7/docs/STEMS-WORKFLOWS.md) for supported evidence, limits and recovery checks.

## 1.1.6 — 2026-11-17

This update adds format and STEMS inspection, native source insights, and more precise backup and tempo evidence.

- Add **Library lab → Formats & STEMS**, with bounded ANLZ framing, grid/tempo and repeated cue-group checks, player-settings CRC validation, classic catalog headers, separate OneLibrary detection and recognized Recordbox STEMS cache structure. Keep source association, unsupported formats and native STEMS readiness explicit.
- Add **Native source insights** for captured composer/remixer/original-artist/lyricist relationships, raw analysis flags, cue anomalies and bounded smart-playlist definitions. Resolve key and signed MyTag references without executing rules or guessing BPM-rule units.
- Combine report section, severity, validation and text filters before pagination and full JSON downloads. Expose captured native evidence in single-track details and localize the new controls across all 13 interface languages.
- Correct player-settings `.DAT` classification in backup coverage; report device catalogs separately and verify captured `.3EX` members individually. Keep ZIP checksum success separate from invalid settings payloads.
- Add synthetic format/source regressions and real-server Playwright checks for the new sections, filters, source preservation, saved reports, native details and mobile controls in the existing CI workflow.

- Check exact backup member paths and retain tempo evidence from XML-only collections.
- Keep smart playlists with unavailable rule definitions visible, distinguish STEMS inspection limits from corrupt lengths, and leave truncated grid tempo comparisons inconclusive.
- Link OneTagger and its existing reviewed M3U handoff workflow from the README.

Release scope: merged PRs #61, #62 and #63. Format inspection and checksum results do not certify native STEMS readiness, rekordbox restoration or physical player compatibility. Unsupported or incomplete evidence remains explicit; original libraries and audio are not rewritten by these inspections.

## 1.1.5 — 2026-11-16

This update adds migration-readiness reports and real-server browser checks, strengthens original-input verification, and rejects invalid metadata before it can block an export.

- Add **Library lab → Health & coverage → Migration readiness**, with saved evidence reports and full JSON downloads. Controls are localized across all 13 supported interface languages.
- Inspect backup ZIP coverage for database, analysis, artwork, settings and music members; identify missing captured analysis references. Optionally verify member SHA-256 and ZIP CRCs within a 512 MiB read budget, leaving unread members explicitly unverified. No files are extracted or restored.
- Add a versioned CDJ-2000NXS2 format-family profile, FAT32 single-file size checks, and recorded destination-name advisories. Missing evidence stays Unknown; these metadata checks do not certify decoding, firmware, a device database or physical playback.
- Compare saved BPM with newly captured XML average/grid tempo, highlight possible half/double-tempo disagreements, and list recognized saved keys in Camelot wheel order while retaining original notation. These reports do not analyze audio or rewrite BPM, keys or beatgrids.
- Record full-file SHA-256 fingerprints at import and verify content on resume and before/after export. Reject XML/ZIP changes even when file size and modification time are preserved; retain known content identities when reattaching originals. Hashing supports cooperative cancellation.
- Reject XML-invalid characters in all exportable text overrides before committing them, preserving prior values, edit history and revisions on rejection.
- Bound completed in-memory job results to 256 records or one hour, protect active jobs and completion callbacks, and synchronize task insertion/pruning. Saved reports, decisions and exports remain available in their history views after a transient job record expires.
- Run real-server Playwright workflow-integrity checks in Chromium CI, covering competing tabs, scoped edits, restart/reset persistence, export checksums and source preservation. Add migration-report acceptance, invalid-edit rejection, responsive controls, and first-table/search timing checks on a 5,000-track synthetic snapshot.

Release scope: merged [PR #59](https://github.com/fantuz/rekordbox-migration-helper/pull/59). Backup coverage is not a restore test. Player profiles and tempo/key reports are read-only advisories. Older/native-only snapshots may lack comparative XML tempo evidence; capture fresh matching inputs when needed. Existing workspaces without full-file hashes validate their recorded XML digest/native pair identity before upgrading. Full-file verification adds disk reads for large backups, and an expired task ID returns 404 without deleting persisted outputs. Real rekordbox restoration and physical player compatibility require separate validation.

## 1.1.4 — 2026-11-16

This update strengthens access to audio on mounted libraries, makes MusicBrainz matching more auditable, adds reviewed OneTagger tag transfers, and independently verifies exported libraries before publication.

- Cache bounded case/Unicode directory resolution for mounted Windows audio and reject replaced mapped volumes without falling back to another recorded local file.
- Label nonempty readable files Accessible while keeping existing `playable` API keys; empty files are Unverified and cannot be launched.
- Preserve original tags, search cleanup steps, every MusicBrainz query attempt and candidate disagreements, with version checks in both directions.
- Add a local OneTagger M3U/manifest handoff, tag rescan and explicit field-level review with stale-edit checks, atomic sidecar staging and provenance.
- Independently read XML/native ZIP outputs against original-input expectations and frozen decisions before publication, covering metadata, references, cues and playlist order. Add encrypted mutation regressions and browser coverage for the handoff workflow.
- Verify resolved native metadata lookup values as well as track references. Render OneTagger selection and review values as text, with browser regressions for HTML-like tags; exercise mounted-path caching on case-insensitive volumes too.

Release scope: merged [PR #57](https://github.com/fantuz/rekordbox-migration-helper/pull/57). Local OneTagger handoff requires the user to run OneTagger separately; synthetic acceptance covers handoff and tag read-back but does not certify a complete installed OneTagger or rekordbox restore workflow.

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

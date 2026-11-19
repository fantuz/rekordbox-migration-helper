# Interface and workflow

Use the language selector for interface labels, short guidance and confirmations. MusicBrainz batch states, provider counters, result sorting, file-health statuses, journal-monitor guidance and offline bubble selectors use the shared translated catalogue. Dynamic labels refresh with language changes while preserving selected bubble dimensions; user-provided tags, paths, identifiers, provider text and technical diagnostics remain unchanged. Library metadata, file paths, cue labels, technical identifiers and raw diagnostics retain their source values. The full project documentation currently uses English. The Documentation page renders the bundled Markdown; it does not download documentation or images from the internet.

## Import and source analysis

New browser tabs open a clickable **Workflow map** connecting inputs,
transformation, enrichment, checks and outputs. Tool links remain in the
sidebar, and returning tabs retain their selected page. A preparation card and
post-load prompt explain internal snapshots and optional scans. See
[workflow requirements and inventory scope](WORKFLOWS.md).

Create an untouched rekordbox Backup Library backup before preparing transformed files. Preserve audio separately if it is excluded. For XML/ZIP review, create matching exports consecutively without intervening library changes. Uploaded files are temporary local analysis copies. The existing-file option reads originals in place and requires them to stay unchanged.

Source analyzer can instead inspect a database folder or collection XML. Close rekordbox and pause Cloud Library Sync for capture. Windows and Mac suggestions are optional; manual paths also work on Linux for a user-mounted filesystem. Read [migration](MIGRATION.md), [compatibility](COMPATIBILITY.md) and [capture/asset/history procedures](DISCOVERY-ASSETS-HISTORY.md) for details.

File health separates **Local access** from **Cloud presence**. **Yes** under
Local access indicates a successful local file inspection; **No** groups
Missing and Inaccessible. **Unknown** represents Unverified; records never
inspected remain Unchecked and must not be treated as No. **Scan local files**
checks the filesystem, while **Check remote files** on a connected provider
checks cloud metadata for the same saved collection. Cloud presence shows that
saved provider result and check time without making a new cloud request when
the page opens. Remote presence can be known while local access stays Unknown.
Local filtering and sorting run against the complete scanned index before the
50-record page is selected. Dropbox and Google Drive path filters use colored
labels. Cloud-only placeholders and absent cloud paths remain distinct from
confirmed local absence. Playback independently rechecks the path and requires
a fresh one-track confirmation for cloud-managed audio. See [cloud file health
and metadata API findings](CLOUD-FILE-HEALTH.md). These are not decoding or
audio-integrity tests.

**Cloud connections** guides provider selection, account authorization, source
selection and location review. Detected candidates retain their provenance;
selected-file download folders can also sit outside a provider desktop root.
A complete metadata preview must match the selected library before **Attach**
saves the relationship. Dropbox and Google Drive remain separate attachments,
and **Detach** does not remove files or disconnect the other provider. See
[connection guidance](CLOUD-CONNECTIONS.md).

**Dropbox connector** and **Google Drive connector** provide explicit
metadata-only checks for their attached collection. Register the provider
client, authorize in its browser screen, and choose **Check remote files**.
Remote presence and local availability are separate evidence. An individual
download requires its own confirmation; existing placeholders use the
individual Play flow. See [Dropbox setup](DROPBOX-CONNECTOR.md) and
[Google Drive setup](GOOGLE-DRIVE-CONNECTOR.md).

In saved native snapshot **Duplicate review** and **File references**, click a sortable column heading to order the entire filtered collection, not only the visible 50 rows. Click again to reverse direction; changing the column resets to page one, and Previous/Next retain the chosen sort. The arrows indicate direction, while the Review action column is not sortable. Large requests use the shared Loading / Waiting feedback without locking the page. File health independently sorts its full scanned SQLite index before paging.

The **Enrich** sidebar group contains separate **MusicBrainz** and
**OneTagger bridge** pages. The Workflow map opens OneTagger directly. The
bridge retains its own snapshot, folder mappings, saved handoffs and report
review without loading the MusicBrainz page.

## Compact collection navigation and charts

**Collection context** and **Collection snapshot** sit in a slim row above the
page header, collapsed by default. Orange and pink outlines identify the two
controls. Their short labels show the current selections. Expand a control to
change its source, inspect capture times or use the existing snapshot actions.
Only one group expands at once; click outside or press Escape to close it.
Snapshot controls follow the active tool, while Collection context remains the
shared source for collection views. Choosing a tool snapshot retains that
tool's existing scope rules; it does not silently change the shared context.

**Collection statistics** shows addition-year, track-length, release-year and
saved-genre distributions. Release dates contribute their year only when a
valid captured year or ISO release date is available. Genre names retain their
saved spelling. For very many genres, an explicit Other saved genres bucket
collects small categories, retaining the complete known total.

Release years start with **Newest years first**. Use the compact selector to
switch to **Most tracks first** without changing the counts or requesting
another statistics scan. Unknown years remain last when shown; the separate
Hide unknown choice still controls their inclusion and the excluded totals.

The compact **Hide unknown** checkbox is remembered locally and shared with
Bubble and Tonality views. Statistics exclude unknown values independently for
each chart, showing displayed/total counts and the number excluded. A missing
genre does not remove a known release year or duration. Known zero values remain
visible. Unverified scalar counters can be hidden too, without changing the
captured collection or source totals. Key notation is another remembered
display choice; see [key grouping and evidence](DJ-INSIGHTS.md).

See the [compact collection controls](screenshots/compact-bubble-filters.png)
and [four statistics histograms](screenshots/collection-statistics-distributions.png)
using invented metadata. [Screenshot provenance](SCREENSHOTS.md) describes the fixtures.

## Review and evidence

Duplicate decisions, reference changes and metadata overrides are staged locally. Cues inferred as manual or mixed take keeper priority; cue origin is inferred from editable labels. Review unresolved conflicts before export. Snapshot statistics describe captured library entries and can include duplicates. A zero play count does not prove a track was never played.

Routine pages use short technical labels. Expand information boxes or select **Details** for procedures and evidence limits. Small icons supplement visible labels; colour alone does not identify an action. See [Library lab](LIBRARY-LAB.md) and [DJ insights](DJ-INSIGHTS.md).

Single-track **File view** provides 0–5 instant personal-star buttons alongside the existing instant colour palette. Both stage a local working edit on click, without a confirmation or advanced-field unlock. Reset restores the captured value. Supported native colour choices are constrained to verified palette mappings; nothing is written to original source libraries or audio files. Comments retain their separate Save action, and export still requires normal review.

## Export and cleanup

The paired XML/ZIP export uses one frozen decision snapshot. XML retains its input collection scope. A successful consistency check does not prove that rekordbox will restore a native ZIP. Use an isolated library and follow [restore testing](RESTORE-TEST.md).

Quick export generates an offline HTML explorer and minisite ZIP. Both now include an on-demand category bubble chart on the Overview page, grouping only dimensions included in that export. Public summaries use aggregate-only counts and labels; no individual track rows, audio, paths, usage or private ratings are added by the chart. The chart is rendered locally from existing export data, without a network dependency, and presents a readable category legend.  They contain metadata and interface language resources, not audio or a native backup. Changing display language does not rewrite metadata. Use **Stop and clean up** to remove temporary imports, database copies and incomplete exports; completed exports, reports and decisions remain. See [temporary-file handling](TEMPORARY-FILES.md).

## Optional internet queries

MusicBrainz retrieval requires an explicit sample review, enable switch and confirmation. Language selection and documentation browsing make no provider queries. The pilot sends only confirmed identity metadata, not paths or audio. See [community evidence](COMMUNITY-RATINGS.md).

**Enrich current library** defaults to the loaded XML/ZIP workspace. The collection selector can also use a connected Rekordbox desktop source already discovered through Source analyzer. **Use this library** prepares current metadata locally; a source-folder selection takes a fresh private database copy. Users do not need to visit Library lab to create a snapshot first. The snapshot remains the internal, immutable basis of each reviewed batch. If no usable source is connected, new previews and starts are blocked; saved results remain available for review. Switching libraries or changing the unavailable-audio option invalidates the previous preview and confirmation.

New batches include only **playable tracks** unless **Include tracks with unavailable or unverified audio** is checked. Preview checks availability before sampling and reports exclusions. Each new lookup checks again; a file that became unavailable is skipped without a provider request. Here, playable means readable local audio at a recorded path, not a successful decoding or listening test. Earlier batches without this availability policy require a new preview before starting.

Genre, album, year and playlist selectors display **Loading** and stay disabled while their first list is prepared. Later selections reuse the cached lists. Concurrent requests share the first load, failed loads expose **Refresh**, and empty lists show an explicit empty state. The progress notice stays at the top while scrolling and **View results** jumps to the batch progress/results. The saved-batch list shows active jobs in submission order and retains recent completed or interrupted jobs. Dismissal lasts until the active queue changes; reduced-motion preferences disable the entrance animation.

Files & workflow presents compact Rekordbox and Serato cards side by side, stacking on small screens. The Rekordbox card opens source analysis; the Serato card opens the existing experimental export section, not a Serato importer.

## Navigation and long operations

The sidebar separates sources, analysis/insights, cleanup/migration, and exports/help. Menu labels use larger text without decorative icons; uppercase group captions identify scope. Its width selector remembers Compact, Standard or Wide locally. Small screens show the groups above the workspace instead of hiding their labels. The shared header places a compact informational notice between the title and selectors. Its first line explains that source files remain unchanged; on Play history, Collection statistics and Library lab it also presents the relevant page guidance and an expandable Details control. The original translated explanations and their documentation links remain available there, without full-width repeated banners. On smaller screens the note wraps beneath the controls.

Uploads, analysis and transformations show a centred progress dialog. Navigation is inactive while it is open. Escape does not dismiss an active operation; wait for completion or use **Stop and clean up** to open the normal cleanup confirmation. The optional MusicBrainz run has a Cancel action. Indeterminate transfers show activity without a fabricated percentage.

Summary cards balance totals with larger labels and evidence notes. Native ZIP copy and verification progress updates during large members, while unchanged compressed analysis data is streamed through. Completed outputs are published only after validation.

Duplicate review keeps the candidate list and comparison in separate scrolling panes. Captured master.db collections give more desktop width to the candidate list, use compact record cards for comparison, and keep Save review above the records. The explanatory note is available under Details. Candidate counts and duration spread sit in separate columns; narrow lists hide the spread column while each record's duration remains in the comparison. XML/ZIP workspaces give more width to the comparison and keep stage, skip and undo actions in their visible action bar. Clicking a candidate brings the review workspace into view. On narrower screens, Review opens a side drawer; Close or Escape returns to the candidate list and restores keyboard focus. Evidence and conflict options retain native controls with full labels. Keeper selection and staged export rules stay the same.

Chart match confirmation/export and Library intelligence report saving appear before their result tables and remain visible while scrolling. Saved-investigation cleanup previews appear next to the preview control, before the selection list. Track metadata editing already uses the File view dialog; row-level MusicBrainz and file-reference actions remain next to their records.

## Result-table sorting and navigation

Column headings in Library lab tracks and reports, saved history, DJ insights, bubble and tonality track lists, Library intelligence, MusicBrainz, File health and native collection tables sort the complete filtered result before pagination. Combined headings also offer a **Sort all results by** selector for individual fields such as artist, year, stars or duration. Duplicate candidate lists, Media inventory and storage groups offer sorting selectors. Original order restores the tool's normal ranking or saved sequence.

Numeric values are compared as numbers; missing values stay last in both directions. Sorting a saved session does not change its recorded sequence or the basis of BPM differences. Library lab sorts effective staged metadata; analytical views continue to describe captured metadata. Report downloads and insight CSV use the requested filters and order. Small, fully rendered summary tables retain the generic local sorter.

File-health ordering uses the last explicit saved local scan. **Unchecked** is
separate from **Unverified**. Live playback probes update the Play button
without moving rows or replacing the saved evidence. Provider results retain
their separate metadata-check time. File health scans run only when explicitly
requested; the SQLite index supports collection-wide filtering and sorting.

Browser Back and Forward restore the selected page. Source and filter choices, and collection sort choices, are retained per tab through navigation and reload. A reload starts at the first result page; an ordinary return to an already loaded view retains its page where supported. Consent, staged editor drafts, local filesystem paths and upload files are not restored from browsing preferences.

## Opt-in journal activity monitoring

Source analyzer can now monitor filesystem metadata for `master.db`, `master.db-wal` and `master.db-journal` from an existing saved modern source capture. Monitoring is **off by default**. When enabled on the Source analyzer page, the application checks for changes every four seconds; after two unchanged samples it can launch a new, independent read-only snapshot. It preserves the earlier report and never rewrites the source. Failed or changing captures are not presented as updated library state; reattempts are throttled. The normal progress dialog appears during a recapture. Metadata requests never overlap; disabling monitoring, leaving the page or selecting another report prevents an older response from replacing the selection.

This feature detects journal/file activity, **not necessarily committed database transactions**. It is not a raw WAL decoder, does not read uncommitted edits, and is not a guarantee of an immediately consistent view of an actively edited SQLCipher database. A WAL checkpoint can produce a stamp change without a logical library change. SQLite WAL transactions need a valid commit frame and snapshot-consistent access (see [SQLite WAL overview](https://www.sqlite.org/wal.html)). For a reliable migration snapshot, the normal recommendation remains to close Rekordbox and pause Cloud Library Sync.

## Audio folders on another operating system

Discovering a database on a mounted Windows volume does not translate its saved audio locations. In **MusicBrainz** or **File health**, expand **Audio folders**. Map the recorded drive or folder (for example `D:/Music`) to the corresponding directory on this computer (for example `/media/music/Music`). Choose **Check example paths**, review the actual mappings, then **Save audio folders**. Multiple drives can have separate mappings. Run File health again or create a new MusicBrainz preview.

Mappings belong to the selected source and are reused by its saved snapshots and freshly prepared MusicBrainz captures. They affect local availability, playback and enrichment eligibility only; original metadata, audio files and export references are unchanged. Windows paths are matched at folder boundaries, including file URIs, Unicode and case differences. Ambiguous case matches, traversal, network paths, symlinks and replaced/disconnected mount identities are held rather than guessed. A readable audio-suffixed file is not proof that its media content can be decoded.

## Workspace changes and import recovery

Workspace actions carry the workspace identity and revision that the tab reviewed. If another tab loads a different workspace or changes its working state, stale actions are rejected with a reload message. Use **Reload workspace**, then review the action again. Explicitly selected immutable snapshots remain separate from this active-workspace guard.

Interrupted uploads remove incomplete files and support retrying the same import. While the page stays open and the selected files are unchanged, resubmitting retains completed uploads, including a file whose success response was lost. Selecting different files creates a new import. Disk capacity, permissions, cancellation and interrupted streams produce actionable failures. Duplicate analysis submissions share the existing task. An import is made active only after its initial saved state is successfully published; a failed import keeps the previously active workspace.

Closing the application still removes temporary uploaded copies according to the existing cleanup policy. Saved decisions can be resumed by reattaching the matching original XML/ZIP pair; retries never bypass input-identity checks.

## MusicBrainz recording and release review

The first retrieved recording is a proposal. Expand **Alternative recordings**, select another retrieved candidate, explicitly consent to that retrieval, then choose **Retrieve selected recording**. Provider calls use the existing cache, pacing, cancellation and bounded queue. Finish or cancel queued lookups before changing a candidate. A failed retrieval keeps the previous result. A successful change resets identity approval, release selection and this batch's still-staged suggestions; later manual edits are preserved.

Approve the selected recording before choosing **Album / release**. Review its title, date, country, status, disambiguation and MusicBrainz ID, then choose **Use this release**. The choices are the bounded release list returned with that recording, not a complete discography. **Stage album** uses that explicit edition. **Stage release year** is separate from the existing first-known recording year. Unlock metadata staging for the selected snapshot before staging fields.

Each new MusicBrainz override retains structured provenance: batch, recording, optional release, source URL, field basis, retrieval, approval and staging times. Inspect it in the track editor's staged edits. Identity/release changes and revoked approvals clear only this batch's matching suggestions and record resets in the private override history. Review revisions reject stale selections from other tabs. Personal star ratings are never populated from provider similarity or community ratings.

Provider reference: [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API). The integration retrieves metadata; it does not submit changes to MusicBrainz.

## Exported references and destination platform

**Prepare export → Exported references** shows the target inferred from recorded current/XML paths. Windows drive-letter or UNC paths identify Windows; conventional macOS paths identify macOS. The helper's operating system and Audio folders mappings do not choose the target. For mixed or unknown source paths, choose Windows or macOS explicitly.

Selecting a target does not convert paths. Use **File references** to deliberately stage destination changes, then review them before export. An export is held if surviving references still belong to the other platform. New destination references and saved relocation edits are checked again before XML/ZIP output; Linux access paths and known playback aliases cannot silently enter the exported library. Destination and source-path evidence are included in the export manifest.

In advanced Media inventory, **Exported reference prefix · required for staging** is distinct from the local search folder. For example, search `/media/disk/Music` while exporting under `file://localhost/D:/Music`. A scan without a destination prefix can help investigate matches, but cannot stage them. Supply the prefix and repeat the scan before staging.

Windows libraries remain Windows libraries when inspected from Linux or macOS. Accessing a Windows filesystem from a Mac does not imply a change of library destination.

## Zero metadata flags and DJ preparation filters

Captured duplicate review and DJ insights have colored **Zero-duration** and **Zero-size** quick filters. They select records whose saved duration or size is exactly zero; unknown values are not counted as zero. They do not scan audio or prove that a physical file is empty. Playability is independent, so a flagged record can still play. Duplicate filters count matching groups across the complete collection and keep every member of a matching group for comparison. Playback refreshes also update the comparison's availability badges.

DJ insights adds **Missing BPM or key**, **Played but unprepared**, **Favourites needing cues**, and **Long tracks / mixes**. Their rules are missing BPM/key, positive selected usage with zero manual cues, at least four stars with zero manual cues, and duration of at least ten minutes respectively. These filters describe captured metadata; they do not infer forgotten cues or identify mixes with certainty. The zero flags can be combined with a perspective. Source, perspective and metadata filter choices survive navigation/reload; CSV/report output uses the chosen filters.

## Allowed audio locations

Audio folders are checked against locations selected by the application: your home folder, the application's data folder, and detected mounted/local volumes. The panel lists these allowed locations. The check resolves links and requires a full directory boundary, so a similarly named sibling or a link outside those locations cannot broaden access.

Mounted NTFS audio remains supported. If a custom audio folder is outside all displayed locations, configure it on the helper host before starting the application, using the `LIBRARY_WORKBENCH_AUDIO_ROOTS` environment variable as a JSON list of absolute folders. For example, on Linux: `export LIBRARY_WORKBENCH_AUDIO_ROOTS='["/srv/music"]'`. This is host configuration; a browser request cannot add trusted locations. Use narrow music folders. These access boundaries never change recorded/exported paths.

# Interface and workflow

Use the language selector for interface labels, short guidance and confirmations. Library metadata, file paths, cue labels, technical identifiers and raw diagnostics retain their source values. The full project documentation currently uses English. The Documentation page renders the bundled Markdown; it does not download documentation or images from the internet.

## Import and source analysis

Create an untouched rekordbox Backup Library backup before preparing transformed files. Preserve audio separately if it is excluded. For XML/ZIP review, create matching exports consecutively without intervening library changes. Uploaded files are temporary local analysis copies. The existing-file option reads originals in place and requires them to stay unchanged.

Source analyzer can instead inspect a database folder or collection XML. Close rekordbox and pause Cloud Library Sync for capture. Windows and Mac suggestions are optional; manual paths also work on Linux for a user-mounted filesystem. Read [migration](MIGRATION.md), [compatibility](COMPATIBILITY.md) and [capture/asset/history procedures](DISCOVERY-ASSETS-HISTORY.md) for details.

## Opt-in journal activity monitoring

Source analyzer can now monitor filesystem metadata for `master.db`, `master.db-wal` and `master.db-journal` from an existing saved modern source capture. Monitoring is **off by default**. When enabled on the Source analyzer page, the application checks for changes every four seconds; after two unchanged samples it can launch a new, independent read-only snapshot. It preserves the earlier report and never rewrites the source. Failed or changing captures are not presented as updated library state; reattempts are throttled. The normal progress dialog appears during a recapture.

This feature detects journal/file activity, **not necessarily committed database transactions**. It is not a raw WAL decoder, does not read uncommitted edits, and is not a guarantee of an immediately consistent view of an actively edited SQLCipher database. A WAL checkpoint can produce a stamp change without a logical library change. SQLite WAL transactions need a valid commit frame and snapshot-consistent access (see [SQLite WAL overview](https://www.sqlite.org/wal.html)). For a reliable migration snapshot, the normal recommendation remains to close Rekordbox and pause Cloud Library Sync.

## Review and evidence

Duplicate decisions, reference changes and metadata overrides are staged locally. Cues inferred as manual or mixed take keeper priority; cue origin is inferred from editable labels. Review unresolved conflicts before export. Snapshot statistics describe captured library entries and can include duplicates. A zero play count does not prove a track was never played.

Routine pages use short technical labels. Expand information boxes or select **Details** for procedures and evidence limits. Small icons supplement visible labels; colour alone does not identify an action. See [Library lab](LIBRARY-LAB.md) and [DJ insights](DJ-INSIGHTS.md).

## Export and cleanup

The paired XML/ZIP export uses one frozen decision snapshot. XML retains its input collection scope. A successful consistency check does not prove that rekordbox will restore a native ZIP. Use an isolated library and follow [restore testing](RESTORE-TEST.md).

Quick export generates an offline HTML explorer and minisite ZIP. They contain metadata and interface language resources, not audio or a native backup. Changing display language does not rewrite metadata. Use **Stop and clean up** to remove temporary imports, database copies and incomplete exports; completed exports, reports and decisions remain. See [temporary-file handling](TEMPORARY-FILES.md).

## Optional internet queries

MusicBrainz retrieval requires an explicit sample review, enable switch and confirmation. Language selection and documentation browsing make no provider queries. The pilot sends only confirmed identity metadata, not paths or audio. See [community evidence](COMMUNITY-RATINGS.md).

## Navigation and long operations

The sidebar separates sources, analysis/insights, cleanup/migration, and exports/help. Menu labels use larger text without decorative icons; uppercase group captions identify scope. Its width selector remembers Compact, Standard or Wide locally. Small screens show the groups above the workspace instead of hiding their labels. The shared header places a compact informational notice between the title and selectors. Its first line explains that source files remain unchanged; on Play history, Collection statistics and Library lab it also presents the relevant page guidance and an expandable Details control. The original translated explanations and their documentation links remain available there, without full-width repeated banners. On smaller screens the note wraps beneath the controls.

Uploads, analysis and transformations show a centred progress dialog. Navigation is inactive while it is open. Escape does not dismiss an active operation; wait for completion or use **Stop and clean up** to open the normal cleanup confirmation. The optional MusicBrainz run has a Cancel action. Indeterminate transfers show activity without a fabricated percentage.

Summary cards balance totals with larger labels and evidence notes. Native ZIP copy and verification progress updates during large members, while unchanged compressed analysis data is streamed through. Completed outputs are published only after validation.

Duplicate review keeps the candidate list and comparison in separate scrolling panes. Captured master.db collections give more desktop width to the candidate list, use compact record cards for comparison, and keep Save review above the records. The explanatory note is available under Details. Candidate counts and duration spread sit in separate columns; narrow lists hide the spread column while each record's duration remains in the comparison. XML/ZIP workspaces give more width to the comparison and keep stage, skip and undo actions in their visible action bar. Clicking a candidate brings the review workspace into view. On narrower screens, Review opens a side drawer; Close or Escape returns to the candidate list and restores keyboard focus. Evidence and conflict options retain native controls with full labels. Keeper selection and staged export rules stay the same.

Chart match confirmation/export and Library intelligence report saving appear before their result tables and remain visible while scrolling. Saved-investigation cleanup previews appear next to the preview control, before the selection list. Track metadata editing already uses the File view dialog; row-level MusicBrainz and file-reference actions remain next to their records.

## Result-table sorting

Click a column heading to sort its **currently displayed rows** ascending or descending. Sorting never changes the underlying snapshot, review classifications, audio files or metadata. Paginated result views sort only the current page; use their search and filters to narrow the complete result set. Tables with a local Play button include a sortable status column, distinguishing **Playable**, **Missing**, **Inaccessible**, **Unverified** and **Unchecked** (not yet probed). As playback checks finish, status cells update without unexpectedly moving the user's current selection.

The **File health** page is different: its sorting and filters apply to the **entire saved scan index** using SQLite before 50-row pagination. The scan is a deliberate local operation, cancellable at progress checkpoints and read-only with respect to original libraries. No scan is launched just by entering the page. Its status counts distinguish unscanned items from inconclusive checks.

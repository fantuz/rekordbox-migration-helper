# Native collection views and saved investigations

Choose `master.db` in Source analysis. The reader copies it and any available
journals into a private working directory before opening the database. A successful
capture becomes the selected collection in the shared header. Opening an older
source report selects that capture too.

The following pages use retained metadata from the selected capture or snapshot:

- **Collection statistics:** length filters, cue categories, ratings, saved play
  counts, playlists and library addition dates. Unknown fields remain unverified.
  Relationship counts cover the whole captured source, regardless of length filters.
- **Play history:** native history sessions and recorded entry order, including
  repeats and entries absent from the active collection. An additional Library lab
  snapshot is optional for these views. History dates are not individual play times.
- **Duplicate review:** candidate groups by recorded path or normalized artist and
  title, with paginated record comparisons and saved review classifications. Version
  labels in titles remain significant. Neither matching metadata nor paths proves
  identical audio. Native review does not merge tracks or change the source database.
- **File references:** searchable current, original and analysis paths, plus filters
  for changed originals and empty current paths. Missing audio cannot be inferred
  from these records alone. Playback uses files available on this computer.

The **Save a snapshot for insight tools** button creates a retained snapshot from
the selected source and selects it in the shared header. This is an explicit action,
not a new snapshot created on every visit. Merging and staging path changes for a
copy export continue to require the XML + ZIP workspace.

## Clean up saved investigations

Open **Saved investigations**, select individual items or entire categories, then
choose **Preview cleanup**. The preview identifies retained reports, lookup batches
or journeys that reference selected items. Select those dependents too, or keep
their source. A native snapshot is self-contained and can remain after archiving
its original analyzer capture.

**Archive selected investigations** moves the selected work out of active menus.
The page retains a **Restore cleanup** action for each operation. Archiving is
reversible and does not reclaim disk space. Original source libraries, audio,
uploaded inputs, staged metadata overrides and completed exports are preserved.
For inactive XML/ZIP workspaces, only their saved state is archived; export files
remain in place. The active workspace and running background jobs block cleanup.

Restore refuses to overwrite an investigation that already exists. Restore with a
matching application version if an archived SQLite schema differs after an upgrade.
After restore, choose the collection you want in the shared header.

## Private regression testing

Real library files can be tested locally without uploading them to GitHub or
configuring Actions secrets. Keep both fixtures and generated captures outside the
checkout. Repository tests and browser fixtures use invented records only. Do not
commit private databases, extracted metadata, download links or personal screenshots.


### File health in duplicate review

The comparison pane includes cached local file evidence: **Playable**, **Missing**, **Inaccessible** and **Unverified**, with a summary and optional filter. Use **Refresh file evidence** when a removable drive has been connected or a path has been repaired. A status is about reachability on this computer, not about whether recordings are equivalent. Inaccessible and unverified records should be investigated rather than discarded; even a file reported missing may still exist elsewhere or on another computer. This feature neither deletes files nor changes the saved keep-separate/candidate review decision.

This is an initial library-health diagnostic rather than an automatic duplicate-removal policy. Future maintenance workflows can combine file evidence with metadata, history, rating, cue, format and storage evidence, with explicit user review before any exported change.

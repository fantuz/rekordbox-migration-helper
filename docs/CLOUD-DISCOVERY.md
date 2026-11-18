# Cloud folders and relocated libraries

Source analyzer includes **Cloud library locations**. It looks for local
Dropbox/Google Drive folders and database filenames within them. Choosing a
suggestion only fills the source path. It does not start analysis, move files,
change sync settings or rewrite music references.

## Detected layouts

- Dropbox's local `info.json` can identify personal and business roots,
  including custom team names. The account path is used; email, tokens and
  unrelated fields are ignored. Folder-name candidates remain a weaker
  fallback when provider configuration is absent.
- Team/customer layouts such as
  `C:\Users\dj\Example DJ team Dropbox\Example Customer\rekordbox`
  are included in the shallow search. A folder does not need to be named
  exactly `Dropbox`. This is an invented example, not a committed user path.
- Windows sync-root registrations are filtered to the current process's user
  SID. Provider-labelled fixed local volumes can also suggest Google Drive
  streaming locations. Volume labels alone are not provider verification.
  Network drives are not probed automatically.
- Google Drive streamed or mirrored folders can be found when their local
  locations are registered or use recognizable local folder layouts. macOS
  File Provider roots under `Library/CloudStorage` support multiple accounts.
  The app does not decode private DriveFS databases or infer streaming versus
  mirroring from a folder name. Unregistered custom mirror folders can be
  supplied manually through the existing folder search.
- On Linux, local provider metadata/folders can be inspected and existing
  mounted folders can be selected manually. The application never mounts a
  filesystem or signs in to a cloud provider.

An accessible folder named `rekordbox` may contain music or analysis data
without containing the library database. Workbench only adds a library
suggestion when it finds known database filenames. Those filenames do not
establish database readability, version compatibility or content identity.
The database can remain in AppData while music lives in a cloud folder.

## Use a detected folder

1. Open **Source analyzer → Cloud library locations** and select **Refresh**.
2. Review the provider root, evidence and any database-folder suggestions.
   **Add** places a root into the manual search field; it does not search yet.
3. Select **Use this library** to fill the source path, then inspect the path.
4. Close rekordbox and pause library synchronization before explicitly
   capturing a database. Normal read-only capture and integrity checks still
   determine whether it can be analyzed.

For large team folders, choose your own customer subfolder as a manual search
root to avoid spending the search budget on unrelated accessible folders.
Online-only directories, symbolic links and junctions are skipped. Make
required files locally available through the provider before capture.

## Relocation evidence

Saved rekordbox/Agent database-location settings can supply a previous path.
Matching at least two trailing directory components with a detected cloud
library yields a **Possible library relocation** suggestion. A basename
match such as `rekordbox` alone is insufficient. Equally strong candidates
stay ambiguous and must be reviewed.

The report always leaves relocation identity unverified: folder and settings
evidence does not compare database UUIDs, source bytes or music content. If no
previous path was recorded, the interface says relocation is not established;
it can still show current locations. A current working path need not imply
that it was moved from somewhere else.

Library-folder discovery is separate from audio relocation. After selecting
and capturing the correct collection, use **Audio folders** for local preview
mapping and **File health** to inspect its files. Use **File references** or
Media inventory to review changes for a copy export. Discovery never applies
an audio mapping automatically. Availability and filename matches are not
proof that two recordings contain identical bytes.

## Limits, privacy and reports

Provider configuration reads are limited to 1 MiB each. At most 24 roots are
returned. The shallow library search visits at most 128 containers and 4,096
directory entries, with a two-second soft deadline; known library-name probes
and explicitly recorded paths are checked within that scope. Slow operating
system metadata calls can exceed a soft deadline. Partial searches are
labelled and cannot establish that an undiscovered library does not exist.

Results are cached in process for ten seconds to avoid repeated metadata
walks during page refreshes. The cloud **Refresh** action clears that cache.
No source database or audio bytes are opened during this discovery. File
provider clients control metadata availability; the app does not request file
hydration, login or remote provider operations.

**Download JSON report** contains detected paths, evidence, ambiguity and
search scope. Paths can include user/account labels. Other provider-config
fields are omitted. Reports are downloaded only on request and are not
published or uploaded by Workbench.

The automated examples use invented personal/team/customer folders, Google
Drive registrations and File Provider layouts. They validate filesystem and
workflow behavior, not the installation of a specific provider version on a
user's computer. Manual path selection remains available for other layouts.

# Temporary copies and shutdown

Original library folders and user-selected XML/ZIP files are never overwritten or deleted. Selecting **Choose files** uploads copies to this computer, into a marked per-run `.temporary` folder under the application's data directory. **Use existing files** reads the selected originals in place without another XML/ZIP copy. Native database extraction and journal recovery always use temporary copies.

**Stop and clean up** displays the disposable file count/size and requires acknowledgement. The app cancels active jobs/uploads, waits for file handles to close, removes the owned temporary folder and records the result in `cleanup-last.json`. Failed cleanup leaves the application open with an error and a retry action. Windows and Mac builds use the same browser acknowledgement. Closing a browser tab alone keeps the local application running.

On Linux, the first Ctrl+C prints what will be deleted and keeps the app running. A second Ctrl+C confirms cleanup and shutdown. The browser button is also available. Normal operating-system termination requests trigger cleanup; a forced kill or power failure cannot run application cleanup. On the next start, marked stale folders are recovered automatically, while locked folders belonging to active instances are left alone.

Removed: uploaded XML/ZIP copies, extracted native databases/journals, partial uploads and unfinished XML/ZIP/HTML exports. Raw MusicBrainz response cache is cleared; selected observations remain with the saved pilot report.

Kept: original files, user-managed input-folder files, saved reports, review decisions, compact metadata/review catalogs and snapshots, presets, pilot results and completed XML/ZIP/HTML/minisite exports. Review metadata is retained intentionally for resuming; it contains no audio or bulk analysis assets. A completed export is a deliberate output and can itself be large.

For an uploaded library, choose **Saved sessions → Reattach originals** after restart, then select the same XML/ZIP pair again. XML SHA-256, native database SHA-256 and the archive member index must match before saved decisions are restored. Renamed matching files are accepted; different library snapshots are rejected. A linked library resumes directly while its originals remain accessible and unchanged. Older sessions without a saved identity need their recorded paths restored once, or a new import.

Cleanup is confined to directories created and marked by this temporary-file manager. It does not recursively purge the application data directory, follow symlinks into source folders, or delete unmarked pre-existing files from older installations. This protects user-owned files and previously saved outputs.

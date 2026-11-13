# Finding sources, auditing assets and browsing history

## Choose an accessible source

Source analyzer checks normal Windows AppData and macOS Library locations plus saved database-directory settings. Cloud music can be stored elsewhere; Dropbox/Google Drive folders are not necessarily the database location. Custom absolute paths remain available on every platform.

| Platform / source | Locations checked | Meaning |
| --- | --- | --- |
| Windows desktop data | `%APPDATA%\Pioneer\rekordbox` | Usual master database location; `%APPDATA%` normally expands to the current user's `AppData\Roaming` |
| macOS desktop data | `~/Library/Pioneer/rekordbox` | Usual master database location; `~` means the current user's home folder |
| Preferences / Agent | Windows `%APPDATA%\Pioneer`, macOS `~/Library/Application Support/Pioneer` | `rekordbox3.settings` and `rekordboxAgent/storage/options.json` can point to a different active database |
| External database | Saved directory, its `Master` or `PIONEER/Master` subfolder | Candidate locations; inspect the actual database rather than assuming an entire drive is the library |
| Mounted Windows/Mac volume | Standard profile paths under `Users`, saved paths mapped within that volume, and `PIONEER/Master` | Linux can read an accessible mounted copy; drive-letter mappings must be checked by the user |

The official [rekordbox troubleshooting guide](https://forums.pioneerdj.com/hc/en-us/articles/205021519-Read-this-article-before-posting-for-help-with-rekordbox) documents the usual Windows and Mac data directories. The official [external database guide](https://forums.pioneerdj.com/hc/en-us/articles/205021549-Moving-your-rekordbox-database-Video) confirms that the master database may be moved. [pyrekordbox's configuration reader](https://pyrekordbox.readthedocs.io/en/stable/_modules/pyrekordbox/config.html) is the community implementation reference for Agent `db-path` discovery. It is not an official native-format specification.

Discovery checks the original Pioneer namespace first, then AlphaTheta and version-suffixed folders as additional candidates. The extra names are fallback probes, not a claim that every version uses them. Agent database pointers take priority over standard-folder guesses; old files can remain after migration. The optional `analysis-data-root-path` hint supplies analysis candidates when present. Only location fields are returned; unrelated Agent options, authentication/device values and configuration contents are not included in discovery reports. Settings are never edited.

Automatic suggestions skip network-share pointers and relative paths. Enter a deliberate manual path for an unusual setup. Discovery uses fixed database-name probes instead of listing all files in a large music directory. A suggested folder is still a candidate: the analyzer checks its format and schema after you explicitly choose capture.

**Find libraries in custom folders or mounted volumes** performs a user-triggered, bounded search. Pick one or more roots, choose depth and search. Results only populate the source-path field when selected. Analysis starts separately, after you close rekordbox and pause library synchronization. Database queries always run on a detached temporary copy.

Linux users can select a real Windows library on a filesystem they have already mounted with their own tools. The app checks recognized mounted volumes and standard Windows profile paths, including relocated settings paths that can be mapped within the same volume. Verify candidates: a Windows drive letter does not establish which Linux mount represents it. The app does not mount, unlock, repair or write to Windows filesystems. Network homes, unusual installations and inaccessible mounts may need manual paths.

Search is limited to 15 seconds, 12,000 directories, 200,000 entries and depth 12. Links, junctions, recognized online-only subfolders and common system/cache trees are skipped. Partial results explicitly report limits and errors. Select a narrower root for complete coverage. The JSON discovery report is retained with other reports.

## Multiple analysis scopes

In Library lab, save/select a native snapshot, then provide up to 20 analysis-folder or backup-ZIP paths, one per line. Add detected USBANLZ trees or use the bounded asset search. ZIPs are inventoried directly, without extracting the analysis tree. A path can also point to a nonstandard folder containing recognizable ANLZ files; ownership there may remain unknown.

The audit keeps physical copies separate across roots even when their USBANLZ identifiers match. Overlapping roots do not count the same physical path twice. Matching analysis member names/sizes form candidates; only explicit SHA-256 comparison establishes equality of recognized ANLZ member sets. Verification has a 256 MiB read budget. Different content, skipped members, online-only assets, changed files and incomplete scans are distinguished. No audit deletes data.

Missing means absent from the selected scopes. Unreferenced means no owner in the captured complete reference set, not safe to delete: another library may use the folder. The audit is bounded to 160,000 directories, 300,000 entries and 45 seconds for inventory. Byte verification has its separate explicit budget. Reported sizes are logical file sizes; compression, placeholders, sparse files and filesystem allocation can differ from occupied/freeable disk space.

## STEMS evidence

The audit reports extension counts and bytes (`.DAT`, `.EXT`, `.2EX`, `.3EX` where found), RBSC drum-capture files and other STEMS-named candidates. It keeps those categories separate from a **prepared-track count**, which remains unknown: we have no validated persistent per-track readiness indicator. Neither a `.3EX` file nor a directory named STEMS proves that a track is prepared for separation.

The [official v7 FAQ](https://rekordbox.com/en/support/faq/rekordbox7/) describes `.rbsc` as captured DRUMS samples and notes same-account playback restrictions. That is useful file-type evidence, not a complete-song STEMS cache. Other filename hints remain unverified. Zero candidates does not mean zero tracks can use STEMS. No analysis/audio asset is modified or deleted.

## Play history

For supported native schemas, the reader captures active `djmdHistory` session/folder rows and active `djmdSongHistory` membership, including `TrackNo` order. It ignores soft-deleted history rows. History folders are excluded from session counts. Session names/dates remain recorded values; the app does not infer whether a session was a gig, practice or export.

Open **Play history**, capture from a loaded native ZIP workspace or saved source-folder capture, then select the saved snapshot. Filter by session year/name/date, browse ordered tracks and download a session JSON report. Missing active track references remain present; archived title/artist metadata is shown when available. Collection tags reflect the captured collection, not necessarily the tags that existed at the time of the gig. A sum of full track lengths is not performance duration; individual play timestamps are not inferred from a session date.

Native history travels inside `master.db` in a modern backup ZIP; a separate history file or running instance is not required. A source-folder capture is an alternative if no suitable backup exists. Standard XML does not encode that History tab. Legacy `.edb` history is not decoded. Older Workbench snapshots lacking history capability need a new native capture; unknown does not mean empty.

History snapshots live in the retained local sidecar, independently of temporary input/DB cleanup. Session reports can contain private gig names/dates. Shareable HTML/minisite explorers deliberately exclude session histories. Their **Added by year** category is derived from captured addition dates, separately from release-year tables.

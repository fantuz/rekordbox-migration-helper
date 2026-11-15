# Listen while reviewing

A small play button accompanies local track titles in DJ insight tables and their bubble/tonality drill-downs, the track editor, Library lab, MusicBrainz local matches, play history, playlist contents, collection lenses, session progression, duplicate sibling cards and media inventory. Chart candidate selections also have a local play button. Aggregate headings and remote recordings without a library match are not playable.

The local application resolves the captured track ID, checks its recorded current path and recorded alternatives, and asks the operating system to open the available audio file. Windows uses the file's default association, macOS uses its desktop opener, and Linux uses `xdg-open`. Set the preferred music player as the default for each audio format in the operating system.

Visible buttons are checked in small batches. Missing files appear unavailable; reconnect a disk and return focus to refresh. Availability is checked again on every click. Paths from a different computer must first be made accessible. Remote URLs, UNC paths, executables and relative paths are not launched; a mounted music volume can be used instead. Browsing from a remote computer cannot launch the server's media player.

Playback does not change ratings, colours, comments or playlists automatically. It lets you listen while using the existing review/edit controls. The media player is external, so the helper does not provide pause/seek controls or claim to know whether playback started after the operating system accepted the open request.

Playback is a feature of the running local app. Shared HTML/offline exports do not have access to this launcher.

## Cached local file evidence

The application saves bounded, path-digest-keyed observations in its **private** `workbench-sidecar.sqlite3`, never in Rekordbox's database. These observations are shared by play-button availability and captured duplicate review. No audio bytes are read or cached, and original paths are not stored in the evidence table. Multiple records referring to the same recorded paths reuse one observation. The status expires after 60 minutes for a readable file, 90 seconds for missing/inaccessible files, and five minutes for unverified evidence; the oldest observations are evicted after 20,000 entries.

Four advisory states distinguish **Playable** (readable file with a supported audio extension; this does *not* verify successful decoding), **Missing** (file absent in an accessible parent directory), **Inaccessible** (present but denied or permission error), and **Unverified** (no usable local path, unmounted folder, foreign-platform path, unsupported type or inconclusive evidence). A readable recorded alternative takes precedence over an unavailable current path. A potentially disconnected drive is never classified as a confirmed missing recording.

The duplicate inspector shows per-record status, summary counts, a status filter and **Refresh file evidence** for reconnecting storage devices. Filtering only changes the view: it does not change review classifications or mark a track for removal. Playback launch **always revalidates** the path rather than trusting a cached observation. The availability API retains its existing boolean `tracks` map and adds `statuses` and `cached` maps. Returning focus to the application or bringing its tab back into view requests a fresh filesystem check in both the browser and SQLite cache; repeated focus events within five seconds are throttled. The explicit **Refresh file evidence** button always bypasses the cache. Remote browsers cannot invoke these local filesystem checks.

# Listen while reviewing

A small play button accompanies local track titles in DJ insight tables and their bubble/tonality drill-downs, the track editor, Library lab, MusicBrainz local matches, play history, playlist contents, collection lenses, session progression, duplicate sibling cards and media inventory. Chart candidate selections also have a local play button. Aggregate headings and remote recordings without a library match are not playable.

The local application resolves the captured track ID, checks its recorded current path and recorded alternatives, and asks the operating system to open the available audio file. Windows uses the file's default association, macOS uses its desktop opener, and Linux uses `xdg-open`. Set the preferred music player as the default for each audio format in the operating system.

Visible buttons are checked in small batches. Missing files appear unavailable; reconnect a disk and return focus to refresh. Availability is checked again on every click. Paths from a different computer must first be made accessible. Remote URLs, UNC paths, executables and relative paths are not launched; a mounted music volume can be used instead. Browsing from a remote computer cannot launch the server's media player.

Playback does not change ratings, colours, comments or playlists automatically. It lets you listen while using the existing review/edit controls. The media player is external, so the helper does not provide pause/seek controls or claim to know whether playback started after the operating system accepted the open request.

Playback is a feature of the running local app. Shared HTML/offline exports do not have access to this launcher.

# Chart playlists

Library intelligence can fetch up to 100 recordings from the public ListenBrainz sitewide listening chart for the week, month or year. MusicBrainz supplies recording metadata; this feature uses ListenBrainz listening statistics, not a MusicBrainz sales chart. These rankings represent contributions to ListenBrainz and are not sales, radio or DJ popularity measurements.

Select a snapshot, open **Chart to playlist**, choose a period and acknowledge the remote request. Only a fixed public statistics endpoint is queried. Library tags, paths, audio and identities are not sent to this provider. Results are cached locally in the running process for an hour; rate-limit responses cause a cooldown.

Matching runs locally. A unique exact title/artist match is preselected for review, not treated as a proven recording identity. Duplicate candidates stay ambiguous. Similar titles from the same artist are suggestions requiring review; remix/version words are retained. Unmatched recordings remain visible. Missing MBIDs do not prevent tag matching.

Listen to a local candidate with its play button, choose or skip each match, then confirm review and export M3U8. The saved server-side candidate report bounds the selection. Output follows chart order, removes repeated local track IDs and includes only absolute recorded local paths. No audio is copied and no rekordbox library is changed. The target player must have access to those paths; availability at export is not guaranteed.

The original snapshot remains unchanged. This creates a playlist file, not a playlist inserted into the native rekordbox database.

Sources: [ListenBrainz statistics API](https://listenbrainz.readthedocs.io/en/latest/users/api/statistics.html), [API and rate limits](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html).

# Share and browse an offline summary

**Share & offline summary** saves a standalone HTML file and a ZIP minisite. Both work in a browser after Library Workbench closes. They contain no music, artwork, waveforms, cue timestamps or rekordbox database. These files are summaries, not backups and cannot restore a collection.

You can use the loaded XML/ZIP workspace or a Source analyzer capture. For a lighter workflow, analyze a standalone XML collection export first: a native library ZIP is unnecessary when the XML has the metadata you want to share. Fields absent from that source remain unknown.

## Choose the audience

| Preset | What is saved | Suitable use |
| --- | --- | --- |
| **Public summary** | Category labels, counts, duration totals and average BPM for genre, artist, album, release year, BPM range, duration range, format, tonality and saved colour | Share the shape of your music collection without a track-by-track inventory |
| **Selected track list** | Title, artist, album, genre, year, BPM, duration and format for the selected playlist or track IDs | Share a selected part of your collection |
| **Private explorer** | Only the metadata fields you check; recorded paths require the separate explicit path choice | Keep a detailed personal reference |

Public summary is the interface default. It excludes individual tracks, track IDs, playlists, dates, play counts, personal ratings, cue information and file paths. Category labels can still reveal musical preferences or personal text in saved tags. It is a sharing preset, not an anonymity guarantee.

The selected list combines the chosen playlist and any entered track IDs, without repeating tracks that match both. Playlist selection does not disclose its name or other playlist memberships in that preset. IDs are used locally to select records, then omitted from the output. A selection must match at least one track.

Private fields are removed from the serialized data when unchecked: hiding a column is insufficient, so the exporter omits its values from both the HTML payload and the ZIP data file. Personal comments are never exported by this feature. Paths can reveal account or folder names and should normally remain excluded.

## Review the preview

The preview lists the number of tracks, included fields, excluded fields and metadata state before generating files. It reads metadata already captured locally. It does not contact an online service or publish anything.

**Captured metadata** is the saved source information. **Working metadata** applies your explicit local metadata overrides, such as reviewed genres or colours. Merge and relocation decisions are not applied to these browsing exports; their XML/ZIP library exports have a separate preparation and validation flow. The selected state is recorded in the generated files and export details.

Public summaries offer category tables and CSV export. Detailed presets retain search, filters, track details and only the category pages for included fields. Unknown values remain visible. Counts include library records; they are not a claim that every audio file exists or every record is a distinct recording.

## Open or share the result

1. Choose **Generate offline explorer**.
2. Download **Standalone HTML** and double-click it to browse. This single file is easiest to share.
3. Alternatively download **Minisite ZIP**, extract the entire archive, and open `index.html`. Keep its files together.
4. Check the generated files before sending them to someone else. Library Workbench does not upload or publish them.

Finished summaries stay in the workspace for later download. Temporary imported library copies are still cleaned according to the normal exit procedure; deliberately exported summaries, reports and decisions remain.

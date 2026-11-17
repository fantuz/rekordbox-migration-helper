# Audio access, matching evidence and OneTagger

## Mounted music folders

In **Audio folders**, map a recorded folder such as `D:/Music` to the connected local folder containing that music. The original Windows or macOS references remain unchanged. Local aliases support listening, File health, MusicBrainz eligibility and the OneTagger handoff.

Windows references can resolve differences in filename case and Unicode composition. Bounded directory indexes are reused until the directory changes. Ambiguous names, symlink escapes and replaced volumes remain unresolved. Reconnect a volume and review its mapping before rescanning; the application does not guess another destination.

**Accessible** means a nonempty, readable regular file with a supported audio extension. It does not certify decoding or successful playback. Empty files are Unverified and cannot be launched. Missing, Inaccessible, Unverified and Unchecked retain their separate meanings. Existing API consumers continue to receive the historical `playable` status key.

## MusicBrainz evidence

The original artist and title remain captured metadata. Search-only cleanup records every changed step, including spacing and dash normalization, leading articles, original-version suffixes, release attributes and featured artists. Queries try the exact tags first, then applicable cleaned tags, a base title and a title-only fallback, with at most four search requests. ISRC searches retain their dedicated strategy.

Open **Search and match evidence** to inspect original tags, cleanup, each attempted query and its candidate IDs. Failed provider requests retain their attempt history too. Candidate evidence records title, artist, version, duration and unconfirmed-identifier disagreements. Version differences are flagged whether the source or the candidate has the extra version qualifier. Cleanup never becomes a title edit or automatic identity approval.

The approach takes inspiration from [OneTagger MatchingUtils](https://github.com/fantuz/onetagger/blob/master/crates/onetagger-tagger/src/lib.rs). It is a bounded tag-search workflow, without acoustic fingerprinting or audio uploads.

## OneTagger handoff

1. Open **MusicBrainz metadata** under **Enrich**, then the **OneTagger bridge** panel. Select a saved snapshot. Use Audio folders first when its recorded paths belong to another computer.
2. Search and select up to 500 accessible tracks. Selections persist across result pages. Click **Create OneTagger selection**.
3. Download the JSON selection manifest. In a OneTagger build with results support, load it under **Auto tag → Input & Tags → Helper selection manifest (optional)**. Review providers and tag settings, disable file moves, and start tagging. OneTagger edits the selected audio files and saves a results JSON; Workbench itself does not write audio tags or launch OneTagger.
4. Keep the files at their selected locations. Return to the saved selection and use **Import OneTagger results JSON**. The Helper checks the selection identity and independently compares current files and tags with the report before preparing review. Alternatively, drop the exported M3U into OneTagger's playlist area and use **Rescan tags after OneTagger** afterward. Read failures and invalid tags remain visible. Missing tags do not clear captured library values.
5. Review changes to title, artist, album, genre and year. Select only the fields you want, unlock metadata edits and confirm **I reviewed the selected tag changes.**, then **Stage selected fields**. Fields are unchecked initially. Personal stars, cues, grids and references are excluded.

The UTF-8 M3U uses the bridge machine's resolved local paths. The manifest stores these separately from each track ID and its original references. Percent characters and Unicode filenames survive OneTagger's M3U decoding. This handoff must run on the same computer as OneTagger; it is not a transferable Windows/macOS export path conversion.

Selections and reviews survive application restarts. A different mapping, newer rescan, changed tag file or intervening metadata edit invalidates old approval. Staging is atomic and keeps per-field provenance. Snapshot-only edits remain sidecar edits; only a matching loaded XML/ZIP workspace can apply them to its prepared export.

Supported handoff/read-back formats are MP3, FLAC, AIF/AIFF, M4A, WAV, OGG and Opus. Files that OneTagger renames or moves require a new selection. The bridge does not infer replacement files by name.

See [results JSON instructions and contract](ONETAGGER-RESULTS.md) for limits, statuses and provider evidence. OneTagger v1.7.2 supports the M3U/rescan workflow; JSON report exchange requires builds containing the linked integration changes.

The M3U behavior follows [OneTagger's playlist reader](https://github.com/fantuz/onetagger/blob/master/crates/onetagger-playlist/src/lib.rs). Synthetic tests cover the handoff and review contract; an installed OneTagger application is not launched by the Helper tests.

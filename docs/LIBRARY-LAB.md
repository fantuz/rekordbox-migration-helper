# Library lab

Keep an untouched rekordbox **Backup Library** backup outside the workspace before transforming files. Preserve audio separately if it is excluded from the backup. Generated native ZIPs require an isolated rekordbox restore test; automated file checks do not prove restore compatibility.

## Capture and compare

Save an immutable snapshot from a loaded XML/ZIP workspace or a detached Source analyzer capture. Label snapshots before and after changes, choose both and compare. Tracks match through unique UUIDs or guarded identifiers/paths; ambiguous identities stay unmatched. Cue loss is reported only for matched tracks with available cue positions. Compare cue/loop times, labels, colors, personal stars, ordered playlist membership and smart-playlist criteria. A 0–50 ms cue tolerance is explicit. Snapshot capture time is not evidence that two original exports were simultaneous. New snapshots also record a distinct timezone-aware **saved_at** timestamp. Snapshot selectors show the local date, time of day and time zone so similarly named editions can be distinguished; the shared collection header separates the original capture time from the later saved-snapshot time. Older date-only snapshots still display a calendar date without fabricating a time.

Automatic cue origin is inferred from editable CUE(Auto)/1.1Bars labels. It is not authoritative provenance. Comparisons use captured native cues where available; XML/native discrepancies remain available in Duplicate review.

## Quality and coverage

- Metadata consistency proposes conservative case, whitespace and Unicode normalization groups. It flags missing title, artist, album, genre, year or BPM and unusual numeric values. It does not infer that two artist aliases name the same person. Use the group action to stage a canonical value after unlocking the matching snapshot; reset individual edits in the editor.
- Coverage uses configurable cue/manual-cue counts and analyzed status. Tables group tracks by genre and 10-BPM band, with preparation percentage, saved zero-play counts and unknown status shown separately. No saved plays/history does not establish that a track was never used.
- Analysis asset audit inventories USBANLZ files in a chosen folder or native ZIP. Missing means absent from the selected scope; unreferenced requires a complete captured native reference set. Matching member names/sizes are candidates. Explicit SHA-256 verification has a 256 MiB byte budget, skips cloud placeholders and rejects changing files. No asset is deleted.

Reports support finding filters, paging and complete JSON download. Analysis audit now accepts multiple custom folders/ZIPs, bounded discovery and separate STEMS evidence counters. The Play history page browses native session snapshots and ordered membership, with missing tracks retained. See [discovery, assets and history](DISCOVERY-ASSETS-HISTORY.md) for limits and privacy. All library inputs, reports, working data and real pilot samples stay local and are excluded from source control, public CI and releases.

## Staged field overrides

The per-track file view opens Comments directly. Save a comment without unlocking other metadata. The colour palette also stages a working edit with one click: choose a labelled standard colour or clear the assignment. The selected colour has a checkmark and a pressed state, and captured custom colour names remain visible. Unavailable native colour mappings stay disabled with an explanation. Changing colour does not submit or replace an unsaved comment.

The file view lists the saved working edits separately from unsaved comment text. The final private export report recaps staged comment and colour edits alongside other requested changes. Its `applied_by_format` counts show what each writer applied after merging and collection scope limits; an XML-only export may omit edits for tracks outside its collection. Saved and reset edit history remains complete. Comment values stay out of insight tables/CSV and shareable HTML. The same-workspace copy writers support XML Comments/Colour and native Commnt/ColorID with baseline/conflict checks. See [DJ insights and track comments](DJ-INSIGHTS.md).

Title, artist, album, genre, year and personal stars start read-only. Unlock the snapshot scope to stage these fields; comments and colours remain available without that unlock. Original snapshots stay immutable; edits and reset history live in `workbench-sidecar.sqlite3` under the private application data directory. Whole personal stars use 0–5. Year may be cleared.

For XML/native ZIP copy export, edits must belong to a snapshot captured from that same loaded XML/ZIP workspace. The export freezes edits alongside merge/relocation decisions, validates their original baseline, resolves donors to keepers and holds conflicting edits. Native named values reuse exact active names or create validated lookup rows with new IDs/UUIDs/update counters. XML retains its own collection scope; native-only edits outside that scope are counted in validation. Sources and audio tags remain unchanged. Older native schemas are not silently enabled.

Any snapshot can generate offline HTML with or without its staged metadata. This projection excludes paths. It does not apply duplicate merges or relocations, and it is not a rekordbox backup.

## MusicBrainz proof of concept

The Enrich page now provides **Quick enrichment target** choices before preview: balanced top genres (the previous behavior), reproducible random samples, a chosen genre/album/year/playlist, or tracks missing genre, album or year. The album target chooses *local tracks* by saved album tag; the provider still matches individual recordings, not albums. The selected target and seed are saved in each immutable pilot batch. **Selection seed** controls reproducibility, not randomness or MusicBrainz confidence. **Populated genres** controls only the balanced default. **Lookup speed** controls the delay between provider requests, not filesystem speed. These explanations are available in a compact expandable section; consent and explicit identity approval remain mandatory.


Open **Enrich → MusicBrainz** in the sidebar. The dedicated page has its own snapshot selector, preview controls, saved batches and results. Home-page shortcuts, the enrichment journey and the background status strip open this page. Library lab retains snapshot capture, comparison and the metadata editor. Select the same source snapshot as the saved batch before starting retrieval or staging a suggestion.

Retrieval is **disabled by default**, controlled separately from editing. `LIBRARY_WORKBENCH_MUSICBRAINZ=0` forces it off. It can be disabled during a batch; cancellation retains partial results.

1. Preview up to 150, 300 (default) or 1,000 distinct tag identities, balanced across 3–12 selected top genres and an unknown-genre bucket. Insufficient unique identities produce smaller samples. A seed gives repeatable selection.
2. Review the sample and explicitly enable retrieval/confirm sending the selected tags. Queries use ISRC when available or escaped title/artist text. Duration helps review candidates. Path-like tags are withheld. Audio, paths, artwork and fingerprints are not uploaded.
3. Choose gentle (3 s), balanced (2 s) or fast (1.1 s) spacing. One shared serial gate enforces a minimum 1.1 seconds; cache hits use no request. Respect Retry-After and bounded backoff; long service pauses stop retrieval rather than retrying early. Repeated service errors pause a batch. Two requests per uncached match are typical; 150 tracks at balanced speed need about ten minutes plus delays. Other clients on the same public IP can consume the service's shared limit.
4. Review the best candidate, title/artist similarity, duration difference and version evidence. No match is approved automatically. Approval records identity only. Stage each suggested year or genre explicitly in an unlocked editor. For a different candidate, inspect MusicBrainz and use manual field edits; there is no automatic candidate substitution.

Community ratings come from actual recording ratings/vote counts, never the search relevance score. Missing votes mean unavailable, not zero. External scores remain decimal community values with provenance and vote counts; your personal stars are not automatically overwritten. First known recording release year can differ from the year of a particular mix/file release. Community genres are not guaranteed to fit a DJ's categorization.

For unreferenced audio, explicitly scan Media inventory, then capture unreferenced local tags. TinyTag reads tags and duration without writing tags or loading artwork; filename fallback is marked for review. Online-only placeholders are skipped. Up to 5,000 files are read per capture. Automatic audio identification needs a separate AcoustID/Chromaprint integration and is deferred.

Provider responses are cached locally for up to 30 days. MusicBrainz core data is CC0; supplementary ratings/tags are [CC BY-NC-SA 3.0](https://musicbrainz.org/doc/About/Data_License). Derived proposals retain source URLs, retrieval dates and license attribution. Retrieved data is not bundled into the project's MIT-licensed source or releases. Sharing derived data requires attention to its separate terms.

The PoC needs broader real-world matching and service-availability testing. No production SLA or completeness is assumed. Maintenance includes API/schema changes, provider etiquette, candidate/version review and data-license attribution. There is no mandatory API key for these read requests; network availability and service policy still govern use. [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API), [rate limits](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).

Lookups continue in the background while you explore. Keep the application running; the status strip and saved batches report progress, completion and recoverable interruptions. See [larger pilot behavior](COMMUNITY-RATINGS.md) and [local audio playback](TRACK-PLAYBACK.md).

## Migration readiness

Choose a saved snapshot, then open **Library lab → Health & coverage → Migration readiness**. Each action creates a saved evidence report; **Download full JSON** includes all findings, even when the table is paginated. Sources and audio tags stay unchanged. Reports can contain private member names and track metadata; review them before sharing.

**Backup coverage:** enter an absolute path to a Backup Library ZIP. The report inventories database, analysis, artwork, settings, music and other members. Missing captured analysis references are listed separately. Component labels use filename/path evidence; presence does not establish ownership, a complete backup, a valid database or successful restoration. Music and settings absent from the ZIP need separate backups when relevant. Nothing is extracted or copied into a destination library.

Enable **Verify checksums (512 MiB budget)** to read selected ZIP member bytes, validate their ZIP CRCs, and record SHA-256 values in the manifest. Members exceeding the total read budget remain unverified; the report marks verification partial. A cancelled or failed job does not save a successful report. Keep the manifest beside the original backup if you need to compare those member checksums later. The manifest does not automatically repair or restore anything.

**Check export readiness:** choose a player profile and destination filesystem. The first named profile, **CDJ-2000NXS2**, checks the format families listed on the [manufacturer's product page](https://www.pioneerdj.com/en/product/player/cdj-2000nxs2/black/): MP3, WAV, AAC, AIFF, FLAC and ALAC. A format outside this profile is flagged for review, not declared unplayable. The report records its profile version and rule source. M4A alone cannot identify the contained codec. Generic profiles and missing metadata retain Unknown outcomes.

Choosing **FAT32** flags captured file sizes above 4 GiB minus 1 byte. Recorded Windows-reserved path names/characters and known zero-byte audio files are also flagged. These checks read captured metadata, not the audio. They do not validate decoding, sample rate, bit depth, firmware, a device database or physical playback; no result certifies a USB export. Compare with the [Microsoft filesystem limits](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison).

**Review tempo & keys:** compare saved BPM against captured XML average BPM and up to 32 distinct XML tempo values per track. Disagreements over 1% (with a 0.1 BPM minimum tolerance) are advisory; half/double-tempo relationships are called out and variable-tempo grids may be intentional. New XML/ZIP imports retain this evidence. Older or native-only snapshots can lack comparative tempo data and stay Unknown; capture fresh matching inputs when needed.

Recognized saved keys appear in Camelot wheel order, retaining the original notation. Major/minor and common sharp/flat equivalents are normalized only in the report. Unknown labels remain visible. No audio is analyzed, no key is inferred, and BPM, key and grid values are never rewritten by these checks. Normalization and edits still use the separate, explicit staging workflow.

## Input identity and text validation

New imports record streaming SHA-256 fingerprints of the complete XML and ZIP files. Resume and export verify recorded content; exports check again before publication. Changing bytes while preserving size and modification time is therefore rejected. Existing workspaces without full-file hashes first validate their recorded XML digest and native pair signature before upgrading. This does not retroactively provide a full-file baseline for earlier versions. Reattaching originals retains recorded full-file identities even when paths change. Hashing large backups requires additional disk reads and can be cancelled at chunk checkpoints.

All exportable text overrides reject XML-invalid characters before saving. Rejected edits preserve previous values, history and revisions; normal multilingual text and emoji remain supported. Comments retain their separate newline/tab allowance.

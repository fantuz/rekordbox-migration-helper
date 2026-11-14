# Collection and session intelligence

Open **Library intelligence** under Analysis & insights. Choose a saved collection snapshot, or select the same snapshot in the shared Collection context. Source captures remain immutable; these views do not apply working metadata overrides.

| View | What it measures | Interpretation |
| --- | --- | --- |
| Playlist overlap | Shared captured track IDs divided by the union of IDs; selectable minimum, 50 results per page | Equal membership and equal saved order are separate. Repeated entries do not inflate membership. Overlap can be intentional; no list is removed. Name-only captures can combine equally named playlists. |
| Session progression | Captured BPM, tonality and colour in saved native session order | Adjacent BPM differences stay unknown if either tag is absent. These are captured tags, not measured transitions, individual play times or actual gig duration. |
| Collection evolution | Unique guarded matches, unmatched records, changed fields and artist/genre distribution changes | Unmatched can mean new, removed or ambiguous. No deletion is inferred. The 30 largest distribution changes per field are shown. |
| Duplicate impact | Record totals and distributions before/after excluding donors from the loaded workspace's validated staged merges | This is a record-count view of the current cleanup plan. It does not estimate distinct recordings, delete audio or claim freed disk space. |

Snapshots can represent different export scopes or dates. Check their capture context before interpreting growth or changes. Distribution counts include duplicate records. Evolution is a summary; use **Compare snapshots** for individual cue, rating and playlist findings.

**Save evidence report** recomputes the selected view on the server and keeps it locally in Library lab. Session and overlap reports retain the current 50-row page plus overall counts and page position, explicitly labelled as a retained page. Reports and completed summaries remain after temporary input cleanup.

## Playlist contents and lateral views

Browse captured playlist members with preserved repeated entries, saved positions when available, missing-metadata flags and bounded search/pagination. Smart playlists show the members captured at that time; their rules are not re-evaluated.

Collection lenses show all tracks, tracks outside captured playlists, tracks occurring in at least two saved history sessions, and tracks absent from captured history. Recurrence counts sessions, so repeated plays within one session do not qualify by themselves. Missing history coverage is disclosed; absence is never labeled as proof that a song was never played. Summary counts and page reports retain their evidence scope.

The same page contains reviewed [chart-to-playlist export](CHART-PLAYLISTS.md) and the [Serato interoperability draft](SERATO-BRIDGE.md). [Local playback](TRACK-PLAYBACK.md) is available alongside captured track titles.

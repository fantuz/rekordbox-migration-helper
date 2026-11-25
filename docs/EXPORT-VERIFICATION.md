# Independent export verification

Prepared rekordbox XML and native ZIP files are read independently before the completed export folder becomes available. A writer returning success is insufficient.

Before either writer runs, expectations are frozen from the original XML and encrypted database, the reviewed merge/cue decisions, reference edits and staged metadata. The reader compares the completed files against those expectations. It does not use a snapshot of the generated database as its expected result.

| Output | Comparisons |
| --- | --- |
| XML | Exact surviving IDs, track attributes and references, cue labels/positions/colours, saved tempo/grid entries, collection count, playlist hierarchy and ordered references, including repeated entries |
| Native ZIP | Database schema, active content metadata and references, resolved artist/album/genre/key/colour values, native cue rows and serialized cue summaries, playlist hierarchy and order columns, active content relations and backup contents count |
| Other ZIP members | Member names, original CRC and uncompressed size; existing writer checks also preserve compressed members |

Native bookkeeping timestamps, synchronization flags and update counters are excluded from semantic equality. Generated lookup IDs are resolved to the reviewed field values. Existing personal metadata is preserved unless covered by the frozen decisions. Native-only tracks required by XML playlists are checked against the original database and saved grids.

The private `report.json` records the verification basis, comparisons and an expectation digest for each format. A mismatch raises an error and removes the pending set, so half a pair or a failed result is not listed in Completed exports. Sources are never edited.

Read-back validation does not decode audio, authenticate third-party metadata or certify a restore in rekordbox. Unchanged archive CRC/size comparisons are not a fresh SHA-256 audit of every analysis or artwork file. Test generated copies in an isolated library on their selected Windows/macOS target before replacing a working library, with Cloud Library Sync paused as described in the recovery guide.

Regression tests generate encrypted fixtures and deliberately alter playlist order, file references, cue labels, metadata and tempo entries after writer validation. They assert that the independent reader blocks publication. Other tests cover preserved repeated playlist entries, merges and native-only playlist recovery.

## Hot Cue Banks and duplicate merges

A Hot Cue Bank can refer to a cue by ID, even when the bank entry omits its track ID. Before a native ZIP export, Workbench checks active bank entries and their serialized copies against the staged duplicate merges. A merge can move a donor cue to the keeper, retire a cue, or change the label or colour on a keeper cue.

If a bank relies on an affected track or cue, Workbench identifies the merge by its donor and keeper track IDs. Unstage that merge in **Duplicate review** to export the rest of the selection. To carry the merge forward, review the linked bank in AlphaTheta Rekordbox, then create a fresh matching backup ZIP and collection XML. An unreadable active bank holds the native merge until Workbench can establish which entries it references.

The check applies to the native ZIP, including a paired XML and ZIP export. A separate XML export remains available. Metadata-only exports and merges with unrelated bank entries continue normally. The independent native reader also compares the active serialized bank records when verifying the generated ZIP.

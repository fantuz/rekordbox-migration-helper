# Guided library journeys

The home page offers four starting points: **Check library health**, **Migrate a library**, **Review duplicates**, and **Share & offline summary**. They use the same source captures, immutable Library lab snapshots, media inventories and staged decisions as the existing tools.

## Collection context

The collection selector records which loaded workspace, existing Source analyzer capture or saved snapshot you are inspecting. For a saved snapshot, it carries the original capture date, scope, track count and available capabilities. Source captures and loaded workspaces offer a link to save an immutable snapshot before using snapshot-only tools. The selector synchronizes the snapshot choices in Library lab, DJ insights, Library bubbles, Tonality and Play history when that snapshot is available there. Selecting a source does not scan a folder, change the original database, or apply cleanup decisions.

The context distinguishes captured metadata from the number of staged metadata overrides. Snapshot comparison uses captured values. Export controls explicitly state whether working overrides are included; neither a context selection nor a comparison applies merge or relocation decisions to a captured snapshot. A currently loaded workspace has no claimed capture timestamp until a snapshot is saved.

## Migration assistant

The saved checklist follows this sequence:

1. Keep a fresh, separate, untouched **Backup Library** backup. Preserve audio separately if excluded from the ZIP.
2. Capture the source library and save an immutable snapshot in Library lab.
3. Check audio availability in selected Media inventory roots. Make cloud audio available locally as needed. Dropbox or Google Drive music roots can differ from the database location.
4. Record destination paths as planning notes. Use **File references** to stage actual reference changes; typing a destination into the checklist moves nothing.
5. Optionally review duplicates and metadata. Cleanup can be skipped.
6. Create the XML/native ZIP working-copy exports. The existing backup acknowledgement and native-version gates still apply.
7. Follow the [export and restore guide](INPUTS-AND-RESTORE.md) on the destination, with an untouched backup available and cloud sync paused for an isolated test. A native restore and an XML import are alternative routes.
8. Capture the restored destination using Source analyzer, save another Library lab snapshot, choose both snapshots in the journey, and compare them.

The destination comparison uses the existing safe, unique identity matching. It reports changed or unmatched cues, personal stars, metadata and playlists where those fields are captured. Unmatched records and unavailable fields are not silently treated as cue loss or a successful migration. Review the report and test actual playback on the destination.

Checkmarks are explicitly **user confirmations**, not machine verification. Recording the cloud Copy/Move setting is also a user statement; the tool cannot reliably infer that choice from paths alone. Notes, snapshot references, checklist progress and small reports are retained in the separate local SQLite sidecar after temporary source copies are cleaned up. Changing the selected comparison snapshots clears the old comparison link; the old report itself remains available in Library lab.

## Integrity checker

**Quick** uses the selected captured metadata and any corresponding saved native/XML source report. It combines database integrity/schema results, broken record references, repeated recorded-path candidates and metadata consistency. It reuses a saved Media inventory only when it belongs to the exact same workspace scope.

**Deep** adds an inventory of the analysis folders or backup ZIPs you explicitly enter, one per line. With no analysis location supplied, assets remain **Not checked**. It does not scan default folders or read audio automatically. Use Media inventory separately to inspect chosen music roots or explicitly verify audio bytes.

Results distinguish:

| State | Meaning |
| --- | --- |
| Issue | A captured database integrity/schema failure or broken record reference was recorded. |
| Needs review | Evidence suggests a candidate or quality gap; it does not establish a destructive fix. |
| Unknown | Evidence or inventory completeness is insufficient. |
| Not checked | This check was not performed or its required saved report is absent. |
| No finding in scope | The available check found no issue in its stated captured/selected scope. |

There is no overall health score. XML cannot establish native database integrity. A path absent from selected roots can exist elsewhere; unreferenced analysis assets may belong to another library. Cloud-only placeholders are not locally playable audio. Asset filename hints do not prove STEMS readiness. No journey deletes source files or writes a live rekordbox library.

## Validation boundaries

Synthetic regression cases cover persistence, unknown/not-checked distinctions, explicit deep scopes, comparison invalidation, and user confirmations. Run them through GitHub CI with the rest of the suite. Genuine v6 captures, cloud Copy/Move fixtures, classic device and OneLibrary samples, and a fully recorded native restore checklist remain separate validation tasks. The existing Windows 11 user-reported restore result is useful evidence, not certification of every version or feature.

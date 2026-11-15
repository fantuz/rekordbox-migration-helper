# Optional library journeys

Open **Library journeys** in the sidebar. Choose a goal, start a checklist, add notes and confirm the steps you performed. Use **Resume a journey** to continue later. These confirmations are your statements; they do not prove that a migration, backup or restore succeeded. You can open any tool from the sidebar at any time.

| Goal | Suggested sequence | Current boundary |
| --- | --- | --- |
| Rekordbox → Serato | Separate backup, capture, snapshot, optional cleanup, Serato draft, destination checks | Basic database and static crates; actual Serato import remains unverified |
| Serato → Rekordbox | Separate backup, review limitations, external migration, capture the resulting rekordbox library, check tracks and playlists | No Serato reader/importer or automatic converter is implemented |
| Check library health | Capture, statistics, consistency checks, file references, history | File availability and metadata completeness are separate checks |
| Review duplicates | Backup, capture, candidate review, playlist impact, copy export | Native candidate classification does not merge tracks; copy transformations require supported inputs |
| MusicBrainz metadata | Capture, snapshot, opt-in pilot, review matches and staged edits, copy export | Remote results are suggestions, not automatic personal ratings |
| Metadata editor | Capture, snapshot, bubbles, edit fields, compare snapshots | Original libraries remain unchanged |
| Share & offline summary | Capture, choose sharing scope and privacy, export and review | HTML/CSV/JSON exports contain metadata, not music files |
| Backup and recovery | Create a backup in rekordbox, capture evidence, restore in rekordbox, compare destination | Workbench does not create a full native backup or perform a live restore |

## Migration direction matters

For **Rekordbox → Serato**, follow [Serato draft limits and testing](SERATO-BRIDGE.md). Keep the generated database and crates separate from a working Serato library until they have been tested.

For **Serato → Rekordbox**, preserve the Serato library and music first. Workbench cannot yet decode that library or transfer its cues, grids, ratings or crates into rekordbox. Complete the migration using a separately verified external workflow. Then select the resulting rekordbox database or XML in Source analyzer and check collection totals, paths, playlist membership and order. Validate playback and preparation in rekordbox itself. A checked box does not mean the application has performed those actions.

## Sharing with friends

A metadata export helps friends browse your collection without receiving audio. It represents your selected collection; it is not the invented test data used in project screenshots. Choose the sharing preset and review which paths, notes and identifiers are included before sending the exported file. Workbench does not send files to other people.

## Backup and Windows startup

Follow [the input and restore guide](INPUTS-AND-RESTORE.md) for backup creation and restore inside rekordbox. Keep the backup separate from the working library.

For an unsigned Windows build obtained from this project's GitHub Releases, the SmartScreen sequence is **More info → Run anyway**. Check that the app name is **Library Workbench.exe**. If policy blocks the option, contact the administrator; do not disable system protection. See [Microsoft's Windows publishing guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/publish-first-app).

# Isolated rekordbox restore test

1. Use a separate Windows test profile or machine with the same rekordbox release. Keep the production library and its untouched Backup Library archive separate. Preserve the audio too when it is not in that archive.
2. Keep Cloud Library Sync paused on the test instance. Do not connect a restored test library to the production cloud library during initial validation.
3. Import a consecutive XML/ZIP pair into Library Workbench. Start with a small, reviewable set of duplicate/reference decisions. Acknowledge the separate untouched backup, then generate the paired outputs.
4. Read `report.json`: verify the decisions, mappings, validation results and recorded input paths. XML and ZIP may cover different track scopes while sharing the same decision snapshot.
5. Use rekordbox **File → Library → Restore Library** with `edited-library.zip` in the isolated instance. The XML output is an alternative import/inspection representation, not an instruction to import the same tracks a second time after a native restore.
6. Check collection counts, representative playlists, ratings, memory cues, hot cues, loops, beat grids, artwork, file relocation and playback. Include manual-cue keepers, automatic-only keepers and a multi-sibling group.
7. Record the exact rekordbox version and outcome. Keep the production backup until native restore and the intended cloud reconciliation procedure have both been validated.

A passing archive, SQLCipher or CI check does not replace this application-level test. There is no direct source-folder overwrite operation in the current analyzer.

## User-reported result

The maintainer reported that the Windows utility and restoration worked on **Windows 11**, with the rekordbox version recalled as **approximately 7.2.19**. The report did not specify whether the native ZIP or XML route was used, or enumerate every item in the checklist. This is encouraging user-reported evidence, not a claim of complete validation for that version or other setups.

For the basic file-creation and restore steps, see [Create your input files and restore an edited copy](INPUTS-AND-RESTORE.md).

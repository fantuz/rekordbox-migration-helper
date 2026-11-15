# Saved reports, caches and starting fresh

Open **Saved investigations** to manage Workbench's own saved work. Original music, rekordbox databases, linked or uploaded inputs and completed exports are outside these cleanup actions.

- Source, discovery and storage summary reports are published with an atomic file replacement, so interrupted writes do not expose half-written JSON. SQLite reports already use transactions.
- **Open report** in Source analyzer reopens saved evidence without scanning the source again. A new analysis is a separate action. The saved collection context and reports persist; custom discovery depth and the analyzer path are not application preferences.
- Saved-collection statistics, duplicate candidates and file-reference pages reuse a persistent derived-result cache. It is bounded to 64 results and 16 MiB of JSON, with a seven-day expiry. Keys include the selected snapshot digest or saved capture file stamps, filters and duplicate-review decisions. Mutable XML/ZIP workspaces are not cached here. No audio availability or live scan is inferred from a cached result.
- **Clear result and provider caches** removes derived responses, insight indexes and cached provider responses. Reports, captures and metadata edits remain. Another provider lookup still requires the normal consent and rate controls.
- **Preview cleanup** and **Archive selected investigations** remove selected work from menus while keeping recovery available. Dependencies are shown first. Discovery and storage reports, and incomplete source captures, appear alongside the other saved investigations.
- **Start fresh with an archive** previews all current investigations, including the loaded workspace. Confirming archives them and staged metadata edits, clears result/provider caches, clears the current collection and detaches loaded workspaces. Existing archives remain available. Language, theme and sidebar appearance are kept.
- **Delete archived investigations** previews all existing archives for permanent deletion. It requires a separate acknowledgment. Recovery is no longer available afterwards. If some archives must be retained, restore those investigations before deleting the remaining archives.

Active tasks and provider jobs must finish or be cancelled before cleanup. Temporary database and upload copies are handled by **Stop and clean up**; starting fresh does not claim to remove the running application's temporary directory. SQLite may reuse freed space rather than immediately shrinking its database file.

A fresh workspace and permanent deletion are deliberately separate actions: beginners can get an empty working state first, review the archive, and choose later whether to discard it.

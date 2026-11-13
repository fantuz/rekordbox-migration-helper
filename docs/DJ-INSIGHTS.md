# DJ insights, bubble maps, tonality and track comments

All these views run locally over retained Library lab/history snapshots. Choose a saved snapshot or capture the loaded XML + ZIP workspace. To use a source folder or standalone XML, run Source analyzer and save its capture in Library lab. No source database is queried in place, no audio is analyzed, and no metadata is sent to an online chart service.

## Rotation and discovery

DJ insights offers most played, least played (positive counts), known zero usage, prepared with no recorded usage, highly rated but underplayed, rediscovery of past rotation, recently added, recently used, preparation opportunities, random discovery and all matching entries. Personal stars and saved plays remain separate signals; playing a track does not establish that it is a favourite.

Select an evidence basis:

- **Saved play count:** the captured native/XML counter. Its completeness and reset history are unknown. Missing stays unknown rather than becoming zero.
- **Captured history entries:** occurrences in decoded saved sessions. Repeated plays count separately; optional start/end dates restrict sessions. Undated sessions are included only without a date filter. Zero means no occurrence in that captured scope.
- **Distinct captured sessions:** how many captured sessions include the entry, counting repeats inside one session once. This is useful for finding tracks used across gigs, but does not establish each session's purpose.

History dates are session dates, not timestamps for individual plays. Entries outside the captured active collection are reported and excluded from track-based metrics. Legacy/metadata-only inputs without native history cannot use history evidence. Last-use dates later than the snapshot reference are flagged and excluded from “Recently used”; they remain inspectable elsewhere.

Filters include genre family, exact saved tag, saved tonality, track colour, known-zero/low/positive/unknown usage, preparation, title/artist/album text, BPM, duration and personal stars. “Prepared” specifically requires a saved analyzed flag and at least one cue classified as manual. Cue origin is inferred from editable labels. Underplayed thresholds and the rediscovery age are user choices; rediscovery uses a displayed snapshot reference date, not an invented play date.

Uniform random sampling treats each matching entry equally. Genre-balanced sampling selects entries in shuffled rounds across families, giving small families more opportunity. The seed makes a selection reproducible; “Surprise me” changes it. Duplicate recordings can still appear as different library entries.

The genre-balance panel compares shares of entries with known usage to shares of recorded usage in the filtered collection, before the selected perspective. Unknown counters do not lower a group's score. If total recorded plays are zero, the exploration gap is unavailable rather than a fabricated preference score. Top-ten concentration is another descriptive measure, not a judgement about how a set should be played.

## Bubble explorer and Colour cloud

Click a category to narrow the collection. The default path is genre family → saved genre → artist initial → artist → tracks. Choose a different next dimension, including release/addition year, BPM band, personal stars, usage, cue preparation, format, tonality or track colour. Breadcrumbs return to earlier branches.

Circle **area**, not radius, represents track count, recorded usage from the selected evidence, or the sum of full track durations. Durations are not actual time played. Up to 60 categories are drawn per page to keep large collections responsive; exact totals, paging and the accessible category list remain available. Zero/unknown weights stay in that list even when a circle cannot be drawn. Compare circle areas within one displayed page. Individual tracks can be inspected from bubbles or tables.

Genre families use explicit word/phrase aliases in saved tags, not a new audio classifier. A tag matching multiple families goes into “Mixed families” once. Unmapped tags, blank/unknown genres and generic electronic labels remain visible. The exact saved tags behind a bubble and the grouping rules can be inspected. No genre is rewritten by these views.

**Colour cloud** starts with saved track colours. Assigned, unassigned and uncaptured colours are distinct. Native `ColorID` joins `djmdColor`; its saved `Commnt` supplies the configured label. When `ColorCode` is absent, the standard eight-colour palette is inferred from `SortKey` and labeled as an inference. Unsupported/missing RGB remains neutral. XML uses an explicitly exported `Colour` RGB field; an absent field is unknown, not proof of no assigned colour. Track colours are separate from hot-cue colours.

DJs describe using colours for energy/mood, set position, vocals, favourites and technical preparation reminders. There is no universal mapping. Source labels are preserved, and an optional **local legend** can name a hue “opener”, “banger”, “finale” or anything useful to its owner. Those labels are sidecar preferences, never writes to rekordbox's colour table.

Sources: [official rekordbox XML fields](https://cdn.rekordbox.com/files/20200410160904/xml_format_list.pdf), [official v7 manual](https://cdn.rekordbox.com/files/20251202174516/rekordbox7.2.8_manual_EN.pdf), [DJs' own colour workflows](https://www.reddit.com/r/Rekordbox/comments/tar386), [Pioneer DJ community: configured colour names](https://community.pioneerdj.com/hc/en-us/community/posts/22979656433177-Track-Ratings). Community examples are individual practices, not a statistical claim about all DJs. References reviewed 13 November 2026.

## Tonality and tempo

Tonality & tempo shows saved-key coverage, a clickable 10-BPM histogram, and per-key usage/mean/median BPM tables. Overall BPM mean, median, range, known/unknown counts and mean/median full track length appear alongside the other insight views. Means weight each entry equally. Missing/zero BPM is excluded from BPM statistics; missing track lengths stay unknown.

Keys come from XML `Tonality` or native `djmdKey.ScaleName` through `KeyID`. Different saved notations remain separate; there is no automatic enharmonic, Camelot or Open Key conversion, audio key detection, harmonic-compatibility guarantee or half/double-time BPM correction. Older Workbench snapshots need a new capture to include fields that were not previously retained.

## Track comments and responsible edits

Open an individual **File view** from insight tables, a track bubble, Duplicate review or the Library lab editor. **Comments** is a collapsed section. Comments can be staged without unlocking other fields; they are not displayed in collection tables, CSV, insight reports or shareable HTML. Existing whitespace/newlines are preserved. The editor accepts up to 4,096 characters and rejects invalid XML/control characters. A blank working value explicitly clears the comment in generated copies; resetting removes the working override and restores the captured value.

Other metadata is behind a collapsed panel and an explicit unlock warning. Unlocking is for the same snapshot scope; title, artist, album, genre, year and personal stars use the existing guarded override workflow. Tonality, colour and BPM are inspection fields here. No original files or audio tags are changed.

Comments are stored in the retained local sidecar and can participate in XML `Comments` / native `Commnt` copy export from the **same loaded workspace**. Export checks the captured baseline and holds conflicting donor/keeper edits. Source-folder snapshots do not attach edits to an unrelated XML/ZIP workspace. An old snapshot without its original comment can retain a working note, but a matching fresh capture is needed before applying it safely. Rekordbox may include My Tag text in Comments; this utility does not parse, remove or rewrite that text automatically.

Insight charts describe captured values. Staged overrides remain separate; use the existing working HTML/export workflow to review their projection. Native ZIP transformation still requires an untouched-backup acknowledgement and an isolated Windows rekordbox restore test.

## Reports, downloads and packaging

Download the entire matching view as CSV, including its evidence label. Spreadsheet-formula prefixes in text cells are neutralized. Seeded-random CSV exports contain the selected sample. “Keep an insight report” retains counts, filters and the first 200 ranked/sample entries with other local Lab reports; the cap is explicit. Visible bubble maps can be saved as standalone static SVG, including a description of the current branch/metric. SVG is a picture of the displayed page, not an interactive backup.

Reports, decisions, comments, preferences and deliberate downloads survive temporary-input cleanup. Comments remain private to the file-view/working store and prepared library copies. Shareable metadata explorers add tonality and track-colour categories while excluding comments.

Bubble layout uses a bundled, integrity-checked [d3-hierarchy 3.1.2](https://github.com/d3/d3-hierarchy) build under ISC, with license/provenance in `static`. It requires no CDN, JavaScript package installation or internet at runtime. The native packaging checks exercise the insight APIs and bundled chart asset on Windows and both Mac architectures; they do not exercise a licensed rekordbox restoration.

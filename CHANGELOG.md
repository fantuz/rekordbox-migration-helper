# Changelog

## Unreleased

- Self-contained Linux x86-64 TAR.GZ with bundled Python/dependencies, a glibc 2.28 build baseline, Ubuntu 22.04 executable checks and an XDG workspace. Linux source remains available.
- Five-archive release verification and download tables include the new native Linux package. Existing 1.0.0 assets are unchanged.
- Source discovery reads location fields from rekordbox Agent options and saved preferences, finds external Master folders, and maps Windows/Mac profile hints inside user-mounted volumes without mounting disks or exposing unrelated options.
- Multi-copy review lists all members, supports donor exclusions, previews accumulated cue/rating conflicts and direct-match requirements, and stages compatible donors with reversible batch history.
- Prominent, translated ZIP/XML creation and restore instructions link to a bundled step-by-step guide. The guide distinguishes native restore from alternative XML import and explains separate audio preservation.
- English interface and Markdown spelling checks run in GitHub CI. A Windows 11 restore report is recorded with the approximate user-recalled version and its limits.

## 1.0.0 — 2026-11-13

The first 1.0 milestone brings the current library analysis, cleanup preparation and migration tools together in Windows x64, Mac Intel, Mac Apple Silicon and Linux source downloads. Native rekordbox ZIP restoration remains experimental and needs an isolated Windows restore test.

- Library tools include duplicate/cue review, reference and cloud-copy checks, snapshot comparison, analysis/STEMS audits, history browsing and genre/BPM preparation coverage.
- DJ insights, tonality/tempo statistics and offline HTML/ZIP metadata explorers support reviewing a collection without sharing audio or private comments.
- Nine interface languages, retained decisions/reports and acknowledged temporary-copy cleanup support repeatable local workflows. MusicBrainz remains an optional, explicitly enabled proof of concept.
- Release notes now list all six downloads directly: four platform archives, checksums and the complete commit log with full messages. Linked commit summaries include merged branches and a comparison with the previous stable release.

- Colour cloud: explicit loaded-library capture, visible source/loading/empty states, bounded group-detail calculations and a large-library regression.
- Bubble maps: expanded canvas, stable wider circle spacing and a fixed horizontal category-detail panel.
- Readability: grouped, resizable text navigation, compact header, balanced summary cards and larger duplicate-review controls and comparison details.
- File view: comments open directly, labelled colour palette saves without unlocking, and private export recaps retain saves and resets. Working colour edits map to verified native IDs or documented XML RGB values.
- Language changes preserve inspected comparisons, keeper choices and draft options; removed comparisons use a valid fallback.
- Centred operation progress blocks navigation during long tasks. Native ZIP copying and verification report progress inside large members.
- Download badges follow the project platform layout; new package/artifact names omit the preview suffix and release notes generate platform links.
- Additional translation-catalogue, locale/storage, responsive-layout and three-engine browser checks run on GitHub alongside native package validation.

## 0.4.5 — 2026-11-13

- DJ Insights: most/least played, preparation opportunities, rediscovery and repeatable random picks, with separate saved-count, history-entry and session evidence.
- Interactive library bubbles and Colour cloud: drill into genre families, artists, years, musical keys and saved track colours; size by track count, recorded usage or duration; save a personal colour legend and export SVG/CSV reports.
- Tonality & tempo: saved-key coverage, BPM histograms, mean/median/range and duration statistics. Unknown values stay explicit.
- Per-track File view: freely staged Comments in a collapsed editor, with explicit unlocking for other metadata and guarded XML/native-copy export.
- Library lab: snapshot cue/rating/playlist comparison, metadata consistency, collection coverage and analysis/STEMS asset audits. Retained snapshots also support play-history browsing and offline HTML/ZIP metadata explorers.
- Opt-in MusicBrainz proof of concept: bounded sampling, selectable request pacing, separate local evidence and a disable flag. No background provider queries.
- Temporary analysis copies are removed on acknowledged shutdown; reports, review decisions, comments and deliberate exports remain available.
- Automatic native builds for pull requests and `main`, automatic preview releases for version tags, a web release form, checked package/source digests and dependency audits. Windows x64, Mac Intel, Mac Apple Silicon and Linux source downloads are included.

Native ZIP restoration inside a licensed Windows rekordbox instance still needs real-world validation. Mac packages are ad-hoc signed and are not notarized. Keep an untouched rekordbox backup before preparing transformed copies. Private libraries and audio are not distributed.

## 0.4.0 — 2026-11-12

Initial public portable preview: local library analysis, duplicate/cue review, copy preparation and Windows/macOS/Linux packages. Later library-lab and DJ-insight features are included in 0.4.5.

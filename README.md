# rekordbox Migration Helper · Library Workbench

<!-- project-badges:start -->
<p align="center">
  <a href="https://github.com/fantuz/rekordbox-migration-helper/actions/workflows/check-and-package.yml"><img src="https://github.com/fantuz/rekordbox-migration-helper/actions/workflows/check-and-package.yml/badge.svg?branch=main" alt="Build and native runtime checks" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/actions/workflows/security.yml"><img src="https://github.com/fantuz/rekordbox-migration-helper/actions/workflows/security.yml/badge.svg?branch=main" alt="Security checks" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/actions/workflows/release.yml"><img src="https://github.com/fantuz/rekordbox-migration-helper/actions/workflows/release.yml/badge.svg" alt="Release packages" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/releases/latest"><img src="https://img.shields.io/github/v/release/fantuz/rekordbox-migration-helper?label=release" alt="Latest stable release" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/releases"><img src="https://img.shields.io/github/downloads/fantuz/rekordbox-migration-helper/total?label=downloads" alt="Downloads" height="20"></a>
  <br>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/fantuz/rekordbox-migration-helper" alt="MIT license" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/stargazers"><img src="https://img.shields.io/github/stars/fantuz/rekordbox-migration-helper?style=flat" alt="GitHub stars" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/issues"><img src="https://img.shields.io/github/issues/fantuz/rekordbox-migration-helper" alt="Open issues" height="20"></a>
  <a href="https://github.com/fantuz/rekordbox-migration-helper/commits/main"><img src="https://img.shields.io/github/last-commit/fantuz/rekordbox-migration-helper/main" alt="Last commit on main" height="20"></a>
  <br>
  <a href="#start"><img src="https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20%7C%20macOS-507269" alt="Supported platforms" height="20"></a>
  <a href="#start"><img src="https://img.shields.io/badge/Python-3.13%2B-3776ab" alt="Linux source runtime: Python 3.13 or newer" height="20"></a>
  <a href="docs/LOCALIZATION.md"><img src="https://img.shields.io/badge/interface-9%20languages-2e7d32" alt="Nine interface languages" height="20"></a>
  <a href="SECURITY.md"><img src="https://img.shields.io/badge/security-private%20reporting-507269" alt="Security policy and private reporting" height="20"></a>
</p>
<!-- project-badges:end -->

A local browser application for understanding a rekordbox library, reviewing duplicates and preparing edited copies. Use it to prepare a move to a new computer or compare a library before and after a version change: inspect references, preparation and history, then verify the target collection. Linux is the primary development platform. Windows and macOS portable applications are built and exercised by CI.

**DJ insights** adds explainable rotation/discovery views, seeded genre-balanced random picks, a clickable bubble explorer and **Colour cloud**. **Tonality & tempo** inspects saved keys, BPM distributions and duration statistics. A collapsed per-track Comments editor stages notes freely; other metadata still requires an explicit unlock. Everything runs locally over retained snapshots. See the [DJ insights guide](docs/DJ-INSIGHTS.md) for evidence sources, unknown values, grouping rules, colour meanings, privacy and copy-export limits.

The interface offers German, French, Italian, Spanish, Greek, Polish, Czech and Russian alongside English. Controls and offline explorers are localized; source metadata, paths, machine-readable fields and raw diagnostics retain their values. Routine panels use concise technical wording, with detailed procedures in the built-in **Documentation** view. See [translations](docs/LOCALIZATION.md), [Unicode/input checks](docs/UNICODE-INPUTS.md) and [contributing](CONTRIBUTING.md).

See the [migration workflow](docs/MIGRATION.md), [format sources for v5/v6/v7 XML and native libraries](docs/FORMAT-SOURCES.md), and [path discovery, analysis/STEMS audit and play-history guide](docs/DISCOVERY-ASSETS-HISTORY.md). The light interface uses blue/green emphasis, prominent duplicate-pair counts and compact tables. Statistics and offline explorers separate addition year from release year. Native histories remain private local snapshot data, browsable after temporary database cleanup.

**Keep a fresh, untouched backup created by rekordbox Backup Library outside this workspace before generating transformed files. Preserve the audio separately when it is excluded from the backup. Native ZIP restoration in rekordbox remains experimental.**

## Start

<!-- project-downloads:start -->
<p align="center">
  <a href="https://github.com/fantuz/rekordbox-migration-helper/releases/latest#downloads"><img src="https://img.shields.io/badge/Download%20now-Windows%20x64%20portable%20ZIP-0078D4?style=for-the-badge" alt="Download now — Windows" height="28"></a>
</p>

<p align="center">
  <a href="https://github.com/fantuz/rekordbox-migration-helper/releases/latest#downloads"><img src="https://img.shields.io/badge/Download%20now-macOS%20Intel%20x86--64-555555?style=for-the-badge" alt="Download now — Mac Intel" height="28"></a>
</p>

<p align="center">
  <a href="https://github.com/fantuz/rekordbox-migration-helper/releases/latest#downloads"><img src="https://img.shields.io/badge/Download%20now-macOS%20Apple%20Silicon%20ARM64-222222?style=for-the-badge" alt="Download now — Mac ARM" height="28"></a>
</p>

<p align="center">
  <a href="https://github.com/fantuz/rekordbox-migration-helper/releases/latest#downloads"><img src="https://img.shields.io/badge/Download%20now-Linux%20source%20%7C%20Python%203.13%2B-2e7d32?style=for-the-badge" alt="Download now — Linux" height="28"></a>
</p>

<!-- project-downloads:end -->

The buttons open the latest stable release’s automatically generated **Downloads** table. Choose the row for your platform; older and prerelease builds remain under [Releases](https://github.com/fantuz/rekordbox-migration-helper/releases). See [what changed in 0.4.5](CHANGELOG.md).

On Linux, use Python 3.13 or newer and run `./start.sh` from this directory. The first launch installs requirements into a local virtual environment. The application opens your browser and binds only to loopback. Use **Stop local application** in its footer when finished.

Windows users extract the complete portable ZIP and double-click **Library Workbench.exe**. Python and dependencies are included. Mac users choose the Apple Silicon (`arm64`) or Intel (`x86_64`) archive, extract it and open **Library Workbench.app**. Mac applications are ad-hoc signed, not Developer ID signed or notarized; macOS may restrict opening them. Source checkout remains available for developers.

## Two workflows

1. **Source analyzer** reads a source data folder through a private database/journal snapshot. It reports integrity, schema compatibility, track/cue/playlist counters, reference issues and selected-folder footprint. It does not modify the source. Close rekordbox and pause Cloud Library Sync during capture. No XML or ZIP input is required for this mode.
2. **Import XML + ZIP** loads a consecutive Backup Library ZIP and collection XML export. Choose files to copy them into a workspace, or use existing files by full path without another large copy. Compare duplicate groups, cues, ratings and file references, then generate XML and native ZIP together from one frozen decision snapshot.

The **0.4.5 Library lab preview** adds snapshot comparison, metadata consistency, analysis asset audits, genre/BPM preparation coverage and a locked metadata editor backed by a separate local SQLite store. An opt-in MusicBrainz pilot previews 20 tracks per top genre plus 50 unknown-genre tracks, with selectable lookup pacing and separate community-rating evidence. Sources stay unchanged. See the [Library lab guide](docs/LIBRARY-LAB.md) for scope, privacy, export behavior and limits, and the [changelog](CHANGELOG.md) for additions since 0.4.0.

The preview also reads standalone collection XML for v5 statistics (track counts, artist, title, BPM, duration and other available tags). Native v5 `.edb` records remain undecoded. Analysis copies are removed on acknowledged shutdown; reports, decisions and completed exports are retained. See [temporary-file cleanup and resuming](docs/TEMPORARY-FILES.md).

The **Files & workflow** page explains each step and shows the input and output paths. Completed exports remain downloadable after restarting. Separate single-format exports are also available. Both writers must validate a paired export before its files become available. XML keeps its input collection scope, which can be narrower than the native backup when cloud/device cohorts differ.

Cloud Library Sync supports **Dropbox or Google Drive**. The cloud music folder and the master database folder can differ. Suggested Windows/Mac locations and saved database settings help locate a source, and manual path entry is always available on all platforms. Online-only audio should be downloaded before file-byte verification or playback testing. This application does not authenticate to or operate the cloud providers.

## Compatibility status

| Library | Current handling | Evidence and limits |
| --- | --- | --- |
| v5 and earlier `.edb` | Format detection and file footprint | Legacy records are not decoded or converted |
| v6 `master.db` | Schema-based read-only checks | Same modern SQLCipher family; genuine v6 sample validation pending |
| v7 `master.db` | Read-only checks and experimental copy preparation | Reader/writers checked with v7.2.19 backup data on Linux; rekordbox restore test pending |
| USB `export.pdb` / `exportLibrary.db` | Detected as a device export | Not treated as the desktop master library |

The major desktop conversion was v5 → v6. AlphaTheta documents that v6 → v7 needs no library conversion. This tool does not implement version downgrading. A format match or successful CI run does not establish that rekordbox will restore a generated backup correctly. See [compatibility and validation](docs/COMPATIBILITY.md).

## Review features

- Manual or mixed cues take keeper priority over automatic-only cues. Newest-added, last-played or play-count policies break ties. Cue origin is inferred from editable labels.
- Connected recording groups support one keeper across multiple siblings, with accumulated cue checks, held conflicts and undo.
- Evidence filters include recorded paths, saved preview waveforms, cue/grid agreement, ratings, usage, XML membership and optional local file hashes.
- Filters cover track length, cue category, album, artist, genre, label, format, BPM, bitrate, playlist and media availability. Saved views and resumable workspaces retain work locally.
- Media inventory scans only selected roots. SHA-256 reads audio only on explicit request, and unavailable cloud placeholders are held.

## Cloud/local storage audit

**Cloud & storage** compares explicitly selected local, Dropbox and Google Drive music folders. It reads file metadata first and shows visible logical bytes, OS-reported local disk allocation, detected placeholders and possible extra copies. These are scoped folder measurements, not provider account usage.

Copy/Move/Unknown is a user-supplied history hint. An optional source-analyzer report links original/current database paths to physical locations, including renamed cloud files. Multiple database records pointing at one file are distinguished from multiple physical files. Exact filename and size are candidate evidence; explicit SHA-256 verification confirms content. Hard-link aliases and overlapping roots do not count as extra physical copies. Changed files and detected Windows/Mac cloud placeholders are held before hashing. No file removal is performed. Real-world cloud-enabled fixture validation remains pending; synthetic tests exercise both single-track/multiple-file and multiple-record/single-file cases.

## Quick export: an offline metadata explorer

Choose **Quick export**, select the loaded XML/ZIP workspace or a saved source snapshot, and generate a standalone HTML file plus a minisite ZIP. Double-click the HTML file, or extract the complete ZIP and open `index.html`. The application can be closed; neither output needs a server, internet connection or installed dependencies.

Browse genre, year, artist, album, BPM range, personal rating, duration, format and playlist pages. Search and combine numeric filters, drill into category tables, sort and paginate, inspect individual metadata, switch themes and save filtered tables as CSV. Unknown tags remain visible. Playlists can overlap, so playlist totals are not additive.

The export freezes captured source metadata. Staged merges and reference edits are not applied. It contains no audio, artwork, waveforms, cue timestamps, native database or cloud credentials. File paths are excluded unless explicitly selected. This read-only export does not require backup acknowledgement and is not a native backup. Older analyzer reports need a fresh capture to gain a metadata snapshot.

The optional MusicBrainz proof of concept sends selected metadata queries only after the user starts a confirmed pilot. Community evidence stays in the local working database. See [the ratings feasibility study](docs/COMMUNITY-RATINGS.md) and [the library-analysis roadmap](docs/LIBRARY-ROADMAP.md).

## Workspace locations

- Linux source: `.data/` beside the application.
- Windows: `%LOCALAPPDATA%/LibraryWorkbench`.
- macOS: `~/Library/Application Support/LibraryWorkbench`.

Set `LIBRARY_WORKBENCH_DATA_DIR` to use a different local workspace. The optional `inputs/` folder accepts any ZIP/XML filenames. Import sessions, private analyzer snapshots and exports are separated. Export folders contain `edited-collection.xml`, `edited-library.zip`, `report.json` and an export manifest as applicable. Input files, databases, music, decisions and generated archives are excluded from source control and release source allowlists.

A private precomputed example can be configured in `.data/example.json` or through `LIBRARY_WORKBENCH_EXAMPLE`. No personal library or example database is distributed.

## Development and packaging

Run `python -m unittest discover -v` after installing `requirements.txt`. The suite covers keeper/cue rules, raw ZIP64 copying, media matching, read-only encrypted/WAL snapshots, source mutation checks, paired-export isolation, backup acknowledgement and platform discovery. CI also checks desktop HTTP startup, Unicode paths and source preservation using synthetic fixtures. No personal library data is uploaded to CI.

Windows assembly: `python packaging/build_windows.py` on Linux with MinGW. The archive contains official embedded CPython and matching Windows wheels, checked against publisher/package digests. A Windows CI job launches the actual packaged executable, runs the analyzer and records validation in the artifact.

Mac assembly: install `requirements-build.txt`, then run `python packaging/build_macos.py` on a native Mac. Separate Intel and Apple Silicon jobs package and smoke-test the self-contained app. Linux source archive: `python packaging/build_source.py`.

See [the Windows restore procedure](docs/RESTORE-TEST.md) before testing transformed backups. The project uses the existing [MIT license](LICENSE); bundled dependency licenses remain separate.

## Releases and security

Every pull request and push to `main` automatically tests and builds Windows x64, Mac Intel, Mac Apple Silicon and Linux source archives. Download development packages from the run's **Artifacts** section; the final check summary lists the correct artifact for each platform. Development artifacts are retained for 14 days.

For a release, use **Actions → Create release → Run workflow** on `main`, enter a version and choose draft or publication. The workflow builds and validates all four archives, adds the matching changelog entry and installation guidance, then creates the version tag automatically. No local push/tag or personal token is needed. Pushing a `v<version>` tag for a commit already merged into `main` also builds and publishes automatically, as in entropy-service. Plain versions become the latest stable release; alpha/beta/rc versions remain previews. Release downloads remain available separately from temporary CI artifacts. See [release instructions](docs/RELEASING.md).

[SECURITY.md](SECURITY.md) explains private reporting and local trust boundaries. Weekly dependency checks, pinned actions and Dependabot configuration complement the repository's existing default CodeQL setup. [Repository security guidance](docs/REPOSITORY-SECURITY.md) compares DNSProxy/entropy-service and provides importable branch/tag ruleset templates. Merge-policy changes remain a maintainer choice.

# rekordbox Migration Helper · Library Workbench

A local browser application for understanding a rekordbox library, reviewing duplicates and preparing edited copies. Linux is the primary development platform. Windows and macOS portable previews are built and exercised by CI.

**Keep a fresh, untouched backup created by rekordbox Backup Library outside this workspace before generating transformed files. Preserve the audio separately when it is excluded from the backup. Native ZIP restoration in rekordbox remains experimental.**

## Start

On Linux, use Python 3.13 or newer and run `./start.sh` from this directory. The first launch installs requirements into a local virtual environment. The application opens your browser and binds only to loopback. Use **Stop local application** in its footer when finished.

Windows users extract the complete portable ZIP and double-click **Library Workbench.exe**. Python and dependencies are included. Mac users choose the Apple Silicon (`arm64`) or Intel (`x86_64`) preview, extract it and open **Library Workbench.app**. Mac previews are ad-hoc signed, not Developer ID signed or notarized; macOS may restrict opening them. Source checkout remains available for developers.

## Two workflows

1. **Source analyzer** reads a source data folder through a private database/journal snapshot. It reports integrity, schema compatibility, track/cue/playlist counters, reference issues and selected-folder footprint. It does not modify the source. Close rekordbox and pause Cloud Library Sync during capture. No XML or ZIP input is required for this mode.
2. **Import XML + ZIP** loads a consecutive Backup Library ZIP and collection XML export. Choose files to copy them into a workspace, or use existing files by full path without another large copy. Compare duplicate groups, cues, ratings and file references, then generate XML and native ZIP together from one frozen decision snapshot.

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

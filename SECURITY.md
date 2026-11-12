# Security policy

Library Workbench is a local library-preparation utility. The maintained preview line receives security fixes through reviewed updates; use the newest published preview and retain your original backups. Older snapshots are not maintained indefinitely. Native rekordbox restoration compatibility is still experimental.

## Supported versions

| Version | Security maintenance |
| --- | --- |
| 0.4.x preview / current source | Maintained preview line |
| 0.3.x and earlier | Upgrade to the maintained preview for dependency fixes |

## Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/fantuz/rekordbox-migration-helper/security/advisories/new). Private reporting is enabled for this repository. Do not post vulnerabilities, tokens, personal library databases, cloud account details or music files in public issues.

Include the affected version or commit, operating system, a clear description, expected impact and minimal reproduction steps. Use a small synthetic XML/ZIP example where possible. Describe any required real-world fixture before sharing it. This is a volunteer project; no guaranteed response or remediation deadline is promised.

Ordinary feature requests and non-sensitive bugs can use public issues. If you are unsure whether a report is sensitive, use the private channel first.

## Scope and trust boundaries

- The local server binds to loopback and uses an action token for state-changing requests. Do not expose it through a reverse proxy or public network.
- Imported databases and XML/ZIP files are untrusted inputs. The source analyzer queries a private snapshot. Transformations write new copies, never the running rekordbox library.
- Offline HTML contains the selected metadata and, only when explicitly requested, recorded paths. It includes no credentials or native database. Check what you share; an HTML explorer is not encrypted.
- The explorer uses embedded/local assets and blocks network connections. Exported tag values are serialized as data and rendered as text.
- The experimental MusicBrainz pilot is disabled by default. Enabling it and confirming a sample sends selected public artist/title or ISRC queries to MusicBrainz. It sends no audio, file paths or credentials. Community scores remain separate from personal stars. Set `LIBRARY_WORKBENCH_MUSICBRAINZ=0` to force retrieval off; existing reports remain usable.
- Library lab snapshots, edit history and provider cache live in a separate local SQLite sidecar. Editing starts locked after application startup. Unlocked field changes affect generated copies only; they never write the source database or audio tags.
- Source control, CI and release packaging exclude personal library inputs, music, snapshots and review state. Public CI uses synthetic fixtures.

## Build and release security

Project GitHub Actions are pinned by commit. Dependency audits, GitHub's existing default CodeQL setup and review checks supplement the regression and native package tests; they do not establish that software has no vulnerabilities. Build jobs use read permissions; only the final release job receives repository content write access. There is no `pull_request_target` workflow or automatic merge.

Manual releases validate the default-branch commit and every package before creating a release. Existing version tags and assets are never intentionally overwritten. SHA256SUMS helps detect download corruption; it is not a code-signing identity. Windows previews are not Authenticode signed; Mac previews are ad-hoc signed and not notarized.

See [repository protection guidance](docs/REPOSITORY-SECURITY.md) for recommended rulesets and settings.

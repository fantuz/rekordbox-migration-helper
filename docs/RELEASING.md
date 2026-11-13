# Builds and releases from GitHub

## Automatic development builds

Every pull request and push to `main` runs source tests on Linux, Windows, Mac Intel and Mac Apple Silicon, then builds and exercises the portable applications. Open the run under **Actions → Check and package** and scroll to **Artifacts**, or follow the download link in the final check summary:

Source checks and native builds run independently; a queued platform does not prevent other platform artifacts from being built. The final required check and release workflow still require every source, browser and native package check to pass, then verify the complete five-archive set. Current Mac runners are macOS 15 for Intel and macOS 26 for Apple Silicon; runner versions are recorded in build manifests. Tested runner versions are not a claim that every older operating system has been validated.

| Download | Artifact |
| --- | --- |
| Windows x64 portable | `windows-x64-portable` |
| Mac Apple Silicon | `macos-arm64-portable` |
| Mac Intel | `macos-x86_64-portable` |
| Linux x86-64 portable | `linux-x86_64-portable` |
| Linux source | `linux-source` |

GitHub wraps each artifact in an outer ZIP; extract it to find the actual application archive. The intermediate `windows-portable-assembly` has not passed the native Windows executable check; use `windows-x64-portable`. Development artifacts expire after 14 days. GitHub release assets are retained separately. **Check and package → Run workflow** also builds a selected ref without publishing.

Archive filenames contain the version and architecture without a `-preview` suffix, for example `Library-Workbench-0.4.6-windows-x64.zip` and `Library-Workbench-0.4.6-macos-arm64.zip`. The release channel is separate: alpha/beta/rc versions still publish as prereleases.

The README download buttons always open the latest stable release's **Downloads** table. That table is generated for each release with links to its exact five versioned archives, so no README version edit is needed. Existing published releases keep their original names.

## Release without a shell

Open **Actions → Create release → Run workflow**. Select **main**, enter a version such as `0.4.5` or `0.4.6-rc.1` (blank uses `VERSION`), and choose:

- **Publish when complete:** leave unchecked for a draft, or check to publish after every check passes.
- **Preview / prerelease:** check to publish an optional preview. Plain versions publish as stable/latest by default. Versions containing `-alpha`, `-beta` or `-rc` are always prereleases.

Click **Run workflow**. The workflow audits dependencies, builds the selected default-branch commit, runs the complete source checks and exercises the actual Windows/Mac/Linux packaged applications. It attaches five archives, `SHA256SUMS` and `COMMIT-LOG.txt`. The download table links directly to all seven files and gives a short start instruction for each platform. The matching section of [CHANGELOG.md](../CHANGELOG.md), installation instructions, compatibility limits and source commit populate the release notes. A collapsed list links every reachable commit, including merged branches, oldest first; the text attachment preserves author, date and complete messages. A comparison link shows changes since the previous stable release. A complete history checkout is required, so a shallow checkout stops publication instead of producing a partial log. No local tag, push, personal access token or signing secret is needed.

For draft mode, open **Releases**, inspect the completed draft and click **Publish release**. The workflow summary links to it. Use this Actions form when creating a new release from the website; a hand-written release entry does not run the packaging workflow.

The entered version is embedded in package manifests and the source archive's `VERSION`; the form does not change `VERSION` on `main`. Update `VERSION` and the changelog in a reviewed PR for the next development baseline. Existing tags or releases are rejected before rebuilding, and never overwritten. A draft is used internally until all uploads finish, so incomplete uploads are not advertised as a complete public release. A failed publication can leave a draft/tag for inspection; use a new version or clean up that failed draft through GitHub before retrying.

## Automatic version-tag releases

Like entropy-service, pushing a canonical tag such as `v0.4.6` or `v0.4.6-rc.1` automatically runs the complete release chain and publishes after it passes. Plain versions become the latest stable release; `-alpha`, `-beta` and `-rc` versions remain previews. Both lightweight and annotated tags work. The tag determines the package version and must resolve to the checked commit, already merged into the default branch. An unrelated branch, moved/deleted tag, duplicate release or API validation failure stops publication.

Tag builds reuse the triggering tag; web releases create a new tag atomically after validation. A tag created by the web workflow's `GITHUB_TOKEN` does not trigger a second build: that same run has already built and validated the packages. See [GitHub token event behavior](https://docs.github.com/en/actions/concepts/security/github_token).

Development runs can cancel superseded development work; a newer push does not cancel release packaging. Different version releases have separate concurrency groups. The checked source commit is fixed for the run, even if `main` advances. Packages are collected only from that run and checked for matching versions, source commits, native runtime evidence and source/archive hashes.

Do not copy entropy-service's tag-creation restrictions unchanged: those can block `GITHUB_TOKEN` from creating a web release tag. The recommended [tag ruleset](version-tags-ruleset.json) protects existing tags against deletion/rewriting while allowing new tags.

No release is published by a pull request. Source and package tests use synthetic fixtures; private libraries, audio and working databases are excluded. Native rekordbox Restore Library compatibility still requires a real-instance check.

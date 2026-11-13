# Builds and releases from GitHub

## Automatic development builds

Every pull request and push to `main` runs source tests on Linux, Windows, Mac Intel and Mac Apple Silicon, then builds and exercises the portable applications. Open the run under **Actions → Check and package** and scroll to **Artifacts**, or follow the download link in the final check summary:

| Download | Artifact |
| --- | --- |
| Windows x64 portable | `windows-x64-preview` |
| Mac Apple Silicon | `macos-preview-macos-15` |
| Mac Intel | `macos-preview-macos-15-intel` |
| Linux source | `linux-source` |

GitHub wraps each artifact in an outer ZIP; extract it to find the actual application archive. The intermediate `windows-portable-assembly` has not passed the native Windows executable check; use `windows-x64-preview`. Development artifacts expire after 14 days. GitHub release assets are retained separately. **Check and package → Run workflow** also builds a selected ref without publishing.

## Release without a shell

Open **Actions → Create release → Run workflow**. Select **main**, enter a version such as `0.4.5` or `0.4.6-rc.1` (blank uses `VERSION`), and choose:

- **Publish when complete:** leave unchecked for a draft, or check to publish after every check passes.
- **Preview / prerelease:** check to publish an optional preview. Plain versions publish as stable/latest by default. Versions containing `-alpha`, `-beta` or `-rc` are always prereleases.

Click **Run workflow**. The workflow audits dependencies, builds the selected default-branch commit, runs the complete source checks and exercises the actual Windows/Mac packaged applications. It attaches four archives plus `SHA256SUMS`. The matching section of [CHANGELOG.md](../CHANGELOG.md), installation instructions, compatibility limits and source commit populate the release notes. No local tag, push, personal access token or signing secret is needed.

For draft mode, open **Releases**, inspect the completed draft and click **Publish release**. The workflow summary links to it. Use this Actions form when creating a new release from the website; a hand-written release entry does not run the packaging workflow.

The entered version is embedded in package manifests and the source archive's `VERSION`; the form does not change `VERSION` on `main`. Update `VERSION` and the changelog in a reviewed PR for the next development baseline. Existing tags or releases are rejected before rebuilding, and never overwritten. A draft is used internally until all uploads finish, so incomplete uploads are not advertised as a complete public release. A failed publication can leave a draft/tag for inspection; use a new version or clean up that failed draft through GitHub before retrying.

## Automatic version-tag releases

Like entropy-service, pushing a canonical tag such as `v0.4.6` or `v0.4.6-rc.1` automatically runs the complete release chain and publishes after it passes. Plain versions become the latest stable release; `-alpha`, `-beta` and `-rc` versions remain previews. Both lightweight and annotated tags work. The tag determines the package version and must resolve to the checked commit, already merged into the default branch. An unrelated branch, moved/deleted tag, duplicate release or API validation failure stops publication.

Tag builds reuse the triggering tag; web releases create a new tag atomically after validation. A tag created by the web workflow's `GITHUB_TOKEN` does not trigger a second build: that same run has already built and validated the packages. See [GitHub token event behavior](https://docs.github.com/en/actions/concepts/security/github_token).

Development runs can cancel superseded development work; a newer push does not cancel release packaging. Different version releases have separate concurrency groups. The checked source commit is fixed for the run, even if `main` advances. Packages are collected only from that run and checked for matching versions, source commits, native runtime evidence and source/archive hashes.

Do not copy entropy-service's tag-creation restrictions unchanged: those can block `GITHUB_TOKEN` from creating a web release tag. The recommended [tag ruleset](version-tags-ruleset.json) protects existing tags against deletion/rewriting while allowing new tags.

No release is published by a pull request. Source and package tests use synthetic fixtures; private libraries, audio and working databases are excluded. Native rekordbox Restore Library compatibility still requires a real-instance check.

# Builds and releases from GitHub

## Automatic development builds

Every pull request and push to `main` runs source tests and exercises the portable applications on Linux, Windows, Mac Intel and Mac Apple Silicon. Open the run under **Actions → Check and package** and scroll to **Artifacts**, or follow the download link in the final check summary.

Platforms run independently. On macOS, each architecture uses one runner for the native build, packaged startup, source suite and source startup check. The source diagnostics and validated portable app remain separate downloads. Each browser worker installs Playwright once and runs the language suite alongside its connector and workflow checks, with separate logs in the language validation artifact. The final required check verifies the complete five-archive set after every source, browser and native package check passes. Current Mac runners are macOS 15 for Intel and macOS 26 for Apple Silicon. Build manifests record the tested runner versions.

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

## Release from a reviewed version bump

Treat each release as a reviewed source milestone, not merely a version override.

1. Confirm the previous stable tag, the intended `main` commit, and that the target release and tag do not already exist. Merge feature PRs before starting release preparation.
2. Open a separate **release-preparation PR**. Set the root `VERSION` file to the target version. Move completed entries under **Unreleased** into a dated `## <version> — YYYY-MM-DD` section in `CHANGELOG.md`; attribute earlier released features to their historical release instead of duplicating them. Preserve `Unreleased` for new development.
3. Use GitHub Actions to validate the PR: source checks across Linux/Windows/macOS, browser tests across Chromium/Firefox/WebKit, native packaging, aggregate checks and security. Merge only after checks pass.
4. After merging, **Release merged version** automatically follows the successful main-push **Check and package** run. It requires an increasing `VERSION` change against the merge's first parent, a dated non-empty changelog section, all validated artifacts, and successful **Security checks** and CodeQL analysis for the same source commit.
5. Keep `main` at that commit until publication finishes. The trigger starts the existing **Create release** workflow with the version and expected source SHA, publishes stable versions as latest, and keeps alpha/beta/rc versions as prereleases. The workflow reuses the exact validated main build and repeats the dependency audit and archive verification before creating the tag and release.
6. Verify that `v<version>` points to the validated commit, that the release is the latest stable, and that all five archives, `SHA256SUMS`, `COMMIT-LOG.txt` and release notes are present. Do not consider a release published merely because a development run passed.

The release workflow technically supports an explicit version override, but use it only for deliberate exceptional releases—not as a substitute for updating `VERSION` on `main`. Do not create hand-written releases, overwrite existing tags or bypass the release workflow.

## Automatic trigger and recovery

The trigger runs only after a successful **push to main** package build in this repository. Pull requests, forks, manual development builds, failed/cancelled builds, ordinary commits without a version change, and initial commits do not publish. It uses the repository's short-lived `GITHUB_TOKEN` with `actions: write` only in the dispatcher job; no personal access token or additional secret is needed. GitHub permits [workflow dispatches made with GITHUB_TOKEN](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow) to start the release workflow.

The source SHA is checked both before dispatch and by the receiving workflow. If `main` advances, automatic publication stops instead of releasing a different commit. Automatic publication requires already validated artifacts and cannot silently fall back to an unvalidated build. The dispatcher waits up to about ten minutes for the same commit's security and CodeQL runs; failed or missing validation stops publication. The current native CodeQL setup is identified by its `dynamic/github-code-scanning/codeql` workflow path; update the trigger if that setup is replaced.

Existing releases or tags are never overwritten. Serialized trigger runs and an active-release check avoid duplicate dispatches; tag creation remains atomic if a manual release races automation. Rerun a failed trigger after transient/API errors or delayed security checks are resolved. If the branch moved or artifacts expired, inspect the new main commit and use the manual workflow below. A failed publication that already created a tag/draft still requires deliberate recovery; it is not silently retried or replaced.

## Manual release and recovery without a shell

Open **Actions → Create release → Run workflow**. Select **main**, enter a version such as `0.4.5` or `0.4.6-rc.1` (blank uses `VERSION`), and choose (leave **Expected source SHA** blank and **Require already validated packages** unchecked for the usual manual path):

- **Publish when complete:** leave unchecked for a draft, or check to publish after every check passes.
- **Preview / prerelease:** check to publish an optional preview. Plain versions publish as stable/latest by default. Versions containing `-alpha`, `-beta` or `-rc` are always prereleases.

Click **Run workflow**. The workflow audits dependencies and looks for a successful **Check and package** main-push run for the exact source commit and package version. When every required artifact is still available, it reuses that already validated set. Otherwise it builds the selected default-branch commit, runs the complete source checks and exercises the actual Windows/Mac/Linux packaged applications. It attaches five archives, `SHA256SUMS` and `COMMIT-LOG.txt`. The download table links directly to all seven files and gives a short start instruction for each platform. The matching section of [CHANGELOG.md](../CHANGELOG.md), installation instructions, compatibility limits and source commit populate the release notes. A collapsed list links every reachable commit, including merged branches, oldest first; the text attachment preserves author, date and complete messages. A comparison link shows changes since the previous stable release. A complete history checkout is required, so a shallow checkout stops publication instead of producing a partial log. No local tag, push, personal access token or signing secret is needed.

For draft mode, open **Releases**, inspect the completed draft and click **Publish release**. The workflow summary links to it. Use this Actions form when creating a new release from the website; a hand-written release entry does not run the packaging workflow.

The entered version is embedded in package manifests and the source archive's `VERSION`; the form does not change `VERSION` on `main`. Update `VERSION` and the changelog in a reviewed PR for the next development baseline. Existing tags or releases are rejected before rebuilding, and never overwritten. A draft is used internally until all uploads finish, so incomplete uploads are not advertised as a complete public release. A failed publication can leave a draft/tag for inspection; use a new version or clean up that failed draft through GitHub before retrying.

## Automatic version-tag releases

Like entropy-service, pushing a canonical tag such as `v0.4.6` or `v0.4.6-rc.1` automatically runs the complete release chain and publishes after it passes. Plain versions become the latest stable release; `-alpha`, `-beta` and `-rc` versions remain previews. Both lightweight and annotated tags work. The tag determines the package version and must resolve to the checked commit, already merged into the default branch. An unrelated branch, moved/deleted tag, duplicate release or API validation failure stops publication.

Tag builds reuse the triggering tag; web releases create a new tag atomically after validation. A tag created by the web workflow's `GITHUB_TOKEN` does not trigger a second build: that same run has already built and validated the packages. See [GitHub token event behavior](https://docs.github.com/en/actions/concepts/security/github_token).

Development runs can cancel superseded development work; a newer push does not cancel release packaging. Different version releases have separate concurrency groups. The checked source commit is fixed for the run, even if `main` advances. Packages come from the current build or one fully successful main-push run with the exact source commit and matching `VERSION`. Pull-request builds, forks, other branches, incomplete runs, expired artifacts and version overrides cannot supply reused release assets. Publication always repeats the checks for matching versions, source commits, native runtime evidence and source/archive hashes. Reuse never skips the fresh dependency audit. A missing artifact during download stops publication; rerun after its expiry to select a fresh build.

Do not copy entropy-service's tag-creation restrictions unchanged: those can block `GITHUB_TOKEN` from creating a web release tag. The recommended [tag ruleset](version-tags-ruleset.json) protects existing tags against deletion/rewriting while allowing new tags.

No release is published by a pull request. Source and package tests use synthetic fixtures; private libraries, audio and working databases are excluded. Native rekordbox Restore Library compatibility still requires a real-instance check.

## Pinned Linux runtime cache

Linux native builds can restore the shared CPython runtime before assembling the application. The cache key includes the build script and the actual inputs used in the pinned manylinux image, including the Python source checksum, compiler, architecture and installed development-package versions. A change to a build dependency therefore selects a new cache entry. Each restore checks the archive digest and build context, then starts the interpreter and imports its compression, TLS, SQLite and shared-library modules. A failed check triggers a build from the pinned source. Only successful trusted `main` builds can save runtime checkpoints. Pull requests can read them.

The job installs application dependencies after runtime validation and checks the Linux application inside the container and on the host. Release publication reuses the five packages from the validated `main` build for the exact release commit and version.

Performance measurements and duplicate-query cache rules are documented in [PERFORMANCE.md](PERFORMANCE.md).

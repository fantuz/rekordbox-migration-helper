# Release from the GitHub website

After the release workflow is merged into `main`, open **Actions → Create release → Run workflow**. Select **main**, enter a version such as `0.4.0` or `0.4.1-rc.1` (blank uses `VERSION`), and choose:

- **Publish when complete:** leave unchecked to prepare a draft, or check it to publish after every check passes.
- **Preview / prerelease:** keep checked while native rekordbox restoration remains experimental.

Click **Run workflow**. No local tag, push, personal access token or signing secret is needed. The workflow builds the selected default-branch commit, runs source checks on Linux/Windows/both Mac architectures, exercises the actual packaged applications and audits dependencies. It attaches the Windows x64, Mac Intel, Mac Apple Silicon and Linux source archives plus `SHA256SUMS` to the release.

For draft mode, open **Releases**, inspect the completed draft and click **Publish release** when ready. The workflow's summary links directly to the release.

The release version is embedded in the package manifests and source archive's `VERSION`; entering it in the web form does not push a version-changing commit to `main`. Existing versions are rejected. Publishing uses a draft internally until all uploads finish, so a failed upload is not presented as a complete public release. A failed run can leave a draft/tag for maintainer inspection; use a new version or clean up that failed draft through GitHub before retrying the same version.

The checked source commit is fixed for the whole run, even if `main` advances. Release validation compares archive digests, package versions, native runtime evidence, source commits and application-source hashes across all four archives. It never picks an artifact from an unrelated prior run.

The final job creates the tag atomically at that checked commit and refuses an existing ref, including one created while the packages were building. The release then requires that tag to exist. It does not silently attach new packages to somebody else's version tag.

Do not copy entropy-service's tag-creation restrictions unchanged: those can block `GITHUB_TOKEN` from creating the new release tag. The recommended tag rules protect existing tags against deletion/rewriting while allowing the web workflow to create a new version.

Workflow configuration and dry validation are tested in PR CI. A real release is not published as a side effect of a pull request. The first default-branch manual run is the final end-to-end publication check.

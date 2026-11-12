# Repository protection guidance

The comparison below uses the repository settings read on 12 November 2026. Workbench had no rulesets or classic `main` protection at that time. Private vulnerability reporting has now been enabled; Dependabot alerts were already enabled. The proposals below are templates for review, not silently applied merge restrictions.

## Comparison with the other projects

| Repository | Observed protection | Lesson for this project |
| --- | --- | --- |
| DNSProxy | Default-branch deletion/force-push prevention and a strict required PR check, without bypass actors | Use a stable aggregate check that always reports a result |
| entropy-service | PR review, code-owner review, resolved conversations, linear history, packaged Windows check, CodeQL/code-quality gates and an administrator bypass | Stronger collaboration baseline; requiring somebody else's approval can block a solo maintainer |
| entropy-service version tags | Creation/update/deletion restrictions with administrator bypass | Do not copy creation restrictions without granting the release actor a suitable bypass |

## Recommended first rulesets

Download [main-ruleset.json](main-ruleset.json) and [version-tags-ruleset.json](version-tags-ruleset.json), then use **Settings → Rules → Rulesets → Import a ruleset**. Confirm the check name matches a successful run before activating it. These files contain the intended settings, not repository IDs or credentials.

The main template requires a PR, resolved review conversations and the aggregate **Workbench PR checks** result, and prevents branch deletion/force pushes. It requires zero outside approvals for this solo-maintainer project. Raise that to one and enable code-owner review when a second active maintainer exists. Administrator bypass is limited to PRs for recovery; protect the owner account with MFA. Add a linear-history rule only after selecting squash/rebase merging to match it.

The tag template prevents deletion and force updates of `v*` tags but allows new tag creation. Existing release versions should remain immutable. An owner can use the documented administrator bypass for an exceptional withdrawal; explain the change publicly when it affects a published release.

## Other settings worth checking

| Setting | Recommended choice / status |
| --- | --- |
| Private vulnerability reporting | Enabled; use the private advisory link in SECURITY.md |
| Dependency graph and Dependabot alerts | Keep enabled; alerts were already enabled |
| Dependabot security updates | Enable in Settings → Advanced Security; observed disabled before this change |
| CodeQL | Existing default setup is enabled for Python, JavaScript/TypeScript and Actions; retain it. Do not add an advanced CodeQL workflow concurrently. A CodeQL high-severity ruleset gate can follow successful scans. |
| Actions token permissions | Keep the repository default read-only; individual jobs request only the access they need |
| Actions approval | Require approval for first-time external contributors; never run untrusted PR code with release credentials |
| Action SHA pinning | All project actions are pinned; repository-wide SHA pinning enforcement can also be enabled after checking all workflows |
| Secret scanning / push protection | Enable if available for the repository; do not upload personal libraries as test fixtures |
| Releases | Prefer prereleases until native restore validation; add signing/notarization later, with protected signing credentials |
| Bundled native runtimes | Review CPython, SQLCipher/SQLite and libxml2 advisories when updating packages; a Python dependency audit is not a complete audit of embedded native code |
| Owner access | MFA/passkeys, minimal collaborators and periodic token/app review |

Badges are navigation and visibility aids, not a security certification. Neither a policy file nor a green scanner badge guarantees library restoration or absence of vulnerabilities.

References: [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets), [private reporting](https://docs.github.com/en/code-security/security-advisories/working-with-repository-security-advisories/configuring-private-vulnerability-reporting-for-a-repository), [Actions hardening](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions).

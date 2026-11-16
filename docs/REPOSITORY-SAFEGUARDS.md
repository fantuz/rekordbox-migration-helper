# Repository safeguards

Verified on 2026-11-16: the active `branch-level-rule` ruleset targets the default branch and has no bypass actors. [View the live ruleset](https://github.com/fantuz/rekordbox-migration-helper/rules/27173327). Settings may change independently of this document; compare the live configuration before importing a template.

## Current main-branch protection

- Pull requests and resolved review conversations are required. Zero approving reviews supports the solo-maintainer workflow; require one when another reviewer is available.
- Branches must be up to date. Required GitHub Actions checks are **Workbench PR checks**, **Python dependency audit**, and **Review dependency changes** (integration 15368).
- Force pushes and branch deletion are blocked. No actor can bypass these rules.
- Native **CodeQL code-scanning protection** blocks high/critical security findings and error-level alerts. This is a findings gate; successful analysis/upload jobs alone are not a substitute. A duplicate status-check rule named CodeQL is unnecessary when this native rule is configured.
- **Code Quality** is separately required at error severity. Its rule is enabled, but a corresponding analysis result was not verified during the review. Confirm the feature is configured and produces its result on the next PR. Do not weaken another check to work around a missing quality result.

[`main-ruleset.json`](main-ruleset.json) mirrors that verified configuration, including the native scanning/quality rules and empty bypass list. Import through **Settings → Rules → Rulesets** only after reviewing enabled tools and current rules; prefer updating the existing rule over creating overlapping duplicates.

## Release tags

No version-tag ruleset was returned by the repository rules API during this review. [`version-tags-ruleset.json`](version-tags-ruleset.json) remains an optional setup template, not evidence of an enabled policy. It protects `refs/tags/v*` against deletion and updates while permitting new release tags. Review its administrator bypass before importing; remove it unless a deliberate recovery exception is needed. Test that the release workflow can still create a new tag.

## Verify enforcement

On the next disposable or ordinary PR, verify that a failing required check blocks merging, CodeQL findings are evaluated, Code Quality completes, and passing checks permit the intended maintainer workflow. The latest completed PR predates activation of the revised ruleset, so it does not demonstrate the new gates end to end.

The aggregate **Workbench PR checks** gate already requires source, browser and native packaging checks. Keep security/dependency checks enabled for PRs and review workflow changes like application changes.

GitHub documentation: [Available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets) and [Code Quality](https://docs.github.com/en/code-security/concepts/code-quality/code-quality).

# Repository safeguards: quick setup

This is setup guidance, not an enabled repository policy. On 2026-11-16 the existing branch ruleset was disabled, had no branch inclusion, and required no status checks. Review current settings before changing them.

1. Open **Settings → Rules → Rulesets**, edit the existing branch ruleset (or create a branch ruleset), and target the default branch `main`.
2. Require pull requests and resolution of review conversations. For a solo maintainer, zero required approvals still permits the PR workflow; choose one approval when another reviewer is available.
3. Require the actual check names from a completed PR: **Workbench PR checks**, **Python dependency audit**, and **Review dependency changes**, plus **CodeQL** from **GitHub Advanced Security**. Select the matching check provider where offered. The successful CodeQL analysis/upload jobs are different from the security findings check. Do not enter workflow filenames in place of check names.
4. Require the branch to be up to date before merging. Block force pushes and branch deletion. Keep any bypass permission narrow and deliberate.
5. Check the existing CodeQL/code-quality requirements against tools actually enabled for this repository. Configure those checks, or remove unavailable requirements before activating the ruleset; otherwise normal PRs may be blocked indefinitely.
6. Set enforcement to **Active**, save, then verify on a disposable PR that a failing required check blocks merging and that passing checks allow the intended maintainer workflow.

Keep security checks on pull requests and dependency updates enabled. Workflow edits should receive the same review as application changes. The aggregate **Workbench PR checks** gate already checks the source, browser and packaging jobs, so it remains stable when individual matrix names change.

GitHub documentation: [Creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository) and [Available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets).

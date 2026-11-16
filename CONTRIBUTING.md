# Contributing

Use a focused branch and pull request. GitHub runs source/property tests, native packaging, dependency checks and real-browser language checks. A release builds only after its validation gates pass. Plain version tags publish stable/latest releases; alpha/beta/rc versions remain previews.

For local development use Python 3.13 or newer, `requirements.txt` and `requirements-test.txt`; run `python -m unittest discover -v`. Browser checks additionally use `requirements-browser.txt` and `python -m playwright install chromium`, then `python packaging/check_browser_languages.py --browser chromium --output ci-output/languages`. Native packaging requires its target platform or the documented Windows cross-build tooling.

Use synthetic fixtures. Do not commit personal libraries, database exports, audio, cloud credentials or working data. Describe reproduction steps with a small generated example when possible. Report vulnerabilities through [SECURITY.md](SECURITY.md).

For real-server workflow integrity checks, run `python packaging/check_workflow_integrity.py --output ci-output/workflow-integrity` after installing the browser requirements and Chromium. This test uses disposable synthetic snapshots and real HTTP/SQLite operations: save an edit, reject a competing stale tab, isolate edits by snapshot scope, restart the server, download and verify public exports, and reset the edit across another restart. It verifies captured snapshots remain unchanged. The output includes a JSON report, browser trace and downloaded artifacts; failures also capture screenshots. CI runs this check in its Chromium job. In environments where `/tmp` and the checkout cannot exchange files using atomic rename, create `.data/tmp` and set `TMPDIR` to its absolute path before running browser checks.

Translations belong in the shared [interface catalogue](static/locales.json). Follow the [localization guide](docs/LOCALIZATION.md), preserve placeholders and technical identifiers, and check both live and offline interfaces. Native-speaker corrections are welcome. Full project documentation and legal policies remain English unless a separately reviewed translation is added.

For input-format changes, include a regression that exercises actual parsing/writing and confirms source preservation. Document unsupported cases rather than silently replacing characters or guessing a format. Read [Unicode/input checks](docs/UNICODE-INPUTS.md) and [compatibility](docs/COMPATIBILITY.md).

Contributions are provided under the project's existing MIT license. Third-party terms remain separate.

## Keep the feature inventory current

The README **Feature inventory** is the reusable factual summary of the software. In the same PR as a user-visible addition, removal or behavior change, update its relevant bullets and detailed guide. State input requirements and draft compatibility limits. Do not describe a roadmap item as implemented. Update screenshots when the main workflow changes visibly, using synthetic data and the GitHub browser checks; never publish personal libraries or audio.

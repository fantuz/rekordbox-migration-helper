import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import urllib.error

with patch.object(sys, 'path', [str(Path(__file__).parent / 'packaging'), *sys.path]):
    import auto_release
    from prepare_release import validate_expected_source
    import select_release_build


class AutomaticReleaseTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.parent = 'b' * 40
        self.repository = 'example/workbench'
        self.run = dict(id=10, head_sha=self.sha, head_branch='main', event='push',
                        head_repository={'full_name': self.repository}, status='completed',
                        conclusion='success', path='.github/workflows/check-and-package.yml')
        self.branch_sha = self.sha
        self.parents = [{'sha': self.parent}]
        self.version = '1.1.3'
        self.previous = '1.1.2'
        self.notes = '# Changelog\n\n## Unreleased\n\n## 1.1.3 — 2026-11-16\n\nRepair import retries.\n'
        self.artifacts = [{'name': name, 'expired': False} for name in auto_release.REQUIRED_ARTIFACTS]
        self.runs = [dict(self.run, id=11, path='.github/workflows/security.yml'),
                     dict(self.run, id=12, path='dynamic/github-code-scanning/codeql', event='dynamic')]
        self.existing = set()

    def read(self, path):
        if path == 'actions/runs/10':
            return copy.deepcopy(self.run)
        if path == 'branches/main':
            return {'commit': {'sha': self.branch_sha}}
        if path == 'commits/' + self.sha:
            return {'parents': self.parents}
        if path.startswith('contents/'):
            parsed = urlsplit(path)
            ref = parse_qs(parsed.query)['ref'][0]
            if parsed.path == 'contents/VERSION':
                value = self.version if ref == self.sha else self.previous
            else:
                self.assertEqual(parsed.path, 'contents/CHANGELOG.md')
                self.assertEqual(ref, self.sha)
                value = self.notes
            return {'encoding': 'base64', 'content': base64.b64encode(value.encode()).decode()}
        if path.startswith(('releases/tags/', 'git/ref/tags/')):
            if path in self.existing:
                return {}
            raise urllib.error.HTTPError(path, 404, 'Not found', {}, None)
        if path == 'actions/runs/10/artifacts?per_page=100':
            return {'artifacts': self.artifacts}
        if path.startswith('actions/runs?'):
            self.assertEqual(parse_qs(urlsplit(path).query)['head_sha'], [self.sha])
            return {'workflow_runs': copy.deepcopy(self.runs)}
        raise AssertionError('Unexpected API path: ' + path)

    def candidate(self):
        return auto_release.automatic_release(self.read, 10, self.repository)

    def test_validated_version_bump_dispatches_existing_workflow_with_source_guard(self):
        payload, _ = self.candidate()
        self.assertEqual(payload, {'ref': 'main', 'inputs': {'release_version': '1.1.3',
                         'publish': True, 'prerelease': False, 'expected_source_commit': self.sha,
                         'require_validated_build': True}})

    def test_preview_versions_remain_prereleases(self):
        self.version = '1.1.3-rc.1'
        self.notes = self.notes.replace('1.1.3', self.version)
        self.assertTrue(self.candidate()[0]['inputs']['prerelease'])

    def test_pr_fork_branch_manual_and_failed_builds_cannot_release(self):
        for update in ({'event': 'pull_request'}, {'event': 'workflow_dispatch'},
                       {'head_repository': {'full_name': 'fork/workbench'}}, {'head_branch': 'feature'},
                       {'path': '.github/workflows/unrelated.yml'}, {'status': 'in_progress'},
                       {'conclusion': 'failure'}, {'conclusion': 'cancelled'}):
            with self.subTest(update=update):
                original = self.run
                self.run = dict(original, **update)
                self.assertIsNone(self.candidate()[0])
                self.run = original

    def test_new_main_commit_prevents_stale_release(self):
        self.branch_sha = 'c' * 40
        self.assertIsNone(self.candidate()[0])

    def test_ordinary_merge_without_version_change_does_not_release(self):
        self.previous = self.version
        self.assertIsNone(self.candidate()[0])

    def test_initial_commit_does_not_automatically_release(self):
        self.parents = []
        self.assertIsNone(self.candidate()[0])

    def test_merge_compares_first_parent_not_feature_branch_version(self):
        self.parents.append({'sha': 'c' * 40})
        self.assertIsNotNone(self.candidate()[0])

    def test_downgrade_and_invalid_versions_fail_closed(self):
        for version in ('1.1.1', '1.1.2-rc.1', 'not-a-version', '1.1.3\nextra'):
            with self.subTest(version=version):
                self.version = version
                with self.assertRaises(ValueError):
                    self.candidate()

    def test_version_order_handles_numeric_components_and_preview_promotion(self):
        order = ['1.1.3-alpha.2', '1.1.3-alpha.10', '1.1.3-beta.1', '1.1.3-rc.1', '1.1.3', '1.1.10', '1.2.0']
        self.assertEqual(sorted(order, key=auto_release.version_key), order)

    def test_missing_empty_or_invalid_date_notes_block_release(self):
        for notes in ('## Unreleased\n\nNew work.', '## 1.1.3 — 2026-11-16\n\n## 1.1.2\nOld work.',
                      '## 1.1.3 — 2026-99-16\n\nNew work.'):
            with self.subTest(notes=notes):
                self.notes = notes
                with self.assertRaises(ValueError):
                    self.candidate()

    def test_existing_release_or_partial_tag_is_never_overwritten(self):
        for path in ('releases/tags/v1.1.3', 'git/ref/tags/v1.1.3'):
            self.existing = {path}
            self.assertIsNone(self.candidate()[0])

    def test_expired_or_missing_artifacts_block_automatic_release(self):
        self.artifacts[0]['expired'] = True
        with self.assertRaisesRegex(ValueError, 'artifacts'):
            self.candidate()
        self.artifacts = []
        with self.assertRaisesRegex(ValueError, 'artifacts'):
            self.candidate()

    def test_security_must_be_successful_for_the_same_source_and_repository(self):
        for update in ({'head_sha': 'd' * 40}, {'head_repository': {'full_name': 'fork/workbench'}},
                       {'head_branch': 'feature'}, {'event': 'pull_request'}, {'status': 'queued'}):
            with self.subTest(update=update):
                original = self.runs[0]
                self.runs[0] = dict(original, **update)
                with self.assertRaises(auto_release.PendingChecks):
                    self.candidate()
                self.runs[0] = original

    def test_new_failed_security_run_overrides_old_success(self):
        for row in self.runs[:]:
            self.runs.append(dict(row, id=30, conclusion='failure'))
            with self.assertRaisesRegex(ValueError, 'Security validation'):
                self.candidate()
            self.runs.pop()

    def test_queued_release_prevents_duplicate_dispatch(self):
        self.runs.append(dict(self.run, id=20, path='.github/workflows/release.yml',
                              event='workflow_dispatch', status='queued', conclusion=None))
        self.assertIsNone(self.candidate()[0])

    def test_permission_error_is_not_treated_as_missing_release(self):
        def denied(path):
            if path.startswith('releases/'):
                raise urllib.error.HTTPError(path, 403, 'Denied', {}, None)
            return self.read(path)
        with self.assertRaises(urllib.error.HTTPError):
            auto_release.automatic_release(denied, 10, self.repository)

    def test_security_wait_rechecks_the_branch_before_dispatch(self):
        self.runs[0]['status'] = 'in_progress'
        def advance(_):
            self.branch_sha = 'c' * 40
        result = auto_release.wait_for_release(self.read, 10, self.repository, 'main', attempts=2, sleep=advance)
        self.assertIsNone(result[0])

    def test_security_wait_is_bounded_and_can_complete(self):
        self.runs[0]['status'] = 'in_progress'
        with self.assertRaisesRegex(ValueError, 'did not finish'):
            auto_release.wait_for_release(self.read, 10, self.repository, 'main', attempts=2, sleep=lambda _: None)
        def finish(_):
            self.runs[0]['status'] = 'completed'
        result = auto_release.wait_for_release(self.read, 10, self.repository, 'main', attempts=2, sleep=finish)
        self.assertIsNotNone(result[0])

    def test_receiving_workflow_rejects_branch_movement_after_dispatch(self):
        validate_expected_source('', self.sha)
        validate_expected_source(self.sha, self.sha)
        for expected in ('b' * 40, 'main', self.sha + '\nextra'):
            with self.assertRaisesRegex(ValueError, 'source commit'):
                validate_expected_source(expected, self.sha)

    def test_dispatch_submits_json_to_existing_release_workflow(self):
        payload, _ = self.candidate()
        response = Mock(status=204)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.dict(os.environ, {'GH_TOKEN': 'synthetic-test-token'}), \
                patch.object(auto_release.urllib.request, 'urlopen', return_value=response) as send:
            auto_release.dispatch_release(self.repository, payload)
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.github.com/repos/example/workbench/actions/workflows/release.yml/dispatches')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(json.loads(request.data), payload)

    def test_automatic_reuse_never_falls_back_to_an_unvalidated_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'VERSION').write_text(self.version, encoding='utf-8')
            environment = {'GITHUB_REPOSITORY': self.repository, 'GITHUB_SHA': self.sha,
                           'REQUESTED_RELEASE_VERSION': self.version, 'GITHUB_OUTPUT': str(root / 'output'),
                           'REQUIRE_VALIDATED_BUILD': 'true'}
            with patch.dict(os.environ, environment), patch.object(select_release_build, 'ROOT', root), \
                    patch.object(select_release_build, 'github_reader'), \
                    patch.object(select_release_build, 'select_build', return_value=None):
                with self.assertRaisesRegex(ValueError, 'validated main build'):
                    select_release_build.main()
                self.assertFalse((root / 'output').exists())
                with patch.dict(os.environ, {'REQUIRE_VALIDATED_BUILD': 'false'}):
                    select_release_build.main()
                self.assertEqual((root / 'output').read_text().strip(), 'reuse_run_id=')


if __name__ == '__main__':
    unittest.main()

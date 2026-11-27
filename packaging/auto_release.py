"""Dispatch the existing release workflow after a reviewed version bump passes CI."""
import base64
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import quote, urlencode
import urllib.error
import urllib.request

from prepare_release import github_reader
from release_tools import changelog_notes, normalized_version
from select_release_build import REQUIRED_ARTIFACTS


class PendingChecks(Exception):
    """The exact-source security workflows have not finished yet."""


def source_text(read, path, commit):
    row = read('contents/' + path + '?' + urlencode({'ref': commit}))
    if row.get('encoding') != 'base64':
        raise ValueError('Expected a base64 repository file')
    return base64.b64decode(row['content']).decode('utf-8')


def version_key(value):
    version = normalized_version(value)
    core, _, preview = version.partition('-')
    stage, _, number = preview.partition('.')
    return (*map(int, core.split('.')), {'alpha': 0, 'beta': 1, 'rc': 2, '': 3}[stage], int(number or 0))


def exists(read, path):
    try:
        read(path)
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
        return False
    return True


def automatic_release(read, run_id, repository, branch='main'):
    """Return a dispatch payload, or a reason for safely doing nothing."""
    run = read('actions/runs/' + str(int(run_id)))
    if (run.get('event') != 'push' or run.get('head_branch') != branch or
            run.get('head_repository', {}).get('full_name') != repository or
            run.get('path') != '.github/workflows/check-and-package.yml' or
            run.get('status') != 'completed' or run.get('conclusion') != 'success'):
        return None, 'Only successful package builds from this repository on the default branch can release.'
    commit = run.get('head_sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Invalid checked source commit')
    if read('branches/' + quote(branch, safe=''))['commit']['sha'] != commit:
        return None, 'The default branch moved; release the reviewed version manually after checking the new source.'
    parents = read('commits/' + commit)['parents']
    if not parents:
        return None, 'The initial commit is not an automatic version bump.'
    version = normalized_version(source_text(read, 'VERSION', commit))
    previous = normalized_version(source_text(read, 'VERSION', parents[0]['sha']))
    if version == previous:
        return None, 'VERSION did not change against the first parent.'
    if version_key(version) <= version_key(previous):
        raise ValueError('Automatic releases require an increasing version')
    changelog_notes(version, source_text(read, 'CHANGELOG.md', commit))
    tag = quote('v' + version, safe='')
    if exists(read, 'releases/tags/' + tag) or exists(read, 'git/ref/tags/' + tag):
        return None, 'This release or tag already exists; it will never be overwritten.'
    artifacts = read('actions/runs/' + str(int(run_id)) + '/artifacts?per_page=100')['artifacts']
    available = {row['name'] for row in artifacts if not row.get('expired', True)}
    if not REQUIRED_ARTIFACTS <= available:
        raise ValueError('The successful build no longer has all validated release artifacts')
    runs = read('actions/runs?' + urlencode({'head_sha': commit, 'per_page': 100}))['workflow_runs']
    trusted = [row for row in runs if row.get('head_sha') == commit and
               row.get('head_branch') == branch and
               row.get('head_repository', {}).get('full_name') == repository]
    # Check the latest run, including a failed/in-progress rerun, never an older success.
    for path, event in (('.github/workflows/security.yml', 'push'),
                        ('dynamic/github-code-scanning/codeql', 'dynamic')):
        matches = [row for row in trusted if row.get('path') == path and row.get('event') == event]
        latest = max(matches, key=lambda row: (row['id'], row.get('run_attempt', 1)), default=None)
        if latest is None or latest.get('status') != 'completed':
            raise PendingChecks('Waiting for security validation of ' + commit)
        if latest.get('conclusion') != 'success':
            raise ValueError('Security validation did not succeed: ' + path)
    if any(row.get('path') == '.github/workflows/release.yml' and row.get('status') != 'completed'
           for row in trusted):
        return None, 'A release workflow is already queued or running for this source.'
    # Dispatch only a branch name supported by GitHub; the receiving workflow checks
    # this SHA again, closing the race if the branch moves between the read and POST.
    return {'ref': branch, 'inputs': {'release_version': version, 'publish': True,
            'prerelease': '-' in version, 'expected_source_commit': commit,
            'require_validated_build': True}}, 'Dispatching validated release v' + version


def wait_for_release(read, run_id, repository, branch, attempts=40, sleep=time.sleep):
    for attempt in range(attempts):
        try:
            return automatic_release(read, run_id, repository, branch)
        except PendingChecks:
            if attempt + 1 == attempts:
                raise ValueError('Security checks did not finish; rerun this trigger after they pass') from None
            sleep(15)


def dispatch_release(repository, payload):
    request = urllib.request.Request(
        'https://api.github.com/repos/' + repository + '/actions/workflows/release.yml/dispatches',
        data=json.dumps(payload).encode('utf-8'), method='POST',
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json',
                 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Library-Workbench-release'})
    with urllib.request.urlopen(request, timeout=25) as response:
        if response.status not in (200, 201, 204):
            raise ValueError('GitHub did not accept the release dispatch')


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    payload, reason = wait_for_release(github_reader(repository), os.environ['VALIDATED_RUN_ID'],
                                      repository, os.environ.get('RELEASE_DEFAULT_BRANCH') or 'main')
    if payload:
        dispatch_release(repository, payload)
    print(reason)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as summary:
        summary.write(reason + '\n')


if __name__ == '__main__':
    main()

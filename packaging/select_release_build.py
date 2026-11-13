"""Select a fully validated default-branch build of this exact release source."""
import os
from pathlib import Path
from urllib.parse import urlencode
import urllib.error

from prepare_release import github_reader
from release_tools import ROOT,normalized_version

REQUIRED_ARTIFACTS={'windows-x64-portable','macos-arm64-portable','macos-x86_64-portable',
                    'linux-x86_64-portable','linux-source','release-set-validation'}


def select_build(read,commit,version,source_version,repository,branch='main'):
    # A main push embeds VERSION. A manually overridden release version must build
    # new archives even if its source commit has already passed every check.
    if normalized_version(version)!=normalized_version(source_version):return None
    query=urlencode({'event':'push','branch':branch,'head_sha':commit,'status':'success','per_page':20})
    runs=read('actions/workflows/check-and-package.yml/runs?'+query).get('workflow_runs',[])
    for run in runs:
        if (run.get('event')!='push' or run.get('head_branch')!=branch or run.get('head_sha')!=commit or
            run.get('status')!='completed' or run.get('conclusion')!='success' or
            run.get('head_repository',{}).get('full_name')!=repository or
            run.get('path')!='.github/workflows/check-and-package.yml'):continue
        artifacts=read('actions/runs/'+str(int(run['id']))+'/artifacts?per_page=100').get('artifacts',[])
        available={row['name'] for row in artifacts if not row.get('expired',True)}
        if REQUIRED_ARTIFACTS<=available:return int(run['id'])
    return None


def main():
    repo=os.environ['GITHUB_REPOSITORY'];run=None
    try:
        run=select_build(github_reader(repo),os.environ['GITHUB_SHA'],os.environ['REQUESTED_RELEASE_VERSION'],
                         (ROOT/'VERSION').read_text(encoding='utf-8'),repo,
                         os.environ.get('RELEASE_DEFAULT_BRANCH') or 'main')
    except (urllib.error.URLError,ValueError,KeyError) as error:
        # Discovery is an optimization only; native assembly remains the fallback.
        print('No reusable build could be selected; rebuilding every platform ('+type(error).__name__+').')
    with Path(os.environ['GITHUB_OUTPUT']).open('a',encoding='utf-8') as output:
        output.write('reuse_run_id='+('' if run is None else str(run))+'\n')
    print('Reusing validated main build '+str(run) if run else 'Building fresh native packages')


if __name__=='__main__':main()

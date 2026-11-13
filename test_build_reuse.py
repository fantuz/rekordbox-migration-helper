"""Release reuse trusts exact main builds and rejects stale or foreign evidence."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

with patch.object(sys,'path',[str(Path(__file__).parent/'packaging'),*sys.path]):
    import build_linux_python as runtime
    from select_release_build import REQUIRED_ARTIFACTS,select_build


class BuildReuseTests(unittest.TestCase):
    def setUp(self):
        self.commit='a'*40;self.repo='example/workbench'
        self.run={'id':22,'head_sha':self.commit,'head_branch':'main','event':'push','status':'completed',
                  'conclusion':'success','head_repository':{'full_name':self.repo},
                  'path':'.github/workflows/check-and-package.yml'}
        self.artifacts=[{'name':name,'expired':False} for name in REQUIRED_ARTIFACTS]

    def read(self,path):
        if path.startswith('actions/workflows/'):return {'workflow_runs':[self.run]}
        self.assertEqual(path,'actions/runs/22/artifacts?per_page=100')
        return {'artifacts':self.artifacts}

    def select(self):return select_build(self.read,self.commit,'1.0.1','1.0.1',self.repo)

    def test_exact_successful_main_run_is_reused_only_with_every_validated_artifact(self):
        self.assertEqual(self.select(),22)
        for name in REQUIRED_ARTIFACTS:
            saved=deepcopy(self.artifacts)
            next(row for row in self.artifacts if row['name']==name)['expired']=True
            self.assertIsNone(self.select());self.artifacts=saved

    def test_pr_fork_wrong_commit_branch_or_workflow_is_never_reused(self):
        for field,value in (('head_sha','b'*40),('head_branch','feature'),('event','pull_request'),
                            ('status','in_progress'),('conclusion','failure'),
                            ('path','.github/workflows/unreviewed.yml'),('head_repository',{'full_name':'other/fork'})):
            saved=deepcopy(self.run);self.run[field]=value
            self.assertIsNone(self.select(),field);self.run=saved

    def test_version_override_builds_fresh_without_querying_artifacts(self):
        def forbidden(path):self.fail('Version override must not select a main artifact')
        self.assertIsNone(select_build(forbidden,self.commit,'1.0.2','1.0.1',self.repo))


class RuntimeCacheTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.cache=self.root/'cache';self.cache.mkdir()
        self.context={'version':runtime.VERSION,'source_sha256':runtime.SOURCE_SHA256,'image':'pinned'}
        patcher=patch.object(runtime,'PREFIX',self.root/'workbench-python');patcher.start();self.addCleanup(patcher.stop)

    def archive(self,name='workbench-python/bin/python3.13'):
        archive=self.cache/'python-runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as package:
            data=b'synthetic runtime';info=tarfile.TarInfo(name);info.size=len(data);package.addfile(info,BytesIO(data))
        (self.cache/'runtime.json').write_text(json.dumps({'context':self.context,'sha256':sha256(archive.read_bytes()).hexdigest()}),encoding='utf-8')

    def test_valid_context_and_checksum_still_require_runtime_validation(self):
        self.archive()
        with patch.object(runtime,'validate_runtime') as validate:
            self.assertTrue(runtime.restore_runtime(self.cache,self.context));validate.assert_called_once()
        self.assertTrue((runtime.PREFIX/'bin/python3.13').is_file())

    def test_wrong_source_context_corruption_and_escaping_archive_are_rebuilt(self):
        self.archive()
        with patch.object(runtime,'validate_runtime') as validate:
            self.assertFalse(runtime.restore_runtime(self.cache,{'version':'other'}));validate.assert_not_called()
            archive=self.cache/'python-runtime.tar.gz';archive.write_bytes(archive.read_bytes()+b'corrupt')
            self.assertFalse(runtime.restore_runtime(self.cache,self.context));validate.assert_not_called()
            self.archive('../outside')
            self.assertFalse(runtime.restore_runtime(self.cache,self.context));validate.assert_not_called()
        self.assertFalse((self.root/'outside').exists())


    def test_member_cannot_escape_runtime_prefix_inside_opt_parent(self):
        self.archive('workbench-python/../sibling.bin')
        with patch.object(runtime,'validate_runtime') as validate:
            self.assertFalse(runtime.restore_runtime(self.cache,self.context));validate.assert_not_called()
        self.assertFalse((self.root/'sibling.bin').exists())

    def test_symlink_cannot_target_sibling_in_prefix_parent(self):
        archive=self.cache/'python-runtime.tar.gz'
        with tarfile.open(archive,'w:gz') as package:
            member=tarfile.TarInfo('workbench-python/escape');member.type=tarfile.SYMTYPE;member.linkname='../sibling'
            package.addfile(member)
        (self.cache/'runtime.json').write_text(json.dumps({'context':self.context,'sha256':sha256(archive.read_bytes()).hexdigest()}),encoding='utf-8')
        with patch.object(runtime,'validate_runtime') as validate:
            self.assertFalse(runtime.restore_runtime(self.cache,self.context));validate.assert_not_called()
        self.assertFalse((runtime.PREFIX/'escape').exists())


if __name__=='__main__':unittest.main()

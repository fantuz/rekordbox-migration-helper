from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import zipfile


spec=importlib.util.spec_from_file_location('workbench_release_tools',Path(__file__).parent/'packaging/release_tools.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
with patch.object(sys,'path',[str(Path(__file__).parent/'packaging'),*sys.path]):
    from prepare_release import validate_release_target


class ReleaseTests(unittest.TestCase):
    def test_plain_versions_publish_stable_unless_preview_is_requested(self):
        self.assertFalse(release.release_is_preview('0.4.5'))
        self.assertTrue(release.release_is_preview('0.4.5',requested=True))
        for suffix in ('alpha.1','beta.2','rc.1'):
            self.assertTrue(release.release_is_preview('0.4.6-'+suffix))
        with self.assertRaises(ValueError):release.release_is_preview('not-a-version')

    def test_native_artifact_layouts_are_collected_without_private_or_unexpected_files(self):
        import sys
        with patch.object(sys,'path',[str(Path(__file__).parent/'packaging'),*sys.path]):
            from collect_release_assets import collect
            self.packages();destination=self.root/'flat';windows=next(self.root.glob('*windows*.zip'))
            nested=self.root/'releases';nested.mkdir();windows.rename(nested/windows.name)
            (self.root/'private.db').write_bytes(b'never a release input')
            names=collect(self.root,destination,self.version)
            self.assertEqual(len(names),8);self.assertFalse((destination/'private.db').exists())
            self.assertEqual(len(release.verify_assets(destination,self.version,self.commit)),4)
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.commit='a'*40;self.version='0.4.0';self.source=b'# synthetic source\n'

    def packages(self,wrong_commit=False,private_source=False):
        for platform in ('windows-x64','macos-arm64','macos-x86_64'):
            manifest={'version':self.version,'application_sources':{'app.py':sha256(self.source).hexdigest()}}
            if platform.startswith('windows'):
                manifest.update(windows_runtime_test='passed',windows_validation={'commit':'b'*40 if wrong_commit else self.commit})
                path='Library Workbench/BUILD-MANIFEST.json'
            else:
                manifest.update(macos_runtime_test='passed',commit=self.commit)
                path='Library Workbench.app/Contents/Resources/BUILD-MANIFEST.json'
            file=self.root/('Library-Workbench-'+self.version+'-'+platform+'.zip')
            with zipfile.ZipFile(file,'w') as archive:archive.writestr(path,json.dumps(manifest))
        file=self.root/('Library-Workbench-'+self.version+'-linux-source.tar.gz')
        with tarfile.open(file,'w:gz') as archive:
            for name,content in [('app.py',self.source),('.gitattributes',b'static/vendor.js -text\n'),('VERSION',(self.version+'\n').encode()),*([('.data/private.db',b'private')] if private_source else [])]:
                member=tarfile.TarInfo('library-workbench/'+name);member.size=len(content);archive.addfile(member,BytesIO(content))
        for file in self.root.iterdir():
            if file.name.endswith(('.zip','.tar.gz')):
                checksum=file.with_suffix('.sha256') if file.suffix=='.zip' else file.with_suffix('.gz.sha256')
                checksum.write_text(sha256(file.read_bytes()).hexdigest()+'  '+file.name+'\n',encoding='utf-8')

    def test_release_versions_are_validated_without_shell_interpretation(self):
        self.assertEqual(release.release_plan('v0.4.1-rc.1','refs/heads/main'),{'version':'0.4.1-rc.1','tag':'v0.4.1-rc.1'})
        for value in ('0.4.0;touch /tmp/example','$(echo bad)','0.4','01.2.3','0.4.0\ntag=other'):
            with self.assertRaises(ValueError):release.normalized_version(value)
        with self.assertRaisesRegex(ValueError,'default branch'):release.release_plan('0.4.0','refs/heads/unreviewed')

    def test_tag_version_is_canonical_and_cannot_be_overridden(self):
        self.assertEqual(release.release_plan('','refs/tags/v0.4.5'),{'version':'0.4.5','tag':'v0.4.5'})
        self.assertEqual(release.release_plan('','refs/tags/v0.4.6-rc.1')['version'],'0.4.6-rc.1')
        for ref in ('refs/tags/0.4.5','refs/tags/v0.4.5-unreviewed','refs/tags/v0.4.5/extra'):
            with self.assertRaises(ValueError):release.release_plan('',ref)
        with self.assertRaisesRegex(ValueError,'does not match'):release.release_plan('0.4.6','refs/tags/v0.4.5')

    def github_state(self, target=None, merged=True, existing_release=False):
        def read(path):
            if path.startswith('releases/tags/'):
                if existing_release:return {'id':123}
            elif path.startswith('git/ref/tags/'):
                if target is not None:return {'object':target}
            elif path.startswith('git/tags/'):
                return {'object':{'type':'commit','sha':self.commit}}
            elif path.startswith('compare/'):
                return {'status':'ahead' if merged else 'diverged','merge_base_commit':{'sha':self.commit if merged else 'c'*40}}
            raise urllib.error.HTTPError('https://api.github.test/'+path,404,'Not found',{},None)
        return read

    def test_manual_release_requires_a_new_tag_and_a_new_release(self):
        plan=release.release_plan(self.version,'refs/heads/main')
        validate_release_target(plan,'refs/heads/main',self.commit,self.github_state())
        with self.assertRaisesRegex(ValueError,'tag already exists'):
            validate_release_target(plan,'refs/heads/main',self.commit,self.github_state({'type':'commit','sha':self.commit}))
        with self.assertRaisesRegex(ValueError,'release already exists'):
            validate_release_target(plan,'refs/heads/main',self.commit,self.github_state(existing_release=True))

    def test_lightweight_and_annotated_tags_must_match_the_checked_main_commit(self):
        ref='refs/tags/v'+self.version;plan=release.release_plan('',ref)
        for target in ({'type':'commit','sha':self.commit},{'type':'tag','sha':'d'*40}):
            validate_release_target(plan,ref,self.commit,self.github_state(target))
        for target,message in ((None,'no longer exists'),({'type':'commit','sha':'b'*40},'checked commit'),({'type':'tree','sha':self.commit},'checked commit')):
            with self.assertRaisesRegex(ValueError,message):
                validate_release_target(plan,ref,self.commit,self.github_state(target))
        with self.assertRaisesRegex(ValueError,'merged into the default branch'):
            validate_release_target(plan,ref,self.commit,self.github_state({'type':'commit','sha':self.commit},merged=False))

    def test_api_failures_and_cyclic_annotated_tags_fail_closed(self):
        ref='refs/tags/v'+self.version;plan=release.release_plan('',ref)
        def denied(path):raise urllib.error.HTTPError('https://api.github.test/'+path,403,'Denied',{},None)
        with self.assertRaises(urllib.error.HTTPError):validate_release_target(plan,ref,self.commit,denied)
        read=self.github_state({'type':'tag','sha':'d'*40})
        def cyclic(path):
            if path.startswith('git/tags/'):return {'object':{'type':'tag','sha':'d'*40}}
            return read(path)
        with self.assertRaisesRegex(ValueError,'tag chain'):validate_release_target(plan,ref,self.commit,cyclic)

    def test_release_notes_include_only_the_requested_changelog_and_installation_limits(self):
        changelog='# Changelog\n\n## 0.4.6 — future\n\nUnreleased feature.\n\n## 0.4.5 — 2026-11-13\n\nColour cloud and insights.\n\n### Details\n\nStaged comments.\n\n## 0.4.0 — old\n\nOld feature.\n'
        notes=release.release_notes('0.4.5',self.commit,changelog)
        for value in ('Colour cloud','Staged comments','### Details','Library Workbench.exe','Apple Silicon','SHA256SUMS','experimental',self.commit):self.assertIn(value,notes)
        for value in ('Unreleased feature','Old feature'):self.assertNotIn(value,notes)
        self.assertIn('local library analyzer',release.release_notes('0.4.7',self.commit,changelog))

    def test_real_source_packager_allows_gitattributes_but_excludes_private_workspaces(self):
        import sys
        with patch.object(sys,'path',[str(Path(__file__).parent/'packaging'),*sys.path]):
            import build_source
        self.packages()
        source=self.root/'checkout';source.mkdir()
        (source/'app.py').write_bytes(self.source)
        (source/'.gitattributes').write_text('static/vendor.js -text\n',encoding='utf-8')
        (source/'CHANGELOG.md').write_text('# Public release notes\n',encoding='utf-8')
        (source/'.data').mkdir();(source/'.data'/'private.db').write_bytes(b'private input')
        with patch.object(build_source,'ROOT',source),patch.object(build_source,'VERSION',self.version):build_source.main()
        archive=next((source/'releases').glob('*.tar.gz'))
        with tarfile.open(archive) as packed:
            self.assertIn('library-workbench/.gitattributes',packed.getnames())
            self.assertIn('library-workbench/CHANGELOG.md',packed.getnames())
            self.assertNotIn('library-workbench/.data/private.db',packed.getnames())
        for output in (source/'releases').iterdir():
            (self.root/output.name).write_bytes(output.read_bytes())
        self.assertEqual(len(release.verify_assets(self.root,self.version,self.commit)),4)

    def test_download_table_links_exact_versioned_assets_without_preview_suffixes(self):
        names=release.archive_names('0.4.6-rc.1')
        self.assertEqual(names,[
            'Library-Workbench-0.4.6-rc.1-windows-x64.zip',
            'Library-Workbench-0.4.6-rc.1-macos-x86_64.zip',
            'Library-Workbench-0.4.6-rc.1-macos-arm64.zip',
            'Library-Workbench-0.4.6-rc.1-linux-source.tar.gz'])
        with patch.dict('os.environ',{'GITHUB_REPOSITORY':'example/workbench'}):notes=release.release_notes('0.4.6-rc.1',self.commit)
        self.assertEqual(notes.count('[Download now]('),4)
        for name in names:self.assertIn('https://github.com/example/workbench/releases/download/v0.4.6-rc.1/'+name,notes)
        self.assertNotIn('-preview.zip',notes)
        self.assertTrue(release.release_is_preview('0.4.6-rc.1'))

    def test_stale_preview_archives_are_not_published_as_current_output(self):
        self.packages()
        windows=self.root/('Library-Workbench-'+self.version+'-windows-x64.zip')
        windows.rename(windows.with_name(windows.stem+'-preview.zip'))
        with self.assertRaisesRegex(ValueError,'exactly the four'):release.verify_assets(self.root,self.version,self.commit)

    def test_full_history_includes_merged_features_and_complete_unicode_messages(self):
        repo=self.root/'history';repo.mkdir()
        def git(*args):
            return subprocess.run(['git',*args],cwd=repo,check=True,capture_output=True,text=True,encoding='utf-8').stdout.strip()
        git('init','--initial-branch=main');git('config','user.name','Release fixture');git('config','user.email','fixture@example.invalid')
        (repo/'base.txt').write_text('base',encoding='utf-8');git('add','base.txt');git('commit','-m','Initial feature')
        first=git('rev-parse','HEAD');git('checkout','-b','feature')
        (repo/'feature.txt').write_text('colour',encoding='utf-8');git('add','feature.txt')
        message='Colour [links] <tag> @mention\n\nFull details: Ελληνικά · Łódź · 日本語 🎧\nSecond body line.'
        git('commit','-m',message);feature=git('rev-parse','HEAD')
        git('checkout','main');(repo/'main.txt').write_text('metadata',encoding='utf-8')
        git('add','main.txt');git('commit','-m','Main metadata');git('merge','--no-ff','feature','-m','Merge colour feature')
        head=git('rev-parse','HEAD');history=release.commit_history(head,repo)
        self.assertEqual(len(history),4);self.assertEqual(history[0]['sha'],first);self.assertEqual(history[-1]['sha'],head)
        self.assertEqual(next(r['message'].rstrip('\n') for r in history if r['sha']==feature),message)
        text=release.full_commit_log('1.0.0',head,history)
        self.assertIn(message,text)
        for record in history:
            for key in ('sha','author','date','message'):self.assertIn(record[key],text)
        with patch.dict('os.environ',{'GITHUB_REPOSITORY':'example/workbench'}):
            notes=release.release_notes('1.0.0',head,'',history,'v0.4.5')
        for record in history:self.assertIn('/commit/'+record['sha'],notes)
        self.assertIn('Full commit log',notes);self.assertIn('Show all 4 commits',notes)
        self.assertIn('/compare/v0.4.5...v1.0.0',notes)
        self.assertIn('/releases/download/v1.0.0/COMMIT-LOG.txt',notes)
        self.assertIn('/releases/download/v1.0.0/SHA256SUMS',notes)
        self.assertIn('&#64;mention',notes);self.assertIn('&lt;tag&gt;',notes);self.assertIn(r'\[links\]',notes)

    def test_partial_history_and_unchecked_refs_cannot_be_published_as_full(self):
        with patch.object(release.subprocess,'run',return_value=SimpleNamespace(stdout='true\n')):
            with self.assertRaisesRegex(ValueError,'complete checkout'):release.commit_history(self.commit,self.root)
        for ref in ('--all','main','a'*40+'\nextra'):
            with self.assertRaisesRegex(ValueError,'checked release commit'):release.commit_history(ref,self.root)

    def test_four_native_validated_archives_must_share_release_source(self):
        self.packages()
        self.assertEqual(len(release.verify_assets(self.root,self.version,self.commit)),4)
        self.assertEqual(len((self.root/'SHA256SUMS').read_text().splitlines()),4)

    def test_existing_checksum_does_not_excuse_a_different_build_commit(self):
        self.packages(wrong_commit=True)
        with self.assertRaisesRegex(ValueError,'commit'):release.verify_assets(self.root,self.version,self.commit)

    def test_private_source_inputs_and_extra_archives_are_rejected(self):
        self.packages(private_source=True)
        with self.assertRaisesRegex(ValueError,'Unexpected source'):release.verify_assets(self.root,self.version,self.commit)
        extra=self.root/'Library-Workbench-9.9.9-surprise.zip';extra.write_bytes(b'not validated')
        with self.assertRaisesRegex(ValueError,'exactly the four'):release.verify_assets(self.root,self.version,self.commit)

    def test_corrupt_or_replaced_download_is_rejected(self):
        self.packages()
        next(self.root.glob('*.zip')).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum'):release.verify_assets(self.root,self.version,self.commit)


if __name__=='__main__':unittest.main()

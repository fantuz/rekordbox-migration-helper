from hashlib import sha256
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec=importlib.util.spec_from_file_location('workbench_release_tools',Path(__file__).parent/'packaging/release_tools.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
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
            file=self.root/('Library-Workbench-'+self.version+'-'+platform+'-preview.zip')
            with zipfile.ZipFile(file,'w') as archive:archive.writestr(path,json.dumps(manifest))
        file=self.root/('Library-Workbench-'+self.version+'-linux-source.tar.gz')
        with tarfile.open(file,'w:gz') as archive:
            for name,content in [('app.py',self.source),('VERSION',(self.version+'\n').encode()),*([('.data/private.db',b'private')] if private_source else [])]:
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

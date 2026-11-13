"""Synthetic streaming regressions; formal execution belongs to GitHub CI."""
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
import zipfile

from native_export import rewrite_archive


def digest(stream,size=None):
    value=sha256()
    while size is None or size:
        chunk=stream.read(2*1024**2 if size is None else min(size,2*1024**2))
        if not chunk:break
        value.update(chunk)
        if size is not None:size-=len(chunk)
    return value.digest()


def file_digest(path):
    with path.open('rb') as stream:return digest(stream)


def raw_member_digest(path,name):
    with zipfile.ZipFile(path) as archive:
        infos=sorted(archive.infolist(),key=lambda row:row.header_offset)
        index=next(i for i,row in enumerate(infos) if row.filename==name)
        end=infos[index+1].header_offset if index+1<len(infos) else archive.start_dir
        archive.fp.seek(infos[index].header_offset)
        return digest(archive.fp,end-infos[index].header_offset)


class NativeArchiveProgressTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup);self.root=Path(folder.name)

    def large_source(self):
        source=self.root/'source.zip'
        with zipfile.ZipFile(source,'w') as archive:
            archive.writestr('master.db',b'old database')
            with archive.open('analysis/large.bin','w',force_zip64=True) as stream:
                block=b'large analysis fixture\0'.ljust(2*1024**2,b'\x7f')
                for _ in range(18):stream.write(block)
        return source

    def test_large_zip64_member_reports_mid_copy_and_keeps_its_raw_bytes(self):
        source=self.large_source();target=self.root/'edited.zip';before=file_digest(source)
        values=[];intermediate=[]
        def progress(value,message):
            values.append(value)
            self.assertFalse(target.exists(),'The unvalidated output was published')
            if 35<value<90:intermediate.append(target.with_suffix('.partial').stat().st_size)
        rewrite_archive(source,target,{'master.db':b'new database with a different length'},progress)
        self.assertEqual(values[0],35);self.assertEqual(values[-1],99)
        self.assertEqual(values,sorted(values))
        self.assertGreaterEqual(len(intermediate),2)
        self.assertTrue(all(0<size<source.stat().st_size for size in intermediate))
        self.assertEqual(file_digest(source),before)
        self.assertEqual(raw_member_digest(source,'analysis/large.bin'),raw_member_digest(target,'analysis/large.bin'))
        with zipfile.ZipFile(source) as original,zipfile.ZipFile(target) as checked:
            self.assertEqual(checked.namelist(),original.namelist())
            self.assertIsNone(checked.testzip())
            self.assertEqual(checked.read('master.db'),b'new database with a different length')
            self.assertNotEqual(original.getinfo('analysis/large.bin').header_offset,checked.getinfo('analysis/large.bin').header_offset)

    def test_cancellation_mid_member_keeps_existing_destination_and_removes_partial(self):
        source=self.large_source();target=self.root/'edited.zip'
        with zipfile.ZipFile(target,'w') as prior:prior.writestr('master.db',b'previous completed export')
        before=file_digest(source);prior=file_digest(target);interrupted=[]
        def cancel(value,message):
            if 35<value<90:
                interrupted.append(target.with_suffix('.partial').stat().st_size)
                raise InterruptedError('Synthetic cancellation during a large ZIP member')
        with self.assertRaisesRegex(InterruptedError,'Synthetic cancellation'):
            rewrite_archive(source,target,{'master.db':b'new database'},cancel)
        self.assertEqual(len(interrupted),1)
        self.assertLess(interrupted[0],source.stat().st_size)
        self.assertEqual(file_digest(source),before);self.assertEqual(file_digest(target),prior)
        self.assertFalse(target.with_suffix('.partial').exists())

    def test_replacement_stream_and_hash_verification_both_report_progress(self):
        source=self.root/'source.zip';replacement=self.root/'native-master.db';target=self.root/'edited.zip'
        with replacement.open('wb') as stream:
            for _ in range(10):stream.write(b'\x17'*(2*1024**2))
        with zipfile.ZipFile(source,'w') as archive:
            archive.writestr('master.db',b'old database')
            archive.writestr('analysis/kept.dat',b'unchanged analysis'*500,compress_type=zipfile.ZIP_DEFLATED)
        before=file_digest(source);replacement_before=file_digest(replacement);values=[]
        def progress(value,message):
            values.append(value);self.assertFalse(target.exists())
        rewrite_archive(source,target,{'master.db':replacement},progress)
        self.assertEqual(values,sorted(values));self.assertEqual(values[-1],99)
        self.assertTrue(any(35<value<90 for value in values))
        self.assertTrue(any(90<value<99 for value in values))
        self.assertEqual(file_digest(source),before);self.assertEqual(file_digest(replacement),replacement_before)
        self.assertEqual(raw_member_digest(source,'analysis/kept.dat'),raw_member_digest(target,'analysis/kept.dat'))
        with zipfile.ZipFile(target) as checked,checked.open('master.db') as stream:
            self.assertEqual(digest(stream),replacement_before)
            self.assertIsNone(checked.testzip())

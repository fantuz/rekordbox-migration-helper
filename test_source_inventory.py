"""Synthetic bounded source-folder inspection, including cancellation and links."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest

from analyzer import footprint,analyze_folder
from test_analyzer import schema,add_track
import sqlite3


class SourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'source';self.root.mkdir()
        (self.root/'master.db').write_bytes(b'database')
        self.child=self.root/'USBANLZ';self.child.mkdir()
        (self.child/'nested.DAT').write_bytes(b'analysis')

    def test_default_never_opens_subdirectories(self):
        import os
        scandir=os.scandir;opened=[]
        def inspect(path):opened.append(Path(path));return scandir(path)
        with patch('analyzer.os.scandir',side_effect=inspect):report,assets=footprint(self.root,lambda *_:None)
        self.assertEqual(opened,[self.root]);self.assertEqual(report['files'],1)
        self.assertEqual(report['scope'],'top_level');self.assertIsNone(assets)

    def test_recursive_entry_limit_is_partial_and_does_not_claim_missing_assets(self):
        report,assets=footprint(self.root,lambda *_:None,recursive=True,max_entries=1)
        self.assertLessEqual(report['entries_inspected'],1);self.assertFalse(report['complete'])
        self.assertEqual(report['limit_reached'],'entry_limit');self.assertIsNone(assets)

    def test_elapsed_limit_is_partial(self):
        with patch('analyzer.time.monotonic',side_effect=[0,31]):report,assets=footprint(self.root,lambda *_:None,recursive=True)
        self.assertEqual(report['limit_reached'],'time_limit');self.assertIsNone(assets)

    def test_cancellation_propagates_instead_of_becoming_an_unreadable_warning(self):
        for i in range(150):(self.root/f'{i}.dat').touch()
        def progress(_,message):
            if '128 entries' in message:raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):footprint(self.root,progress,recursive=True)

    def test_depth_limit_and_directory_links_are_not_followed(self):
        report,assets=footprint(self.root,lambda *_:None,recursive=True,max_depth=0)
        self.assertFalse(report['complete']);self.assertEqual(report['files'],1);self.assertIsNone(assets)
        try:(self.root/'loop').symlink_to(self.root,target_is_directory=True)
        except OSError:return
        report,assets=footprint(self.root,lambda *_:None,recursive=True)
        self.assertEqual(report['files'],2);self.assertGreater(report['skipped_entries'],0)

    def test_cloud_and_windows_reparse_directories_are_not_entered(self):
        import stat
        class Entry:
            name='linked';path=str(self.root/'linked')
            def stat(self,**_):return SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
            def is_symlink(self):return False
        class Scan:
            def __enter__(self):return iter([Entry()])
            def __exit__(self,*_):pass
        with patch('analyzer.os.scandir',return_value=Scan()) as scan:
            report,assets=footprint(self.root,lambda *_:None,recursive=True)
        self.assertEqual(scan.call_count,1);self.assertEqual(report['skipped_entries'],1);self.assertIsNone(assets)

    def test_progress_names_the_subfolder_and_report_splits_the_count(self):
        messages=[]
        report,_=footprint(self.root,lambda _,text:messages.append(text),recursive=True)
        self.assertTrue(any('USBANLZ' in text for text in messages))
        self.assertEqual(report['files_by_top_level_folder'],{'.':1,'USBANLZ':1})

    def test_default_capture_keeps_database_statistics_and_unknown_asset_availability(self):
        (self.root/'master.db').unlink()
        with sqlite3.connect(self.root/'master.db') as db:schema(db);add_track(db);db.commit()
        result=analyze_folder(self.root,Path(self.tmp.name)/'output',lambda *_:None)
        self.assertEqual(result['read_status'],'checked',result['messages'])
        self.assertEqual(result['database']['counters']['tracks'],1)
        for key in ('analysis_folders_found','unlinked_analysis_folders','analysis_folders_not_found_here'):
            self.assertIsNone(result['database']['health'][key])

if __name__=='__main__':unittest.main()

from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest
from analyzer import analyze_folder
from migration_readiness import tempo_key_review
from workbench_store import Store


class XmlStatisticsTests(unittest.TestCase):
    def test_xml_only_capture_and_saved_snapshot_preserve_tempo_disagreement(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'collection.xml';output=root/'report'
            tracks='''<TRACK TrackID="1" Name="Half time" AverageBpm="87"><TEMPO Bpm="174"/></TRACK>
              <TRACK TrackID="2" Name="Agreement" AverageBpm="128"><TEMPO Bpm="128"/></TRACK>
              <TRACK TrackID="3" Name="Variable" AverageBpm="128"><TEMPO Bpm="128"/><TEMPO Bpm="140"/></TRACK>
              <TRACK TrackID="4" Name="Unknown"><TEMPO Bpm="NaN"/><TEMPO Bpm="-1"/></TRACK>'''
            source.write_text('<DJ_PLAYLISTS><COLLECTION>'+tracks+'</COLLECTION></DJ_PLAYLISTS>')
            original=source.read_bytes();analyze_folder(str(source),output,lambda *_:None)
            for name in ('metadata.json','comparison.json'):
                captured=json.loads((output/name).read_text())
                self.assertEqual(captured['tracks'][0].get('grid_bpms'),[174])
                self.assertEqual(captured['tracks'][0].get('xml_bpm'),87)
                self.assertEqual(captured['tracks'][3].get('grid_bpms'),[])
                self.assertIsNone(captured['tracks'][3].get('xml_bpm'))
                store=Store(root/'sidecar.sqlite3');sid=store.save_snapshot(captured,name)['id']
                summary,rows=tempo_key_review(store.snapshot(sid))
                self.assertEqual(summary['tempo_disagreements'],2)
                self.assertEqual(summary['tempo_agreements'],1)
                self.assertEqual(summary['tempo_comparison_unknown'],1)
                half=next(r for r in rows if r['section']=='tempo_disagreement' and r['track_id']=='1')
                self.assertTrue(half['half_double']);self.assertEqual(half['saved_bpm'],87)
                self.assertEqual(store.edit_state(captured['scope_key'])['overrides'],{})
            self.assertEqual(source.read_bytes(),original)

    def test_v5_xml_counts_tags_and_playlists_without_conversion_or_source_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'v5-collection.xml';output=root/'report'
            source.write_text('''<DJ_PLAYLISTS><PRODUCT Version="5.8.6"/><COLLECTION Entries="2">
              <TRACK TrackID="1" Name="First" Artist="An artist" Album="Album" Genre="House" TotalTime="240" AverageBpm="125" Year="2018" Rating="153" Location="file://localhost/C:/Music/first.mp3"/>
              <TRACK TrackID="2" Name="Second" Artist="Another artist" Location="file://localhost/C:/Music/second.mp3"/>
              </COLLECTION><PLAYLISTS><NODE Name="ROOT" Type="0"><NODE Name="Set" Type="1" KeyType="0"><TRACK Key="1"/></NODE>
              <NODE Name="By location" Type="1" KeyType="1"><TRACK Key="file://localhost/C:/Music/second.mp3"/></NODE></NODE></PLAYLISTS></DJ_PLAYLISTS>''',encoding='utf-8')
            before=sha256(source.read_bytes()).hexdigest();report=analyze_folder(str(source),output,lambda *_:None)
            self.assertEqual(report['xml']['counters']['tracks'],2);self.assertEqual(report['xml']['counters']['artists'],2)
            self.assertEqual(report['xml']['counters']['playlists'],2);self.assertEqual(report['xml']['counters']['bpm_known'],1)
            self.assertIsNone(report['database']);self.assertFalse(report['source_writes'])
            metadata=json.loads((output/'metadata.json').read_text())
            self.assertEqual(metadata['tracks'][0]['bpm'],125);self.assertEqual(metadata['tracks'][0]['duration'],240)
            self.assertEqual(metadata['tracks'][0]['rating'],3);self.assertIsNone(metadata['tracks'][1]['bpm'])
            self.assertEqual(metadata['tracks'][1]['playlists'],['By location'])
            self.assertEqual(sha256(source.read_bytes()).hexdigest(),before)

    def test_xml_entity_declarations_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'collection.xml';source.write_text('<!DOCTYPE x [<!ENTITY e "private">]><DJ_PLAYLISTS>&e;</DJ_PLAYLISTS>')
            with self.assertRaises(ValueError):analyze_folder(str(source),root/'out',lambda *_:None)


if __name__=='__main__':unittest.main()

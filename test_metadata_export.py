from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import app as application
from metadata_export import capture_catalog, disclosure, export_metadata, list_metadata_exports, number, payload, track


ASSETS=Path(__file__).parent/"static"


def example_catalog():
    tracks={"a":{"track_id":"a","title":"</script><img src=x onerror=alert(1)> 日本", "artist":"Artist & friend",
                  "album":"Album", "genre":"House", "year":2020,"bpm":128,"rating":4,"duration_seconds":360,
                  "current_path":r"C:\Users\private-name\Music\track.mp3","original_path":"/private/original.mp3",
                  "playlist_ids":["p"],"october_xml":True,"analysed":True},
            "b":{"track_id":"b","title":"Other","artist":"Artist","genre":"","duration_seconds":0,
                  "rating":0,"october_xml":False,"analysed":None}}
    return SimpleNamespace(tracks=tracks,metadata={"version":"7.2.19","playlist_options":[{"id":"p","name":"My playlist"}]},
                           cue_summary=lambda _: {"auto":2,"other":1})


class MetadataExportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)

    def test_snapshot_filters_xml_scope_and_preserves_unknown_values(self):
        cat=example_catalog();before=deepcopy(cat.tracks)
        all_tracks=capture_catalog(cat)
        self.assertEqual(len(all_tracks["tracks"]),2)
        unknown=all_tracks["tracks"][1]
        self.assertIsNone(unknown['bpm']);self.assertIsNone(unknown['year'])
        self.assertIsNone(unknown['analysed']);self.assertEqual(unknown['rating'],0)
        self.assertEqual(all_tracks["tracks"][0]['playlists'],['My playlist'])
        self.assertEqual(len(capture_catalog(cat,'xml')['tracks']),1)
        self.assertEqual(cat.tracks,before)
        with self.assertRaises(ValueError):capture_catalog(cat,'invalid')

    def test_html_and_minisite_are_offline_and_do_not_disclose_paths_by_default(self):
        snapshot=capture_catalog(example_catalog())
        result=export_metadata(snapshot,self.root,'a'*32,ASSETS,lambda *_:None,title='Private <library>')
        folder=Path(result['directory']);text=(folder/'library.html').read_text(encoding='utf-8')
        self.assertNotIn('private-name',text);self.assertNotIn('/private/original',text)
        self.assertNotIn('</script><img',text);self.assertIn('\\u003c/script',text)
        self.assertIn('Private &lt;library&gt;',text)
        self.assertIn("connect-src 'none'",text)
        self.assertNotRegex(text,r'<(?:script|link)[^>]+(?:src|href)="https?://')
        self.assertNotIn('fetch(',text)
        self.assertFalse(result['staged_changes_applied'])
        with zipfile.ZipFile(folder/'metadata-explorer.zip') as archive:
            self.assertIsNone(archive.testzip())
            for page in ('index','tracks','genres','years','added','artists','albums','bpm','ratings','duration','formats','playlists','tonality','colours'):
                self.assertIn(page+'.html',archive.namelist())
            script=archive.read('library-data.js').decode('utf-8')
            self.assertNotIn('private-name',script)
            data=json.loads(script.removeprefix('window.METADATA_SNAPSHOT=').removesuffix(';'))
            self.assertEqual(len(data['rows']),2)
            self.assertNotIn('current_path',data['columns'])
        self.assertEqual(list_metadata_exports(self.root)[0]['id'],result['id'])

    def test_explicit_path_choice_and_invalid_numbers_are_handled(self):
        snapshot=capture_catalog(example_catalog())
        result=export_metadata(snapshot,self.root,'b'*32,ASSETS,lambda *_:None,include_paths=True)
        text=(Path(result['directory'])/'library.html').read_text(encoding='utf-8')
        self.assertIn('private-name',text);self.assertTrue(result['includes_paths'])
        for value in ('NaN',float('inf'),-1,'garbage',None):self.assertIsNone(number(value))
        self.assertIsNone(track({'rating':8,'year':0,'bpm':0})['rating'])

    def test_failed_generation_never_publishes_a_partial_explorer(self):
        with patch('metadata_export.zipfile.ZipFile',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):export_metadata(capture_catalog(example_catalog()),self.root,'c'*32,ASSETS,lambda *_:None)
        self.assertFalse((self.root/('c'*32)).exists())
        self.assertEqual(list(self.root.iterdir()),[])

    def test_public_summary_does_not_embed_individual_or_personal_metadata(self):
        snapshot=capture_catalog(example_catalog())
        snapshot['tracks'][0].update(id='PRIVATE-ID',title='PRIVATE-TITLE',play_count=987654,
                                     date_added='PRIVATE-DATE',last_played='PRIVATE-LAST',comment='PRIVATE-COMMENT')
        data=payload(snapshot,'Shared preferences',include_paths=True,preset='public')
        self.assertEqual(data['rows'],[]);self.assertEqual(data['columns'],[])
        self.assertEqual(data['track_count'],2);self.assertFalse(data['includes_paths'])
        encoded=json.dumps(data)
        for private in ('PRIVATE-ID','PRIVATE-TITLE','PRIVATE-DATE','PRIVATE-LAST','PRIVATE-COMMENT','987654','My playlist','private-name'):
            self.assertNotIn(private,encoded)
        self.assertEqual(data['aggregates']['tracks'],2)
        self.assertEqual(data['aggregates']['categories']['genres'][0]['count'],1)
        result=export_metadata(snapshot,self.root,'f'*32,ASSETS,lambda *_:None,preset='public')
        self.assertEqual(result['tracks'],2);self.assertEqual(result['preset'],'public')
        with zipfile.ZipFile(Path(result['directory'])/'metadata-explorer.zip') as archive:
            embedded=archive.read('library-data.js').decode('utf-8')
            self.assertNotIn('PRIVATE-TITLE',embedded);self.assertNotIn('My playlist',embedded)
            self.assertEqual(json.loads(embedded.removeprefix('window.METADATA_SNAPSHOT=').removesuffix(';'))['rows'],[])

    def test_selected_track_list_and_private_field_choices_are_enforced_in_data(self):
        snapshot=capture_catalog(example_catalog())
        data=payload(snapshot,'One track',preset='selected',track_ids=['a'])
        self.assertEqual(data['track_count'],1)
        self.assertNotIn('id',data['columns']);self.assertNotIn('play_count',data['columns'])
        self.assertNotIn('playlists',data['columns']);self.assertNotIn('date_added',data['columns'])
        by_playlist=payload(snapshot,'Playlist',preset='selected',playlist='My playlist')
        self.assertEqual(by_playlist['rows'],data['rows'])
        minimal=payload(snapshot,'Minimal',preset='private',fields=['genre'])
        self.assertEqual(minimal['columns'],['genre']);self.assertEqual(minimal['rows'],[['House'],['']])
        self.assertNotIn('Artist & friend',json.dumps(minimal))
        for choices in ({'preset':'selected'},{'preset':'selected','track_ids':['missing']},{'fields':['password']},
                        {'fields':[]},{'preset':'invalid'},{'track_ids':'a'}):
            with self.assertRaises(ValueError):payload(snapshot,'Invalid',**choices)

    def test_preview_matches_export_fields_and_state_without_returning_track_values(self):
        snapshot=capture_catalog(example_catalog());snapshot['metadata_overrides_applied']=2
        choices={'preset':'private','fields':['artist','year'],'include_paths':True}
        preview=disclosure(snapshot,**choices);data=payload(snapshot,'Private',**choices)
        self.assertEqual(preview['fields'],data['columns']);self.assertEqual(preview['track_count'],len(data['rows']))
        self.assertEqual(preview['data_state'],'working');self.assertFalse(preview['staged_changes_applied'])
        self.assertNotIn('rows',preview);self.assertNotIn('private-name',json.dumps(preview))
        selected=disclosure(snapshot,preset='selected')
        self.assertEqual(selected['track_count'],0);self.assertIn('My playlist',selected['available_playlists'])

    def test_public_aggregation_keeps_unknowns_unicode_and_empty_collections(self):
        snapshot={'tracks':[track({'id':'é-𝄞','genre':'</script>日本\u2028','bpm':None,'duration':0})]}
        data=payload(snapshot,'Unicode',preset='public')
        self.assertEqual(data['aggregates']['categories']['genres'][0]['label'],'</script>日本\u2028')
        self.assertIsNone(data['aggregates']['average_bpm'])
        empty=payload({'tracks':[]},'Empty',preset='public')
        self.assertEqual(empty['aggregates']['tracks'],0);self.assertEqual(empty['aggregates']['categories']['genres'],[])


class QuickExportAPITests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.catalog=example_catalog()
        self.session={'catalog':self.catalog,'backup_acknowledged':None,'decisions':{'sample':{'action':'merge'}},'relocations':{'a':'file:///new/location.mp3'}}
        self.outputs=[]
        def launch(work,message):
            self.outputs.append(work(lambda *_:None));return 'job'
        for name,value in (('DATA',self.root),('sessions',{'test':self.session}),('active','test'),('launch',launch)):
            p=patch.object(application,name,value);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def test_read_only_export_needs_no_backup_ack_and_does_not_apply_staged_edits(self):
        before=deepcopy(self.session['decisions'])
        response=self.client.post('/api/quick-export',json={'source':'session'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        result=self.outputs[0];self.assertEqual(result['tracks'],2)
        self.assertFalse(result['staged_changes_applied']);self.assertEqual(self.session['decisions'],before)
        downloaded=self.client.get('/api/quick-export/'+result['id']+'/html')
        self.assertEqual(downloaded.status_code,200)
        self.assertNotIn(b'file:///new/location.mp3',downloaded.data);downloaded.close()
        self.assertEqual(len(self.client.get('/api/quick-export').json['exports']),1)

    def test_source_snapshot_can_export_with_no_active_workspace(self):
        application.active=None
        report='d'*32;folder=self.root/'analyzers'/report;folder.mkdir(parents=True)
        (folder/'metadata.json').write_text(json.dumps(capture_catalog(self.catalog)),encoding='utf-8')
        response=self.client.post('/api/quick-export',json={'source':report},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.outputs[0]['tracks'],2)
        response=self.client.post('/api/quick-export',json={'source':report,'scope':'xml'},headers=self.headers)
        self.assertEqual(response.status_code,400)

    def test_local_token_and_source_paths_are_enforced(self):
        self.assertEqual(self.client.post('/api/quick-export',json={}).status_code,403)
        response=self.client.post('/api/quick-export',json={'source':'../../master.db'},headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.client.get('/api/quick-export/'+'e'*32+'/html').status_code,404)


if __name__=='__main__':unittest.main()

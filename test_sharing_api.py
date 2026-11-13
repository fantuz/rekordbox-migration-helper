"""Sharing integration: exact disclosure, metadata state and private XML copies."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import app as application
from metadata_export import FIELDS,capture_catalog
from temporary_files import TemporaryWorkspace
from test_metadata_export import example_catalog
from workbench_store import Store

XML=b'''<?xml version="1.0" encoding="UTF-8"?><DJ_PLAYLISTS><PRODUCT Version="7.2.19"/>
<COLLECTION Entries="1"><TRACK TrackID="one" Name="Track" Artist="Artist" Genre="House" AverageBpm="128"
Location="file://localhost/C:/Users/private-name/Music/track.mp3"/></COLLECTION>
<PLAYLISTS><NODE Type="0" Name="ROOT"><NODE Type="1" Name="Private set" KeyType="0"><TRACK Key="one"/></NODE></NODE></PLAYLISTS></DJ_PLAYLISTS>'''


class SharingApiTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.data=self.root/'data'
        self.temporary=TemporaryWorkspace(self.data);self.addCleanup(self.temporary.best_effort_cleanup)
        self.store=Store(self.data/'workbench-sidecar.sqlite3');self.catalog=example_catalog()
        self.session={'id':'session1','catalog':self.catalog,'decisions':{'pair':{'action':'merge'}},'relocations':{'a':'new-path'}}
        self.jobs={}
        def launch(work,message):
            identity='job-'+str(len(self.jobs))
            try:
                with self.temporary.operation():result=work(lambda *_:None)
                self.jobs[identity]={'id':identity,'status':'complete','result':result}
            except Exception as error:
                self.jobs[identity]={'id':identity,'status':'error','message':str(error)}
            return identity
        for name,value in (('DATA',self.data),('TEMPORARY',self.temporary),('launch',launch),('tasks',self.jobs),
                           ('sessions',{'session1':self.session}),('active','session1')):
            patcher=patch.object(application,name,value);patcher.start();self.addCleanup(patcher.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def generate(self,values):
        response=self.client.post('/api/quick-export',json=values,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        state=self.jobs[response.json['job']];self.assertEqual(state['status'],'complete',state)
        record=state['result']
        with zipfile.ZipFile(Path(record['directory'])/'metadata-explorer.zip') as archive:
            raw=archive.read('library-data.js').decode('utf-8')
        return record,json.loads(raw.removeprefix('window.METADATA_SNAPSHOT=').removesuffix(';'))

    def preview(self,values):
        response=self.client.post('/api/quick-export/preview',json=values,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json);return response.json

    def test_default_api_remains_private_and_staged_cleanup_is_not_silently_applied(self):
        before=deepcopy(self.catalog.tracks);decisions=deepcopy(self.session['decisions'])
        preview=self.preview({'source':'session'});record,data=self.generate({'source':'session'})
        self.assertEqual(data['preset'],'private');self.assertEqual(data['columns'],list(FIELDS))
        self.assertEqual(preview['fields'],data['columns']);self.assertEqual(preview['track_count'],data['track_count'])
        self.assertEqual(data['data_state'],'captured');self.assertFalse(record['staged_changes_applied'])
        self.assertEqual(self.catalog.tracks,before);self.assertEqual(self.session['decisions'],decisions)
        self.assertNotIn('current_path',data['columns'])

    def test_captured_and_working_state_use_the_same_source_for_preview_and_generation(self):
        self.store.save_override('session:session1','a','genre','Techno','House')
        for working,expected in ((False,'House'),(True,'Techno')):
            choices={'source':'session','preset':'private','fields':['genre'],'working':working}
            preview=self.preview(choices);record,data=self.generate(choices)
            self.assertEqual(data['rows'][0],[expected]);self.assertEqual(data['columns'],preview['fields'])
            self.assertEqual(data['data_state'],'working' if working else 'captured')
            self.assertEqual(preview['data_state'],data['data_state'])
            self.assertEqual(record['metadata_overrides_applied'],int(working))
        self.assertEqual(self.catalog.tracks['a']['genre'],'House')

    def test_old_analyzer_metadata_gets_consistent_scope_for_working_overrides(self):
        source='a'*32;folder=self.data/'analyzers'/source;folder.mkdir(parents=True)
        snapshot=capture_catalog(self.catalog)
        self.assertNotIn('scope_key',snapshot)
        (folder/'metadata.json').write_text(json.dumps(snapshot),encoding='utf-8')
        self.store.save_override('capture:'+source,'a','genre','Techno','House')
        choices={'source':source,'preset':'private','fields':['genre'],'working':True}
        preview=self.preview(choices);record,data=self.generate(choices)
        self.assertEqual(data['rows'][0],['Techno']);self.assertEqual(preview['metadata_overrides_applied'],1)
        self.assertEqual(record['data_state'],'working')
        self.assertNotIn('scope_key',json.loads((folder/'metadata.json').read_text()))

    def test_saved_lab_source_and_selected_allowlist_do_not_disclose_other_fields(self):
        snapshot=capture_catalog(self.catalog);snapshot['scope_key']='saved'
        identity=self.store.save_snapshot(snapshot,'Saved')['id']
        choices={'source':'lab:'+identity,'preset':'selected','track_ids':['a'],'fields':['artist','year']}
        preview=self.preview(choices);record,data=self.generate(choices)
        self.assertEqual(preview['fields'],['artist','year']);self.assertEqual(data['columns'],['artist','year'])
        self.assertEqual(data['rows'],[['Artist & friend',2020]]);self.assertEqual(record['tracks'],1)
        encoded=json.dumps(data)
        for private in ('private-name','My playlist','</script>','current_path','last_played'):
            if private not in data['disclosure']['omitted']:self.assertNotIn(private,encoded)
        public_preview=self.preview({'source':'lab:'+identity,'preset':'public','include_paths':True})
        _,public=self.generate({'source':'lab:'+identity,'preset':'public','include_paths':True})
        self.assertTrue(public_preview['aggregates_only']);self.assertEqual(public['rows'],[])
        self.assertFalse(public['includes_paths']);self.assertNotIn('private-name',json.dumps(public))

    def test_missing_malformed_and_path_sources_fail_without_publication(self):
        for values in ([],None,{'source':None},{'source':'../../private.xml'},{'source':'f'*32},
                       {'source':'lab:missing'},{'source':'session','scope':'invalid'},
                       {'source':'session','fields':['password']},{'source':'session','fields':[]}):
            response=self.client.post('/api/quick-export/preview',json=values,headers=self.headers)
            self.assertEqual(response.status_code,400,values)
        source='b'*32;folder=self.data/'analyzers'/source;folder.mkdir(parents=True)
        for malformed in ('not JSON','[]','{"tracks":[null]}','{"tracks":[{"id":"one","playlists":null}]}'):
            (folder/'metadata.json').write_text(malformed,encoding='utf-8')
            self.assertEqual(self.client.post('/api/quick-export/preview',json={'source':source},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/quick-export/preview',json={}).status_code,403)
        response=self.client.post('/api/quick-export',json={'source':'session','fields':['password']},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(self.jobs[response.json['job']]['status'],'error')
        self.assertEqual(list((self.data/'quick-exports').glob('*/export.json')),[])

    def test_xml_only_upload_copies_bytes_temporarily_and_keeps_original_untouched(self):
        original=self.root/'original.xml';original.write_bytes(XML);before=sha256(XML).hexdigest()
        response=self.client.put('/api/quick-export/xml',data=original.read_bytes(),content_type='application/xml',headers=self.headers)
        self.assertEqual(response.status_code,200);identity=response.json['source']
        self.assertEqual(self.jobs[response.json['job']]['status'],'complete')
        copy=self.temporary.path/'xml-summaries'/identity/'collection.xml'
        self.assertEqual(copy.read_bytes(),XML);self.assertNotEqual(copy,original)
        self.assertEqual(list(copy.parent.glob('*.part')),[])
        preview=self.preview({'source':identity,'preset':'public'})
        self.assertEqual(preview['track_count'],1);record,data=self.generate({'source':identity,'preset':'public'})
        self.assertEqual(record['tracks'],1);self.assertEqual(data['rows'],[])
        self.assertNotIn('private-name',json.dumps(data));self.assertNotIn('Private set',json.dumps(data))
        self.temporary.cleanup()
        self.assertFalse(copy.exists());self.assertTrue(original.exists())
        self.assertEqual(sha256(original.read_bytes()).hexdigest(),before)
        self.assertTrue((Path(record['directory'])/'library.html').is_file())
        self.assertTrue((self.data/'analyzers'/identity/'report.json').is_file())

    def test_empty_malformed_and_entity_xml_do_not_create_usable_metadata(self):
        self.assertEqual(self.client.put('/api/quick-export/xml',data=XML,headers={}).status_code,403)
        response=self.client.put('/api/quick-export/xml',data=b'',headers=self.headers)
        self.assertEqual(response.status_code,400);self.assertIn('empty',response.json['error'])
        for content in (b'<broken',b'<not-rekordbox/>',b'<DJ_PLAYLISTS><COLLECTION Entries="0"/></DJ_PLAYLISTS>',
                        b'<!DOCTYPE x [<!ENTITY e "private">]><DJ_PLAYLISTS>&e;</DJ_PLAYLISTS>'):
            response=self.client.put('/api/quick-export/xml',data=content,headers=self.headers)
            self.assertEqual(response.status_code,200)
            self.assertEqual(self.jobs[response.json['job']]['status'],'error')
            folder=self.data/'analyzers'/response.json['source']
            self.assertFalse((folder/'metadata.json').exists());self.assertFalse((folder/'report.json').exists())
        self.assertEqual(list(self.temporary.path.rglob('*.part')),[])


if __name__=='__main__':unittest.main()

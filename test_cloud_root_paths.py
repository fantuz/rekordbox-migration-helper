"""Cloud-relative and old-user references through real attachment/check routes."""
from copy import deepcopy
from pathlib import Path
import json
import os
import unittest
from unittest.mock import patch

from cloud_candidates import suggestions
import dropbox_files
from workbench_store import Store


class CloudRootPathTests(unittest.TestCase):
    def setUp(self):
        from test_cloud_connection_workflows import CloudConnectionWorkflowTests
        self.fixture=CloudConnectionWorkflowTests('test_both_selected_cache_attachments_preserve_sources_and_detach_independently')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        # Use genuine temporary folders and provider configuration for the
        # NEW user's destination; only the captured OLD reference is virtual.
        f.dropbox=f.root/'Users'/'NEW'/'Cloud Option DJ team Dropbox';f.dropbox.mkdir(parents=True)
        config=Path(os.environ['APPDATA'])/'Dropbox'/'info.json'
        config.write_text(json.dumps({'business':{'path':str(f.dropbox)}}))
        self.member=f.dropbox/'Invented member';self.member.mkdir()
        self.contents_id='contents_invented_123'
        self.contents=self.member/'rekordbox'/self.contents_id;(self.contents/'Collection').mkdir(parents=True)
        self.tail='electrobuzz_2026/Invented album/03 - Normal Song.mp3'
        self.old='C:/Users/OLD/Cloud Option DJ team Dropbox/Invented member'
        tracks=[{'id':'normal','title':'Invented normal song','current_path':'/'+self.tail,
                 'original_path':self.old+'/'+self.tail},
                {'id':'contents','title':'Invented cloud storage song',
                 'current_path':'/'+self.contents_id+'/Collection/Cloud Song.mp3',
                 'original_path':'E:/Unrelated metadata/._Earlier Song.mp3'},
                {'id':'unknown','title':'Unknown old file','current_path':'Z:/Elsewhere/Unknown.mp3',
                 'original_path':'E:/Unrelated metadata/Other.mp3'}]
        saved=f.store.save_snapshot({'scope_key':'synthetic:cloud-root-prefixes','tracks':tracks,'playlists':[]},'Invented cloud roots')
        f.sid=saved['id'];f.source='snapshot:'+f.sid;f.before=deepcopy(f.store.snapshot(f.sid))
        seed=deepcopy(f.providers['dropbox'].entries[0]);f.providers['dropbox'].entries=[]
        for identity,path in [('normal','/'+self.tail),('contents','/rekordbox/'+self.contents_id+'/Collection/Cloud Song.mp3')]:
            f.providers['dropbox'].entries.append({**seed,'id':'id:'+identity,'name':path.rsplit('/',1)[-1],
                'path_display':path,'path_lower':path.lower()})

    def attach(self,prefix):
        f=self.fixture;value=f.values('dropbox',local_root=str(self.member),recorded_root=prefix,remote_root='')
        preview=f.poll(f.post('cloud-setup/preview',value))
        self.assertTrue(preview['attachable'],preview)
        attached=f.post('cloud-setup/attach',{'preview_token':preview['preview_token'],'confirm':True})
        self.assertEqual(attached.status_code,200,attached.json)
        f.poll(f.post('dropbox/check',{'source':f.source}))
        response=f.client.get('/api/dropbox/files',query_string={'source':f.source})
        self.assertEqual(response.status_code,200,response.json)
        return preview,response.json

    def test_old_windows_and_mac_prefixes_survive_real_http_attach_to_current_native_folder(self):
        f=self.fixture
        for index,old in enumerate(('C:/Users/OLD/Cloud Option DJ team Dropbox/Invented member',
                                    '/Users/OLD/Dropbox/Invented member',
                                    '/Users/OLD/Library/CloudStorage/Dropbox-Team/Invented member')):
            with self.subTest(recorded_prefix=old):
                source=deepcopy(f.before);source['scope_key']='synthetic:cross-computer-prefix-'+str(index)
                next(track for track in source['tracks'] if track['id']=='normal')['original_path']=old+'/'+self.tail
                saved=f.store.save_snapshot(source,'Invented cross-computer paths '+str(index))
                f.sid=saved['id'];f.source='snapshot:'+f.sid;f.before=deepcopy(f.store.snapshot(f.sid))
                status=f.client.get('/api/cloud-setup/status',query_string={'source':f.source})
                self.assertEqual(status.status_code,200,status.json)
                candidates=status.json['source']['suggestions']
                expected=next(row for row in candidates if row['evidence']=='correlated_cloud_paths' and row['recorded_root'].replace('\\','/')==old)
                self.assertEqual(expected['tracks'],1);self.assertEqual(expected['kind'],'dropbox')
                self.assertIn('original_path',expected['reference_fields']);self.assertIn('current_path',expected['reference_fields'])
                preview,result=self.attach(expected['recorded_root'])
                self.assertEqual(preview['matched'],1)
                rows={row['track_id']:row for row in result['rows']}
                self.assertEqual(rows['normal']['status'],'present');self.assertEqual(rows['normal']['remote_path'],'/'+self.tail)
                self.assertEqual(rows['normal']['reference_field'],'original_path')
                self.assertEqual(rows['normal']['local_path'],str(self.member.joinpath(*self.tail.split('/'))))
                self.assertEqual(rows['contents']['status'],'unmapped');self.assertEqual(rows['unknown']['status'],'unmapped')
                self.assertEqual(f.store.snapshot(f.sid),f.before)
                self.assertEqual(next(track for track in f.before['tracks'] if track['id']=='normal')['original_path'],old+'/'+self.tail)
                self.assertTrue(all(not provider.downloads for provider in f.providers.values()))
                self.assertEqual(list(self.member.rglob('*.mp3')),[])

    def test_common_member_root_and_explicit_longer_contents_alias_cover_both_after_attach(self):
        f=self.fixture
        # The actual contents location is chosen explicitly. It is not inferred
        # from a name or forced as the whole provider's attachment root.
        response=f.client.get('/api/audio-paths',query_string={'source':f.source})
        self.assertEqual(response.status_code,200,response.json)
        saved=f.post('audio-paths',{'source':f.source,'revision':response.json['revision'],
            'mappings':[{'recorded_root':'/'+self.contents_id,'local_root':str(self.contents)}]})
        self.assertEqual(saved.status_code,200,saved.json)
        original_open=Path.open
        def no_audio(path,*args,**kwargs):
            if path.suffix.lower() in ('.mp3','.flac','.wav'):raise AssertionError('Audio opened during metadata preview')
            return original_open(path,*args,**kwargs)
        with patch.object(Path,'open',no_audio):preview,result=self.attach('/')
        self.assertEqual(preview['matched'],2)
        rows={row['track_id']:row for row in result['rows']}
        self.assertEqual(rows['normal']['status'],'present');self.assertEqual(rows['normal']['remote_path'],'/'+self.tail)
        self.assertEqual(rows['contents']['status'],'present')
        self.assertEqual(rows['contents']['remote_path'],'/rekordbox/'+self.contents_id+'/Collection/Cloud Song.mp3')
        self.assertEqual(rows['contents']['local_path'],str(self.contents/'Collection'/'Cloud Song.mp3'))
        self.assertEqual(rows['unknown']['status'],'unmapped')
        attachment=f.store.setting('dropbox_mapping')
        self.assertEqual(attachment['local_root'],str(self.member));self.assertEqual(attachment['recorded_root'],'/')
        aliases=f.store.setting('audio_paths:'+f.before['scope_key'])
        self.assertEqual({row['recorded_root'] for row in aliases},{'/', '/'+self.contents_id})
        # An active alias whose volume identity changed must not silently fall
        # back to the root-relative reference or the old original path.
        broken=deepcopy(aliases)
        next(row for row in broken if row['recorded_root']=='/')['inode']+=1
        normal=next(track for track in f.before['tracks'] if track['id']=='normal')
        self.assertIsNone(dropbox_files.target(normal,attachment,broken))
        self.assertEqual(f.store.snapshot(f.sid),f.before)
        self.assertTrue(all(not provider.downloads for provider in f.providers.values()))
        self.assertEqual(list(self.member.rglob('*.mp3')),[])

    def test_both_computer_directions_project_only_explicit_old_prefixes(self):
        tail='electrobuzz_2026/Invented album/Track.mp3'
        cases=[('C:/Users/OLD/Dropbox/Invented member','/Users/NEW/Library/CloudStorage/Dropbox-Team/Invented member'),
               ('/Users/OLD/Dropbox/Invented member','C:/Users/NEW/Dropbox/Invented member'),
               ('/Users/OLD/Library/CloudStorage/Dropbox-Team/Invented member','C:/Users/NEW/Dropbox/Invented member')]
        for old,new in cases:
            with self.subTest(old=old,new=new):
                track={'current_path':'/'+tail,'original_path':old+'/'+tail};before=deepcopy(track)
                mapping={'provider':'dropbox','local_root':new,'remote_root':'/Music'}
                self.assertIsNone(dropbox_files.target(track,mapping))
                target=dropbox_files.target(track,{**mapping,'recorded_root':old})
                self.assertEqual(target['remote_path'],'/Music/'+tail)
                self.assertEqual(target['local_path'].replace('\\','/'),new+'/'+tail)
                self.assertEqual(target['recorded_path'],old+'/'+tail)
                self.assertEqual(track,before)
                unrelated={'current_path':'Z:/Unknown/Track.mp3','original_path':'/Users/OTHER/Unrelated/Track.mp3'}
                self.assertIsNone(dropbox_files.target(unrelated,{**mapping,'recorded_root':old}))

    def test_root_relative_windows_destination_requires_explicit_recorded_prefix(self):
        track={'current_path':'/electrobuzz_2026/Album/Track.mp3','original_path':'E:/Unknown/Other.mp3'}
        mapping={'local_root':'C:/Users/NEW/Dropbox/Member','remote_root':'','provider':'dropbox'}
        self.assertIsNone(dropbox_files.target(track,mapping))
        target=dropbox_files.target(track,{**mapping,'recorded_root':'/'})
        self.assertEqual(target['remote_path'],'/electrobuzz_2026/Album/Track.mp3')
        self.assertEqual(target['local_path'],r'C:\Users\NEW\Dropbox\Member\electrobuzz_2026\Album\Track.mp3')
        self.assertIsNone(dropbox_files.target({'current_path':'E:/Unknown/Other.mp3'},dict(mapping,recorded_root='/')))
        self.assertIsNone(dropbox_files.target({'current_path':'/contents_id/safe:stream.mp3'},dict(mapping,recorded_root='/')))


if __name__=='__main__':unittest.main()

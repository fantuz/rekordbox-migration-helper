"""Synthetic recovery evidence, stale-candidate guards and reversible staging."""
from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import app as application
from media_recovery import scan, stage_candidate, recovery_report


def tagged_wave(path, title='Test song', artist='Test artist', seconds=3):
    stream=BytesIO()
    with wave.open(stream,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000)
        audio.writeframes(b'\0\0' * (8000*seconds))
    info=b'INFO'
    for key,text in ((b'INAM',title),(b'IART',artist)):
        value=text.encode()+b'\0'
        info+=key+struct.pack('<I',len(value))+value+b'\0'*(len(value)%2)
    content=stream.getvalue()+b'LIST'+struct.pack('<I',len(info))+info
    path.write_bytes(content[:4]+struct.pack('<I',len(content)-8)+content[8:])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.music=self.root/'music';self.music.mkdir()
        self.audio=self.music/'Renamed.wav';tagged_wave(self.audio)
        self.track={'track_id':'a','title':'Test song','artist':'Test artist',
                    'current_path':str(self.root/'Lost.wav'),'size_bytes':10,
                    'duration_seconds':3,'playlist_ids':['saved-playlist']}

    def scan(self,**extra):
        return scan({'a':self.track},[{'root':str(self.music),**extra}],lambda *_:None)

    def test_renamed_file_uses_real_tags_and_duration_without_size_agreement(self):
        before=self.audio.read_bytes();result=self.scan();match=result['matches']['a']
        self.assertTrue(result['complete']);self.assertEqual(match['status'],'found')
        self.assertEqual(match['evidence'],'tags_and_duration')
        self.assertEqual(stage_candidate(result,match),self.audio.as_uri())
        self.assertEqual(before,self.audio.read_bytes())
        self.assertEqual(self.track['current_path'],str(self.root/'Lost.wav'))

    def test_version_words_and_duration_remain_distinct(self):
        self.track['title']='Test song (Dub)'
        self.assertEqual(self.scan()['matches']['a']['status'],'not_found')
        self.track['title']='Test song';self.track['duration_seconds']=12
        self.assertEqual(self.scan()['matches']['a']['status'],'not_found')

    def test_filename_size_match_with_conflicting_tags_needs_review(self):
        self.track.update(current_path=str(self.root/'Renamed.wav'),size_bytes=self.audio.stat().st_size,title='Test song (Dub)')
        result=self.scan();match=result['matches']['a']
        self.assertEqual(match['status'],'review')
        self.assertIn('title',match['candidates'][0]['metadata_conflicts'])
        with self.assertRaises(ValueError):stage_candidate(result,match)

    def test_multiple_candidates_and_unknown_size_do_not_create_a_unique_match(self):
        tagged_wave(self.music/'Another.wav')
        result=self.scan();match=result['matches']['a']
        self.assertEqual(match['status'],'ambiguous');self.assertEqual(match['candidate_count'],2)
        with self.assertRaises(ValueError):stage_candidate(result,match)
        self.track.update(title='',artist='',size_bytes=0)
        self.assertEqual(self.scan()['matches']['a']['status'],'not_found')

    def test_unavailable_root_and_failed_tags_hold_other_suggestions_for_review(self):
        result=scan({'a':self.track},[{'root':str(self.music)},{'root':str(self.root/'offline')}],lambda *_:None)
        self.assertFalse(result['complete']);self.assertEqual(result['matches']['a']['status'],'review')
        (self.music/'Broken.mp3').write_bytes(b'not audio')
        self.assertEqual(self.scan()['matches']['a']['status'],'review')

    def test_available_recorded_file_is_not_classified_as_unresolved(self):
        self.track['current_path']=str(self.audio)
        self.assertEqual(self.scan()['matches']['a']['status'],'available')

    def test_overlap_is_deduplicated_and_conflicting_destinations_are_held(self):
        mappings=[{'root':str(self.music)},{'root':str(self.music)}]
        result=scan({'a':self.track},mappings,lambda *_:None)
        self.assertEqual(result['matches']['a']['candidate_count'],1)
        mappings[1]['export_uri']='file://localhost/D:/Elsewhere'
        result=scan({'a':self.track},mappings,lambda *_:None)
        self.assertEqual(result['matches']['a']['status'],'review')

    def test_limits_and_missing_roots_do_not_claim_absence(self):
        self.track['title']='Other'
        with patch('media_recovery.MAX_FILES',0):
            result=self.scan()
        self.assertFalse(result['complete']);self.assertEqual(result['matches']['a']['status'],'unverified')
        with self.assertRaises(ValueError):scan({'a':self.track},[{'root':'.'}],lambda *_:None)

    def test_cloud_audio_is_not_read_or_staged(self):
        from media import file_record
        def placeholder(path):return {**file_record(path),'cloud_only':True}
        self.track.update(current_path=str(self.root/self.audio.name),size_bytes=self.audio.stat().st_size)
        with patch('media_recovery.file_record',side_effect=placeholder),patch('media_recovery.read_tags') as reader:
            result=self.scan()
        reader.assert_not_called();self.assertEqual(result['matches']['a']['status'],'cloud_only')

    def test_staging_rejects_changed_disappeared_and_linked_files(self):
        result=self.scan();match=result['matches']['a']
        with patch('media_recovery.ordinary_path',return_value=False):
            with self.assertRaises(ValueError):stage_candidate(result,match)
        self.audio.write_bytes(b'changed')
        with self.assertRaises(ValueError):stage_candidate(result,match)
        self.audio.unlink()
        with self.assertRaises(ValueError):stage_candidate(result,match)

    def test_api_stages_undoes_reports_and_rejects_stale_or_remote_requests(self):
        inventory=self.scan()
        session={'id':'test','catalog':SimpleNamespace(tracks={'a':self.track}),
                 'inventory':inventory,'relocations':{},'metadata':{}}
        client=application.app.test_client();headers={'X-Workbench-Token':application.TOKEN}
        body={'track_id':'a','workspace':'test','scan_id':inventory['scan_id']}
        with patch.object(application,'current',return_value=session),patch.object(application,'log'),patch.object(application,'summary',return_value={'id':'test'}):
            endpoint='/api/inventory/stage'
            for invalid in ({**body,'workspace':'other'},{**body,'scan_id':'stale'}):
                self.assertEqual(client.post(endpoint,json=invalid,headers=headers).status_code,400)
            self.assertEqual(client.post(endpoint,json=body,headers=headers,environ_overrides={'REMOTE_ADDR':'8.8.8.8'}).status_code,400)
            self.assertEqual(client.post(endpoint,json=body,headers=headers).status_code,200)
            self.assertEqual(session['relocations'],{'a':self.audio.as_uri()})
            payload=client.get('/api/inventory/report').json
            self.assertEqual(payload['tracks'][0]['metadata']['playlist_ids'],['saved-playlist'])
            self.assertEqual(payload['library_entries_removed'],0)
            self.assertEqual(client.get('/api/inventory?status=unresolved').json['total'],0)
            self.assertEqual(client.post(endpoint,json={**body,'undo':True},headers=headers).status_code,200)
            self.assertEqual(session['relocations'],{})
        self.assertFalse(recovery_report(session)['audio_files_modified'])


if __name__=='__main__':unittest.main()

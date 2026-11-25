import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cleanup_review import build_report
from research_capture import capture_private_database
from xml_analysis import analyze_xml


class Inspector:
    host = 'Windows'
    can_apply = True

    def __init__(self):
        self.facts = {}
        self.hashes = []
        self.probes = []

    def inspect(self, path, *, cloud_hint=False):
        self.probes.append(path)
        status, inode, size = self.facts[path]
        return dict(status='cloud' if cloud_hint else status, os=self.host, volume='C:',
                    identity=[1,inode] if status == 'present' else None, size=size, stamp=[1,inode,size,100,100])

    def digest(self, path, finding, budget, progress=None):
        self.hashes.append(path)
        if progress: progress(finding['size'])
        return 'a'*64, finding['size']


def track(identity, **changes):
    return {'id':identity, 'current_path':'C:/Users/DJ/Music/'+identity+'/Tune.wav',
            'title':'Tune','size':1024,'rating':0,'cues':[], **changes}


def collection(*tracks):
    return {'cleanup_coverage':{'version':1,'scope':'xml','complete':True},'tracks':list(tracks)}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.fs = Inspector()
        self.tracks = [track(i) for i in ['b','a','c','d']]
        for i, row in enumerate(self.tracks):
            self.fs.facts[row['current_path']] = ('present',i+1,1024)
        self.snapshot = collection(*self.tracks)

    def review(self,**opts):
        return build_report(self.snapshot,inspector=self.fs,**opts)

    def test_distinct_rows_need_complete_digest_and_same_catalog_metadata(self):
        self.tracks[2]['artist'] = 'Other artist'
        self.tracks[3]['rating'] = 3
        report = self.review()
        self.assertEqual(self.fs.hashes,[])
        self.assertEqual(report['counts']['eligible'],0)
        report = self.review(compare_bytes=True)
        rows = {r['id']:r for r in report['rows']}
        self.assertEqual((rows['b']['candidate'],rows['b']['keeper_id'],rows['b']['proof']),('duplicate','a','sha256'))
        self.assertIn('distinct_metadata',rows['c']['signals'])
        self.assertIn('rating',rows['d']['reasons'])
        self.assertEqual(report['signals']['same_name_size'],4)
        self.assertNotIn(self.tracks[3]['current_path'],self.fs.hashes)
        self.assertEqual(report['hash_bytes'],3072)
        self.fs.hashes.clear(); self.fs.probes.clear()
        subset = self.review(compare_bytes=True,scope_ids={'a','b'})
        self.assertEqual({r['id'] for r in subset['rows']},{'a','b'})
        self.assertEqual(set(self.fs.probes),{self.tracks[i]['current_path'] for i in (0,1)})
        for r in subset['rows']:
            self.assertEqual(r['evidence'],rows[r['id']]['evidence'])
        with self.assertRaises(ValueError): self.review(scope_ids={'no-longer-there'})

    def test_no_bytes_needed_for_alias_but_name_size_and_budget_are_insufficient(self):
        self.fs.facts[self.tracks[0]['current_path']] = ('present',2,1024)
        self.assertEqual(self.review()['rows'][0]['proof'],'same_file')
        with patch('cleanup_review.HASH_BUDGET',1024):
            report = self.review(compare_bytes=True)
        self.assertEqual((report['hash_bytes'],report['hash_skipped']),(1024,3))
        self.assertEqual(report['counts']['duplicate'],0)
        self.assertFalse(report['rows'][2]['candidate'])

    def test_alias_proof_is_stable_when_scoped_recheck_can_hash_more_files(self):
        self.fs.facts[self.tracks[2]['current_path']] = ('present',10,1024)
        self.fs.facts[self.tracks[3]['current_path']] = ('present',10,1024)
        with patch('cleanup_review.HASH_BUDGET',2048):
            report = self.review(compare_bytes=True)
            subset = self.review(compare_bytes=True,scope_ids={'c','d'})
        self.assertEqual(report['rows'][3]['proof'],'same_file')
        for full, fresh in zip(report['rows'][2:], subset['rows']):
            self.assertEqual((full['keeper_id'],full['evidence']), (fresh['keeper_id'],fresh['evidence']))

    def test_cloud_alternate_unknown_size_pruned_history_and_working_edits_keep_missing_rows(self):
        for i, row in enumerate(self.tracks): self.fs.facts[row['current_path']] = ('missing',i+10,None)
        self.tracks[1]['original_path'] = 'D:/old/Tune.wav'
        self.fs.facts[self.tracks[1]['original_path']] = ('external',22,None)
        self.snapshot['histories'] = [{'entries':[{'track_id':'d'}]}]
        report = self.review(protected_ids={'c':{'keep_separate','metadata_edit'}},cloud_ids={'d'})
        a,b,c,d = report['rows']
        self.assertEqual(a['candidate'],'missing')
        self.assertIn('alternate_reference',b['reasons'])
        self.assertTrue(set(c['reasons']) >= {'metadata_edit','keep_separate'})
        self.assertTrue(set(d['reasons']) >= {'play_history','cloud_reference'})
        self.assertEqual(report['volumes'][0]['eligible'],1)
        self.tracks[0]['size'] = None
        self.assertIn('unknown_metadata',self.review()['rows'][0]['reasons'])

    def test_incomplete_or_migrated_sources_linux_and_unsaved_inputs_are_read_only(self):
        self.snapshot.pop('cleanup_coverage')
        self.assertEqual(self.review(compare_bytes=True)['gates'],['incomplete_capture'])
        self.snapshot['cleanup_coverage'] = {'version':1,'complete':True,'scope':'xml'}
        self.snapshot['cleanup_lineage'] = {'parent_snapshot_id':'p'}
        self.assertEqual(self.review(compare_bytes=True)['parent_snapshot_id'],'p')
        self.snapshot.pop('cleanup_lineage')
        self.assertIn('save_snapshot',self.review(compare_bytes=True,review_only=True)['gates'])
        self.fs.can_apply=False; self.fs.host='Unclassified'
        self.assertIn('host_review_only',self.review(compare_bytes=True)['gates'])
        self.assertFalse(self.fs.hashes)

    def test_incomplete_xml_links_block_entire_capture_and_unshown_fields_keep_separate_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'source.xml'
            tracks = ''.join(f'<TRACK TrackID="{t["id"]}" Name="Tune" Size="1024" Location="{t["current_path"]}" Mix="{i}"/>'
                             for i,t in enumerate(self.tracks))
            doc = '<DJ_PLAYLISTS><COLLECTION>'+tracks+'</COLLECTION><PLAYLISTS>{}</PLAYLISTS></DJ_PLAYLISTS>'
            for playlist, complete in [('',True),('<NODE Type="1"><TRACK Key="absent"/></NODE>',False)]:
                source.write_text(doc.format(playlist)); analyze_xml(source,root/'out',lambda *_:None)
                snapshot=json.loads((root/'out'/'comparison.json').read_text())
                self.assertEqual(snapshot['cleanup_coverage']['complete'],complete)
                report=build_report(snapshot,inspector=self.fs,compare_bytes=True)
                self.assertEqual(report['counts']['eligible'],0)
                self.assertEqual(report['signals'].get('distinct_metadata',0),4 if complete else 0)

    def test_native_capture_resolves_both_bank_paths_and_serialized_cues(self):
        db=sqlite3.connect(':memory:'); self.addCleanup(db.close)
        db.executescript('''CREATE TABLE djmdContent(ID,Title,FolderPath,OrgFolderPath,FileSize,ServiceID,DJPlayCount,Commnt,Rating,Analysed,CloudID,AnalysisDataPath);
        INSERT INTO djmdContent VALUES('a','Tune','C:/Users/DJ/Music/a/Tune.wav','',1024,0,0,'',0,0,NULL,NULL),
          ('b','Tune','C:/Users/DJ/Music/b/Tune.wav','',1024,0,0,'',0,0,NULL,NULL),
          ('c','Tune','C:/Users/DJ/Music/c/Tune.wav','',1024,0,0,'',0,0,'provider-ref',NULL),
          ('d','Tune','C:/Users/DJ/Music/d/Tune.wav','',1024,0,0,'',0,0,NULL,NULL);
        CREATE TABLE djmdCue(ID,ContentID,Kind,InMsec,Comment);
        CREATE TABLE djmdPlaylist(ID,Name); CREATE TABLE djmdSongPlaylist(PlaylistID,ContentID);
        CREATE TABLE djmdHistory(ID,DateCreated); CREATE TABLE djmdSongHistory(HistoryID,ContentID);
        CREATE TABLE contentFile(ContentID,Path);
        CREATE TABLE contentCue(ContentID,Cues); INSERT INTO contentCue VALUES('b','[{"ID":"cue-b"}]');
        CREATE TABLE hotCueBanklistCue(Cues); INSERT INTO hotCueBanklistCue VALUES('[{"CueID":"cue-b"}]');
        CREATE TABLE djmdSongHotCueBanklist(ContentID,CueID); INSERT INTO djmdSongHotCueBanklist VALUES('a',NULL);
        CREATE TABLE djmdRelatedTracks(ContentID1,ContentID2);
        ''')
        snapshot=capture_private_database(db,'capture:synthetic')
        self.assertTrue(snapshot['cleanup_coverage']['complete'])
        self.assertEqual({t['id']:set(t.get('cleanup_links',())) for t in snapshot['tracks']},
                         {'a':{'hot_cue_bank'},'b':{'hot_cue_bank','cues'},'c':{'cloud_reference'},'d':set()})
        self.fs.facts[self.tracks[3]['current_path']] = ('missing',4,None)
        report=build_report(snapshot,inspector=self.fs)
        self.assertEqual([r['id'] for r in report['rows'] if r['candidate']], ['d'])
        for raw in ('no json','[{"CueID":"dangling"}]','[{"ContentID":"a","ContentID":"b"}]','[{"ContentID":[]}]'):
            db.execute('PRAGMA query_only=OFF'); db.execute('UPDATE hotCueBanklistCue SET Cues=?',(raw,))
            self.assertFalse(capture_private_database(db,'capture:synthetic')['cleanup_coverage']['complete'])
        db.execute('PRAGMA query_only=OFF')
        db.execute("DELETE FROM hotCueBanklistCue")
        db.execute("INSERT INTO contentFile VALUES(NULL,'/WAVEFORM')")
        db.execute("INSERT INTO djmdPlaylist VALUES('p','Unknown type')")
        coverage = capture_private_database(db,'capture:synthetic')['cleanup_coverage']
        self.assertEqual(coverage['gaps'], ['smart_membership', 'unresolved_native_links'])
        db.execute('PRAGMA query_only=OFF')
        db.execute('ALTER TABLE contentFile RENAME COLUMN ContentID TO Other')
        db.execute("ALTER TABLE djmdPlaylist ADD COLUMN Attribute")
        db.execute("UPDATE djmdPlaylist SET Attribute=4")
        coverage = capture_private_database(db,'capture:synthetic')['cleanup_coverage']
        self.assertEqual(coverage['gaps'], ['smart_membership', 'unresolved_native_links'])

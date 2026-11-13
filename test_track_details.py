"""Track-comment staging and saved colour/key evidence; synthetic data only."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
from hashlib import sha256
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as application
from dj_insights import InsightIndex,tonalities,bubbles,ranking
from metadata_export import capture_database,payload,track
from metadata_overrides import validate,plan
from track_tags import native_colour,xml_colour,rgb
from workbench_store import Store


class SavedTagTests(unittest.TestCase):
    def test_chart_bundle_has_pinned_integrity_and_its_license_is_packaged(self):
        assets=Path(__file__).parent/'static';provenance=json.loads((assets/'d3-hierarchy-provenance.json').read_text())
        self.assertEqual(provenance['version'],'3.1.2');self.assertEqual(provenance['license'],'ISC')
        self.assertEqual(sha256((assets/'d3-hierarchy-3.1.2.min.js').read_bytes()).hexdigest(),provenance['vendored_sha256'])
        self.assertIn('Mike Bostock',(assets/'d3-hierarchy-LICENSE.txt').read_text())

    def test_native_palette_inference_is_labeled_and_unassigned_differs_from_unknown(self):
        c=native_colour('id1',{'SortKey':2,'ColorCode':None,'Commnt':'Peak time'})
        self.assertEqual(c['color_status'],'assigned');self.assertEqual(c['color_hex'],'#FF0000');self.assertEqual(c['color_name'],'Peak time')
        self.assertIn('inferred',c['color_basis'])
        self.assertEqual(native_colour(None)['color_status'],'unassigned')
        self.assertEqual(native_colour(None,available=False)['color_status'],'unknown')
        self.assertIsNone(native_colour('unrecognized')['color_hex'])
        self.assertIsNone(rgb('red;url(javascript:x)'))

    def test_xml_rgb_is_evidence_without_inventing_a_set_role(self):
        c=xml_colour('0xFF007F');self.assertEqual(c['color_hex'],'#FF007F');self.assertEqual(c['color_name'],'Pink')
        self.assertNotIn('opener',json.dumps(c).casefold())
        self.assertEqual(xml_colour(None)['color_status'],'unknown');self.assertEqual(xml_colour('')['color_status'],'unassigned')
        self.assertEqual(xml_colour('invalid')['color_status'],'unknown')

    def test_native_capture_reads_comment_key_and_color_without_source_writes(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.executescript('''
                CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT,Commnt TEXT,KeyID TEXT,ColorID TEXT);
                CREATE TABLE djmdKey(ID TEXT,ScaleName TEXT);
                CREATE TABLE djmdColor(ID TEXT,ColorCode INTEGER,SortKey INTEGER,Commnt TEXT);
                INSERT INTO djmdKey VALUES('key','F#m');
                INSERT INTO djmdColor VALUES('c',NULL,5,'Warm up');
                INSERT INTO djmdContent VALUES('t','Track','/not-read.mp3','First line\nSecond line','key','c');
            ''')
            columns={name:{r[1] for r in db.execute('PRAGMA table_info('+name+')')} for name in ('djmdContent','djmdKey','djmdColor')}
            before=db.total_changes;s=capture_database(db,columns);self.assertEqual(db.total_changes,before)
        t=s['tracks'][0];self.assertEqual(t['tonality'],'F#m');self.assertEqual(t['comment'],'First line\nSecond line')
        self.assertEqual(t['color_name'],'Warm up');self.assertEqual(t['color_hex'],'#00FF00')
        exported=json.dumps(payload(s,'Test'));self.assertNotIn('Second line',exported);self.assertNotIn('comment',payload(s,'Test')['columns'])
        self.assertIn('tonality',payload(s,'Test')['columns'])

    def test_tonality_and_bpm_stats_keep_unknowns_and_raw_notations(self):
        tracks=[track({'id':str(i),'tonality':tone,'bpm':bpm,'duration':length,**xml_colour(colour)}) for i,(tone,bpm,length,colour) in enumerate([
            ('Am',120,240,'0x00FF00'),('A minor',140,300,'0xFF0000'),('',None,None,None),('Am',0,180,'')])]
        index=InsightIndex({'tracks':tracks,'captured':'2026-11-13','capabilities':{}});r=tonalities(index,{})
        self.assertEqual(r['summary']['bpm_known'],2);self.assertEqual(r['summary']['bpm_unknown'],2)
        self.assertEqual(r['summary']['bpm_mean'],130);self.assertEqual(r['summary']['bpm_median'],130)
        self.assertEqual(r['summary']['bpm_min'],120);self.assertEqual(r['summary']['bpm_max'],140)
        self.assertEqual(r['summary']['duration_mean'],240);self.assertEqual(r['summary']['duration_median'],240)
        self.assertEqual(r['summary']['tonality_unknown'],1);self.assertEqual(len(r['tonalities']),3)
        self.assertEqual(sum(b['tracks'] for b in r['bpm_histogram']),2)
        self.assertEqual(tonalities(index,{'tone':'Am'})['summary']['entries'],2)
        colours=bubbles(index,{'dimension':'colour'});self.assertEqual(sum(g['entries'] for g in colours['groups']),4)
        self.assertEqual(colours['summary']['coloured'],2);self.assertEqual(colours['summary']['colour_unassigned'],1);self.assertEqual(colours['summary']['colour_unknown'],1)

    def test_comments_preserve_whitespace_and_reject_invalid_xml_characters(self):
        value='  Notes\nTabs\there & <text>  '
        self.assertEqual(validate('comment',value),value)
        self.assertEqual(validate('comment',''),'')
        for value in ('x'*4097,'bad\x00value','bad\ud800value'):
            with self.assertRaises(ValueError):validate('comment',value)


class FreeCommentAPITests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name).resolve()
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.s={'tracks':[track({'id':'t','title':'Track','comment':'Captured private note','tonality':'Am',**xml_colour('0xFF0000')})],
                'scope_key':'comments-test','source_kind':'Synthetic','captured':'2026-11-13','capabilities':{}}
        self.saved=self.store.save_snapshot(self.s,'Test');self.identity=self.saved['id']
        p=patch.object(application,'DATA',self.root);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def test_comment_staging_and_reset_are_free_while_other_fields_remain_locked(self):
        url='/api/lab/overrides';body={'snapshot':self.identity,'track_id':'t','field':'comment','value':'Working\ncomment'}
        r=self.client.post(url,json=body,headers=self.headers);self.assertEqual(r.status_code,200,r.json)
        detail=self.client.get('/api/lab/track',query_string={'snapshot':self.identity,'track_id':'t'}).json
        self.assertFalse(detail['unlocked']);self.assertEqual(detail['overrides']['comment']['value'],'Working\ncomment')
        self.assertEqual(detail['original']['comment'],'Captured private note')
        blocked=self.client.post(url,json={**body,'field':'genre','value':'House'},headers=self.headers)
        self.assertEqual(blocked.status_code,400);self.assertIn('read-only',blocked.json['error'])
        self.assertEqual(self.client.delete(url,json=body,headers=self.headers).status_code,200)
        self.assertEqual(self.store.overrides('comments-test'),{})
        self.assertEqual(self.store.snapshot(self.identity)['tracks'][0]['comment'],'Captured private note')
        self.assertEqual(self.client.post(url,json=body).status_code,403)

    def test_insights_csv_and_shareable_payloads_do_not_contain_private_comments(self):
        r=self.client.get('/api/insights/tracks',query_string={'snapshot':self.identity,'perspective':'all'})
        self.assertNotIn('Captured private note',r.get_data(as_text=True))
        csv=self.client.get('/api/insights/tracks.csv',query_string={'snapshot':self.identity,'perspective':'all'})
        self.assertNotIn('Captured private note',csv.get_data(as_text=True))
        self.assertNotIn('Captured private note',json.dumps(payload(self.s,'Test')))

    def test_colour_role_labels_are_local_preferences_without_tag_mutation(self):
        before=deepcopy(self.store.snapshot(self.identity))
        r=self.client.post('/api/insights/colour-meanings',json={'snapshot':self.identity,'meanings':{'#FF0000':'Banger'}},headers=self.headers)
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['meanings']['#FF0000'],'Banger')
        options=self.client.get('/api/insights/options',query_string={'snapshot':self.identity}).json
        self.assertEqual(options['colour_meanings']['#FF0000'],'Banger')
        self.assertEqual(self.store.snapshot(self.identity),before);self.assertEqual(self.store.overrides('comments-test'),{})
        bad=self.client.post('/api/insights/colour-meanings',json={'snapshot':self.identity,'meanings':{'not-a-track-colour':'x'}},headers=self.headers)
        self.assertEqual(bad.status_code,400)


if __name__=='__main__':unittest.main()

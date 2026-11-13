"""Local intelligence API contracts using synthetic immutable sidecar captures."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as application
from workbench_store import Store


class IntelligenceApiTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        patcher=patch.object(application,'DATA',self.root);patcher.start();self.addCleanup(patcher.stop)
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.source={'scope_key':'synthetic','captured':'2026-01-02T03:04:05Z','source_kind':'Synthetic test',
                     'tracks':[{'id':str(i),'uuid':'uuid-'+str(i),'title':'日本 🎧 <song> '+str(i),'artist':'Artist',
                                'genre':'House','bpm':120+i%5,'rating':0} for i in range(70)],
                     'capabilities':{'playlist_order':True,'history_details':True,'history_order':True},
                     'playlists':[{'id':str(i),'name':'Set '+str(i),'tracks':['1','2']} for i in range(55)],
                     'histories':[{'id':'h','name':'Saved gig','date':'2026-01-01',
                                   'entries':[{'track_id':str(i),'position':i+1} for i in range(70)]}]}
        self.first=self.store.save_snapshot(self.source,'Before')['id']
        later=deepcopy(self.source);later['tracks'][0]['genre']='Techno'
        self.second=self.store.save_snapshot(later,'After')['id']
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def test_options_and_overlap_are_read_only_and_pages_have_exact_totals(self):
        before=self.store.snapshot(self.first)
        options=self.client.get('/api/intelligence/options',query_string={'snapshot':self.first})
        self.assertEqual(options.status_code,200);self.assertEqual(len(options.json['playlists']),55)
        self.assertTrue(options.json['history_order'])
        response=self.client.get('/api/intelligence/playlists',query_string={'snapshot':self.first,'playlist':'0','offset':50})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['total'],54)
        self.assertEqual(len(response.json['rows']),4)
        self.assertTrue(all(row['identical_membership'] for row in response.json['rows']))
        self.assertEqual(self.store.snapshot(self.first),before)

    def test_missing_sources_and_invalid_inputs_return_actionable_errors(self):
        for path,query in [('/api/intelligence/options',{}),
                           ('/api/intelligence/options',{'snapshot':'unknown'}),
                           ('/api/intelligence/playlists',{'snapshot':self.first,'playlist':'0','minimum':'NaN'}),
                           ('/api/intelligence/playlists',{'snapshot':self.first,'playlist':'0','offset':'bad'}),
                           ('/api/intelligence/session',{'snapshot':self.first,'history':'missing'})]:
            response=self.client.get(path,query_string=query)
            self.assertEqual(response.status_code,400,(path,query));self.assertIn('error',response.json)
        for values in ([],{'kind':'session','snapshot':[]},
                       {'kind':'playlists','snapshot':self.first,'playlist':'0','minimum':None},
                       {'kind':'session','snapshot':self.first,'history':'h','offset':{}},
                       {'kind':'not-a-report'}):
            response=self.client.post('/api/intelligence/report',json=values,headers=self.headers)
            self.assertEqual(response.status_code,400,values)
        self.assertEqual(self.store.reports(),[])

    def test_reports_require_token_recompute_and_disclose_page_only_retention(self):
        values={'kind':'session','snapshot':self.first,'history':'h','offset':50,
                'rows':[{'track_id':'forged','title':'Untrusted supplied report'}]}
        self.assertEqual(self.client.post('/api/intelligence/report',json=values).status_code,403)
        response=self.client.post('/api/intelligence/report',json=values,headers=self.headers)
        self.assertEqual(response.status_code,200)
        record=self.store.report(response.json['id'],all_rows=True)
        self.assertEqual(record['total'],20);self.assertEqual(record['summary']['total'],70)
        self.assertEqual(record['summary']['offset'],50);self.assertTrue(record['summary']['retained_page_only'])
        self.assertEqual(record['rows'][0]['track_id'],'50')
        self.assertNotIn('forged',[row['track_id'] for row in record['rows']])
        download=self.client.get(response.json['download'])
        self.assertEqual(download.status_code,200);self.assertIn('attachment',download.headers['Content-Disposition'])

    def test_evolution_uses_captured_values_and_never_applies_working_overrides(self):
        self.store.save_override('synthetic','0','genre','Changed locally','House')
        response=self.client.get('/api/intelligence/evolution',query_string={'before':self.first,'after':self.second})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['changed_fields']['genre'],1)
        self.assertEqual(self.store.snapshot(self.first)['tracks'][0]['genre'],'House')
        report=self.client.post('/api/intelligence/report',json={'kind':'evolution','before':self.first,'after':self.second},headers=self.headers)
        self.assertEqual(report.status_code,200);self.assertFalse(report.json['summary']['retained_page_only'])

    def test_duplicate_projection_excludes_donors_without_changing_source_or_audio(self):
        original=deepcopy(self.source)
        session={'catalog':object(),'decisions':{'pair':{'action':'merge'}}}
        with patch.object(application,'current',return_value=session),patch('intelligence_routes.decision_map',return_value=({'2':'1'},{})),patch('intelligence_routes.capture_catalog',return_value=self.source):
            self.assertEqual(self.client.post('/api/intelligence/duplicate-impact').status_code,403)
            response=self.client.post('/api/intelligence/duplicate-impact',json={},headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['removed_records'],1)
        self.assertEqual(response.json['retained_records'],69);self.assertFalse(response.json['audio_files_removed'])
        self.assertEqual(self.source,original)


if __name__=='__main__':unittest.main()

"""No provider traffic: alternative selection, release identity and stale review contracts."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import app as application
from musicbrainz_pilot import create_batch,batch_record
from musicbrainz_review import revision
from workbench_store import Store,encoded
from test_library_lab import snapshot

A='01234567-89ab-cdef-0123-456789abcdef'
B='11111111-2222-3333-4444-555555555555'
R='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

class MusicBrainzReviewTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);root=Path(tmp.name)
        for key,value in [('DATA',root),('active',None),('sessions',{})]:
            p=patch.object(application,key,value);p.start();self.addCleanup(p.stop)
        self.store=Store(root/'workbench-sidecar.sqlite3');self.store.set_setting('musicbrainz_enabled',True)
        self.sid=self.store.save_snapshot(snapshot(),'Review')['id'];self.source=self.store.snapshot(self.sid)
        self.batch=create_batch(self.store,self.source)['id'];self.url='/api/lab/musicbrainz/'+self.batch
        self.result={'status':'candidate_needs_review','match_approved':False,'selected_mbid':A,
                     'candidates':[{'mbid':A,'title':'First','confidence':90},{'mbid':B,'title':'Alternative','confidence':85}],
                     'proposal':{'year':1998,'genre':'House','retrieved_at':'2026-01-01',
                                 'possible_albums':[{'mbid':R,'title':'Selected edition','date':'2005-03','country':'GB'}]}}
        with self.store.connection() as db:db.execute('INSERT INTO mb_results VALUES (?,?,?,?)',(self.batch,'one',self.result['status'],encoded(self.result)))
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}
        self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
    def current(self):
        with self.store.connection() as db:return json.loads(db.execute('SELECT payload FROM mb_results WHERE batch_id=? AND track_id=?',(self.batch,'one')).fetchone()[0])
    def post(self,action,**values):
        return self.client.post(self.url+'/'+action,json={'track_id':'one','review_revision':revision(self.current()),**values},headers=self.headers)
    def approve(self):self.assertEqual(self.post('review',approved=True).status_code,200)
    def choose(self):
        self.approve();self.assertEqual(self.post('release',release_mbid=R).status_code,200)
    def launch(self,work,*args,**kwargs):
        self.job_result=work(lambda *_:None)
        if kwargs.get('on_finished'):kwargs['on_finished']('complete')
        return 'test-job'
    def fake(self,**changes):
        detail={'id':B,'first-release-date':'2010','genres':[{'name':'Techno','count':4}],
                'releases':[{'id':R,'title':'Other edition','date':'2011-04','country':'DE'}],**changes}
        return SimpleNamespace(get=lambda *_:deepcopy(detail))
    def test_album_requires_explicit_release_and_provenance_survives(self):
        self.approve()
        self.assertEqual(self.post('stage',field='album').status_code,400)
        self.assertEqual(self.post('release',release_mbid=B).status_code,400)
        self.assertEqual(self.post('release',release_mbid=R).status_code,200)
        album=self.post('stage',field='album');self.assertEqual(album.json['value'],'Selected edition')
        year=self.post('stage',field='year',year_basis='release');self.assertEqual(year.json['value'],2005)
        self.assertEqual(year.json['provenance']['release_id'],R)
        recording=self.post('stage',field='year');self.assertEqual(recording.json['value'],1998)
        self.assertIsNone(recording.json['provenance']['release_id'])
        edits=self.store.overrides(self.source['scope_key'])['one']
        provenance=json.loads(edits['album']['origin']);self.assertEqual(provenance['recording_id'],A)
        self.assertEqual(provenance['batch_id'],self.batch);self.assertEqual(provenance['basis'],'release')
        self.assertNotIn('rating',edits);self.assertEqual(self.store.snapshot(self.sid),self.source)

    def test_stale_review_stage_and_release_do_not_mutate_new_identity(self):
        old=revision(self.current());self.approve()
        for action,extra in [('review',{'approved':False}),('stage',{'field':'genre'}),('release',{'release_mbid':R})]:
            self.assertEqual(self.post(action,review_revision=old,**extra).status_code,409)
        self.assertTrue(self.current()['match_approved']);self.assertEqual(self.store.overrides(self.source['scope_key']),{})

    def test_alternative_resets_approval_release_and_own_staging_preserves_manual_edits(self):
        self.choose();self.assertEqual(self.post('stage',field='album').status_code,200)
        self.store.save_override(self.source['scope_key'],'one','genre','Manual genre',self.source['tracks'][0].get('genre'))
        with patch('enrichment_context.require_snapshot'),patch('lab_routes.MusicBrainzClient',return_value=self.fake()),patch.object(application,'launch',side_effect=self.launch):
            response=self.post('candidate',candidate_mbid=B,query_consent=True)
        self.assertEqual(response.status_code,200,response.json)
        result=self.current();self.assertEqual(result['selected_mbid'],B);self.assertFalse(result['match_approved'])
        self.assertIsNone(result['selected_release']);self.assertEqual(result['proposal']['genre'],'Techno')
        self.assertEqual(self.store.overrides(self.source['scope_key'])['one']['genre']['value'],'Manual genre')
        self.assertNotIn('album',self.store.overrides(self.source['scope_key'])['one'])
        self.assertEqual(batch_record(self.store,self.batch)['rows'][0]['selected_mbid'],B)
        self.assertFalse(application.lab_jobs_active())

    def test_failed_retrieval_keeps_review_and_staging_unchanged_and_releases_queue(self):
        self.choose();self.post('stage',field='album');before=self.current();edits=self.store.overrides(self.source['scope_key'])
        with patch('enrichment_context.require_snapshot'),patch('lab_routes.MusicBrainzClient',return_value=self.fake(id=A)),patch.object(application,'launch',side_effect=self.launch):
            response=self.post('candidate',candidate_mbid=B,query_consent=True)
        self.assertEqual(response.status_code,400)
        self.assertEqual(self.current(),before);self.assertEqual(self.store.overrides(self.source['scope_key']),edits)
        self.assertFalse(application.lab_jobs_active())

    def test_consent_disable_foreign_candidate_and_stale_selection(self):
        with patch('enrichment_context.require_snapshot'),patch('lab_routes.MusicBrainzClient') as client:
            self.assertEqual(self.post('candidate',candidate_mbid=B,query_consent=False).status_code,400)
            self.store.set_setting('musicbrainz_enabled',False)
            self.assertEqual(self.post('candidate',candidate_mbid=B,query_consent=True).status_code,400)
            self.store.set_setting('musicbrainz_enabled',True)
            self.assertEqual(self.post('candidate',candidate_mbid=R,query_consent=True).status_code,400)
            self.assertEqual(self.post('candidate',candidate_mbid=B,query_consent=True,review_revision='stale').status_code,409)
            client.assert_not_called()

    def test_cancelled_alternative_keeps_prior_result_and_releases_reservation(self):
        pending={}
        def queued(work,*args,**kwargs):
            pending.update(work=work,**kwargs);return 'queued'
        before=self.current()
        with patch('enrichment_context.require_snapshot'),patch.object(application,'launch',side_effect=queued):
            self.assertEqual(self.post('candidate',candidate_mbid=B,query_consent=True).status_code,200)
        self.addCleanup(lambda:pending['on_finished']('cancelled'))
        self.assertEqual(self.post('review',approved=True).status_code,409)
        pending['cancel_event'].set()
        with patch('lab_routes.MusicBrainzClient',return_value=self.fake()):
            with self.assertRaises(InterruptedError):pending['work'](lambda *_:None)
        self.assertEqual(self.current(),before);self.assertFalse(application.lab_jobs_active())

    def test_revoking_approval_removes_only_batch_suggestions(self):
        self.choose();self.post('stage',field='album')
        self.assertEqual(self.post('review',approved=False).status_code,200)
        self.assertEqual(self.store.overrides(self.source['scope_key']),{})
        self.assertTrue(any(r['current'] is None for r in self.store.override_history(self.source['scope_key'])))

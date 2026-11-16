"""Search audit trails retain the source spelling and both version directions."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from matching_evidence import cleanup
from musicbrainz_pilot import candidates_for,create_batch,run_batch,batch_record
from workbench_store import Store

MBID='11111111-1111-4111-8111-111111111111'


class MatchingEvidenceTests(unittest.TestCase):
    def test_cleanup_records_each_changed_step_without_mutating_title(self):
        title='The Night - Original Mix';artist='DJ feat. Guest';result=cleanup(title,artist)
        self.assertEqual(result['original'],{'title':title,'artist':artist})
        self.assertEqual(result['cleaned'],{'title':'night','artist':'dj'})
        self.assertIn('original_version',[s['step'] for s in result['steps']])
        self.assertIn('featured_artists',[s['step'] for s in result['steps']])

    def test_versions_are_held_in_both_directions_and_disagreements_retained(self):
        for a,b in [('Night','Night (Live)'),('Night (Live)','Night'),('Night (Dub)','Night (Radio Edit)')]:
            track={'title':a,'artist':'DJ','duration':180};before=deepcopy(track)
            candidate=candidates_for(track,[{'id':MBID,'title':b,'length':190000,'artist-credit':[{'name':'Other'}]}])[0]
            self.assertTrue(candidate['version_needs_review'])
            self.assertEqual({d['field'] for d in candidate['disagreements']},{'title','artist','version','duration'})
            self.assertFalse(candidate['match_approved']);self.assertEqual(track,before)

    def test_failed_search_still_keeps_attempts_and_original_tags(self):
        with TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'sidecar.db');track={'id':'one','title':'The Night (Original Mix)','artist':'DJ','genre':'House'}
            sid=store.save_snapshot({'scope_key':'test','tracks':[track]},'Test')['id']
            batch=create_batch(store,store.snapshot(sid),playable_only=False)
            calls=[]
            def get(endpoint,params):
                calls.append(params['query'])
                if len(calls)==2:raise OSError('Provider unavailable')
                return {'recordings':[]}
            run_batch(store,batch['id'],SimpleNamespace(get=get,requests=0,cache_hits=0),lambda *_:None)
            row=batch_record(store,batch['id'])['rows'][0]
            self.assertEqual(row['original_tags']['title'],track['title'])
            self.assertEqual(len(row['search_history']),2)
            self.assertEqual(row['search_history'][-1]['error'],'OSError')


if __name__=='__main__':unittest.main()

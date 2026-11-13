import unittest
from copy import deepcopy
from library_intelligence import duplicate_impact,playlist_overlap,session_progression,evolution


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot={'tracks':[{'id':'1','title':'🎧','artist':'A','genre':'House','bpm':120,'uuid':'one'},
                                 {'id':'2','title':'Second','artist':'B','genre':'House','bpm':None,'uuid':'two'},
                                 {'id':'3','title':'Third','artist':'A','genre':'Techno','bpm':125,'uuid':'three'}],
                       'capabilities':{'history_details':True,'history_order':True,'playlist_order':True},
                       'playlists':[{'id':'a','name':'Set','tracks':['1','2']},{'id':'b','name':'Set copy','tracks':['2','1']},
                                    {'id':'c','name':'Other','tracks':['2','3']},{'id':'d','name':'Empty','tracks':[]}],
                       'histories':[{'id':'h','name':'Gig','entries':[{'track_id':'1'},{'track_id':'2'},{'track_id':'3'},{'track_id':'missing'}]}]}

    def test_overlap_preserves_intent_and_order_distinction(self):
        result=playlist_overlap(self.snapshot,'a',.2)
        self.assertEqual(result['total'],2)
        same=result['rows'][0];self.assertTrue(same['identical_membership']);self.assertFalse(same['same_saved_order'])
        self.assertAlmostEqual(result['rows'][1]['jaccard'],.3333)
        self.assertEqual(playlist_overlap(self.snapshot,'d',0)['total'],0)
        with self.assertRaises(ValueError):playlist_overlap(self.snapshot,'a',float('nan'))

    def test_progression_does_not_bridge_missing_values(self):
        result=session_progression(self.snapshot,'h')
        self.assertEqual([r['bpm_delta'] for r in result['rows']],[None,None,None,None])
        self.assertTrue(result['rows'][-1]['missing_metadata'])
        self.snapshot['capabilities']['history_order']=False
        with self.assertRaises(ValueError):session_progression(self.snapshot,'h')

    def test_donor_exclusion_is_record_count_only(self):
        original=deepcopy(self.snapshot);result=duplicate_impact(self.snapshot,{'1':'3','2':'3'})
        self.assertEqual(result['removed_records'],2);self.assertEqual(result['retained_records'],1)
        self.assertFalse(result['audio_files_removed']);self.assertEqual(self.snapshot,original)

    def test_evolution_distinguishes_ambiguous_from_removed(self):
        later=deepcopy(self.snapshot);later['tracks'][0]['genre']='Techno';later['tracks'].pop()
        later['tracks'].append({'id':'new','uuid':'new','title':'new'})
        result=evolution(self.snapshot,later)
        self.assertEqual(result['matched_records'],2);self.assertEqual(result['unmatched_before'],1)
        self.assertEqual(result['unmatched_after'],1);self.assertEqual(result['changed_fields']['genre'],1)

    def test_page_boundary_retains_previous_bpm(self):
        self.snapshot['tracks'][1]['bpm']=123
        result=session_progression(self.snapshot,'h',1)
        self.assertEqual(result['rows'][0]['bpm_delta'],3)

    def test_missing_history_tracks_retain_archived_labels_without_inventing_bpm(self):
        self.snapshot['histories'][0]['entries'][-1].update(title='Archived song',artist='Archived artist')
        result=session_progression(self.snapshot,'h')
        row=result['rows'][-1]
        self.assertEqual(row['title'],'Archived song');self.assertEqual(row['artist'],'Archived artist')
        self.assertTrue(row['missing_metadata']);self.assertIsNone(row['bpm']);self.assertIsNone(row['bpm_delta'])

    def test_unknown_fields_are_not_reported_as_confirmed_changes(self):
        later=deepcopy(self.snapshot);later['tracks'][0]['bpm']=None
        result=evolution(self.snapshot,later)
        self.assertNotIn('bpm',result['changed_fields'])
        self.assertEqual(result['unavailable_field_comparisons']['bpm'],2)

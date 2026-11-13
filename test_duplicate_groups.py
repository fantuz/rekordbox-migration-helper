"""Synthetic multi-donor regressions: preview must agree with reversible staging."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import app as application
from engine import decision_map
from test_engine import catalog, cue


class RecordingGroupTests(unittest.TestCase):
    def setUp(self):
        self.cat,_=catalog([cue(1,1000,'My intro')],[cue(2,2000,'My drop')])
        for track,points in {'c':[cue(3,3000,'My break')],
                             'd':[cue(2,5000,'Different manual drop')],
                             'e':[cue(4,4000,'Alternate mix')],
                             'f':[cue(5,5000,'Indirect candidate')]}.items():
            self.cat.tracks[track]=dict(self.cat.tracks['b']);self.cat.cues[track]=points
        self.cat.pairs={f'a~{i}':{'a':'a','b':i} for i in 'bcde'}
        self.cat.pairs['e~f']={'a':'e','b':'f'}
        self.session={'catalog':self.cat,'decisions':{},'held_pairs':{},'batches':[],'last_batch':[]}
        self.body={'track_ids':list('abcdef'),'keeper':'a','excluded':['e']}
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}
        for patcher in (patch.object(application,'current',return_value=self.session),
                        patch.object(application,'summary',return_value={'synthetic':True}),
                        patch.object(application,'log')):
            patcher.start();self.addCleanup(patcher.stop)

    def test_preview_accumulates_donor_cues_and_holds_conflicts_without_mutation(self):
        decisions=deepcopy(self.session['decisions']);cues=deepcopy(self.cat.cues)
        response=self.client.post('/api/group/preview',json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,200);plan=response.json
        self.assertEqual(plan['counts'],{'ready':2,'held':2,'excluded':1,'already_staged':0})
        self.assertEqual(plan['decisions'],['a~b','a~c'])
        self.assertIn('conflict',plan['held']['d']);self.assertIn('No direct match',plan['held']['f'])
        self.assertEqual(self.session['decisions'],decisions);self.assertEqual(self.session['held_pairs'],{})
        self.assertEqual(self.session['batches'],[]);self.assertEqual(self.cat.cues,cues)

    def test_one_keeper_with_two_donors_stages_once_and_undo_preserves_prior_choice(self):
        self.session['decisions']['a~b']={'action':'skip'}
        before=deepcopy(self.session['decisions']);cues=deepcopy(self.cat.cues)
        response=self.client.post('/api/group/stage',json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['count'],2)
        mapping,result=decision_map(self.cat,self.session['decisions'])
        self.assertEqual(mapping,{'b':'a','c':'a'});self.assertEqual(len(result['a']['cues']),3)
        self.assertEqual(self.cat.cues,cues)
        preview=self.client.post('/api/group/preview',json=self.body,headers=self.headers).json
        self.assertEqual(preview['counts']['already_staged'],2);self.assertEqual(preview['counts']['ready'],0)
        undone=self.client.post('/api/bulk/undo',json={},headers=self.headers)
        self.assertEqual(undone.status_code,200);self.assertEqual(undone.json['count'],2)
        self.assertEqual(self.session['decisions'],before);self.assertEqual(self.session['held_pairs'],{})

    def test_exclusions_do_not_undo_existing_staged_merges(self):
        self.session['decisions']['a~b']={'action':'merge','keeper':'a'}
        self.body['excluded'].append('b')
        plan,_=application.recording_group_plan(self.session,self.body)
        row=next(r for r in plan['rows'] if r['track_id']=='b')
        self.assertEqual(row['status'],'already_staged')

    def test_overlapping_keeper_and_manual_cue_conflicts_are_held_even_with_auto_policy(self):
        self.cat.pairs['b~c']={'a':'b','b':'c'}
        self.session['decisions']['b~c']={'action':'merge','keeper':'b'}
        plan,_=application.recording_group_plan(self.session,{**self.body,'prefer_auto':True})
        self.assertIn('another keeper',plan['held']['b'])
        self.assertIn('another keeper',plan['held']['c'])
        # With no prior mapping, d clashes with b only after b's cue is accumulated.
        self.session['decisions'].clear()
        plan,_=application.recording_group_plan(self.session,{**self.body,'prefer_auto':True})
        self.assertIn('conflict',plan['held']['d'])

    def test_malformed_and_oversized_plans_fail_before_staging(self):
        for body in ({'track_ids':['a','a'],'keeper':'a'}, {'track_ids':['a']*101,'keeper':'a'},
                     {'track_ids':['a','unknown'],'keeper':'a'}, {'track_ids':[['a']],'keeper':'a'},
                     {**self.body,'excluded':['a']}, {**self.body,'excluded':['unknown']}):
            response=self.client.post('/api/group/stage',json=body,headers=self.headers)
            self.assertEqual(response.status_code,400,body);self.assertEqual(self.session['decisions'],{})
        response=self.client.post('/api/group/preview',json=self.body)
        self.assertEqual(response.status_code,403)


if __name__=='__main__':unittest.main()

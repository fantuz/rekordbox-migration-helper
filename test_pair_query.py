"""Cache dependency and pagination regressions, using synthetic recordings only."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from pair_query import page


def fixture(count=90):
    rows={str(i):{'id':str(i),'a':str(i*2),'b':str(i*2+1),'keeper':str(i*2),
                 'title':'Track '+str(i),'artist':'Artist','category':'review' if i%3==0 else 'ready',
                 'evidence':{'metadata_agrees':True,'rated':i%2==0}} for i in range(count)}
    return {'catalog':SimpleNamespace(descriptions=rows,policy='newest'),
            'decisions':{},'held_pairs':{},'inventory':{'matches':{}},'media_verifications':{}}


def evidence(session,row):
    check=session['media_verifications'].get(row['id'])
    return {**row,'evidence':{**row['evidence'],'content_hash_agrees':bool(check and check['same_file_bytes']),
                            'files_found_both':all(session['inventory']['matches'].get(i,{}).get('status')=='found' for i in (row['a'],row['b']))}}


def scope(session,row,values,include_evidence=False):
    return not values.get('q') or values['q'].casefold() in row['title'].casefold()


class PairQueryTests(unittest.TestCase):
    def test_pagination_and_group_view_reuse_one_filtered_graph(self):
        session=fixture();first=page(session,{},scope,evidence)
        second=page(session,{'offset':'40'},scope,evidence)
        grouped=page(session,{'view':'groups'},scope,evidence)
        self.assertEqual(first['total'],90);self.assertEqual(grouped['groups'],90)
        self.assertEqual(len(first['rows']),40);self.assertEqual(len(second['rows']),40)
        self.assertFalse({r['id'] for r in first['rows']}&{r['id'] for r in second['rows']})
        self.assertEqual(session['catalog']._pair_query_cache.builds,1)
        self.assertEqual(grouped['potential_reduction'],90)

    def test_every_evidence_dependency_invalidates_including_nested_changes(self):
        session=fixture(3);page(session,{},scope,evidence);cache=session['catalog']._pair_query_cache
        mutations=[lambda:session['decisions'].update({'1':{'action':'merge','keeper':'2'}}),
                   lambda:session['decisions']['1'].update(action='skip'),
                   lambda:session['held_pairs'].update({'1':'Manual review'}),
                   lambda:session['inventory']['matches'].update({'2':{'status':'found'},'3':{'status':'found'}}),
                   lambda:session['inventory']['matches']['2'].update(status='missing'),
                   lambda:session['media_verifications'].update({'1':{'same_file_bytes':True}}),
                   lambda:session['media_verifications']['1'].update(same_file_bytes=False),
                   lambda:setattr(session['catalog'],'policy','played'),
                   lambda:setattr(session['catalog'],'descriptions',deepcopy(session['catalog'].descriptions))]
        for mutate in mutations:
            before=cache.builds;mutate();page(session,{},scope,evidence)
            self.assertEqual(cache.builds,before+1)

    def test_filter_changes_recompute_and_staged_evidence_facets_remain_correct(self):
        session=fixture(6)
        result=page(session,{'evidence':'rated'},scope,evidence)
        self.assertEqual(result['total'],3);self.assertEqual(result['facets']['metadata_agrees'],6)
        session['decisions']['2']={'action':'merge','keeper':'4'}
        staged=page(session,{'filter':'staged'},scope,evidence)
        self.assertEqual([row['id'] for row in staged['rows']],['2'])
        self.assertEqual(page(session,{'q':'Track 5'},scope,evidence)['total'],1)
        self.assertEqual(page(session,{'evidence':'unknown-evidence'},scope,evidence)['total'],0)

    def test_connected_three_copy_group_uses_transitive_graph(self):
        session=fixture(2);session['catalog'].descriptions['1'].update(a='1',b='2')
        result=page(session,{'view':'groups'},scope,evidence)
        self.assertEqual(result['groups'],1);self.assertEqual(result['tracks'],3)
        self.assertEqual(result['rows'][0]['track_ids'],['0','1','2'])
        self.assertEqual(result['potential_reduction'],2)


if __name__=='__main__':unittest.main()

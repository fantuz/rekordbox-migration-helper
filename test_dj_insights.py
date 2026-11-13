"""Synthetic insight contracts; no private data, network lookups or audio reads."""
from copy import deepcopy
import csv
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app as application
from dj_insights import InsightIndex,ranking,bubbles,genre_family,initial,saved_date,statistics as insight_statistics
from workbench_store import Store


def song(identity,**values):
    return {'id':identity,'title':'Track '+identity,'artist':'Artist '+identity,'album':'Synthetic',
            'genre':'House','year':2024,'bpm':128,'duration':240,'format':'MP3','rating':4,
            'play_count':0,'manual_cues':1,'auto_cues':0,'analysed':True,'date_added':'2021-01-01','last_played':None,**values}


def snapshot():
    return {'id':'synthetic','label':'Synthetic collection','scope_key':'test','captured':'2026-11-13T10:00:00+00:00',
            'source_kind':'Synthetic test snapshot','tracks':[
                song('a',play_count=30,last_played='2026-01-01'),
                song('b',genre='Deep House',play_count=2,rating=5,last_played='2026-09-01',date_added='2026-10-01'),
                song('c',genre='Techno'),
                song('d',genre='House / Techno',play_count=None,rating=None,manual_cues=None,auto_cues=None,analysed=None,duration=None,year=None,bpm=None),
                song('e',genre='Unclassified',rating=0,manual_cues=0,auto_cues=3,bpm=0),
                song('f',genre='Progressive',play_count=1,rating=3,manual_cues=0,analysed=False,last_played='2025-01-01'),
                song('g',genre='Dub Techno',play_count=5,manual_cues=0,analysed=False,last_played='2027-01-01')],
            'capabilities':{'history_details':True},'histories':[
                {'id':'h1','date':'2026-10-02','entries':[{'track_id':k} for k in ('a','a','b','d','ghost')]},
                {'id':'h2','date':'2026-09-01','entries':[{'track_id':k} for k in ('a','c')]},
                {'id':'h3','date':None,'entries':[{'track_id':'e'}]},
                {'id':'folder','folder':True,'date':'2026-11-01','entries':[{'track_id':'g'}]}]}


class InsightEvidenceTests(unittest.TestCase):
    def setUp(self):self.source=snapshot();self.index=InsightIndex(self.source)

    def test_rankings_keep_unknown_zero_and_low_positive_counts_distinct(self):
        self.assertEqual([t['id'] for t in ranking(self.index,{'perspective':'most'})['rows']],['a','g','b','f'])
        self.assertEqual([t['id'] for t in ranking(self.index,{'perspective':'least'})['rows']],['f','b','g','a'])
        self.assertEqual({t['id'] for t in ranking(self.index,{'perspective':'zero'})['rows']},{'c','e'})
        unknown=ranking(self.index,{'perspective':'all','usage_filter':'unknown'})
        self.assertEqual(unknown['total'],1);self.assertEqual(unknown['rows'][0]['id'],'d')
        self.assertIsNone(unknown['rows'][0]['plays']);self.assertEqual(unknown['result_stats']['zero_usage'],0)

    def test_prepared_and_underplayed_views_require_explicit_positive_evidence(self):
        self.assertEqual([t['id'] for t in ranking(self.index,{'perspective':'ready'})['rows']],['c'])
        gems=ranking(self.index,{'perspective':'gems'})
        self.assertEqual([t['id'] for t in gems['rows']],['b','c','f'])
        self.assertTrue(all(t['reason'] for t in gems['rows']))
        self.assertEqual({t['id'] for t in ranking(self.index,{'perspective':'preparation'})['rows']},{'e','f','g'})
        self.assertEqual([t['id'] for t in ranking(self.index,{'perspective':'all','preparation':'unknown'})['rows']],['d'])

    def test_history_repeats_and_distinct_session_reach_are_different_bases(self):
        entries=ranking(self.index,{'perspective':'all','basis':'history'});sessions=ranking(self.index,{'perspective':'all','basis':'sessions'})
        count=lambda r,key:next(t['plays'] for t in r['rows'] if t['id']==key)
        self.assertEqual(count(entries,'a'),3);self.assertEqual(count(sessions,'a'),2)
        self.assertEqual(count(entries,'d'),1);self.assertEqual(count(entries,'g'),0)
        self.assertEqual(entries['result_stats']['recorded_plays'],7)
        self.assertEqual(entries['context']['history_unresolved_entries'],1);self.assertEqual(entries['context']['history_undated_entries'],1)
        filtered=ranking(self.index,{'perspective':'all','basis':'history','from':'2026-10-01','to':'2026-10-31'})
        self.assertEqual(filtered['context']['selected_sessions'],1);self.assertEqual(filtered['result_stats']['recorded_plays'],4)
        self.assertEqual(count(filtered,'e'),0);self.assertEqual(count(filtered,'c'),0)

    def test_missing_history_and_undated_usage_do_not_become_fabricated_plays(self):
        source=snapshot();source['capabilities']={};index=InsightIndex(source)
        self.assertFalse(index.options()['history_available'])
        with self.assertRaises(ValueError):ranking(index,{'basis':'history'})
        with self.assertRaises(ValueError):ranking(index,{'basis':'saved','from':'2026-01-01'})
        self.assertEqual(ranking(self.index,{'perspective':'all','basis':'history','from':'2026-10-01'})['result_stats']['unknown_usage'],0)

    def test_dates_and_rediscovery_use_recorded_dates_and_snapshot_reference(self):
        result=ranking(self.index,{'perspective':'rediscover','days':180})
        self.assertEqual([t['id'] for t in result['rows']],['f','a'])
        self.assertEqual(ranking(self.index,{'perspective':'recent'})['rows'][0]['id'],'b')
        self.assertEqual(ranking(self.index,{'perspective':'last_used'})['rows'][0]['id'],'b')
        self.assertTrue(next(t for t in ranking(self.index,{'perspective':'all'})['rows'] if t['id']=='g')['evidence_date_after_snapshot'])
        self.assertIsNone(saved_date('2026-13-01'));self.assertEqual(saved_date('20261001').isoformat(),'2026-10-01')
        undated={'tracks':[song('x',last_played='2020-01-01',play_count=1)],'capabilities':{}}
        r=ranking(InsightIndex(undated),{'perspective':'rediscover'});self.assertFalse(r['rediscovery_date_available']);self.assertEqual(r['total'],0)

    def test_uniform_and_genre_balanced_sampling_are_reproducible_and_unique(self):
        source=snapshot();source['tracks']=[song(str(i),genre='House' if i<200 else 'Techno') for i in range(205)]
        index=InsightIndex(source);args={'perspective':'random','sample':10,'seed':'one','random_mode':'balanced'}
        first=ranking(index,args);again=ranking(index,args)
        self.assertEqual(first['rows'],again['rows']);self.assertEqual(len({r['id'] for r in first['rows']}),10)
        self.assertEqual(sum(r['family']=='Techno' for r in first['rows']),5)
        self.assertNotEqual([r['id'] for r in first['rows']],[r['id'] for r in ranking(index,{**args,'seed':'two'})['rows']])
        self.assertEqual(ranking(index,{**args,'random_mode':'uniform'})['total'],10)
        small=ranking(self.index,{**args,'sample':100});self.assertEqual(small['total'],7);self.assertEqual(small['eligible'],7)

    def test_filters_do_not_invent_unknown_bpm_duration_or_cross_field_search_matches(self):
        args={'perspective':'all','family':'House','bpm_min':125,'bpm_max':130,'min':3,'max':5,'rating_min':5}
        self.assertEqual([t['id'] for t in ranking(self.index,args)['rows']],['b'])
        self.assertEqual(ranking(self.index,{'perspective':'all','genre':'Deep House'})['total'],1)
        for args in ({'bpm_min':140,'bpm_max':120},{'min':'NaN'},{'stars':8},{'perspective':'bad'},{'from':'2026-11-10','to':'2026-01-01','basis':'history'}):
            with self.assertRaises(ValueError):ranking(self.index,args)
        source={'tracks':[song('x',title='Example track',artist='Another artist')],'capabilities':{}}
        self.assertEqual(ranking(InsightIndex(source),{'perspective':'all','q':'track another'})['total'],0)

    def test_local_projection_preserves_source_and_excludes_paths_and_cue_payloads(self):
        self.source['tracks'][0].update(current_path='/private/audio.mp3',cues=[{'label':'Private cue comment'}])
        before=deepcopy(self.source);result=ranking(InsightIndex(self.source),{'perspective':'all'})
        self.assertEqual(before,self.source);public=json.dumps(result)
        self.assertNotIn('/private/audio',public);self.assertNotIn('Private cue comment',public);self.assertNotIn('_search',public)
        self.assertEqual(result['scope_stats']['unknown_usage'],1)
        self.assertEqual(result['scope_stats']['top_ten_play_share'],100)


class BubbleAggregationTests(unittest.TestCase):
    def test_tag_families_are_conservative_and_ambiguous_tags_remain_visible(self):
        for tag,family in [('Tech House','House'),('UK Drum & Bass','Drum & bass'),('Techno / House','Mixed families'),('Progressive','Other / unmapped'),('Unknown','Unknown genre'),('Minimal','Electronic · unspecific'),('Dub Techno','Techno'),('Dub','Reggae & dub')]:
            self.assertEqual(genre_family(tag),family)
        self.assertEqual(initial('Česka'),'C');self.assertEqual(initial('5 Artists'),'0–9');self.assertEqual(initial('The Band'),'T')

    def test_bubble_weights_conserve_counts_plays_duration_and_unknowns(self):
        index=InsightIndex(snapshot())
        for metric in ('tracks','plays','duration'):
            r=bubbles(index,{'metric':metric})
            expected={'tracks':7,'plays':38,'duration':1440}[metric]
            self.assertEqual(sum(g['value'] for g in r['groups']),expected)
            self.assertEqual(sum(g['entries'] for g in r['groups']),7)
            self.assertEqual(r['total_weight'],expected)
        r=bubbles(index,{'metric':'plays'});mixed=next(g for g in r['groups'] if g['key']=='Mixed families')
        self.assertEqual(mixed['value'],0);self.assertEqual(mixed['weight_unknown_entries'],1)
        self.assertIsNone(mixed['manual_cue_percent']);self.assertIsNone(mixed['mean_personal_rating'])
        house=next(g for g in r['groups'] if g['key']=='House')
        self.assertEqual(house['manual_cue_percent'],100);self.assertEqual(house['mean_personal_rating'],4.5)

    def test_large_colour_cloud_preserves_unknowns_and_bounds_detailed_group_work(self):
        palette=['#FF007F','#FF0000','#FFA500','#FFFF00','#00FF00','#25FDE9','#0000FF','#660099']
        tracks=[]
        for i in range(33000):
            bucket=i%10
            tracks.append(song(str(i),color_key='native:'+str(bucket+1) if bucket<8 else 'unassigned' if bucket==8 else 'unknown',
                               color_name='Saved colour '+str(bucket)+' · Ελληνικά' if bucket<8 else None,
                               color_hex=palette[bucket] if bucket<8 else None,
                               color_status='assigned' if bucket<8 else 'unassigned' if bucket==8 else 'unknown'))
        index=InsightIndex({'tracks':tracks,'capabilities':{}})
        cloud=bubbles(index,{'dimension':'colour','metric':'tracks'})
        self.assertEqual(cloud['groups_total'],10);self.assertEqual(cloud['total_weight'],33000)
        self.assertEqual(sum(g['entries'] for g in cloud['groups']),33000)
        self.assertTrue(all(g['value']==3300 for g in cloud['groups']))
        self.assertEqual(cloud['summary']['coloured'],26400)
        self.assertEqual(cloud['summary']['colour_unassigned'],3300);self.assertEqual(cloud['summary']['colour_unknown'],3300)
        assigned=next(g for g in cloud['groups'] if g['key']=='native:1')
        self.assertEqual(assigned['label'],'Saved colour 0 · Ελληνικά');self.assertEqual(assigned['color_hex'],palette[0])
        unplayed=bubbles(index,{'dimension':'colour','metric':'plays'})
        self.assertEqual(unplayed['zero_weight_groups'],10);self.assertEqual(unplayed['total_weight'],0)
        # Paging a high-cardinality split should not calculate medians and tag
        # samples for the 32,940 groups that are not displayed on this page.
        with patch('dj_insights.statistics',wraps=insight_statistics) as detail:
            page=bubbles(index,{'dimension':'tracks','group_offset':32760})
        self.assertEqual(page['groups_total'],33000);self.assertEqual(page['total_weight'],33000)
        self.assertEqual(len(page['groups']),60);self.assertLessEqual(detail.call_count,61)
        self.assertEqual(len({g['key'] for g in page['groups']}),60)
        self.assertEqual(tracks[0]['color_name'],'Saved colour 0 · Ελληνικά')

    def test_click_branches_intersect_dimensions_without_double_counting(self):
        index=InsightIndex(snapshot());path=[{'dimension':'family','key':'House'}]
        tags=bubbles(index,{'path':path,'dimension':'genre'})
        self.assertEqual(tags['summary']['entries'],2);self.assertEqual(tags['groups_total'],2)
        path.append({'dimension':'genre','key':'Deep House'})
        rows=ranking(index,{'path':path,'perspective':'all'})
        self.assertEqual([t['id'] for t in rows['rows']],['b']);self.assertEqual(rows['context']['breadcrumbs'][0]['label'],'House')
        path.append({'dimension':'initial','key':'A'})
        self.assertEqual(bubbles(index,{'path':path,'dimension':'artist'})['groups'][0]['key'],'Artist b')
        with self.assertRaises(ValueError):bubbles(index,{'path':path,'dimension':'family'})
        with self.assertRaises(ValueError):bubbles(index,{'path':[{'dimension':'malicious','key':'x'}]})
        with self.assertRaises(ValueError):bubbles(index,{'path':[path[0],path[0]]})

    def test_paged_category_maps_do_not_hide_low_or_zero_weight_categories(self):
        source={'tracks':[song(str(i),artist='Artist '+str(i)) for i in range(150)],'capabilities':{}}
        index=InsightIndex(source);seen=set();total=0
        for offset in (0,60,120):
            r=bubbles(index,{'dimension':'artist','group_offset':offset,'metric':'plays'})
            self.assertEqual(r['groups_total'],150);self.assertEqual(r['zero_weight_groups'],150)
            keys={g['key'] for g in r['groups']};self.assertFalse(keys&seen);seen|=keys
            total+=sum(g['entries'] for g in r['groups'])
        self.assertEqual(total,150);self.assertEqual(len(seen),150)

    def test_each_supported_dimension_reconciles_to_the_same_branch_count(self):
        index=InsightIndex(snapshot())
        for dimension in index.options()['dimensions']:
            r=bubbles(index,{'dimension':dimension})
            self.assertEqual(sum(g['entries'] for g in r['groups']),7,dimension)
        self.assertEqual(bubbles(index,{'dimension':'tracks'})['groups_total'],7)
        self.assertEqual(ranking(index,{'perspective':'all','track_id':'d'})['rows'][0]['id'],'d')


class InsightAPITests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name).resolve()
        self.store=Store(self.root/'workbench-sidecar.sqlite3');self.record=self.store.save_snapshot(snapshot(),'Synthetic')
        p=patch.object(application,'DATA',self.root);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def test_read_only_endpoints_and_branch_requests_need_no_unlock_or_network(self):
        options=self.client.get('/api/insights/options',query_string={'snapshot':self.record['id']})
        self.assertEqual(options.status_code,200);self.assertEqual(options.json['entries'],7)
        r=self.client.get('/api/insights/bubbles',query_string={'snapshot':self.record['id'],'path':json.dumps([{'dimension':'family','key':'House'}]),'dimension':'artist'})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['summary']['entries'],2)
        self.assertEqual(self.store.overrides('test'),{})
        self.assertEqual(self.client.get('/api/insights/tracks',query_string={'snapshot':self.record['id'],'perspective':'bad'}).status_code,400)
        self.assertEqual(self.client.get('/api/insights/bubbles',query_string={'snapshot':self.record['id'],'path':'invalid'}).status_code,400)
        self.assertEqual(self.client.get('/api/insights/options?snapshot=none').status_code,400)

    def test_csv_exports_complete_views_and_neutralizes_spreadsheet_formula_tags(self):
        s=snapshot();s['tracks'][0]['title']='=HYPERLINK("malicious")';s['tracks'][0]['artist']=' +SUM(1,2)'
        record=self.store.save_snapshot(s,'CSV safety')
        response=self.client.get('/api/insights/tracks.csv',query_string={'snapshot':record['id'],'perspective':'all'})
        self.assertEqual(response.status_code,200);self.assertIn('attachment',response.headers['Content-Disposition'])
        rows=list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),7);row=next(t for t in rows if t['id']=='a')
        self.assertTrue(row['title'].startswith("'="));self.assertTrue(row['artist'].startswith("' +"))
        self.assertEqual(row['usage_evidence'],'Saved play count');self.assertNotIn('current_path',row)

    def test_saved_reports_are_bounded_and_preserve_counts_and_filters(self):
        s=snapshot();s['tracks']=[song(str(i),play_count=i+1) for i in range(300)]
        record=self.store.save_snapshot(s,'Large synthetic')
        response=self.client.post('/api/insights/report',json={'snapshot':record['id'],'filters':{'perspective':'most'}},headers=self.headers)
        self.assertEqual(response.status_code,200)
        saved=self.store.report(response.json['id'],all_rows=True)
        self.assertEqual(saved['summary']['entries'],300);self.assertEqual(len(saved['rows']),200)
        self.assertEqual(saved['summary']['filters']['perspective'],'most')
        self.assertEqual(self.client.get(response.json['download']).status_code,200)
        self.assertEqual(len(self.store.snapshot(record['id'])['tracks']),300)
        self.assertEqual(self.client.post('/api/insights/report',json={'snapshot':record['id']}).status_code,403)


if __name__=='__main__':unittest.main()

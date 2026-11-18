"""Display aliases conserve source evidence, grouping and filter identity."""
from copy import deepcopy
import csv
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import app as application
from dj_insights import InsightIndex, bubbles, ranking, tonalities
import key_notation as keys
from test_support import workspace_client
from workbench_store import Store

# Independent wheel reference: Camelot -> conventional major/minor spelling.
WHEEL={1:('B','Abm'),2:('F#','Ebm'),3:('Db','Bbm'),4:('Ab','Fm'),
       5:('Eb','Cm'),6:('Bb','Gm'),7:('F','Dm'),8:('C','Am'),
       9:('G','Em'),10:('D','Bm'),11:('A','F#m'),12:('E','C#m')}


def fixture():
    values=['Am','8A','1m','A minor','CM','8B','1d','C♯ minor','12A','Dbm','Unknown','', 'ambiguous C/D', '__proto__']
    return {'scope_key':'synthetic:key-display','tracks':[
        {'id':str(i),'title':'Synthetic '+str(i),'artist':'Unknown' if i==0 else 'Test artist',
         'tonality':value,'duration':0 if i==0 else 240,'play_count':0 if i==0 else i,
         'bpm':120,'genre':'House','year':2024,'date_added':'2020-01-01'} for i,value in enumerate(values)]}


class KeyNotationTests(unittest.TestCase):
    def test_all_24_keys_have_correct_major_minor_and_open_key_equivalents(self):
        self.assertEqual(len(keys.KEYS),24)
        seen=set()
        for number,(major,minor) in WHEEL.items():
            for suffix,alpha in [('B',major),('A',minor)]:
                identity=keys.parse(str(number)+suffix);self.assertIsNotNone(identity)
                seen.add(identity)
                self.assertEqual(keys.label(identity,'alpha'),alpha)
                self.assertEqual(keys.parse(alpha),identity)
                self.assertEqual(keys.parse(keys.label(identity,'open_key')),identity)
                self.assertEqual(keys.parse(f'{number:02}'+suffix),identity)
        self.assertEqual(len(seen),24)
        for alpha,open_key in [('C','1d'),('Am','1m'),('G','2d'),('Em','2m'),('F','12d'),('Dm','12m')]:
            self.assertEqual(keys.parse(alpha),keys.parse(open_key))
        self.assertEqual(keys.parse('CM'),keys.parse('8B'))
        self.assertEqual(keys.parse('Cm'),keys.parse('5A'))
        self.assertEqual(keys.parse('C♯ MINOR'),keys.parse('D♭m'))
        self.assertEqual(keys.parse('B♯ major'),keys.parse('C'))
        for raw in ('C/D','0A','13B','8','H minor','8AB','1major','key:0:major','constructor','__proto__'):
            self.assertIsNone(keys.parse(raw),raw)

    def test_format_switch_preserves_canonical_groups_weights_source_tags_and_branches(self):
        source=fixture();before=deepcopy(source);index=InsightIndex(source)
        expected=None
        for mode,label in [('alpha','Am'),('camelot','8A'),('open_key','1m')]:
            result=bubbles(index,{'dimension':'tone','key_notation':mode})
            counts={g['key']:g['entries'] for g in result['groups']}
            if expected is None:expected=counts
            self.assertEqual(counts,expected)
            minor=next(g for g in result['groups'] if g['key']==keys.parse('Am'))
            self.assertEqual(minor['label'],label);self.assertEqual(minor['entries'],4)
            self.assertEqual({v['value'] for v in minor['source_keys']},{'Am','8A','1m','A minor'})
            branch=[{'dimension':'tone','key':minor['key']}]
            rows=ranking(index,{'path':branch,'key_notation':mode,'perspective':'all'})
            self.assertEqual({r['id'] for r in rows['rows']},{'0','1','2','3'})
            self.assertEqual(rows['context']['breadcrumbs'][0]['label'],label)
            self.assertEqual(ranking(index,{'tone':'8A','key_notation':mode,'perspective':'all'})['total'],4)
            self.assertEqual(sum(g['entries'] for g in result['groups']),len(source['tracks']))
        counts=result['key_source_counts']
        self.assertEqual(counts,{'alphabetical':5,'camelot':3,'open_key':2,'numerical':5,'unknown':2,'unrecognized':2,'total':14})
        self.assertEqual(source,before)
        # Legacy API callers explicitly retaining source mode keep raw group keys.
        legacy=bubbles(index,{'dimension':'tone'})
        self.assertTrue({'Am','8A','1m'} <= {g['key'] for g in legacy['groups']})

    def test_unknown_exclusion_is_per_dimension_and_metric_and_keeps_known_zero(self):
        source=fixture();source['tracks'][1]['play_count']=None
        index=InsightIndex(source)
        result=bubbles(index,{'dimension':'tone','key_notation':'alpha','hide_unknown':'1'})
        self.assertEqual(result['excluded_unknown'],4);self.assertEqual(result['summary']['entries'],14)
        self.assertEqual(sum(g['entries'] for g in result['groups']),10)
        played=bubbles(index,{'dimension':'tone','metric':'plays','key_notation':'alpha','hide_unknown':True})
        self.assertEqual(played['excluded_unknown'],5)
        self.assertEqual(next(g for g in played['groups'] if g['key']==keys.parse('Am'))['entries'],3)
        artists=bubbles(index,{'dimension':'artist','hide_unknown':True})
        self.assertEqual(artists['excluded_unknown'],0)  # A band named Unknown is valid data.
        tones=tonalities(index,{'key_notation':'camelot','hide_unknown':True})
        self.assertEqual(sum(b['tracks'] for b in tones['bpm_histogram']),14)
        self.assertEqual(tones['excluded_unknown'],4)
        for args in ({'key_notation':'random'},{'hide_unknown':'maybe'}, {'key_notation':'alpha','tone':'key:99:minor'}):
            with self.assertRaises(ValueError):bubbles(index,args)

    def test_projection_api_csv_and_shared_alias_script_never_stage_original_key_changes(self):
        with TemporaryDirectory() as temp,patch.object(application,'DATA',Path(temp)):
            store=Store(Path(temp)/'workbench-sidecar.sqlite3');sid=store.save_snapshot(fixture(),'Key fixture')['id']
            before=store.snapshot(sid);client=workspace_client(application)
            for mode in ('alpha','camelot','open_key'):
                response=client.get('/api/insights/bubbles',query_string={'snapshot':sid,'dimension':'tone','key_notation':mode})
                self.assertEqual(response.status_code,200,response.json)
                response=client.get('/api/insights/tracks.csv',query_string={'snapshot':sid,'perspective':'all','key_notation':mode})
                rows=list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'))))
                self.assertEqual({r['id']:r['tonality'] for r in rows},{r['id']:r['tonality'] for r in before['tracks']})
            self.assertEqual(store.snapshot(sid),before);self.assertEqual(store.overrides(before['scope_key']),{})
            script=client.get('/api/key-notation.js')
            self.assertEqual(script.status_code,200);self.assertIn('text/javascript',script.content_type)
            self.assertNotIn('</script',script.text.lower());self.assertNotIn('Synthetic',script.text)

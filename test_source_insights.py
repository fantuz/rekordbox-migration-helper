"""Synthetic native snapshots and private report filtering; no installed DJ libraries."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from metadata_export import payload
from research_capture import capture_private_database
from source_insights import source_insights,inspect_smartlist,native_evidence
from task_control import OperationCancelled
from workbench_store import Store


def native_snapshot():
    """All IDs, names, rules and paths are invented for regression/acceptance checks."""
    with closing(sqlite3.connect(':memory:')) as db:
        db.executescript('''
          CREATE TABLE djmdContent(ID TEXT,Title TEXT,FolderPath TEXT,ArtistID TEXT,ComposerID TEXT,RemixerID TEXT,OrgArtistID TEXT,Lyricist TEXT,
             ReleaseDate TEXT,DiscNo INTEGER,TrackNo INTEGER,HotCueAutoLoad TEXT,Analysed INTEGER,AnalysisUpdated INTEGER,Length INTEGER);
          CREATE TABLE djmdArtist(ID TEXT,Name TEXT);
          CREATE TABLE djmdPlaylist(ID TEXT,Name TEXT,ParentID TEXT,Attribute INTEGER,SmartList TEXT);
          CREATE TABLE djmdMyTag(ID TEXT,Name TEXT,ParentID TEXT);
          CREATE TABLE djmdKey(ID TEXT,ScaleName TEXT);
          CREATE TABLE djmdCue(ID TEXT,ContentID TEXT,Kind INTEGER,InMsec INTEGER,OutMsec INTEGER,Comment TEXT,Color INTEGER,ActiveLoop INTEGER);
          INSERT INTO djmdArtist VALUES('artist','Synthetic artist'),('writer','Synthetic writer 日本');
          INSERT INTO djmdContent VALUES('a','Native evidence track','/Synthetic/a.wav','artist','writer','missing','artist','writer',
             '2024-03-01',2,7,'off',4,1,240);
          INSERT INTO djmdContent VALUES('b','Unknown evidence track','/Synthetic/b.wav',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
          INSERT INTO djmdMyTag VALUES('4258818180','Techno','root');
          INSERT INTO djmdKey VALUES('key','Am');
          INSERT INTO djmdCue VALUES('c','a',5,1000,2000,'Loop',3,1),('bad','b',99,-1,0,'Malformed',0,0);
        ''')
        xml='<NODE LogicalOperator="1"><CONDITION PropertyName="myTag" Operator="1" ValueLeft="-36149116"/><CONDITION PropertyName="key" Operator="1" ValueLeft="key"/></NODE>'
        db.execute('INSERT INTO djmdPlaylist VALUES (?,?,?,?,?)',('smart','Synthetic smart list','root',4,xml))
        db.execute('INSERT INTO djmdPlaylist VALUES (?,?,?,?,?)',('unsupported','Unknown rule','root',4,'<NODE LogicalOperator="2"><CONDITION PropertyName="futureField" Operator="1" ValueLeft="keep me"/></NODE>'))
        before=db.total_changes
        result=capture_private_database(db,'synthetic:native-insights')
        assert db.total_changes==before
    return result


class SourceInsightTests(unittest.TestCase):
    def test_role_ids_resolve_through_artist_lookup_and_keep_unknowns(self):
        source=native_snapshot();e=source['tracks'][0]['native_evidence']
        self.assertEqual(e['artist_roles']['lyricist']['name'],'Synthetic writer 日本')
        self.assertEqual(e['artist_roles']['lyricist']['raw_id'],'writer')
        self.assertEqual(e['artist_roles']['remixer']['state'],'unresolved')
        self.assertEqual(e['artist_roles']['remixer']['raw_id'],'missing')
        self.assertEqual(source['tracks'][1]['native_evidence']['artist_roles']['lyricist']['state'],'empty')
        old=native_evidence({},set(),{})
        self.assertEqual(old['artist_roles']['lyricist']['state'],'not_captured')
        self.assertIsNone(e['native_stems_readiness'])

    def test_native_units_and_null_flags_are_retained_without_stems_inference(self):
        source=native_snapshot();s,rows=source_insights(source)
        first=source['tracks'][0]['native_evidence'];last=source['tracks'][1]['native_evidence']
        self.assertEqual(first['fields']['Analysed']['raw'],4);self.assertIsNone(last['fields']['Analysed']['raw'])
        self.assertEqual(first['units']['Length'],'seconds');self.assertEqual(first['units']['InMsec'],'milliseconds')
        self.assertEqual(s['tracks_with_native_evidence'],2);self.assertIsNone(s['native_stems_readiness'])
        self.assertTrue(all(r['native_stems_readiness'] is None for r in rows if 'native_stems_readiness' in r))

    def test_rules_signed_tag_ids_and_key_lookup_are_decoded(self):
        source=native_snapshot();s,rows=source_insights(source)
        rule=next(r for r in rows if r.get('playlist_id')=='smart')
        self.assertEqual(rule['validation'],'recognized');self.assertFalse(rule['executable']);self.assertEqual(rule['match'],'all')
        self.assertEqual(rule['conditions'][0]['lookup_id'],'4258818180')
        self.assertEqual(rule['conditions'][0]['value']['name'],'Techno')
        self.assertEqual(rule['conditions'][1]['value'],'Am')
        self.assertEqual(s['smart_rules_recognized'],1);self.assertEqual(s['smart_rules_unsupported'],1)

    def test_unsupported_conditions_are_retained_in_the_complete_rule(self):
        xml='<NODE LogicalOperator="2"><CONDITION PropertyName="genre" Operator="1" ValueLeft="House"/><CONDITION PropertyName="futureField" Operator="88" ValueLeft="preserve"/></NODE>'
        r=inspect_smartlist(xml)
        self.assertEqual(r['validation'],'unsupported');self.assertEqual(len(r['conditions']),2)
        self.assertEqual(r['conditions'][1]['raw']['ValueLeft'],'preserve');self.assertEqual(r['match'],'any')

    def test_missing_definition_differs_from_malformed_and_unsupported(self):
        self.assertEqual(inspect_smartlist(None)['validation'],'not_checked')
        self.assertEqual(inspect_smartlist('<NODE>')['validation'],'corrupt')
        self.assertEqual(inspect_smartlist('<NODE/>')['validation'],'unsupported')
        self.assertEqual(inspect_smartlist('<NODE LogicalOperator="3"><CONDITION PropertyName="genre" Operator="1"/></NODE>')['validation'],'unsupported')

    def test_rule_parser_rejects_entities_excessive_nodes_and_nested_rules(self):
        for xml in ('<!DOCTYPE NODE [<!ENTITY x "hello">]><NODE>&x;</NODE>',
                    '<NODE LogicalOperator="1"><NODE/></NODE>',
                    '<NODE LogicalOperator="1">'+'<CONDITION/>'*129+'</NODE>',
                    'x'*65537):
            self.assertEqual(inspect_smartlist(xml)['validation'],'unsupported')

    def test_property_aliases_and_bpm_units_are_explicit(self):
        for property,field in (('grouping','colour'),('producer','composer'),('counter','play_count'),('name','title')):
            r=inspect_smartlist(f'<NODE LogicalOperator="1"><CONDITION PropertyName="{property}" Operator="1" ValueLeft="1"/></NODE>')
            self.assertEqual(r['conditions'][0]['field'],field)
        r=inspect_smartlist('<NODE LogicalOperator="1"><CONDITION PropertyName="bpm" Operator="5" ValueLeft="12800" ValueRight="13000"/></NODE>')
        self.assertEqual(r['conditions'][0]['value'],'12800');self.assertIn('unverified',r['conditions'][0]['unit'])

    def test_unresolved_key_tag_and_invalid_tag_range_never_become_supported(self):
        for prop,value in (('key','unknown'),('myTag','1'),('myTag',str(2**32)),('myTag','bad')):
            r=inspect_smartlist(f'<NODE LogicalOperator="1"><CONDITION PropertyName="{prop}" Operator="1" ValueLeft="{value}"/></NODE>')
            self.assertEqual(r['validation'],'unsupported')

    def test_cue_kinds_loops_and_time_sentinels(self):
        source=native_snapshot();s,rows=source_insights(source)
        self.assertEqual(s['cues_checked'],2);self.assertEqual(s['cue_anomalies'],1);self.assertEqual(s['active_loops'],1)
        source['tracks'][0]['cues']=[{'kind':17,'in_ms':1000,'out_ms':2**32-1,'active_loop':0}]
        self.assertEqual(source_insights(source)[0]['cue_anomalies'],1)
        source['tracks'][0]['cues']=[{'kind':5,'in_ms':2000,'out_ms':1000,'active_loop':1}]
        self.assertEqual(source_insights(source)[0]['cue_anomalies'],2)

    def test_old_and_xml_snapshots_report_unavailable_not_empty_evidence(self):
        s,rows=source_insights({'tracks':[{'id':'a'}],'playlists':[]})
        self.assertEqual(s['tracks_with_native_evidence'],0)
        self.assertEqual(rows[0]['validation'],'not_checked');self.assertEqual(rows[0]['section'],'source_capability')

    def test_row_budget_cancel_and_snapshot_immutability(self):
        source=native_snapshot();before=deepcopy(source)
        s,rows=source_insights(source,max_rows=1)
        self.assertEqual(len(rows),1);self.assertFalse(s['findings_complete']);self.assertGreater(s['findings'],1)
        self.assertEqual(source,before)
        def stop(*_):raise OperationCancelled('stop')
        with self.assertRaises(OperationCancelled):source_insights(source,stop)

    def test_shareable_metadata_excludes_private_rules_native_flags_and_role_ids(self):
        source=native_snapshot();exported=json.dumps(payload(source,'Synthetic'))
        for text in ('smart_definition','smart_rule_lookups','native_evidence','"writer"','-36149116'):
            self.assertNotIn(text,exported)


class ReportFilterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.store=Store(self.root/'sidecar.sqlite3')
        self.rows=[{'section':'analysis_format','severity':'review' if i%2 else 'info',
                    'validation':'corrupt' if i%2 else 'recognized','title':f'Synthetic {i:03}','detail':'bounded evidence'} for i in range(125)]
        self.report=self.store.save_report('formats',[],{},self.rows)['id']

    def test_filters_are_global_before_pagination_and_preserve_facets(self):
        first=self.store.report(self.report,severity='review',validation='corrupt')
        second=self.store.report(self.report,50,severity='review',validation='corrupt')
        self.assertEqual(first['total'],62);self.assertEqual(len(first['rows']),50);self.assertEqual(len(second['rows']),12)
        self.assertEqual(first['validations'],[{'validation':'corrupt','count':62},{'validation':'recognized','count':63}])
        self.assertEqual(first['sections'],[{'section':'analysis_format','count':125}])
        self.assertTrue(all(r['validation']=='corrupt' for r in first['rows']+second['rows']))

    def test_combined_filters_search_and_full_download_agree(self):
        r=self.store.report(self.report,section='analysis_format',query='Synthetic 01',severity='review',validation='corrupt',all_rows=True)
        self.assertEqual([x['title'] for x in r['rows']],['Synthetic 011','Synthetic 013','Synthetic 015','Synthetic 017','Synthetic 019'])
        with self.assertRaises(ValueError):self.store.report(self.report,severity='anything')
        with self.assertRaises(ValueError):self.store.report(self.report,validation="' OR 1=1")

    def test_old_reports_without_validation_remain_accessible(self):
        identity=self.store.save_report('old',[],{},[{'section':'old','severity':'info','title':'Old report'}])['id']
        self.assertEqual(self.store.report(identity)['total'],1);self.assertEqual(self.store.report(identity)['validations'],[])

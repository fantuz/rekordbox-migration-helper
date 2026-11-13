"""Colour edits stay in private sidecars and resolve real configured native IDs."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from xml.etree.ElementTree import Element

import app as application
from lab_routes import workspace_overrides
from metadata_export import track,payload
from metadata_overrides import validate,baseline,apply_xml,apply_native,change_summary,plan
from track_tags import PALETTE,colour_support,xml_colour,xml_colour_support,native_colour,native_colour_support
from workbench_store import Store


def database(schema='ColorID TEXT',rows="INSERT INTO djmdContent VALUES ('t','old',0);"):
    db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE djmdContent(ID TEXT,'+schema+',rb_local_deleted INTEGER);'+rows+'''
        CREATE TABLE djmdColor(ID TEXT,ColorCode INTEGER,SortKey INTEGER,Commnt TEXT,rb_local_deleted INTEGER);
        INSERT INTO djmdColor VALUES('real-red',NULL,2,'Peak time',0);
        INSERT INTO djmdColor VALUES('real-green',65280,5,'Warm up',0);
    ''')
    return db


def apply(db,value):
    tables={r[0]:{c[1] for c in db.execute('PRAGMA table_info('+r[0]+')')} for r in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    def update(table,where,params,values):
        db.execute('UPDATE '+table+' SET '+','.join(k+'=?' for k in values)+' WHERE '+where,[*values.values(),*params])
    return apply_native(db,tables,{'t':{'colour':value}},update,'2026-11-13',lambda:1)


class ColourExportTests(unittest.TestCase):
    def test_palette_validation_and_documented_xml_rgb_roundtrip(self):
        for _,code in PALETTE:
            self.assertEqual(validate('colour',code.lower()),code)
            e=Element('TRACK');apply_xml(e,{'colour':code})
            self.assertEqual(e.get('Colour'),'0x'+code[1:])
            self.assertEqual(xml_colour(e.get('Colour'))['color_hex'],code)
        e=Element('TRACK',Colour='0xFF0000');apply_xml(e,{'colour':''})
        self.assertEqual(xml_colour(e.get('Colour'))['color_status'],'unassigned')
        for bad in (None,0,False,'red','#123456','url(x)',''):
            if bad=='':self.assertEqual(validate('colour',bad),'')
            else:
                with self.assertRaises(ValueError):validate('colour',bad)

    def test_native_uses_actual_ids_and_unique_palette_row_without_creating_rows(self):
        with closing(database()) as db:
            self.assertEqual(apply(db,'#FF0000'),0)
            self.assertEqual(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0],'real-red')
            apply(db,'#00FF00');self.assertEqual(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0],'real-green')
            self.assertEqual(db.execute('SELECT count(*) FROM djmdColor').fetchone()[0],2)
            db.execute("INSERT INTO djmdColor VALUES('red-copy',16711680,NULL,'Other red',0)")
            with self.assertRaisesRegex(ValueError,'unique configured'):apply(db,'#FF0000')
            self.assertEqual(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0],'real-green')
            db.execute("UPDATE djmdColor SET rb_local_deleted=1 WHERE ID='red-copy'")
            apply(db,'#FF0000');self.assertEqual(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0],'real-red')
            with self.assertRaisesRegex(ValueError,'unique configured'):apply(db,'#660099')

    def test_numeric_colour_id_obeys_existing_content_column_affinity(self):
        with closing(database()) as db:
            db.execute('DROP TABLE djmdColor')
            db.execute('CREATE TABLE djmdColor(ID INTEGER,ColorCode INTEGER,SortKey INTEGER,Commnt TEXT,rb_local_deleted INTEGER)')
            db.execute("INSERT INTO djmdColor VALUES(17,16711680,2,'Red',0)")
            apply(db,'#FF0000')
            self.assertEqual(db.execute('SELECT ColorID,typeof(ColorID) FROM djmdContent').fetchone(),('17','text'))

    def test_clearing_preserves_empty_id_convention_or_schema_and_holds_unsupported(self):
        with closing(database()) as db:
            apply(db,'');self.assertIsNone(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0])
        with closing(database("ColorID TEXT NOT NULL DEFAULT '0'")) as db:
            apply(db,'');self.assertEqual(db.execute('SELECT ColorID FROM djmdContent').fetchone()[0],'0')
        with closing(database('ColorID TEXT NOT NULL')) as db:
            support=native_colour_support(db,{'djmdContent':{'ColorID'},'djmdColor':{'ID'}},[])
            self.assertFalse(support['palette'][-1]['supported']);self.assertIn('safely clear',support['palette'][-1]['reason'])
            with self.assertRaisesRegex(ValueError,'safely clear'):apply(db,'')
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE djmdContent(ID TEXT,rb_local_deleted INTEGER)');db.execute("INSERT INTO djmdContent VALUES('t',0)")
            with self.assertRaisesRegex(ValueError,'ColorID is unavailable'):apply(db,'#FF0000')

    def test_configured_palette_support_reports_missing_and_ambiguous_rows(self):
        columns={'djmdContent':{'ColorID'},'djmdColor':{'ID','SortKey','ColorCode','Commnt'}}
        rows=[{'ID':'configured','SortKey':2,'ColorCode':None,'Commnt':'Peak time'}]
        palette=colour_support(columns,rows)['palette'];red=next(p for p in palette if p['value']=='#FF0000')
        self.assertTrue(red['supported']);self.assertEqual(red['native_name'],'Peak time')
        self.assertFalse(next(p for p in palette if p['value']=='#0000FF')['supported'])
        self.assertFalse(next(p for p in colour_support(columns,rows+[{**rows[0],'ID':'another'}])['palette'] if p['value']=='#FF0000')['supported'])

    def test_donor_colour_conflicts_are_held_and_comments_appear_only_in_private_recap(self):
        c=SimpleNamespace(tracks={'t':{},'donor':{}},metadata={'field_overrides':{'t':{'colour':'#FF0000'},'donor':{'colour':'#00FF00'}}})
        with self.assertRaisesRegex(ValueError,'conflicting colour'):plan(c,{'donor':'t'})
        recap=change_summary({'t':{'comment':'Private note','colour':'#FF0000'}})
        self.assertEqual(recap['by_field'],{'comment':1,'colour':1});self.assertEqual(recap['fields'],2)
        self.assertIn('Private note',json.dumps(recap))
        s={'tracks':[track({'id':'t','comment':'Private note',**xml_colour('0xFF0000')})]}
        self.assertNotIn('Private note',json.dumps(payload(s,'Shareable')))


class ColourSidecarAPITests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()
        self.store=Store(self.root/'workbench-sidecar.sqlite3')
        self.s={'tracks':[track({'id':'t','title':'Track','comment':'Original private note',**native_colour('old-red',{'SortKey':2,'Commnt':'Peak time'})})],
                'scope_key':'session:synthetic','source_kind':'Synthetic','colour_edit_support':xml_colour_support()}
        self.identity=self.store.save_snapshot(self.s,'Test')['id']
        p=patch.object(application,'DATA',self.root);p.start();self.addCleanup(p.stop)
        self.client=application.app.test_client();self.headers={'X-Workbench-Token':application.TOKEN}

    def test_colour_and_comments_are_free_separately_logged_and_reset_returns_saved_recap(self):
        body={'snapshot':self.identity,'track_id':'t','field':'colour','value':'#00FF00'}
        r=self.client.post('/api/lab/overrides',json=body,headers=self.headers)
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['overrides']['colour']['value'],'#00FF00')
        comment=self.client.post('/api/lab/overrides',json={**body,'field':'comment','value':'Working private note'},headers=self.headers)
        self.assertEqual(comment.status_code,200);self.assertEqual(set(comment.json['overrides']),{'comment','colour'})
        detail=self.client.get('/api/lab/track',query_string={'snapshot':self.identity,'track_id':'t'}).json
        self.assertFalse(detail['unlocked']);self.assertTrue(detail['colour_editable']);self.assertEqual(len(detail['colour_palette']),9)
        self.assertEqual(detail['original']['colour'],'#FF0000');self.assertNotIn('colour',detail['editable_fields'])
        self.assertEqual(self.store.effective(self.store.snapshot(self.identity))['tracks'][0]['color_hex'],'#00FF00')
        self.assertEqual(self.store.snapshot(self.identity)['tracks'][0]['color_key'],'native:old-red')
        reset=self.client.delete('/api/lab/overrides',json=body,headers=self.headers)
        self.assertEqual(set(reset.json['overrides']),{'comment'})
        history=self.store.override_history('session:synthetic');self.assertEqual(len(history),3)
        self.assertIsNone(history[-1]['current']);self.assertEqual(history[-1]['previous'],'#00FF00')
        self.assertEqual(self.client.post('/api/lab/overrides',json=body).status_code,403)

    def test_baselines_include_native_identity_and_scope_never_crosses_to_other_library(self):
        t=self.s['tracks'][0];self.store.save_override('session:synthetic','t','colour','#00FF00',baseline('colour',t))
        changed=deepcopy(self.s);changed['tracks'][0]['color_key']='native:different-row-same-rgb'
        with self.assertRaisesRegex(ValueError,'baseline changed'):self.store.effective(changed)
        with self.assertRaisesRegex(ValueError,'baseline changed'):self.store.save_override('session:synthetic','t','colour','#0000FF',baseline('colour',changed['tracks'][0]))
        other=deepcopy(changed);other['scope_key']='capture:other'
        self.assertEqual(self.store.effective(other)['metadata_overrides_applied'],0)
        catalog=SimpleNamespace(tracks={'t':{**changed['tracks'][0],'track_id':'t'}},metadata={},cue_summary=lambda _:dict(auto=0,other=0))
        with self.assertRaisesRegex(ValueError,'baseline changed'):workspace_overrides(self.root,{'id':'synthetic','catalog':catalog})

    def test_bulk_route_applies_the_same_colour_support_guard(self):
        old=deepcopy(self.s);old.pop('colour_edit_support');identity=self.store.save_snapshot(old,'Old')['id']
        unlock=self.client.post('/api/lab/unlock',json={'snapshot':identity,'unlocked':True},headers=self.headers)
        self.assertEqual(unlock.status_code,200)
        r=self.client.post('/api/lab/normalize',json={'snapshot':identity,'track_ids':['t'],'field':'colour','value':'#FF0000'},headers=self.headers)
        self.assertEqual(r.status_code,400);self.assertIn('Capture this library again',r.json['error'])
        self.assertEqual(self.store.overrides('session:synthetic'),{})

    def test_private_export_report_keeps_changes_and_reset_history_with_count_only_manifest(self):
        from file_workflow import prepare_export
        self.store.save_override('session:synthetic','t','comment','Private edited note','Original private note')
        self.store.save_override('session:synthetic','t','colour','#00FF00',baseline('colour',self.s['tracks'][0]))
        self.store.clear_override('session:synthetic','t','colour')
        self.store.save_override('session:synthetic','t','colour','#0000FF',baseline('colour',self.s['tracks'][0]))
        evidence=self.store.overrides('session:synthetic')
        edits={identity:{f:e['value'] for f,e in fields.items()} for identity,fields in evidence.items()}
        xml=self.root/'source.xml';xml.write_text('<TRACK/>');backup=self.root/'source.zip';backup.write_bytes(b'fixture')
        catalog=SimpleNamespace(metadata={'xml_path':str(xml),'zip_path':str(backup),'field_overrides':edits})
        state={'id':'synthetic','metadata_override_evidence':evidence,'metadata_edit_history':self.store.override_history('session:synthetic')}
        def writer(c,d,r,path,p):path.write_bytes(b'output');return {'merges':0,'metadata_fields':1,'metadata_changes_by_field':{'comment':1},'metadata_tracks_outside_xml':1}
        result=prepare_export(catalog,{}, {},state,self.root/'exports','a'*32,'xml',lambda *_:None,xml_writer=writer)
        report=json.loads((Path(result['directory'])/'report.json').read_text())
        self.assertEqual(report['metadata_change_recap']['by_field'],{'comment':1,'colour':1})
        self.assertEqual(report['metadata_change_recap']['count_scope'],'staged')
        self.assertEqual(report['metadata_change_recap']['fields'],2)
        self.assertEqual(report['metadata_change_recap']['applied_by_format']['xml']['metadata_fields'],1)
        self.assertEqual(report['metadata_change_recap']['applied_by_format']['xml']['metadata_tracks_outside_xml'],1)
        self.assertEqual(len(report['session']['metadata_edit_history']),4)
        self.assertIn('Private edited note',json.dumps(report))
        manifest=json.loads((Path(result['directory'])/'export.json').read_text())
        self.assertNotIn('Private edited note',json.dumps(manifest))
        self.assertEqual(result['metadata_changes_by_field'],{'comment':1,'colour':1})
        self.assertEqual(result['metadata_count_scope'],'staged')
        self.assertEqual(result['applied_by_format']['xml']['metadata_changes_by_field'],{'comment':1})

    def test_old_snapshot_without_verified_mapping_cannot_silently_stage_colour(self):
        old=deepcopy(self.s);old.pop('colour_edit_support');identity=self.store.save_snapshot(old,'Old')['id']
        r=self.client.post('/api/lab/overrides',json={'snapshot':identity,'track_id':'t','field':'colour','value':'#FF0000'},headers=self.headers)
        self.assertEqual(r.status_code,400);self.assertIn('Capture this library again',r.json['error'])
        self.assertEqual(self.store.overrides('session:synthetic'),{})


if __name__=='__main__':unittest.main()

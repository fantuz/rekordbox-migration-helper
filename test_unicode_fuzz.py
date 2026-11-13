"""Bounded property-based tests. Synthetic inputs only, with reproducible CI runs."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from xml.etree import ElementTree as ET

try:
    from hypothesis import given,settings,strategies as st
except ImportError:
    raise unittest.SkipTest('Install requirements-test.txt for Unicode property tests')

from engine import export_xml,parse_xml,path_key
from metadata_export import export_metadata,track
from metadata_overrides import validate
from native_export import mutable_copy,rewrite_archive
from workbench_store import Store

ASSETS=Path(__file__).parent/'static'
CORPUS=['Straße · Grüße','Français œ ç','Città più','Español ñ ¿','Ελληνικά άς','Łódź żółć','Český řů','Русский ёж','日本語 中文 한글','🎧 👩🏽‍💻 𝄞','café','cafe\u0301','İ ı I i Σ σ ς','</script><img src=x onerror=alert(1)>','A & B <mix> "quote"',"'); DROP TABLE tracks; --",'=HYPERLINK("https://example.invalid")',' \t=1+1','\ufeff@SUM(1,1)','\n=1+1','\u202eabc\u202c','\u2028\u2029','{slot0} {count}',' leading and trailing ']
VALID=st.characters(min_codepoint=32,max_codepoint=0x10ffff,exclude_categories=('Cs',),exclude_characters='\ufffe\uffff')
TEXT=st.one_of(st.sampled_from(CORPUS),st.text(VALID,max_size=65))
BOUNDED=settings(max_examples=40,deadline=None,derandomize=True,database=None)


class UnicodePropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp=tempfile.TemporaryDirectory();cls.addClassCleanup(temp.cleanup)
        master=Path(temp.name)/'synthetic.db'
        with closing(mutable_copy(master)) as db:db.execute('CREATE TABLE synthetic(marker TEXT)');db.commit()
        cls.master=master.read_bytes()

    @BOUNDED
    @given(title=TEXT,artist=TEXT,album=TEXT,version=TEXT)
    def test_xml_copy_roundtrip_preserves_unicode_and_escapes_product_version(self,title,artist,album,version):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'collection.xml';backup=root/'backup.zip';output=root/'edited.xml'
            tree=ET.Element('DJ_PLAYLISTS');ET.SubElement(tree,'PRODUCT',Version='7.0.0')
            collection=ET.SubElement(tree,'COLLECTION',Entries='1')
            attrs={'TrackID':'one','Name':title,'Artist':artist,'Album':album,'Location':'file://localhost/C:/Music/Δοκιμή%20🎧%23%25.mp3'}
            ET.SubElement(collection,'TRACK',attrs);playlists=ET.SubElement(tree,'PLAYLISTS');node=ET.SubElement(playlists,'NODE',Name=album);ET.SubElement(node,'TRACK',Key='one')
            source.write_bytes(ET.tostring(tree,encoding='utf-8',xml_declaration=True))
            with zipfile.ZipFile(backup,'w') as archive:archive.writestr('master.db',self.master)
            before=[sha256(p.read_bytes()).hexdigest() for p in (source,backup)]
            catalog=SimpleNamespace(tracks={'one':{'october_xml':True}},metadata={'xml_path':str(source),'zip_path':str(backup),'version':version})
            export_xml(catalog,{}, {},output,lambda *_:None)
            checked,refs,read_version,_=parse_xml(output,lambda *_:None)
            self.assertEqual(checked['one']['attrs'],attrs);self.assertEqual(refs,['one']);self.assertEqual(read_version,version)
            self.assertEqual([sha256(p.read_bytes()).hexdigest() for p in (source,backup)],before)

    @BOUNDED
    @given(title=TEXT,artist=TEXT,album=TEXT)
    def test_sqlite_json_and_html_keep_source_strings_and_do_not_execute_markup(self,title,artist,album):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root/'working.sqlite3')
            entry=track({'id':'one','title':title,'artist':artist,'album':album,'playlists':[album]})
            snapshot={'tracks':[entry],'scope_key':'synthetic','source_kind':'Synthetic Unicode fixture'}
            saved=store.save_snapshot(snapshot,'Unicode fixture');restored=store.snapshot(saved['id'])
            for name,value in (('title',title),('artist',artist),('album',album)):self.assertEqual(restored['tracks'][0][name],value)
            result=export_metadata(restored,root/'exports','a'*32,ASSETS,lambda *_:None,title='Synthetic Unicode fixture')
            standalone=(Path(result['directory'])/'library.html').read_text(encoding='utf-8')
            marker='window.METADATA_SNAPSHOT=';encoded=standalone.split(marker,1)[1].split(';</script>',1)[0]
            data=json.loads(encoded);row=dict(zip(data['columns'],data['rows'][0]))
            for name,value in (('title',title),('artist',artist),('album',album)):self.assertEqual(row[name],value)
            self.assertNotIn('</script>',encoded.lower());self.assertNotIn('<img',encoded.lower())

    @settings(max_examples=25,deadline=None,derandomize=True,database=None)
    @given(name=TEXT,body=st.binary(max_size=2048),compression=st.sampled_from([zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED]))
    def test_zip_utf8_names_and_payloads_survive_raw_copy(self,name,body,compression):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source.zip';target=root/'edited.zip'
            member='audio/'+name.replace('/','_').replace('\\','_')+'.bin'
            with zipfile.ZipFile(source,'w') as archive:
                archive.writestr('master.db',b'old');archive.writestr(member,body,compress_type=compression)
            before=source.read_bytes();rewrite_archive(source,target,{'master.db':b'new'},lambda *_:None)
            with zipfile.ZipFile(target) as archive:
                self.assertIsNone(archive.testzip());self.assertEqual(archive.read(member),body);self.assertEqual(archive.read('master.db'),b'new')
            self.assertEqual(source.read_bytes(),before)

    def test_legacy_cp437_and_traversal_names_are_preserved_without_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'inside';root.mkdir();source=root/'source.zip';target=root/'edited.zip'
            with zipfile.ZipFile(source,'w') as archive:
                archive.writestr('master.db',b'old');archive.writestr('legacy/e.bin',b'legacy');archive.writestr('../outside.bin',b'not extracted')
            raw=source.read_bytes();self.assertEqual(raw.count(b'legacy/e.bin'),2)
            source.write_bytes(raw.replace(b'legacy/e.bin',b'legacy/\x82.bin'))
            rewrite_archive(source,target,{'master.db':b'new'},lambda *_:None)
            with zipfile.ZipFile(target) as archive:
                self.assertIsNone(archive.testzip());self.assertEqual(archive.read('legacy/é.bin'),b'legacy');self.assertEqual(archive.getinfo('legacy/é.bin').flag_bits&0x800,0)
                self.assertEqual(archive.read('../outside.bin'),b'not extracted')
            self.assertFalse((root.parent/'outside.bin').exists());self.assertFalse((root/'outside.bin').exists())

    def test_malformed_and_entity_xml_is_rejected_without_changing_its_bytes(self):
        examples=[b'<wrong/>',b'\xff\xfe<',b'<DJ_PLAYLISTS><COLLECTION><TRACK/></COLLECTION></DJ_PLAYLISTS>',
                  b'<DJ_PLAYLISTS><COLLECTION><POSITION_MARK Name="orphan"/></COLLECTION></DJ_PLAYLISTS>',
                  b'<DJ_PLAYLISTS><COLLECTION><TRACK TrackID="one"/></COLLECTION><PLAYLISTS><TRACK/></PLAYLISTS></DJ_PLAYLISTS>',
                  b'<!DOCTYPE DJ_PLAYLISTS [<!ENTITY attack SYSTEM "file:///not-read">]><DJ_PLAYLISTS>&attack;</DJ_PLAYLISTS>',
                  b'<DJ_PLAYLISTS><COLLECTION><TRACK TrackID="one" Name="\x00"/></COLLECTION></DJ_PLAYLISTS>']
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'malformed.xml'
            for body in examples:
                source.write_bytes(body)
                with self.assertRaises(ValueError):parse_xml(source,lambda *_:None)
                self.assertEqual(source.read_bytes(),body)

    def test_invalid_xml_controls_and_surrogates_are_rejected_explicitly(self):
        for bad in ('\x00','\x01','\x0b','\ud800','\udfff','\ufffe','\uffff'):
            with self.assertRaises(ValueError):validate('comment','before'+bad+'after')
        self.assertNotEqual(path_key('C:/Music/café.mp3'),path_key('C:/Music/cafe\u0301.mp3'))

    def test_all_requested_scripts_work_in_physical_file_paths(self):
        from file_workflow import select_inputs
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'Grüße Français Città Español Ελληνικά Łódź Český Русский 🎧';root.mkdir()
            paths={kind:root/('Συλλογή Łódź Český Русский 🎧.'+kind) for kind in ('xml','zip')}
            for path in paths.values():path.write_bytes(b'synthetic')
            self.assertEqual(select_inputs({key:str(value) for key,value in paths.items()}),{key:value.resolve() for key,value in paths.items()})

"""Real Rust batch -> JSON -> Helper verification -> explicit SQLite staging.

Only the provider is offline. Both sides use their production selection, tag IO,
report and review code. All files and database rows are synthetic and disposable.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
from time import perf_counter
from unittest import TestCase
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app
from onetagger_bridge import read_tags
from test_onetagger_bridge import OneTaggerBridgeTests
from test_onetagger_extended import extended_mp3


def mp4(path):
    def atom(kind,data):return struct.pack('>I',len(data)+8)+kind+data
    def text(kind,value):return atom(kind,atom(b'data',struct.pack('>II',1,0)+value.encode()))
    header=bytearray(100);header[12:16]=struct.pack('>I',1000);header[16:20]=struct.pack('>I',1000)
    metadata=b''.join(text(k,v) for k,v in [(b'\xa9nam','Original'),(b'\xa9ART','Artist'),(b'\xa9wrt','Composer')])
    movie=atom(b'mvhd',header)+atom(b'udta',atom(b'meta',bytes(4)+atom(b'ilst',metadata)))
    path.write_bytes(atom(b'ftyp',b'M4A \0\0\0\0M4A isom')+atom(b'moov',movie)+atom(b'mdat',b'preserve-media-payload'))


class RoundTrip(TestCase):
    setUp=OneTaggerBridgeTests.setUp

    def exercise(self,producer,output,version=2,cancelled=False):
        self.audio=self.root/'100%20 Café 日本.mp3';extended_mp3(self.audio)
        second=self.root/'Second.m4a';mp4(second)
        tracks=[{**self.track,'id':identity,'current_path':'D:/Music/'+path.name,
                 'label':'Library label','composer':'Library composer','bpm':128,'tonality':'8A',
                 'play_count':17,'cues':[{'in_ms':1000}],'playlists':['Preserve']}
                for identity,path in [('one',self.audio),('duplicate',self.audio),('mp4',second)]]
        self.sid=self.store.save_snapshot({'scope_key':self.before['scope_key'],'tracks':tracks},'Round trip')['id']
        before=deepcopy(self.store.snapshot(self.sid));original={p:p.read_bytes() for p in [self.audio,second]}
        response=self.client.post('/api/onetagger/export',json={'snapshot':self.sid,'track_ids':[t['id'] for t in tracks]},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json);identity=response.json['id'];base='/api/onetagger/'+identity
        manifest=json.loads(self.client.get(base+'/manifest').data)
        self.assertEqual(manifest['results_version'],2)
        if version==1:manifest.pop('results_version') # Exact legacy negotiation.
        selection=self.root/'selection.json';selection.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
        report_path=self.root/'producer-report.json'
        environment={**os.environ,'XDG_DATA_HOME':str(self.root/'producer-data'),
                     'ONETAGGER_ROUNDTRIP_SELECTION':str(selection),'ONETAGGER_ROUNDTRIP_REPORT':str(report_path),
                     'ONETAGGER_ROUNDTRIP_CANCEL':'1' if cancelled else '0'}
        start=perf_counter()
        subprocess.run(['cargo','test','-p','onetagger-autotag','--locked','--test','helper_roundtrip',
                        'produce_helper_report','--','--ignored','--nocapture'],cwd=producer,env=environment,check=True,timeout=1200)
        producer_seconds=perf_counter()-start
        raw=report_path.read_bytes();report=json.loads(raw);self.assertEqual(report['version'],version)
        tagged={p:p.read_bytes() for p in original}
        def launch(work,*_,**kwargs):work(lambda *_:None);return 'roundtrip'
        start=perf_counter()
        with patch.object(app,'launch',side_effect=launch),patch('onetagger_bridge.read_tags',wraps=read_tags) as reader:
            response=self.client.post(base+'/import-results',data=raw,content_type='application/json',headers=self.headers)
            self.assertEqual(response.status_code,200,response.json);reads=reader.call_count
        import_seconds=perf_counter()-start
        scan=self.client.get(base+'/review').json['scan']
        self.assertEqual(scan['report']['digest'],sha256(raw).hexdigest())
        self.assertEqual(self.store.overrides(before['scope_key']),{})
        if cancelled:
            self.assertTrue(scan['report']['cancelled']);self.assertEqual(scan['summary']['changes'],0)
            self.assertEqual(original,tagged);self.assertEqual(reads,0)
        else:
            self.assertEqual(scan['summary']['verified'],3,scan)
            self.assertEqual(reads,2,'Duplicate library IDs must share one file read')
            fields=('label','composer') if version==2 else ('genre',)
            self.client.post('/api/lab/unlock',json={'snapshot':self.sid,'unlocked':True},headers=self.headers)
            choices=[{'track_id':identity,'field':field} for identity in ('one','duplicate','mp4') for field in fields]
            with patch('onetagger_bridge.read_tags',wraps=read_tags) as reader:
                response=self.client.post(base+'/stage',json={'reviewed':True,'review_revision':scan['review_revision'],
                    'edit_revision':scan['edit_revision'],'changes':choices},headers=self.headers)
                self.assertEqual(response.status_code,200,response.json);self.assertEqual(reader.call_count,2)
            edits=self.store.overrides(before['scope_key'])
            self.assertEqual(set(edits),{'one','duplicate','mp4'})
            for values in edits.values():self.assertEqual(set(values),set(fields))
            self.assertEqual(self.store.snapshot(self.sid),before)
            for path,data in tagged.items():self.assertEqual(path.read_bytes(),data,'Helper modified audio')
            # Uploading stale evidence must keep the changed file ineligible.
            with self.audio.open('ab') as stream:stream.write(b'changed after report')
            with patch.object(app,'launch',side_effect=launch):
                self.assertEqual(self.client.post(base+'/import-results',data=raw,content_type='application/json',headers=self.headers).status_code,200)
            stale=self.client.get(base+'/review').json['scan'];self.assertEqual(stale['summary']['unreadable'],2)
        result={'version':version,'cancelled':cancelled,'tracks':3,'unique_files':2,'import_reads':reads,
                'producer_seconds':producer_seconds,'import_seconds':import_seconds,'passed':True,
                'producer_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=producer,text=True).strip(),
                'helper_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result))
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a',encoding='utf-8') as summary:
                summary.write(f"\n- Report v{version}, cancelled={cancelled}: passed; {reads} metadata reads for 3 library IDs / 2 files; import {import_seconds:.4f}s.\n")


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--producer',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    for version,cancelled in [(2,False),(1,False),(2,True)]:
        case=RoundTrip();case.setUp()
        try:case.exercise(args.producer.resolve(),args.output/f'v{version}-{"cancelled" if cancelled else "complete"}.json',version,cancelled)
        finally:case.doCleanups()


if __name__=='__main__':main()

"""CI-only synthetic 33k/100k duplicate-query time and incremental-memory budgets."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from time import perf_counter
import tracemalloc
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class SyntheticCatalog(SimpleNamespace):
    def cue_summary(self,identity):return {'total':0,'auto':0,'other':0}


def synthetic(count):
    tracks={};descriptions={};matches={}
    for index in range(count):
        identity=str(index)
        tracks[identity]={'track_id':identity,'title':'Synthetic '+identity,'artist':'Artist '+str(index%600),
                          'duration_seconds':180+index%300,'rating':index%6,'play_count':index%8,
                          'october_xml':True,'genre':'Genre '+str(index%20),'album':'Album '+str(index%300),
                          'label':'Label','current_path':'/synthetic/'+identity+'.mp3','bpm':120+index%20,
                          'bitrate':320,'playlist_ids':['all']}
        matches[identity]={'status':'found'}
        if index%3:
            keeper=str(index-index%3);pair=keeper+'~'+identity
            descriptions[pair]={'id':pair,'a':keeper,'b':identity,'keeper':keeper,
                                'title':tracks[keeper]['title'],'artist':tracks[keeper]['artist'],
                                'category':'review' if index%7==0 else 'ready',
                                'evidence':{'metadata_agrees':True,'rated':bool(index%6),
                                            'recorded_path_agrees':False,'grid_agrees':True}}
    return {'catalog':SyntheticCatalog(tracks=tracks,descriptions=descriptions,policy='newest'),
            'decisions':{},'held_pairs':{},'media_verifications':{},'inventory':{'matches':matches}}


def measure(count,in_scope,media_evidence):
    from pair_query import page
    session=synthetic(count)
    tracemalloc.start();started=perf_counter()
    first=page(session,{'filter':'all'},in_scope,media_evidence)
    cold=perf_counter()-started
    started=perf_counter()
    for offset in (40,80,120,160,200):
        page(session,{'filter':'all','offset':str(offset),'view':'groups' if offset==200 else ''},in_scope,media_evidence)
    warm=(perf_counter()-started)/5
    peak=tracemalloc.get_traced_memory()[1];tracemalloc.stop()
    builds=session['catalog']._pair_query_cache.builds
    if first['total']!=len(session['catalog'].descriptions) or builds!=1:
        raise AssertionError('Pagination rebuilt its graph or lost candidates')
    # Generous cross-runner ceilings catch accidental quadratic work. The JSON
    # measurements, rather than a fragile microbenchmark speed ratio, show drift.
    if cold>60 or warm>10 or peak>600*1024**2:
        raise AssertionError('Synthetic duplicate query exceeded its CI budget')
    return {'tracks':count,'pairs':first['total'],'groups':first['groups'],
            'cold_query_seconds':round(cold,5),'warm_page_seconds_mean':round(warm,5),
            'incremental_peak_bytes':peak,'graph_builds':builds,
            'budgets':{'cold_seconds':60,'warm_seconds':10,'incremental_peak_bytes':600*1024**2}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('ci-output/performance.json'))
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='workbench-benchmark-') as workspace:
        os.environ['LIBRARY_WORKBENCH_DATA_DIR']=workspace
        from app import in_scope,media_evidence
        results=[measure(count,in_scope,media_evidence) for count in (33000,100000)]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'status':'passed','scope':'Synthetic duplicate graph, real API filters, 40-row pages',
                                     'python':sys.version,'results':results},indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()

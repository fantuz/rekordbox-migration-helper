"""Read-only local insight APIs and explicitly retained report/download actions."""
from collections import OrderedDict
import csv
from io import StringIO
import json
from threading import RLock

from flask import jsonify,request

from dj_insights import InsightIndex,ranking,bubbles,tonalities
from workbench_store import Store


def register(owner):
    app=owner.app;cache=OrderedDict();guard=RLock()
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def index_for(identity):
        working=store()
        with working.connection() as db:r=db.execute('SELECT digest FROM snapshots WHERE id=?',(identity,)).fetchone()
        if r is None:raise ValueError('Choose a saved snapshot for DJ insights. Save one in Library lab or capture the loaded library.')
        key=(str(owner.DATA.resolve()),identity,r[0])
        with guard:
            if key not in cache:cache[key]=InsightIndex(working.snapshot(identity))
            cache.move_to_end(key)
            while len(cache)>2:cache.popitem(last=False)
            return cache[key]
    def filters(values):
        args=dict(values)
        if isinstance(args.get('path'),str):
            try:args['path']=json.loads(args['path'])
            except (TypeError,ValueError):raise ValueError('Invalid bubble branch path')
        if len(str(args.get('q','')))>1000:raise ValueError('Keep insight searches within 1,000 characters')
        return args

    @app.get('/api/insights/options')
    def options():return jsonify(**index_for(request.args.get('snapshot','')).options(),colour_meanings=store().setting('colour_meanings',{}))

    @app.get('/api/insights/tracks')
    def tracks():return jsonify(ranking(index_for(request.args.get('snapshot','')),filters(request.args)))

    @app.get('/api/insights/bubbles')
    def bubble_groups():return jsonify(bubbles(index_for(request.args.get('snapshot','')),filters(request.args)))

    @app.get('/api/insights/tonality')
    def tonality_groups():return jsonify(tonalities(index_for(request.args.get('snapshot','')),filters(request.args)))

    @app.post('/api/insights/colour-meanings')
    def colour_meanings():
        body=request.get_json(silent=True) or {};options=index_for(body.get('snapshot','')).options();values=body.get('meanings')
        if not isinstance(values,dict):raise ValueError('Choose colour labels to save locally')
        allowed={r['hex'] or r['key'] for r in options['colours'] if r['status']=='assigned'};saved=store().setting('colour_meanings',{})
        for key,label in values.items():
            if key not in allowed or not isinstance(label,str) or len(label)>120 or any(ord(c)<32 for c in label):raise ValueError('Colour meanings use up to 120 characters for assigned colours in this snapshot')
            if label.strip():saved[key]=label.strip()
            else:saved.pop(key,None)
        store().set_setting('colour_meanings',saved)
        return jsonify(meanings=saved,note='Local legend only; no rekordbox colour, track tag or source file is changed')

    @app.get('/api/insights/tracks.csv')
    def download_csv():
        args=filters(request.args);result=ranking(index_for(args.get('snapshot','')),args,all_rows=True)
        columns=('id','title','artist','album','genre','family','year','tonality','color_name','color_hex','color_status','bpm','rating','duration','format',
                 'plays','play_count','manual_cues','auto_cues','analysed','date_added','evidence_last_date','reason')
        stream=StringIO(newline='');writer=csv.writer(stream);writer.writerow((*columns,'usage_evidence'))
        def safe(value):
            if value is None:return ''
            if isinstance(value,str) and (value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n'))):return "'"+value
            return value
        for row in result['rows']:writer.writerow([safe(row.get(field)) for field in columns]+[result['context']['basis_label']])
        return app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename="dj-insights.csv"'})

    @app.post('/api/insights/report')
    def save_report():
        body=request.get_json(silent=True) or {};args=body.get('filters',{})
        if not isinstance(args,dict):raise ValueError('Choose valid insight filters')
        args=filters(args);args.pop('offset',None);identity=body.get('snapshot','')
        result=ranking(index_for(identity),args,limit=200)
        summary={**result['result_stats'],'perspective':result['title'],'scope':result['scope_stats'],
                 'evidence':result['context'],'filters':args,'eligible_entries':result['eligible'],
                 'retained_track_rows':len(result['rows']),'row_limit':200,
                 'note':'Retains the first 200 ranked/sample rows, plus full view counts and filters. CSV downloads can include the complete matching view.'}
        rows=[{**r,'section':'track_insight','track_id':r['id'],'detail':r['reason'] or result['context']['basis_label']} for r in result['rows']]
        report=store().save_report('DJ insights',[identity],summary,rows)
        return jsonify(**report,download='/api/lab/reports/'+report['id']+'/download')

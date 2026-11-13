"""Local read-only intelligence; deliberate report exports live in the sidecar."""
from flask import jsonify, request
from workbench_store import Store
from library_intelligence import playlists,playlist_overlap,session_progression,evolution,duplicate_impact
from metadata_export import capture_catalog
from engine import decision_map


def register(owner):
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def identity(value):
        if not isinstance(value,str) or not value or len(value)>128:
            raise ValueError('Choose a saved Library lab snapshot')
        return value
    def captured(saved,value):return saved.snapshot(identity(value))
    def snapshot():return captured(store(),request.args.get('snapshot',''))
    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide an intelligence report request')
        return value

    @owner.app.get('/api/intelligence/options')
    def options():
        s=snapshot()
        return jsonify(playlists=[{k:p[k] for k in ('id','name','order_available')} for p in playlists(s)],
                       histories=[{'id':h['id'],'name':h.get('name',''),'date':h.get('date')} for h in s.get('histories',[]) if not h.get('folder')],
                       history_order=s.get('capabilities',{}).get('history_order',False))

    @owner.app.get('/api/intelligence/playlists')
    def overlap():return jsonify(playlist_overlap(snapshot(),request.args.get('playlist',''),request.args.get('minimum',.5),request.args.get('offset',0)))

    @owner.app.get('/api/intelligence/session')
    def progression():return jsonify(session_progression(snapshot(),request.args.get('history',''),request.args.get('offset',0)))

    @owner.app.get('/api/intelligence/evolution')
    def changed():
        saved=store()
        return jsonify(evolution(captured(saved,request.args.get('before','')),captured(saved,request.args.get('after',''))))

    @owner.app.post('/api/intelligence/duplicate-impact')
    def duplicates():
        with owner.lock:
            session=owner.current();mapping,_=decision_map(session['catalog'],session['decisions'])
            result=duplicate_impact(capture_catalog(session['catalog']),mapping)
        return jsonify(result)

    @owner.app.post('/api/intelligence/report')
    def report():
        values=body();kind=values.get('kind');saved=store()
        # Recompute server-side; never treat an arbitrary browser-supplied report as evidence.
        if kind=='evolution':
            sources=[values.get('before',''),values.get('after','')]
            result=evolution(*(captured(saved,i) for i in sources))
        elif kind=='playlists':
            sources=[values.get('snapshot','')]
            result=playlist_overlap(captured(saved,sources[0]),values.get('playlist',''),values.get('minimum',.5),values.get('offset',0))
        elif kind=='session':
            sources=[values.get('snapshot','')]
            result=session_progression(captured(saved,sources[0]),values.get('history',''),values.get('offset',0))
        else:raise ValueError('Choose an intelligence report')
        result['retained_page_only']=kind in ('playlists','session')
        record=saved.save_report('Library intelligence: '+kind,sources,{k:v for k,v in result.items() if k!='rows'},
                                 [{'section':kind,'detail':result['basis'],**r} for r in result.get('rows',[])])
        return jsonify(**record,download='/api/lab/reports/'+record['id']+'/download')

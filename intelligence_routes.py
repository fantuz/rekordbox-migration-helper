"""Local read-only intelligence; deliberate report exports live in the sidecar."""
from result_order import page_result,scan_statuses
from flask import jsonify, request
from workbench_store import Store
from collection_sources import resolve
from library_intelligence import playlists,playlist_overlap,session_progression,evolution,duplicate_impact,playlist_contents,collection_lenses
from metadata_export import capture_catalog
from engine import decision_map
from chart_playlists import ChartClient,match_chart,chart_m3u
from serato_bridge import draft_package,preview_package


def register(owner):
    charts=ChartClient()
    def clear_chart_cache():
        with charts.lock:charts.cache.clear()
    owner.clear_chart_cache=clear_chart_cache
    def store():return Store(owner.DATA/'workbench-sidecar.sqlite3')
    def identity(value):
        if not isinstance(value,str) or not value or len(value)>128:
            raise ValueError('Choose a saved Library lab snapshot')
        return value
    def captured(saved,value):
        value=identity(value)
        result=resolve(owner,value) if value.startswith(('capture:','snapshot:')) else saved.snapshot(value)
        if value.startswith('capture:'):result['id']=value
        return result
    def snapshot():return captured(store(),request.args.get('snapshot',''))
    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ValueError('Provide an intelligence report request')
        return value

    @owner.app.get('/api/intelligence/options')
    def intelligence_options():
        s=snapshot()
        return jsonify(playlists=[{k:p[k] for k in ('id','name','order_available')}|{'entries':len(p['tracks']),'smart':p['smart']} for p in playlists(s)],
                       histories=[{'id':h['id'],'name':h.get('name',''),'date':h.get('date')} for h in s.get('histories',[]) if not h.get('folder')],
                       playlist_membership='playlists' in s or bool(s['tracks']) and all('playlists' in t for t in s['tracks']),
                       history_order=s.get('capabilities',{}).get('history_order',False),history_details=s.get('capabilities',{}).get('history_details',False))

    def sorted_view(kind,values):
        s=captured(store(),values.get('snapshot',''))
        operations={'playlists':lambda:playlist_overlap(s,values.get('playlist',''),values.get('minimum',.5),all_rows=True),
                    'contents':lambda:playlist_contents(s,values.get('playlist',''),values.get('q',''),all_rows=True),
                    'lenses':lambda:collection_lenses(s,values.get('lens','unfiled'),values.get('q',''),all_rows=True),
                    'session':lambda:session_progression(s,values.get('history',''),all_rows=True)}
        fields={'playlists':('name','common_tracks','tracks','jaccard','same_saved_order'),
                'contents':('sequence','title','artist','genre','bpm','rating','file_status'),
                'lenses':('title','artist','genre','playlists','saved_sessions','saved_entries','file_status'),
                'session':('sequence','title','artist','bpm','bpm_delta','tonality','color_name','file_status')}
        return page_result(operations[kind](),values,fields[kind],
                           statuses=None if kind=='playlists' else scan_statuses(store(),s))

    @owner.app.get('/api/intelligence/playlists')
    def intelligence_overlap():return jsonify(sorted_view('playlists',request.args))

    @owner.app.get('/api/intelligence/contents')
    def intelligence_contents():return jsonify(sorted_view('contents',request.args))

    @owner.app.get('/api/intelligence/lenses')
    def intelligence_lenses():return jsonify(sorted_view('lenses',request.args))

    @owner.app.get('/api/intelligence/session')
    def intelligence_progression():return jsonify(sorted_view('session',request.args))

    @owner.app.get('/api/intelligence/evolution')
    def intelligence_changed():
        saved=store()
        return jsonify(evolution(captured(saved,request.args.get('before','')),captured(saved,request.args.get('after',''))))

    @owner.app.post('/api/intelligence/duplicate-impact')
    def intelligence_duplicates():
        with owner.lock:
            session=owner.current();mapping,_=decision_map(session['catalog'],session['decisions'])
            result=duplicate_impact(capture_catalog(session['catalog']),mapping)
        return jsonify(result)

    @owner.app.post('/api/intelligence/report')
    def intelligence_report():
        values=body();kind=values.get('kind');saved=store()
        # Recompute server-side; never treat an arbitrary browser-supplied report as evidence.
        if kind=='evolution':
            sources=[values.get('before',''),values.get('after','')]
            result=evolution(*(captured(saved,i) for i in sources))
        elif kind in ('playlists','contents','lenses','session'):
            sources=[values.get('snapshot','')]
            result=sorted_view(kind,values)
        else:raise ValueError('Choose an intelligence report')
        result['retained_page_only']=kind in ('playlists','session','contents','lenses')
        record=saved.save_report('Library intelligence: '+kind,sources,{k:v for k,v in result.items() if k!='rows'},
                                 [{'section':kind,'detail':result['basis'],**r} for r in result.get('rows',[])])
        return jsonify(**record,download='/api/lab/reports/'+record['id']+'/download')

    @owner.app.post('/api/intelligence/chart')
    def intelligence_chart():
        values=body()
        if values.get('network_consent') is not True:raise ValueError('Confirm fetching the public ListenBrainz chart')
        saved=store();s=captured(saved,values.get('snapshot',''))
        result=match_chart(s,charts.fetch(values.get('period','week')))
        report=saved.save_report('ListenBrainz chart draft',[values.get('snapshot','')],{k:v for k,v in result.items() if k!='rows'},
                                 [{'section':'chart',**r} for r in result['rows']])
        return jsonify(**result,report_id=report['id'])

    @owner.app.post('/api/intelligence/chart/export')
    def intelligence_chart_export():
        values=body()
        if values.get('reviewed') is not True:raise ValueError('Review the chart matches before exporting')
        saved=store();report=saved.report(identity(values.get('report_id','')),all_rows=True)
        if report['kind']!='ListenBrainz chart draft':raise ValueError('Choose a chart draft')
        s=captured(saved,report['sources'][0])
        text=chart_m3u(s,report,values.get('selected'))
        return owner.app.response_class(text,mimetype='audio/x-mpegurl',
            headers={'Content-Disposition':'attachment; filename="listenbrainz-chart.m3u8"'})

    @owner.app.post('/api/intelligence/serato/preview')
    def intelligence_serato_preview():
        values=body()
        return jsonify(preview_package(captured(store(),values.get('snapshot','')),values.get('volume_root',''),values.get('target_profile','auto'),values.get('target_volume_root','')))

    @owner.app.post('/api/intelligence/serato')
    def intelligence_serato():
        values=body()
        if values.get('draft_acknowledged') is not True:raise ValueError('Confirm that this is an unverified Serato interoperability draft')
        s=captured(store(),values.get('snapshot',''))
        payload,_=draft_package(s,values.get('volume_root',''),values.get('target_profile','auto'),values.get('target_volume_root',''))
        return owner.app.response_class(payload,mimetype='application/zip',
            headers={'Content-Disposition':'attachment; filename="serato-draft.zip"'})

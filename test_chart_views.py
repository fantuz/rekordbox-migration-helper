"""Unknown values are excluded independently from each complete chart."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import app as application
from chart_views import release_year
from collection_views import statistics
from test_support import workspace_client
from workbench_store import Store


class ChartProjectionTests(unittest.TestCase):
    def test_year_parser_accepts_saved_year_or_valid_iso_release_date_without_guessing(self):
        for raw,expected in [(2024,'2024'),('2001','2001'),('2020-02-29','2020'),('2020-12','2020'),
                             ('2021-02-29',None),('2024-13',None),(0,None),(True,None),(float('nan'),None),
                             ('not captured',None),('01/02/2024',None),(2024.5,None)]:
            self.assertEqual(release_year({'year':raw}),expected,raw)
        self.assertEqual(release_year({'year':0,'release_date':'1999-05-08'}),'1999')

    def source(self):
        return {'scope_key':'synthetic:charts','tracks':[
            {'id':'zero','duration':0,'year':2024,'genre':'House','date_added':None},
            {'id':'duration-missing','duration':None,'year':1990,'genre':'Techno','date_added':'2020-01-01'},
            {'id':'genre-missing','duration':120,'year':0,'genre':'Unknown','date_added':'2021-04-09'},
            {'id':'year-missing','duration':240,'year':None,'genre':'日本語 <synthetic>','date_added':None}],
            'playlists':[],'capabilities':{}}

    def test_each_histogram_conserves_its_scope_and_never_excludes_unrelated_unknown_fields(self):
        source=self.source();before=deepcopy(source)
        for hide in (False,True):
            result=statistics(source,hide=hide);self.assertEqual(result['counters']['total'],4)
            for name,expected_known in [('duration',3),('added',2),('release_year',2),('genre',3)]:
                chart=result['charts'][name]
                self.assertEqual(chart['known'],expected_known,name)
                self.assertEqual(chart['displayed']+chart['excluded'],4,name)
                self.assertEqual(sum(r['count'] for r in chart['rows']),chart['displayed'])
                self.assertEqual(any(r.get('unknown') for r in chart['rows']),not hide)
            self.assertEqual(result['charts']['duration']['rows'][0]['count'],1)  # known zero seconds
            self.assertIn('Techno',[r['label'] for r in result['charts']['genre']['rows']])
        limited=statistics(source,minimum=100,maximum=300,hide=True)
        self.assertEqual(limited['counters']['total'],2);self.assertEqual(limited['unknown_duration'],0)
        self.assertEqual(limited['charts']['genre']['excluded'],1)
        self.assertEqual(source,before)

    def test_large_genre_chart_aggregates_small_known_categories_without_dropping_them(self):
        source=self.source();source['tracks']=[{'id':str(i),'genre':'Genre '+str(i),'duration':60,'year':2000} for i in range(150)]
        chart=statistics(source,hide=True)['charts']['genre']
        self.assertEqual(chart['categories_total'],150);self.assertEqual(len(chart['rows']),61)
        self.assertEqual(chart['displayed'],150);self.assertEqual(chart['excluded'],0)
        self.assertEqual(chart['rows'][-1]['count'],90);self.assertEqual(chart['rows'][-1]['categories'],90)

    def test_collection_api_cache_separates_unknown_display_choices_and_keeps_snapshot_immutable(self):
        with TemporaryDirectory() as temp,patch.object(application,'DATA',Path(temp)):
            store=Store(Path(temp)/'workbench-sidecar.sqlite3');sid=store.save_snapshot(self.source(),'Synthetic charts')['id']
            source=store.snapshot(sid);client=workspace_client(application)
            for hide in ('0','1','0'):
                response=client.get('/api/collection/statistics',query_string={'source':'snapshot:'+sid,'hide_unknown':hide})
                self.assertEqual(response.status_code,200,response.json)
                self.assertEqual(response.json['charts']['genre']['displayed'],3 if hide=='1' else 4)
            self.assertEqual(client.get('/api/collection/statistics',query_string={'source':'snapshot:'+sid,'hide_unknown':'unsupported'}).status_code,400)
            self.assertEqual(store.snapshot(sid),source)

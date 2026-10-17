"""Lifespan must boot from a cold index over the real cached OSM data."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import geocoding as geo, main


class NameIndexStartupTests(unittest.TestCase):
    def test_incomplete_nodes_ways_and_poi_relations_do_not_crash_startup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);osm=root/'osm';osm.mkdir()
            elements=[
                {'type':'relation','id':20675274,'tags':{'name':'Broken relation','amenity':'school'}},
                {'type':'node','id':1,'lat':10.761,'lon':106.690},
                {'type':'node','id':2,'tags':{'name':'No location','shop':'books'}},
                {'type':'way','id':3,'nodes':[999],'tags':{'name':'Missing road','highway':'residential'}},
                {'type':'way','id':4,'nodes':[1,999],'tags':{'name':'Hẻm 5/2A Fixture','highway':'residential'}},
                {'type':'node','id':5,'lat':10.762,'lon':106.690,'tags':{'name':'Fixture POI','office':'company'}},
            ]
            (osm/'broken.json').write_text(json.dumps({'elements':elements}))
            with patch.object(geo,'OSM_DIR',osm),patch.object(geo,'INDEX_FILE',root/'index.json'),patch.object(geo,'_names',None):
                result=geo.initialize_name_index()
            self.assertEqual({p['label'] for p in result},{'Hẻm 5/2A Fixture','Fixture POI'})

    def test_real_cached_data_cold_index_and_main_lifespan(self):
        # Keep the complete real OSM cache read-only. Force a cold rebuild into a
        # disposable index and disable the background tide refresher/network.
        from app.config import ROOT
        real_cache=ROOT/'backend/cache/osm'
        self.assertTrue((real_cache/'demo_binhthanh.json').exists())
        with tempfile.TemporaryDirectory() as d,patch.object(geo,'OSM_DIR',real_cache), \
             patch.object(geo,'INDEX_FILE',Path(d)/'real-index.json'),patch.object(geo,'_names',None), \
             patch.object(main,'CACHED_ONLY',True), \
             patch.object(geo.httpx,'get',side_effect=AssertionError('Startup must not contact providers')):
            with TestClient(main.app) as client:
                self.assertTrue(geo._names)
                self.assertGreater(len(geo._names),1000)
                self.assertEqual(client.get('/api/vehicles').status_code,200)
            self.assertTrue((Path(d)/'real-index.json').exists())

if __name__=='__main__':unittest.main()

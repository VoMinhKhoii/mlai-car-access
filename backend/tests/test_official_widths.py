"""Official ROW metadata must never become vehicle-fit Evidence."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import evidence, official_widths
from app.osm import AreaGraph, Way


def product(width=1):
    return {'schema_version':1,'semantics':'official_historical_and_planned_metadata_only',
            'sources':{'test':{'title':'Official historic plan','reuse':'attribution'}},
            'ways':{'123':[{'id':'test-1','source_id':'test','source_date':'2009-02-16',
                            'url':'https://example.gov.vn/plan','road_base_width_m':None,
                            'planned_right_of_way_m':[width,width]}]}}


class OfficialWidthMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'product.json'
        self.patcher=patch.object(official_widths,'PATH',self.path);self.patcher.start()
        self.previous=(official_widths._stamp,official_widths._data)
        official_widths._stamp,official_widths._data=None,{}

    def tearDown(self):
        official_widths._stamp,official_widths._data=self.previous
        self.patcher.stop();self.temp.cleanup()

    def test_planned_width_neither_changes_clear_width_nor_creates_official_coverage(self):
        self.path.write_text(json.dumps(product()))
        g=AreaGraph((10.8,106.7));g.nodes={1:(10.8,106.7),2:(10.8002,106.7)}
        w=Way(123,{'highway':'service','service':'alley','width':'4'},[1,2]);g.ways={123:w}
        store=evidence.EvidenceStore()
        with patch.object(evidence,'STORE_EVIDENCE',store):
            before=evidence.width_ranges(g)[123]
            records=before.to_json()['official_width_records']
            self.assertEqual(records[0]['tier'],'Official')
            self.assertFalse(records[0]['affects_clear_width'])
            self.assertEqual(before.top_tier,'Observed')
            self.assertTrue(all(b.tier!='Official' for b in before.evidence))
            self.path.unlink()
            after=evidence.width_ranges(g)[123]
            self.assertEqual((before.lo,before.hi),(after.lo,after.hi))
            self.assertEqual(after.official_width_records,[])

    def test_replacement_invalidates_serialized_plan_cache_and_deletion_removes_metadata(self):
        self.path.write_text(json.dumps(product()))
        store=type('Store',(),{'version':0})()
        official_widths.refresh(store);self.assertEqual(store.version,1)
        official_widths.refresh(store);self.assertEqual(store.version,1)
        self.path.write_text(json.dumps(product(12)))
        official_widths.refresh(store);self.assertEqual(store.version,2)
        self.assertEqual(official_widths.for_way(123)[0]['planned_right_of_way_m'],[12,12])
        self.path.unlink();official_widths.refresh(store)
        self.assertEqual(store.version,3);self.assertEqual(official_widths.for_way(123),[])

    def test_corrupt_or_nonfinite_replacement_keeps_last_good_product(self):
        self.path.write_text(json.dumps(product(6)));official_widths.snapshot()
        self.path.write_text('{broken');official_widths.snapshot()
        self.assertEqual(official_widths.for_way(123)[0]['planned_right_of_way_m'],[6,6])
        self.path.write_text(json.dumps(product(float('nan'))));official_widths.snapshot()
        self.assertEqual(official_widths.for_way(123)[0]['planned_right_of_way_m'],[6,6])

    def test_source_record_mutation_cannot_change_cached_product(self):
        self.path.write_text(json.dumps(product(6)))
        first=official_widths.for_way(123);first[0]['planned_right_of_way_m'][0]=99
        self.assertEqual(official_widths.for_way(123)[0]['planned_right_of_way_m'],[6,6])


if __name__=='__main__':unittest.main()

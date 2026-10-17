import unittest
from unittest.mock import patch
from shapely.geometry import LineString
from app import evidence as ev, parcels, plan, vehicles


class WidthBottleneckTests(unittest.TestCase):
    def fuse_parcels(self, widths):
        store = object.__new__(ev.EvidenceStore)
        store.by_way, store.by_name = {}, {}
        store.live = {'test': {'listings': [], 'photos': [], 'parcels': [
            {'way_id': 20, 'samples': widths, 'cuts': [{'width_m': x, 'gap_m': x+1} for x in widths]}]}}
        store._load_live()
        return store.by_way[20][0]

    def test_real_bottleneck_is_never_discarded(self):
        b = self.fuse_parcels([1,4,4,4,4])
        self.assertLessEqual(b.hi, 1.3)
        self.assertEqual(plan.fit_class(ev.WidthRange(b.lo, b.hi, b.tier), vehicles.get_profile('toyota-vios')), 'no')

    def test_one_cut_does_not_certify_whole_way_even_with_listing(self):
        b = self.fuse_parcels([6])
        lo, hi, tier, review, _ = ev._combine([b, ev.Bound(5,6,'Declared','listing','')])
        self.assertFalse(b.coverage_complete)
        self.assertEqual(plan.fit_class(ev.WidthRange(lo,hi,tier,review=review), vehicles.get_profile('toyota-vios')), 'unknown')

    def test_conflicting_measurements_cannot_be_resolved_by_listing(self):
        bounds = [ev.Bound(.9,1.1,'Measured','narrow',''), ev.Bound(4,4.2,'Measured','wide',''),
                  ev.Bound(4,4.1,'Declared','listing','')]
        lo,hi,tier,review,_ = ev._combine(bounds)
        self.assertEqual((lo,hi), (.9,4.2))
        self.assertTrue(review)
        self.assertEqual(plan.fit_class(ev.WidthRange(lo,hi,tier,review=review), vehicles.get_profile('toyota-vios')), 'unknown')

    def test_harmless_lower_tier_conflict_does_not_poison_measurement(self):
        result = ev._combine([ev.Bound(4,4.1,'Measured','tape',''), ev.Bound(1,2,'Declared','a',''),
                              ev.Bound(5,6,'Declared','b','')])
        self.assertEqual(result[:4], (4,4.1,'Measured',False))

    def test_invalid_junction_cut_is_not_reintroduced_from_samples(self):
        store = object.__new__(ev.EvidenceStore)
        store.by_way, store.by_name = {}, {}
        store.live = {'test': {'listings': [], 'photos': [], 'parcels': [
            {'way_id': 20, 'samples': [6], 'cuts': [{'width_m': 6, 'gap_m': 7, 'valid': False}]}]}}
        store._load_live()
        bounds=store.by_way[20]+[ev.Bound(6,7,'Declared','listing','')]
        lo,hi,tier,review,_=ev._combine(bounds)
        self.assertEqual(lo,0)
        self.assertEqual(plan.fit_class(ev.WidthRange(lo,hi,tier,review=review),vehicles.get_profile('toyota-vios')),'unknown')

    def test_corner_cut_rejected_before_lookup(self):
        with patch.object(parcels, '_cross_section', return_value=5.66) as lookup:
            self.assertIsNone(parcels._cut_at(LineString([(0,0),(20,0),(20,20)]),20,10.8,106.71))
            lookup.assert_not_called()


if __name__ == '__main__': unittest.main()

"""Portal provenance is independent of cache format and physical verification."""
import pytest
from app import evidence, live, plan, vehicles
from .test_engine_quality import street_graph, cut
from .test_engine_compare import ARRIVE


def test_city_and_legacy_portal_cuts_have_identical_official_provenance(monkeypatch):
    g = street_graph()
    cuts = [cut(20, 2.9), cut(30, 2.9)]
    parcel = {'way_id': 20, 'samples': [2.9, 2.9], 'cuts': cuts, 'deep': True}
    monkeypatch.setattr(live, 'city_parcels', lambda: {'20': {k: v for k, v in parcel.items() if k != 'way_id'}})
    widths = []
    for records in ([parcel], live._merge_city(g, [])):
        index = evidence.EvidenceIndex()
        index.add_areas([{'listings': [], 'photos': [], 'parcels': records}])
        ws = evidence.width_ranges(g, evidence.EvidenceView(index))
        widths.append(ws[20])
        wr = ws[20]
        assert (wr.top_tier, wr.lo) == ('Official', 0)
        assert wr.hi == pytest.approx(3.2)
        assert wr.sampled_estimate()['value_m'] == 2.9
        assert not wr.decisive_clearance
        assert not wr.sampled_estimate()['guarantees_clearance']
        assert plan.fit_class(wr, vehicles.get_profile('vinfast-vf-3')) == 'unknown'
    assert widths[0].sampled_estimate() == widths[1].sampled_estimate()


def test_sample_point_and_noncontinuous_range_reach_profile_and_comparison(monkeypatch):
    from app import flags
    g = street_graph()
    index = evidence.EvidenceIndex()
    index.add_areas([{'listings': [], 'photos': [], 'parcels': [
        {'way_id': 20, 'samples': [2.9, 2.9], 'cuts': [cut(20, 2.9), cut(30, 2.9)]}]}])
    ws = evidence.width_ranges(g, evidence.EvidenceView(index))
    ws[20].width_basis = 'unknown'  # Mixed weaker bounds must not hide the sample's parcel basis.
    monkeypatch.setattr(plan, 'area', lambda *args, **kwargs: (g, ws, {}))
    monkeypatch.setattr(flags, 'enabled', lambda name: False)
    r = plan.compare_vehicles(10.8, 106.7+25/109400, 'park', ARRIVE, 60, [], '', ['vinfast-vf-3'])
    segment = next(s for s in r['profile'] if s['way_id'] == 20)
    limiting = r['vehicles'][0]['limiting']
    for item in (segment, limiting):
        assert (item['estimate_m'], item['width_lo'], item['width_hi'], item['tier']) == (2.9, 0, 3.2, 'Official')
        assert 'not continuous clear width' in item['caveat']
    assert segment['sampled']


def test_unlocated_portal_cut_keeps_raw_point_without_certifying_clearance():
    index = evidence.EvidenceIndex()
    index.add_areas([{'listings': [], 'photos': [], 'parcels': [
        {'way_id': 20, 'samples': [2.9], 'cuts': [{'width_m': 2.9, 'gap_m': 3.9, 'at_m': 20}]}]}])
    wr = evidence.width_ranges(street_graph(), evidence.EvidenceView(index))[20]
    assert wr.top_tier == 'Official'
    assert wr.sampled_estimate()['value_m'] == 2.9
    assert not wr.decisive_clearance
    assert plan.fit_class(wr, vehicles.get_profile('vinfast-vf-3')) == 'unknown'

"""Safety regressions for the calibrated footprint evidence product."""
import json

from shapely.geometry import LineString, box
from shapely.strtree import STRtree

from app import evidence, flags, footprints, plan
from app.osm import AreaGraph, Way
from pipelines.footprints_city import section


def test_two_sided_gap_and_source():
    polys = [box(-8, -10, -2, 10), box(3, -10, 9, 10)]
    result = section(LineString([(0, -10), (0, 10)]), 10, STRtree(polys), polys, ['Google', 'Microsoft'])
    assert result == {'status': 'ok', 'gap_m': 5., 'sources': 'Google + Microsoft'}


def test_open_side_is_unknown():
    polys = [box(-8, -10, -2, 10)]
    result = section(LineString([(0, -10), (0, 10)]), 10, STRtree(polys), polys, ['Google'])
    assert result['status'] == 'open_side'
    assert 'gap_m' not in result


def test_merged_roof_spanning_way_is_unknown():
    polys = [box(-8, -10, 9, 10)]
    result = section(LineString([(0, -10), (0, 10)]), 10, STRtree(polys), polys, ['Google'])
    assert result['status'] == 'inside_building'


def product(lo=.5, hi=12.):
    return {'schema_version': 1, 'tier': 'Inferred', 'generated_at': '2026-10-17',
            'dataset': {'release': '2026-09-23.1'}, 'calibration': {'uncertainty_radius_m': 5., 'matched_ways': 150},
            'ways': {'9876543210': {'lo': lo, 'hi': hi, 'source': 'Google Open Buildings', 'samples': 8,
                     'attempted': 10, 'gap_p10_m': 3., 'gap_median_m': 5.}}}


def setup_store(monkeypatch, tmp_path, data):
    path = tmp_path / 'footprints.json'
    path.write_text(json.dumps(data))
    monkeypatch.setattr(footprints, 'PATH', path)
    monkeypatch.setattr(footprints, '_stamp', None)
    monkeypatch.setattr(footprints, '_data', {})
    monkeypatch.setattr(flags, '_state', {k: False for k in flags.AI_FEATURES} | {'footprint_widths': True, 'parcel_widths': True})
    store = evidence.EvidenceStore()
    monkeypatch.setattr(evidence, 'STORE_EVIDENCE', store)
    monkeypatch.setattr(plan, 'STORE_EVIDENCE', store)
    graph = AreaGraph(center=(10.8, 106.7), source='test-footprints')
    graph.ways[9876543210] = Way(9876543210, {'highway': 'service', 'service': 'alley'}, [])
    return path, store, graph


def test_calibrated_interval_not_truncated_by_osm_prior(monkeypatch, tmp_path):
    _, _, graph = setup_store(monkeypatch, tmp_path, product())
    wr = evidence.width_ranges(graph)[9876543210]
    assert (wr.lo, wr.hi, wr.top_tier) == (.5, 12., 'Inferred')
    assert not wr.review


def test_official_wins_even_when_footprint_overlaps(monkeypatch, tmp_path):
    _, store, graph = setup_store(monkeypatch, tmp_path, product(3.9, 12.))
    store._add(evidence.Bound(3., 4., 'Official', 'parcel', 'test'), 9876543210)
    wr = evidence.width_ranges(graph)[9876543210]
    assert (wr.lo, wr.hi, wr.top_tier) == (3., 4., 'Official')
    assert [b.feature for b in wr.overruled] == ['footprint_widths']


def test_other_inferred_conflicts_still_require_review(monkeypatch, tmp_path):
    _, store, graph = setup_store(monkeypatch, tmp_path, product())
    store._add(evidence.Bound(20., 25., 'Inferred', 'another imagery inference', 'test'), 9876543210)
    wr = evidence.width_ranges(graph)[9876543210]
    assert wr.review
    assert (wr.lo, wr.hi) == (.5, 25.)


def test_plan_width_cache_reloads_after_atomic_replacement(monkeypatch, tmp_path):
    path, _, graph = setup_store(monkeypatch, tmp_path, product())
    monkeypatch.setattr(plan, 'build_graph', lambda *a: graph)
    monkeypatch.setattr(plan, 'flood_profiles', lambda g: {})
    monkeypatch.setattr(plan, '_WR', {})
    monkeypatch.setattr(plan, '_FP', {})
    assert plan.area(10.8, 106.7)[1][9876543210].hi == 12.
    new = tmp_path / 'new.json'
    new.write_text(json.dumps(product(.5, 9.)))
    new.replace(path)
    assert plan.area(10.8, 106.7)[1][9876543210].hi == 9.


def test_broken_replacement_retains_last_good_snapshot(monkeypatch, tmp_path):
    path, _, _ = setup_store(monkeypatch, tmp_path, product())
    stamp, data = footprints.snapshot()
    path.write_text('{')
    assert footprints.snapshot() == (stamp, data)


def test_disabling_flag_removes_footprint_evidence(monkeypatch, tmp_path):
    _, _, graph = setup_store(monkeypatch, tmp_path, product())
    monkeypatch.setitem(flags._state, 'footprint_widths', False)
    wr = evidence.width_ranges(graph)[9876543210]
    assert (wr.lo, wr.hi) == (1.5, 4.5)
    assert not any(b.feature == 'footprint_widths' for b in wr.evidence)

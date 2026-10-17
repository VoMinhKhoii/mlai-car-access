"""Cached failure regressions and independent automatic-cut safety invariants.

The fixture contains real OSM geometry and cached cuts, not live services. Its
first case is Ministop Trần Doãn Khanh; the next ten are distinct worst sampled
door ways from the seeded baseline (junction first, then narrow conflicts).
"""
from datetime import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app import evidence as ev, osm, plan, vehicles
from app.legality import supports_legal_lane_count


CASES = json.loads((Path(__file__).parent/'fixtures/engine_regressions.json').read_text())['cases']
ARRIVE = datetime.fromisoformat('2026-10-17T09:31:00+07:00')


def cached(case):
    p = case['point']
    graph = osm.graph_from_elements(p['lat'], p['lon'], case['elements'], 'cached-regression')
    index = ev.EvidenceIndex()
    index.add_areas([{'listings': [], 'photos': [], 'parcels': case['parcels']}])
    with patch.object(ev.flags, 'enabled', return_value=True):
        widths = ev.width_ranges(graph, ev.EvidenceView(index))
    return graph, widths


def street_graph():
    lat, lon = 10.8, 106.7
    elements = [{'type': 'node', 'id': n, 'lat': lat+y/110540, 'lon': lon+x/109400}
                for n, x, y in [(1, 0, 0), (2, 100, 0), (3, 0, -50), (4, 0, 50)]]
    elements += [{'type': 'way', 'id': 20, 'nodes': [1, 2], 'tags': {'highway': 'residential'}},
                 {'type': 'way', 'id': 10, 'nodes': [3, 1, 4], 'tags': {'highway': 'tertiary'}}]
    return osm.graph_from_elements(lat, lon, elements, 'quality-fixture')


def cut(at, width, y=0):
    return {'lat': 10.8+y/110540, 'lon': 106.7+at/109400,
            'at_m': at, 'width_m': width, 'gap_m': width+1}


def parcel_bound(cuts, tier='Inferred'):
    width = min(c['width_m'] for c in cuts)
    return ev.Bound(width, width, tier, 'cached automatic parcel cuts', '',
                    feature='parcel_widths', estimate_m=width, sample_count=len(cuts), sample_cuts=cuts,
                    coverage={'complete': False}, measurement_schema='parcel-usable-v2')


def estimate(graph, width, profile=None, failures=None, other_widths=None):
    edge = next(e for e in graph.edges if e.way_id == 20)
    c = plan.Candidate('door', *plan._interp(graph, edge.u, edge.v, 50, edge.length),
                       'fixture', 20, edge.idx, 50, data={'walk_path': {'unverified': False}})
    checks = {'route_in': {'strict': False, '_segments': [(edge.idx, 50)]},
              'way_out': {'mode': 'through', 'strict': False, '_segments': [(edge.idx, 50)]},
              'legality': {'status': 'Unverified', 'rules': []},
              'flood': {'stay': {'status': 'risky'}}, 'fit': {'class': plan.fit_class(
                  width, profile or vehicles.get_profile('toyota-vios'))}}
    if other_widths:
        checks['route_in']['_segments'] += [(e.idx, e.length) for e in graph.edges if e.way_id in other_widths]
    return plan._estimate(c, graph, {20: width, **(other_widths or {})}, profile or vehicles.get_profile('toyota-vios'),
                          checks, failures or [])


@pytest.mark.parametrize('case', CASES[1:], ids=lambda c: f"worst-{c['point']['i']}-way-{c['door_way_id']}")
def test_ten_cached_worst_cuts_keep_constraints_and_never_verify(case):
    graph, widths = cached(case)
    width = widths[case['door_way_id']]
    bound = next(b for b in width.evidence if b.feature == 'parcel_widths')
    assert bound.estimate_m == case['expected_sample_m']
    reasons = {c['rejection_reason'] for c in bound.sample_quality['rejected_cuts']}
    assert reasons == set(case['expected_rejection_reasons'])
    assert not width.decisive_clearance
    assert not supports_legal_lane_count(width)
    assert plan.fit_class(width, vehicles.get_profile('toyota-vios')) not in ('fits', 'tight')
    if bound.estimate_m is not None:
        # These narrow motorcycle passages must not become wide roads merely
        # because their automatic samples disagree with OSM class/access tags.
        assert bound.hi < vehicles.get_profile('toyota-vios').tight_min
    else:
        assert bound.measurement_schema == 'parcel-survey-unresolved-v2'
        assert bound.lo == 0 and bound.hi == ev.OPEN_HI


@pytest.mark.parametrize('intent,dwell', [('park', 120), ('pickup', 15)])
def test_ministop_uses_the_actual_route_and_separate_destination_samples(intent, dwell):
    case = CASES[0]
    graph, widths = cached(case)
    p = case['point']
    with (patch.object(plan, 'area', return_value=(graph, widths, {})),
          patch.object(plan.flags, 'enabled', return_value=False),
          patch.object(plan, 'GOONG_API_KEY', ''),
          patch.object(plan.parking_data, 'lots_near', return_value=[]),
          patch.object(plan.parking_data, 'paid_street_ways', return_value={})):
        result = plan.plan(p['lat'], p['lon'], 'class-m', intent, ARRIVE, dwell)
    door = result['door']
    est = door['estimate']
    assert (est['answer'], est['confidence']) == ('fits', 'low')
    assert est['coverage']['total_segments'] == 10
    assert est['limiting_width']['way_id'] == 35113132  # Cây Điệp, not the destination
    assert est['limiting_width']['value_m'] == 3.58
    assert est['stop_width']['value_m'] == 5.56
    sampled = door['fit']['width_range']['sampled_estimate']
    assert (sampled['lo'], sampled['hi']) == (5.26, 5.86)
    assert not sampled['guarantees_clearance']
    assert door['fit']['width_range']['lo'] == 0
    assert door['fit']['class'] == 'unknown'
    assert not door['verified']
    assert 'Đường Cây Điệp' in est['basis'] and 'Đường Trần Doãn Khanh' in est['basis']
    assert '≈1.50 m' not in est['basis']
    assert '_segments' not in door['route_in']
    assert result['verdict']['estimate'] == result['stop_points'][0]['estimate']


def test_junction_and_misaligned_outliers_are_rejected_before_fusion():
    graph = street_graph()
    cuts = [cut(2, .5), cut(20, 5.56), cut(30, 5.65), cut(50, .6, y=3)]
    bound = ev._validate_parcel_bound(graph, graph.ways[20], parcel_bound(cuts))
    assert bound.estimate_m == 5.56
    assert bound.sample_count == 2
    assert bound.sample_quality['bottleneck_support'] == 2
    assert {c['rejection_reason'] for c in bound.sample_quality['rejected_cuts']} == {
        'within_5m_of_junction', 'off_centerline_over_1_5m'}
    assert bound.lo == 0 and not bound.coverage_complete


def test_numeric_cache_strings_are_normalized_and_bad_locations_stay_unresolved():
    graph = street_graph()
    index = ev.EvidenceIndex()
    numeric = {k: str(v) for k, v in cut(20, 5.56).items()}
    index.add_areas([{'listings': [], 'photos': [], 'parcels': [
        {'way_id': 20, 'samples': ['5.56'], 'cuts': [numeric]},
        {'way_id': 10, 'samples': ['.5'], 'cuts': [{**numeric, 'lat': 'bad'}]}]}])
    with patch.object(ev.flags, 'enabled', return_value=True):
        widths = ev.width_ranges(graph, ev.EvidenceView(index))
    assert next(b for b in widths[20].evidence if b.feature == 'parcel_widths').estimate_m == 5.56
    assert widths[10].review
    assert not widths[10].decisive_clearance


def test_mad_alone_never_erases_a_credible_local_constriction():
    graph = street_graph()
    cuts = [cut(20, 5), cut(30, 5), cut(50, .8), cut(70, 5), cut(80, 5)]
    bound = ev._validate_parcel_bound(graph, graph.ways[20], parcel_bound(cuts, 'Official'))
    assert bound.sample_quality['isolated_low_outlier']
    assert bound.sample_quality['bottleneck_support'] == 1
    assert bound.estimate_m == .8 and bound.hi == pytest.approx(1.1)
    width = ev.WidthRange(bound.lo, bound.hi, 'Official', [bound])
    assert plan.fit_class(width, vehicles.get_profile('toyota-vios')) == 'no'
    result = estimate(graph, width)
    assert (result['answer'], result['confidence']) == ('no', 'low')


@pytest.mark.parametrize('second_at,expected_support,confidence', [(50.2, 1, 'low'), (55, 2, 'high')])
def test_only_independent_consistent_cuts_can_support_a_confident_automatic_negative(
        second_at, expected_support, confidence):
    graph = street_graph()
    cuts = [cut(50, .8), cut(second_at, .9), cut(70, 5), cut(80, 5)]
    bound = ev._validate_parcel_bound(graph, graph.ways[20], parcel_bound(cuts, 'Official'))
    assert bound.sample_quality['bottleneck_support'] == expected_support
    width = ev.WidthRange(bound.lo, bound.hi, 'Official', [bound])
    result = estimate(graph, width)
    assert (result['answer'], result['confidence']) == ('no', confidence)


def test_unresolved_official_interval_cannot_invent_a_one_point_five_metre_sample():
    width = ev.WidthRange(0, 15, 'Official', [
        ev.Bound(0, 40, 'Official', 'failed survey', '',
                 measurement_schema='parcel-survey-unresolved-v2'),
        ev.Bound(3.5, 15, 'Inferred', 'OSM road class', '')])
    hypothesis = plan._width_hypothesis(width)
    assert hypothesis['value_m'] == 5
    assert hypothesis['tier'] == 'Inferred' and hypothesis['fallback_from_unresolved']
    assert not hypothesis['sampled']
    assert plan.fit_class(width, vehicles.get_profile('toyota-vios')) == 'unknown'


def test_unresolved_prior_cannot_borrow_medium_confidence_from_other_measured_segments():
    width = ev.WidthRange(0, 15, 'Official', [
        ev.Bound(0, 40, 'Official', 'failed survey', '',
                 measurement_schema='parcel-survey-unresolved-v2'),
        ev.Bound(3.5, 15, 'Inferred', 'OSM road class', '')])
    measured = ev.WidthRange(6, 6.2, 'Measured', [ev.Bound(6, 6.2, 'Measured', 'physical survey', '')])
    result = estimate(street_graph(), width, other_widths={10: measured})
    assert result['coverage']['sample_supported_fraction'] > .5
    assert (result['answer'], result['confidence']) == ('fits', 'low')


def test_legacy_raw_gap_single_sample_cannot_borrow_high_confidence(tmp_path):
    csv = tmp_path/'gaps.csv'
    csv.write_text('osm_way_id,width_m\n20,1.8\n')
    index = ev.EvidenceIndex()
    with patch.object(ev, 'PARCEL_FILE', csv):
        index._load_csv(csv, 'Official', 'legacy cadastral gap', None)
    bound = index.by_way[20][0]
    result = estimate(street_graph(), ev.WidthRange(bound.lo, bound.hi, 'Official', [bound]))
    assert (result['answer'], result['confidence']) == ('no', 'low')


def test_partial_edge_metres_and_strictness_survive_until_estimation():
    graph = street_graph()
    edge = next(e for e in graph.edges if e.way_id == 20)
    c = plan.Candidate('door', *plan._interp(graph, edge.u, edge.v, 25, edge.length),
                       'fixture', 20, edge.idx, 25)
    networks = {True: ({}, {}), False: ({1: 0}, {})}
    route = plan._route_in(c, graph, networks)
    assert route['_segments'] == [(edge.idx, 25)]
    assert route['meters'] == 25 and not route['strict']
    width = ev.WidthRange(0, 6, 'Inferred')
    exit_route = plan._way_out(c, graph, {20: width}, {20: 'unknown'},
                              vehicles.get_profile('toyota-vios'),
                              {True: ({}, {}), False: ({2: 0}, {})}, route)
    assert exit_route['_segments'][0][1] == pytest.approx(edge.length-25)
    assert '_segments' not in plan._public_route(exit_route)


def test_missing_network_always_has_an_unknown_low_verdict():
    graph = osm.AreaGraph(center=(10.8, 106.7))
    with (patch.object(plan, 'area', return_value=(graph, {}, {})),
          patch.object(plan.flags, 'enabled', return_value=False),
          patch.object(plan, 'GOONG_API_KEY', ''),
          patch.object(plan.parking_data, 'lots_near', return_value=[])):
        result = plan.plan(10.8, 106.7, 'toyota-vios', 'park', ARRIVE, 120)
    assert result['verdict']['estimate']['answer'] == 'unknown'
    assert result['verdict']['estimate']['confidence'] == 'low'
    assert not result['stop_points']


def test_english_verdicts_keep_street_names_and_confidence_explicit():
    stop = {'kind': 'street', 'verified': False, 'name': 'Võ Duy Ninh', 'walk': {'meters': 39},
            'estimate': {'answer': 'fits', 'confidence': 'low'},
            'legality': {'status': 'Unverified', 'rules': []},
            'way_out': {'text': 'Exit unverified'}, 'unverified_reasons': []}
    assert plan._verdict([stop], None, 'park', 400)['headline'] == 'Park on Võ Duy Ninh, 39 m walk — low confidence'
    stop.update(kind='door', estimate={'answer': 'fits', 'confidence': 'medium'})
    assert plan._verdict([stop], None, 'park', 400)['headline'] == 'Can reach the door — medium confidence'
    payload = ev.english_payload({'name': 'Hẻm Mưa Võ Duy Ninh', 'street': 'Đường Trần Doãn Khanh',
                                  'reason': 'No valid tide data at this time'})
    assert payload['name'] == 'Hẻm Mưa Võ Duy Ninh'
    assert payload['street'] == 'Đường Trần Doãn Khanh'
    assert payload['reason'] == 'No valid tide data at this time'
    assert ev.TIER_VI['Official'] == 'Official'


def test_sample_display_counts_do_not_promote_inferred_confidence():
    graph = street_graph()
    bound = ev._validate_parcel_bound(graph, graph.ways[20], parcel_bound([cut(20, 5.56), cut(30, 5.65)]))
    result = estimate(graph, ev.WidthRange(bound.lo, bound.hi, 'Inferred', [bound]))
    assert result['coverage']['all_sampled_segments'] == 1
    assert result['coverage']['sampled_segments'] == 0
    assert result['coverage']['sample_supported_fraction'] == 0
    assert result['confidence'] == 'low'
    assert '1/1 segments sampled' in result['basis']


@pytest.mark.parametrize('citation', [
    'Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4',
    'QCVN 41:2024/BGTVT, biển P.130/P.131a/P.131b/P.131c',
])
def test_legal_citations_stay_verbatim_in_adapter_estimate_and_verdict(citation):
    rule = {'status': 'Restricted', 'text': 'Cấm dừng', 'citation': citation}
    payload = ev.english_payload({'rules': [rule]})
    assert payload['rules'][0]['text'] == 'No stopping'
    assert payload['rules'][0]['citation'] == citation
    assert ev.english_text(citation) == citation
    stop = {'kind': 'street', 'verified': False, 'name': 'Võ Duy Ninh',
            'estimate': {'answer': 'no', 'confidence': 'high'},
            'legality': {'status': 'Restricted', 'rules': [rule]}}
    verdict = ev.english_payload(plan._verdict([stop], None, 'pickup', 400))
    assert verdict['detail'] == 'No stopping (' + citation + ')'
    graph = street_graph()
    width = ev.WidthRange(5, 6, 'Measured', [])
    original = plan._estimate
    # Exercise the same helper as other quality fixtures while supplying a
    # cited hard prohibition, independently of width/flood uncertainty.
    def legal_estimate(candidate, graph, widths, profile, checks, failures):
        checks['legality'] = {'status': 'Restricted', 'rules': [rule]}
        return original(candidate, graph, widths, profile, checks, failures)
    with patch.object(plan, '_estimate', side_effect=legal_estimate):
        result = estimate(graph, width)
    assert 'No stopping (' + citation + ')' in result['basis']

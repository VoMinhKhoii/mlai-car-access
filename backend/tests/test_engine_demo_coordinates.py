"""Frozen cadastral hypotheses at the reported HUTECH endpoint regressions.

OSM geometry is the repository's prefetched demo graph. The sample points below
are frozen from the server cache before this fix; no portal or crawler is used.
Portal cuts carry Official provenance, with no continuous clear-width lower guarantee.
"""
import json
from datetime import datetime
from functools import lru_cache

import pytest
from app import evidence, flags, osm, plan, vehicles

SAMPLES = {32578483: 2.4,
 32580171: 5.55,
 32584224: 7.23,
 32585926: 7.62,
 32587999: 6.75,
 112286501: 1.95,
 136505791: 3.39,
 136505806: 2.94,
 136507349: 3.73,
 192512286: 2.56,
 192512292: 1.28,
 192512293: 1.09,
 192512295: 0.61,
 192512297: 3.7,
 192512303: 4.86,
 192512356: 1.73,
 192512360: 4.93,
 192512372: 3.7,
 192512373: 1.9,
 192512381: 0.73,
 192512387: 3.7,
 192512389: 1.99,
 192512393: 2.61,
 192512394: 3.7,
 192512395: 1.53,
 192512396: 3.7,
 192512413: 4.55,
 192512429: 4.3,
 192512433: 4.43,
 263603378: 0.91,
 268563780: 1.03,
 268563988: 1.27,
 366265646: 5.92,
 388370867: 3.7,
 567708980: 0.91,
 602290887: 0.55,
 604168322: 6.07,
 604529796: 4.46,
 604535051: 6.8,
 604535053: 5.46,
 604771129: 4.3,
 604771130: 2.26,
 604781145: 3.41,
 604781148: 2.55,
 604819705: 3.48,
 604834162: 1.54,
 604834163: 1.28,
 604834165: 2.58,
 604834167: 3.7,
 604834169: 3.7,
 604834172: 2.89,
 604837643: 1.3,
 608976501: 1.09,
 608976504: 2.33,
 608976505: 4.27,
 608976506: 3.7,
 609856624: 4.06,
 609856625: 1.0,
 609856656: 0.78,
 609856657: 1.12,
 609856658: 3.03,
 609856659: 4.95,
 609856660: 0.94,
 609856662: 0.75,
 609856663: 5.36,
 609856664: 5.38,
 609856665: 6.36,
 609856666: 6.09,
 609856668: 1.29,
 609856670: 0.86,
 609856672: 1.77,
 609856673: 0.96,
 609856674: 0.58,
 609856675: 1.3,
 609856676: 1.61,
 609856677: 1.88,
 609856678: 1.55,
 609967096: 3.7,
 609967124: 2.39,
 609967179: 4.09,
 609967181: 0.95,
 609980572: 1.16,
 609980575: 3.3,
 610082005: 7.75,
 610082009: 2.9,
 610082012: 0.59,
 610082013: 0.93,
 610082016: 0.5,
 610082018: 2.82,
 610082023: 5.06,
 610082025: 0.5,
 610082030: 3.22,
 610102929: 5.88,
 610102930: 1.1,
 610102931: 2.36,
 610102932: 0.88,
 610102935: 4.38,
 610102938: 5.93,
 610102957: 0.56,
 610102959: 3.91,
 610240381: 3.8,
 610240385: 2.01,
 610240387: 3.41,
 610240392: 3.7,
 610251606: 5.89,
 610251609: 1.33,
 610251612: 3.98,
 610251622: 2.52,
 610251624: 5.71,
 610251628: 0.5,
 610251632: 1.21,
 610251654: 7.54,
 610251671: 2.83,
 722702831: 3.7,
 737495706: 5.56,
 899717188: 2.36,
 900667771: 3.33,
 952077943: 2.78,
 1040123788: 0.5,
 1054386454: 3.7,
 1065135125: 1.12,
 1076507738: 1.2,
 1084964778: 3.02,
 1086876216: 6.16,
 1114843254: 1.89,
 1198619998: 3.7,
 1253891038: 1.63,
 1258909452: 0.61,
 1269008323: 2.87,
 1290846557: 4.94,
 1290846558: 1.46,
 1330786034: 3.7,
 1330786039: 4.89,
 1349519500: 2.94,
 1411065926: 3.7,
 1422409258: 1.65,
 1455411022: 0.75}
POINTS = [
    (10.799694, 106.7160292),  # Hẻm 550 Điện Biên Phủ
    (10.7998633, 106.7143109),  # Hẻm 294/83 Xô viết Nghệ Tĩnh
    (10.7998622, 106.7141545),  # Hẻm 294/115
    (10.799074, 106.7145452),   # Hẻm 294
    (10.7993099, 106.7137166),  # Hẻm 294/84
    (10.7990181, 106.714337),   # Hẻm 294/120
]
IDS = ['class-xs', 'class-s', 'class-m', 'class-l', 'class-xl', 'toyota-fortuner', 'vinfast-vf-3']
ORDER = {'no': 0, 'unknown': 1, 'tight': 2, 'fits': 3}
ARRIVE = datetime.fromisoformat('2026-10-17T14:00:00+07:00')


@lru_cache(maxsize=1)
def snapshot():
    g = osm.graph_from_elements(10.799694, 106.7160292,
        json.loads(osm.DEMO_FILE.read_text())['elements'], 'coherence-cached-regression')
    ws = evidence.width_ranges(g, evidence.EvidenceView(evidence.EvidenceIndex()))
    for wid, width in SAMPLES.items():
        if wid in g.ways:
            ws[wid] = evidence.WidthRange(0, width+.3, 'Official', [evidence.Bound(
                0, width+.3, 'Official', 'Cadastral parcel-gap estimate', '',
                feature='parcel_widths', estimate_m=width, sample_count=1)])
    return g, ws, {}


@pytest.mark.parametrize('lat,lon', POINTS)
def test_reported_endpoints_never_penalize_narrower_vehicle(monkeypatch, lat, lon):
    monkeypatch.setattr(plan, 'area', lambda *args, **kwargs: snapshot())
    monkeypatch.setattr(plan, 'GOONG_API_KEY', '')
    monkeypatch.setattr(flags, 'enabled', lambda name: False)
    output = []
    for vid in IDS:
        r = plan.plan(lat, lon, vid, 'park', ARRIVE, 60)
        output.append((vehicles.get_profile(vid).mirror_width, r))
    output.sort(key=lambda item: item[0])
    for (_, small), (_, wide) in zip(output, output[1:]):
        assert ORDER[small['verdict']['estimate']['answer']] >= ORDER[wide['verdict']['estimate']['answer']]
        assert ORDER[small['door']['estimate']['answer']] >= ORDER[wide['door']['estimate']['answer']]
    compared = plan.compare_vehicles(lat, lon, 'park', ARRIVE, 60, [], '', IDS)
    rows = sorted(compared['vehicles'], key=lambda v: v['mirror_width'])
    assert all(ORDER[a['answer']] >= ORDER[b['answer']] for a, b in zip(rows, rows[1:]))

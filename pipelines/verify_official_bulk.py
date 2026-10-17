"""Replay every imported way with/without metadata and prohibit external HTTP."""
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import requests

from official_bulk import ROOT, graph_for
from app import evidence, official_widths


def main():
    product=json.loads((ROOT/'backend/cache/live/official_widths.json').read_text())
    inventory=json.loads((ROOT/'backend/cache/live/evidence_inventory.json').read_text())
    graph,_=graph_for({wid:inventory['ways'][wid] for wid in product['ways']})
    def forbidden(*args,**kwargs):raise AssertionError('Verifier forbids external HTTP')
    with patch.object(requests.Session,'request',forbidden),patch.object(httpx.Client,'request',forbidden),patch.object(httpx.AsyncClient,'request',forbidden):
        actual=evidence.width_ranges(graph)
        with patch.object(official_widths,'for_way',return_value=[]):
            baseline=evidence.width_ranges(graph)
    diffs=[]
    for wid in actual:
        a=actual[wid].to_json();b=baseline[wid].to_json()
        a.pop('official_width_records');b.pop('official_width_records')
        if a!=b:diffs.append(wid)
    assert not diffs,diffs
    wid=next(w for w,r in actual.items() if r.official_width_records)
    result={'ways_checked':len(actual),'changed_clear_width_or_other_evidence':len(diffs),
            'metadata_nonempty':sum(bool(r.official_width_records) for r in actual.values()),
            'example_way':wid,'example_current_width':{'lo':actual[wid].lo,'hi':actual[wid].hi,'top_tier':actual[wid].top_tier},
            'example_metadata':actual[wid].official_width_records[:1],'network_calls':0,
            'http_guard':'requests and sync/async httpx requests forbidden'}
    path=ROOT/'docs/eval/official-bulk-runtime-validation.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='example_metadata'}))


if __name__=='__main__':main()

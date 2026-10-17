"""Isolated real search/agent/plan HTTP server, with all outbound HTTP denied.

AGENT_ALLOW_PAID=0 PYTHONPATH=backend python3 pipelines/e2e_cached_server.py
Only port 8793 is used. No production process, flags, or ledger is changed.
"""
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ['AGENT_ALLOW_PAID'] = '0'
from app import agent, agent_budget, geocoding, live, main, osm, parcels, plan
import httpx

OUT = ROOT / 'docs/eval'
OUT.mkdir(exist_ok=True)

def denied(*args, **kwargs):
    raise RuntimeError('E2E cached test forbids outbound HTTP / portal / paid calls')

# Guard the actual transport as well as the known download entry points.
httpx.HTTPTransport.handle_request = denied
httpx.AsyncHTTPTransport.handle_async_request = denied
osm._fetch_overpass = denied
parcels._parcel = denied
plan.GOONG_API_KEY = ''
agent_budget.reserve = denied

# Exercise the real quota-recovery path without touching the shared ledger.
def unavailable(*args, **kwargs):
    raise ValueError('Gemini miễn phí: deterministic E2E fallback mode')
agent.generate = unavailable

# Copy provider caches, then permit only cache reads. No provider miss can call HTTP.
db_path = OUT / 'e2e-geocoding.sqlite'
if not db_path.exists():
    with sqlite3.connect(geocoding.DB) as src, sqlite3.connect(db_path) as dst:
        src.backup(dst)
geocoding.DB = db_path
geocoding.INDEX_FILE = OUT / 'e2e-osm-name-index.json'
def cached_provider(provider, endpoint, params):
    with geocoding._db() as db:
        row = db.execute('SELECT body FROM responses WHERE provider=? AND key=?',
                         (provider, endpoint + ':' + geocoding._key(params))).fetchone()
    return json.loads(row[0]) if row else ([] if provider == 'nominatim' else {})
geocoding.goong = lambda endpoint, params, deadline=None: cached_provider('goong', endpoint, params)
geocoding._nominatim_request = lambda endpoint, params: cached_provider('nominatim', endpoint, params)

def cached_build(lat, lon, *args, **kwargs):
    key = live.apply(None, lat, lon)
    yield json.dumps({'status': {'key': key, 'state': 'off'}, 'area': None}) + '\n'
live.build = cached_build

# The production engine keeps one mutable evidence store; serialize plans while
# search and parsing remain concurrent. This prevents cross-request contamination.
plan_lock = threading.Lock()
make_plan = main.make_plan
def locked_plan(req):
    with plan_lock:
        return make_plan(req)
main.make_plan = locked_plan

if __name__ == '__main__':
    import uvicorn
    geocoding.initialize_name_index()
    geocoding.configure_curated(main.PRESETS, agent.DEMO_PLACES)
    uvicorn.run(main.app, host='127.0.0.1', port=8793, lifespan='off', log_level='warning')

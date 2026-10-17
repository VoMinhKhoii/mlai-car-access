"""Live-like HTTP/UI review on 8788: real engine and agent; cached evidence only.

No portal, Overpass, live crawler or paid route requests. Gemini remains the normal
agent path, with its shared ledger/call cap. No production configuration is edited.
"""
import json
from pathlib import Path
from app import main, live, osm, parcels, plan, agent_budget


def denied(*args, **kwargs):
    raise RuntimeError('Estimate review forbids portal/Overpass calls')

osm._fetch_overpass = denied
parcels._parcel = denied
plan.GOONG_API_KEY = ''

# A process-local <=10-call ceiling, independent of the parallel imagery job's
# paid calls in the same shared ledger. Keep every reservation/charge unchanged.
reserve = agent_budget.reserve
finish = agent_budget.finish
paid_log = Path('docs/eval/estimate-paid-calls.jsonl')
paid_calls = len(paid_log.read_text().splitlines()) if paid_log.exists() else 0
def review_reserve(body, **kwargs):
    global paid_calls
    if paid_calls >= 10:
        raise ValueError('Đã chạm hạn mức 10 lượt kiểm tra trả phí.')
    rid = reserve(body, **kwargs)
    paid_calls += 1
    return rid

def review_finish(rid, usage, rejected=False):
    with agent_budget.ledger() as ledger:
        ceiling = ledger['reservations'][rid]
    finish(rid, usage, rejected)
    cost = ((agent_budget.INPUT_USD_PER_M * usage.get('promptTokenCount',0) +
             agent_budget.OUTPUT_USD_PER_M * (usage.get('candidatesTokenCount',0) + usage.get('thoughtsTokenCount',0))) / 1e6
            if usage is not None else 0 if rejected else ceiling)
    with Path('docs/eval/estimate-paid-calls.jsonl').open('a') as output:
        output.write(json.dumps({'call':paid_calls, 'cost_usd':cost, 'rejected':rejected, 'usage':usage})+'\n')

agent_budget.reserve = review_reserve
agent_budget.finish = review_finish


def cached_build(lat, lon, *args, **kwargs):
    key = live.apply(None, lat, lon)
    yield json.dumps({'status': {'key': key, 'state': 'off'}, 'area': None}) + '\n'

live.build = cached_build

# Review-only inputs in the real Demo menu: exact pre-change coordinates/times.
# Engine responses and rendered production components are never replaced.
def review_config():
    result = main.config()
    rows = json.loads(Path('docs/eval/estimate-before.json').read_text())
    result['presets'] = [{**row['request'], 'id':f'estimate-{i}',
        'title':f"{row['request']['label']} · {row['request']['vehicle_id']}",
        'story':'Kiểm tra ước tính trên dữ liệu cache, không gọi cổng quy hoạch.'}
        for i, row in enumerate(rows)]
    return result

for route in main.app.routes:
    if getattr(route, 'path', None) == '/api/config':
        route.endpoint = review_config
        route.dependant.call = review_config

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(main.app, host='127.0.0.1', port=8788, lifespan='off', log_level='warning')

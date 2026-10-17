"""Read-only, credential-free round-3 timing and coverage report."""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
VN = ZoneInfo('Asia/Ho_Chi_Minh')


def read(path):
    try:return json.loads((ROOT/path).read_text())
    except (OSError,ValueError):return {}


def report():
    op=read('docs/eval/round3-operation.json')
    state=read('backend/cache/live/crawl_city_state.json')
    cache=read('backend/cache/live/city_parcels.json')
    now=time.time(); start=op['launched_at']; elapsed=max(1,now-start); pid=op['crawler_pid']
    monitored_pids = set(op.get('monitored_pids', [pid])) | {op['api_pid']}
    rows=[]
    for line in (ROOT/'backend/cache/parcels_points/portal_events.jsonl').read_text().splitlines():
        try:row=json.loads(line)
        except ValueError:continue
        if row['at']>=start and row['pid'] in monitored_pids:rows.append(row)
    starts=sorted(r['at'] for r in rows if r['kind']=='request_start')
    responses=[r for r in rows if r['kind']=='response']
    completions=state.get('round3_completion_events',[])
    counts=Counter(row['kind'] for row in completions)
    with_data=Counter(row['kind'] for row in completions if row['with_data'])
    nonzero=Counter(row['kind'] for row in completions if row['cuts']>0)
    events_new=[row for row in completions if row['wid'] not in set(op.get('baseline_cache_ids',[]))]
    added=Counter(row['kind'] for row in events_new)
    stats=dict(state.get('point_cache',{}))
    for key,value in op.get('point_stats_before_restart',{}).items():stats[key]=stats.get(key,0)+value
    excluded=op.get('excluded_local_lease_lookup_stats',{})
    hits=stats.get('online_polygon_hits',0)-excluded.get('online_polygon_hits',0)
    empty=stats.get('online_empty_hits',0)-excluded.get('online_empty_hits',0)
    misses=stats.get('requests',0)-excluded.get('requests',0)
    progress=dict(state.get('round3_progress',{}))
    inner_ids=set().union(*(set(ids) for ids in state.get('campus_inner_targets',{}).values()))
    progress['inner_any_results']=sum(w in cache for w in inner_ids)
    progress['inner_any_width']=sum(bool(cache.get(w)) for w in inner_ids)
    minutes_left=max(0,(datetime.fromisoformat(op['stop_at']).timestamp()-now)/60)
    active=max(1,now-starts[0]) if starts else 0
    projections={}
    for kind in ('inner','ring','city'):
        current=progress.get(f'{kind}_completed',0)
        rate=counts[kind]*60/elapsed
        projected=math.floor(current+rate*minutes_left)
        if kind!='city':projected=min(progress.get(f'{kind}_target',0),projected)
        active_projected=math.floor(current+counts[kind]*60/max(1,active)*minutes_left) if active else None
        if active_projected is not None and kind!='city':active_projected=min(progress.get(f'{kind}_target',0),active_projected)
        projections[kind]={'completed':current,'new_completed':counts[kind],
            'new_unique_results':added[kind], 'new_with_data':with_data[kind],
            'completed_with_nonzero_cuts':nonzero[kind], 'ways_min':round(rate,4),
            'projected_completed_by_stop':projected, 'projected_if_current_active_rate_persists':active_projected}
    allhits=stats.get('polygon_hits',0)
    lookup_total=allhits+stats.get('empty_hits',0)+stats.get('lookup_misses',0)
    window_max=max((sum(0<=t-other<60 for other in starts) for t in starts), default=0)
    try:os.kill(pid,0);running=True;nice=os.getpriority(os.PRIO_PROCESS,pid)
    except OSError:running=False;nice=None
    return {'observed_at':datetime.now(VN).isoformat(),'window_started_at':datetime.fromtimestamp(start,VN).isoformat(),
        'elapsed_min':round(elapsed/60,3),'pid':pid,'running':running,'niceness':nice,'stop_at':op['stop_at'],
        'stage':state.get('stage'),'ways_total':len(cache),'ways_with_width':sum(bool(v) for v in cache.values()),
        'effective_ways_min':round(len(completions)*60/elapsed,4),
        'new_unique_ways_min':round(len(events_new)*60/elapsed,4),
        'projected_total_unique_by_stop':math.floor(len(cache)+len(events_new)*60/elapsed*minutes_left),
        'active_period_ways_min':round(len(completions)*60/active,4) if active else None,
        'http':{'requests_started':len(starts),'responses':len(responses),
                'locked_responses':sum(r.get('locked',False) for r in responses),
                'lock_incidents':sum(r['kind']=='lock_incident' for r in rows),
                'transport_errors':sum(r['kind']=='transport_error' for r in rows),
                'minimum_start_gap_s':round(min((b-a for a,b in zip(starts,starts[1:])),default=0),4),
                'max_starts_in_rolling_60s':window_max},
        'online_polygon_hit_ratio':round(hits/max(1,hits+empty+misses),4),
        'polygon_hits_vs_http_starts_ratio':round(hits/max(1,hits+empty+len(starts)),4),
        'eligible_online_lookup_counts':{'polygon_hits':hits,'empty_hits':empty,'misses':misses},
        'excluded_local_lease_lookup_stats':excluded,
        'polygon_hit_ratio_definition':'Online polygon hits / eligible online lookup attempts; excludes cache-only probes and the local test-lease outage. Raw counters and exclusions are provided. Actual HTTP counts are independent.',
        'lookup_attempt_polygon_hit_ratio':round(hits/max(1,hits+empty+misses),4),
        'online_any_cache_hit_ratio':round((hits+empty)/max(1,hits+empty+misses),4),
        'all_lookup_polygon_hit_ratio':round(allhits/max(1,lookup_total),4),
        'point_cache':stats,'progress':progress,'categories':projections,
        'campuses':state.get('campuses',{}),'cells_visited':len(state.get('cells_visited',[])),
        'cells_complete':len(state.get('cells_done',[])),'osm_cells_cached':state.get('osm_cells_cached'),
        'projection_note':'Conditional linear extrapolation of completed-way rates including recovery pauses, capped at campus targets; not a coverage guarantee. Inner partial cuts are reported separately.',
        'initial_recovery_until':datetime.fromtimestamp(op['inherited_recovery_until'],VN).isoformat(),
        'cooldown_file':read('backend/cache/parcels_points/cooldown.json')}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output');args=parser.parse_args()
    data=report()
    if args.output:(ROOT/args.output).write_text(json.dumps(data,ensure_ascii=False,indent=2))
    compact={k:v for k,v in data.items() if k not in ('campuses','cooldown_file')}
    print(json.dumps(compact,ensure_ascii=False,indent=2))

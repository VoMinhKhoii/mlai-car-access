#!/usr/bin/env python3
"""Cluster the two frozen cached-engine runs; render a reproducible static map."""
from __future__ import annotations

from collections import Counter, defaultdict
import html
import json
from pathlib import Path
import random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from pipelines import stress_cached_engine as s

OUT=s.OUT
NAMES={
 'failed_survey_midpoint':'Failed-survey midpoint labelled Official',
 'missing_route_not_width':'Missing route / Way Out labelled no-fit',
 'junction_cut':'Automatic cut within 5 m of junction',
 'misaligned_cut':'Cut displaced from mapped centreline',
 'single_cut_confidence':'Uncorroborated automatic bottleneck confidence',
 'clamped_basis_provenance':'Weaker cap relabelled as Official sample',
 'cited_stop_prohibition':'Cited stopping prohibition (retained)',
 'different_route_bottleneck':'Different route segment limits access',
 'narrow_cut_requires_field_check':'Submetre cut needs field review',
 'street_prior_or_other_checks':'Other street-negative review candidate',
 'vehicle_monotonicity':'Vehicle monotonicity', 'exception':'Exception',
 'walk_or_contract':'Walking / output-contract invariant',
 'missing_network':'All twelve answers unknown: missing cached coverage',
}
RULES={
 'failed_survey_midpoint':('An unresolved Official [0,40] survey was truncated by a weak prior; its interval midpoint invented 1.5 m with an Official badge.',
    'Use a sourced weaker hypothesis for estimates only; preserve the strict zero lower bound.'),
 'missing_route_not_width':('A missing directed path/Way Out was presented as a physical fit rejection despite adequate width hypotheses.',
    'Return unknown/low for the hypothesis; the failed Hard Check still excludes the stop.'),
 'junction_cut':('Legacy automatic frontage cuts sample a junction/corner instead of the corridor.',
    'Revalidate cached cuts against physical junctions and bends; invalid cuts supply no width cap.'),
 'misaligned_cut':('The saved cut centre is displaced from its claimed OSM way.',
    'Reject automatic cuts over 1.5 m from the way; retain an unresolved Official survey.'),
 'single_cut_confidence':('One automatic narrow cut, or an isolated low tail, was allowed to determine medium/high rejection.',
    'Keep credible narrow cuts as hard constraints, but require two independent consistent cuts for confident automatic rejection.'),
 'clamped_basis_provenance':('A stronger sampled value was clamped to a weaker cap and the invented value inherited the stronger source label.',
    'Retain the actual sampled value and source for the hypothesis; hard fused caps remain separate.'),
 'cited_stop_prohibition':('Random road-node destinations frequently lie at junctions or on another prohibited stopping location.',
    'Retain the cited exclusion. A road admitting cars does not authorize stopping at this point.'),
 'different_route_bottleneck':('A wide destination way does not establish widths/turns on every approach and departure segment.',
    'Name and link the actual limiting route way in the basis; retain credible bottlenecks.'),
 'narrow_cut_requires_field_check':('Sparse automatic cadastral cuts can describe a real motorcycle passage or uncertain alignment.',
    'Retain credible narrow constraints; expose geometry, support and uncertainty for field review.'),
 'street_prior_or_other_checks':('A street-level negative needs review of the actual route, vehicle threshold and stopping checks.',
    'Do not promote an excluded stop based solely on a highway tag.'),
 'missing_network':('The cached graph lacks a usable car/main-road/walking projection.',
    'Retain unknown/low; do not manufacture a route or query the network.'),
 'vehicle_monotonicity':('A physically smaller profile receives a worse plan.', 'Inspect route/candidate selection; do not relax checks.'),
 'exception':('Planner or harness exception.', 'Repair and rerun identical inputs.'),
 'walk_or_contract':('Returned geometry/stop contract violates its invariant.', 'Repair the shared path/contract calculation.'),
}
ACTIONABLE={'failed_survey_midpoint','missing_route_not_width','junction_cut','misaligned_cut',
            'single_cut_confidence','clamped_basis_provenance','vehicle_monotonicity','exception','walk_or_contract'}


def load(phase):
    results=[json.loads(line) for line in (OUT/f'stress-{phase}.jsonl').read_text().splitlines()]
    rows=[r for x in results for r in x['rows']]
    flags=[r for x in results for r in x['flags']]
    for r in flags:
        if r['cluster']=='street_prior_or_other_checks' and any('đường ra' in x or 'đường vào' in x for x in r.get('fail_reasons',[])):
            r['cluster']='missing_route_not_width'
        if r['cluster']=='single_cut_confidence' and r.get('legal_status') in ('Prohibited','Restricted'):
            r['flags']=[x for x in r['flags'] if x!='single_cut_confidence']
            r['cluster']='cited_stop_prohibition'
        # Complete feature schema even when no cut/limiting segment exists.
        r.setdefault('scope','plan')
        r.setdefault('coverage_fraction',None)
        lim=r.setdefault('limiting',{})
        for k in ['way_id','highway','tags','nearest_junction_m','cut_length_m','way_length_m',
                  'cut_length_vs_way_length','number_of_cuts','evidence_tiers','way_crosses_cell_boundary','basis_data_source']:
            lim.setdefault(k,None)
    unknown=[]
    for x in results:
        if all(r.get('verdict',{}).get('estimate',{}).get('answer')=='unknown' for r in x['rows']):
            unknown.append(x['point']['i'])
    streaks={}
    for vid in s.IDS:
        for intent in ('park','pickup'):
            length=best=0;first=None;best_start=None
            for r in sorted((r for r in rows if r['vehicle_id']==vid and r['intent']==intent),key=lambda r:r['i']):
                if r.get('verdict',{}).get('estimate',{}).get('answer')=='unknown':
                    if not length:first=r['i']
                    length+=1
                    if length>best:best=length;best_start=first
                else:length=0
            streaks[f'{vid}:{intent}']={'longest':best,'start_destination':best_start}
    return results,rows,flags,{'all_twelve_unknown_destinations':unknown,'longest_streaks':streaks}


def example_link(r):
    wid=r.get('limiting',{}).get('way_id') or r.get('sampled_way_id')
    name=r.get('limiting',{}).get('name') or f"{r['lat']:.6f}, {r['lon']:.6f}"
    url=f'https://www.openstreetmap.org/way/{wid}' if wid else f"https://www.openstreetmap.org/?mlat={r['lat']}&mlon={r['lon']}#map=19/{r['lat']}/{r['lon']}"
    return f"[{name} ({r['lat']:.6f}, {r['lon']:.6f})]({url})"


def plot(before,after,clusters):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from shapely.geometry import shape
    geo=json.loads((s.ROOT/'data/official/hcmc_urban_districts_2021.geojson').read_text())
    order=[r['cluster'] for r in clusters]
    palette=plt.get_cmap('tab20')
    colors={c:palette(i%20) for i,c in enumerate(order)}
    fig=plt.figure(figsize=(19,10),facecolor='#faf9f6')
    gs=fig.add_gridspec(2,3,width_ratios=[1,1,1.05],height_ratios=[1,.12],wspace=.16)
    for j,(phase,flags) in enumerate([('Before',before),('After',after)]):
        ax=fig.add_subplot(gs[0,j]);ax.set_facecolor('#f2f3ef')
        for f in geo['features']:
            poly=shape(f['geometry']);parts=list(poly.geoms) if hasattr(poly,'geoms') else [poly]
            for p in parts:
                x,y=p.exterior.xy;ax.fill(x,y,color='#e7ebe6',zorder=0);ax.plot(x,y,color='#aab8ae',linewidth=.6,zorder=1)
        for cluster in order:
            points={(round(r['lon'],7),round(r['lat'],7)) for r in flags if r['cluster']==cluster}
            if points:
                x,y=zip(*points);ax.scatter(x,y,s=24,c=[colors[cluster]],alpha=.85,edgecolors='white',linewidths=.4,zorder=2)
        ax.set_title(f'{phase} · {len(flags):,} flagged evaluations',loc='left',fontweight='bold',fontsize=14)
        ax.set_xlim(106.42,106.88);ax.set_ylim(10.64,11.06);ax.set_aspect(1/.982)
        ax.set_xlabel('Longitude');ax.set_ylabel('Latitude')
        ax.grid(alpha=.16);ax.tick_params(labelsize=8)
    ax=fig.add_subplot(gs[0,2]);ax.set_facecolor('#faf9f6')
    y=list(range(len(order)));labels=[NAMES.get(c,c) for c in order]
    ax.barh([i-.18 for i in y],[r['before'] for r in clusters],height=.34,color=[colors[c] for c in order],label='Before')
    ax.barh([i+.18 for i in y],[r['after'] for r in clusters],height=.34,color=[colors[c] for c in order],alpha=.4,label='After')
    ax.set_yticks(y,labels,fontsize=8);ax.invert_yaxis();ax.set_xlabel('Flagged door/stop evaluations');ax.legend(frameon=False)
    ax.set_title('Root-cause review clusters',loc='left',fontweight='bold',fontsize=14)
    for spine in ['top','right']:ax.spines[spine].set_visible(False)
    foot=fig.add_subplot(gs[1,:]);foot.axis('off')
    foot.text(0,1,'600 random destinations + 31 targeted probes · 6 vehicles × park/pickup · identical frozen caches · no network',fontsize=12,weight='bold')
    foot.text(0,.52,'Flags are review candidates: cited stopping prohibitions and credible narrow cuts are retained. Coincident vehicle points are collapsed on maps.',fontsize=10)
    foot.text(0,.12,'Cached HCMC extent; 17 urban district polygons (2021). No Cần Giờ cache coverage. Software invariants and plausibility, not field accuracy.',fontsize=10,color='#555')
    fig.suptitle('Ngõ Ngách | Cached engine stress test',x=.08,y=.98,ha='left',fontsize=22,fontweight='bold')
    fig.subplots_adjust(top=.91,bottom=.05,left=.06,right=.98)
    fig.savefig(OUT/'stress-clusters.png',dpi=180,facecolor=fig.get_facecolor());plt.close(fig)


def main():
    manifest=json.loads((OUT/'stress-inputs.json').read_text())
    br,brows,bflags,bu=load('before');ar,arows,aflags,au=load('after')
    summaries={phase:json.loads((OUT/f'stress-{phase}-summary.json').read_text()) for phase in ('before','after')}
    bc=Counter(r['cluster'] for r in bflags);ac=Counter(r['cluster'] for r in aflags)
    clusters=[]
    for c in sorted(set(bc)|set(ac),key=lambda c:(-bc[c],c)):
        examples=[];seen=set()
        for r in bflags+aflags:
            if r['cluster']!=c:continue
            location=(r['lat'],r['lon'],r.get('limiting',{}).get('way_id'))
            if location in seen:continue
            seen.add(location);examples.append({'lat':r['lat'],'lon':r['lon'],'osm':example_link(r),'plan_id':r['id']})
            if len(examples)==3:break
        cause,fix=RULES.get(c,('Review required','Retain uncertainty'))
        clusters.append({'cluster':c,'name':NAMES.get(c,c),'before':bc[c],'after':ac[c],
                         'share_of_flagged_evaluations':bc[c]/len(bflags) if bflags else 0,
                         'before_unique_plans':len({r['id'] for r in bflags if r['cluster']==c}),
                         'actionable':c in ACTIONABLE,'examples':examples,'hypothesis':cause,'fix':fix})
    pool=[r for r in arows if r['cohort']=='random' and r['stops']]
    random.Random(17015).shuffle(pool);examples=[];seen=set()
    for r in pool:
        if r['i'] in seen:continue
        seen.add(r['i']);st=r['stops'][0];wid=st['way_id']
        name=st['name']
        if name=='Trước cửa nhà':
            g=s.osm.graph_from_elements(r['lat'],r['lon'],json.loads((s.FROZEN/('demo_binhthanh.json' if r['key']=='demo' else f"area_{r['key']}.json")).read_text())['elements'])
            name=g.display_name(wid)
        examples.append({'point_id':r['i'],'name':name,'district':r['district'],'lat':r['lat'],'lon':r['lon'],
                         'vehicle':r['vehicle_id'],'intent':r['intent'],'verdict':r['verdict']['headline'],
                         'answer':r['verdict']['estimate']['answer'],'confidence':r['verdict']['estimate']['confidence'],
                         'basis':r['verdict']['estimate']['basis'],'osm_url':f'https://www.openstreetmap.org/way/{wid}' if wid else f"https://www.openstreetmap.org/?mlat={r['lat']}&mlon={r['lon']}"})
        if len(examples)==15:break
    validation={}
    for phase,rows,flags in [('before',brows,bflags),('after',arows,aflags)]:
        validation[phase]={'plans':len(rows),'destinations':len({r['i'] for r in rows}),
            'flag_counts':dict(Counter(f for r in flags for f in r['flags'])),
            'flagged_evaluations':len(flags),'flagged_unique_plans':len({r['id'] for r in flags}),
            'actionable_evaluations':sum(r['cluster'] in ACTIONABLE for r in flags),
            'invariants':dict(Counter(k for r in rows for k in r.get('invariants',[]))),
            'exceptions':sum('error' in r for r in rows),
            'random_verdict_answers':dict(Counter(r.get('verdict',{}).get('estimate',{}).get('answer','exception') for r in rows if r['cohort']=='random')),
            'by_intent_latency_s':{intent:s.quantiles([r['seconds'] for r in rows if r['intent']==intent]) for intent in ('park','pickup')},
            'latency_s':s.quantiles([r['seconds'] for r in rows])}
    report={'seed':manifest['seed'],'design':{k:v for k,v in manifest.items() if k not in ('points','sources_before','frozen_files_sha256')},
            'sampling_counts':dict(Counter(p['sampling'] for p in manifest['points'] if p['cohort']=='random')),
            'district_destinations':dict(Counter(p['district'] for p in manifest['points'] if p['cohort']=='random')),
            'selected_cells':len({p['key'] for p in manifest['points']}),'validation':validation,'clusters':clusters,
            'unknown':{'before':bu,'after':au},'examples':examples,'flagged_plans':{'before':bflags,'after':aflags},
            'source_hashes':{phase:summaries[phase]['source_sha256_start'] for phase in summaries},
            'frozen_inputs_unchanged':all(s.sha(s.FROZEN/name)==digest for name,digest in manifest['frozen_files_sha256'].items())}
    s.write(OUT/'stress-test.json',report)
    plot(bflags,aflags,clusters)
    lines=['# Ngõ Ngách cached-engine stress test — 17 October 2026','',
        'No commits, Gemini, Goong, Overpass, portal requests, server restarts or cache edits. Socket connections are denied in the harness. '
        'The existing live server on :8787 needs a restart to load these Python changes; it was left running unchanged.','',
        f"**{len(manifest['points'])} destinations × six vehicles × both intents = {len(arows):,} plans per phase.** "
        f"600 random destinations use the full {manifest['all_cached_cells_in_pool']:,}-cell routing-key pool; {report['selected_cells']} distinct cells were selected. "
        '31 targeted probes are reported separately from the random cohort. VF 3, Vios, class-m, Fortuner, Carnival and Transit; park 120 minutes, pickup 15 minutes, arrival 2026-10-17 09:31 +07.','',
        'Random mix: '+', '.join(f'{k} {v}/600 ({v/6:.1f}%)' for k,v in report['sampling_counts'].items())+'. '
        'For road samples, choose a random eligible way then a random node in its cell. Off-road samples are random cell-interior points at least 8 m from a mapped node; they are block probes, not verified building entrances. '
        '21 represented district strata use 17 cached 2021 urban polygons and explicit nearest-centroid labels outside their extent. No Cần Giờ cells are cached. '
        'Adjacent overlapping cells are not independent field observations.','',
        'Reproduction: `PYTHONPATH=backend:. python3 pipelines/stress_cached_engine.py freeze --n 600 --seed 171026`, then `run --phase before --workers 6` on the original engine and `run --phase after --workers 6` after changes; '
        '`PYTHONPATH=backend:. python3 pipelines/stress_cached_report.py`. Frozen input SHA-256s are in [stress-inputs.json](stress-inputs.json); immutable copies are under `tmp/stress-frozen/`. '
        'Each destination has cold process-local area evidence, so request history cannot blend overlapping observations. Workers import the engine once before forking; the baseline continues using its original imported code while edits are developed. '
        'All other cached evidence keeps production flags; no new inference runs. Raw full-plan summaries and feature vectors are in `stress-{before,after}.jsonl`, with aggregate [JSON](stress-test.json).','',
        '## Reported Trần Doãn Khanh failure','',
        'Reproduced `no / medium` at (10.7889312, 106.6975450), class-m, park 120 minutes. '
        'The 1.5 m is **not a cadastral cut**. [Nguyễn Thành Ý, way 1185234990](https://www.openstreetmap.org/way/1185234990) has eleven failed cuts and zero usable samples. '
        'Its unresolved Official `[0,40]` survey was fused with a residential `[3.5,15]` prior to `[0,15]`; the old midpoint `(0+min(15,3))/2` invented 1.5 m and retained the Official badge. '
        '[Trần Doãn Khanh, way 35115025](https://www.openstreetmap.org/way/35115025) has five valid usable samples 5.56–5.65 m. '
        'The strict lower bound is zero because its 32.08 m destination-prefix survey does not certify the whole OSM way (D36), not because any sample is zero.','',
        'After: **fits / medium**, still unverified. Basis names [Cây Điệp, way 35113132](https://www.openstreetmap.org/way/35113132), whose ten samples have a 3.58 m bottleneck. '
        'Trần Doãn Khanh exposes a separate sampled range 5.26–5.86 m; the strict interval and legal/flood/turning caveats remain. '
        'See [before](stress-known-before.json), [route provenance](stress-known-route-before.json), and [after](stress-known-after.json).','',
        '## Ranked causal clusters','',
        'Counts below are flagged door/first-stop evaluations, not field-confirmed defects or independent locations. '
        'One plan may flag both door and alternative stop; each evaluation is assigned one primary cluster. '
        'Shares use all baseline flagged evaluations. Deterministic rules use causal evidence and geometry; k-means/HDBSCAN would mix vehicle duplicates and legitimate legal negatives without adding causal information.','',
        '| Cluster | Before → after | Baseline share | 2–3 map examples | Root cause / action |',
        '|---|---:|---:|---|---|']
    for c in clusters:
        links='<br>'.join(e['osm'] for e in c['examples'])
        lines.append(f"| {c['name']} | {c['before']} → {c['after']} | {c['share_of_flagged_evaluations']:.1%} | {links} | {c['hypothesis']} {c['fix']} |")
    lines += ['', '![Failure clusters and before/after sizes](stress-clusters.png)','',
        'Every flag carries implausibility classes, limiting way/tags, district and its assignment method, cut-to-junction distance, cut/way lengths and ratio, '
        'cut count, evidence tiers, vehicle size, door/stop scope, sample-supported coverage fraction, cell-boundary crossing and basis source. '
        'Null geometry means the cache contains no cut/location; it is not encoded as a zero-distance cut. '
        'Automatic cuts are geometry-revalidated before bottleneck fusion. MAD marks an isolated low cut for confidence review; it never deletes a credible constriction solely for being narrow. '
        'Two independent cut centres at least 1 m apart, with widths within 0.6 m of the bottleneck (twice the existing ±0.3 m allowance), support a confident automatic negative. These thresholds remain modelling assumptions.','',
        '## Implausibility and invariant counts','', '| Class | Before | After |','|---|---:|---:|']
    for key in sorted(set(validation['before']['flag_counts'])|set(validation['after']['flag_counts'])):
        lines.append(f"| {key} | {validation['before']['flag_counts'].get(key,0)} | {validation['after']['flag_counts'].get(key,0)} |")
    for phase,v in validation.items():
        q=v['latency_s'];lines+=['',f"{phase.title()}: {v['exceptions']} exceptions; invariant failures {v['invariants'] or 'none'}. "
            f"Latency under six-worker contention: p50 **{q['p50']:.3f} s**, p95 **{q['p95']:.3f} s**, max **{q['max']:.3f} s**. "
            f"{v['flagged_unique_plans']} unique flagged plans / {v['flagged_evaluations']} evaluations; {v['actionable_evaluations']} evaluations in actionable clusters."]
    lines += ['', f"All twelve answers unknown at a destination: {len(bu['all_twelve_unknown_destinations'])} → {len(au['all_twelve_unknown_destinations'])}. "
        'Longest per-vehicle/intent consecutive streaks (destination-index order, not geographic adjacency) and exact IDs are in the JSON. '
        'Missing graph coverage stays unknown; prevalence is not improved by fabricating fit or route evidence.','',
        '## Fifteen seeded random map spot-checks','',
        'Way names below come from cached OSM, not geocoded house numbers. The coordinate is the requested destination; the verdict/basis describe the chosen stop.','',
        '| Way / destination | Vehicle · intent | Verdict · confidence | Basis |',
        '|---|---|---|---|']
    for e in examples:
        lines.append(f"| [{e['name']}]({e['osm_url']}) · {e['district']} · {e['lat']:.6f}, {e['lon']:.6f} | {e['vehicle']} · {e['intent']} | {e['answer']} · {e['confidence']} | {e['basis']} |")
    lines += ['', '## Validation, changes and restart','',
        'Backend regression results: [stress-backend-tests.txt](stress-backend-tests.txt). Frozen original 300-destination/five-vehicle audit: [stress-audit-summary.json](stress-audit-summary.json). '
        'The regression fixtures freeze the reported case plus at least ten extreme real cached examples; synthetic tests independently enforce no false clearance guarantee, retention of a credible constriction, source attribution, and independent cut support.','',
        'Changed: `backend/app/plan.py`, `backend/app/evidence.py`, new `backend/app/width_samples.py`, `backend/tests/test_engine_stress.py`, '
        '`pipelines/stress_cached_engine.py`, `pipelines/stress_cached_report.py`, decision-log entries and these eval artifacts. '
        'No search/place/reverse functions were edited. No commit was created.','',
        'Restart is needed to load the Python modules. Do **not** run a second listener while the old process holds :8787. '
        'The exact start command from [STATUS-2026-10-17.md](../STATUS-2026-10-17.md), after the current server is stopped by its owner:','',
        '```sh','cd /Users/khoivo/Developer/mlai-car-access',
        'AGENT_ALLOW_PAID=1 AGENT_PAID_LIMIT_USD=3.00 AGENT_FREE_CALL_LIMIT=0 \\',
        'AGENT_FREE_MODEL=gemini-2.5-flash \\',
        'AGENT_PAID_ENDPOINT=https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-3.5-flash:generateContent \\',
        'PYTHONPATH=backend python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787','```','',
        'The status document advises 2–3 minutes of warm-up. No server was restarted during this work. '
        'These results establish software invariants and explain cached-data plausibility defects; they do not establish field accuracy, present-day curb legality or continuous surveyed clearance.','']
    (OUT/'stress-test.md').write_text('\n'.join(lines))
    print(json.dumps({'validation':validation,'clusters':[(c['cluster'],c['before'],c['after']) for c in clusters]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()

"""Offline self-contained research summary; OSM geometry only, no remote basemap."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/eval/official-bulk.html'

def main():
    validation=json.loads((ROOT/'docs/eval/official-bulk-validation.json').read_text())
    product=json.loads((ROOT/'backend/cache/live/official_widths.json').read_text())
    inventory=json.loads((ROOT/'backend/cache/live/evidence_inventory.json').read_text())['ways']
    cad=json.loads((ROOT/'data/raw/official_bulk/cadastral_snapshot.json').read_text())
    datasets=[]
    for wid,claims in product['ways'].items():
        if wid not in inventory:continue
        s={r['source_id'] for r in claims};kind='both' if len(s)>1 else 'q9' if 'q9_2009' in s else 'hcmgis'
        datasets.append((inventory[wid]['coords'],kind,inventory[wid]['tags'].get('name') or 'OSM '+wid))
    points=[(c['lon'],c['lat']) for cuts in cad['ways'].values() for c in cuts]
    coords=[p for cs,_,_ in datasets for p in cs]+points
    xmin,xmax=min(p[0] for p in coords),max(p[0] for p in coords)
    ymin,ymax=min(p[1] for p in coords),max(p[1] for p in coords)
    def project(p):return (28+(p[0]-xmin)/(xmax-xmin)*644,315-(p[1]-ymin)/(ymax-ymin)*290)
    paths=[]
    for cs,kind,name in datasets:
        d='M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in map(project,cs))
        paths.append(f'<path class="way {kind}" d="{d}"><title>{html.escape(name)}</title></path>')
    for p in points:
        x,y=project(p);paths.append(f'<circle class="reference" cx="{x:.1f}" cy="{y:.1f}" r="1.6"/>')
    table=[('Quận 9 gazette PDF','935 rows · 2009','165 ways','Historical base width + planned ROW'),
           ('HCMGIS public WFS','355 lines · 2021','143 ways','Dated road width; definition unverified'),
           ('Cadastral reference','213 city / 244 with areas','0 overlaps','Agreement and error: N/A'),
           ('New DPA ArcGIS app','Public raster map','401 for features','Authorised account / formal request')]
    rows=''.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in r)+'</tr>' for r in table)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Official bulk width research</title>
<style>
body{margin:0;color:var(--foreground,#182b35);font:14px/1.55 var(--font-sans,system-ui);background:transparent}h1{font-size:24px;line-height:1.2;font-weight:650;margin:0 0 10px}p{margin:8px 0 16px}.muted{color:var(--muted-foreground,#657880)}.numbers{display:grid;grid-template-columns:1fr 1fr;gap:22px;margin:22px 0;border-block:1px solid var(--border,#d9e0e4);padding:18px 0}.n{font-size:38px;line-height:1.1;font-weight:650;font-variant-numeric:tabular-nums}.n small{display:block;font-size:13px;font-weight:400;margin-top:8px}.n:last-child{color:var(--warning,#b35c00)}h2{font-size:16px;font-weight:650;margin:20px 0 8px}svg{width:100%;height:340px;display:block;background:var(--muted,#f1f4f5);border-radius:var(--radius,8px)}.way{fill:none;stroke-width:1.8;stroke-linecap:round;opacity:.85}.q9{stroke:#287ab5}.hcmgis{stroke:#d28b19}.both{stroke:#8c59b9;stroke-width:2.4}.reference{fill:#4e6572;opacity:.45}.legend{display:flex;flex-wrap:wrap;gap:7px 15px;margin:10px 0}.dot{display:inline-block;width:9px;height:9px;border-radius:9px;margin-right:6px}.filters{display:flex;gap:7px;margin:12px 0}button{font:inherit;padding:5px 11px;border-radius:5px;border:1px solid var(--border,#d9e0e4);color:inherit;background:transparent;cursor:pointer}button[aria-pressed=true]{background:var(--accent-surface,#dfedf5)}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.45}td,th{border-bottom:1px solid var(--border,#d9e0e4);padding:10px 9px 10px 0;text-align:left;vertical-align:top}th{color:var(--muted-foreground,#657880);font-weight:500}td:first-child{font-weight:600}a{color:var(--accent,#287ab5)}.note{font-size:12px;color:var(--muted-foreground,#657880)}@media(max-width:450px){h1{font-size:21px}.n{font-size:31px}table{font-size:11px}td,th{padding-right:5px}.filters{gap:4px}button{font-size:12px}}
</style><body><p class="muted">NGÕ NGÁCH · RESEARCH SNAPSHOT · 17 OCT 2026</p><h1>Real bulk sources. Partial, dated coverage.</h1><p>No verified open, current citywide Clear Width dataset was found. Official historical road widths and planned lộ giới have been imported separately from vehicle-fit Evidence.</p>
<div class="numbers"><div class="n">295<small>OSM ways with new Official metadata<br>192 named or tagged alleys</small></div><div class="n">0<small>new ways with current Clear Width<br>metadata never changes vehicle-fit bounds</small></div></div>
<h2>Imported metadata and the existing cadastral reference</h2><p class="note">The sources are east of the saved reference. No overlapping ways means no defensible agreement estimate.</p><div class="filters"><button data-kind="all" aria-pressed="true">All sources</button><button data-kind="q9" aria-pressed="false">Quận 9 · 2009</button><button data-kind="hcmgis" aria-pressed="false">HCMGIS · 2021</button></div>
<svg viewBox="0 0 700 340" role="img" aria-label="Cached OSM ways carrying official dated metadata and the separate existing cadastral reference, with no validation overlap">__PATHS__<text x="28" y="333" fill="currentColor" font-size="10">West: __WEST__° E</text><text x="560" y="333" fill="currentColor" font-size="10">East: __EAST__° E</text><text x="32" y="19" fill="currentColor" font-size="10">North ↑ · relative geographic positions</text></svg>
<div class="legend"><span><i class="dot" style="background:#287ab5"></i>Q9 only</span><span><i class="dot" style="background:#d28b19"></i>HCMGIS only</span><span><i class="dot" style="background:#8c59b9"></i>Both (13 ways)</span><span><i class="dot" style="background:#4e6572"></i>Cadastral cuts</span></div><p class="note">OSM road geometry © OpenStreetMap contributors, ODbL. Diagram has independent axis scales; no remote basemap or official WFS geometry is embedded.</p>
<h2>What each source can support</h2><table><thead><tr><th>Source</th><th>Snapshot</th><th>Correspondence</th><th>Use / next step</th></tr></thead><tbody>__ROWS__</tbody></table>
<p class="note">Q9: 139/935 rows matched. HCMGIS: 109/355 source lines matched. WFS access constraints say NONE, but no explicit redistribution licence was found. Current cadastral agreement is N/A. All 295 ways replayed with zero changes to their current widths or other Evidence.</p><p><strong>Human follow-up:</strong> request an authorised city GIS export/account, HCMGIS field definitions and reuse terms, and the missing district annexes. Five Vietnamese request drafts are saved; none was sent.</p><p class="note">29 candidates audited · 95 backend tests passed · No point-portal requests · No Gemini · No commit</p>
<script>document.querySelectorAll('button[data-kind]').forEach(b=>b.onclick=()=>{let k=b.dataset.kind;document.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));document.querySelectorAll('.way').forEach(p=>p.style.display=k==='all'||p.classList.contains(k)||p.classList.contains('both')?'':'none')});console.log('summary ready; ways: __COUNT__; external requests: 0');</script></body></html>'''
    page=page.replace('__PATHS__',''.join(paths)).replace('__ROWS__',rows).replace('__WEST__',f'{xmin:.3f}').replace('__EAST__',f'{xmax:.3f}').replace('__COUNT__',str(len(datasets)))
    OUT.write_text(page);print(OUT)

if __name__=='__main__':main()
